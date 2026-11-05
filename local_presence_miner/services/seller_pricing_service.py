from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.commercial import CurrentOfferContext
from local_presence_miner.domain.models import StartingOffer
from local_presence_miner.services.comparable_offer_service import ComparableOfferAnalysis, ComparableOfferService
from local_presence_miner.services.pricing_calibration import ProjectValue, estimate_project_value, round_price
from local_presence_miner.services.seller_proof_service import (
    SellerProofSummary,
    safe_proof_sentence,
    summarize_seller_proof,
)


@dataclass(frozen=True)
class PhasedPrice:
    name: str
    amount: int
    scope: str


@dataclass(frozen=True)
class SellerPricingRecommendation:
    project: ProjectValue
    easy_close: int | None
    recommended: int | None
    stretch: int | None
    confidence: str
    comparable: ComparableOfferAnalysis
    proof: SellerProofSummary
    reasoning: tuple[str, ...]
    phases: tuple[PhasedPrice, ...]
    relevant_proof_sentence: str
    price_answer: str
    objections: tuple[tuple[str, str], ...]

    @property
    def price_available(self) -> bool:
        return self.easy_close is not None and self.recommended is not None and self.stretch is not None

    def display_price(self, value: int | None) -> str:
        return f"${value:,}" if value is not None else self.project.range_text

    @property
    def easy_close_text(self) -> str:
        return self.display_price(self.easy_close)

    @property
    def recommended_text(self) -> str:
        return self.display_price(self.recommended)

    @property
    def stretch_text(self) -> str:
        return self.display_price(self.stretch)


class SellerPricingService:
    def recommend_for_lead(
        self, session: Session, lead: Lead, competitors: list[CompetitorRecord] | None = None
    ) -> SellerPricingRecommendation:
        """Convenience boundary that still builds an explicit fresh context."""
        from local_presence_miner.services.commercial_plan_service import build_current_offer_context

        selected = competitors or []
        context, current_offer = build_current_offer_context(session, lead, competitors=selected)
        return self.recommend(session, lead, selected, current_offer=current_offer, current_offer_context=context)

    def recommend(
        self,
        session: Session,
        lead: Lead,
        competitors: list[CompetitorRecord] | None = None,
        *,
        current_offer: StartingOffer,
        current_offer_context: CurrentOfferContext,
    ) -> SellerPricingRecommendation:
        competitors = competitors or []
        if current_offer_context.lead_id != lead.id:
            raise ValueError("CurrentOfferContext belongs to a different lead")
        if tuple(current_offer.scope) != current_offer_context.scope:
            raise ValueError("Seller pricing requires the exact scope from CurrentOfferContext")
        project = estimate_project_value(lead, competitors, current_offer)
        if not current_offer_context.price_available:
            decision = current_offer_context.intervention_assessment
            project = replace(project, low=None, high=None,
                              resolution_status=str(decision.get("state") or "research_required"),
                              reasoning=(str(decision.get("summary") or "Commercial evidence needs review."),))
        proof = summarize_seller_proof(session, lead.category)
        scope_items = list(current_offer.scope)
        scope_summary = "; ".join(scope_items) or current_offer.offer_name
        comparable = ComparableOfferService().analyze(
            session,
            lead,
            project.offer_name,
            scope_summary,
            project.low,
            project.high,
            offer_id=project.offer_id,
        )
        if not project.offer_id or project.low is None or project.high is None:
            reasons = list(project.reasoning)
            reasons.append("No new paid scope or price is justified until the commercial evidence and selection are reviewed.")
            return SellerPricingRecommendation(
                project=project,
                easy_close=None,
                recommended=None,
                stretch=None,
                confidence=proof.evidence_confidence,
                comparable=comparable,
                proof=proof,
                reasoning=tuple(reasons),
                phases=(),
                relevant_proof_sentence=safe_proof_sentence(proof, lead.category),
                price_answer="I do not have enough support to recommend a paid intervention now. Let's confirm the actual need first.",
                objections=(),
            )
        step = price_step(project.low)
        reasons = list(project.reasoning)
        won = [item.offer for item in comparable.offers if item.offer.status == "Won" and item.offer.closed_amount]
        if won:
            newest_won = max(won, key=lambda item: (item.offer_date, item.id or 0))
            history_anchor = max(comparable.median_won_price or 0, newest_won.closed_amount or 0)
            proof_steps = {"Low": 0, "Moderate": 1, "Strong": 2}[proof.evidence_confidence]
            recommended = history_anchor + proof_steps * step
            reasons.append(
                f"Recent/relevant won history anchors the ask near ${history_anchor:,}; "
                f"{proof.evidence_confidence.lower()} proof supports {proof_steps} transparent ${step:,} step(s)."
            )
        else:
            starter_share = {"Low": 0.75, "Moderate": 0.85, "Strong": 1.0}[proof.evidence_confidence]
            recommended = round_price(project.low * starter_share)
            reasons.append(
                f"No comparable wins exist. The ask uses {int(starter_share * 100)}% of the Project Value floor while "
                "keeping the documented service-cost band visible; price bands alone do not add or remove deliverables."
            )
        recommended = max(round_price(project.low * 0.6), min(round_price(recommended), project.high))
        easy = max(round_price(project.low * 0.5), round_price(recommended - step))
        stretch = min(project.high, max(project.low, round_price(recommended + step)))
        reasons.extend(proof_reasoning(proof, comparable))
        first_scope = starter_scope(scope_items)
        smaller_scope = first_scope != scope_summary
        phases = (
            PhasedPrice("Starter" if smaller_scope else "Lower ask (same scope)", easy, first_scope),
            PhasedPrice("Core", recommended, scope_summary or "Core recommended package"),
            PhasedPrice("Upper planning range", stretch, "Same verified core scope; no additional deliverables are promised."),
        )
        price_answer = (
            f"The documented scope has a recommended ask of ${recommended:,}; the upper planning ask is ${stretch:,}. "
            + (f"A first phase at ${easy:,} includes only: {first_scope}." if smaller_scope else
               f"The ${easy:,} lower ask covers the same deliverables, not a smaller or expanded scope.")
            + " Confirm the written delivery plan and agreed terms before any payable commitment."
        )
        return SellerPricingRecommendation(
            project=project,
            easy_close=easy,
            recommended=recommended,
            stretch=stretch,
            confidence=proof.evidence_confidence,
            comparable=comparable,
            proof=proof,
            reasoning=tuple(reasons),
            phases=phases,
            relevant_proof_sentence=safe_proof_sentence(proof, lead.category),
            price_answer=price_answer,
            objections=objection_responses(recommended, easy, project, smaller_scope=smaller_scope),
        )


