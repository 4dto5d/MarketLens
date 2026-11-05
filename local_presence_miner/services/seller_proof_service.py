from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from sqlalchemy.orm import Session

from local_presence_miner.database.pricing_repository import list_offer_history, list_seller_projects, list_seller_proof
from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import OfferHistory, SellerProject, SellerProof
from local_presence_miner.domain.niche_taxonomy import niche_relation
from local_presence_miner.services.proof_dependency_service import (
    USAGE_CASE_STUDY,
    USAGE_CLIENT_NAME,
    USAGE_PUBLIC_URL,
    USAGE_TESTIMONIAL,
    proof_allows_external_use,
)

# Transparent evidence weights. They classify evidence strength; they never multiply Project Value.
PROOF_WEIGHTS = {
    "Paid Project": 3,
    "Case Study": 3,
    "Before / After": 2,
    "Testimonial": 2,
    "Relevant Employment Experience": 2,
    "Certification": 1,
    "Portfolio Example": 1,
    "Unpaid Project": 1,
    "Other": 1,
}
PROJECT_PROOF_TYPES = {"Paid Project", "Unpaid Project", "Portfolio Example", "Case Study", "Before / After"}
PROJECT_PROOF_TYPES.update(
    {
        "Local-Business Website Project",
        "Audit Project",
        "Google Presence Project",
        "AI / Software System",
        "Automation Workflow",
        "Data-Processing Pipeline",
        "Portfolio Concept",
        "Niche-Specific Project",
    }
)
COMPLETED_PROOF_STATUSES = {
    "Completed",
    "Completed + Verified",
    "Completed + Testimonial",
    "Completed + Measurable Result",
}


@dataclass(frozen=True)
class SellerProofSummary:
    completed_projects: int
    completed_paid_projects: int
    relevant_niche_projects: int
    testimonials: int
    case_studies: int
    verified_items: int
    comparable_won_jobs: int
    median_closed_project: int | None
    recent_pricing_trend: str
    evidence_confidence: str
    relevant_items: tuple[SellerProof, ...]
    evidence_points: int
    proof_artifacts: int

    def snapshot(self) -> dict:
        return {
            "completed_projects": self.completed_projects,
            "completed_paid_projects": self.completed_paid_projects,
            "relevant_niche_projects": self.relevant_niche_projects,
            "testimonials": self.testimonials,
            "case_studies": self.case_studies,
            "verified_items": self.verified_items,
            "comparable_won_jobs": self.comparable_won_jobs,
            "median_closed_project": self.median_closed_project,
            "recent_pricing_trend": self.recent_pricing_trend,
            "evidence_confidence": self.evidence_confidence,
            "proof_artifacts": self.proof_artifacts,
            "relevant_items": [
                {"proof_type": item.proof_type, "title": item.title, "niche": item.niche, "verified": item.verified} for item in self.relevant_items
            ],
        }


