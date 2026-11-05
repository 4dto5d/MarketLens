"""Deterministic, read-only Search Market advice for commercial planning.

Places captures are sampled local-search windows, never organic rank or demand.
Only the Search Market projection decides whether a probe is eligible; this
module deliberately cannot promote an UNKNOWN query to negative evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import dumps, loads
from local_presence_miner.database.schema import (
    ActivityLog,
    ContactInteraction,
    Lead,
    LeadSearch,
    OfferHistory,
    OutreachApprovalHistory,
    OutreachDraft,
    SearchMarketQuery,
    SearchMarketRun,
    WebsiteAuditRecord,
)
from local_presence_miner.domain.enums import OUTREACH_BLOCKED_STATUSES, LeadStatus
from local_presence_miner.domain.intervention_assessment import assess_interventions
from local_presence_miner.domain.niche_taxonomy import NICHE_RULES, commercial_class, resolve_niche
from local_presence_miner.domain.offer_registry import OfferID, offer_definition
from local_presence_miner.services.query_universe_service import QUERY_UNIVERSE_VERSION, generate_query_universe
from local_presence_miner.services.search_market_analysis import QueryCoverage, project_search_market
from local_presence_miner.services.search_visibility_service import frozen_search_market_binding
from local_presence_miner.time_utils import utc_now


@dataclass(frozen=True)
class SearchOfferFinding:
    finding_type: str
    run_id: int
    canonical_niche_id: str
    query_ids: tuple[str, ...]
    cluster_ids: tuple[str, ...]
    probe_ids: tuple[int, ...]
    observed_at: tuple[str, ...]
    organic_visibility: str
    local_visibility: str
    eligible_queries: int
    affected_queries: int
    recurring_competitor_place_ids: tuple[str, ...]
    confidence: str
    offer_id: str
    rationale: str
    uncertainty: str
    corroborating_evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RankedOffer:
    offer_id: str
    fit: str
    components: dict[str, str]
    finding_types: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OfferFusion:
    original_offer_id: str
    selected_offer_id: str
    selection_source: str
    sticky_reason: str
    findings: tuple[SearchOfferFinding, ...]
    ranked_offers: tuple[RankedOffer, ...]
    explanation: str
    lead_recommended_offer_id: str = ""
    intervention_assessment: dict = field(default_factory=dict)
    human_quote_authorized: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def commercial_dependency(self) -> dict:
        """Only a changed canonical choice is material to pricing/outreach."""
        if self.selected_offer_id == self.lead_recommended_offer_id:
            return {}
        winning = next((item for item in self.ranked_offers if item.offer_id == self.selected_offer_id), None)
        return {
            "lead_recommended_offer_id": self.lead_recommended_offer_id,
            "selected_offer_id": self.selected_offer_id,
            "winning_evidence_refs": list(winning.evidence_refs) if winning else [],
            "winning_components": winning.components if winning else {},
        }


@dataclass(frozen=True)
class BusinessTypeRecommendation:
    canonical_niche_id: str
    display_name: str
    curated_prior: str
    prior_points: int
    observed_gap_queries: int
    observed_eligible_queries: int
    observed_runs: int
    observed_points: int
    combined_points: int
    confidence: str
    likely_offer_id: str
    why: str
    unknown: str


@dataclass(frozen=True)
class BusinessCandidate:
    lead_id: int
    place_id: str
    name: str
    canonical_niche_id: str
    run_id: int
    gap_query_ids: tuple[str, ...]
    probe_ids: tuple[int, ...]
    reason: str


def _latest_run(session: Session, lead: Lead) -> SearchMarketRun | None:
    niche = resolve_niche(lead.category)
    if not niche.resolved or not lead.place_id:
        return None
    return session.scalar(
        select(SearchMarketRun)
        .where(
            SearchMarketRun.prospect_place_id == lead.place_id,
            SearchMarketRun.canonical_niche_id == niche.canonical_id,
            SearchMarketRun.demo_mode.is_(False),
        )
        .order_by(SearchMarketRun.started_at.desc(), SearchMarketRun.id.desc())
        .limit(1)
    )


def _run_matches_current_lead(session: Session, run: SearchMarketRun, lead: Lead) -> bool:
    """Keep frozen search evidence historical when the lead's target window changes."""
    parent = session.get(LeadSearch, lead.search_id) if lead.search_id is not None else None
    if parent is None or run.query_universe_version != QUERY_UNIVERSE_VERSION or run.lifecycle_state != "Completed":
        return False
    queries = list(session.scalars(
        select(SearchMarketQuery).where(SearchMarketQuery.run_id == run.id).order_by(SearchMarketQuery.ordinal)
    ))
    if not queries:
        return False
    try:
        _, _, frozen = frozen_search_market_binding(session, run.search_id, queries[0].id)
        expected = generate_query_universe(lead.category, parent.city, parent.state_region, limit=len(queries))
    except (TypeError, ValueError, AttributeError):
        return False
    return bool(
        frozen.city == parent.city
        and frozen.state_region == parent.state_region
        and frozen.target_zip_code.strip().casefold() == (lead.target_zip_code or "").strip().casefold()
        and frozen.target_radius_miles == lead.target_radius_miles
        and frozen.radius_meters == round(lead.target_radius_miles * 1609.344)
        and frozen.max_results == 20  # run_for_lead's collected-window contract
        and tuple(query.query_id for query in queries) == tuple(query.query_id for query in expected)
    )


