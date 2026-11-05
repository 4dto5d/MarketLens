from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_outreach_service import AdaptiveOutreachService, AdaptiveSalesPlan
from local_presence_miner.services.conversation_state_service import ConversationState, ConversationStateService
from local_presence_miner.services.credibility_service import CredibilityService
from local_presence_miner.services.offer_builder import StartingOfferInput, generate_starting_offer
from local_presence_miner.services.sales_evidence_service import USAGE_OWNER_COPIED, SalesEvidenceService
from local_presence_miner.services.seller_pricing_service import SellerPricingRecommendation


class OutreachService:
    def __init__(self, sender: SenderInfo) -> None:
        self.sender = sender

    def generate_all(
        self,
        lead: Lead,
        city: str = "",
        state_region: str = "",
        pricing: SellerPricingRecommendation | None = None,
        competitors: list[CompetitorRecord] | None = None,
        *,
        session: Session | None = None,
        adaptive_plan: AdaptiveSalesPlan | None = None,
    ) -> dict[OutreachKind, tuple[str, str]]:
        target_signals = loads(lead.target_signals_json, [])
        offer_input = StartingOfferInput(
            business_name=lead.name,
            niche=lead.category,
            city=city,
            state_region=state_region,
            target_zip_code=lead.target_zip_code,
            target_radius_miles=lead.target_radius_miles,
            phone=lead.phone,
            website=lead.website,
            google_maps_url=lead.google_maps_url,
            yelp_url=lead.yelp_url,
            current_rank_position=lead.search_position,
            review_count=lead.review_count,
            rating=lead.rating,
            target_signals=target_signals,
            recommended_offer=lead.recommended_offer or "",
            past_sales_notes=lead.past_sales_notes,
        )
        legacy_offer = generate_starting_offer(offer_input)
        conversation = ConversationStateService().build(session, lead) if session is not None else ConversationState(contact_name=(lead.owner or "").strip())
        credibility = CredibilityService().build(session, lead.category) if session is not None else None
        if adaptive_plan is None and session is not None:
            from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan

            adaptive_plan, pricing = build_adaptive_sales_plan(session, lead, competitors=competitors)
        adaptive = adaptive_plan or AdaptiveOutreachService().build(
            lead,
            competitors or [],
            pricing,
            legacy_offer,
            conversation=conversation,
        )
        smart_offer = adaptive.smart_offer
        greeting = conversation.contact_name or lead.owner or f"{lead.name} team"
        issue_line = "a possible customer-facing need that requires a recorded, reviewed observation"
        competitors = competitors or []
        competitor_line = (
            f"A comparison could inspect the {len(competitors)} recorded public business observations after review."
            if competitors
            else "I kept the note limited to what is visible in your own public-facing information."
        )
        contact = self.contact_block()
        opt_out = self.sender.opt_out_line
        assessment = smart_offer.intervention_assessment
        sales_evidence = SalesEvidenceService().build(session, lead, assessment=assessment,
                                                     offer_id=smart_offer.offer_id, scope=smart_offer.scope) if session is not None else None
        if assessment:
            permitted = sales_evidence.for_usage(USAGE_OWNER_COPIED) if sales_evidence else ()
            issue_line = (sales_evidence.plain_finding if sales_evidence and sales_evidence.selected_evidence else
                          permitted[0].claim if permitted else "a possible need that requires confirmation")
            competitor_line = "The observations are bounded checks, not proof of lost revenue or of a competitor winning customers."
        question = (sales_evidence.owner_question if sales_evidence else
                    "What customer-facing job would you like the website to do?")
        next_step = sales_evidence.next_step if sales_evidence else "Verify the observation and owner priority first."
        goal_line = ""
        if conversation.business_goal:
            goal_line = (
                f"\n\nYou described your goal as {conversation.business_goal.lower()}. "
                "We still need to confirm that the specific scope fits your desired work, timing and territory."
            )
        buyer_line = ""
        if conversation.buyer_questions:
            buyer_line = "\n\nI’ll also address the questions you raised about " + ", ".join(conversation.buyer_questions[:3]) + "."
        credibility_line = ""
        if credibility and any(
            (
                conversation.credibility_concern,
                conversation.wants_examples,
                conversation.wants_references,
                conversation.wants_proof,
                conversation.seller_experience_question,
                conversation.concerned_about_ai,
                conversation.legitimacy_concern,
            )
        ):
            credibility_contexts: list[str] = []
            if conversation.seller_experience_question or conversation.wants_examples or conversation.wants_references or conversation.wants_proof:
                credibility_contexts.append(credibility.email_context)
            if conversation.concerned_about_ai:
                credibility_contexts.append(
                    "You asked about AI. It supports research and build speed, while evidence selection, unsupported-claim prevention, "
                    "scope, and final review remain human-controlled."
                )
            if conversation.local_presence_question:
                credibility_contexts.append("You asked where I work from: " + credibility.location_response)
            if conversation.legitimacy_concern:
                credibility_contexts.append(
                    "You also raised a legitimacy concern, so the next step is limited to reviewable public evidence; "
                    "no payment or website access is needed to review it."
                )
            if not credibility_contexts:
                credibility_contexts.append("You raised a credibility question, so I am keeping this follow-up limited to verifiable evidence.")
            credibility_line = "\n\n" + " ".join(credibility_contexts)
            if credibility.attachments.send:
                credibility_line += " I can send the verified artifact the proof ledger ranked first."
            elif conversation.wants_examples or conversation.wants_proof:
                credibility_line += " No public proof artifact is currently approved, so I will rely on the verified analysis rather than imply otherwise."
        if assessment and not (pricing and pricing.price_available):
            # All channels are non-commercial, but recorded owner questions,
            # corrections and permitted credibility responses must survive.
            message = (
                "I do not see a meaningful paid change to recommend from the current evidence. There is no project to force."
                if assessment.get("state") == "no_sale" else
                "I need to verify the observation and understand your goal before recommending any paid work. "
                "The current evidence does not justify a price or a promised result."
            )
            drafts = {kind: (f"Evidence review — {lead.name}",
                             f"Hi {greeting},\n\n{message}{goal_line}{buyer_line}{credibility_line}\n\n{contact}\n\n{opt_out}")
                      for kind in OutreachKind}
            for kind in (OutreachKind.VOICEMAIL, OutreachKind.CALL_OPENING):
                drafts[kind] = ("", f"Hi, this is {self.sender.name or 'a website analyst'}. {message} "
                               f"You can reach me at {self.sender.phone or '[your phone]' }.")
            return drafts
        price_reply = (
            f"The current evidence-backed recommendation is {pricing.recommended_text}. "
            f"The planning asks are {pricing.easy_close_text} to {pricing.stretch_text}. "
            "These amounts do not establish different deliverables; any smaller or additional scope must be separately defined. "
            "A price is for discovery discussion until the customer delivery packet is reviewed."
            if pricing and pricing.price_available
            else "I need to confirm the scope and Seller Pricing Intelligence before giving you a responsible number."
        )
        research_only = adaptive.segment in {"Hold", "Reject"}
        first_scope = smart_offer.scope[0].lower() if smart_offer.scope else "validate the actual business need"
        initial_subject = f"RESEARCH REQUIRED — {lead.name}" if research_only else f"Quick {adaptive.primary_theme.lower()} idea for {lead.name}"
        initial_body = (
            "INTERNAL — DO NOT SEND YET\n\n"
            f"This lead is currently {adaptive.segment} with {lead.qualification_confidence or 'Low'} qualification confidence. "
            f"{adaptive.email_objective}\n\n"
            "Complete the Smart Offer human checks and recalculate qualification before drafting confident cold outreach."
            if research_only
            else (
                f"Hi {greeting},\n\n"
                f"I have one public-facing point to verify for {lead.name}: {issue_line}. "
                f"{competitor_line}\n\n"
                f"The first thing I would test is {first_scope}. {smart_offer.positioning}\n\n"
                f"{question} {next_step} I can prepare a short comparison after manual verification of the source facts and profile ownership. "
                "Would that be useful?"
                f"{goal_line}{buyer_line}{credibility_line}\n\n{contact}\n\n{opt_out}"
            )
        )

        report_scope = "; ".join(smart_offer.scope[:3])
        report_price = f"${smart_offer.recommended_ask:,}" if smart_offer.recommended_ask else "to be confirmed after scope review"
        return {
            OutreachKind.INITIAL_EMAIL: (initial_subject, initial_body),
            OutreachKind.SHORT_FOLLOW_UP: (
                f"Should I send the comparison for {lead.name}?",
                f"Hi {greeting},\n\nA current reviewed comparison may be useful. The bounded source observation to verify is {issue_line}."
                f"{goal_line}{credibility_line}\n\nIf useful, I can send the short evidence-based breakdown.\n\n{contact}\n\n{opt_out}",
            ),
            OutreachKind.FINAL_FOLLOW_UP: (
                f"Closing the loop — {lead.name}",
                f"Hi {greeting},\n\nI’ll close the loop after this. If this becomes useful later, I can prepare a current reviewed comparison. "
                f"If you want that review, reply.\n\n{contact}\n\n{opt_out}",
            ),
            OutreachKind.INTERESTED_REPLY: (
                f"The focused comparison for {lead.name}",
                f"Hi {greeting},\n\nThanks — the bounded observation to discuss is {issue_line}. {question}\n\n"
                f"The focused recommendation is {smart_offer.offer_name}, starting with {first_scope}. "
                f"The intended outcome is {smart_offer.primary_outcome}.{goal_line}{buyer_line}{credibility_line}\n\n"
                f"I can send the evidence first, then we can confirm that the scope matches what you actually want.\n\n{contact}\n\n{opt_out}",
            ),
            OutreachKind.PRICE_REPLY: (
                f"Scope and options for {lead.name}",
                f"Hi {greeting},\n\n{price_reply}\n\nThe recommended scope begins with {first_scope}."
                f"{goal_line}\n\nI’d confirm the actual goal and existing tools before turning that range into a written quote. "
                f"I do not guarantee rankings, leads, calls, or revenue.\n\n{contact}\n\n{opt_out}",
            ),
            OutreachKind.PROVIDER_REPLY: (
                f"Comparison notes for {lead.name}",
                f"Hi {greeting},\n\nThat makes sense. I’m not asking you to replace an existing provider. "
                f"The useful item to verify is {issue_line}. Once reviewed, you can discuss it with whoever handles the site."
                f"{goal_line}\n\n{contact}\n\n{opt_out}",
            ),
            OutreachKind.NOT_NOW_REPLY: (
                f"Closing the loop for now — {lead.name}",
                f"Hi {greeting},\n\nUnderstood. I won’t manufacture urgency. "
                f"If you want, tell me a specific month when the comparison would be useful; otherwise I’ll close this out.\n\n{contact}\n\n{opt_out}",
            ),
            OutreachKind.CALL_OPENING: (
                "",
                f"15-second opening:\nHi, is this the person who handles the public website or Google presence for {lead.name}? I’ll be quick. "
                f"The one public-facing point to verify is {issue_line}. "
                f"{question} Can I explain that one observation?",
            ),
            OutreachKind.VOICEMAIL: (
                "",
                f"Hi, this is {self.sender.name or 'a website analyst'}. I have a question for {lead.name}: {question} "
                f"I can prepare reviewed public evidence if useful. Call or text me back at {self.sender.phone or '[your phone]'}.",
            ),
            OutreachKind.REPORT_DELIVERY: (
                f"The comparison for {lead.name}",
                f"Hi {greeting},\n\nAfter a current comparison is prepared and reviewed, I can send it for your consideration. "
                f"The current Smart Offer is {smart_offer.offer_name}; the first scope is {report_scope}; the current recommended ask is {report_price}."
                f"{goal_line}{buyer_line}{credibility_line}\n\n{contact}\n\n{opt_out}",
            ),
            OutreachKind.MOCKUP_DELIVERY: (
                f"Website concept for {lead.name}",
                f"Hi {greeting},\n\nIf useful, I can prepare an optional concept after the facts and selected scope are reviewed. "
                "Any concept would be a prospect demo rather than a live affiliated site; it would require review before sharing."
                f"{goal_line}\n\n{contact}\n\n{opt_out}",
            ),
        }

    def proof_dependencies(
        self, lead: Lead, session: Session, *, research_only: bool = False,
    ) -> dict[OutreachKind, list[dict[str, Any]]]:
        """Return structured Seller Proof dependencies for drafts that actually use credibility output."""
        conversation = ConversationStateService().build(session, lead)
        credibility = CredibilityService().build(session, lead.category)
        credibility_used = any(
            (
                conversation.credibility_concern,
                conversation.wants_examples,
                conversation.wants_references,
                conversation.wants_proof,
                conversation.seller_experience_question,
                conversation.concerned_about_ai,
                conversation.legitimacy_concern,
            )
        )
        if not credibility_used:
            return {}
        dependencies: list[dict[str, Any]] = []
        if conversation.seller_experience_question or conversation.wants_examples or conversation.wants_references or conversation.wants_proof:
            dependencies.extend(credibility.email_proof_dependencies)
        if credibility.attachments.send:
            dependencies.extend(credibility.attachment_proof_dependencies)
        merged: dict[int, dict[str, Any]] = {}
        for dependency in dependencies:
            proof_id = int(dependency["proof_id"])
            if proof_id not in merged:
                merged[proof_id] = dict(dependency)
                merged[proof_id]["usages"] = list(dependency.get("usages", []))
            else:
                usages = set(merged[proof_id].get("usages", []))
                usages.update(dependency.get("usages", []))
                merged[proof_id]["usages"] = sorted(usages)
        result = list(merged.values())
        if not result:
            return {}
        return {
            kind: result
            for kind in (
                OutreachKind.INITIAL_EMAIL,
                OutreachKind.SHORT_FOLLOW_UP,
                OutreachKind.INTERESTED_REPLY,
                OutreachKind.REPORT_DELIVERY,
            )
            if kind != OutreachKind.INITIAL_EMAIL or not research_only
        }

    def contact_block(self) -> str:
        parts = [self.sender.name, self.sender.business_name, self.sender.reply_email, self.sender.phone, self.sender.postal_address]
        return "\n".join(part for part in parts if part).strip() or "[Your name]\n[Your business]\n[Your contact info]"
