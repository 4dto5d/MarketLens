from __future__ import annotations

from dataclasses import asdict, dataclass, field

from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.models import StartingOffer
from local_presence_miner.domain.offer_presentation import (
    conversation_focus,
    conversation_framing_for_offer,
    presentation_for_offer,
)
from local_presence_miner.domain.offer_registry import offer_definition
from local_presence_miner.services.conversation_state_service import ConversationState
from local_presence_miner.services.seller_pricing_service import SellerPricingRecommendation


@dataclass(frozen=True)
class SmartOfferDraft:
    headline: str
    offer_type: str
    offer_name: str
    positioning: str
    primary_outcome: str
    scope: tuple[str, ...]
    easy_close: int | None
    recommended_ask: int | None
    stretch: int | None
    pricing_confidence: str
    why_this_offer: tuple[str, ...]
    first_step: str
    boundary: str
    human_checks: tuple[str, ...]
    offer_id: str = ""
    resolution_status: str = "resolved"
    intervention_assessment: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AdaptiveSalesPlan:
    intelligence_level: str
    segment: str
    primary_theme: str
    primary_problem: str
    message_strategy: str
    call_objective: str
    email_objective: str
    evidence_lines: tuple[str, ...]
    decision_questions: tuple[str, ...]
    do_not_claim: tuple[str, ...]
    smart_offer: SmartOfferDraft
    offer_fusion: dict | None = None


