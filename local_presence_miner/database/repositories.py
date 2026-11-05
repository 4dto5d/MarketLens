from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.schema import (
    ActivityLog,
    CommercialDispositionRecord,
    CompetitorRecord,
    ContactInteraction,
    ContactPoint,
    ConversationAssertion,
    GooglePresenceAssessment,
    Lead,
    LeadSearch,
    OutreachApprovalHistory,
    OutreachDraft,
    SearchRunLead,
    SellerProof,
    SuppressionEntry,
    WebsiteAuditRecord,
)
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.domain.enums import OUTREACH_BLOCKED_STATUSES, LeadStatus, OutreachKind
from local_presence_miner.domain.models import (
    BusinessProfile,
    CompetitorMatch,
    ScoreBreakdown,
    SearchCriteria,
    WebsiteAudit,
)
from local_presence_miner.domain.niche_taxonomy import resolve_niche
from local_presence_miner.domain.offer_registry import resolve_offer
from local_presence_miner.domain.verification import assess_verification, format_missing_requirements
from local_presence_miner.services.outbound_validation_service import validate_outbound_draft
from local_presence_miner.services.proof_dependency_service import (
    PERMISSION_FIELDS,
    assess_dependencies,
    body_fingerprint,
    dependency_set_fingerprint,
    make_proof_dependency,
    parse_dependencies,
    proof_allows_external_use,
)
from local_presence_miner.time_utils import utc_now


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def lead_google_details_retrieved(lead: Lead) -> bool:
    public_data = loads(lead.google_public_data_json, {})
    if "details_retrieved" in public_data:
        return bool(public_data["details_retrieved"])
    return bool(lead.phone or lead.website or lead.has_hours or lead.photo_count or lead.rating is not None)


def create_search(session: Session, criteria: SearchCriteria) -> LeadSearch:
    search = LeadSearch(
        name=criteria.output_name,
        city=criteria.city,
        state_region=criteria.state_region,
        niche=criteria.niche,
        criteria_json=dumps(asdict(criteria)),
        lifecycle_state="Running",
        started_at=utc_now(),
    )
    session.add(search)
    session.flush()
    log_activity(session, "search_created", f"Created search {criteria.output_name}")
    return search


def mark_search_completed(session: Session, search_id: int) -> None:
    search = session.get(LeadSearch, search_id)
    if search:
        search.completed = True
        search.lifecycle_state = "Completed"
        search.completed_at = utc_now()
        log_activity(session, "search_completed", f"Completed search {search.name}")


