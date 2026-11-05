from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.pricing_repository import current_seller_semantic_revision
from local_presence_miner.database.repositories import dumps, save_outreach_draft
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.services.adaptive_outreach_service import AdaptiveOutreachService, AdaptiveSalesPlan
from local_presence_miner.services.commercial_plan_service import build_current_offer_context
from local_presence_miner.services.commercial_state_service import persist_current_plan
from local_presence_miner.services.conversation_state_service import ConversationStateService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.seller_pricing_service import SellerPricingRecommendation, SellerPricingService


@dataclass(frozen=True)
class AdaptiveSalesAssets:
    plan: AdaptiveSalesPlan
    pricing: SellerPricingRecommendation
    draft_count: int


def build_adaptive_sales_plan(
    session: Session,
    lead: Lead,
    *,
    competitors: list[CompetitorRecord] | None = None,
    city: str = "",
    state_region: str = "",
) -> tuple[AdaptiveSalesPlan, SellerPricingRecommendation]:
    """Canonical side-effect-free Smart Offer planner used by every surface."""
    plan, pricing, _context = build_adaptive_sales_plan_with_context(
        session, lead, competitors=competitors, city=city, state_region=state_region
    )
    return plan, pricing


def build_adaptive_sales_plan_with_context(
    session: Session,
    lead: Lead,
    *,
    competitors: list[CompetitorRecord] | None = None,
    city: str = "",
    state_region: str = "",
):
    """Return the plan, pricing, and the one immutable context used for both."""
    if competitors is None:
        competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
    conversation = ConversationStateService().build(session, lead)
    context, starting_offer = build_current_offer_context(
        session, lead, competitors=competitors, city=city, state_region=state_region, conversation=conversation
    )
    pricing = SellerPricingService().recommend(
        session, lead, competitors, current_offer=starting_offer, current_offer_context=context
    )
    google_presence = dict(context.planning_inputs.get("google", {}))
    plan = AdaptiveOutreachService().build(
        lead,
        competitors,
        pricing,
        starting_offer,
        conversation=conversation,
        google_presence=google_presence,
        scope_override=context.scope,
        offer_fusion=context.offer_fusion,
    )
    return plan, pricing, context


def refresh_adaptive_sales_assets(
    session: Session,
    lead: Lead,
    sender: SenderInfo,
    *,
    competitors: list[CompetitorRecord] | None = None,
    city: str = "",
    state_region: str = "",
) -> AdaptiveSalesAssets:
    """Regenerate the Smart Offer and human-reviewed scripts from current evidence and conversation state."""
    plan, pricing, context = build_adaptive_sales_plan_with_context(
        session,
        lead,
        competitors=competitors,
        city=city,
        state_region=state_region,
    )
    lead.starting_offer_json = dumps(plan.smart_offer.to_dict())
    lead.adaptive_assets_revision = current_seller_semantic_revision(session)
    # Retain the exact context used to calculate the current Smart Offer.
    commercial_snapshot = persist_current_plan(
        session, lead, competitors=competitors or [], pricing=pricing, context=context
    )
    outreach_service = OutreachService(sender)
    drafts = outreach_service.generate_all(
        lead,
        city=city,
        state_region=state_region,
        pricing=pricing,
        competitors=competitors,
        adaptive_plan=plan,
        session=session,
    )
    dependencies = outreach_service.proof_dependencies(lead, session, research_only=plan.segment in {"Hold", "Reject"})
    for kind, (subject, body) in drafts.items():
        save_outreach_draft(
            session, lead.id, kind, subject, body, proof_dependencies=dependencies.get(kind, []),
            commercial_snapshot=commercial_snapshot.to_dict(),
        )
    return AdaptiveSalesAssets(plan, pricing, len(drafts))


def refresh_after_interaction_change(session: Session, lead_id: int, sender: SenderInfo) -> AdaptiveSalesAssets | None:
    """Canonical post-mutation pipeline for contact-history changes."""
    lead = session.get(Lead, lead_id)
    if lead is None:
        return None
    return refresh_adaptive_sales_assets(session, lead, sender)


def refresh_after_seller_proof_change(session: Session, sender: SenderInfo) -> int:
    """Refresh every lead's dynamic offer and unapproved scripts after proof changes."""
    leads = list(session.execute(select(Lead).order_by(Lead.id)).scalars())
    for lead in leads:
        refresh_adaptive_sales_assets(session, lead, sender)
    return len(leads)


def refresh_after_seller_semantic_change(session: Session, sender: SenderInfo) -> int:
    """Authoritative propagation for profile, project, proof, and offer-history mutations."""
    return refresh_after_seller_proof_change(session, sender)