def _references(queries: list[QueryCoverage]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[int, ...], tuple[str, ...]]:
    ordered = sorted(queries, key=lambda item: item.query_id)
    return (
        tuple(item.query_id for item in ordered),
        tuple(sorted({item.cluster_id for item in ordered})),
        tuple(sorted({item.probe_id for item in ordered if item.probe_id is not None})),
        tuple(sorted({item.observed_at for item in ordered if item.observed_at})),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def findings_for_lead(
    session: Session, lead: Lead, *, google: dict | None = None, now: datetime | None = None,
    run_id: int | None = None,
) -> tuple[SearchOfferFinding, ...]:
    """Project only fresh, same-prospect live evidence; never infer organic rank."""
    run = session.get(SearchMarketRun, run_id) if run_id is not None else _latest_run(session, lead)
    niche = resolve_niche(lead.category)
    if (
        run is None or run.demo_mode or run.prospect_place_id != lead.place_id
        or not niche.resolved or run.canonical_niche_id != niche.canonical_id
        or not _run_matches_current_lead(session, run, lead)
    ):
        return ()
    projection = project_search_market(session, run.id, now=now)
    if (
        projection.evidence_mode != "live"
        or projection.coverage_denominator != projection.tracked_queries
    ):
        # Partial coverage can be inspected in Search Market itself, but must
        # not become a commercial recommendation about the whole query set.
        return ()
    eligible = [item for item in projection.queries if item.state in {"present", "absent"}]
    absent = [item for item in eligible if item.state == "absent"]
    present = [item for item in eligible if item.state == "present"]
    findings: list[SearchOfferFinding] = []
    recurring = tuple(sorted(item.place_id for item in projection.top_search_competitors if item.gap_capture_queries >= 2))
    google = google or {}
    google_gaps = tuple(str(item) for item in google.get("observed_gaps", ()) if str(item).strip())
    google_action = str(google.get("recommended_action") or "")
    google_date = str(google.get("generated_at") or "")
    try:
        google_age = _utc(now or utc_now()) - _utc(datetime.fromisoformat(google_date))
    except ValueError:
        google_age = timedelta.max
    google_current = (
        not lead.google_rich_data_stale
        and google.get("confidence") in {"Moderate", "Strong"}
        and timedelta(0) <= google_age <= timedelta(days=30)
    )
    profile_gap = any(
        any(token in gap.casefold() for token in ("hour", "phone", "photo", "categor", "review", "profile", "maps link"))
        for gap in google_gaps
    )
    if len(absent) >= 2 and len(absent) * 2 >= len(eligible) and recurring:
        refs = _references(absent)
        mapped = (
            OfferID.GOOGLE_PRESENCE_CLEANUP.value
            if lead.website and google_current and profile_gap and google_action in {"Google Presence-only", "Website + Google Presence"}
            else ""
        )
        findings.append(SearchOfferFinding(
            "local_coverage_gap", run.id, run.canonical_niche_id, *refs,
            "UNKNOWN", "WEAK_IN_TRACKED_PLACES_WINDOWS", len(eligible), len(absent), recurring,
            "Moderate" if len(absent) < 3 else "High", mapped,
            f"Prospect absent in {len(absent)} of {len(eligible)} eligible tracked Places windows; "
            f"{len(recurring)} competitor(s) appeared repeatedly in gap windows.",
            "This is sampled Places coverage, not exact Maps/Local Pack rank, organic rank, or search demand.",
            (f"google_presence:{google['assessment_id']}",) if mapped and google.get("assessment_id") else (),
        ))
    audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead.id))
    audit_age = _utc(now or utc_now()) - _utc(audit.created_at) if audit else timedelta.max
    audit_checks = loads(audit.checks_json, {}) if audit else {}
    verified_service_issue = bool(
        audit and audit.reachable and audit.url.rstrip("/") == lead.website.rstrip("/")
        and timedelta(0) <= audit_age <= timedelta(days=30)
        and isinstance(audit_checks, dict) and audit_checks.get("service_pages") is False
    )
    service_absent = [
        item for item in absent
        if not item.cluster_id.endswith(":core") and item.commercial_relevance >= 2
    ]
    if len(service_absent) >= 2 and lead.website and verified_service_issue:
        assert audit is not None
        refs = _references(service_absent)
        findings.append(SearchOfferFinding(
            "service_query_gap", run.id, run.canonical_niche_id, *refs,
            "UNKNOWN", "ABSENT_IN_TRACKED_SERVICE_PLACES_WINDOWS", len(eligible), len(service_absent), recurring,
            "Moderate", "",
            f"Prospect absent in {len(service_absent)} eligible service-query Places windows and "
            "a separate current website audit did not detect service-page content. Validate the useful service demand before scoping work.",
            "Places results do not establish organic coverage or prove that service-page changes will improve rank.",
            (f"website_audit:{audit.id}",),
        ))
    if len(present) >= 2 and not absent:
        refs = _references(present)
        findings.append(SearchOfferFinding(
            "strong_tracked_local_coverage", run.id, run.canonical_niche_id, *refs,
            "UNKNOWN", "PRESENT_IN_TRACKED_PLACES_WINDOWS", len(eligible), len(present), (),
            "Moderate", "",
            f"Prospect returned in all {len(present)} eligible tracked Places windows.",
            "This does not establish complete local or organic visibility.",
        ))
        if google_current and profile_gap and google_action in {"Google Presence-only", "Website + Google Presence"}:
            findings.append(SearchOfferFinding(
                "listing_presentation_gap", run.id, run.canonical_niche_id, *refs,
                "UNKNOWN", "PRESENT_IN_TRACKED_PLACES_WINDOWS", len(eligible), len(present), (),
                "Moderate", OfferID.GOOGLE_PRESENCE_CLEANUP.value,
                "Tracked Places presence is present; a separate current Google Presence assessment identifies "
                "public listing/profile presentation work.",
                "This is a presentation opportunity, not a weak-visibility or exact-rank claim.",
                (f"google_presence:{google['assessment_id']}",) if google.get("assessment_id") else (),
            ))
    return tuple(sorted(findings, key=lambda item: (item.finding_type, item.query_ids)))


