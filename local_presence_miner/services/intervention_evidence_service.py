"""Current, source-bound inputs for the intervention assessor (no mutations).

This adapter intentionally ignores target_signals, lead scores and competitor
counts: they are derived/triage labels, not independent observations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import audit_from_record, loads
from local_presence_miner.database.schema import Lead, WebsiteAuditRecord
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.domain.intervention_assessment import InterventionEvidence
from local_presence_miner.domain.scoring import website_evidence_state
from local_presence_miner.services.conversation_state_service import ConversationState
from local_presence_miner.time_utils import utc_now


def current_at(value: object, now: datetime) -> bool:
    """Missing, malformed, future-dated and expired timestamps all fail closed."""
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
        clock = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
        return timedelta(0) <= clock - stamp <= timedelta(days=30)
    except (ValueError, TypeError, OverflowError):
        return False


def collect_intervention_evidence(
    session: Session, lead: Lead, *, conversation: ConversationState,
    findings: tuple[dict[str, Any], ...] = (), now: datetime | None = None,
) -> InterventionEvidence:
    now = now or utc_now()
    audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead.id))
    checks: dict[str, bool] = {}
    website_state = "unknown"
    website_refs: tuple[str, ...] = ()
    if (audit is not None and bool(lead.website)
            and audit.url.rstrip("/") == lead.website.rstrip("/") and current_at(audit.created_at, now)):
        raw = loads(audit.checks_json, {})
        if isinstance(raw, dict):
            checks = {str(key): value for key, value in raw.items() if type(value) is bool}
        website_state = website_evidence_state(audit_from_record(audit))
        if website_state != "observed":
            checks = {}
        identity = {"url": audit.url, "created_at": audit.created_at, "reachable": audit.reachable,
                    "status_code": audit.status_code, "checks": checks, "website_state": website_state,
                    "final_url": audit.final_url, "title": audit.title, "evidence": loads(audit.evidence_json, {})}
        website_refs = (f"website_audit:{audit.id}:{fingerprint(identity)}",)
    public = loads(lead.google_public_data_json, {})
    if not isinstance(public, dict):
        public = {}
    stamp = lead.last_rich_google_retrieved_at or lead.google_retrieved_at
    google_current = (public.get("details_retrieved") is True and not lead.google_rich_data_stale
                      and current_at(stamp, now))
    google_refs: tuple[str, ...] = ()
    if google_current:
        identity = {"place_id": lead.place_id, "retrieved_at": stamp, "hours": lead.has_hours,
                    "photos": lead.photo_count, "rating": lead.rating, "reviews": lead.review_count}
        google_refs = (f"google_places:{lead.place_id}:{fingerprint(identity)}",)
        if not lead.website:
            website_state = "absent"
    from local_presence_miner.services.seo_research_service import project_seo_research

    seo_research = project_seo_research(session, lead, now=now)
    from local_presence_miner.services.owner_strategy_service import project_owner_strategy

    owner_strategy = project_owner_strategy(session, lead)
    return InterventionEvidence(
        website_url=lead.website or "", website_state=website_state,
        website_checks=checks, website_refs=website_refs,
        google_current=google_current,
        has_hours=lead.has_hours if google_current else None,
        photo_count=lead.photo_count if google_current else None,
        rating=lead.rating if google_current else None,
        review_count=lead.review_count if google_current else None,
        google_refs=google_refs, search_findings=findings,
        seo_research=seo_research,
        capacity_status=conversation.capacity_status or "",
        commercial_disposition=lead.commercial_disposition or "UNKNOWN",
        business_goal=conversation.business_goal or "",
        owner_strategy=owner_strategy,
    )