class AdaptiveOutreachService:
    """Turns stored evidence into human-reviewed sales decision support.

    This service is deliberately deterministic. It adapts language and scope from
    the current lead, qualification snapshot, competitor evidence, and seller-side
    pricing, but it does not infer private facts or learn from outcomes by itself.
    """

    def build(
        self,
        lead: Lead,
        competitors: list[CompetitorRecord],
        pricing: SellerPricingRecommendation | None,
        starting_offer: StartingOffer,
        conversation: ConversationState | None = None,
        google_presence: dict | None = None,
        scope_override: tuple[str, ...] | None = None,
        offer_fusion: dict | None = None,
    ) -> AdaptiveSalesPlan:
        qualification = loads(lead.qualification_json, {})
        conversation = conversation or ConversationState()
        signals = [str(item).strip() for item in loads(lead.target_signals_json, []) if str(item).strip()]
        primary_signal = select_primary_signal(signals, bool(lead.website))
        theme, problem, outcome, first_scope = _theme_for(primary_signal, bool(lead.website))
        google_presence = google_presence or {}
        google_action = str(google_presence.get("recommended_action") or "")
        google_gaps = tuple(str(item) for item in google_presence.get("observed_gaps", []) if str(item).strip())
        google_comparison = tuple(str(item) for item in google_presence.get("competitor_summary", []) if str(item).strip())
        if google_action == "Google Presence-only":
            theme = "Google presence"
            problem = google_gaps[0].lower() if google_gaps else "the public Google presence trails the evidence available on the website"
            outcome = "a more useful, evidence-aligned public Google presence"
            first_scope = "Public Google presence improvement plan based on observable fields"
        elif google_action == "Website + Google Presence":
            theme = "Cross-surface alignment"
            problem = google_gaps[0].lower() if google_gaps else problem
            outcome = "a clearer website conversion path aligned with the business's public Google evidence"
            first_scope = "Website conversion and Google presence alignment"
        if conversation.business_goal:
            focus = conversation_focus(conversation.business_goal)
            if focus == "lead_quality":
                theme = "Lead quality"
                problem = "the business wants better-fit inquiries rather than simply more inquiries"
                outcome = "clearer service-fit messaging and intake qualification"
                first_scope = "Service-fit messaging and inquiry qualification"
            elif focus == "intake":
                theme = "Intake efficiency"
                problem = "the current intake path may be creating avoidable friction for the business"
                outcome = "an easier, more structured customer intake path"
                first_scope = "Contact and estimate-flow simplification"
            elif focus == "trust":
                theme = "Trust proof"
                problem = "the business wants the public site to better validate the quality of the company"
                outcome = "stronger presentation of verified trust signals"
                first_scope = "Trust-proof and reputation presentation"
        presentation = presentation_for_offer(starting_offer.offer_id)
        canonical_scope = ""
        if presentation is not None:
            framing = conversation_framing_for_offer(starting_offer.offer_id, conversation.business_goal or "")
            selected = framing or presentation
            theme = selected.theme
            problem = selected.problem
            outcome = selected.outcome
            first_scope = selected.first_scope
            canonical_scope = presentation.first_scope if framing is not None else ""
            if not presentation.supports_google_scope:
                google_action = ""
        segment = str(qualification.get("classification") or lead.qualification_class or "Qualified")
        qualification_confidence = str(qualification.get("confidence") or lead.qualification_confidence or "Low")
        strategy, call_objective, email_objective = _strategy_for(segment, qualification_confidence)

        positives = tuple(str(item) for item in qualification.get("positives", []) if str(item).strip())
        if conversation.business_goal:
            positives = (*positives, f"Prospect-stated goal: {conversation.business_goal}")
        disconfirmers = tuple(str(item) for item in qualification.get("disconfirmers", []) if str(item).strip())
        unknowns = tuple(str(item) for item in qualification.get("unknowns", []) if str(item).strip())
        evidence = tuple(
            dict.fromkeys(
                [
                    f"Observed opportunity: {primary_signal}",
                    *positives[:2],
                    *(
                        [f"Selected comparison set: {len(competitors)} nearby business(es)."]
                        if competitors
                        else ["No selected competitor evidence is available yet."]
                    ),
                    *([f"Conversation context: {conversation.business_goal}"] if conversation.business_goal else []),
                    *([f"Google evidence: {google_gaps[0]}"] if google_gaps else []),
                    *([f"Google comparison: {google_comparison[0]}"] if google_comparison else []),
                ]
            )
        )

        google_scope: tuple[str, ...] = ()
        if google_action == "Google Presence-only":
            google_scope = (
                "Verify public phone, hours, website link, category, and photo evidence",
                "Create an owner-authorized Google improvement checklist",
            )
        elif google_action == "Website + Google Presence":
            google_scope = (
                "Align verified reputation and service evidence across Google and the website",
                "Create an owner-authorized Google improvement checklist",
            )
        scope_items = scope_override if scope_override is not None else (
            first_scope, canonical_scope, *google_scope, *starting_offer.scope
        )
        scope = tuple(dict.fromkeys(item.strip() for item in scope_items if item and item.strip()))
        why = [
            f"Sales Priority {lead.sales_priority_score or 0}/100: {segment} with {qualification_confidence} qualification confidence.",
            f"The first scope item responds directly to the observed {theme.lower()} gap.",
        ]
        if competitors:
            why.append(f"The recommendation can be demonstrated against {len(competitors)} selected nearby comparison(s).")
        if google_presence:
            why.append(
                f"Google Presence is {google_presence.get('strength_score', 0)}/100 strength and "
                f"{google_presence.get('opportunity_score', 0)}/100 opportunity with "
                f"{str(google_presence.get('confidence', 'Low')).lower()} evidence confidence."
            )
        if pricing and pricing.price_available:
            why.append(
                f"Seller Pricing Intelligence supports a {pricing.recommended_text} recommended ask with {pricing.confidence.lower()} seller-proof confidence."
            )
        elif pricing:
            why.append("Seller Pricing Intelligence is unavailable until the current commercial offer is resolved.")
        else:
            why.append("Seller Pricing Intelligence was not supplied; manually confirm price before presenting the offer.")
        if offer_fusion and offer_fusion.get("findings"):
            why.append(str(offer_fusion.get("explanation") or "Search Market advice was reviewed."))

        human_checks = [
            f"Verify the public evidence behind: {primary_signal}.",
            "Confirm the proposed scope matches what the business actually wants before presenting it.",
            "Review every email or call response manually; nothing is sent or dialed automatically.",
        ]
        if unknowns:
            human_checks.append("Resolve missing evidence before making a confident claim: " + "; ".join(unknowns[:2]))
        if disconfirmers:
            human_checks.append("Address or accept the disconfirming evidence: " + "; ".join(disconfirmers[:2]))
        if segment in {"Hold", "Reject"}:
            human_checks.append("Missing evidence or a disqualifier makes this research-first; do not cold pitch yet.")
        if conversation.buyer_questions:
            human_checks.append("Answer only buyer questions you can support: " + "; ".join(conversation.buyer_questions[:3]))
        if conversation.credibility_concern:
            human_checks.append("Resolve the recorded credibility concern with relevant Seller Proof before pressing the offer.")
        if conversation.concerned_about_ai:
            human_checks.append("Explain the evidence, verification, and human-review system around AI; do not defend AI with guarantees.")

        recommended = pricing.recommended if pricing else None
        easy = pricing.easy_close if pricing else None
        stretch = pricing.stretch if pricing else None
        pricing_confidence = pricing.confidence if pricing else "Unverified"
        positioning = _positioning(theme, bool(lead.website), segment)
        assessment = (offer_fusion or {}).get("intervention_assessment") or {}
        if assessment:
            candidates = assessment.get("ranked_candidates", ())
            selected_candidate = next((item for item in candidates if item.get("offer_id") == starting_offer.offer_id
                                       and starting_offer.offer_id), None)
            why = [str(assessment.get("summary") or "Evidence needs review."),
                   str((offer_fusion or {}).get("explanation") or "")]
            if selected_candidate:
                problem = selected_candidate["problem_hypothesis"]
                outcome = selected_candidate["expected_effect"]
                positioning = selected_candidate["why_over_alternatives"]
                why.extend((selected_candidate["why_now"], selected_candidate["why_over_alternatives"]))
                evidence = tuple(selected_candidate["observations"])
            elif not (pricing and pricing.price_available):
                theme = "No paid intervention" if assessment["state"] == "no_sale" else "Evidence validation"
                problem = str(assessment["summary"])
                outcome = "Confirm a meaningful business need before proposing paid work."
                positioning = "No new paid scope is justified by the current evidence."
                evidence = tuple(item for candidate in candidates for item in candidate["observations"])
            else:
                positioning = "Retained human-selected scope; the current assessment does not establish it as the highest-leverage purchase."
                evidence = ()
            human_checks.extend(str(item) for item in assessment.get("unknowns", ()))
            if conversation.business_goal:
                evidence = (*evidence, f"Prospect-stated goal: {conversation.business_goal}")
            why.append("Recommendation confidence concerns source support; pricing confidence concerns seller proof. Neither predicts ROI.")
            if pricing and pricing.price_available:
                why.append(f"Catalog-based ask: {pricing.recommended_text}; verify effort and access before quoting this exact scope.")
        smart_offer = SmartOfferDraft(
            headline=f"Smart Offer — {lead.name}",
            offer_type=("no_paid_recommendation" if assessment and not (pricing and pricing.price_available) else
                        offer_definition(starting_offer.offer_id).semantic_family if presentation else google_action or "Website-only"),
            offer_name=("No paid recommendation" if assessment and not (pricing and pricing.price_available) else starting_offer.offer_name),
            positioning=positioning,
            primary_outcome=outcome,
            scope=scope,
            easy_close=easy,
            recommended_ask=recommended,
            stretch=stretch,
            pricing_confidence=pricing_confidence,
            why_this_offer=tuple(why),
            first_step=(
                "No paid work is justified now; revisit only when a meaningful need is evidenced."
                if assessment.get("state") == "no_sale" else
                "Validate the observation, owner goal and relevant baseline before discussing a paid scope."
                if assessment and not (pricing and pricing.price_available) else
                conversation.next_action or _first_step(segment, starting_offer.first_ask)
            ),
            boundary=(
                "This is a scoped recommendation based on public evidence and recorded seller history. "
                "It does not guarantee rankings, leads, calls, revenue, or the prospect's ability to pay."
            ),
            human_checks=tuple(human_checks),
            offer_id=starting_offer.offer_id,
            resolution_status=starting_offer.resolution_status,
            intervention_assessment=assessment,
        )
        return AdaptiveSalesPlan(
            intelligence_level=str(assessment.get("confidence") or "Unverified"),
            segment=segment,
            primary_theme=theme,
            primary_problem=problem,
            message_strategy=strategy,
            call_objective=call_objective,
            email_objective=email_objective,
            evidence_lines=evidence,
            decision_questions=tuple(dict.fromkeys((*_decision_questions(theme, segment), *(conversation.buyer_questions[:2])))),
            do_not_claim=(
                "Do not claim lost revenue or a conversion lift without the owner's data.",
                "Do not claim a competitor is winning customers; describe only observed public differences.",
                "Do not describe Places search result order as an exact Google Maps ranking.",
                "Do not claim access to private Google Business Profile settings or unpublished completeness data.",
                "Do not assume budget, decision-maker identity, capacity, or urgency.",
            ),
            smart_offer=smart_offer,
            offer_fusion=offer_fusion,
        )


