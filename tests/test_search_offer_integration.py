"""Adversarial Search Market → commercial intelligence contract tests."""

from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
from sqlalchemy import select

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import log_activity, save_outreach_draft
from local_presence_miner.database.schema import (
    ContactInteraction,
    GooglePresenceAssessment,
    Lead,
    LeadSearch,
    OfferHistory,
    OutreachDraft,
    SearchMarketRun,
    SearchVisibilityProbe,
    SellerProfile,
    WebsiteAuditRecord,
)
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.domain.models import SearchCriteria, SearchVisibilityAcquisition, VisibilityObservationCapture
from local_presence_miner.domain.offer_presentation import PRESENTATIONS
from local_presence_miner.domain.offer_registry import OFFER_REGISTRY_VERSION, OfferID, offer_definition
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_plan_service import build_current_offer_context
from local_presence_miner.services.commercial_state_service import (
    current_plan_dependency_errors,
    draft_commercial_errors,
    persist_current_plan,
    recompute_lead_commercial_candidate,
)
from local_presence_miner.services.conversation_state_service import SUBJECT_BUSINESS_GOAL, ConversationStateService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.search_market_analysis import project_search_market
from local_presence_miner.services.search_market_service import SearchMarketService, reconcile_interrupted_search_market_runs
from local_presence_miner.services.search_offer_intelligence import (
    accept_advisory_offer,
    findings_for_lead,
    fuse_offer,
    recommend_actual_businesses,
    recommend_business_types,
)
from local_presence_miner.time_utils import utc_now
from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
from local_presence_miner.ui.widgets.search_market_widget import SearchMarketDetailDialog, SearchMarketWidget

CONTACT_REPAIR_CHECKS = {
    "https": True, "viewport": True, "tap_to_call": False, "contact_form": False,
    "sitewide_contact_path": False, "clear_primary_cta": False,
    "service_pages": True, "trust_signals": True, "indexable_sample": True,
}
CONTACT_REPAIR_SCOPE = ("mobile call/quote button", "homepage CTA rewrite")


