from __future__ import annotations

from dataclasses import dataclass, field, replace

from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_tree_identity import CALL_TREE_ID, CALL_TREE_VERSION, FOLLOWUP_NODE_IDS
from local_presence_miner.services.commercial_state_service import snapshot_for_pricing
from local_presence_miner.services.conversation_state_service import ConversationStateService
from local_presence_miner.services.credibility_service import CredibilityService
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.sales_evidence_service import (
    USAGE_OWNER_COPIED,
    USAGE_OWNER_SPOKEN,
    SalesEvidenceService,
)


@dataclass(frozen=True)
class CallFollowUp:
    label: str
    response: str
    next_prompt: str = ""
    followups: tuple[CallFollowUp, ...] = ()
    state_updates: dict[str, object] = field(default_factory=dict)
    # Quick wording is authored, never a sentence fragment mechanically cut
    # from an owner-facing reply.
    quick_response: str = ""
    node_id: str = ""
    strategy_id: str = ""
    response_version: int = 1


@dataclass(frozen=True)
class CallBranch:
    key: str
    label: str
    response: str
    next_prompt: str = ""
    followups: tuple[CallFollowUp, ...] = ()
    state_updates: dict[str, object] = field(default_factory=dict)
    quick_response: str = ""
    node_id: str = ""
    strategy_id: str = ""
    response_version: int = 1


def _followup_snapshot(item: CallFollowUp) -> dict[str, object]:
    return {
        "node_id": item.node_id,
        "strategy_id": item.strategy_id,
        "response_version": item.response_version,
        "label": item.label,
        "response": item.response,
        "next_prompt": item.next_prompt,
        "state_updates": item.state_updates,
        "quick_response": item.quick_response,
        "followups": [_followup_snapshot(child) for child in item.followups],
    }


def _branch_snapshot(item: CallBranch) -> dict[str, object]:
    return {
        "node_id": item.node_id,
        "strategy_id": item.strategy_id,
        "response_version": item.response_version,
        "key": item.key,
        "label": item.label,
        "response": item.response,
        "next_prompt": item.next_prompt,
        "state_updates": item.state_updates,
        "quick_response": item.quick_response,
        "followups": [_followup_snapshot(child) for child in item.followups],
    }


@dataclass(frozen=True)
class CallGuide:
    business_name: str
    opening_15s: str
    opening_30s: str
    full_opening: str
    lead_with: str
    price_answer: str
    branches: tuple[CallBranch, ...]
    intelligence_level: str = "Unverified"
    strategy: str = ""
    recommended_ask: int | None = None
    do_not_claim: tuple[str, ...] = ()
    research_only: bool = False
    why_you: tuple[str, ...] = ()
    proof_attachments: str = ""
    initial_branch_keys: tuple[str, ...] = ()
    call_phase: str = "IDENTITY"
    commercial_dependency_fingerprint: str = ""
    in_person_opening_15s: str = ""
    in_person_opening_30s: str = ""
    in_person_full_opening: str = ""
    other_opening_15s: str = ""
    other_opening_30s: str = ""
    other_full_opening: str = ""
    evidence_claims: tuple[str, ...] = ()
    owner_spoken_claims: tuple[str, ...] = ()
    owner_copied_claims: tuple[str, ...] = ()
    tree_id: str = CALL_TREE_ID
    tree_version: str = CALL_TREE_VERSION
    selected_evidence: dict = field(default_factory=dict)
    evidence_review_state: str = "REVIEW_REQUIRED"
    owner_validation_question: str = ""
    next_step: str = ""
    delivery_packet: dict = field(default_factory=dict)


def response_fingerprint(
    *, tree_id: str, tree_version: str, node_id: str, response_version: int, response: str
) -> str:
    return fingerprint(
        {
            "tree_id": tree_id,
            "tree_version": tree_version,
            "node_id": node_id,
            "response_version": response_version,
            "response": response,
        }
    )


def _identify_call_tree(branches: tuple[CallBranch, ...]) -> tuple[CallBranch, ...]:
    consumed: set[tuple[str, ...]] = set()

    def identify_followup(
        item: CallFollowUp, root_key: str, label_path: tuple[str, ...]
    ) -> CallFollowUp:
        identity_path = (root_key, *label_path, item.label)
        try:
            node_id = FOLLOWUP_NODE_IDS[identity_path]
        except KeyError as exc:
            raise ValueError(f"Guided Call node is missing an authored immutable ID: {identity_path!r}") from exc
        consumed.add(identity_path)
        return replace(
            item,
            node_id=node_id,
            strategy_id=f"gc.strategy.{root_key}",
            followups=tuple(
                identify_followup(child, root_key, (*label_path, item.label)) for child in item.followups
            ),
        )

    identified = tuple(
        replace(
            branch,
            node_id=f"gc.{branch.key}",
            strategy_id=f"gc.strategy.{branch.key}",
            followups=tuple(identify_followup(child, branch.key, ()) for child in branch.followups),
        )
        for branch in branches
    )
    unused = set(FOLLOWUP_NODE_IDS) - consumed
    if unused:
        raise ValueError(f"Guided Call identity registry contains stale paths: {sorted(unused)!r}")
    node_ids = [branch.node_id for branch in identified]
    for branch in identified:
        pending = list(branch.followups)
        while pending:
            item = pending.pop()
            node_ids.append(item.node_id)
            pending.extend(item.followups)
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("Guided Call node IDs must be unique.")
    return identified


