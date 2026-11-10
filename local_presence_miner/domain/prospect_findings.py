"""Provider-neutral source/review envelopes with two deliberately narrow adapters.

Review verifies correspondence to a captured source, never business impact or
the intrinsic truth of a provider response. New providers need explicit adapters.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from local_presence_miner.domain.commercial import fingerprint

SOURCE_ENVELOPE_VERSION = 1
REVIEW_STATES = frozenset({"UNREVIEWED", "VERIFIED", "UNKNOWN", "DISPUTED"})
CONTACT_FACTS = {
    "website.check.tap_to_call": ("tap_to_call", "tap-to-call link"),
    "website.check.contact_form": ("contact_form", "contact or quote form"),
    "website.check.sitewide_contact_path": ("sitewide_contact_path", "site-wide contact path"),
    "website.check.viewport": ("viewport", "mobile viewport"),
    "website.check.clear_primary_cta": ("clear_primary_cta", "clear primary CTA"),
}
MANUAL_ATTRIBUTIONS = frozenset({"OPERATOR_REPORTED_OWNER", "OPERATOR_OBSERVATION"})


def utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()


def bounded_text(value: object, label: str, *, required: bool = True, maximum: int = 8000) -> str:
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"{label} requires {'nonempty ' if required else ''}text up to {maximum} characters.")
    return value.strip()


def decode_snapshot(raw: str, expected_hash: str, lead_id: int) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate source field.")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Finding source is corrupt.") from exc
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value.get("schema_version") != SOURCE_ENVELOPE_VERSION
            or not isinstance(value.get("source_kind"), str) or not 1 <= len(value["source_kind"]) <= 80
            or not isinstance(value.get("subject"), dict) or type(value["subject"].get("lead_id")) is not int
            or value.get("subject") != {"lead_id": lead_id} or not isinstance(value.get("payload"), dict)
            or fingerprint(value) != expected_hash):
        raise ValueError("Finding source version, ownership or hash is invalid.")
    return value


def contact_claim(fact_id: str, value: object) -> str:
    if fact_id not in CONTACT_FACTS:
        raise ValueError("Unsupported website contact-path fact.")
    _, label = CONTACT_FACTS[fact_id]
    if type(value) is not bool:
        return f"Whether the sampled capture contained a {label} is UNKNOWN."
    return f"The sampled capture {'recorded' if value else 'did not detect'} a {label}."