def proof_reasoning(proof: SellerProofSummary, comparable: ComparableOfferAnalysis) -> list[str]:
    lines = [
        f"Seller evidence: {proof.completed_paid_projects} paid project(s), "
        f"{proof.relevant_niche_projects} relevant proof item(s), and {proof.testimonials} testimonial(s).",
        f"Comparable history: {comparable.sample_count} offer(s), {comparable.won_count} won.",
        comparable.success_text,
    ]
    if comparable.median_won_price:
        lines.append(f"Median comparable won amount is ${comparable.median_won_price:,}.")
    if comparable.average_negotiation_discount is not None:
        lines.append(f"Average observed negotiation discount is ${comparable.average_negotiation_discount:,}.")
    if proof.evidence_confidence == "Low":
        lines.append("Limited seller history: reduce first-phase scope before heavily discounting the full project.")
    return lines


def objection_responses(recommended: int, easy: int, project: ProjectValue, *, smaller_scope: bool = False) -> tuple[tuple[str, str], ...]:
    return (
        (
            "That's too expensive.",
            f"I understand. The full scope is based on work valued around ${project.low:,}-${project.high:,}. "
            + (f"A ${easy:,} first phase includes only the separately documented subset." if smaller_scope else
               f"The ${easy:,} lower ask includes the same scope; it does not promise extra work or a smaller phase."),
        ),
        (
            "I need to think about it.",
            "Of course. I can send the scope in writing so you can review what is included without any pressure.",
        ),
        (
            "I know someone who can do it cheaper.",
            f"That may be a good option. My ${recommended:,} recommendation is tied to this documented scope and evidence; "
            "the useful comparison is what each option actually includes.",
        ),
        (
            "We don't need a new website.",
            "That may be right. The recommendation can be reduced to the verified contact-flow or trust fixes without replacing everything.",
        ),
        (
            "We're already getting enough business.",
            "That is a good position to be in. There is no reason to force a rebuild; the smaller fixes only make sense if they support a real goal.",
        ),
    )


def price_step(project_low: int) -> int:
    if project_low < 1000:
        return 100
    if project_low < 2500:
        return 250
    return 500


def starter_scope(scope_items: list[str]) -> str:
    if scope_items:
        return "; ".join(scope_items[:2])
    return "Tightly scoped first phase focused on the primary conversion/contact gap"
