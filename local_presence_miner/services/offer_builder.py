from __future__ import annotations

from dataclasses import asdict

from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.models import StartingOffer, StartingOfferInput
from local_presence_miner.domain.offer_registry import OfferDefinition, resolve_offer


def build_starting_offer_input(
    lead: Lead,
    competitors: list[CompetitorRecord],
    city: str = "",
    state_region: str = "",
) -> StartingOfferInput:
    target_signals = loads(lead.target_signals_json, [])
    competitor_names = [competitor.competitor_name for competitor in competitors]
    return StartingOfferInput(
        business_name=lead.name,
        niche=lead.category,
        city=city,
        state_region=state_region,
        target_zip_code=lead.target_zip_code,
        target_radius_miles=lead.target_radius_miles,
        phone=lead.phone,
        website=lead.website,
        google_maps_url=lead.google_maps_url,
        yelp_url=lead.yelp_url,
        current_rank_position=lead.search_position,
        review_count=lead.review_count,
        rating=lead.rating,
        competitor_names=competitor_names,
        target_signals=target_signals,
        recommended_offer=lead.recommended_offer,
        past_sales_notes=lead.past_sales_notes,
        recommended_offer_id=lead.recommended_offer_id,
    )


def generate_starting_offer(data: StartingOfferInput) -> StartingOffer:
    resolution = resolve_offer(data.recommended_offer, data.recommended_offer_id or None)
    offer = resolution.definition
    if offer is None:
        raw = data.recommended_offer.strip() or "(blank)"
        research_required = resolution.status == "research_required"
        return StartingOffer(
            headline=(f"Research required for {data.business_name}" if research_required else f"Unresolved offer for {data.business_name}"),
            opening_angle=(
                "Public evidence must be verified before selecting a commercial scope."
                if research_required
                else "A commercial offer has not been safely mapped. Review the legacy label before preparing outreach."
            ),
            offer_name=raw,
            price_range="Research required" if research_required else "Manual mapping required",
            scope=[],
            proof_plan=(
                ["Complete evidence review before presenting commercial scope or price."]
                if research_required
                else ["Resolve the offer identity before presenting scope or price."]
            ),
            first_ask="Pause commercial outreach until the offer is reviewed.",
            risk_reversal="No offer substitution was made.",
            talk_track=(
                "Public details still need review before a commercial recommendation is prepared."
                if research_required
                else "This recommendation is unresolved and is not ready to present."
            ),
            offer_id="",
            resolution_status=resolution.status,
        )
    location = " ".join(part for part in [data.city, data.state_region, data.target_zip_code] if part).strip()
    rank = (
        f"retained at candidate position {data.current_rank_position} after MarketLens filters; "
        "that is not provider result position or an exact Maps rank"
        if data.current_rank_position
        else "included in the collected sample without a verified result position"
    )
    competitor_line = ", ".join(data.competitor_names[:3]) or "nearby competitors"
    signals = ", ".join(data.target_signals[:4]) or "public-facing website and Google presence gaps"

    past_sales_notes = (data.past_sales_notes or "").strip()
    if past_sales_notes:
        proof_plan = [
            f"Use your existing proof honestly: {past_sales_notes}",
            "Show the prospect the audit findings before asking for the sale.",
            "Offer a fixed-scope first step so the buyer is not taking an open-ended risk.",
        ]
    else:
        proof_plan = [
            "Be direct that you are building local case studies and are starting with a narrow pilot.",
            "Bring the audit, competitor comparison, and mockup so the value is visible before they pay.",
            "Ask for permission to use anonymized before/after screenshots or a testimonial after delivery.",
        ]

    scope = list(offer.deliverables)

    return StartingOffer(
        headline=f"{offer.name} for {data.business_name}",
        opening_angle=(
            f"I found {signals}. In the local {data.niche} results for {location or 'your area'}, "
            f"your record was {rank}. Selected comparison businesses include {competitor_line}; "
            "review their observed trust and contact signals before claiming a gap."
        ),
        offer_name=offer.name,
        price_range=offer.price_range,
        scope=scope,
        proof_plan=proof_plan,
        first_ask="Ask for permission to send the short audit and one-page concept, not for a full project on first contact.",
        risk_reversal="Offer a small fixed-scope pilot first; no ranking, revenue, or call-volume guarantees.",
        talk_track=(
            f"“I am putting together a few local before/after case studies. I noticed {data.business_name} has "
            f"{signals}. I made a short audit and a simple concept for how I would make the website/Google presence "
            f"easier to trust and easier to contact. Would it be useful if I sent that over?”"
        ),
        offer_id=offer.offer_id.value,
        resolution_status="resolved",
    )


def find_offer(name: str, offer_id: str = "") -> OfferDefinition | None:
    return resolve_offer(name, offer_id or None).definition


def starting_offer_to_json(offer: StartingOffer) -> dict:
    return asdict(offer)
