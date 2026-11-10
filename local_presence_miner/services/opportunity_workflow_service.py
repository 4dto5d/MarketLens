"""Operator planning on existing activity history, never commercial approval.

Worksheets retain reported needs and estimates without promoting them to website
evidence, owner strategy, qualification, canonical offers or delivery permission.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import ActivityLog, Lead

WORKSHEET_ACTION = "opportunity_worksheet_v1"
ROUTES = {
    "public_problem": "Publicly observable problem",
    "public_clue": "Public clue requiring owner confirmation",
    "owner_report": "Private problem reported in conversation",
}
TEXT_FIELDS = {
    "source_ref": "Source and date / conversation reference",
    "observation": "What was observed or reported (exact wording where available)",
    "alternatives": "Other explanations / what remains unknown",
    "owner_question": "Question to confirm the owner's need",
    "candidate_scope": "Candidate service and bounded deliverables — not accepted scope",
    "acquisition_route": "How you would approach this business / warm introduction",
    "platform_assumptions": "Platform, access and delivery assumptions",
    "platform_alternatives": "Alternatives, including keeping the current platform",
    "next_action": "Next action you will actually take",
}
NUMBER_FIELDS = {
    "delivery_hours": "Estimated delivery hours",
    "acquisition_hours": "Estimated research and sales hours",
    "travel_hours": "Estimated travel hours",
    "support_hours": "Estimated learning, revision and support hours",
    "hourly_cost": "Your planning value per hour ($)",
    "direct_costs": "Direct costs, travel expenses and platform fees ($)",
}


def normalize_worksheet(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) - ({"route", "owner_reported", "finding_refs"} | TEXT_FIELDS.keys() | NUMBER_FIELDS.keys()):
        raise ValueError("Unsupported opportunity worksheet fields.")
    if data.get("route") not in ROUTES or type(data.get("owner_reported", False)) is not bool:
        raise ValueError("Choose a discovery route and explicit owner attribution.")
    result = {"route": data["route"], "owner_reported": data.get("owner_reported", False)}
    for key in TEXT_FIELDS:
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > 8000:
            raise ValueError(f"{TEXT_FIELDS[key]} must be text of at most 8,000 characters.")
        result[key] = value.strip()
    if not result["source_ref"] or not result["observation"]:
        raise ValueError("Record the observation and its source/date; a hypothesis alone is not evidence.")
    for key in NUMBER_FIELDS:
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > 30:
            raise ValueError(f"{NUMBER_FIELDS[key]} must be a number or blank for unknown.")
        value = value.strip()
        if value:
            try:
                number = Decimal(value)
                if not number.is_finite() or number < 0 or number > 1_000_000:
                    raise ValueError
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"{NUMBER_FIELDS[key]} must be finite, nonnegative and at most 1,000,000.") from exc
        result[key] = value
    refs = data.get("finding_refs", [])
    if not isinstance(refs, list) or len(refs) > 50 or any(not isinstance(ref, str) or len(ref) > 120 for ref in refs):
        raise ValueError("Finding links must be a bounded list of revision references.")
    result["finding_refs"] = list(dict.fromkeys(refs))
    return result


def planning_cost(data: dict) -> str:
    """Blank is unknown; explicit zero is a valid operator estimate."""
    if any(not data.get(key, "").strip() for key in NUMBER_FIELDS):
        return "UNKNOWN — complete all cost inputs, using 0 only when explicitly estimated as zero."
    normalized = normalize_worksheet(data)
    hours = sum(Decimal(normalized[key]) for key in ("delivery_hours", "acquisition_hours", "travel_hours", "support_hours"))
    cost = hours * Decimal(normalized["hourly_cost"]) + Decimal(normalized["direct_costs"])
    return f"Estimated effort: {hours:g} hours; planning cost: ${cost:,.2f}. Not a quote, buyer budget, margin or ROI."


def save_worksheet(session: Session, lead: Lead, data: dict) -> ActivityLog:
    normalized = normalize_worksheet(data)
    if lead.id is None or session.get(Lead, lead.id) is not lead:
        raise ValueError("Save the business in this session first.")
    from local_presence_miner.services.prospect_finding_service import validate_finding_references

    validate_finding_references(session, lead.id, normalized["finding_refs"])
    row = ActivityLog(lead_id=lead.id, action=WORKSHEET_ACTION, message=json.dumps(normalized, ensure_ascii=False, sort_keys=True))
    session.add(row)
    session.flush()
    return row


def latest_worksheet(session: Session, lead_id: int) -> dict:
    row = session.scalar(select(ActivityLog).where(ActivityLog.lead_id == lead_id, ActivityLog.action == WORKSHEET_ACTION)
                         .order_by(ActivityLog.id.desc()).limit(1))
    if row is None:
        return {"state": "empty", "data": {}}
    try:
        data = normalize_worksheet(json.loads(row.message))
    except (ValueError, TypeError):
        return {"state": "invalid", "data": {}, "record_id": row.id}
    return {"state": "recorded", "data": data, "record_id": row.id, "recorded_at": row.created_at.isoformat()}


def create_warm_opportunity(session: Session, *, name: str, website: str = "", category: str = "", data: dict) -> Lead:
    normalized = normalize_worksheet(data)
    if normalized["finding_refs"]:
        raise ValueError("Save the warm business before linking its own findings.")
    if not isinstance(name, str) or not name.strip() or len(name) > 240:
        raise ValueError("A business name of at most 240 characters is required.")
    if not isinstance(category, str) or len(category) > 160 or not isinstance(website, str) or len(website) > 500:
        raise ValueError("Business type or website exceeds the supported length.")
    website = website.strip()
    if website:
        try:
            url = urlsplit(website)
            if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Use a complete http(s) website URL without credentials, or leave it blank.") from exc
    # Existing Lead requires a unique place_id. This explicit local namespace is
    # an internal key, not an invented Google listing. No search or Google facts
    # are created, and the explicit marker prevents legacy rich-data inference.
    lead = Lead(place_id="manual:" + uuid4().hex, name=name.strip(), category=category.strip(), website=website,
                google_public_data_json='{"details_retrieved":false,"source":"manual_intake"}',
                qualification_class="Hold", qualification_confidence="Low", profile_verification_required=True)
    session.add(lead)
    session.flush()
    save_worksheet(session, lead, normalized)
    return lead
