"""Fresh, deterministic commercial planning.

This is deliberately the only place that turns a Lead's *current* public and
conversation evidence into the scope that pricing and outreach may use.  The
persisted Smart Offer is a historical/cache artifact, never an input here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import select

from local_presence_miner.database.repositories import loads
from local_presence_miner.domain.commercial import CurrentOfferContext, fingerprint
from local_presence_miner.domain.models import StartingOffer
from local_presence_miner.domain.niche_taxonomy import NICHE_TAXONOMY_VERSION, resolve_niche
from local_presence_miner.domain.offer_presentation import conversation_focus, conversation_framing_for_offer, presentation_for_offer
from local_presence_miner.domain.offer_registry import OFFER_REGISTRY_VERSION
from local_presence_miner.services.adaptive_outreach_service import _theme_for, select_primary_signal
from local_presence_miner.services.conversation_state_service import ConversationState
from local_presence_miner.services.google_presence_service import assessment_to_dict
from local_presence_miner.services.offer_builder import build_starting_offer_input, generate_starting_offer
from local_presence_miner.services.search_offer_intelligence import fuse_offer

if TYPE_CHECKING:  # pragma: no cover - imports only for static checking
    from sqlalchemy.orm import Session

    from local_presence_miner.database.schema import CompetitorRecord, Lead


def _context_scope(
    lead: Lead, offer: StartingOffer, conversation: ConversationState, google: dict,
) -> tuple[str, ...]:
    """Apply all scope inputs before seller pricing is calculated."""
    signals = [str(item).strip() for item in loads(lead.target_signals_json, []) if str(item).strip()]
    primary_signal = select_primary_signal(signals, bool(lead.website))
    _, _, _, first_scope = _theme_for(primary_signal, bool(lead.website))
    action = str(google.get("recommended_action") or "")
    if action == "Google Presence-only":
        first_scope = "Public Google presence improvement plan based on observable fields"
    elif action == "Website + Google Presence":
        first_scope = "Website conversion and Google presence alignment"
    goal = conversation_focus(conversation.business_goal or "")
    conversation_detail = ""
    if goal == "lead_quality":
        conversation_detail = "Service-fit messaging and inquiry qualification"
    elif goal == "intake":
        conversation_detail = "Contact and estimate-flow simplification"
    elif goal == "trust":
        conversation_detail = "Trust-proof and reputation presentation"
    presentation = presentation_for_offer(offer.offer_id)
    canonical_scope = ""
    if presentation is not None:
        framing = conversation_framing_for_offer(offer.offer_id, conversation.business_goal or "")
        first_scope = framing.first_scope if framing is not None else presentation.first_scope
        canonical_scope = presentation.first_scope if framing is not None else ""
        conversation_detail = ""
        if not presentation.supports_google_scope:
            action = ""
    elif conversation_detail:
        first_scope = conversation_detail
        conversation_detail = ""
    google_scope: tuple[str, ...] = ()
    if action == "Google Presence-only":
        google_scope = (
            "Verify public phone, hours, website link, category, and photo evidence",
            "Create an owner-authorized Google improvement checklist",
        )
    elif action == "Website + Google Presence":
        google_scope = (
            "Align verified reputation and service evidence across Google and the website",
            "Create an owner-authorized Google improvement checklist",
        )
    scope_items = (first_scope, canonical_scope, conversation_detail, *google_scope, *offer.scope)
    return tuple(dict.fromkeys(item.strip() for item in scope_items if item and item.strip()))


def build_current_offer_context(
    session: Session,
    lead: Lead,
    *,
    competitors: list[CompetitorRecord],
    city: str = "",
    state_region: str = "",
    conversation: ConversationState | None = None,
) -> tuple[CurrentOfferContext, StartingOffer]:
    """Return fresh scope and an offer-shaped compatibility view of that scope.

    ``StartingOffer`` remains the compatibility type used by existing price
    math, while ``CurrentOfferContext`` is the semantic authority.
    """
    from local_presence_miner.services.conversation_state_service import ConversationStateService

    starting_input = build_starting_offer_input(lead, competitors, city, state_region)
    base = generate_starting_offer(starting_input)
    conversation = conversation or ConversationStateService().build(session, lead)
    from local_presence_miner.database.schema import GooglePresenceAssessment

    google_record = session.scalar(select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead.id))
    google = assessment_to_dict(google_record)
    if google_record is not None:
        google["assessment_id"] = google_record.id
    fusion = fuse_offer(session, lead, base.offer_id, google=google)
    if fusion.selected_offer_id and fusion.selected_offer_id != base.offer_id and base.resolution_status != "unmapped":
        base = generate_starting_offer(replace(
            starting_input, recommended_offer_id=fusion.selected_offer_id,
            recommended_offer=fusion.selected_offer_id,
        ))
    from local_presence_miner.services.sales_evidence_service import SalesEvidenceService

    evidence = SalesEvidenceService().build(session, lead)
    assessment = fusion.intervention_assessment
    candidates = assessment.get("ranked_candidates", ())
    selected = next((item for item in candidates if item.get("offer_id") == base.offer_id and base.offer_id), None)
    # A recorded human selection remains a quoteable catalog selection, not a
    # machine claim of highest leverage. No-sale/timing decisions never upsell.
    retained_human = bool(fusion.human_quote_authorized and base.offer_id)
    from local_presence_miner.services.owner_strategy_service import project_owner_strategy

    owner_strategy = project_owner_strategy(session, lead)
    unresolved_retained_fit = bool(retained_human and not selected and (
        owner_strategy.get("state") in {"invalid", "ambiguous", "unconfirmed"}
        or owner_strategy.get("constraints") or owner_strategy.get("target_territories")
    ))
    price_allowed = bool(base.offer_id and (
        assessment.get("state") == "recommended" and (selected or retained_human)
        or retained_human and assessment.get("state") == "insufficient_evidence"
    ))
    if unresolved_retained_fit:
        price_allowed = False
        assessment = {**assessment, "state": "validate_first", "owner_fit_status": "unknown",
                      "owner_fit_reason": "The retained human offer's exact scope/service must be reconciled with current owner instructions.",
                      "owner_validation_question": "Does this retained offer and exact scope still satisfy the owner's current instructions?",
                      "summary": "Retain canonical identity and historical quote; validate current owner fit before a new paid commitment."}
    scope = (tuple(selected["scope"]) if selected else _context_scope(lead, base, conversation, {})) if price_allowed else ()
    # Only selected scope/evidence is a pricing dependency. Advisory comparisons
    # remain inspectable without invalidating an otherwise unchanged quote.
    commercial_assessment = {
        "version": assessment.get("version"), "price_allowed": price_allowed,
        "decision": "human_retained" if retained_human and price_allowed and not selected else assessment.get("state"),
        "selected_candidate": selected,
        "decision_refs": assessment.get("evidence_refs", ()) if not price_allowed else (),
        "owner_fit_status": assessment.get("owner_fit_status", "unknown"),
        "owner_fit_reason": assessment.get("owner_fit_reason", ""),
        "owner_validation_question": assessment.get("owner_validation_question", ""),
    }
    niche = resolve_niche(lead.category)
    qualification = loads(lead.qualification_json, {})
    if not isinstance(qualification, dict):
        qualification = {}
    planning_inputs = {
        # Current plan inputs only. Historical/cache JSON and volatile timestamps
        # are deliberately excluded from this authority.
        "lead_name": lead.name or "",
        "target_signals": sorted(str(item).strip() for item in loads(lead.target_signals_json, []) if str(item).strip()),
        "website_present": bool(lead.website),
        "lead_score": int(lead.lead_score or 0),
        "sales_priority_score": int(lead.sales_priority_score or 0),
        "qualification": {
            "classification": str(qualification.get("classification") or lead.qualification_class or ""),
            "confidence": str(qualification.get("confidence") or lead.qualification_confidence or ""),
            "positives": [str(item) for item in qualification.get("positives", []) if str(item).strip()],
            "disconfirmers": [str(item) for item in qualification.get("disconfirmers", []) if str(item).strip()],
            "unknowns": [str(item) for item in qualification.get("unknowns", []) if str(item).strip()],
        },
        "google": {
            "recommended_action": str(google.get("recommended_action") or ""),
            "strength_score": int(google.get("strength_score") or 0),
            "opportunity_score": int(google.get("opportunity_score") or 0),
            "confidence": str(google.get("confidence") or ""),
            "observed_gaps": [str(item) for item in google.get("observed_gaps", []) if str(item).strip()],
            "competitor_summary": [str(item) for item in google.get("competitor_summary", []) if str(item).strip()],
        },
        "conversation": {
            # These are the exact current fields consumed by the plan and its
            # Guided Call rendering.  Historical interactions stay outside this
            # projection; assertion revision identifies the current projection
            # without reviving superseded history.
            "assertion_revision": conversation.assertion_revision,
            "business_goal": conversation.business_goal or "",
            "capacity_status": conversation.capacity_status or "",
            "buyer_questions": list(conversation.buyer_questions),
            "objections": list(conversation.objections),
            "commitments": list(conversation.commitments),
            "next_action": conversation.next_action or "",
            "credibility_concern": bool(conversation.credibility_concern),
            "concerned_about_ai": bool(conversation.concerned_about_ai),
            "ambiguous_subjects": list(conversation.ambiguous_subjects),
        },
        "commercial_disposition": {
            "value": lead.commercial_disposition or "UNKNOWN",
            "revision": int(lead.commercial_disposition_revision or 0),
            "not_before": lead.disposition_not_before or "",
            "follow_up_permission": lead.follow_up_permission or "UNKNOWN",
        },
        "sales_evidence": list(evidence.identity()),
        "competitor_ids": [item.competitor_place_id for item in competitors],
        "intervention_decision": commercial_assessment,
    }
    if material_fusion := fusion.commercial_dependency():
        planning_inputs["search_market_fusion"] = material_fusion
    planning_input_fingerprint = fingerprint(planning_inputs)
    scope_fingerprint = fingerprint({"scope": scope})
    context_document = {
        "offer_id": base.offer_id,
        "resolution_state": base.resolution_status,
        "raw_label": lead.recommended_offer or "",
        "niche": niche.canonical_id if niche.resolved else "",
        "scope_fingerprint": scope_fingerprint,
        "planning_input_fingerprint": planning_input_fingerprint,
        "registry_versions": {"offer": OFFER_REGISTRY_VERSION, "niche": NICHE_TAXONOMY_VERSION},
    }
    context = CurrentOfferContext(
        schema_version=2,
        lead_id=lead.id,
        lead_place_id=lead.place_id or "",
        raw_label=lead.recommended_offer or "",
        supplied_canonical_id=lead.recommended_offer_id or "",
        offer_id=base.offer_id,
        resolution_state=base.resolution_status,
        matched_alias=base.offer_id if fusion.selected_offer_id != starting_input.recommended_offer_id else
        lead.recommended_offer_id or lead.recommended_offer or "",
        registry_version=OFFER_REGISTRY_VERSION,
        selection_source=fusion.selection_source,
        raw_category=lead.category or "",
        canonical_niche_id=niche.canonical_id if niche.resolved else "",
        niche_rule=niche.match_rule,
        niche_registry_version=NICHE_TAXONOMY_VERSION,
        scope=scope,
        scope_template_key=base.offer_id or "unresolved",
        planning_inputs=planning_inputs,
        planning_input_fingerprint=planning_input_fingerprint,
        scope_fingerprint=scope_fingerprint,
        context_fingerprint=fingerprint(context_document),
        offer_fusion=fusion.to_dict(),
        intervention_assessment=assessment,
    )
    return context, replace(base, scope=list(scope))