def _theme_for(signal: str, has_website: bool) -> tuple[str, str, str, str]:
    text = signal.strip().rstrip(".")
    lower = text.casefold()
    if not has_website or "no website" in lower or "broken website" in lower:
        return (
            "Digital foundation",
            "customers do not have a dependable business-owned page that explains the business and gives them a clear next step",
            "a credible, mobile-friendly landing and contact path",
            "Focused one-page local presence with a verified contact path",
        )
    if any(token in lower for token in ("cta", "quote", "estimate", "contact form", "tap-to-call", "phone button", "booking")):
        return (
            "Conversion path",
            "the next step for a customer is not obvious or easy from the current public site",
            "a clearer path from interest to a real inquiry",
            "Homepage CTA and estimate/request flow",
        )
    if any(token in lower for token in ("review", "trust", "warrant", "financing", "photo", "proof", "credential")):
        return (
            "Trust proof",
            "useful public proof is not being surfaced clearly before a customer decides whether to contact the business",
            "stronger presentation of verified trust signals",
            "Verified review and trust-proof presentation",
        )
    if any(token in lower for token in ("mobile", "slow", "viewport", "performance")):
        return (
            "Mobile friction",
            "mobile visitors may face avoidable friction while trying to understand the business or make contact",
            "a faster, clearer mobile contact experience",
            "Mobile-first homepage and contact-flow repair",
        )
    return (
        "Public presence",
        text[:1].lower() + text[1:] if text else "a public-facing gap needs manual review",
        "a clearer and more credible public customer experience",
        "Evidence-backed public-presence improvement",
    )