class CallGuideService:
    def build(self, session: Session, lead: Lead, competitors: list[CompetitorRecord]) -> CallGuide:
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=competitors)
        first_scope = plan.smart_offer.scope[0].lower() if plan.smart_offer.scope else "validate the actual need before selecting paid work"
        commercial_snapshot = snapshot_for_pricing(session, lead, competitors=competitors, pricing=pricing, context=context)
        conversation = ConversationStateService().build(session, lead)
        credibility = CredibilityService().build(session, lead.category)
        sales_evidence = SalesEvidenceService().build(session, lead, assessment=context.intervention_assessment,
                                                    offer_id=context.offer_id, scope=context.scope)
        delivery_packet = DeliveryPacketService().build(session, lead, context=context, selected_price=pricing.recommended)
        owner_findings = sales_evidence.for_usage(USAGE_OWNER_SPOKEN)
        owner_copy_findings = sales_evidence.for_usage(USAGE_OWNER_COPIED)
        evidence_claims = tuple(item.claim for item in sales_evidence.findings)
        owner_spoken_claims = tuple(item.claim for item in owner_findings)
        owner_copied_claims = tuple(item.claim for item in owner_copy_findings)
        owner_observation = sales_evidence.plain_finding or (owner_findings[0].claim if owner_findings else "")
        verification = loads(lead.verification_json, {})
        competitors_verified = bool(verification.get("competitors"))
        lead_with = owner_observation or plan.primary_problem
        opening_15 = f"Hi, is this the person who handles the website for {lead.name}? I’ll be quick. " + (
            f"I noticed one public-facing point: {owner_observation}. Can I give you the 20-second version?"
            if owner_observation
            else "I have a brief question about how the website supports the business. Is now an okay time?"
        )
        opening_30 = "Hi, I’ll be quick. " + (
            f"I noticed {owner_observation}. Would it be useful if I explained why that may matter?"
            if owner_observation
            else "I’m not assuming you need a redesign; I’d like to understand whether the current website is doing the job you want."
        )
        full = f"Hi, is this the owner, manager, or person who handles the website for {lead.name}? I’ll be quick. " + (
            f"I noticed {owner_observation}. I’m not asking you to replace anything on the spot — would you be open to a 30-second explanation?"
            if owner_observation
            else (
                "I’m calling to understand whether the website has a customer-facing job you want to improve. "
                "I’m not asking you to replace anything on the spot."
            )
        )
        in_person_opening_15 = "Hi, I’m [your name]. I work on public-facing website improvements. " + (
            f"I noticed {owner_observation}. Is this a good moment for the short version?"
            if owner_observation
            else "Is this a good moment for one brief question about the website?"
        )
        in_person_opening_30 = "Hi, I’m [your name]. I’m not here to pressure you into a redesign. " + (
            f"I noticed {owner_observation}; I can explain why it may matter, then you can tell me whether it is relevant."
            if owner_observation
            else "I’d like to understand how the website is working for the business before suggesting anything."
        )
        in_person_full = "Hi, I’m [your name]. I work on focused public-facing website improvements. " + (
            f"I noticed {owner_observation}. I can explain that one observation, and you can decide whether it is worth discussing."
            if owner_observation
            else "I’m here to learn whether the website has a practical job it is not doing well enough; if not, I’ll leave it there."
        )
        other_opening_15 = "Hi, I’m [your name]. I have one brief question about the website. " + (
            f"I noticed {owner_observation}. Is now an okay time for the short version?"
            if owner_observation
            else "Is now an okay time for one brief question?"
        )
        other_opening_30 = "Hi, I’m [your name]. I’m reaching out about one public-facing website point. " + (
            f"I noticed {owner_observation}. I can explain why it may matter, then you can tell me whether it is relevant."
            if owner_observation
            else "I’d like to understand whether the current website is doing the job you want before suggesting anything."
        )
        other_full = "Hi, I’m [your name]. I’m reaching out about focused public-facing website improvements. " + (
            f"I noticed {owner_observation}. I can explain that one bounded observation, and you can decide whether it is worth discussing."
            if owner_observation
            else "I’d like to understand whether there is a practical website problem before suggesting any change."
        )
        if conversation.business_goal:
            opening_30 += f" You described your goal as {conversation.business_goal.lower()}; I still need to confirm this specific scope fits."
        if sales_evidence.selected_evidence:
            opening_30 += f" {sales_evidence.owner_question} {sales_evidence.next_step}"

        why_picked = self._why_picked(lead, owner_observation, competitors, competitors_verified)
        # Keep operator routing separate from anything the owner can hear or
        # copy.  The existing permission-aware attachment selector remains the
        # authority for internal guidance.
        attachment_text = self._proof_spoken_response(credibility)
        attachment_guidance = self._attachment_guidance(credibility)
        ai_followups = self._ai_followups(credibility.ai_response)

        branches: tuple[CallBranch, ...] = (
            CallBranch(
                "who_are_you",
                "Who are you?",
                credibility.identity_response,
                "Answer identity first, then ask permission to explain why this business was selected.",
                (
                    CallFollowUp(
                        "What company are you with?",
                        credibility.company_response,
                        "Use only the configured Seller Profile identity.",
                    ),
                    CallFollowUp("What exactly do you do?", credibility.identity_response, "Keep it concrete and brief."),
                    CallFollowUp(
                        "Are you local?",
                        credibility.location_response,
                        "Never imply a local office that is not configured.",
                        state_updates={"local_presence_question": True},
                    ),
                    CallFollowUp("How did you find us?", self._how_found(lead), "Return to public sources and the specific evidence."),
                    CallFollowUp("Why did you pick us?", why_picked, "Use only prospect-specific observed evidence."),
                    CallFollowUp(
                        "Is this a sales call?",
                        "Yes. I’m calling about possible paid improvement work, but I want to show the evidence before asking you to consider it.",
                        "Be direct.",
                    ),
                    CallFollowUp(
                        "Is this AI?",
                        credibility.ai_response,
                        "Explain the system and human review, not AI hype.",
                    ),
                    CallFollowUp("Who gave you my number?", self._number_source(), "Suppress immediately if they ask not to be contacted."),
                ),
            ),
            CallBranch(
                "what_about",
                "What is this about?",
                (
                    f"I noticed {owner_observation}. I wanted to ask whether that is relevant before suggesting anything."
                    if owner_observation
                    else "I’m calling about whether the website is doing the job you want; I do not want to assume there is a problem."
                ),
                "Ask permission to clarify the one bounded observation, if verified.",
            ),
            CallBranch(
                "how_found",
                "How did you find us?",
                self._how_found(lead),
                "Explain the public research source without implying hidden enrichment.",
            ),
            CallBranch(
                "experience",
                "Have you actually done this before?",
                credibility.experience_normal,
                "Use the proof-ledger state; do not turn prototypes into completions.",
                (
                    CallFollowUp("Who have you done this for?", credibility.experience_detailed, "Use only recorded client-work proof."),
                    CallFollowUp(
                        "Can I see examples?",
                        attachment_text,
                        "Send only the recommended verified/relevant artifacts.",
                        state_updates={"wants_examples": True, "wants_proof": True, "credibility_concern": True, "next_action": "Send proof"},
                    ),
                    CallFollowUp(
                        "Do you have references?",
                        self._references_response(credibility),
                        "A testimonial is not a reference unless the record supports contact permission.",
                        state_updates={"wants_references": True, "credibility_concern": True},
                    ),
                    CallFollowUp("What qualifies you?", credibility.experience_detailed, "Let evidence and process carry the answer."),
                ),
                state_updates={"seller_experience_question": True},
            ),
            CallBranch(
                "wrong_person",
                "I'm not the person who handles that",
                "No problem — who usually handles the website, marketing, or decisions about changes like this?",
                "Find the right person without forcing the pitch through a gatekeeper.",
                (
                    CallFollowUp(
                        "The owner handles it",
                        "Thanks. Is the owner available now, or is there a better time or email for a brief explanation?",
                        "Capture the owner name and best route.",
                        state_updates={"decision_maker_status": "Owner identified", "next_action": "Reach owner"},
                    ),
                    CallFollowUp(
                        "A manager handles it",
                        "Got it. Does that manager make website decisions, or do they usually take recommendations to the owner?",
                        "Identify authority before pitching.",
                        state_updates={"decision_maker_status": "Manager identified"},
                    ),
                    CallFollowUp(
                        "Outside agency / web person",
                        "Understood. I can send a short written summary of what I can verify so it can be passed "
                        "directly to them. Who is the best contact for that?",
                        "Do not attack the existing provider.",
                        state_updates={"decision_maker_status": "Outside provider", "next_action": "Discuss source details with provider/owner"},
                    ),
                    CallFollowUp(
                        "Corporate controls the site",
                        "That helps. If the local business cannot change the website, I don’t want to waste your time. I’ll mark that for review.",
                        "Likely qualify out unless another local-presence scope exists.",
                        state_updates={"decision_maker_status": "Corporate control", "next_action": "Research before outreach"},
                    ),
                ),
                state_updates={"decision_maker_status": "Not decision maker"},
            ),
            CallBranch(
                "gatekeeper_what_regarding",
                "What is this regarding?",
                (
                    f"I noticed one bounded public website point: {owner_observation}. "
                    "I’m trying to reach whoever handles the website — not sell a generic package to the front desk."
                    if owner_observation
                    else "I have one brief question about the public website. I’m trying to reach whoever handles it — "
                    "not sell a generic package to the front desk."
                ),
                "Ask for the correct person or best email.",
            ),
            CallBranch(
                "interested",
                "Sure / what did you find?",
                (
                    f"The public point I can discuss is: {owner_observation}. Does that match what you see?"
                    if owner_observation
                    else "Before I suggest a change, what job do you need the website to do better?"
                ),
                "Use only a verified bounded finding; otherwise ask a discovery question.",
                state_updates={"commitments": ["Interested in evidence"], "next_action": "Show evidence"},
            ),
            CallBranch(
                "happy",
                "We're happy with our website",
                (
                    "That makes sense. I’m not suggesting the whole site needs to be thrown out. "
                    f"The bounded public point I can verify is: {owner_observation}. You can decide whether that one point is worth discussing."
                    if owner_observation
                    else "That makes sense. I’m not assuming the site needs a rebuild. If you are open to it, I can ask one question "
                    "about what job you need the site to do and leave it there if there is no practical gap."
                ),
                "Diagnose whether they mean no need, recent redesign, or satisfaction with a provider.",
                (
                    CallFollowUp(
                        "We just redid it",
                        (
                            f"Then I would not push a rebuild. I’d only discuss this verified public point: {owner_observation}. "
                            "You can decide whether it is a small repair or nothing at all."
                            if owner_observation
                            else "Then I would not push a rebuild. I’d first ask what, if anything, is not working the way you want."
                        ),
                        "Do not pitch a full rebuild.",
                    ),
                    CallFollowUp(
                        "It works fine for us",
                        "That may be true. Does the site currently do the job you need — validation, intake, better-fit work, or lead generation?",
                        "Learn the real business goal before offering anything.",
                    ),
                ),
            ),
            CallBranch(
                "provider",
                "We already have someone",
                "That’s fine — I’m not trying to interfere with an existing relationship. "
                "The useful question is whether there is anything they believe is worth acting on.",
                "Find out what the existing provider actually covers.",
                (
                    CallFollowUp(
                        "They handle everything",
                        "Great. Are you happy with the results and responsiveness, or is there any part of the website/local presence "
                        "you still wish worked better?",
                        "If genuinely satisfied, offer a verified bounded observation only if one exists; otherwise exit cleanly.",
                    ),
                    CallFollowUp(
                        "Friend / family member",
                        "Understood. I can keep this provider-neutral and explain the question so you can pass it along without being put in the middle.",
                        "Do not criticize the relationship.",
                    ),
                    CallFollowUp(
                        "We use an agency",
                        "That may already cover it. Do they handle conversion work and local SEO, or mostly maintenance/ads? "
                        "I can keep the discussion limited to whatever falls outside their scope.",
                        "Do not claim the agency is failing without evidence.",
                    ),
                    CallFollowUp(
                        "Corporate handles it",
                        "Then the local office may not have a real website decision to make. I’ll mark that instead of forcing a pitch.",
                        "Research before further outreach.",
                        state_updates={"decision_maker_status": "Corporate control", "next_action": "Research before outreach"},
                    ),
                ),
                state_updates={"objections": ["Already has provider"]},
            ),
            CallBranch(
                "credibility",
                "Who are you / why should I trust you?",
                credibility.trust_response,
                "Diagnose whether they need proof, examples, legitimacy reassurance, access boundaries, or payment-process clarity.",
                (
                    CallFollowUp(
                        "I want proof",
                        attachment_text,
                        "Choose the strongest relevant artifact, not the whole biography.",
                        state_updates={"wants_proof": True, "credibility_concern": True, "next_action": "Send proof"},
                    ),
                    CallFollowUp(
                        "I want references",
                        self._references_response(credibility),
                        "Do not offer private client details or unapproved references.",
                        state_updates={"wants_references": True, "credibility_concern": True},
                    ),
                    CallFollowUp(
                        "Show me examples",
                        attachment_text,
                        "Use verified Seller Proof only.",
                        state_updates={"wants_examples": True, "wants_proof": True, "credibility_concern": True},
                    ),
                    CallFollowUp(
                        "You do not have enough experience",
                        credibility.experience_normal,
                        "Acknowledge the concern; do not inflate experience.",
                        state_updates={"seller_experience_question": True, "credibility_concern": True},
                    ),
                    CallFollowUp(
                        "Is this legitimate or a scam?",
                        "You do not need to pay or share access based on this call. I can first send a written summary of what I can verify, "
                        "identity details, and a clear review step.",
                        "Offer a verifiable, low-risk next step before payment or access.",
                        state_updates={"legitimacy_concern": True, "credibility_concern": True},
                    ),
                    CallFollowUp(
                        "Will you need website access?",
                        "Not to review public evidence. Any later access would be requested only for an agreed scope, "
                        "through the least-privileged account the platform supports.",
                        "Never ask for credentials during cold outreach.",
                    ),
                    CallFollowUp(
                        "What happens before payment?",
                        "First we verify the evidence and goal, then review a customer-specific delivery checklist covering the exact scope, "
                        "actual price/payment arrangement, owner account control, platform/email, minimal access, backup/staging, tests, "
                        "owner approval, live-change limits, recovery, measurement and handoff. " + delivery_packet["warning"],
                        "Move to a written, reviewable next step.",
                    ),
                ),
                state_updates={"credibility_concern": True, "wants_proof": True, "decision_maker_skeptical": True},
            ),
            CallBranch(
                "ai_skepticism",
                "Are you just using AI?",
                credibility.ai_response,
                "Choose the specific AI concern; do not claim AI guarantees quality, safety, or rankings.",
                ai_followups,
                state_updates={"concerned_about_ai": True, "credibility_concern": True, "decision_maker_skeptical": True},
            ),
            CallBranch(
                "why_you",
                "What makes you different?",
                self._differentiator_response(lead, competitors_verified),
                "Use only the strongest one to three truthful workflow differences.",
                (
                    CallFollowUp("What have you built?", credibility.experience_detailed, "Use the proof ledger."),
                    CallFollowUp("Send the strongest example", attachment_text, "Confirm the best public artifact and email."),
                ),
                state_updates={"credibility_concern": True},
            ),
            CallBranch(
                "price",
                "How much?",
                pricing.price_answer,
                "Give the evidence-backed range, then ask which scope they want to understand.",
                (
                    CallFollowUp(
                        "Show me the smaller first phase",
                        f"The lower planning ask is {pricing.easy_close_text}. The recorded deliverables begin with "
                        f"{first_scope}; a genuinely smaller phase needs its own written scope before pricing.",
                        "Confirm the first-phase outcome and exclusions.",
                    ),
                    CallFollowUp(
                        "What does the recommended price include?",
                        f"The recommended ask is {pricing.recommended_text}. It is tied to: " + "; ".join(plan.smart_offer.scope[:3]) + ".",
                        "Ask which scope item matters most.",
                    ),
                    CallFollowUp(
                        "Can you give me an exact quote?",
                        "Yes, after I confirm the actual goal, existing tools, content, and approval process. "
                        "I don’t want to turn a planning range into a fake exact quote.",
                        "Schedule a short scope review.",
                    ),
                ),
            ),
            CallBranch(
                "too_expensive",
                "That's too expensive",
                "That’s fair. Is the issue mainly that the total is outside what you want to spend right now, "
                "or that you’re not yet convinced the changes are worth that amount?",
                "Diagnose budget vs value vs competing quote.",
                (
                    CallFollowUp(
                        "Mostly the budget",
                        f"The lower planning ask is {pricing.easy_close_text} for the currently recorded deliverables. "
                        "If you want less work, we must separately define what is removed and recheck that the remaining scope is useful.",
                        "Ask whether a smaller phase would help.",
                        (
                            CallFollowUp(
                                "A smaller phase could work",
                                "Let's define the exact reduced deliverables and acceptance first; the current amount does not establish a smaller scope.",
                                "Confirm scope in writing.",
                            ),
                            CallFollowUp(
                                "There is no budget right now",
                                "Understood. Would you prefer I close this out or follow up in a specific month?",
                                "Do not keep following up without permission.",
                            ),
                        ),
                    ),
                    CallFollowUp(
                        "Not sure it's worth it",
                        "That’s fair. I wouldn’t want you paying for changes just because I prefer a different design. "
                        "Let me show you the one or two public differences that matter most, then you can decide whether the value is there.",
                        "Return to evidence, not pressure.",
                        (
                            CallFollowUp(
                                "Show me the evidence",
                                (
                                    f"The bounded public observation is: {owner_observation}. Does that match what you see?"
                                    if owner_observation
                                    else "I should not assume a public observation is correct. What would make a change worthwhile to you?"
                                ),
                                "Ask whether the issue matters to them.",
                            ),
                            CallFollowUp(
                                "Can you guarantee results?",
                                "No. I can deliver the agreed change, but I cannot guarantee rankings, leads, calls, or revenue.",
                                "Continue only if the scoped improvement has value without a guarantee.",
                            ),
                        ),
                    ),
                    CallFollowUp(
                        "Someone else is cheaper",
                        f"They may be a good option. My current recommendation is around {pricing.recommended_text} for the documented scope. "
                        "The useful question is what each quote actually includes.",
                        "Compare scope before price.",
                        (
                            CallFollowUp(
                                "Their scope is the same",
                                "That may be the better fit. Compare deliverables, ownership, revisions, support, and evidence before deciding.",
                                "Do not race to the bottom.",
                            ),
                            CallFollowUp(
                                "Their scope is smaller",
                                f"Then we need to compare their deliverables with the currently recorded scope at {pricing.easy_close_text}, "
                                f"not the full {pricing.recommended_text} recommendation.",
                                "Compare equal scope.",
                            ),
                        ),
                    ),
                ),
                state_updates={"objections": ["Too expensive"]},
                quick_response="I understand. Before we talk price, is the concern the budget, the scope, or whether the change would matter?",
            ),
            CallBranch(
                "think",
                "I need to think about it",
                "Absolutely. Is the uncertainty mostly the price, whether the changes would matter, the timing, or another person’s approval?",
                "Choose the real blocker.",
                (
                    CallFollowUp(
                        "Mostly the price",
                        "I can prepare the current scope in writing. A smaller option would need separately defined deliverables before you compare prices.",
                        "Ask which written option they want.",
                    ),
                    CallFollowUp(
                        "Mostly timing",
                        "When would this realistically be worth revisiting? I’d rather follow up at a useful time than keep checking randomly.",
                        "Record a specific date/month.",
                    ),
                    CallFollowUp(
                        "I’m not sure it would matter",
                        "That is fair. I should not assume it would. What would need to be different for the website work to be worth considering?",
                        "Clarify value uncertainty without promising a result.",
                        state_updates={"objections": ["Value uncertainty"]},
                        quick_response="That is fair. What would need to be different for this to be worth considering?",
                    ),
                    CallFollowUp(
                        "Need another person's approval",
                        "I can send a short version with the problem, evidence, scope, and price so you don’t have to relay the whole call from memory.",
                        "Ask who should receive it.",
                        state_updates={"next_action": "Send decision summary"},
                    ),
                ),
            ),
            CallBranch(
                "send_info",
                "Send me information",
                "Absolutely. What would be most useful — a brief explanation, examples of what I’d change, or pricing?",
                "Diagnose what 'send info' actually means.",
                (
                    CallFollowUp(
                        "Send source details",
                        "I can send a brief explanation with only material that is verified and permitted.",
                        "Confirm the best email and one follow-up date.",
                        state_updates={"commitments": ["Send source details"], "next_action": "Send source details"},
                    ),
                    CallFollowUp(
                        "Send examples / concept",
                        "I’ll send a focused example tied to the specific gap, not a generic mockup.",
                        "Confirm what they want to see.",
                        state_updates={"commitments": ["Send concept"], "next_action": "Send concept"},
                    ),
                    CallFollowUp(
                        "Send pricing",
                        f"I can prepare the currently recorded scope and its {pricing.easy_close_text} to {pricing.recommended_text} planning asks "
                        "with the differences clearly listed.",
                        "Do not add unrequested work.",
                        state_updates={"commitments": ["Send pricing"], "next_action": "Send pricing"},
                    ),
                    CallFollowUp(
                        "I need to show someone else",
                        "I’ll make it easy to forward: problem, evidence, proposed scope, and price on one page.",
                        "Ask who else is involved.",
                        state_updates={"next_action": "Send decision summary"},
                    ),
                ),
            ),
            CallBranch(
                "busy",
                "I'm busy / bad time",
                "No problem. Is this just a bad minute, a bad season, or are you saying the project itself isn’t a priority?",
                "Separate timing from no need.",
                (
                    CallFollowUp("Bad minute", "I can send a brief explanation and call at a specific better time.", "Get permission and a time."),
                    CallFollowUp("Busy season", "Which month would actually be useful for one follow-up?", "Record the month and stop until then."),
                    CallFollowUp("Not a priority", "Understood. I’ll close it unless you want a brief explanation for later.", "Do not manufacture urgency."),
                ),
            ),
            CallBranch(
                "no_need",
                "We don't need a new website",
                "Understood. I’m not assuming you need a rebuild. Is the issue that the current site already does its job, "
                "or that you’d only consider fixing specific pieces?",
                "Offer repair/reuse when appropriate.",
                (
                    CallFollowUp(
                        "Current site does its job",
                        "Then I’d only show the evidence and let you decide whether the specific gap matters. If not, there’s no project to force.",
                        "Exit if no real need.",
                    ),
                    CallFollowUp(
                        "We would fix specific pieces",
                        f"That fits a focused repair better than a rebuild. I’d start with {first_scope} and keep the rest optional.",
                        "Shift the Smart Offer to repair scope.",
                        state_updates={"business_goal": "Fix specific website pieces", "next_action": "Prepare focused repair scope"},
                    ),
                ),
            ),
            CallBranch(
                "buyer_questions",
                "Website / ownership / hosting questions",
                "Those are good buying questions. I’ll separate what is already decided from what needs to be confirmed "
                "so I don’t promise a platform or fee structure that isn’t actually in the scope.",
                "Choose the exact question they asked.",
                (
                    CallFollowUp(
                        "Can you fix the existing site?",
                        "Possibly. I’d inspect the current platform first. If the specific problems can be repaired cleanly, I won’t force a rebuild.",
                        "Inspect platform before promising.",
                        state_updates={"buyer_questions": ["Existing-site repair"]},
                    ),
                    CallFollowUp(
                        "Do I keep my domain?",
                        "Yes, the goal should be for you to keep control of your domain. I’ll verify the registrar/account access before any migration work.",
                        "Confirm ownership/access.",
                        state_updates={"buyer_questions": ["Domain ownership"]},
                    ),
                    CallFollowUp(
                        "Who owns the website?",
                        "The proposal should state ownership clearly. I won’t imply ownership terms until the platform, hosting, "
                        "and assets are defined in writing.",
                        "Put ownership in the written scope.",
                        state_updates={"buyer_questions": ["Website ownership"]},
                    ),
                    CallFollowUp(
                        "Is there a monthly fee / hosting?",
                        "That depends on the chosen platform and hosting. I’ll separate one-time build work from any recurring "
                        "platform/hosting cost before you approve anything.",
                        "Confirm recurring costs in writing.",
                        state_updates={"buyer_questions": ["Hosting and recurring fees"]},
                    ),
                    CallFollowUp(
                        "Do you do SEO?",
                        "I can scope on-site/local-presence improvements separately from ongoing SEO. I won’t promise rankings, "
                        "and I’ll make clear what is included versus ongoing work.",
                        "Separate build SEO from ongoing SEO.",
                        state_updates={"buyer_questions": ["SEO scope"]},
                    ),
                    CallFollowUp(
                        "Will changing it hurt rankings?",
                        "Any migration should preserve URLs, redirects, metadata, and indexable content where appropriate. "
                        "I can reduce migration risk, but I can’t guarantee rankings won’t move.",
                        "Audit before migration.",
                        state_updates={"buyer_questions": ["Migration/SEO risk"]},
                    ),
                    CallFollowUp(
                        "Can I edit it myself?",
                        "That should be decided by the platform and handoff plan. If self-editing matters, "
                        "I’ll treat that as a requirement before choosing the build approach.",
                        "Record editability as a requirement.",
                        state_updates={"buyer_questions": ["Self-editing"]},
                    ),
                    CallFollowUp(
                        "How long will it take?",
                        "I’ll give a timeline only after scope, content, access, and approvals are clear. I don’t want to invent a delivery date on the call.",
                        "Estimate after scope review.",
                        state_updates={"buyer_questions": ["Timeline"]},
                    ),
                    CallFollowUp(
                        "Do you use AI?",
                        "Yes, where useful for research/build speed, but not to invent business facts. "
                        "Claims, scope, content, and final approval stay human-reviewed.",
                        "Return to evidence and review process.",
                        state_updates={"buyer_questions": ["AI use"]},
                    ),
                ),
            ),
            CallBranch(
                "busy_enough",
                "We're already busy enough",
                "That’s a good problem to have. I wouldn’t push a rebuild just to chase more leads. "
                "Is the issue that you’re booked out, the website is not important, or you simply do not want changes?",
                "Do not assume more leads are desirable.",
                (
                    CallFollowUp(
                        "We're booked out",
                        "Understood. Is the useful goal better-fit work, easier intake, stronger trust, hiring support, or no change at all?",
                        "Choose their real goal instead of selling more volume.",
                        (
                            CallFollowUp(
                                "We want better-fit jobs",
                                "Then I would focus the site on clearer service fit and expectations so the wrong inquiries can self-select out.",
                                "Ask which jobs are the best fit.",
                                state_updates={
                                    "business_goal": "Better-fit jobs",
                                    "capacity_status": "Booked/busy",
                                    "next_action": "Prepare lead-quality scope",
                                },
                            ),
                            CallFollowUp(
                                "We need easier intake",
                                "Then the useful scope is the contact and estimate flow, not a cosmetic redesign.",
                                "Confirm the intake bottleneck.",
                                state_updates={"business_goal": "Easier intake", "capacity_status": "Booked/busy", "next_action": "Prepare intake scope"},
                            ),
                            CallFollowUp(
                                "We do not want changes",
                                "That is clear. I’ll close this out and won’t keep pushing.",
                                "Do not schedule follow-up without permission.",
                                state_updates={"next_action": "Close opportunity"},
                            ),
                        ),
                        state_updates={"capacity_status": "Booked/busy"},
                    ),
                    CallFollowUp(
                        "Most work is referrals",
                        "Then the site’s job may be validation, not lead generation. "
                        "I’d focus only on accurate services, proof, and easy contact for referred customers.",
                        "Validate the referral use case.",
                        state_updates={"business_goal": "Referral validation"},
                    ),
                    CallFollowUp(
                        "We do not want changes",
                        "That is clear. I’ll close this out and won’t keep pushing.",
                        "Do not schedule follow-up without permission.",
                        state_updates={"next_action": "Close opportunity"},
                    ),
                ),
            ),
            CallBranch(
                "how_number",
                "How did you get this number?",
                "I used the public business contact information listed online. I’m calling about the business, "
                "not a private number I obtained elsewhere. If you’d rather not receive outreach, I’ll mark that and stop.",
                "If they ask not to be contacted again, suppress immediately.",
            ),
            CallBranch(
                "what_selling",
                "What are you selling?",
                "Website and local-presence improvement work, but not a generic package. I would first confirm what you want "
                "the website to do before proposing a focused scope.",
                "Ask whether there is a practical website job they want to improve.",
            ),
            CallBranch(
                "not_interested",
                "Not interested",
                "Understood. Is that no current need, bad timing, already handled, or a request not to contact you again?",
                "Classify the outcome without pushing.",
                (
                    CallFollowUp(
                        "No current need",
                        "Understood. I’ll close it out rather than keep following up.",
                        "Close respectfully.",
                        state_updates={"next_action": "Close opportunity"},
                    ),
                    CallFollowUp("Bad timing", "What month, if any, would be useful for one follow-up?", "Only schedule with permission."),
                    CallFollowUp("Already handled", "Makes sense. I’ll close it and leave the existing setup alone.", "Close respectfully."),
                    CallFollowUp(
                        "Do not contact me again",
                        "Understood. I’ll mark this do-not-contact now.",
                        "Suppress immediately.",
                        state_updates={"next_action": "Do Not Contact"},
                    ),
                ),
            ),
            CallBranch(
                "other",
                "Other / I don't know what they mean",
                "I want to make sure I answer the question you actually mean. Is the concern mainly who I am, "
                "why I called, my experience, AI, proof, or the proposed work?",
                "Clarify before choosing a branch.",
            ),
            CallBranch(
                "prior_vendor_injury",
                "We were burned by a prior vendor",
                "I’m sorry that happened. You should not have to rely on promises; any next step should make scope, access, "
                "ownership, and checkpoints clear before a commitment.",
                "Acknowledge the experience without diagnosing or blaming the prior vendor.",
                quick_response="I’m sorry that happened. Any next step should be clear and reviewable before a commitment.",
            ),
            CallBranch(
                "overwhelmed",
                "I don’t understand / this is too much",
                "That is on me. The simple version is: I am asking whether the website has one practical job you want to improve. "
                "If not, we can leave it there.",
                "Use plain language; do not restate unsupported findings.",
                quick_response="That is on me. Is there one practical job you want the website to do better?",
            ),
            CallBranch(
                "evidence_dispute",
                "That observation is wrong",
                "I may have it wrong. I will not treat it as fact; which part does not match your experience?",
                "Record the correction as an observation or UNKNOWN; do not defend the finding.",
                quick_response="I may have it wrong. Which part does not match your experience?",
            ),
            CallBranch(
                "stop_disengage",
                "Please stop / not a fit",
                "Understood. I will end the conversation here. If you want no further contact, I can record that now.",
                "Confirm the actual request in the outcome dialog; only an explicit confirmed DNC triggers suppression.",
                state_updates={"next_action": "End conversation"},
                quick_response="Understood. I will end the conversation here.",
            ),
        )
        branches = _identify_call_tree(branches)
        if not context.price_available:
            neutral = (
                "I do not see a meaningful paid change to recommend now. There is no project to force."
                if context.intervention_assessment.get("state") == "no_sale" else
                "I need to verify the actual need and your goal before recommending a paid scope or price."
            )

            def noncommercial(item: CallFollowUp) -> CallFollowUp:
                return replace(item, response=neutral, quick_response=neutral,
                               next_prompt="Confirm the need without proposing paid work.",
                               followups=tuple(noncommercial(child) for child in item.followups))

            branches = tuple(replace(branch, response=neutral, quick_response=neutral,
                                     next_prompt="Confirm the need without proposing paid work.",
                                     followups=tuple(noncommercial(child) for child in branch.followups))
                             if branch.key in {"price", "too_expensive", "think", "send_info", "no_need"}
                             else branch for branch in branches)
        strategy = f"{plan.primary_theme} · {plan.message_strategy}"
        do_not_claim = tuple(dict.fromkeys((*plan.do_not_claim, *credibility.do_not_claim)))
        research_only = plan.segment in {"Hold", "Reject"} or not context.price_available
        call_phase = "LEGITIMACY" if conversation.credibility_concern else "IDENTITY"
        initial_branch_keys = (
            "who_are_you",
            "what_about",
            "provider",
            "too_expensive",
            "think",
            "overwhelmed",
            "evidence_dispute",
            "stop_disengage",
        )
        # Guided Call consumes more than the generic pricing snapshot: Seller
        # Profile identity, credibility wording, proof availability, competitor
        # verification, and rendered branch text all matter at Live/copy/outcome
        # boundaries. Fingerprint the exact rendered guide plus the commercial
        # plan dependency so any material guide change requires refresh.
        guide_fingerprint = fingerprint(
            {
                "tree_id": CALL_TREE_ID,
                "tree_version": CALL_TREE_VERSION,
                "commercial_plan_dependency": commercial_snapshot.dependency_fingerprint,
                "business_name": lead.name,
                "opening_15s": opening_15,
                "opening_30s": opening_30,
                "full_opening": full,
                "lead_with": lead_with,
                "price_answer": pricing.price_answer,
                "branches": [_branch_snapshot(branch) for branch in branches],
                "intelligence_level": plan.intelligence_level,
                "strategy": strategy,
                "recommended_ask": pricing.recommended,
                "do_not_claim": list(do_not_claim),
                "research_only": research_only,
                "why_you": list(credibility.why_you),
                "proof_attachments": attachment_guidance,
                "initial_branch_keys": list(initial_branch_keys),
                "call_phase": call_phase,
                "sales_evidence": list(sales_evidence.identity()),
                "delivery_packet": delivery_packet,
                "in_person_opening_15s": in_person_opening_15,
                "in_person_opening_30s": in_person_opening_30,
                "in_person_full_opening": in_person_full,
                "other_opening_15s": other_opening_15,
                "other_opening_30s": other_opening_30,
                "other_full_opening": other_full,
                "evidence_claims": list(evidence_claims),
                "owner_spoken_claims": list(owner_spoken_claims),
                "owner_copied_claims": list(owner_copied_claims),
            }
        )
        return CallGuide(
            lead.name,
            opening_15,
            opening_30,
            full,
            lead_with,
            pricing.price_answer,
            branches,
            intelligence_level=plan.intelligence_level,
            strategy=strategy,
            recommended_ask=pricing.recommended,
            do_not_claim=do_not_claim,
            research_only=research_only,
            why_you=credibility.why_you,
            proof_attachments=attachment_guidance,
            initial_branch_keys=initial_branch_keys,
            call_phase=call_phase,
            commercial_dependency_fingerprint=guide_fingerprint,
            in_person_opening_15s=in_person_opening_15,
            in_person_opening_30s=in_person_opening_30,
            in_person_full_opening=in_person_full,
            other_opening_15s=other_opening_15,
            other_opening_30s=other_opening_30,
            other_full_opening=other_full,
            evidence_claims=evidence_claims,
            owner_spoken_claims=owner_spoken_claims,
            owner_copied_claims=owner_copied_claims,
            tree_id=CALL_TREE_ID,
            tree_version=CALL_TREE_VERSION,
            selected_evidence=sales_evidence.selected_evidence,
            evidence_review_state=sales_evidence.review_state,
            owner_validation_question=sales_evidence.owner_question,
            next_step=sales_evidence.next_step,
            delivery_packet=delivery_packet,
        )

    @staticmethod
    def _how_found(lead: Lead) -> str:
        source = "public business listings and public website information"
        if lead.google_maps_url or lead.place_id:
            source = "the public Google business listing and public website information"
        return f"I found {lead.name} through {source} while researching businesses in this category. I did not use private account data."

    @staticmethod
    def _number_source() -> str:
        return (
            "I used the public business contact information listed online. I did not obtain a private number or hidden email. "
            "If you would rather not receive outreach, I will mark that and stop."
        )

    @staticmethod
    def _why_picked(lead: Lead, owner_observation: str, competitors: list[CompetitorRecord], competitors_verified: bool) -> str:
        """Owner copy may state only a finding whose own contract permits it."""
        if owner_observation:
            return f"The bounded public observation I can discuss is: {owner_observation}. I wanted to ask whether it is relevant to you."
        return "I am not assuming there is a problem. I wanted to ask whether the website is doing the job you need before suggesting anything."

    @staticmethod
    def _references_response(credibility) -> str:
        if credibility.reference_options:
            return f"I have {credibility.reference_options[0]} recorded with explicit permission to offer it. I would confirm the introduction manually."
        return "I do not have an approved reference recorded, so I won't invent one. I can send the actual analysis and any verified public examples instead."

    @staticmethod
    def _proof_spoken_response(credibility) -> str:
        if credibility.attachments.send:
            return "I can share a relevant example or proof item that is approved for this use. I will confirm the most relevant one before sending anything."
        return (
            "I do not have an approved public example to offer right now. "
            "I can explain the process, and only follow up with material that is verified and permitted."
        )

    @staticmethod
    def _attachment_guidance(credibility) -> str:
        lines = ["Safest proof package:"]
        if credibility.attachments.send:
            lines.extend(f"SEND: {item}" for item in credibility.attachments.send)
        else:
            lines.append("SEND: the prospect-specific audit/comparison after manual verification; no public proof artifact is currently approved")
        lines.extend(f"OPTIONAL: {item}" for item in credibility.attachments.optional)
        lines.extend(f"DO NOT SEND: {item}" for item in credibility.attachments.do_not_send[:3])
        return "\n".join(lines)

    @staticmethod
    def _differentiator_response(lead: Lead, competitors_verified: bool) -> str:
        points = [
            "I start with evidence and a targeted scope instead of assuming you need a full redesign",
            "every recommendation can be traced to a public observation and human review",
        ]
        if competitors_verified:
            points.insert(1, "the comparison set was manually reviewed before I used competitor language")
        return f"For {lead.name}, the main differences are: " + "; ".join(points[:3]) + "."

    @staticmethod
    def _ai_followups(ai_response: str) -> tuple[CallFollowUp, ...]:
        return (
            CallFollowUp("Is the website AI-generated?", ai_response, "Explain what is automated and what is reviewed."),
            CallFollowUp(
                "Why would I pay if AI can make a website?",
                "You may not need to pay someone if you can define the right scope, verify the business facts, select the platform, "
                "review the output, and implement it safely yourself. The paid value is the evidence, judgment, implementation, "
                "and accountability around the tool.",
                "Do not argue against DIY; clarify the work around generation.",
                (
                    CallFollowUp(
                        "I can do it myself",
                        "That may be the right choice. I can still send a short written summary of what I can verify "
                        "so you can decide what, if anything, to fix first.",
                        "Offer the analysis and exit cleanly.",
                    ),
                    CallFollowUp(
                        "I don't have time to do it",
                        "Then the value is taking the verified scope through implementation and review, not charging for a button press.",
                        "Return to the focused scope.",
                    ),
                ),
            ),
            CallFollowUp(
                "Can't I use ChatGPT, Lovable, or Canva myself?",
                "Yes. Those can be useful tools. The difference is choosing what evidence belongs in the site, preventing invented claims, "
                "integrating the real contact flow, and reviewing the result against the business goal.",
                "Acknowledge the tools; explain the workflow around them.",
            ),
            CallFollowUp(
                "Is this an automated sales pitch?",
                "No message or call is sent automatically by this app. The research and scripts are decision support; "
                "I review the evidence and make the call myself.",
                "Be explicit about the human-led outreach boundary.",
            ),
            CallFollowUp("How much did AI do?", ai_response, "Describe actual tooling without assigning fake percentages."),
            CallFollowUp(
                "Will AI make things up?",
                "It can, which is why unsupported business facts are blocked, public evidence is stored with provenance, "
                "and final claims require human review. I still won't promise the process is error-free.",
                "Offer the exact evidence for review.",
            ),
            CallFollowUp(
                "Is AI safe for my business?",
                "Safety depends on the data, provider, access, and review process. I would define what data is allowed, "
                "avoid unnecessary private data, and document any AI-enabled feature before it is used.",
                "Do not claim universal safety.",
            ),
            CallFollowUp(
                "Does AI hurt SEO?",
                "AI use by itself does not let me promise or predict rankings. The content still needs to be accurate, useful, "
                "technically sound, and reviewed; I do not mass-publish unverified pages.",
                "Do not guarantee rankings.",
            ),
            CallFollowUp(
                "Is this all templates?",
                "Templates may provide structure, but the evidence, selected scope, business facts, contact path, "
                "and final implementation still need to fit this business.",
                "Return to the prospect-specific evidence.",
            ),
        )