def _sticky_reason(session: Session, lead: Lead) -> str:
    if lead.id is None:
        return ""
    if session.scalar(select(ActivityLog.id).where(
        ActivityLog.lead_id == lead.id, ActivityLog.action == "offer_selected"
    ).limit(1)) is not None:
        return "human-selected offer exists"
    gates = (
        (OfferHistory, "human offer history exists"),
        # Generated, unapproved drafts are automatic caches, not human action.
        (OutreachApprovalHistory, "outreach approval history exists"),
        (ContactInteraction, "contact interaction exists"),
    )
    for model, reason in gates:
        if session.scalar(select(model.id).where(model.lead_id == lead.id).limit(1)) is not None:
            return reason
    if session.scalar(select(OutreachDraft.id).where(
        OutreachDraft.lead_id == lead.id, OutreachDraft.approved.is_(True)
    ).limit(1)) is not None:
        return "human-approved outreach exists"
    if session.scalar(select(OutreachDraft.id).where(
        OutreachDraft.lead_id == lead.id,
        OutreachDraft.dependency_state.in_({"manual_review_required", "manually_revalidated"}),
    ).limit(1)) is not None:
        return "manually drafted outreach exists"
    if lead.status in {
        LeadStatus.APPROVED_TO_CONTACT.value,
        LeadStatus.CONTACTED.value,
        LeadStatus.REPLIED.value,
        LeadStatus.MEETING_SCHEDULED.value,
        LeadStatus.WON.value,
        LeadStatus.LOST.value,
        *OUTREACH_BLOCKED_STATUSES,
    }:
        return "lead lifecycle has advanced"
    return ""