def select_primary_signal(signals: list[str], has_website: bool) -> str:
    """Choose a stable, intervention-relevant lead signal independent of list order."""
    cleaned = [item.strip() for item in signals if item.strip()]
    if not cleaned:
        return "No verified revenue leak captured yet"
    priority = {
        "Digital foundation": 5,
        "Conversion path": 4,
        "Mobile friction": 3,
        "Trust proof": 2,
        "Public presence": 1,
    }
    return min(
        cleaned,
        key=lambda item: (-priority[_theme_for(item, has_website)[0]], item.casefold()),
    )


def _strategy_for(segment: str, confidence: str) -> tuple[str, str, str]:
    if segment == "Demo Priority":
        return (
            "Lead with one verified gap, show the comparison, then offer a focused demonstration instead of a full redesign pitch.",
            "Confirm the gap matters, learn the owner's actual goal, and earn permission to show the focused concept.",
            "Offer the short evidence comparison first, then introduce the focused scope only after interest.",
        )
    if segment == "High Priority":
        return (
            "Lead with the strongest verified gap and connect it to a narrow, practical first scope.",
            "Confirm the business goal and determine whether the core or phased offer fits.",
            "Use a specific evidence-led opening and one low-friction question.",
        )
    if segment == "Qualified":
        return (
            "Use permission-based outreach and keep the first ask to reviewing the evidence.",
            "Learn whether the observed issue matters before discussing a full project.",
            "Send a concise observation and ask permission to share the comparison.",
        )
    if segment == "Reject":
        return (
            "Do not pursue unless a human review overturns the disqualifier.",
            "Do not pitch; confirm suppression and disqualifying evidence.",
            "Do not send cold outreach while the lead remains rejected.",
        )
    confidence_note = "low-confidence" if confidence == "Low" else "incomplete"
    return (
        f"Research first because the qualification is {confidence_note}; resolve unknowns before choosing an offer.",
        "Do not pitch yet; verify the business, the primary gap, and a usable contact route.",
        "Do not send a confident offer until the missing evidence is reviewed.",
    )


