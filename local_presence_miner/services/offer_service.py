from __future__ import annotations

from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.offer_registry import OFFER_DEFINITIONS, OfferDefinition, OfferID, resolve_offer

OfferOption = OfferDefinition
OFFER_OPTIONS: list[OfferOption] = [offer for offer in OFFER_DEFINITIONS if offer.active]


def options_for_lead(lead: Lead) -> list[OfferOption]:
    resolution = resolve_offer(lead.recommended_offer, lead.recommended_offer_id or None)
    ordered = sorted(OFFER_OPTIONS, key=lambda offer: 0 if offer.offer_id == resolution.offer_id else 1)
    if all(offer.offer_id != OfferID.NO_TRACK_RECORD_PILOT for offer in ordered[:2]):
        pilot = next(offer for offer in OFFER_OPTIONS if offer.offer_id == OfferID.NO_TRACK_RECORD_PILOT)
        return ordered[:2] + [pilot]
    return ordered[:3]


def beginner_approach_playbook() -> list[str]:
    return [
        "Do not pretend to have a big portfolio. Lead with the specific public gaps you observed.",
        "Offer a free short audit or one-page concept before asking for a paid project.",
        "Ask for permission to send the report instead of pitching the whole service on first contact.",
        "Use a fixed-scope pilot with a clear price, timeline, and deliverables.",
        "Trade a small discount only for permission to use an anonymized before/after case study.",
        "Avoid guarantees about rankings, revenue, or call volume.",
        "Keep the ask small: 'Can I send the audit?' or 'Would a quick mockup be useful?'",
    ]
