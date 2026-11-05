from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, replace

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import (
    create_search,
    dumps,
    finish_search,
    refresh_search_counters,
    save_audit,
    save_competitors,
    upsert_lead_with_outcome,
    upsert_search_membership,
)
from local_presence_miner.database.schema import CompetitorRecord, Lead, LeadSearch, SearchRunLead
from local_presence_miner.database.search_run_control import (
    DEFAULT_SEARCH_LEASE_SECONDS,
    DatabaseSearchLease,
    SearchLeaseLostError,
    database_search_is_running,
    reconcile_interrupted_search_runs,
    try_acquire_database_search_lease,
)
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.domain.models import BusinessProfile, SearchCriteria, WebsiteAudit
from local_presence_miner.domain.scoring import score_lead
from local_presence_miner.services.adaptive_sales_asset_service import refresh_adaptive_sales_assets
from local_presence_miner.services.competitor_service import CompetitorService
from local_presence_miner.services.demo_data import demo_audit, load_demo_businesses
from local_presence_miner.services.google_places import GooglePlacesClient, GooglePlacesError
from local_presence_miner.services.google_presence_service import GooglePresenceService
from local_presence_miner.services.mockup_service import MockupService
from local_presence_miner.services.pagespeed import PageSpeedClient
from local_presence_miner.services.preflight_service import PreflightService
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.rendered_auditor import RenderedAuditor
from local_presence_miner.services.report_service import safe_filename
from local_presence_miner.services.search_visibility_service import (
    demo_visibility_acquisition,
    failed_visibility_acquisition,
    link_visibility_observation,
    persist_visibility_acquisition,
)
from local_presence_miner.services.website_auditor import WebsiteAuditor
from local_presence_miner.time_utils import utc_now


class SearchAlreadyRunningError(RuntimeError):
    """Raised when a second workflow targets the same database concurrently."""


@contextmanager
def _single_flight(
    session_factory: sessionmaker[Session],
    lease_seconds: float,
) -> Iterator[DatabaseSearchLease]:
    lease = try_acquire_database_search_lease(
        session_factory,
        lease_seconds=lease_seconds,
    )
    if lease is None:
        raise SearchAlreadyRunningError("A search is already running for this MarketLens Local database.")
    try:
        yield lease
    finally:
        lease.release()


