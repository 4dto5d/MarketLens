from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

from sqlalchemy.orm import Session

from local_presence_miner.database.pricing_repository import list_offer_history
from local_presence_miner.database.schema import Lead, OfferHistory
from local_presence_miner.domain.niche_taxonomy import niche_relation
from local_presence_miner.domain.offer_registry import resolve_offer

MIN_RATE_SAMPLE = 5
PRICE_RELEVANT_LOSSES = {"Too expensive", "Budget unavailable"}


@dataclass(frozen=True)
class ComparableOffer:
    offer: OfferHistory
    similarity_score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ComparableOfferAnalysis:
    offers: tuple[ComparableOffer, ...]
    median_ask: int | None
    median_won_price: int | None
    won_count: int
    resolved_price_sample: int
    comparable_low: int | None
    comparable_high: int | None
    average_negotiation_discount: int | None
    success_text: str

    @property
    def sample_count(self) -> int:
        return len(self.offers)


class ComparableOfferService:
    def analyze(
        self,
        session: Session,
        lead: Lead,
        package_name: str,
        scope_summary: str,
        project_low: int | None,
        project_high: int | None,
        *,
        offer_id: str = "",
    ) -> ComparableOfferAnalysis:
        candidates = []
        for offer in list_offer_history(session):
            if offer.status == "Draft":
                continue
            score, reasons = similarity(offer, lead, package_name, scope_summary, project_low, project_high, offer_id=offer_id)
            if score >= 3:
                candidates.append(ComparableOffer(offer, score, tuple(reasons)))
        candidates.sort(key=lambda item: (item.similarity_score, item.offer.offer_date, item.offer.id or 0), reverse=True)
        selected = tuple(candidates[:10])
        asks = [item.offer.initial_ask for item in selected]
        won = [item.offer for item in selected if item.offer.status == "Won" and item.offer.closed_amount]
        price_losses = [item.offer for item in selected if item.offer.status in {"Lost", "Rejected"} and item.offer.lost_reason in PRICE_RELEVANT_LOSSES]
        resolved = len(won) + len(price_losses)
        if resolved >= MIN_RATE_SAMPLE:
            success = f"Won {len(won)} / {resolved} comparable price-relevant outcomes ({len(won) / resolved * 100:.1f}%)."
        else:
            success = f"Won {len(won)} / {resolved} price-relevant outcomes. Not enough history for a reliable close-rate estimate."
        discounts = [item.initial_ask - item.closed_amount for item in won if item.closed_amount and item.initial_ask]
        return ComparableOfferAnalysis(
            offers=selected,
            median_ask=round(median(asks)) if asks else None,
            median_won_price=round(median([item.closed_amount for item in won])) if won else None,
            won_count=len(won),
            resolved_price_sample=resolved,
            comparable_low=min(asks) if asks else None,
            comparable_high=max(asks) if asks else None,
            average_negotiation_discount=round(sum(discounts) / len(discounts)) if len(discounts) >= 3 else None,
            success_text=success,
        )


def similarity(
    offer: OfferHistory,
    lead: Lead,
    package_name: str,
    scope_summary: str,
    project_low: int | None,
    project_high: int | None,
    *,
    offer_id: str = "",
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    relation = niche_relation(offer.niche, lead.category)
    if relation == "same":
        score += 6
        reasons.append("same niche")
    elif relation == "related":
        score += 2
        reasons.append("related service family")
    elif relation == "different":
        score -= 3
        reasons.append("different niche")
    current_resolution = resolve_offer(package_name, offer_id or None)
    historical_resolution = resolve_offer(offer.package_name, offer.canonical_offer_id or None)
    if current_resolution.offer_id is not None and historical_resolution.offer_id == current_resolution.offer_id:
        score += 3
        reasons.append("same package")
    overlap = token_overlap(offer.scope_summary, scope_summary)
    if overlap >= 0.35:
        score += 2
        reasons.append("similar scope")
    if ranges_overlap(
        offer.project_value_low_at_offer,
        offer.project_value_high_at_offer,
        project_low,
        project_high,
    ):
        score += 2
        reasons.append("overlapping Project Value")
    age_days = (date.today() - date.fromisoformat(offer.offer_date)).days
    if age_days <= 365:
        score += 2
        reasons.append("recent")
    elif age_days <= 730:
        score += 1
        reasons.append("within two years")
    return score, reasons


def ranges_overlap(low: int | None, high: int | None, current_low: int | None, current_high: int | None) -> bool:
    if low is None or high is None or current_low is None or current_high is None:
        return False
    return max(low, current_low) <= min(high, current_high)


def token_overlap(left: str, right: str) -> float:
    a = {token for token in normalize(left).split() if len(token) > 2}
    b = {token for token in normalize(right).split() if len(token) > 2}
    return len(a & b) / len(a | b) if a and b else 0.0


def normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("/", " ").split())