def _valid_offer_id(value: str) -> str:
    try:
        return OfferID(value).value
    except ValueError:
        return ""


def _snapshot_offer_id(raw: str) -> str:
    snapshot = loads(raw, {})
    if not isinstance(snapshot, dict):
        return ""
    dependencies = snapshot.get("dependencies", {})
    if not isinstance(dependencies, dict):
        return ""
    context = dependencies.get("current_offer_context", {})
    if not isinstance(context, dict):
        return ""
    return _valid_offer_id(str(context.get("offer_id") or ""))


def _snapshot_has_price(raw: str) -> bool:
    snapshot = loads(raw, {})
    output = snapshot.get("output", {}) if isinstance(snapshot, dict) else {}
    return isinstance(output, dict) and type(output.get("recommended")) in {int, float}


def _sticky_offer_id(session: Session, lead: Lead) -> tuple[str, bool, bool]:
    """Use the exact commercially acted-on offer, not a later scored Lead hint."""
    selection = session.scalar(select(ActivityLog).where(
        ActivityLog.lead_id == lead.id, ActivityLog.action == "offer_selected"
    ).order_by(ActivityLog.id.desc()).limit(1))
    if selection is not None:
        event = loads(selection.message, {})
        if isinstance(event, dict):
            selected = _valid_offer_id(str(event.get("offer_id") or ""))
            if selected:
                return selected, True, True
    offer = session.scalar(select(OfferHistory).where(OfferHistory.lead_id == lead.id).order_by(
        OfferHistory.offer_date.desc(), OfferHistory.id.desc()
    ).limit(1))
    if offer is not None and (selected := _valid_offer_id(offer.canonical_offer_id)):
        return selected, False, True
    drafts = session.scalars(select(OutreachDraft).where(
        OutreachDraft.lead_id == lead.id,
        (OutreachDraft.approved.is_(True) | OutreachDraft.dependency_state.in_(
            {"manual_review_required", "manually_revalidated"}
        )),
    ).order_by(OutreachDraft.updated_at.desc(), OutreachDraft.id.desc()))
    for draft in drafts:
        if selected := _snapshot_offer_id(draft.commercial_snapshot_json):
            return selected, False, _snapshot_has_price(draft.commercial_snapshot_json)
    interactions = session.scalars(select(ContactInteraction).where(
        ContactInteraction.lead_id == lead.id
    ).order_by(ContactInteraction.id.desc()))
    for interaction in interactions:
        if selected := _snapshot_offer_id(interaction.commercial_snapshot_json):
            return selected, False, _snapshot_has_price(interaction.commercial_snapshot_json)
    return _snapshot_offer_id(lead.commercial_plan_snapshot_json), False, _snapshot_has_price(lead.commercial_plan_snapshot_json)


