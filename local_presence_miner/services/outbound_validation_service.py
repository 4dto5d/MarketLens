from __future__ import annotations

import re
from dataclasses import dataclass

from local_presence_miner.config import SenderInfo
from local_presence_miner.domain.enums import OutreachKind

PLACEHOLDER_RE = re.compile(
    r"\[(?:your|sender|business|name|phone|email|contact|postal|address)[^\]]*\]|\{\{[^{}]+\}\}|<\s*(?:your|sender)[^>]*>",
    re.IGNORECASE,
)
EMAIL_KINDS = {
    OutreachKind.INITIAL_EMAIL.value,
    OutreachKind.SHORT_FOLLOW_UP.value,
    OutreachKind.FINAL_FOLLOW_UP.value,
    OutreachKind.INTERESTED_REPLY.value,
    OutreachKind.PRICE_REPLY.value,
    OutreachKind.PROVIDER_REPLY.value,
    OutreachKind.NOT_NOW_REPLY.value,
    OutreachKind.REPORT_DELIVERY.value,
    OutreachKind.MOCKUP_DELIVERY.value,
}


@dataclass(frozen=True)
class OutboundValidation:
    valid: bool
    reasons: tuple[str, ...]


def validate_outbound_draft(sender: SenderInfo, kind: str, subject: str, body: str) -> OutboundValidation:
    reasons: list[str] = []
    combined = "\n".join((subject, body))
    placeholders = tuple(dict.fromkeys(match.group(0) for match in PLACEHOLDER_RE.finditer(combined)))
    if placeholders:
        reasons.append("Resolve sender placeholder(s): " + ", ".join(placeholders))
    for field_name in ("name", "business_name", "reply_email", "phone", "postal_address", "opt_out_line"):
        value = getattr(sender, field_name)
        if PLACEHOLDER_RE.search(value) or value.strip().casefold() in {"your name", "your business", "your contact info", "your phone", "your email"}:
            reasons.append(f"Resolve the placeholder in sender configuration: {field_name.replace('_', ' ')}.")
    if not sender.name.strip():
        reasons.append("Configure the sender name.")
    if kind in EMAIL_KINDS:
        if not sender.reply_email.strip():
            reasons.append("Configure the sender reply email.")
        if not sender.postal_address.strip():
            reasons.append("Configure the sender postal address.")
        if not sender.opt_out_line.strip():
            reasons.append("Configure the manual opt-out line.")
        normalized_body = " ".join(body.casefold().split())
        for label, value in (
            ("sender name", sender.name), ("reply email", sender.reply_email),
            ("postal address", sender.postal_address), ("opt-out line", sender.opt_out_line),
        ):
            if value.strip() and " ".join(value.casefold().split()) not in normalized_body:
                reasons.append(f"Include the configured {label} in this exact email draft.")
    if kind == OutreachKind.VOICEMAIL.value and not sender.phone.strip():
        reasons.append("Configure the sender phone number for voicemail scripts.")
    return OutboundValidation(not reasons, tuple(dict.fromkeys(reasons)))
