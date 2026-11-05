from __future__ import annotations

from dataclasses import dataclass

from local_presence_miner.database.schema import ContactPoint, Lead
from local_presence_miner.domain.enums import OUTREACH_BLOCKED_STATUSES


@dataclass(frozen=True)
class OutreachChannelPlan:
    state: str
    primary_channel: str
    secondary_channel: str
    reason: str
    recipient: str
    phone: str
    contact_page: str
    warnings: tuple[str, ...]


def build_outreach_channel_plan(lead: Lead, contacts: list[ContactPoint]) -> OutreachChannelPlan:
    if lead.suppressed or lead.status in OUTREACH_BLOCKED_STATUSES:
        reason = "This lead is suppressed." if lead.suppressed else f"This lead's status is {lead.status}."
        return OutreachChannelPlan(
            state="Blocked",
            primary_channel="Do not contact",
            secondary_channel="",
            reason=reason,
            recipient="",
            phone="",
            contact_page="",
            warnings=("Suppression is an absolute outreach block.",),
        )

    emails = [p for p in contacts if p.kind == "email" and p.verified_public is not False]
    phones = [p for p in contacts if p.kind == "phone" and p.verified_public is not False]
    pages = [p for p in contacts if p.kind == "contact_page" and p.verified_public is not False]
    preferred = next((p for p in contacts if p.selected and p.verified_public is not False), None)
    selected_email = (preferred if preferred and preferred.kind == "email" else None) or (emails[0] if emails else None)
    selected_phone = (preferred if preferred and preferred.kind == "phone" else None) or (phones[0] if phones else None)
    phone = selected_phone.value if selected_phone else lead.phone
    page = (preferred.value if preferred and preferred.kind == "contact_page" else "") or (pages[0].value if pages else "")

    if preferred and preferred.kind == "phone" and phone:
        return OutreachChannelPlan(
            state="Contactable",
            primary_channel="Phone",
            secondary_channel="Email" if emails else ("Contact form" if page else ""),
            reason="The operator selected the public phone as the preferred contact route.",
            recipient=emails[0].value if emails else "",
            phone=phone,
            contact_page=page,
            warnings=("Decision maker is not identified unless separately verified.",),
        )
    if preferred and preferred.kind == "contact_page" and page:
        return OutreachChannelPlan(
            state="Limited",
            primary_channel="Contact form",
            secondary_channel="Email" if emails else ("Phone" if phone else ""),
            reason="The operator selected the official contact page as the preferred route.",
            recipient=emails[0].value if emails else "",
            phone=phone,
            contact_page=page,
            warnings=("Review the form and recipient context manually before submitting.",),
        )
    if selected_email:
        secondary = "Phone" if phone else ("Contact form" if page else "")
        return OutreachChannelPlan(
            state="Contactable",
            primary_channel="Email",
            secondary_channel=secondary,
            reason="A public email is available from the business's official web presence.",
            recipient=selected_email.value,
            phone=phone,
            contact_page=page,
            warnings=tuple(),
        )
    if phone:
        return OutreachChannelPlan(
            state="Contactable",
            primary_channel="Phone",
            secondary_channel="Contact form" if page else "",
            reason="No public email is stored, but a public business phone is available.",
            recipient="",
            phone=phone,
            contact_page=page,
            warnings=("Decision maker is not identified unless separately verified.",),
        )
    if page:
        return OutreachChannelPlan(
            state="Limited",
            primary_channel="Contact form",
            secondary_channel="",
            reason="The official website exposes a contact page but no stored public email or phone.",
            recipient="",
            phone="",
            contact_page=page,
            warnings=("Review the form and recipient context manually before submitting.",),
        )
    return OutreachChannelPlan(
        state="Research required",
        primary_channel="Contact research",
        secondary_channel="",
        reason="No usable public email, phone, or contact page is currently stored.",
        recipient="",
        phone="",
        contact_page="",
        warnings=("Do not guess private contact details.",),
    )