def fuse_offer(
    session: Session, lead: Lead, original_offer_id: str, *, google: dict | None = None,
    now: datetime | None = None,
) -> OfferFusion:
    """Assess interventions before selecting scope; history is never a ranking bonus."""
    from local_presence_miner.services.conversation_state_service import ConversationStateService
    from local_presence_miner.services.intervention_evidence_service import collect_intervention_evidence

    findings = findings_for_lead(session, lead, google=google, now=now)
    evidence = collect_intervention_evidence(
        session, lead, conversation=ConversationStateService().build(session, lead),
        findings=tuple(item.to_dict() for item in findings), now=now,
    )
    assessment = assess_interventions(evidence)
    sticky = _sticky_reason(session, lead)
    lead_offer_id = original_offer_id
    explicit_selection = False
    quote_authorized = False
    locked_offer_id = ""
    if sticky:
        locked_offer_id, explicit_selection, quote_authorized = _sticky_offer_id(session, lead)
    ranked = tuple(
        RankedOffer(item.offer_id, item.fit,
                    {"evidence_confidence": item.confidence, "effort": item.effort},
                    (), item.evidence_refs, item.why_over_alternatives)
        for item in assessment.ranked_candidates if item.offer_id and item.status == "recommended"
    )
    # UNKNOWN is not a competing offer and cannot replace a canonical identity.
    winner_id = assessment.recommended_offer_id if assessment.state == "recommended" else ""
    selected = locked_offer_id or (winner_id if winner_id and not sticky else original_offer_id)
    source = (
        ("search_market_fusion" if findings else "intervention_assessment") if selected != lead_offer_id and not sticky else
        "human_selected_offer" if explicit_selection else
        "commercially_acted_offer" if sticky and selected != lead_offer_id else
        "lead_recommended_offer"
    )
    if sticky and winner_id and winner_id != selected:
        source = "search_market_advisory_locked" if findings else "intervention_advisory_locked"
    displaced = next((item for item in ranked if item.offer_id == original_offer_id), None)
    explanation = (
        assessment.summary + " "
        + (f"Canonical offer retained because {sticky}; any alternative requires explicit acceptance. " if sticky else "")
        + (f"Replaced {original_offer_id or 'unselected'} with {selected}; previous candidate fit: "
           f"{displaced.fit if displaced else 'not supported by current eligible evidence'}. "
           if selected != original_offer_id and not sticky else "")
        + "Fit is a qualitative evidence policy, not measured demand, expected value or a ranking guarantee."
    )
    return OfferFusion(original_offer_id, selected, source, sticky, findings, ranked, explanation,
                       lead_offer_id, assessment.to_dict(), quote_authorized)


def accept_advisory_offer(session: Session, lead: Lead, offer_id: str, *, operator_confirmed: bool) -> None:
    """Explicit human-selection seam; never called by Search Market acquisition."""
    if not operator_confirmed or lead.id is None:
        raise ValueError("A recorded human confirmation is required to switch the commercial offer.")
    selected = _valid_offer_id(offer_id)
    if not selected:
        raise ValueError("Choose an existing canonical Offer ID.")
    from local_presence_miner.database.repositories import log_activity, update_lead_fields
    from local_presence_miner.database.schema import GooglePresenceAssessment
    from local_presence_miner.services.google_presence_service import assessment_to_dict

    record = session.scalar(select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead.id))
    google = assessment_to_dict(record)
    if record is not None:
        google["assessment_id"] = record.id
    fusion = fuse_offer(session, lead, lead.recommended_offer_id, google=google)
    if selected not in {item.offer_id for item in fusion.ranked_offers}:
        raise ValueError("The requested Offer ID is not a current ranked candidate.")
    log_activity(session, "offer_selected", dumps({
        "offer_id": selected, "prior_offer_id": fusion.selected_offer_id,
        "search_market_run_ids": sorted({item.run_id for item in fusion.findings}),
    }), lead.id)
    definition = offer_definition(selected)
    update_lead_fields(
        session, lead.id, recommended_offer_id=selected,
        recommended_offer=definition.display_name, offer_resolution_state="canonical_id",
    )


