from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan


@dataclass(frozen=True)
class OwnerBrief:
    opportunity: str
    business_size: str
    likely_decision_maker: str
    revenue_leaks: list[str]
    recommended_opening: str
    build_difficulty: str
    suggested_package: str
    suggested_range: str
    evidence_confidence: int
    confidence_note: str
    verify_before_calling: list[str]
    project_value_range: str
    easy_close_ask: int | None
    recommended_ask: int | None
    stretch_ask: int | None
    pricing_confidence: str
    pricing_reasoning: tuple[str, ...]
    price_answer: str


def build_owner_brief(lead: Lead, competitors: list[CompetitorRecord], session: Session | None = None) -> OwnerBrief:
    leaks = loads(lead.target_signals_json, [])
    if lead.audit:
        for weakness in loads(lead.audit.weaknesses_json, []):
            if weakness not in leaks:
                leaks.append(weakness)
    leaks = leaks[:7] or ["No verified revenue leak has been captured yet; review manually."]

    evidence_items = [
        bool(lead.phone),
        bool(lead.google_maps_url),
        bool(lead.website) or "No website" in " ".join(leaks),
        lead.audit is not None,
        bool(competitors),
    ]
    evidence_confidence = round(sum(evidence_items) / len(evidence_items) * 100)
    plan, seller_pricing = build_adaptive_sales_plan(session, lead, competitors=competitors) if session else (None, None)
    assessment = plan.smart_offer.intervention_assessment if plan else {}
    if plan:
        leaks = list(plan.evidence_lines) or [str(assessment.get("summary") or "Evidence needs review.")]
    verification = loads(lead.verification_json, {})
    verify_labels = {
        "business_identity": "Confirm the business identity and location.",
        "phone": "Confirm the phone number.",
        "website": "Open the current website and verify major claims.",
        "competitors": "Confirm the selected competitors are genuinely comparable.",
        "offer": "Confirm the proposed scope fits the observed evidence.",
        "price": "Choose the actual price and scope manually.",
        "outreach": "Review the final outreach wording.",
    }

    return OwnerBrief(
        opportunity=str(assessment.get("state") or "insufficient_evidence").replace("_", " "),
        business_size="Not available from public Places data",
        likely_decision_maker="Owner or manager — verify before outreach",
        revenue_leaks=leaks,
        recommended_opening=plan.smart_offer.first_step if plan else "Verify current evidence before proposing paid work.",
        build_difficulty="Scope-specific effort requires platform/access confirmation; ranking difficulty is unknown.",
        suggested_package=plan.smart_offer.offer_name if plan else "No paid recommendation",
        suggested_range=seller_pricing.project.range_text if seller_pricing else "Evidence review required",
        evidence_confidence=evidence_confidence,
        confidence_note="Evidence completeness only; this is not a revenue or close-probability prediction.",
        verify_before_calling=[label for key, label in verify_labels.items() if not verification.get(key)],
        project_value_range=(seller_pricing.project.range_text if seller_pricing else "Evidence review required"),
        easy_close_ask=(seller_pricing.easy_close if seller_pricing else None),
        recommended_ask=(seller_pricing.recommended if seller_pricing else None),
        stretch_ask=(seller_pricing.stretch if seller_pricing else None),
        pricing_confidence=(seller_pricing.confidence if seller_pricing else "Limited seller history"),
        pricing_reasoning=(seller_pricing.reasoning if seller_pricing else ("A fresh commercial context is required before quoting.",)),
        price_answer=(seller_pricing.price_answer if seller_pricing else "Select a price after reviewing private seller history."),
    )


def opportunity_label(score: int) -> str:
    if score >= 75:
        return "High"
    if score >= 50:
        return "Moderate"
    return "Early / needs more evidence"


def difficulty_label(lead: Lead) -> str:
    if not lead.website:
        return "Moderate — new presence required"
    weakness_count = len(loads(lead.audit.weaknesses_json, [])) if lead.audit else 0
    if weakness_count <= 4:
        return "Easy — focused improvements"
    if weakness_count <= 8:
        return "Moderate — several connected fixes"
    return "Higher — broad rebuild or deeper review"
