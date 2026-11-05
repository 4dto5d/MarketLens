from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


class VerifiableLead(Protocol):
    website: str
    google_maps_url: str
    phone: str
    approach_angle: str
    target_signals_json: str
    verification_json: str
    suppressed: bool
    status: str


VERIFICATION_ITEMS = [
    ("business_identity", "Business identity verified"),
    ("phone", "Phone or intended contact verified"),
    ("website", "Website/public presence verified"),
    ("google_url", "Google URL verified"),
    ("competitors", "Competitors reviewed"),
    ("audit_claims", "Major audit claims verified"),
    ("offer", "Offer reviewed"),
    ("price", "Price reviewed"),
    ("outreach", "Outreach wording reviewed"),
]
VERIFICATION_KEYS = [key for key, _label in VERIFICATION_ITEMS]
VERIFICATION_LABELS = dict(VERIFICATION_ITEMS)
BASE_OUTREACH_REQUIREMENTS = {"business_identity", "audit_claims", "outreach"}


@dataclass(frozen=True)
class VerificationAssessment:
    state: str
    completed: int
    total: int
    missing_required: tuple[str, ...]


def verification_values(lead: VerifiableLead) -> dict[str, bool]:
    import json

    try:
        raw = json.loads(lead.verification_json or "{}")
    except (json.JSONDecodeError, TypeError):
        raw = {}
    return {key: bool(raw.get(key, False)) for key in VERIFICATION_KEYS}


def required_verification_keys(
    lead: VerifiableLead,
    *,
    draft_kind: str = "",
    draft_text: str = "",
    competitor_claims: bool | None = None,
) -> set[str]:
    required = set(BASE_OUTREACH_REQUIREMENTS)
    if lead.website:
        required.add("website")
    elif lead.google_maps_url:
        required.add("google_url")

    phone_dependent = bool(re.search(r"call|voicemail|sms|text", draft_kind, re.I))
    if not draft_kind:
        phone_dependent = str(getattr(lead, "contact_method", "")).lower() in {"phone", "voicemail", "sms", "text"}
    if phone_dependent:
        required.add("phone")

    if competitor_claims is None:
        claim_text = " ".join([lead.approach_angle or "", lead.target_signals_json or "", draft_text or ""])
        competitor_claims = bool(
            re.search(
                r"competitor|nearby\s+business(?:es)?|other\s+local\s+business(?:es)?|comparison\s+set|side[- ]by[- ]side\s+compar",
                claim_text,
                re.I,
            )
        )
    if competitor_claims:
        required.add("competitors")
    return required


def assess_verification(
    lead: VerifiableLead,
    *,
    draft_kind: str = "",
    draft_text: str = "",
    competitor_claims: bool | None = None,
) -> VerificationAssessment:
    values = verification_values(lead)
    completed = sum(values.values())
    required = required_verification_keys(
        lead,
        draft_kind=draft_kind,
        draft_text=draft_text,
        competitor_claims=competitor_claims,
    )
    missing = tuple(sorted((key for key in required if not values[key]), key=VERIFICATION_KEYS.index))
    if lead.suppressed or lead.status == "Do Not Contact":
        state = "Suppressed / blocked"
    elif not completed:
        state = "Unverified"
    elif missing:
        state = "Verification incomplete"
    else:
        state = "Ready for outreach"
    return VerificationAssessment(state, completed, len(VERIFICATION_KEYS), missing)


def format_missing_requirements(keys: tuple[str, ...] | list[str]) -> str:
    return ", ".join(VERIFICATION_LABELS.get(key, key.replace("_", " ")) for key in keys)
