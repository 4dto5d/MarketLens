from __future__ import annotations

from dataclasses import dataclass

from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.models import StartingOffer
from local_presence_miner.domain.offer_registry import resolve_offer


@dataclass(frozen=True)
class ProjectValue:
    offer_name: str
    low: int | None
    high: int | None
    reasoning: tuple[str, ...]
    offer_id: str = ""
    resolution_status: str = "resolved"
    raw_offer_label: str = ""

    @property
    def range_text(self) -> str:
        if self.low is None or self.high is None:
            if self.resolution_status in {"no_sale", "validate_first", "insufficient_evidence"}:
                return "No paid recommendation" if self.resolution_status == "no_sale" else "Validate before pricing"
            return "Research required" if self.resolution_status == "research_required" else "Manual mapping required"
        return f"${self.low:,}-${self.high:,}"


@dataclass(frozen=True)
class PricingGuidance:
    offer_name: str
    suggested_range: str
    first_step_price: str
    rationale: list[str]
    warnings: list[str]


def estimate_project_value(
    lead: Lead,
    competitors: list[CompetitorRecord] | None = None,
    current_offer: StartingOffer | None = None,
) -> ProjectValue:
    """Catalog service-cost band, not measured prospect value or expected ROI."""
    competitors = competitors or []
    raw_label = current_offer.offer_name if current_offer is not None else lead.recommended_offer
    canonical_id = current_offer.offer_id if current_offer is not None else lead.recommended_offer_id
    resolution = resolve_offer(raw_label, canonical_id or None)
    definition = resolution.definition
    if definition is None:
        return ProjectValue(
            raw_label or "Unresolved offer",
            None,
            None,
            (f"Offer label {raw_label!r} is unresolved; MarketLens did not substitute a different commercial offer.",),
            "",
            resolution.status,
            raw_label,
        )
    offer_name = definition.display_name
    low, high = definition.price_low, definition.price_high
    reasoning = [f"The current {offer_name} scope starts from the documented ${low:,}-${high:,} service band."]

    reasoning.append("This is a catalog service-cost reference, not expected value, willingness to pay or ROI. "
                     "Growth Score, candidate order and competitor count do not change the price.")
    return ProjectValue(offer_name, low, max(low, high), tuple(reasoning), definition.offer_id.value, resolution.status, raw_label)


def recommend_pricing(lead: Lead, competitors: list[CompetitorRecord] | None = None) -> PricingGuidance:
    """Compatibility view for customer-facing project value; seller calibration lives separately."""
    project = estimate_project_value(lead, competitors)
    warnings = [
        "Do not charge per posted review. Charge for implementation, templates, training, and display work.",
        "Do not guarantee rankings, call volume, revenue, or a specific number of reviews.",
        "Project Value is prospect-side; the operator's actual ask is selected separately in Pricing Intelligence.",
    ]
    return PricingGuidance(
        offer_name=project.offer_name,
        suggested_range=project.range_text,
        first_step_price="Select a phased or full-scope price after reviewing Seller Pricing Intelligence.",
        rationale=list(project.reasoning),
        warnings=warnings,
    )


def round_price(value: float) -> int:
    return max(50, int(round(value / 50.0) * 50))