def upsert_search_membership(
    session: Session,
    search_id: int,
    *,
    candidate_place_id: str,
    candidate_name: str,
    discovery_order: int,
    search_position: int | None,
) -> SearchRunLead:
    stable_candidate_id = candidate_place_id.strip() or f"missing-place-id:{discovery_order}"
    membership = session.execute(
        select(SearchRunLead).where(
            SearchRunLead.search_id == search_id,
            SearchRunLead.candidate_place_id == stable_candidate_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = SearchRunLead(
            search_id=search_id,
            candidate_place_id=stable_candidate_id,
            candidate_name=candidate_name,
            discovery_order=discovery_order,
            search_position=search_position,
        )
        session.add(membership)
    else:
        membership.candidate_name = candidate_name
        membership.discovery_order = discovery_order
        membership.search_position = search_position
    session.flush()
    return membership


def refresh_search_counters(session: Session, search_id: int) -> LeadSearch | None:
    search = session.get(LeadSearch, search_id)
    if search is None:
        return None
    memberships = list(session.scalars(select(SearchRunLead).where(SearchRunLead.search_id == search_id)))
    search.total_candidates = max(search.total_candidates, len(memberships))
    search.processed_count = sum(item.processing_status in {"Succeeded", "Failed", "Skipped"} for item in memberships)
    search.succeeded_count = sum(item.processing_status == "Succeeded" for item in memberships)
    search.failed_count = sum(item.processing_status == "Failed" for item in memberships)
    search.skipped_count = sum(item.processing_status == "Skipped" for item in memberships)
    search.new_count = sum(item.discovery_kind == "new" for item in memberships)
    search.rediscovered_count = sum(item.discovery_kind == "rediscovered" for item in memberships)
    return search


def finish_search(
    session: Session,
    search_id: int,
    lifecycle_state: str,
    *,
    errors: list[str] | tuple[str, ...] = (),
) -> None:
    search = refresh_search_counters(session, search_id)
    if search is None:
        return
    search.lifecycle_state = lifecycle_state
    search.completed = lifecycle_state in {"Completed", "Completed With Errors"}
    search.completed_at = utc_now()
    search.error_summary = "\n".join(dict.fromkeys(error for error in errors if error))[:8000]
    log_activity(
        session,
        "search_finished",
        f"{search.name}: {lifecycle_state}; {search.succeeded_count} succeeded, "
        f"{search.failed_count} failed, {search.skipped_count} skipped",
    )


@dataclass(frozen=True)
class LeadUpsertResult:
    lead: Lead
    is_new: bool


def upsert_lead_with_outcome(
    session: Session,
    profile: BusinessProfile,
    search_id: int | None,
    score: ScoreBreakdown,
    notes: str = "",
) -> LeadUpsertResult:
    lead = session.execute(select(Lead).where(Lead.place_id == profile.place_id)).scalar_one_or_none()
    is_new = lead is None
    if lead is None:
        # SQLite's native conflict handling closes the SELECT/INSERT race
        # without poisoning the surrounding per-lead transaction.
        inserted = session.execute(
            sqlite_insert(Lead)
            .values(place_id=profile.place_id, name=profile.name)
            .on_conflict_do_nothing(index_elements=[Lead.place_id])
        )
        is_new = getattr(inserted, "rowcount", 0) == 1
        lead = session.execute(select(Lead).where(Lead.place_id == profile.place_id)).scalar_one()

    previous_identity = {
        "name": lead.name or "",
        "address": lead.address or "",
        "phone": lead.phone or "",
        "website": lead.website or "",
        "google_maps_url": lead.google_maps_url or "",
    }
    previous_commercial_inputs = {
        "category": lead.category or "",
        "website": lead.website or "",
        "recommended_offer": lead.recommended_offer or "",
        "recommended_offer_id": lead.recommended_offer_id or "",
        "target_signals_json": lead.target_signals_json or "[]",
        "google_public_data_json": lead.google_public_data_json or "{}",
    }
    had_rich = (not is_new) and lead_google_details_retrieved(lead)
    details_error = str(profile.raw.get("details_error", ""))
    rich_success = bool(profile.google_details_retrieved)
    preserve_rich = had_rich and not rich_success and bool(details_error)

    if is_new:
        # Compatibility pointer only.  SearchRunLead is canonical from v0.1.13.
        lead.search_id = search_id
    lead.name = profile.name or lead.name
    lead.category = profile.category or lead.category
    lead.address = profile.address or lead.address
    if not preserve_rich:
        lead.phone = profile.phone
        lead.website = profile.website
        lead.rating = profile.rating
        lead.review_count = profile.review_count
        lead.has_hours = profile.has_hours
        lead.photo_count = profile.photo_count
    lead.google_maps_url = profile.google_maps_url or lead.google_maps_url
    lead.yelp_url = profile.yelp_url or lead.yelp_url
    lead.business_types_json = dumps(profile.business_types or loads(lead.business_types_json, []))
    lead.latitude = profile.latitude if profile.latitude is not None else lead.latitude
    lead.longitude = profile.longitude if profile.longitude is not None else lead.longitude
    lead.search_position = profile.search_position
    lead.profile_verification_required = profile.profile_verification_required
    lead.business_status = profile.business_status or lead.business_status
    lead.primary_type = profile.primary_type or lead.primary_type
    lead.pure_service_area_business = profile.pure_service_area_business

    previous_public = loads(lead.google_public_data_json, {}) if not is_new else {}
    new_public = {
        "international_phone": profile.international_phone,
        "current_hours_available": profile.current_hours_available,
        "public_reviews": profile.public_reviews,
        "price_level": profile.price_level,
        "price_range": profile.price_range,
    }
    if preserve_rich:
        for key in ("international_phone", "current_hours_available", "public_reviews", "price_level", "price_range"):
            if previous_public.get(key) not in (None, "", [], {}):
                new_public[key] = previous_public[key]
    new_public.update(
        {
            "source": "Google Places API" if not profile.place_id.startswith("demo_") else "Demo fixture",
            "details_retrieved": True if preserve_rich else rich_success,
            "detail_fields_requested": bool(profile.raw.get("_detail_fields_requested", rich_success)),
            "selected_for_details": bool(profile.raw.get("_selected_for_details", rich_success)),
            "google_data_depth": str(profile.raw.get("_google_data_depth", "")),
            "preliminary_candidate_score": profile.raw.get("_preliminary_candidate_score"),
            "preliminary_rank": profile.raw.get("_preliminary_rank"),
            "details_error": details_error,
            "rich_data_stale": preserve_rich,
        }
    )
    lead.google_public_data_json = dumps(new_public)
    lead.google_retrieved_at = profile.retrieved_at
    lead.last_google_refresh_attempt_at = profile.retrieved_at
    if rich_success:
        lead.last_rich_google_retrieved_at = profile.retrieved_at
        lead.last_google_refresh_error = ""
        lead.google_rich_data_stale = False
    elif details_error:
        lead.last_google_refresh_error = details_error
        lead.google_rich_data_stale = preserve_rich

    lead.lead_score = score.total
    lead.priority = score.priority
    lead.recommended_offer = score.recommended_offer
    offer_resolution = resolve_offer(score.recommended_offer, score.recommended_offer_id or None)
    lead.recommended_offer_id = offer_resolution.offer_id.value if offer_resolution.offer_id else ""
    lead.offer_resolution_state = offer_resolution.status
    niche_resolution = resolve_niche(profile.category)
    lead.canonical_niche_id = niche_resolution.canonical_id if niche_resolution.resolved else ""
    lead.niche_match_rule = niche_resolution.match_rule
    lead.approach_angle = score.approach_angle
    lead.target_signals_json = dumps(score.target_signals)
    lead.score_breakdown_json = dumps([asdict(factor) for factor in score.factors])
    lead.system_notes = notes
    lead.updated_at = utc_now()
    if is_new:
        lead.status = LeadStatus.NEW.value
    session.flush()

    if not is_new and any(previous_commercial_inputs[key] != str(getattr(lead, key, "") or "") for key in previous_commercial_inputs):
        from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

        recompute_lead_commercial_candidate(session, lead, "Public search evidence changed commercial planning inputs")

    if not is_new:
        changed = {
            key for key, old in previous_identity.items()
            if old != str(getattr(lead, key, "") or "")
        }
        invalid: set[str] = set()
        if changed & {"name", "address"}:
            invalid |= {"business_identity", "outreach"}
        if "phone" in changed:
            invalid |= {"phone", "outreach"}
        if "website" in changed:
            invalid |= {"website", "audit_claims", "outreach"}
        if "google_maps_url" in changed:
            invalid |= {"google_url", "outreach"}
        if invalid:
            invalidate_verification(session, lead, invalid, "Public lead evidence changed during refresh")

    invalidate_contact_readiness(session, lead, "Current lead viability changed during refresh")

    log_activity(session, "lead_upserted", f"Saved lead {lead.name}", lead.id)
    return LeadUpsertResult(lead, is_new)


def upsert_lead(
    session: Session,
    profile: BusinessProfile,
    search_id: int | None,
    score: ScoreBreakdown,
    notes: str = "",
) -> Lead:
    """Compatibility wrapper for callers that do not need rediscovery state."""
    return upsert_lead_with_outcome(session, profile, search_id, score, notes).lead

def save_audit(session: Session, lead_id: int, audit: WebsiteAudit) -> WebsiteAuditRecord:
    record = session.execute(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead_id)).scalar_one_or_none()
    previous_signature = None
    if record is not None:
        previous_signature = (
            record.reachable,
            record.url,
            record.final_url,
            record.checks_json,
            record.rendered_checks_json,
            record.weaknesses_json,
            record.evidence_json,
        )
    if record is None:
        record = WebsiteAuditRecord(lead_id=lead_id)
        session.add(record)
    record.url = audit.url
    record.reachable = audit.reachable
    record.status_code = audit.status_code
    record.final_url = audit.final_url
    record.response_time_ms = audit.response_time_ms
    record.title = audit.title
    record.meta_description = audit.meta_description
    record.checks_json = dumps(audit.checks)
    record.metrics_json = dumps(audit.metrics)
    record.strengths_json = dumps(audit.strengths)
    record.weaknesses_json = dumps(audit.weaknesses)
    record.rendered_checks_json = dumps(audit.rendered_checks)
    record.evidence_json = dumps(audit.evidence)
    record.pagespeed_status = audit.pagespeed_status
    record.rendered_status = audit.rendered_status
    record.desktop_screenshot = audit.desktop_screenshot
    record.mobile_screenshot = audit.mobile_screenshot
    record.created_at = utc_now()
    session.flush()
    current_signature = (
        record.reachable,
        record.url,
        record.final_url,
        record.checks_json,
        record.rendered_checks_json,
        record.weaknesses_json,
        record.evidence_json,
    )
    if previous_signature is not None and previous_signature != current_signature:
        lead = session.get(Lead, lead_id)
        if lead:
            invalidate_verification(session, lead, {"audit_claims", "outreach"}, "Website audit evidence changed")
    return record

def save_competitors(
    session: Session,
    lead_id: int,
    competitors: list[CompetitorMatch],
    profiles: dict[str, BusinessProfile] | None = None,
) -> None:
    existing_rows = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead_id)).scalars())
    existing_by_place = {row.competitor_place_id: row for row in existing_rows}
    old_ids = set(existing_by_place)
    new_ids = {match.place_id for match in competitors}

    def salient_snapshot(value: str) -> tuple[object, ...]:
        data = loads(value, {})
        return tuple(
            data.get(key)
            for key in (
                "business_status",
                "primary_type",
                "rating",
                "review_count",
                "website",
                "phone",
                "hours",
                "photo_count",
                "details_retrieved",
            )
        )

    old_evidence = {
        row.competitor_place_id: (row.website_url or "", salient_snapshot(row.google_snapshot_json))
        for row in existing_rows
    }
    for existing in existing_rows:
        session.delete(existing)
    for match in competitors:
        profile = (profiles or {}).get(match.place_id)
        previous = existing_by_place.get(match.place_id)
        session.add(
            CompetitorRecord(
                lead_id=lead_id,
                competitor_place_id=match.place_id,
                competitor_name=match.name,
                match_score=match.score,
                reason=match.reason,
                checklist_json=previous.checklist_json if previous else dumps(default_competitor_checklist()),
                evidence_notes=previous.evidence_notes if previous else "",
                website_url=profile.website if profile else (previous.website_url if previous else ""),
                google_snapshot_json=dumps(profile_google_snapshot(profile)) if profile else (previous.google_snapshot_json if previous else "{}"),
            )
        )
    session.flush()
    evidence_changed = old_ids != new_ids
    if not evidence_changed and old_ids:
        for match in competitors:
            profile = (profiles or {}).get(match.place_id)
            if not profile:
                continue
            current_evidence = (profile.website or "", salient_snapshot(dumps(profile_google_snapshot(profile))))
            if old_evidence.get(match.place_id) != current_evidence:
                evidence_changed = True
                break
    if evidence_changed:
        lead = session.get(Lead, lead_id)
        if lead:
            if old_ids:
                invalidate_verification(session, lead, {"competitors", "outreach"}, "Competitor comparison evidence changed")
            from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

            recompute_lead_commercial_candidate(session, lead, "Competitor comparison evidence changed")