def _setup(tmp_path, *, offer_id="one_page_conversion_site", signals=(), google=False, website=True,
           checks=None, human_selected=False, profile_gap=True):
    config = AppConfig(tmp_path, tmp_path / "market.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        parent = LeadSearch(name="Denver pest search", city="Denver", state_region="CO", niche="pest control")
        session.add(parent)
        session.flush()
        lead = Lead(
            search_id=parent.id,
            place_id="target", name="Target Pest", category="pest control",
            website="https://target.example" if website else "",
            recommended_offer_id=offer_id, recommended_offer=offer_id,
            offer_resolution_state="canonical_id", status="New",
            target_signals_json=json.dumps(list(signals)),
        )
        session.add(lead)
        session.flush()
        if google:
            # An assessment summary is not independent public evidence. Record
            # the actual rich observation and its current acquisition timestamp.
            lead.google_public_data_json = '{"details_retrieved":true}'
            lead.google_retrieved_at = lead.last_rich_google_retrieved_at = utc_now().isoformat()
            lead.has_hours = not profile_gap
            lead.photo_count = 12
            lead.rating = 4.8
            lead.review_count = 100
            session.add(GooglePresenceAssessment(
                lead_id=lead.id, confidence="Moderate", observed_gaps_json='["Public hours need review"]',
                recommended_action="Google Presence-only", generated_at=utc_now(),
            ))
        if checks is not None:
            session.add(WebsiteAuditRecord(
                lead_id=lead.id, url=lead.website, final_url=lead.website, reachable=True, status_code=200,
                checks_json=json.dumps(checks), created_at=utc_now(),
                evidence_json=json.dumps({"pages_sampled": lead.website}),
            ))
        if human_selected:
            log_activity(session, "offer_selected", json.dumps({"offer_id": offer_id}), lead.id)
        session.commit()
        lead_id = lead.id
    return config, factory, lead_id


def _assert_no_consumed_search_refs(context):
    assert context.offer_fusion["findings"] == ()
    assert not any(ref.startswith(("run:", "probe:")) for ref in context.intervention_assessment["evidence_refs"])


def _run(config, factory, *, mode="absent", demo=False, query_limit=8):
    criteria = SearchCriteria("Denver", "CO", "pest control", radius_meters=round(10 * 1609.344), demo_mode=demo)

    def capture(query, request):
        rows = [VisibilityObservationCapture(1, 1, 1, "comp-a", "Competitor A", retained_position=1)]
        if mode == "present":
            rows.append(VisibilityObservationCapture(2, 1, 2, "target", "Target Pest", retained_position=2))
        return SearchVisibilityAcquisition(
            source="demo_fixture" if demo else "google_places_text_search", query_text=query.query_text,
            resolved_latitude=39.7, resolved_longitude=-104.9,
            radius_meters=request.radius_meters, requested_result_limit=request.max_results,
            collection_status="demo" if demo else "complete", truncated=mode == "truncated",
            page_count=1, raw_result_count=len(rows), retained_result_count=len(rows),
            selected_result_count=0, observed_at=utc_now(), profiles=(), observations=tuple(rows),
        )

    return SearchMarketService(config, factory).run(criteria, "target", capture=capture, query_limit=query_limit)


def test_weak_local_and_google_gap_switches_canonical_offer_and_reprices(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    run_id = _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == plan.smart_offer.offer_id == pricing.project.offer_id == "google_presence_cleanup"
        assert context.selection_source == "search_market_fusion"
        assert context.supplied_canonical_id == "one_page_conversion_site"
        assert context.offer_fusion["original_offer_id"] == "one_page_conversion_site"
        assert context.offer_fusion["selected_offer_id"] == "google_presence_cleanup"
        assert any(str(run_id) in ref for item in context.offer_fusion["ranked_offers"] for ref in item["evidence_refs"])
        assert tuple(plan.smart_offer.scope) == context.scope
        _assert_nonblank_commercial_scope(context, plan, pricing)
        assert lead.recommended_offer_id == "one_page_conversion_site"  # no silent lead/qualification mutation


def test_strong_local_with_conversion_signal_prefers_conversion_not_visibility(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, signals=("No contact form",), google=True, checks=CONTACT_REPAIR_CHECKS)
    _run(config, factory, mode="present")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == "conversion_tune_up"
        assert pricing.project.offer_id == plan.smart_offer.offer_id == "conversion_tune_up"
        assert plan.smart_offer.offer_type == "website_conversion"
        assert plan.smart_offer.scope == CONTACT_REPAIR_SCOPE
        assert plan.primary_theme == "Conversion path"
        assert any(item["finding_type"] == "strong_tracked_local_coverage" for item in context.offer_fusion["findings"])
        assert all(item["finding_type"] != "local_coverage_gap" for item in context.offer_fusion["findings"])


def test_strong_local_with_current_listing_gap_supports_presentation_not_visibility_rebuild(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory, mode="present")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        context, _ = build_current_offer_context(session, lead, competitors=[])
        assert context.offer_id == "google_presence_cleanup"
        findings = context.offer_fusion["findings"]
        assert {item["finding_type"] for item in findings} == {
            "strong_tracked_local_coverage", "listing_presentation_gap"
        }
        assert all(item["local_visibility"] == "PRESENT_IN_TRACKED_PLACES_WINDOWS" for item in findings)
        assert any("google_presence:" in ref for item in findings for ref in item["corroborating_evidence_ids"])


def test_service_query_places_gap_requires_separate_current_website_evidence(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, signals=("Missing service pages",))
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert not any(item.finding_type == "service_query_gap" for item in findings_for_lead(session, lead))
        session.add(WebsiteAuditRecord(
            lead_id=lead.id, url=lead.website, reachable=True,
            checks_json='{"service_pages":false}',
            weaknesses_json='["Service pages are missing"]', created_at=utc_now(),
        ))
        session.flush()
        findings = findings_for_lead(session, lead)
        service = next(item for item in findings if item.finding_type == "service_query_gap")
        assert service.offer_id == ""  # Places absence cannot prescribe a whole site.
        assert service.organic_visibility == "UNKNOWN"
        assert "not establish organic" in service.uncertainty
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.intervention_assessment["state"] == "validate_first"
        assert context.intervention_assessment["recommended_offer_id"] == ""
        assert context.scope == plan.smart_offer.scope == ()
        assert not pricing.price_available
        assert any("demand" in item.lower() for item in context.intervention_assessment["unknowns"])


def test_unknown_truncated_never_switches_or_downgrades(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path)
    _run(config, factory, mode="truncated")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        fusion = fuse_offer(session, lead, lead.recommended_offer_id, google={
            "confidence": "Moderate", "observed_gaps": ["Hours"],
            "recommended_action": "Google Presence-only", "generated_at": utc_now().isoformat(),
        })
        assert not fusion.findings and not fusion.ranked_offers
        assert fusion.selected_offer_id == lead.recommended_offer_id


@pytest.mark.parametrize("corruption", ["context", "stale", "future"])
def test_ineligible_or_stale_probe_cannot_influence_offer(tmp_path, corruption) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        for probe in session.scalars(select(SearchVisibilityProbe)):
            if corruption == "context":
                probe.comparability_fingerprint = "wrong-run-context"
            elif corruption == "stale":
                probe.observed_at = utc_now() - timedelta(days=31)
            else:
                probe.observed_at = utc_now() + timedelta(days=2)
        session.commit()
        lead = session.get(Lead, lead_id)
        context, _ = build_current_offer_context(session, lead, competitors=[])
        # Independent current hours evidence can still support its narrow
        # correction, but no ineligible Search observation may be consumed.
        assert context.offer_id == "google_presence_cleanup"
        _assert_no_consumed_search_refs(context)


def test_demo_capture_is_not_live_commercial_evidence(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory, demo=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert findings_for_lead(session, lead) == ()


@pytest.mark.parametrize("lock", ["approved_draft", "manual_draft", "contact", "advanced_status"])
def test_commercially_acted_on_offer_stays_sticky_with_ranked_alternative(tmp_path, lock) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        if lock == "approved_draft":
            session.add(OutreachDraft(lead_id=lead.id, kind="initial_email", approved=True))
        elif lock == "manual_draft":
            session.add(OutreachDraft(
                lead_id=lead.id, kind="initial_email", subject="Human subject",
                body="Human-reviewed text", dependency_state="manual_review_required",
            ))
        elif lock == "contact":
            session.add(ContactInteraction(lead_id=lead.id, interaction_datetime="2026-09-23"))
        else:
            lead.status = "Contacted"
        session.flush()
        context, _ = build_current_offer_context(session, lead, competitors=[])
        assert context.offer_id == "one_page_conversion_site"
        assert context.selection_source == "search_market_advisory_locked"
        assert context.offer_fusion["ranked_offers"][0]["offer_id"] == "google_presence_cleanup"
        assert context.offer_fusion["sticky_reason"]


def test_regeneration_preserves_human_draft_body_and_manual_offer_lock(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        manual = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL,
            "Human subject", "Human-reviewed text", proof_dependencies=None,
        )
        assert manual.dependency_state == "manual_review_required"
        preserved = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL,
            "Regenerated subject", "Regenerated text", proof_dependencies=[],
        )
        assert preserved.id == manual.id
        assert (preserved.subject, preserved.body) == ("Human subject", "Human-reviewed text")
        context, _ = build_current_offer_context(session, lead, competitors=[])
        assert context.offer_id == "google_presence_cleanup"
        assert context.offer_fusion["sticky_reason"] == "manually drafted outreach exists"
        assert context.offer_fusion["lead_recommended_offer_id"] == "one_page_conversion_site"


def test_generated_unapproved_draft_is_not_human_confirmation(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        session.add(OutreachDraft(lead_id=lead.id, kind="generated", approved=False))
        session.flush()
        assert build_current_offer_context(session, lead, competitors=[])[0].offer_id == "google_presence_cleanup"


@pytest.mark.parametrize("status", ["Auditing", "Needs Review", "Qualified", "Outreach Drafted"])
def test_automatic_pre_contact_status_is_not_human_offer_confirmation(tmp_path, status) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        lead.status = status
        session.flush()
        assert build_current_offer_context(session, lead, competitors=[])[0].offer_id == "google_presence_cleanup"


def test_signal_order_does_not_change_offer_or_scope(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, signals=("Reviews not showcased", "No contact form"),
                                    google=True, checks=CONTACT_REPAIR_CHECKS)
    _run(config, factory, mode="present")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        before, _ = build_current_offer_context(session, lead, competitors=[])
        lead.target_signals_json = json.dumps(["No contact form", "Reviews not showcased"])
        after, _ = build_current_offer_context(session, lead, competitors=[])
        assert (before.offer_id, before.scope, before.context_fingerprint) == (
            after.offer_id, after.scope, after.context_fingerprint
        )


def test_ai_off_is_deterministic_and_read_only(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        before = (lead.qualification_class, lead.status, lead.recommended_offer_id)
        first = build_current_offer_context(session, lead, competitors=[])[0]
        second = build_current_offer_context(session, lead, competitors=[])[0]
        assert first == second
        assert before == (lead.qualification_class, lead.status, lead.recommended_offer_id)


def test_business_type_prior_without_local_observation_is_not_demand(tmp_path) -> None:
    _config, factory, _lead_id = _setup(tmp_path)
    with factory() as session:
        recs = recommend_business_types(session, "Denver, CO")
        assert recs
        assert all(item.observed_runs == item.observed_gap_queries == item.observed_points == 0 for item in recs)
        assert all(item.unknown == "No local observation" for item in recs)
        assert any(item.canonical_niche_id == "pest_control" and item.curated_prior == "moderate" for item in recs)
        assert recs == recommend_business_types(session, "Denver, CO")
        assert len({item.canonical_niche_id for item in recs}) == len(recs)


def test_business_type_observation_is_separate_from_prior_and_unknown_not_demand(tmp_path) -> None:
    config, factory, _lead_id = _setup(tmp_path)
    _run(config, factory)
    with factory() as session:
        recs = recommend_business_types(session, "Denver CO")
        pest = next(item for item in recs if item.canonical_niche_id == "pest_control")
        assert pest.observed_gap_queries >= 2 and pest.observed_runs == 1
        assert pest.combined_points == pest.prior_points + pest.observed_points
        assert "No search volume" in pest.unknown


def test_unknown_market_does_not_fabricate_local_observation(tmp_path) -> None:
    config, factory, _lead_id = _setup(tmp_path)
    _run(config, factory, mode="truncated")
    with factory() as session:
        recs = recommend_business_types(session, "Denver CO")
        pest = next(item for item in recs if item.canonical_niche_id == "pest_control")
        assert pest.observed_runs == pest.observed_gap_queries == pest.observed_eligible_queries == 0


def test_incomplete_query_coverage_is_not_commercial_opportunity(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        probe = session.scalars(select(SearchVisibilityProbe).order_by(SearchVisibilityProbe.id)).first()
        probe.truncated = True
        session.flush()
        lead = session.get(Lead, lead_id)
        assert findings_for_lead(session, lead) == ()
        pest = next(item for item in recommend_business_types(session, "Denver CO") if item.canonical_niche_id == "pest_control")
        assert pest.observed_runs == pest.observed_gap_queries == 0
        assert recommend_actual_businesses(session, "Denver CO") == ()


def test_local_gap_without_current_profile_corroboration_is_advisory_only(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        findings = findings_for_lead(session, lead)
        assert len(findings) == 1 and findings[0].offer_id == ""
        assert build_current_offer_context(session, lead, competitors=[])[0].offer_id == "one_page_conversion_site"


def test_human_offer_record_locks_then_explicit_selection_can_change_identity(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        seller = SellerProfile(display_name="Seller")
        session.add(seller)
        session.flush()
        session.add(OfferHistory(
            lead_id=lead.id, seller_profile_id=seller.id, offer_date="2026-09-23",
            business_name=lead.name, niche=lead.category, package_name=lead.recommended_offer,
            canonical_offer_id=lead.recommended_offer_id, initial_ask=900,
        ))
        session.flush()
        locked, _ = build_current_offer_context(session, lead, competitors=[])
        assert locked.offer_id == "one_page_conversion_site"
        assert locked.selection_source == "search_market_advisory_locked"
        with pytest.raises(ValueError, match="human confirmation"):
            accept_advisory_offer(session, lead, "google_presence_cleanup", operator_confirmed=False)
        accept_advisory_offer(session, lead, "google_presence_cleanup", operator_confirmed=True)
        accepted, _ = build_current_offer_context(session, lead, competitors=[])
        assert accepted.offer_id == "google_presence_cleanup"
        assert accepted.selection_source == "human_selected_offer"


def test_explicit_acceptance_alone_makes_offer_sticky(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        accept_advisory_offer(session, lead, "google_presence_cleanup", operator_confirmed=True)
        accepted, _ = build_current_offer_context(session, lead, competitors=[])
        assert accepted.offer_id == "google_presence_cleanup"
        assert accepted.offer_fusion["sticky_reason"] == "human-selected offer exists"
        assert accepted.selection_source == "human_selected_offer"


def test_approval_of_search_influenced_offer_does_not_self_stale(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == "google_presence_cleanup"
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL,
            "Approved subject", "Approved body", proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        session.flush()
        _fresh_plan, _fresh_pricing, fresh_context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.dependency_dict() == fresh_context.dependency_dict()
        assert recompute_lead_commercial_candidate(session, lead, "unrelated seller change") == 0
        assert lead.commercial_plan_state == "current" and draft.approved
        assert build_current_offer_context(session, lead, competitors=[])[0].offer_id == "google_presence_cleanup"


def test_new_advisory_alternative_does_not_invalidate_approved_offer(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True, human_selected=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL,
            "Approved subject", "Approved body", proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        session.commit()
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        draft = session.scalar(select(OutreachDraft).where(OutreachDraft.lead_id == lead.id))
        context, _ = build_current_offer_context(session, lead, competitors=[])
        assert context.offer_id == "one_page_conversion_site"
        assert context.selection_source == "search_market_advisory_locked"
        assert recompute_lead_commercial_candidate(session, lead, "new advisory evidence") == 0
        assert lead.commercial_plan_state == "current" and draft.approved


def test_locked_alternative_requires_explicit_ui_confirmation(tmp_path, monkeypatch) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    with factory() as session:
        session.add(OutreachDraft(lead_id=lead_id, kind="initial_email", approved=True))
        session.commit()
    _run(config, factory)
    app = QApplication.instance() or QApplication([])
    dialog = LeadDetailDialog(config, factory, lead_id)
    button = dialog.findChild(QPushButton, "accept_search_offer_alternative")
    assert button is not None
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
    button.click()
    with factory() as session:
        assert session.get(Lead, lead_id).recommended_offer_id == "one_page_conversion_site"
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    button.click()
    with factory() as session:
        assert session.get(Lead, lead_id).recommended_offer_id == "google_presence_cleanup"
    dialog.close()
    app.processEvents()


@pytest.mark.parametrize("blocked", ["suppressed", "no_sell", "dnc"])
def test_blocked_business_is_not_surfaced_for_targeting(tmp_path, blocked) -> None:
    config, factory, lead_id = _setup(tmp_path)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        if blocked == "suppressed":
            lead.suppressed = True
        elif blocked == "no_sell":
            lead.commercial_disposition = "NO_SELL"
        else:
            lead.status = "Do Not Contact"
        session.flush()
        assert recommend_actual_businesses(session, "Denver CO") == ()


def test_actual_business_gap_is_inspectable_and_has_no_lifecycle_side_effect(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path)
    run_id = _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        lead.qualification_class = "Qualified"
        lead.phone = "+13035550100"
        session.flush()
        before = (lead.qualification_class, lead.status, lead.recommended_offer_id)
        candidates = recommend_actual_businesses(session, "Denver CO")
        assert len(candidates) == 1
        assert candidates[0].run_id == run_id
        assert candidates[0].gap_query_ids and candidates[0].probe_ids
        assert before == (lead.qualification_class, lead.status, lead.recommended_offer_id)
        assert not session.new and not session.dirty


@pytest.mark.parametrize("mode", ["present", "truncated"])
def test_actual_business_without_demonstrable_gap_not_labeled_weak(tmp_path, mode) -> None:
    config, factory, _lead_id = _setup(tmp_path)
    _run(config, factory, mode=mode)
    with factory() as session:
        assert recommend_actual_businesses(session, "Denver CO") == ()


def test_latest_unknown_run_does_not_resurrect_older_gap(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    _run(config, factory, mode="truncated")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert findings_for_lead(session, lead) == ()
        context = build_current_offer_context(session, lead, competitors=[])[0]
        assert context.offer_id == "google_presence_cleanup"
        _assert_no_consumed_search_refs(context)


def test_cross_niche_or_wrong_place_run_cannot_attach_to_lead(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path)
    run_id = _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        run = session.get(SearchMarketRun, run_id)
        run.canonical_niche_id = "roofing"
        session.flush()
        assert findings_for_lead(session, lead, run_id=run_id) == ()


def test_new_live_capture_stales_only_affected_generated_plan_and_draft(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    with factory() as session:
        target = session.get(Lead, lead_id)
        other = Lead(
            search_id=target.search_id, place_id="other", name="Other Pest",
            category="pest control", website="https://other.example", phone="+13035550200",
            recommended_offer_id="one_page_conversion_site", recommended_offer="One-Page Conversion Site",
            offer_resolution_state="canonical_id", qualification_class="Qualified",
        )
        session.add(other)
        session.flush()
        other_id = other.id
        for lead in (target, other):
            _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
            snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
            if lead.id == lead_id:
                draft = save_outreach_draft(
                    session, lead.id, OutreachKind.INITIAL_EMAIL, "Old subject", "Old body",
                    proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
                )
                session.flush()
                draft_id = draft.id
        session.commit()
    _run(config, factory)
    with factory() as session:
        target = session.get(Lead, lead_id)
        other = session.get(Lead, other_id)
        draft = session.get(OutreachDraft, draft_id)
        assert build_current_offer_context(session, target, competitors=[])[0].offer_id == "google_presence_cleanup"
        assert target.commercial_plan_state == "stale"
        assert draft_commercial_errors(session, draft)
        assert (draft.subject, draft.body) == ("Old subject", "Old body")
        assert other.commercial_plan_state == "current"
        assert not current_plan_dependency_errors(session, other)


def test_evidence_expires_at_draft_boundary_without_any_database_write(tmp_path, monkeypatch) -> None:
    import local_presence_miner.services.search_market_analysis as market_analysis
    import local_presence_miner.services.search_offer_intelligence as offer_intelligence

    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == "google_presence_cleanup"
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Human-approved subject", "Human-approved body",
            proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        session.flush()
        session.commit()
        draft_id = draft.id
    future = utc_now() + timedelta(days=31)
    monkeypatch.setattr(market_analysis, "utc_now", lambda: future)
    monkeypatch.setattr(offer_intelligence, "utc_now", lambda: future)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        draft = session.get(OutreachDraft, draft_id)
        assert build_current_offer_context(session, lead, competitors=[])[0].offer_id == "google_presence_cleanup"
        # The human choice is sticky, but its old Search Market support is not current.
        assert current_plan_dependency_errors(session, lead)
        assert draft_commercial_errors(session, draft)
        assert lead.commercial_plan_state == "stale"
        assert (draft.subject, draft.body, draft.approved) == (
            "Human-approved subject", "Human-approved body", False,
        )
        assert session.new  # immutable approved text has been copied to approval history


@pytest.mark.parametrize("change", ["zip", "radius", "geography", "niche", "universe", "strategy"])
def test_changed_search_context_stays_historical_not_current_commercial_evidence(tmp_path, monkeypatch, change) -> None:
    import local_presence_miner.services.search_market_analysis as market_analysis
    import local_presence_miner.services.search_offer_intelligence as offer_intelligence

    config, factory, lead_id = _setup(tmp_path, google=True)
    run_id = _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert findings_for_lead(session, lead)
        if change == "zip":
            lead.target_zip_code = "80301"
        elif change == "radius":
            lead.target_radius_miles = 3
        elif change == "geography":
            new_parent = LeadSearch(name="Boulder search", city="Boulder", state_region="CO", niche="pest control")
            session.add(new_parent)
            session.flush()
            lead.search_id = new_parent.id
        elif change == "niche":
            lead.category = "roofing"
        elif change == "universe":
            monkeypatch.setattr(offer_intelligence, "QUERY_UNIVERSE_VERSION", "future-query-v2")
        else:
            monkeypatch.setattr(market_analysis, "ACQUISITION_STRATEGY_VERSION", "future-places-v3")
        session.flush()
        assert findings_for_lead(session, lead) == ()
        context = build_current_offer_context(session, lead, competitors=[])[0]
        assert context.offer_id == "google_presence_cleanup"
        _assert_no_consumed_search_refs(context)
        assert session.get(SearchMarketRun, run_id) is not None
        assert project_search_market(session, run_id).tracked_queries == 8


@pytest.mark.parametrize("block", ["reject", "hold", "no_route", "deferred", "closed"])
def test_non_actionable_lead_is_not_an_actual_business_target(tmp_path, block) -> None:
    config, factory, lead_id = _setup(tmp_path)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        lead.qualification_class = "Qualified"
        lead.phone = "+13035550100"
        if block == "reject":
            lead.qualification_class = "Reject"
        elif block == "hold":
            lead.qualification_class = "Hold"
        elif block == "no_route":
            lead.phone = ""
        elif block == "deferred":
            lead.commercial_disposition = "DEFERRED"
        else:
            lead.business_status = "CLOSED_PERMANENTLY"
        session.flush()
        assert recommend_actual_businesses(session, "Denver CO") == ()
        projection = project_search_market(session, session.scalar(select(SearchMarketRun.id)))
        assert projection.tracked_queries == projection.absent_queries == 8


def test_reopening_lead_persists_naturally_expired_commercial_state(tmp_path, monkeypatch) -> None:
    import local_presence_miner.services.search_market_analysis as market_analysis
    import local_presence_miner.services.search_offer_intelligence as offer_intelligence

    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        session.commit()
    future = utc_now() + timedelta(days=31)
    monkeypatch.setattr(market_analysis, "utc_now", lambda: future)
    monkeypatch.setattr(offer_intelligence, "utc_now", lambda: future)
    with factory() as session:
        assert current_plan_dependency_errors(session, session.get(Lead, lead_id))
    app = QApplication.instance() or QApplication([])
    dialog = LeadDetailDialog(config, factory, lead_id)
    app.processEvents()
    dialog.close()
    with factory() as session:
        assert session.get(Lead, lead_id).commercial_plan_state == "stale"


def test_internal_report_flags_expired_embedded_draft_without_rewriting_it(tmp_path, monkeypatch) -> None:
    import local_presence_miner.services.search_market_analysis as market_analysis
    import local_presence_miner.services.search_offer_intelligence as offer_intelligence

    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Original subject", "Original approved text",
            proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        session.commit()
        draft_id = draft.id
    future = utc_now() + timedelta(days=31)
    monkeypatch.setattr(market_analysis, "utc_now", lambda: future)
    monkeypatch.setattr(offer_intelligence, "utc_now", lambda: future)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        path = ReportService(config).generate_report(session, lead, "internal")
        html = path.read_text(encoding="utf-8")
        assert "Historical draft" in html and "review required" in html
        assert "Original approved text" in html
        assert session.get(OutreachDraft, draft_id).body == "Original approved text"


def test_accepted_conversion_offer_keeps_scope_theme_outcome_and_pricing_aligned(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, signals=("No contact form",), google=True,
                                    checks=CONTACT_REPAIR_CHECKS, human_selected=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Approved", "Owner-reviewed text",
            proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        session.commit()
        draft_id = draft.id
    _run(config, factory, mode="present")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert build_current_offer_context(session, lead, competitors=[])[0].selection_source == "search_market_advisory_locked"
        accept_advisory_offer(session, lead, "conversion_tune_up", operator_confirmed=True)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.selection_source == "human_selected_offer"
        assert context.offer_id == plan.smart_offer.offer_id == pricing.project.offer_id == "conversion_tune_up"
        assert plan.smart_offer.offer_type == "website_conversion"
        assert plan.primary_theme == "Conversion path"
        assert "inquir" in plan.smart_offer.primary_outcome
        assert context.scope == plan.smart_offer.scope == CONTACT_REPAIR_SCOPE
        assert "Google improvement checklist" not in " ".join(context.scope)
        assert session.get(OutreachDraft, draft_id).body == "Owner-reviewed text"
        _assert_nonblank_commercial_scope(context, plan, pricing)


@pytest.mark.parametrize("offer_id,family,theme,scope_start", [
    ("google_presence_cleanup", "google_presence", "Google presence", "Public Google presence"),
    ("conversion_tune_up", "website_conversion", "Conversion path", "Homepage CTA"),
    ("starter_local_presence_build", "website_build", "Digital foundation", "Focused three-page"),
    ("one_page_conversion_site", "website_build", "Website conversion", "One-page"),
    ("full_local_authority_site", "website_build", "Service visibility support", "Service-page"),
    ("review_trust_builder", "reviews", "Trust proof", "Verified review"),
    ("monitoring_review_growth", "monitoring", "Public presence monitoring", "Public presence monitoring"),
    ("no_track_record_pilot", "pilot", "Paid first step", "Paid public review"),
    ("paid_fix", "website_conversion", "Specific fix", "One root-cause fix"),
    ("five_page_service_site", "website_build", "Service website rebuild", "Five-page service site"),
    ("platform_migration", "website_build", "Platform move", "Domain-first migration"),
    ("sign_quote_intake", "workflow", "Quote intake", "Quote-ready intake"),
])
def test_all_canonical_offers_keep_product_semantics_with_google_assessment(
    tmp_path, offer_id, family, theme, scope_start,
) -> None:
    assert set(PRESENTATIONS) == set(OfferID)
    _config, factory, lead_id = _setup(tmp_path, offer_id=offer_id, signals=("No contact form",),
                                     google=True, profile_gap=False, human_selected=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == pricing.project.offer_id == plan.smart_offer.offer_id == offer_id
        assert plan.smart_offer.offer_type == offer_definition(offer_id).semantic_family == family
        assert plan.primary_theme == theme
        assert context.scope[0].startswith(scope_start)
        assert tuple(plan.smart_offer.scope) == context.scope


def test_interrupted_latest_run_recovery_stales_only_affected_commercial_plan(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Approved", "Keep these words",
            proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        parent = LeadSearch(name="Interrupted market", city="Denver", state_region="CO", niche="pest control",
                            lifecycle_state="Interrupted / Failed")
        session.add(parent)
        session.flush()
        interrupted = SearchMarketRun(
            search_id=parent.id, prospect_place_id=lead.place_id, canonical_niche_id="pest_control",
            geography="Denver CO", query_universe_version="taxonomy-query-v1", lifecycle_state="Running",
        )
        session.add(interrupted)
        session.commit()
        interrupted_id, draft_id = interrupted.id, draft.id
    reconcile_interrupted_search_market_runs(factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        draft = session.get(OutreachDraft, draft_id)
        assert session.get(SearchMarketRun, interrupted_id).lifecycle_state == "Failed"
        assert lead.commercial_plan_state == draft.commercial_dependency_state == "stale"
        assert not draft.approved and draft.body == "Keep these words"


def test_committed_search_succeeds_and_warns_if_commercial_refresh_raises(tmp_path, monkeypatch) -> None:
    import local_presence_miner.services.commercial_state_service as commercial_state

    config, factory, lead_id = _setup(tmp_path, google=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Approved", "Preserved text",
            proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        session.commit()
        draft_id = draft.id

    def fail_refresh(*_args, **_kwargs):
        raise RuntimeError("injected planner failure")

    monkeypatch.setattr(commercial_state, "recompute_lead_commercial_candidate", fail_refresh)
    run_id = _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        draft = session.get(OutreachDraft, draft_id)
        run = session.get(SearchMarketRun, run_id)
        assert run.lifecycle_state == "Completed"
        assert "Commercial refresh" in run.error_summary
        assert lead.commercial_plan_state == draft.commercial_dependency_state == "stale"
        assert not draft.approved and draft.body == "Preserved text"
    app = QApplication.instance() or QApplication([])
    widget = SearchMarketWidget(factory)
    widget.run_finished(run_id)
    app.processEvents()
    assert "commercial refresh needs review" in widget.status.text()
    assert "commercial review" in widget.table.item(0, 3).text()
    detail = SearchMarketDetailDialog(factory, run_id)
    assert any("Commercial refresh needs review" in label.text() for label in detail.findChildren(QLabel))
    detail.close()
    widget.close()


def _assert_nonblank_commercial_scope(context, plan, pricing) -> None:
    assert context.scope and pricing.price_available
    assert context.scope == tuple(plan.smart_offer.scope)
    assert all(item.strip() for item in context.scope)
    assert len(context.scope) == len(set(context.scope))
    for phase in pricing.phases:
        assert "; ;" not in phase.scope
        assert not phase.scope.endswith("; ")
        assert not phase.scope.startswith("; ")
    if pricing.phases:
        assert pricing.phases[0].scope.startswith(context.scope[0])
        assert pricing.phases[1].scope == "; ".join(context.scope)


@pytest.mark.parametrize("offer_id", [item.value for item in OfferID])
@pytest.mark.parametrize("goal", ["", "Better-fit jobs", "Easier intake", "Stronger trust and credibility"])
@pytest.mark.parametrize("google", [False, True])
def test_canonical_scope_has_no_empty_items_or_pricing_separators(tmp_path, offer_id, goal, google) -> None:
    _config, factory, lead_id = _setup(tmp_path, offer_id=offer_id, signals=("No contact form",),
                                     google=google, profile_gap=False, human_selected=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        if goal:
            ConversationStateService().append_assertion(session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value=goal)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == plan.smart_offer.offer_id == pricing.project.offer_id == offer_id
        _assert_nonblank_commercial_scope(context, plan, pricing)
        repeated, repeated_pricing, repeated_context = build_adaptive_sales_plan_with_context(
            session, lead, competitors=[],
        )
        assert repeated_context.scope == context.scope
        assert repeated.smart_offer.primary_outcome == plan.smart_offer.primary_outcome
        assert repeated_pricing.phases == pricing.phases


@pytest.mark.parametrize("goal,theme,problem,outcome,scope_start", [
    ("Better-fit jobs", "Lead quality", "better-fit", "service-fit", "Service-fit messaging"),
    ("Easier intake", "Intake efficiency", "intake", "inquiry", "Contact and estimate-flow"),
    ("Stronger trust and credibility", "Website trust proof", "trust", "proof", "Website review/testimonial"),
])
def test_conversion_goal_adapts_framing_inside_canonical_envelope(
    tmp_path, goal, theme, problem, outcome, scope_start,
) -> None:
    _config, factory, lead_id = _setup(
        tmp_path, offer_id="conversion_tune_up", signals=("No contact form",), google=True,
        profile_gap=False, human_selected=True,
    )
    with factory() as session:
        lead = session.get(Lead, lead_id)
        ConversationStateService().append_assertion(session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value=goal)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == plan.smart_offer.offer_id == pricing.project.offer_id == "conversion_tune_up"
        assert plan.smart_offer.offer_type == "website_conversion"
        assert plan.primary_theme == theme
        assert problem in plan.primary_problem.lower()
        assert outcome in plan.smart_offer.primary_outcome.lower()
        assert context.scope[0].startswith(scope_start)
        assert "Homepage CTA and estimate/request flow" in context.scope
        assert "Google improvement checklist" not in " ".join(context.scope)
        _assert_nonblank_commercial_scope(context, plan, pricing)


@pytest.mark.parametrize("goal,theme,scope_start", [
    ("Make it easier to find us on Google", "Conversion path", "Homepage CTA and estimate/request flow"),
    ("Improve the quality of our reviews", "Conversion path", "Homepage CTA and estimate/request flow"),
    ("Higher quality leads", "Lead quality", "Service-fit messaging"),
    ("Make intake easier", "Intake efficiency", "Contact and estimate-flow"),
    ("Fix booking friction", "Intake efficiency", "Contact and estimate-flow"),
    ("Show verified review proof", "Website trust proof", "Website review/testimonial"),
    ("Stronger trust and credibility", "Website trust proof", "Website review/testimonial"),
    ("Better-fit jobs and easier intake", "Conversion path", "Homepage CTA and estimate/request flow"),
])
def test_free_text_goal_adaptation_requires_unambiguous_intent(
    tmp_path, goal, theme, scope_start,
) -> None:
    _config, factory, lead_id = _setup(
        tmp_path, offer_id="conversion_tune_up", signals=("No contact form",), google=True,
        profile_gap=False, human_selected=True,
    )
    with factory() as session:
        lead = session.get(Lead, lead_id)
        ConversationStateService().append_assertion(session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value=goal)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == plan.smart_offer.offer_id == pricing.project.offer_id == "conversion_tune_up"
        assert plan.smart_offer.offer_type == "website_conversion"
        assert plan.primary_theme == theme
        assert context.scope[0].startswith(scope_start)
        assert f"Prospect-stated goal: {goal}" in plan.evidence_lines
        _assert_nonblank_commercial_scope(context, plan, pricing)


def test_incompatible_conversation_goal_cannot_turn_review_offer_into_conversion(tmp_path) -> None:
    _config, factory, lead_id = _setup(tmp_path, offer_id="review_trust_builder", google=True,
                                     profile_gap=False, human_selected=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        ConversationStateService().append_assertion(
            session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value="Better-fit jobs",
        )
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == pricing.project.offer_id == "review_trust_builder"
        assert plan.smart_offer.offer_type == "reviews"
        assert plan.primary_theme == "Trust proof"
        assert context.scope[0] == "Verified review and trust-proof presentation"
        assert "Service-fit messaging and inquiry qualification" not in context.scope
        _assert_nonblank_commercial_scope(context, plan, pricing)


def test_human_selected_conversion_keeps_adaptive_goal_and_canonical_identity(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, signals=("No contact form",), google=True,
                                    checks=CONTACT_REPAIR_CHECKS, human_selected=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        ConversationStateService().append_assertion(
            session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value="Better-fit jobs",
        )
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Approved", "Owner-authored body",
            proof_dependencies=[], commercial_snapshot=snapshot.to_dict(),
        )
        draft.approved = True
        session.commit()
        draft_id = draft.id
    _run(config, factory, mode="present")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        accept_advisory_offer(session, lead, "conversion_tune_up", operator_confirmed=True)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.selection_source == "human_selected_offer"
        assert context.offer_id == pricing.project.offer_id == plan.smart_offer.offer_id == "conversion_tune_up"
        assert plan.smart_offer.offer_type == "website_conversion"
        assert plan.primary_theme == "Lead quality"
        # The goal may frame the conversation but cannot add an unobserved
        # service-fit deliverable to the automatically supported repair scope.
        assert context.scope == CONTACT_REPAIR_SCOPE
        assert "Service-fit messaging and inquiry qualification" not in context.scope
        assert session.get(OutreachDraft, draft_id).body == "Owner-authored body"
        _assert_nonblank_commercial_scope(context, plan, pricing)


def test_search_market_fusion_keeps_conversation_inside_selected_google_offer(tmp_path) -> None:
    config, factory, lead_id = _setup(tmp_path, google=True)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        ConversationStateService().append_assertion(
            session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value="Better-fit jobs",
        )
        session.commit()
    _run(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.selection_source == "search_market_fusion"
        assert context.offer_id == pricing.project.offer_id == plan.smart_offer.offer_id == "google_presence_cleanup"
        assert plan.smart_offer.offer_type == "google_presence"
        assert plan.primary_theme == "Google service fit"
        assert context.scope == ("hours and contact cleanup checklist",)
        assert "Google service/category wording review" not in context.scope
        assert "Service-fit messaging and inquiry qualification on the existing website" not in context.scope
        _assert_nonblank_commercial_scope(context, plan, pricing)


def test_offer_semantic_version_changes_context_provenance(tmp_path, monkeypatch) -> None:
    import local_presence_miner.services.commercial_plan_service as commercial_plan

    assert OFFER_REGISTRY_VERSION == 5
    _config, factory, lead_id = _setup(tmp_path, offer_id="conversion_tune_up")
    with factory() as session:
        lead = session.get(Lead, lead_id)
        current, _ = build_current_offer_context(session, lead, competitors=[])
        assert current.registry_version == 5
        monkeypatch.setattr(commercial_plan, "OFFER_REGISTRY_VERSION", 4)
        prior, _ = build_current_offer_context(session, lead, competitors=[])
        assert prior.scope == current.scope
        assert prior.context_fingerprint != current.context_fingerprint
        _, prior_pricing, prior_context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        persist_current_plan(session, lead, competitors=[], pricing=prior_pricing, context=prior_context)
        session.commit()
        assert not current_plan_dependency_errors(session, lead)
        monkeypatch.setattr(commercial_plan, "OFFER_REGISTRY_VERSION", 5)
        assert current_plan_dependency_errors(session, lead)