def summarize_seller_proof(session: Session, niche: str = "") -> SellerProofSummary:
    projects = list_seller_projects(session)
    current_project_ids = {item.id for item in projects if item.active and item.invalidated_at is None}
    proofs = [
        item
        for item in list_seller_proof(session)
        if artifact_is_active(item) and (item.project_id is None or item.project_id in current_project_ids)
    ]
    completed = [item for item in proofs if proof_is_completed(item)]
    offers = list_offer_history(session)
    niche_present = bool(niche.strip())
    relevant = tuple(item for item in proofs if niche_present and niche_relation(item.niche, niche) == "same")
    explicit_completed = [item for item in projects if project_is_completed(item) and item.client_work]
    completed_project_keys = {item.id for item in explicit_completed}
    explicit_relevant = [item for item in explicit_completed if niche_present and niche_relation(item.niche, niche) == "same"]
    relevant_project_keys = {item.id for item in explicit_relevant}
    paid_project_keys = {item.id for item in explicit_completed if item.project_type == "Paid Project"}
    testimonials = [item for item in completed if item.proof_type == "Testimonial" or item.testimonial_available]
    case_studies = [item for item in completed if item.proof_type == "Case Study"]
    won = [item for item in offers if item.status == "Won" and item.closed_amount]
    relevant_won = [item for item in won if niche_present and niche_relation(item.niche, niche) == "same"]
    verified = [item for item in proofs if item.verified]
    relevant_paid_count = (
        sum(
            1
            for item in explicit_completed
            if item.project_type == "Paid Project" and niche_relation(item.niche, niche) == "same"
        )
        if niche_present
        else 0
    )
    relevant_verified = [item for item in relevant if item.verified]
    points = sum(PROOF_WEIGHTS.get(item.proof_type, 1) * (2 if item.verified else 1) for item in proofs)
    relevant_points = sum(PROOF_WEIGHTS.get(item.proof_type, 1) for item in relevant)
    if niche_present:
        if relevant_paid_count >= 3 and len(relevant_verified) >= 4 and len(relevant_won) >= 2:
            confidence = "Strong"
        elif relevant_paid_count >= 1 and (len(relevant_won) >= 1 or relevant_points >= 4):
            confidence = "Moderate"
        else:
            confidence = "Low"
    elif len(paid_project_keys) >= 4 and len(verified) >= 5 and len(won) >= 3:
        confidence = "Strong"
    elif len(paid_project_keys) >= 2 or len(won) >= 2:
        confidence = "Moderate"
    else:
        confidence = "Low"
    return SellerProofSummary(
        completed_projects=len(completed_project_keys),
        completed_paid_projects=len(paid_project_keys),
        relevant_niche_projects=len(relevant_project_keys),
        testimonials=len(testimonials),
        case_studies=len(case_studies),
        verified_items=len(verified),
        comparable_won_jobs=len(relevant_won),
        median_closed_project=round(median([item.closed_amount for item in won])) if won else None,
        recent_pricing_trend=pricing_trend(won),
        evidence_confidence=confidence,
        relevant_items=relevant[:5],
        evidence_points=points,
        proof_artifacts=len(proofs),
    )


def pricing_trend(won: list[OfferHistory]) -> str:
    ordered = sorted(won, key=lambda item: (item.offer_date, item.id or 0), reverse=True)
    if len(ordered) < 4:
        return "Not enough won history"
    recent = median([item.closed_amount for item in ordered[:3] if item.closed_amount])
    prior = median([item.closed_amount for item in ordered[3:6] if item.closed_amount])
    if recent > prior * 1.1:
        return "Increasing"
    if recent < prior * 0.9:
        return "Decreasing"
    return "Stable"


def safe_proof_sentence(summary: SellerProofSummary, niche: str) -> str:
    for item in summary.relevant_items:
        if not item.verified or not proof_is_completed(item):
            continue
        name = f" for {item.client_name}" if proof_allows_external_use(item, USAGE_CLIENT_NAME) else ""
        if item.proof_type == "Testimonial" and proof_allows_external_use(item, USAGE_TESTIMONIAL):
            return f"I have a verified relevant testimonial{name} with permission to share it."
        if item.proof_type in {"Paid Project", "Unpaid Project", "Portfolio Example", "Case Study", "Before / After"} and any(
            proof_allows_external_use(item, usage) for usage in (USAGE_PUBLIC_URL, USAGE_CASE_STUDY)
        ):
            return f"I have a verified relevant {niche or 'local-business'} example{name} with permission to share it."
    return ""


def proof_is_completed(item: SellerProof) -> bool:
    return str(getattr(item, "status", "Unclassified") or "Unclassified") in COMPLETED_PROOF_STATUSES


def project_is_completed(item: SellerProject) -> bool:
    return (
        bool(item.active)
        and str(item.counting_state or "legacy_unresolved") == "confirmed"
        and str(item.status or "Unclassified") in COMPLETED_PROOF_STATUSES
        and bool(item.client_work)
        and item.invalidated_at is None
    )


def artifact_is_active(item: SellerProof) -> bool:
    return str(getattr(item, "artifact_state", "active") or "active") == "active"


def safe_claims(item: SellerProof) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in loads(getattr(item, "safe_claims_json", "[]"), []) if str(value).strip())


def prohibited_claims(item: SellerProof) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in loads(getattr(item, "prohibited_claims_json", "[]"), []) if str(value).strip())