def profile_google_snapshot(profile: BusinessProfile) -> dict[str, Any]:
    return {
        "place_id": profile.place_id,
        "name": profile.name,
        "business_status": profile.business_status,
        "primary_type": profile.primary_type,
        "types": profile.business_types,
        "rating": profile.rating,
        "review_count": profile.review_count,
        "website": bool(profile.website),
        "phone": bool(profile.phone or profile.international_phone),
        "hours": profile.has_hours,
        "photo_count": profile.photo_count,
        "pure_service_area_business": profile.pure_service_area_business,
        "retrieved_at": profile.retrieved_at,
        "details_retrieved": profile.google_details_retrieved,
        "detail_fields_requested": bool(profile.raw.get("_detail_fields_requested", profile.google_details_retrieved)),
        "selected_for_details": bool(profile.raw.get("_selected_for_details", profile.google_details_retrieved)),
        "preliminary_candidate_score": profile.raw.get("_preliminary_candidate_score"),
        "preliminary_rank": profile.raw.get("_preliminary_rank"),
    }


def get_google_presence_assessment(session: Session, lead_id: int) -> GooglePresenceAssessment | None:
    return session.execute(
        select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead_id)
    ).scalar_one_or_none()


def save_outreach_draft(
    session: Session,
    lead_id: int,
    kind: OutreachKind,
    subject: str,
    body: str,
    approved: bool = False,
    proof_dependencies: list[dict[str, Any]] | None = None,
    *,
    sender: SenderInfo | None = None,
    commercial_snapshot: dict[str, Any] | None = None,
) -> OutreachDraft:
    if commercial_snapshot is None:
        # Manual draft entry remains supported, but it cannot bypass the same
        # fresh commercial plan required by generated outreach.
        lead_for_plan = session.get(Lead, lead_id)
        if lead_for_plan is not None:
            cached = loads(lead_for_plan.commercial_plan_snapshot_json, {})
            from local_presence_miner.services.commercial_state_service import current_plan_dependency_errors

            if (
                lead_for_plan.commercial_plan_state == "current"
                and cached
                and not current_plan_dependency_errors(session, lead_for_plan)
            ):
                commercial_snapshot = cached
            else:
                from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
                from local_presence_miner.services.commercial_state_service import persist_current_plan

                plan_competitors = list(
                    session.scalars(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead_id))
                )
                _plan, plan_pricing, plan_context = build_adaptive_sales_plan_with_context(
                    session, lead_for_plan, competitors=plan_competitors
                )
                commercial_snapshot = persist_current_plan(
                    session, lead_for_plan, competitors=plan_competitors, pricing=plan_pricing, context=plan_context
                ).to_dict()
    draft = session.execute(select(OutreachDraft).where(OutreachDraft.lead_id == lead_id, OutreachDraft.kind == kind.value)).scalar_one_or_none()
    if draft is None:
        draft = OutreachDraft(lead_id=lead_id, kind=kind.value)
        session.add(draft)
    else:
        if (
            not draft.approved
            and proof_dependencies is not None
            and draft.dependency_state in {"manual_review_required", "manually_revalidated"}
        ):
            # A human's unapproved edit is not a generated cache. Keep the
            # exact body for review instead of silently replacing it during a
            # Search Market or seller-proof driven Smart Offer refresh.
            return draft
        lead = session.get(Lead, lead_id)
        if (
            draft.approval_revoked_reason
            and lead is not None
            and lead_contact_readiness_errors(session, lead)
        ):
            # Current lead viability outranks automatic asset refresh. Keep the
            # exact previously approved copy visible while the lead is blocked;
            # the immutable approval-history row is the second line of defense.
            return draft
    if draft.approved and approved:
        if subject != draft.subject or body != draft.body:
            edit_outreach_draft(session, draft.id, subject, body)
            raise ValueError("Editing approved text invalidates its evidence snapshot. Revalidate the edited draft before approval.")
        set_outreach_approval(session, draft.id, True, sender=sender)
        return draft
    elif draft.approved and not approved:
        # Human-approved outbound is immutable during automatic regeneration.
        # A stale structured proof dependency is the one exception: preserve the
        # approved copy in history, revoke it, then allow the replacement draft.
        dependency_assessment = assess_dependencies(session, parse_dependencies(draft.proof_dependencies_json))
        from local_presence_miner.services.commercial_state_service import draft_commercial_errors

        commercial_errors = draft_commercial_errors(session, draft)
        if dependency_assessment.valid and not commercial_errors:
            return draft
        if not draft.approved:
            # A freshness check just revoked approval. Keep the human-approved
            # body in the current draft as well as immutable approval history.
            return draft
        revoke_outreach_approval(session, draft, " ".join((*dependency_assessment.reasons, *commercial_errors)))
    draft.subject = subject
    draft.body = body
    draft.approved = False
    dependencies = proof_dependencies or []
    draft.proof_dependencies_json = dumps(dependencies)
    draft.proof_dependency_fingerprint = dependency_set_fingerprint(dependencies)
    draft.dependency_state = "generated" if proof_dependencies is not None else "manual_review_required"
    draft.dependency_body_fingerprint = body_fingerprint(subject, body) if proof_dependencies is not None else ""
    draft.approval_snapshot_json = "{}"
    snapshot = commercial_snapshot or {}
    draft.commercial_snapshot_json = dumps(snapshot)
    draft.commercial_dependency_fingerprint = str(snapshot.get("dependency_fingerprint") or "")
    draft.commercial_output_fingerprint = str(snapshot.get("output_fingerprint") or "")
    draft.commercial_dependency_state = "current" if commercial_snapshot is not None else "stale"
    draft.commercial_plan_revision = int(getattr(session.get(Lead, lead_id), "commercial_plan_revision", 0) or 0)
    draft.updated_at = utc_now()
    session.flush()
    if approved:
        set_outreach_approval(session, draft.id, True, sender=sender)
    return draft


def list_leads(session: Session) -> list[Lead]:
    return list(session.execute(select(Lead).order_by(Lead.sales_priority_score.desc(), Lead.lead_score.desc(), Lead.name)).scalars())


def get_lead(session: Session, lead_id: int) -> Lead | None:
    return session.get(Lead, lead_id)


def update_lead_status(session: Session, lead_id: int, status: LeadStatus | str) -> None:
    lead = session.get(Lead, lead_id)
    if not lead:
        return
    value = status.value if isinstance(status, LeadStatus) else status
    if value == LeadStatus.APPROVED_TO_CONTACT.value:
        raise ValueError("Approve an exact outreach draft in Outreach or Lead Detail; a status change cannot bypass approval validation.")
    if (lead.suppressed or is_suppressed(session, lead)) and value not in OUTREACH_BLOCKED_STATUSES:
        # There is no authorized unsuppression workflow in this release.  A
        # status edit therefore cannot make an explicit DNC look contactable.
        lead.suppressed = True
        lead.status = LeadStatus.DO_NOT_CONTACT.value
        log_activity(session, "status_change_blocked", f"Suppression preserved while attempting {value}", lead_id)
        return
    if (lead.suppressed or lead.status in OUTREACH_BLOCKED_STATUSES) and value == LeadStatus.APPROVED_TO_CONTACT.value:
        raise ValueError("Suppressed leads cannot be approved for contact.")
    if value in OUTREACH_BLOCKED_STATUSES:
        apply_do_not_contact(session, lead, f"Lead status changed to {value}")
        lead.status = value
    else:
        lead.status = value
    lead.updated_at = utc_now()
    log_activity(session, "status_changed", f"Status changed to {value}", lead_id)