class SearchWorkflow:
    def __init__(
        self,
        config: AppConfig,
        session_factory: sessionmaker[Session],
        *,
        lease_seconds: float = DEFAULT_SEARCH_LEASE_SECONDS,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds
        self._active_lease: DatabaseSearchLease | None = None
        self._audit_errors: dict[str, str] = {}

    @classmethod
    def is_running(cls, session_factory: sessionmaker[Session]) -> bool:
        return database_search_is_running(session_factory)

    def run(self, criteria: SearchCriteria) -> int:
        with _single_flight(self.session_factory, self.lease_seconds) as lease:
            self._active_lease = lease
            try:
                reconcile_interrupted_search_runs(self.session_factory)
                return self._run_single(criteria)
            finally:
                self._active_lease = None

    def _run_single(self, criteria: SearchCriteria) -> int:
        search_id: int | None = None
        errors: list[str] = []
        try:
            if not criteria.demo_mode:
                preflight = PreflightService().run(
                    self.config,
                    live_search=True,
                    rendered_requested=criteria.run_rendered_audit,
                    pagespeed_requested=criteria.run_pagespeed,
                )
                if not preflight.ready:
                    detail = "; ".join(f"{item.label}: {item.detail}" for item in preflight.blocking)
                    raise RuntimeError("Preflight failed: " + detail)
            if criteria.safe_live_test and not criteria.demo_mode:
                criteria = replace(criteria, max_results=min(criteria.max_results, 5), top_mockups=0)

            self._heartbeat_search_lease()
            with self.session_factory() as session:
                search = create_search(session, criteria)
                self._require_search_lease().bind_search(session, search.id)
                session.commit()
                search_id = search.id

            try:
                if criteria.demo_mode:
                    acquisition = demo_visibility_acquisition(criteria, load_demo_businesses(criteria))
                else:
                    acquisition = GooglePlacesClient(
                        self.config.google_maps_api_key,
                        self.config.request_timeout_seconds,
                    ).search_with_visibility(criteria)
            except GooglePlacesError as exc:
                with self.session_factory() as session:
                    persist_visibility_acquisition(
                        session,
                        search_id,
                        criteria,
                        exc.acquisition or failed_visibility_acquisition(criteria, str(exc)),
                    )
                    session.commit()
                raise
            profiles = list(acquisition.profiles)

            with self.session_factory() as session:
                probe = persist_visibility_acquisition(session, search_id, criteria, acquisition)
                probe_id = probe.id
                session.commit()

            self._heartbeat_search_lease()
            profiles = [
                replace(
                    profile,
                    place_id=profile.place_id.strip()
                    if isinstance(profile.place_id, str)
                    else "",
                )
                if not isinstance(profile.place_id, str)
                or profile.place_id != profile.place_id.strip()
                else profile
                for profile in profiles
            ]
            candidate_contexts: list[tuple[BusinessProfile, str]] = []

            with self.session_factory() as session:
                active_search = session.get(LeadSearch, search_id)
                if active_search is None:
                    raise RuntimeError("The active Search Run record disappeared.")
                active_search.total_candidates = len(profiles)
                for order, profile in enumerate(profiles, start=1):
                    membership = upsert_search_membership(
                        session,
                        search_id,
                        candidate_place_id=profile.place_id,
                        candidate_name=profile.name,
                        discovery_order=order,
                        search_position=profile.search_position,
                    )
                    candidate_contexts.append((profile, membership.candidate_place_id))
                session.commit()

            valid_profiles = [profile for profile, _key in candidate_contexts if profile.place_id]
            if criteria.demo_mode:
                audits = {profile.place_id: demo_audit(profile) for profile in valid_profiles}
                self._audit_errors = {}
            else:
                audits = self._run_audits(valid_profiles, criteria)

            self._heartbeat_search_lease()
            competitor_service = CompetitorService()
            profile_lookup = {profile.place_id: profile for profile in valid_profiles}
            for profile, membership_key in candidate_contexts:
                self._heartbeat_search_lease()
                if not profile.place_id:
                    errors.append(
                        self._record_local_failure(
                            search_id,
                            membership_key,
                            profile.name,
                            "Missing canonical Google Place ID; candidate cannot be added to the canonical Lead table.",
                        )
                    )
                    continue
                audit_error = self._audit_errors.get(profile.place_id)
                if audit_error:
                    errors.append(self._record_local_failure(search_id, membership_key, profile.name, audit_error))
                    continue
                try:
                    competitors = competitor_service.match_one(profile, valid_profiles, audits)
                    competitor_average = competitor_service.average_website_score(competitors, profile_lookup, audits)
                    score = score_lead(profile, audits[profile.place_id], competitor_average)
                    notes = "; ".join(score.target_signals)
                    with self.session_factory() as session:
                        membership = self._membership(session, search_id, membership_key)
                        outcome = upsert_lead_with_outcome(session, profile, search_id, score, notes=notes)
                        lead = outcome.lead
                        if outcome.is_new:
                            lead.status = LeadStatus.NEEDS_REVIEW.value
                        lead.target_zip_code = criteria.target_zip_code
                        lead.target_radius_miles = criteria.target_radius_miles
                        refresh_failed = bool(profile.raw.get("details_error")) and not profile.google_details_retrieved
                        if not (refresh_failed and lead.audit is not None):
                            save_audit(session, lead.id, audits[profile.place_id])
                        existing_competitors = list(session.scalars(
                            select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)
                        ))
                        if not (refresh_failed and existing_competitors):
                            save_competitors(session, lead.id, competitors, profile_lookup)
                        session.flush()
                        GooglePresenceService().evaluate_and_store(session, lead)
                        QualificationService().evaluate_and_store(session, lead)
                        competitor_records = list(session.scalars(
                            select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)
                        ))
                        if profile.google_details_retrieved:
                            refresh_adaptive_sales_assets(
                                session,
                                lead,
                                self.config.sender,
                                competitors=competitor_records,
                                city=criteria.city,
                                state_region=criteria.state_region,
                            )
                        lead.score_breakdown_json = dumps([asdict(factor) for factor in score.factors])
                        membership.lead_id = lead.id
                        link_visibility_observation(
                            session,
                            probe_id,
                            profile.place_id,
                            lead_id=lead.id,
                            search_run_lead_id=membership.id,
                        )
                        membership.discovery_kind = "new" if outcome.is_new else "rediscovered"
                        membership.processing_status = "Succeeded"
                        membership.score_context_json = dumps({
                            "lead_score": score.total,
                            "priority": score.priority,
                            "target_signals": score.target_signals,
                        })
                        membership.error_summary = ""
                        membership.processed_at = utc_now()
                        current_search = refresh_search_counters(session, search_id)
                        if current_search is not None:
                            current_search.last_candidate = profile.name
                        # Per-lead durable checkpoint.
                        session.commit()
                except SQLAlchemyError:
                    raise
                except Exception as exc:  # noqa: BLE001 - a candidate-local failure must not end the run
                    detail = f"{exc.__class__.__name__}: {exc}"
                    errors.append(self._record_local_failure(search_id, membership_key, profile.name, detail))

            self._heartbeat_search_lease()
            if criteria.top_mockups:
                with self.session_factory() as session:
                    top_leads = list(session.scalars(
                        select(Lead)
                        .join(SearchRunLead, SearchRunLead.lead_id == Lead.id)
                        .where(
                            SearchRunLead.search_id == search_id,
                            SearchRunLead.processing_status == "Succeeded",
                        )
                        .order_by(Lead.sales_priority_score.desc(), Lead.lead_score.desc())
                        .limit(criteria.top_mockups)
                    ))
                mockups = MockupService(self.config)
                for lead in top_leads:
                    try:
                        mockups.generate_mockup(lead)
                    except Exception as exc:  # noqa: BLE001 - artifact failure is recorded, not hidden
                        errors.append(f"Mockup for {lead.name}: {exc.__class__.__name__}: {exc}")

            with self.session_factory() as session:
                self._heartbeat_search_lease()
                refresh_search_counters(session, search_id)
                state = "Completed With Errors" if errors else "Completed"
                finish_search(session, search_id, state, errors=errors)
                session.commit()
            return search_id
        except Exception as exc:
            if search_id is not None and not isinstance(exc, SearchLeaseLostError):
                errors.append(f"Run stopped: {exc.__class__.__name__}: {exc}")
                try:
                    with self.session_factory() as session:
                        stopped_search = refresh_search_counters(session, search_id)
                        state = "Partial" if stopped_search is not None and stopped_search.succeeded_count else "Failed"
                        finish_search(session, search_id, state, errors=errors)
                        session.commit()
                except Exception:
                    # The original systemic failure is the truthful exception.
                    pass
            raise

    def _require_search_lease(self) -> DatabaseSearchLease:
        if self._active_lease is None:
            raise RuntimeError("Search Workflow does not own a database search lease.")
        return self._active_lease

    def _heartbeat_search_lease(self) -> None:
        self._require_search_lease().heartbeat()

    def _membership(self, session: Session, search_id: int, place_id: str) -> SearchRunLead:
        return session.execute(
            select(SearchRunLead).where(
                SearchRunLead.search_id == search_id,
                SearchRunLead.candidate_place_id == place_id,
            )
        ).scalar_one()

    def _record_local_failure(self, search_id: int, place_id: str, name: str, detail: str) -> str:
        summary = f"{name}: {detail}"[:1200]
        with self.session_factory() as session:
            membership = self._membership(session, search_id, place_id)
            membership.processing_status = "Failed"
            membership.error_summary = detail[:1000]
            membership.processed_at = utc_now()
            search = refresh_search_counters(session, search_id)
            if search is not None:
                search.last_candidate = name
            session.commit()
        return summary

    def _run_audits(self, profiles, criteria: SearchCriteria):
        self._audit_errors = {}

        def raw(profile):
            if not profile.google_details_retrieved and not profile.website:
                return WebsiteAudit(weaknesses=["Website was not requested because rich Google details are unavailable."])
            return WebsiteAuditor(
                self.config.request_timeout_seconds,
                self.config.request_delay_seconds,
            ).audit(profile.website)

        workers = max(1, min(int(self.config.audit_concurrency), 4))
        audits: dict[str, WebsiteAudit] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(raw, profile): profile for profile in profiles}
            for future in as_completed(futures):
                profile = futures[future]
                try:
                    audits[profile.place_id] = future.result()
                except Exception as exc:  # noqa: BLE001 - retained as candidate-local evidence
                    self._audit_errors[profile.place_id] = f"Website audit failed: {exc.__class__.__name__}: {exc}"
                    audits[profile.place_id] = WebsiteAudit(
                        weaknesses=["Website audit failed before evidence could be collected."]
                    )

        pagespeed = PageSpeedClient(self.config.pagespeed_api_key, max(self.config.request_timeout_seconds, 15))
        rendered = RenderedAuditor(max(self.config.request_timeout_seconds, 15))
        for profile in profiles:
            if profile.place_id in self._audit_errors:
                continue
            try:
                audit = audits[profile.place_id]
                metrics = dict(audit.metrics)
                pagespeed_status = "not_run"
                if criteria.run_pagespeed:
                    pagespeed_result = pagespeed.run(profile.website)
                    pagespeed_status = str(pagespeed_result.pop("pagespeed_status", "failed"))
                    metrics.update({
                        key if key.startswith("pagespeed_") else f"pagespeed_{key}": value
                        for key, value in pagespeed_result.items()
                    })

                rendered_status = "not_run"
                rendered_checks: dict[str, bool] = {}
                evidence = dict(audit.evidence)
                desktop_screenshot = ""
                mobile_screenshot = ""
                if criteria.run_rendered_audit:
                    screenshot_dir = (
                        self.config.output_dir / "screenshots" / safe_filename(criteria.output_name)
                        / safe_filename(profile.place_id)
                    )
                    rendered_result = rendered.audit(profile.website, screenshot_dir, criteria.generate_screenshots)
                    rendered_status = rendered_result.status
                    rendered_checks = rendered_result.checks
                    evidence.update({
                        f"rendered_{key}": source for key, source in rendered_result.evidence.items()
                    })
                    desktop_screenshot = rendered_result.desktop_screenshot
                    mobile_screenshot = rendered_result.mobile_screenshot
                    if rendered_result.error:
                        metrics["rendered_error"] = rendered_result.error

                audits[profile.place_id] = replace(
                    audit,
                    metrics=metrics,
                    rendered_checks=rendered_checks,
                    evidence=evidence,
                    pagespeed_status=pagespeed_status,
                    rendered_status=rendered_status,
                    desktop_screenshot=desktop_screenshot,
                    mobile_screenshot=mobile_screenshot,
                )
            except Exception as exc:  # noqa: BLE001 - retained as candidate-local evidence
                self._audit_errors[profile.place_id] = (
                    f"Audit enrichment failed: {exc.__class__.__name__}: {exc}"
                )
        return audits
