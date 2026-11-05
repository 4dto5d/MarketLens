"""Commercial snapshot persistence and targeted approval freshness checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from local_presence_miner.database.repositories import dumps
from local_presence_miner.database.schema import OutreachDraft
from local_presence_miner.domain.commercial import CommercialPlanState, make_dependency_snapshot
from local_presence_miner.domain.niche_taxonomy import niche_relation
from local_presence_miner.services.commercial_plan_service import build_current_offer_context

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from local_presence_miner.database.schema import CompetitorRecord, Lead, OfferHistory, SellerProject, SellerProof
    from local_presence_miner.services.seller_pricing_service import SellerPricingRecommendation


def _project_dependency(project: SellerProject) -> dict[str, Any]:
    """Exact project fields that can make pricing evidence/counts material."""
    return {
        "project_id": project.id,
        "project_type": project.project_type,
        "status": project.status,
        "counting_state": project.counting_state,
        "active": bool(project.active),
        "client_work": bool(project.client_work),
        "invalidated_at": project.invalidated_at.isoformat() if project.invalidated_at else "",
        "niche": project.niche or "",
        "canonical_niche_id": project.canonical_niche_id or "",
    }


def _proof_dependency(proof: SellerProof) -> dict[str, Any]:
    """Exact proof fields that can change Seller Pricing evidence/reasoning."""
    return {
        "proof_id": proof.id,
        "project_id": proof.project_id,
        "artifact_state": proof.artifact_state,
        "proof_type": proof.proof_type,
        "status": proof.status,
        "niche": proof.niche or "",
        "canonical_niche_id": proof.canonical_niche_id or "",
        "verified": bool(proof.verified),
        "client_work": bool(proof.client_work),
        "testimonial_available": bool(proof.testimonial_available),
        "internal_only": bool(proof.internal_only),
        "share_client_name": bool(proof.share_client_name),
        "share_public_url": bool(proof.share_public_url),
        "share_testimonial": bool(proof.share_testimonial),
        "share_case_study": bool(proof.share_case_study),
        "share_reference": bool(proof.share_reference),
        "client_name": proof.client_name or "",
        "public_url": proof.public_url or "",
        "completion_date": proof.completion_date or "",
    }


def _offer_dependency(offer: OfferHistory) -> dict[str, Any]:
    """All historical-offer fields consumed by similarity or price analysis."""
    return {
        "offer_history_id": offer.id,
        "lead_id": offer.lead_id,
        "offer_date": offer.offer_date,
        "niche": offer.niche or "",
        "canonical_niche_id": offer.canonical_niche_id or "",
        "package_name": offer.package_name or "",
        "canonical_offer_id": offer.canonical_offer_id or "",
        "scope_summary": offer.scope_summary or "",
        "initial_ask": offer.initial_ask,
        "recommended_ask_at_offer": offer.recommended_ask_at_offer,
        "final_ask": offer.final_ask,
        "closed_amount": offer.closed_amount,
        "status": offer.status,
        "lost_reason": offer.lost_reason or "",
        "growth_score_at_offer": offer.growth_score_at_offer,
        "project_value_low_at_offer": offer.project_value_low_at_offer,
        "project_value_high_at_offer": offer.project_value_high_at_offer,
    }


def _pricing_source_dependencies(session: Session, lead: Lead) -> dict[str, Any]:
    """Return only source rows that can affect Seller Pricing's consumed proof metrics.

    This intentionally does *not* include every completed project or every proof
    artifact.  Broad candidate recomputation is safe; broad dependency sets are
    not, because they create false staleness for unrelated evidence.
    """
    from local_presence_miner.database.pricing_repository import (
        list_offer_history,
        list_seller_projects,
        list_seller_proof,
    )
    from local_presence_miner.services.seller_proof_service import (
        artifact_is_active,
        project_is_completed,
        proof_is_completed,
    )

    niche = (lead.category or "").strip()
    projects = list_seller_projects(session, include_inactive=True)
    completed_projects = [item for item in projects if project_is_completed(item)]

    # SellerPricingService/proof_reasoning consumes total paid-project count and
    # same-niche completed-project count/confidence.  An unpaid, different-niche
    # project therefore is not a dependency merely because it exists.
    count_projects = [
        item
        for item in completed_projects
        if item.project_type == "Paid Project" or (niche and niche_relation(item.niche, niche) == "same")
    ]

    current_project_ids = {
        item.id for item in projects if item.id is not None and item.active and item.invalidated_at is None
    }
    proofs = [
        item
        for item in list_seller_proof(session)
        if artifact_is_active(item) and (item.project_id is None or item.project_id in current_project_ids)
    ]
    proof_sources = [
        item
        for item in proofs
        if (
            (niche and niche_relation(item.niche, niche) == "same")
            or (proof_is_completed(item) and (item.proof_type == "Testimonial" or item.testimonial_available))
            or (not niche and item.verified)
        )
    ]

    # Evidence confidence also consumes same-niche won history (or all won
    # history when the lead niche is absent), independently of the selected
    # comparable set used by ComparableOfferService.
    confidence_offers = [
        item
        for item in list_offer_history(session)
        if item.status == "Won"
        and bool(item.closed_amount)
        and ((niche and niche_relation(item.niche, niche) == "same") or not niche)
    ]

    return {
        "count_driving_projects": [_project_dependency(item) for item in sorted(count_projects, key=lambda row: int(row.id or 0))],
        # Preserve list_seller_proof ordering because safe_proof_sentence chooses
        # the first eligible relevant item.
        "pricing_proof_artifacts": [_proof_dependency(item) for item in proof_sources],
        "proof_confidence_offer_history": [
            _offer_dependency(item) for item in sorted(confidence_offers, key=lambda row: int(row.id or 0))
        ],
    }


def snapshot_for_pricing(
    session: Session,
    lead: Lead,
    *,
    competitors: list[CompetitorRecord],
    pricing: SellerPricingRecommendation,
    context,
):
    # The exact immutable context that produced pricing is required. Rebuilding
    # here could pair a price with a different source snapshot.
    source_dependencies = _pricing_source_dependencies(session, lead)
    comparable_dependencies = [
        {
            **_offer_dependency(item.offer),
            "similarity_score": item.similarity_score,
            "similarity_reasons": list(item.reasons),
        }
        for item in pricing.comparable.offers
        if getattr(item.offer, "id", None) is not None
    ]

    # Profile fields are absent because the commercial *plan* does not render
    # SellerProfile identity. Guided Call has its own rendered-guide fingerprint.
    dependencies = {
        "current_offer_context": context.dependency_dict(),
        "pricing_proof_metrics": {
            "completed_paid_projects": pricing.proof.completed_paid_projects,
            "relevant_niche_projects": pricing.proof.relevant_niche_projects,
            "testimonials": pricing.proof.testimonials,
            "evidence_confidence": pricing.proof.evidence_confidence,
        },
        **source_dependencies,
        "selected_comparable_offers": comparable_dependencies,
    }
    output = {
        "project": {
            "offer_id": pricing.project.offer_id,
            "offer_name": pricing.project.offer_name,
            "low": pricing.project.low,
            "high": pricing.project.high,
            "reasoning": list(pricing.project.reasoning),
        },
        "scope": list(context.scope),
        "easy_close": pricing.easy_close,
        "recommended": pricing.recommended,
        "stretch": pricing.stretch,
        "confidence": pricing.confidence,
        "reasoning": list(pricing.reasoning),
        "relevant_proof_sentence": pricing.relevant_proof_sentence,
        "price_answer": pricing.price_answer,
        "phases": [
            {"name": phase.name, "amount": phase.amount, "scope": phase.scope}
            for phase in pricing.phases
        ],
        "objections": [list(item) for item in pricing.objections],
        "comparable": {
            "sample_count": pricing.comparable.sample_count,
            "median_ask": pricing.comparable.median_ask,
            "median_won_price": pricing.comparable.median_won_price,
            "won_count": pricing.comparable.won_count,
            "resolved_price_sample": pricing.comparable.resolved_price_sample,
            "comparable_low": pricing.comparable.comparable_low,
            "comparable_high": pricing.comparable.comparable_high,
            "average_negotiation_discount": pricing.comparable.average_negotiation_discount,
            "success_text": pricing.comparable.success_text,
        },
    }
    return make_dependency_snapshot(
        consumer_kind="commercial_plan",
        lead_id=lead.id,
        current_offer_context_fingerprint=context.context_fingerprint,
        dependencies=dependencies,
        output=output,
    )


def persist_current_plan(
    session: Session,
    lead: Lead,
    *,
    competitors: list[CompetitorRecord],
    pricing: SellerPricingRecommendation,
    context,
):
    snapshot = snapshot_for_pricing(
        session,
        lead,
        competitors=competitors,
        pricing=pricing,
        context=context,
    )
    lead.commercial_plan_snapshot_json = dumps(snapshot.to_dict())
    lead.commercial_dependency_fingerprint = snapshot.dependency_fingerprint
    lead.commercial_output_fingerprint = snapshot.output_fingerprint
    lead.commercial_plan_state = CommercialPlanState.CURRENT.value
    lead.commercial_plan_revision += 1
    from local_presence_miner.time_utils import utc_now

    lead.commercial_plan_generated_at = utc_now()
    return snapshot


def draft_commercial_errors(session: Session, draft: OutreachDraft) -> tuple[str, ...]:
    """Validate cached/approved draft against fresh commercial planning inputs."""
    if draft.commercial_dependency_state != CommercialPlanState.CURRENT.value:
        return ("Commercial plan requires fresh review before approval, copy, or export.",)
    # Widgets can retain a draft after the list-loading session closed. The
    # supplied validation session is the authority, so never lazy-load the
    # relationship from a detached draft instance.
    from local_presence_miner.database.schema import Lead

    lead = session.get(Lead, draft.lead_id)
    if lead is None:
        return ("Draft lead is unavailable.",)
    if lead.commercial_plan_state != CommercialPlanState.CURRENT.value:
        return ("Commercial plan requires fresh review before approval, copy, or export.",)
    if not lead.commercial_dependency_fingerprint or (
        draft.commercial_dependency_fingerprint != lead.commercial_dependency_fingerprint
        or draft.commercial_output_fingerprint != lead.commercial_output_fingerprint
    ):
        return ("Commercial inputs changed; regenerate and review this draft.",)
    # Fingerprints copied from the same stored plan cannot reveal a new run or
    # time-based evidence expiry. Rebuild the dependency at the use boundary.
    errors = current_plan_dependency_errors(session, lead)
    if errors:
        mark_lead_commercial_stale(session, lead, "Current commercial evidence changed or expired")
    return errors


def _fresh_plan_snapshot(session: Session, lead: Lead):
    from local_presence_miner.database.schema import CompetitorRecord
    from local_presence_miner.services.seller_pricing_service import SellerPricingService

    competitors = list(session.scalars(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)))
    context, offer = build_current_offer_context(session, lead, competitors=competitors)
    pricing = SellerPricingService().recommend(
        session, lead, competitors, current_offer=offer, current_offer_context=context,
    )
    return snapshot_for_pricing(
        session, lead, competitors=competitors, pricing=pricing, context=context,
    )


def current_plan_dependency_errors(session: Session, lead: Lead) -> tuple[str, ...]:
    """Pure freshness check, including evidence that expires without a write."""
    if not lead.commercial_dependency_fingerprint or not lead.commercial_output_fingerprint:
        return ("Commercial plan has no current dependency identity; regenerate and review it.",)
    candidate = _fresh_plan_snapshot(session, lead)
    if (
        candidate.dependency_fingerprint != lead.commercial_dependency_fingerprint
        or candidate.output_fingerprint != lead.commercial_output_fingerprint
    ):
        return ("Commercial inputs changed or evidence expired; regenerate and review this draft.",)
    return ()


def mark_lead_commercial_stale(session: Session, lead: Lead, reason: str) -> int:
    """Invalidate only drafts whose recorded plan belongs to this lead."""
    if lead.commercial_plan_state != CommercialPlanState.LEGACY_UNKNOWN_REVIEW_REQUIRED.value:
        lead.commercial_plan_state = CommercialPlanState.STALE.value
    invalidated = 0
    for draft in session.scalars(select(OutreachDraft).where(OutreachDraft.lead_id == lead.id)):
        draft.commercial_dependency_state = CommercialPlanState.STALE.value
        if draft.approved:
            from local_presence_miner.database.repositories import revoke_outreach_approval

            revoke_outreach_approval(session, draft, reason)
            invalidated += 1
    return invalidated


def mark_all_commercial_stale(session: Session, reason: str) -> int:
    return recompute_commercial_candidates(session, reason)


def mark_commercial_stale_for_niche(session: Session, niche: str, reason: str) -> int:
    # Completed paid-project evidence is seller-wide. Recompute every current
    # plan, but revoke only snapshots whose consumed dependencies differ.
    return recompute_commercial_candidates(session, reason)


def mark_commercial_stale_for_proof(session: Session, proof_id: int, reason: str) -> int:
    return recompute_commercial_candidates(session, reason)


def recompute_lead_commercial_candidate(session: Session, lead: Lead, reason: str) -> int:
    """Compare one lead's recorded plan with a fresh, consumer-specific snapshot.

    Mutation seams may know the affected lead exactly. Recomputing is not itself
    invalidation: only a dependency/output mismatch makes the stored plan stale.
    """
    if not lead.commercial_dependency_fingerprint:
        return 0
    if current_plan_dependency_errors(session, lead):
        return mark_lead_commercial_stale(session, lead, reason)
    return 0


def recompute_commercial_candidates(session: Session, reason: str) -> int:
    """Recompute seller-wide candidates, invalidating only actual mismatches."""
    from local_presence_miner.database.schema import Lead

    total = 0
    for lead in session.scalars(select(Lead)):
        total += recompute_lead_commercial_candidate(session, lead, reason)
    return total