def apply_do_not_contact(session: Session, lead: Lead, reason: str) -> None:
    """The sole explicit DNC transition for every current entry point.

    It writes the lead identity plus currently stored public contact identities,
    revokes any approved outreach, and makes the lead's persisted state agree
    with the suppression ledger.  Nothing infers DNC from ordinary outcomes.
    """
    add_lead_suppression(session, lead.id, reason)
    values = [lead.phone, lead.website] + [point.value for point in list_contact_points(session, lead.id)]
    for value in values:
        if value:
            add_suppression(session, value, reason)
    lead.suppressed = True
    lead.status = LeadStatus.DO_NOT_CONTACT.value
    for draft in session.scalars(
        select(OutreachDraft).where(OutreachDraft.lead_id == lead.id, OutreachDraft.approved.is_(True))
    ):
        revoke_outreach_approval(session, draft, reason)
    lead.updated_at = utc_now()
    log_activity(session, "lead_do_not_contact", reason, lead.id)


def is_explicit_do_not_contact_outcome(outcome: str, next_action: str = "") -> bool:
    """Only exact, operator-confirmed DNC language changes contact permission."""
    normalized = " ".join((outcome or "").casefold().split())
    action = " ".join((next_action or "").casefold().split())
    return normalized in {"do not contact", "do not contact me again"} or action == "do not contact"


def invalidate_verification(session: Session, lead: Lead, keys: set[str], reason: str) -> None:
    values = loads(lead.verification_json, {})
    changed = False
    for key in keys:
        if values.get(key):
            values[key] = False
            changed = True
    if not changed:
        return
    lead.verification_json = dumps(values)
    revoked = 0
    for draft in session.execute(select(OutreachDraft).where(OutreachDraft.lead_id == lead.id, OutreachDraft.approved.is_(True))).scalars():
        if outreach_verification_assessment(session, lead, draft).missing_required:
            revoked += int(revoke_outreach_approval(session, draft, reason))
    log_activity(session, "verification_invalidated", f"{reason}: {', '.join(sorted(keys))}", lead.id)


def update_lead_fields(session: Session, lead_id: int, **fields: str) -> None:
    protected_disposition_fields = {
        "commercial_disposition",
        "commercial_disposition_revision",
        "disposition_not_before",
        "follow_up_permission",
    }
    if protected_disposition_fields.intersection(fields):
        raise ValueError("Commercial disposition fields must be changed through DispositionService.")
    if fields.get("status") == LeadStatus.APPROVED_TO_CONTACT.value:
        raise ValueError("Approve an exact outreach draft; direct field updates cannot grant contact approval.")
    lead = session.get(Lead, lead_id)
    if not lead:
        return
    before = {key: getattr(lead, key, None) for key in fields if hasattr(lead, key)}
    for key, value in fields.items():
        if hasattr(lead, key):
            setattr(lead, key, value)

    invalid: set[str] = set()
    changed = {key for key, old in before.items() if old != getattr(lead, key, None)}
    if changed & {"name", "address"}:
        invalid |= {"business_identity", "outreach"}
    if "phone" in changed:
        invalid |= {"phone", "outreach"}
    if changed & {"website", "yelp_url"}:
        invalid |= {"website", "audit_claims", "outreach"}
    if "google_maps_url" in changed:
        invalid |= {"google_url", "outreach"}
    if changed & {"recommended_offer", "recommended_offer_id", "starting_offer_json", "target_zip_code", "target_radius_miles", "past_sales_notes"}:
        invalid |= {"offer", "price", "outreach"}
    if invalid:
        invalidate_verification(session, lead, invalid, "Lead fields changed")
    if changed & {
        "name", "recommended_offer", "recommended_offer_id", "category", "website", "target_signals_json",
        "google_public_data_json", "lead_score", "sales_priority_score", "qualification_json",
        "qualification_class", "qualification_confidence",
    }:
        from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

        recompute_lead_commercial_candidate(session, lead, "Commercial planning input changed")

    if "verification_json" in fields:
        session.flush()
        revoked = 0
        for draft in session.execute(select(OutreachDraft).where(OutreachDraft.lead_id == lead_id, OutreachDraft.approved.is_(True))).scalars():
            if outreach_verification_assessment(session, lead, draft).missing_required:
                revoked += int(revoke_outreach_approval(session, draft, "Required verification changed"))
        if revoked:
            log_activity(session, "outreach_approval_revoked", f"Unapproved {revoked} draft(s) after required verification changed", lead_id)
    invalidate_contact_readiness(session, lead, "Current lead viability changed")
    lead.updated_at = utc_now()
    log_activity(session, "lead_updated", "Updated lead fields", lead_id)


def lead_contact_readiness_errors(session: Session, lead: Lead) -> tuple[str, ...]:
    """Compatibility wrapper over the canonical B1 eligibility service.

    Existing consumers treat any non-eligible state as a reason to stop current
    Live/copy/approval/export behavior. New code may inspect the reason-coded
    result directly through ``OutreachEligibilityService``.
    """
    from local_presence_miner.domain.enums import EligibilityState
    from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService

    result = OutreachEligibilityService().evaluate(session, lead)
    if result.state is EligibilityState.ELIGIBLE_FOR_HUMAN_REVIEW:
        return ()
    return result.reasons


def invalidate_contact_readiness(session: Session, lead: Lead, reason: str) -> int:
    """Revoke approval when current lead viability no longer permits contact."""
    blockers = lead_contact_readiness_errors(session, lead)
    if not blockers:
        return 0
    detail = f"{reason}: {' '.join(blockers)}"
    revoked = 0
    drafts = session.execute(
        select(OutreachDraft).where(OutreachDraft.lead_id == lead.id, OutreachDraft.approved.is_(True))
    ).scalars()
    for draft in drafts:
        revoked += int(revoke_outreach_approval(session, draft, detail))
    return revoked

def outreach_approval_errors(session: Session, draft: OutreachDraft, sender: SenderInfo) -> tuple[str, ...]:
    """Canonical validator for repository approval, UI approval, copy, and ready export."""
    errors: list[str] = []
    lead = session.get(Lead, draft.lead_id)
    if lead is None:
        return ("The draft's lead no longer exists.",)
    errors.extend(lead_contact_readiness_errors(session, lead))
    assessment = outreach_verification_assessment(session, lead, draft)
    if assessment.missing_required:
        errors.append("Verification incomplete. Confirm: " + format_missing_requirements(assessment.missing_required))
    outbound = validate_outbound_draft(sender, draft.kind, draft.subject, draft.body)
    errors.extend(outbound.reasons)
    if draft.dependency_state not in {"generated", "manually_revalidated"}:
        errors.append("Seller Proof dependencies are unknown or invalidated; regenerate or explicitly revalidate the edited draft.")
    if draft.dependency_body_fingerprint != body_fingerprint(draft.subject, draft.body):
        errors.append("Draft text changed after dependency validation; revalidate this exact body.")
    dependencies = parse_dependencies(draft.proof_dependencies_json)
    raw_dependencies = loads(draft.proof_dependencies_json, None)
    if not isinstance(raw_dependencies, list) or len(raw_dependencies) != len(dependencies):
        errors.append("The evidence-dependency document is malformed and requires revalidation.")
    if draft.proof_dependency_fingerprint != dependency_set_fingerprint(dependencies):
        errors.append("The stored evidence-dependency fingerprint is invalid.")
    errors.extend(assess_dependencies(session, dependencies).reasons)
    from local_presence_miner.services.commercial_state_service import draft_commercial_errors

    errors.extend(draft_commercial_errors(session, draft))
    return tuple(dict.fromkeys(errors))