def _positioning(theme: str, has_website: bool, segment: str) -> str:
    if segment in {"Hold", "Reject"}:
        return "Draft for internal review only; the lead is not ready for a confident offer."
    if not has_website:
        return "Start with a focused business-owned web presence, not an open-ended marketing build."
    if theme in {"Conversion path", "Trust proof", "Mobile friction"}:
        return "Lead with a targeted improvement to the current site; do not assume a full redesign is necessary."
    return "Start with the smallest evidence-backed scope that improves the documented public-facing gap."


def _first_step(segment: str, default: str) -> str:
    if segment in {"Hold", "Reject"}:
        return "Complete manual evidence review and recalculate qualification before outreach."
    return default


def _decision_questions(theme: str, segment: str) -> tuple[str, ...]:
    questions = [
        "Is this the person who decides how the website or customer contact flow is handled?",
        "Does the observed issue create any friction the business actually wants to solve?",
        "Would a focused first phase be more useful than a broader rebuild?",
    ]
    if theme == "Conversion path":
        questions.insert(1, "How do you prefer new customers to request a quote or start a conversation today?")
    elif theme == "Trust proof":
        questions.insert(1, "Which proof matters most to your customers before they contact you?")
    elif theme == "Mobile friction":
        questions.insert(1, "Do most new inquiries begin by phone, form, or another mobile action?")
    elif theme in {"Google presence", "Cross-surface alignment"}:
        questions.insert(1, "Does the business owner control the public Google profile and want help reviewing the observed fields?")
    if segment in {"Hold", "Reject"}:
        questions = ["What evidence is missing or disqualifying, and can it be verified without guessing?"]
    return tuple(questions)


def format_smart_offer(offer: SmartOfferDraft) -> str:
    assessment = offer.intervention_assessment
    reasoning = ""
    if assessment:
        reasoning = f"\n\nDecision: {assessment['state']}\nRecommendation confidence: {assessment['confidence']}\n{assessment['summary']}"
        for rank, candidate in enumerate(assessment.get("ranked_candidates", ()), 1):
            reasoning += (
                f"\n\n{rank}. {candidate['intervention_id'].replace('_', ' ')} — {candidate['fit']} fit / {candidate['status']}"
                f"\nObserved: {'; '.join(candidate['observations'])}"
                f"\nSources: {'; '.join(candidate['evidence_refs'])}"
                f"\nWhy now: {candidate['why_now']}\nWhy over alternatives: {candidate['why_over_alternatives']}"
                f"\nExpected effect (hypothesis): {candidate['expected_effect']}\nMeasure: {candidate['success_metric']}"
                f"\nWould falsify: {candidate['falsifier']}\nEffort: {candidate['effort']}"
            )
        reasoning += "\n\nUnknowns:\n- " + "\n- ".join(assessment.get("unknowns", ()))
    prices = (
        f"Lower planning ask: ${offer.easy_close:,}\nRecommended ask: ${offer.recommended_ask:,}\nUpper planning ask (same scope): ${offer.stretch:,}"
        if offer.easy_close is not None and offer.recommended_ask is not None and offer.stretch is not None
        else "Pricing: no paid recommendation; validate a meaningful need before quoting."
    )
    return (
        f"{offer.headline}\n\n"
        f"Offer type: {offer.offer_type}\nOffer: {offer.offer_name}\n"
        f"Positioning: {offer.positioning}\n"
        f"Primary outcome: {offer.primary_outcome}\n\n"
        f"{prices}\nPricing confidence: {offer.pricing_confidence}\n\n"
        "Recommended scope:\n- "
        + ("\n- ".join(offer.scope) if offer.scope else "No paid scope justified by current evidence.")
        + "\n\nWhy this offer:\n- "
        + "\n- ".join(offer.why_this_offer)
        + f"\n\nFirst step: {offer.first_step}\n\nBoundary: {offer.boundary}\n\nHuman checks:\n- "
        + "\n- ".join(offer.human_checks) + reasoning
    )


def _offer_name(action: str, fallback: str) -> str:
    """Deprecated display helper retained for source compatibility; never changes semantic identity."""
    return fallback