def recommend_business_types(
    session: Session, geography: str, *, now: datetime | None = None
) -> tuple[BusinessTypeRecommendation, ...]:
    """Keep curated sales prior and measured local-query observations separate."""
    rows = list(session.scalars(select(SearchMarketRun).where(
        SearchMarketRun.geography == geography, SearchMarketRun.demo_mode.is_(False)
    ).order_by(SearchMarketRun.started_at.desc(), SearchMarketRun.id.desc())))
    observed: dict[str, tuple[int, int, int]] = {}
    seen: set[str] = set()
    for run in rows:
        if run.prospect_place_id in seen:
            continue
        seen.add(run.prospect_place_id)
        if run.query_universe_version != QUERY_UNIVERSE_VERSION:
            continue
        projection = project_search_market(session, run.id, now=now)
        if projection.coverage_denominator != projection.tracked_queries:
            continue
        gap = sum(item.state == "absent" for item in projection.queries)
        eligible = projection.coverage_denominator
        if not eligible:
            continue
        old = observed.get(run.canonical_niche_id, (0, 0, 0))
        observed[run.canonical_niche_id] = (old[0] + gap, old[1] + eligible, old[2] + 1)
    result: list[BusinessTypeRecommendation] = []
    emitted: set[str] = set()
    for rule in NICHE_RULES:
        if rule.canonical_id in emitted:
            continue  # The shared catalog has aliases; recommendations have one canonical identity.
        emitted.add(rule.canonical_id)
        prior = commercial_class(rule.display_name)
        prior_points = {"high": 30, "moderate": 20, "general": 10}[prior]
        gap, eligible, runs = observed.get(rule.canonical_id, (0, 0, 0))
        observed_points = min(30, 6 * gap) if eligible else 0
        # This is a prior offer family, never a claim that Places alone proves
        # GBP cleanup is needed for an individual business.
        offer_id = OfferID.GOOGLE_PRESENCE_CLEANUP.value if prior != "general" else ""
        result.append(BusinessTypeRecommendation(
            rule.canonical_id, rule.display_name, prior, prior_points, gap, eligible, runs,
            observed_points, prior_points + observed_points,
            "Moderate" if runs >= 2 and eligible >= 4 else "Low",
            offer_id,
            f"Curated {prior} sales-fit prior; {gap} absent of {eligible} eligible tracked Places queries across {runs} run(s).",
            "No local observation" if not eligible else
            "No search volume, organic rank, market size, or customer-demand measurement is available; "
            "individual GBP scope requires separate public-profile evidence.",
        ))
    return tuple(sorted(result, key=lambda item: (-item.combined_points, item.canonical_niche_id)))


def recommend_actual_businesses(
    session: Session, geography: str, *, now: datetime | None = None
) -> tuple[BusinessCandidate, ...]:
    """Surface existing leads only; no qualification or outreach side effects."""
    from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService

    eligibility = OutreachEligibilityService()
    runs = list(session.scalars(select(SearchMarketRun).where(
        SearchMarketRun.geography == geography, SearchMarketRun.demo_mode.is_(False)
    ).order_by(SearchMarketRun.started_at.desc(), SearchMarketRun.id.desc())))
    result: list[BusinessCandidate] = []
    seen: set[str] = set()
    for run in runs:
        if run.prospect_place_id in seen:
            continue
        seen.add(run.prospect_place_id)
        lead = session.scalar(select(Lead).where(Lead.place_id == run.prospect_place_id))
        if (
            lead is None
            or resolve_niche(lead.category).canonical_id != run.canonical_niche_id
        ):
            continue
        if not eligibility.evaluate(session, lead).permits_live_use:
            # Search opportunity is not Qualification or permission to contact.
            # This list is actionable only; ineligible evidence remains in the ledger.
            continue
        findings = findings_for_lead(session, lead, now=now, run_id=run.id)
        gap = next((item for item in findings if item.finding_type == "local_coverage_gap"), None)
        if gap:
            result.append(BusinessCandidate(lead.id, lead.place_id, lead.name, run.canonical_niche_id,
                                            run.id, gap.query_ids, gap.probe_ids, gap.rationale))
    return tuple(sorted(result, key=lambda item: (item.canonical_niche_id, item.place_id)))