def set_outreach_approval(session: Session, draft_id: int, approved: bool, *, sender: SenderInfo | None = None) -> None:
    draft = session.get(OutreachDraft, draft_id)
    if not draft:
        return
    lead = session.get(Lead, draft.lead_id)
    if not lead:
        return
    if not approved and draft.approved:
        revoke_outreach_approval(session, draft, "Operator removed approval")
        return
    if approved:
        errors = outreach_approval_errors(session, draft, sender or SenderInfo())
        if errors:
            raise ValueError("Approval blocked. " + " ".join(errors))
    approval_time = utc_now()
    draft.approved = approved
    draft.approved_at = approval_time if approved else None
    if approved:
        draft.approval_revoked_reason = ""
        draft.approval_revoked_at = None
        draft.approval_snapshot_json = dumps({
            "policy_version": "0.1.13",
            "approved_at": approval_time.isoformat(),
            "body_fingerprint": draft.dependency_body_fingerprint,
            "dependency_state": draft.dependency_state,
            "dependencies": parse_dependencies(draft.proof_dependencies_json),
            "dependency_fingerprint": draft.proof_dependency_fingerprint,
            "commercial_snapshot": loads(draft.commercial_snapshot_json, {}),
            "commercial_dependency_fingerprint": draft.commercial_dependency_fingerprint,
            "commercial_output_fingerprint": draft.commercial_output_fingerprint,
        })
    draft.updated_at = utc_now()
    if approved and lead.status in {
        LeadStatus.NEW.value,
        LeadStatus.NEEDS_REVIEW.value,
        LeadStatus.QUALIFIED.value,
        LeadStatus.OUTREACH_DRAFTED.value,
    }:
        lead.status = LeadStatus.APPROVED_TO_CONTACT.value
        lead.updated_at = utc_now()
    log_activity(
        session,
        "outreach_approval_changed",
        f"{'Approved' if approved else 'Unapproved'} {draft.kind}",
        lead.id,
    )


def revoke_outreach_approval(session: Session, draft: OutreachDraft, reason: str) -> bool:
    """Preserve an approved body for audit/history, then revoke its approval."""
    if not draft.approved:
        return False
    session.add(
        OutreachApprovalHistory(
            outreach_draft_id=draft.id,
            lead_id=draft.lead_id,
            kind=draft.kind,
            subject=draft.subject,
            body=draft.body,
            proof_dependencies_json=draft.proof_dependencies_json,
            proof_dependency_fingerprint=draft.proof_dependency_fingerprint,
            approval_snapshot_json=draft.approval_snapshot_json if draft.approval_snapshot_json not in {"", "{}"} else dumps({
                "dependency_state": draft.dependency_state,
                "body_fingerprint": body_fingerprint(draft.subject, draft.body),
                "dependencies": parse_dependencies(draft.proof_dependencies_json),
                "historical_approval_time": "unknown",
            }),
            commercial_snapshot_json=draft.commercial_snapshot_json,
            commercial_dependency_fingerprint=draft.commercial_dependency_fingerprint,
            commercial_output_fingerprint=draft.commercial_output_fingerprint,
            revocation_reason=reason,
        )
    )
    draft.approved = False
    draft.approved_at = None
    draft.approval_revoked_reason = reason
    draft.approval_revoked_at = utc_now()
    draft.updated_at = utc_now()
    lead = session.get(Lead, draft.lead_id)
    if lead is not None and lead.status == LeadStatus.APPROVED_TO_CONTACT.value:
        lead.status = LeadStatus.NEEDS_REVIEW.value
        lead.updated_at = utc_now()
    log_activity(session, "outreach_approval_revoked", f"Revoked {draft.kind}: {reason}", draft.lead_id)
    return True


def invalidate_approved_outreach_for_proof(session: Session, proof_id: int, reason: str) -> int:
    """Revoke only drafts with a structured dependency on the changed proof record."""
    revoked = 0
    drafts = session.execute(select(OutreachDraft).where(OutreachDraft.approved.is_(True))).scalars()
    for draft in drafts:
        dependencies = parse_dependencies(draft.proof_dependencies_json)
        if any(dependency.get("proof_id") == proof_id for dependency in dependencies):
            revoked += int(revoke_outreach_approval(session, draft, reason))
    return revoked


def edit_outreach_draft(session: Session, draft_id: int, subject: str, body: str) -> OutreachDraft:
    draft = session.get(OutreachDraft, draft_id)
    if draft is None:
        raise ValueError("Draft no longer exists.")
    revoke_outreach_approval(session, draft, "Draft text was edited after approval")
    draft.subject = subject
    draft.body = body
    draft.approved = False
    draft.dependency_state = "manual_review_required"
    draft.dependency_body_fingerprint = ""
    draft.proof_dependencies_json = "[]"
    draft.proof_dependency_fingerprint = ""
    draft.approval_snapshot_json = "{}"
    draft.updated_at = utc_now()
    log_activity(session, "outreach_draft_edited", "Manual edit invalidated prior proof dependencies; revalidation required", draft.lead_id)
    return draft


def revalidate_outreach_evidence(session: Session, draft_id: int, proof_ids: list[int], *, operator_confirmed: bool) -> None:
    """Bind an operator-reviewed dependency set to the exact edited body; never approve it."""
    if not operator_confirmed:
        raise ValueError("Explicit operator review of this exact text and its proof usage is required.")
    draft = session.get(OutreachDraft, draft_id)
    if draft is None:
        raise ValueError("Draft no longer exists.")
    dependencies = []
    for proof_id in sorted(set(proof_ids)):
        proof = session.get(SellerProof, proof_id)
        if proof is None:
            raise ValueError(f"Seller Proof #{proof_id} no longer exists; no replacement was substituted.")
        usages = {usage for usage in PERMISSION_FIELDS if proof_allows_external_use(proof, usage)}
        if not usages:
            raise ValueError(f"Seller Proof #{proof_id} has no verified, permitted external use.")
        dependencies.append(make_proof_dependency(proof, usages))
    revoke_outreach_approval(session, draft, "Evidence dependencies were manually revalidated")
    draft.proof_dependencies_json = dumps(dependencies)
    draft.proof_dependency_fingerprint = dependency_set_fingerprint(dependencies)
    draft.dependency_body_fingerprint = body_fingerprint(draft.subject, draft.body)
    draft.dependency_state = "manually_revalidated"
    draft.approval_snapshot_json = "{}"
    draft.updated_at = utc_now()
    log_activity(session, "outreach_evidence_revalidated", f"Operator reviewed exact body with {len(dependencies)} proof dependency record(s)", draft.lead_id)


def outreach_verification_assessment(session: Session, lead: Lead, draft: OutreachDraft):
    draft_text = f"{draft.subject} {draft.body}"
    return assess_verification(
        lead,
        draft_kind=draft.kind,
        draft_text=draft_text,
        competitor_claims=None,
    )


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\\D+", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


def _canonical_domain(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _suppression_identity(value: str) -> str:
    text = (value or "").strip()
    lowered = text.casefold()
    if not text:
        return ""
    if re.match(r"^(lead|place|email|phone|domain|name):", lowered):
        kind, raw = lowered.split(":", 1)
        if kind == "phone":
            raw = _normalize_phone(raw)
        elif kind == "domain":
            raw = _canonical_domain(raw)
        return f"{kind}:{raw.strip()}"
    if "@" in text and " " not in text:
        return "email:" + lowered
    if _normalize_phone(text) and len(_normalize_phone(text)) >= 7 and not re.search(r"[A-Za-z]", text):
        return "phone:" + _normalize_phone(text)
    if "." in text or "://" in text:
        domain = _canonical_domain(text)
        if domain:
            return "domain:" + domain
    return "name:" + lowered


def suppression_identities_for_lead(session: Session, lead: Lead) -> set[str]:
    identities = {f"lead:{lead.id}"}
    if lead.place_id:
        identities.add("place:" + lead.place_id.casefold())
    if lead.name:
        identities.add("name:" + lead.name.strip().casefold())
    if lead.phone:
        phone = _normalize_phone(lead.phone)
        if phone:
            identities.add("phone:" + phone)
    if lead.website:
        domain = _canonical_domain(lead.website)
        if domain:
            identities.add("domain:" + domain)
    for point in session.execute(select(ContactPoint).where(ContactPoint.lead_id == lead.id)).scalars():
        identity = _suppression_identity(point.value)
        if identity:
            identities.add(identity)
    return identities


def _apply_suppression_to_matching_leads(session: Session, normalized: str) -> None:
    for lead in session.execute(select(Lead)).scalars():
        if normalized not in suppression_identities_for_lead(session, lead):
            continue
        lead.suppressed = True
        lead.status = LeadStatus.DO_NOT_CONTACT.value
        for draft in session.execute(select(OutreachDraft).where(OutreachDraft.lead_id == lead.id, OutreachDraft.approved.is_(True))).scalars():
            revoke_outreach_approval(session, draft, f"Suppression matched {normalized}")


def add_suppression(session: Session, value: str, reason: str = "") -> SuppressionEntry:
    normalized = _suppression_identity(value)
    if not normalized:
        raise ValueError("Suppression value is required.")
    entry = session.execute(select(SuppressionEntry).where(SuppressionEntry.value == normalized)).scalar_one_or_none()
    if entry is None:
        entry = SuppressionEntry(value=normalized, reason=reason)
        session.add(entry)
    _apply_suppression_to_matching_leads(session, normalized)
    log_activity(session, "suppression_added", f"Added suppression entry {normalized}")
    return entry


def add_lead_suppression(session: Session, lead_id: int, reason: str = "") -> SuppressionEntry:
    return add_suppression(session, f"lead:{lead_id}", reason)


def is_suppressed(session: Session, lead: Lead) -> bool:
    identities = suppression_identities_for_lead(session, lead)
    entries = {_suppression_identity(entry.value) for entry in session.execute(select(SuppressionEntry)).scalars()}
    return bool(identities & entries)

def log_activity(session: Session, action: str, message: str, lead_id: int | None = None) -> None:
    session.add(ActivityLog(lead_id=lead_id, action=action, message=message))


def list_contact_interactions(session: Session, lead_id: int) -> list[ContactInteraction]:
    return list(
        session.execute(
            select(ContactInteraction)
            .where(ContactInteraction.lead_id == lead_id)
            .order_by(ContactInteraction.interaction_datetime.desc(), ContactInteraction.id.desc())
        ).scalars()
    )


def _validate_guided_call_capture(
    identity: dict[str, object] | None, sequence: list[dict[str, object]] | None
) -> None:
    required = {
        "schema_version",
        "tree_id",
        "tree_version",
        "recommended_node_id",
        "selected_node_id",
        "strategy_id",
        "response_version",
        "response_fingerprint",
        "response_snapshot",
        "usage_state",
        "rescue_id",
    }
    allowed_usage = {"displayed", "copied", "used"}

    def validate_record(record: dict[str, object], *, event_record: bool) -> None:
        expected = required | ({"event", "sequence"} if event_record else set())
        missing = expected - set(record)
        if missing:
            raise ValueError(f"Guided Call identity is missing required fields: {sorted(missing)}")
        if record.get("schema_version") != 1:
            raise ValueError("Guided Call identity schema version is invalid.")
        if record.get("usage_state") not in allowed_usage:
            raise ValueError("Guided Call usage state is invalid.")
        tree_id = str(record.get("tree_id") or "")
        tree_version = str(record.get("tree_version") or "")
        recommended_node_id = str(record.get("recommended_node_id") or "")
        selected_node_id = str(record.get("selected_node_id") or "")
        strategy_id = str(record.get("strategy_id") or "")
        rescue_id = str(record.get("rescue_id") or "")
        response_snapshot = str(record.get("response_snapshot") or "")
        response_version = record.get("response_version")
        if not tree_id or not tree_version:
            raise ValueError("Guided Call tree identity is required.")
        if not recommended_node_id or not strategy_id:
            raise ValueError("Guided Call node and strategy identity are required.")
        if not rescue_id and not selected_node_id:
            raise ValueError("Guided Call selected-node identity is required for a non-rescue reply.")
        if rescue_id and recommended_node_id != rescue_id:
            raise ValueError("Guided Call rescue identity is inconsistent.")
        if not isinstance(response_version, int) or isinstance(response_version, bool) or response_version < 1:
            raise ValueError("Guided Call response version is invalid.")
        expected_fingerprint = fingerprint(
            {
                "tree_id": tree_id,
                "tree_version": tree_version,
                "node_id": recommended_node_id,
                "response_version": response_version,
                "response": response_snapshot,
            }
        )
        if record.get("response_fingerprint") != expected_fingerprint:
            raise ValueError("Guided Call response fingerprint does not match its persisted snapshot.")
        if event_record and not str(record.get("event") or ""):
            raise ValueError("Guided Call event identity is required.")

    if identity:
        validate_record(identity, event_record=False)
    if sequence is None:
        return
    expected_sequence = 1
    for event in sequence:
        validate_record(event, event_record=True)
        if event.get("sequence") != expected_sequence:
            raise ValueError("Guided Call event sequence must be contiguous and ordered.")
        expected_sequence += 1
    if identity and not sequence:
        raise ValueError("Guided Call identity requires its auditable event sequence.")
    if identity and sequence:
        last_event = sequence[-1]
        if any(last_event.get(key) != identity.get(key) for key in required):
            raise ValueError("Guided Call current identity must match the final auditable event.")


def save_contact_interaction(
    session: Session,
    lead_id: int,
    *,
    interaction_datetime: str,
    method: str,
    direction: str,
    outcome: str,
    notes: str,
    follow_up_date: str = "",
    outreach_draft_id: int | None = None,
    interaction_id: int | None = None,
    response_signals: list[str] | None = None,
    objection: str = "",
    contact_name: str = "",
    contact_role: str = "",
    decision_maker_status: str = "Unknown",
    business_goal: str = "",
    capacity_status: str = "",
    buyer_questions: list[str] | None = None,
    commitments: list[str] | None = None,
    branch_path: list[str] | None = None,
    guided_call_identity: dict[str, object] | None = None,
    guided_call_sequence: list[dict[str, object]] | None = None,
    next_action: str = "",
    credibility_concern: bool = False,
    wants_examples: bool = False,
    wants_references: bool = False,
    concerned_about_ai: bool = False,
    wants_proof: bool = False,
    seller_experience_question: bool = False,
    local_presence_question: bool = False,
    decision_maker_skeptical: bool = False,
    legitimacy_concern: bool = False,
) -> ContactInteraction:
    canonical_datetime = canonical_interaction_datetime(interaction_datetime)
    canonical_follow_up = canonical_follow_up_date(follow_up_date)
    if outreach_draft_id is not None:
        draft = session.get(OutreachDraft, outreach_draft_id)
        if not draft or draft.lead_id != lead_id:
            raise ValueError("The linked outreach draft does not belong to this lead.")
    outcome = outcome.strip()
    if not outcome:
        raise ValueError("Choose or type the truthful contact outcome before saving.")
    if guided_call_identity is not None and not isinstance(guided_call_identity, dict):
        raise ValueError("Guided Call identity must be a structured object.")
    if guided_call_sequence is not None and (
        not isinstance(guided_call_sequence, list) or not all(isinstance(item, dict) for item in guided_call_sequence)
    ):
        raise ValueError("Guided Call sequence must be a structured event list.")
    _validate_guided_call_capture(guided_call_identity, guided_call_sequence)
    interaction = session.get(ContactInteraction, interaction_id) if interaction_id else None
    previous_semantics = None
    write_canonical_semantics = False
    if interaction is None:
        from local_presence_miner.services.conversation_state_service import SEMANTIC_CAPTURE_VERSION

        interaction = ContactInteraction(
            lead_id=lead_id,
            interaction_datetime=canonical_datetime,
            semantic_capture_version=SEMANTIC_CAPTURE_VERSION,
        )
        session.add(interaction)
        write_canonical_semantics = True
        action = "contact_interaction_added"
    else:
        from local_presence_miner.services.conversation_state_service import (
            SEMANTIC_CAPTURE_VERSION,
            ConversationStateService,
        )

        # Editing a pre-B1 row is not, by itself, an explicit semantic review.
        # Keep it legacy/raw until a future reviewed mapping/correction action.
        write_canonical_semantics = (interaction.semantic_capture_version or "").strip() == SEMANTIC_CAPTURE_VERSION
        if write_canonical_semantics:
            previous_semantics = ConversationStateService.semantic_snapshot(interaction)
        action = "contact_interaction_updated"
    if interaction.lead_id != lead_id:
        raise ValueError("The selected interaction belongs to another lead.")
    interaction.interaction_datetime = canonical_datetime
    interaction.method = method
    interaction.direction = direction
    interaction.outcome = outcome
    interaction.response_signals_json = dumps(response_signals or [])
    interaction.objection = objection.strip()
    interaction.contact_name = contact_name.strip()
    interaction.contact_role = contact_role.strip()
    interaction.decision_maker_status = decision_maker_status.strip() or "Unknown"
    interaction.business_goal = business_goal.strip()
    interaction.capacity_status = capacity_status.strip()
    interaction.buyer_questions_json = dumps(buyer_questions or [])
    interaction.commitments_json = dumps(commitments or [])
    interaction.branch_path_json = dumps(branch_path or [])
    if guided_call_identity is not None:
        interaction.guided_call_identity_json = dumps(guided_call_identity)
    if guided_call_sequence is not None:
        interaction.guided_call_sequence_json = dumps(guided_call_sequence)
    interaction.next_action = next_action.strip()
    interaction.credibility_concern = bool(credibility_concern)
    interaction.wants_examples = bool(wants_examples)
    interaction.wants_references = bool(wants_references)
    interaction.concerned_about_ai = bool(concerned_about_ai)
    interaction.wants_proof = bool(wants_proof)
    interaction.seller_experience_question = bool(seller_experience_question)
    interaction.local_presence_question = bool(local_presence_question)
    interaction.decision_maker_skeptical = bool(decision_maker_skeptical)
    interaction.legitimacy_concern = bool(legitimacy_concern)
    interaction.notes = notes
    interaction.follow_up_date = canonical_follow_up
    interaction.outreach_draft_id = outreach_draft_id
    lead = session.get(Lead, lead_id)
    if lead is not None:
        interaction.commercial_snapshot_json = lead.commercial_plan_snapshot_json
        interaction.commercial_dependency_fingerprint = lead.commercial_dependency_fingerprint
    if outreach_draft_id is not None:
        linked_draft = session.get(OutreachDraft, outreach_draft_id)
        interaction.linked_outreach_snapshot_json = linked_draft.commercial_snapshot_json if linked_draft is not None else "{}"
    session.flush()
    if write_canonical_semantics:
        from local_presence_miner.services.conversation_state_service import ConversationStateService

        ConversationStateService().record_interaction_summary(session, interaction, previous=previous_semantics)
    recalculate_contact_summary(session, lead_id)
    lead = session.get(Lead, lead_id)
    if lead is not None:
        # B2 assertions are consumed by the existing B04 commercial snapshot.
        # Reuse its candidate recomputation rather than adding another event or
        # freshness path.  A later explicit refresh creates the new snapshot.
        from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

        recompute_lead_commercial_candidate(session, lead, "Current conversation state changed")
    if lead is not None and is_explicit_do_not_contact_outcome(interaction.outcome, interaction.next_action):
        apply_do_not_contact(session, lead, "Explicit Do Not Contact recorded in contact outcome")
    log_activity(session, action, f"{method} {direction}: {outcome or 'no outcome recorded'}", lead_id)
    return interaction


def delete_contact_interaction(session: Session, interaction_id: int) -> None:
    interaction = session.get(ContactInteraction, interaction_id)
    if not interaction:
        return
    lead_id = interaction.lead_id
    # Privacy/delete semantics: canonical child assertions tied to the deleted
    # interaction must not retain content that the operator deliberately removed.
    # A later assertion may explicitly supersede one of these rows; preserve that
    # later interaction while detaching its now-deleted historical pointer.
    assertions = list(
        session.scalars(
            select(ConversationAssertion).where(ConversationAssertion.interaction_id == interaction_id)
        )
    )
    deleting_ids = {row.id for row in assertions if row.id is not None}
    if deleting_ids:
        for child in session.scalars(
            select(ConversationAssertion).where(ConversationAssertion.supersedes_assertion_id.in_(deleting_ids))
        ):
            if child.id not in deleting_ids:
                child.supersedes_assertion_id = None
        for assertion in assertions:
            session.delete(assertion)
    # Commercial disposition history is append-only audit evidence. If its
    # optional source interaction is deleted, preserve the disposition record
    # but detach the now-removed interaction reference rather than leaving a
    # dangling foreign key/provenance pointer.
    for record in session.scalars(
        select(CommercialDispositionRecord).where(CommercialDispositionRecord.source_interaction_id == interaction_id)
    ):
        record.source_interaction_id = None
    session.delete(interaction)
    session.flush()
    recalculate_contact_summary(session, lead_id)
    lead = session.get(Lead, lead_id)
    if lead is not None:
        from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

        recompute_lead_commercial_candidate(session, lead, "Current conversation state changed after interaction deletion")
    log_activity(session, "contact_interaction_deleted", f"Deleted interaction #{interaction_id}", lead_id)


def canonical_interaction_datetime(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("Interaction date/time is required.")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Interaction date/time must use ISO format YYYY-MM-DDTHH:MM.") from exc
    return parsed.isoformat(timespec="minutes")


def canonical_follow_up_date(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("Follow-up date must use ISO format YYYY-MM-DD.") from exc


def recalculate_contact_summary(session: Session, lead_id: int) -> None:
    lead = session.get(Lead, lead_id)
    if not lead:
        return
    interactions = list(session.execute(select(ContactInteraction).where(ContactInteraction.lead_id == lead_id)).scalars())
    valid: list[tuple[datetime, int, ContactInteraction]] = []
    for interaction in interactions:
        try:
            parsed = datetime.fromisoformat(interaction.interaction_datetime)
        except (TypeError, ValueError):
            continue
        valid.append((parsed, interaction.id or 0, interaction))
    latest = max(valid, default=None, key=lambda item: (item[0], item[1]))
    if latest is None:
        lead.last_contacted_date = ""
        lead.contact_method = ""
        lead.contact_outcome = ""
        lead.next_follow_up_date = ""
    else:
        interaction = latest[2]
        lead.last_contacted_date = latest[0].date().isoformat()
        lead.contact_method = interaction.method
        lead.contact_outcome = interaction.outcome
        lead.next_follow_up_date = interaction.follow_up_date
        protected = {
            LeadStatus.MEETING_SCHEDULED.value,
            LeadStatus.WON.value,
            LeadStatus.LOST.value,
            LeadStatus.OPTED_OUT.value,
            LeadStatus.DO_NOT_CONTACT.value,
        }
        if lead.status not in protected:
            lead.status = LeadStatus.REPLIED.value if interaction.direction == "Inbound" else LeadStatus.CONTACTED.value

    # Canonical disposition owns whether a deferred follow-up date is actionable.
    # Legacy interaction dates cannot authorize a callback when permission is
    # unknown or not agreed.
    if (lead.commercial_disposition or "").strip().upper() == "DEFERRED":
        if (lead.follow_up_permission or "").strip().upper() == "AGREED" and (lead.disposition_not_before or "").strip():
            lead.next_follow_up_date = lead.disposition_not_before
        else:
            lead.next_follow_up_date = ""
    lead.updated_at = utc_now()


def dashboard_stats(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count(Lead.id))) or 0
    unreviewed_statuses = [LeadStatus.NEW.value, LeadStatus.NEEDS_REVIEW.value]
    unreviewed = session.scalar(select(func.count(Lead.id)).where(Lead.status.in_(unreviewed_statuses))) or 0
    high_priority = session.scalar(select(func.count(Lead.id)).where(Lead.priority == "A")) or 0
    approved = session.scalar(select(func.count(OutreachDraft.id)).where(OutreachDraft.approved.is_(True))) or 0
    contacted = session.scalar(select(func.count(Lead.id)).where(Lead.status == LeadStatus.CONTACTED.value)) or 0
    reply_statuses = [LeadStatus.REPLIED.value, LeadStatus.MEETING_SCHEDULED.value]
    replies = session.scalar(select(func.count(Lead.id)).where(Lead.status.in_(reply_statuses))) or 0
    opt_outs = session.scalar(select(func.count(Lead.id)).where(Lead.status == LeadStatus.OPTED_OUT.value)) or 0
    searches = session.scalar(select(func.count(LeadSearch.id)).where(LeadSearch.completed.is_(True))) or 0
    avg_score = session.scalar(select(func.avg(Lead.lead_score))) or 0
    return {
        "total_leads": total,
        "unreviewed": unreviewed,
        "high_priority": high_priority,
        "approved_drafts": approved,
        "contacted": contacted,
        "replies": replies,
        "opt_outs": opt_outs,
        "searches_completed": searches,
        "average_lead_score": round(float(avg_score), 1),
    }


def audit_from_record(record: WebsiteAuditRecord | None) -> WebsiteAudit:
    if record is None:
        return WebsiteAudit()
    from local_presence_miner.domain.website_evidence import ordinary_content_projection

    return ordinary_content_projection(WebsiteAudit(
        url=record.url,
        reachable=record.reachable,
        status_code=record.status_code,
        final_url=record.final_url,
        response_time_ms=record.response_time_ms,
        title=record.title,
        meta_description=record.meta_description,
        checks=loads(record.checks_json, {}),
        metrics=loads(record.metrics_json, {}),
        strengths=loads(record.strengths_json, []),
        weaknesses=loads(record.weaknesses_json, []),
        rendered_checks=loads(record.rendered_checks_json, {}),
        evidence=loads(record.evidence_json, {}),
        pagespeed_status=record.pagespeed_status,
        rendered_status=record.rendered_status,
        desktop_screenshot=record.desktop_screenshot,
        mobile_screenshot=record.mobile_screenshot,
    ))


def profile_from_lead(lead: Lead) -> BusinessProfile:
    public_data = loads(lead.google_public_data_json, {})
    return BusinessProfile(
        place_id=lead.place_id,
        name=lead.name,
        category=lead.category,
        address=lead.address,
        phone=lead.phone,
        website=lead.website,
        google_maps_url=lead.google_maps_url,
        yelp_url=lead.yelp_url,
        rating=lead.rating,
        review_count=lead.review_count,
        business_types=loads(lead.business_types_json, []),
        has_hours=lead.has_hours,
        photo_count=lead.photo_count,
        latitude=lead.latitude,
        longitude=lead.longitude,
        search_position=lead.search_position,
        profile_verification_required=lead.profile_verification_required,
        business_status=lead.business_status,
        primary_type=lead.primary_type,
        pure_service_area_business=lead.pure_service_area_business,
        international_phone=str(public_data.get("international_phone", "")),
        current_hours_available=bool(public_data.get("current_hours_available")),
        public_reviews=list(public_data.get("public_reviews", [])),
        price_level=str(public_data.get("price_level", "")),
        price_range=dict(public_data.get("price_range", {})),
        retrieved_at=lead.google_retrieved_at,
        raw={
            "_details_retrieved": bool(public_data.get("details_retrieved")),
            "_detail_fields_requested": bool(public_data.get("detail_fields_requested")),
            "_selected_for_details": bool(public_data.get("selected_for_details")),
            "_preliminary_candidate_score": public_data.get("preliminary_candidate_score"),
            "_preliminary_rank": public_data.get("preliminary_rank"),
        },
    )


def default_competitor_checklist() -> dict[str, bool]:
    return {
        "good_cta": False,
        "good_hero": False,
        "review_proof": False,
        "gallery": False,
        "online_booking": False,
        "service_pages": False,
        "trust_badges": False,
    }


def replace_contact_points(session: Session, lead_id: int, points: list[dict[str, Any]]) -> list[ContactPoint]:
    existing = list(session.execute(select(ContactPoint).where(ContactPoint.lead_id == lead_id)).scalars())
    selected_values = [(point.kind, point.value.casefold()) for point in existing if point.selected]
    incoming_keys = [
        (str(item.get("kind", "")).strip().lower(), str(item.get("value", "")).strip().casefold())
        for item in points
        if str(item.get("kind", "")).strip() and str(item.get("value", "")).strip()
    ]
    preserved_selection = next((key for key in selected_values if key in incoming_keys), None)
    discovered_selection = next(
        (
            (str(item.get("kind", "")).strip().lower(), str(item.get("value", "")).strip().casefold())
            for item in points
            if item.get("selected") and str(item.get("kind", "")).strip() and str(item.get("value", "")).strip()
        ),
        None,
    )
    selected_key = preserved_selection or discovered_selection
    for point in existing:
        session.delete(point)
    saved: list[ContactPoint] = []
    seen: set[tuple[str, str]] = set()
    for item in points:
        kind = str(item.get("kind", "")).strip().lower()
        value = str(item.get("value", "")).strip()
        key = (kind, value.casefold())
        if not kind or not value or key in seen:
            continue
        seen.add(key)
        record = ContactPoint(
            lead_id=lead_id,
            kind=kind,
            value=value,
            label=str(item.get("label", "")).strip(),
            source_type=str(item.get("source_type", "official_website")).strip() or "official_website",
            source_url=str(item.get("source_url", "")).strip(),
            confidence=str(item.get("confidence", "Moderate")).strip() or "Moderate",
            verified_public=bool(item.get("verified_public", True)),
            selected=key == selected_key,
            notes=str(item.get("notes", "")).strip(),
            updated_at=utc_now(),
        )
        session.add(record)
        saved.append(record)
    session.flush()
    if saved and not any(point.selected for point in saved):
        preferred = next((point for point in saved if point.kind == "email"), None) or next((point for point in saved if point.kind == "phone"), None)
        if preferred:
            preferred.selected = True
    log_activity(session, "contact_discovery_saved", f"Saved {len(saved)} public contact points", lead_id)
    return saved


def list_contact_points(session: Session, lead_id: int) -> list[ContactPoint]:
    return list(
        session.execute(
            select(ContactPoint)
            .where(ContactPoint.lead_id == lead_id)
            .order_by(ContactPoint.selected.desc(), ContactPoint.kind, ContactPoint.confidence.desc(), ContactPoint.id)
        ).scalars()
    )


def set_selected_contact_point(session: Session, lead_id: int, contact_point_id: int) -> None:
    points = list_contact_points(session, lead_id)
    chosen = None
    for point in points:
        point.selected = point.id == contact_point_id
        if point.selected:
            chosen = point
        point.updated_at = utc_now()
    if chosen:
        log_activity(session, "contact_point_selected", f"Selected {chosen.kind}: {chosen.value}", lead_id)


def best_contact_point(session: Session, lead_id: int, kind: str | None = None) -> ContactPoint | None:
    points = list_contact_points(session, lead_id)
    candidates = [point for point in points if kind is None or point.kind == kind]
    if not candidates:
        return None
    return next((point for point in candidates if point.selected), candidates[0])
