from __future__ import annotations

import json
from dataclasses import replace

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.schema import CompetitorRecord, Lead, WebsiteAuditRecord
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_outreach_service import AdaptiveOutreachService
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.conversation_state_service import ConversationState
from local_presence_miner.services.offer_builder import build_starting_offer_input, generate_starting_offer
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.seller_pricing_service import SellerPricingService


def adaptive_lead() -> Lead:
    lead = Lead(
        place_id="adaptive-roofer",
        name="ABC Roofing",
        category="roofers",
        phone="555-0100",
        website="https://abc.example",
        rating=4.8,
        review_count=34,
        lead_score=82,
        sales_priority_score=86,
        qualification_class="Demo Priority",
        qualification_confidence="Strong",
        recommended_offer_id="conversion_tune_up",
        recommended_offer="conversion_tune_up",
        offer_resolution_state="canonical_id",
    )
    lead.target_signals_json = json.dumps(["No obvious CTA", "No contact form", "Reviews not showcased"])
    # Paid conversion advice now requires a current structured observation;
    # legacy free-text labels are not proof of a defect.
    lead.audit = WebsiteAuditRecord(
        url=lead.website, reachable=True, status_code=200,
        checks_json=json.dumps({"https": True, "viewport": True, "tap_to_call": False,
                                "sitewide_contact_path": False, "contact_form": False,
                                "clear_primary_cta": False, "service_pages": True}),
    )
    lead.qualification_json = json.dumps(
        {
            "classification": "Demo Priority",
            "confidence": "Strong",
            "positives": [
                "The public audit shows a meaningful improvement opportunity.",
                "Strong public rating suggests the underlying business has customer trust.",
            ],
            "disconfirmers": [],
            "unknowns": [],
            "next_action": "Prioritize phone outreach; build a custom demo after interest.",
        }
    )
    return lead


def test_plan_combines_observed_evidence_offer_and_live_pricing_without_inflated_confidence(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "adaptive.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = adaptive_lead()
        session.add(lead)
        session.flush()
        competitor = CompetitorRecord(
            lead_id=lead.id,
            competitor_place_id="competitor-1",
            competitor_name="Better Roof Co",
            match_score=86,
            reason="Same niche and market",
        )
        session.add(competitor)
        session.flush()
        plan, pricing = build_adaptive_sales_plan(session, lead, competitors=[competitor])

    assert plan.intelligence_level == "Moderate"
    assert plan.segment == "Demo Priority"
    assert plan.primary_theme == "Conversion path"
    assert "sampled contact" in plan.primary_problem.lower()
    assert plan.smart_offer.recommended_ask == pricing.recommended
    assert plan.smart_offer.easy_close == pricing.easy_close
    assert plan.smart_offer.stretch == pricing.stretch
    assert plan.smart_offer.scope[0] == "mobile call/quote button"
    assert any("qualitative" in reason for reason in plan.smart_offer.why_this_offer)
    assert any("verify" in item.lower() for item in plan.smart_offer.human_checks)


def test_direct_adaptive_scope_override_discards_blank_and_duplicate_items(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "scope-override.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = adaptive_lead()
        session.add(lead)
        session.flush()
        offer = generate_starting_offer(build_starting_offer_input(lead, []))
        pricing = SellerPricingService().recommend_for_lead(session, lead, [])
        plan = AdaptiveOutreachService().build(
            lead, [], pricing, offer,
            scope_override=(" Homepage CTA and estimate/request flow ", "", " \t ", "Homepage CTA and estimate/request flow"),
        )
    assert plan.smart_offer.offer_id == "conversion_tune_up"
    assert plan.smart_offer.scope == ("Homepage CTA and estimate/request flow",)


def test_unresolved_offer_fallback_uses_same_fail_closed_goal_focus() -> None:
    lead = adaptive_lead()
    offer = replace(generate_starting_offer(build_starting_offer_input(lead, [])), offer_id="")
    cases = (
        ("Make it easier to find us on Google", "Conversion path"),
        ("Improve the quality of our reviews", "Conversion path"),
        ("Higher quality leads", "Lead quality"),
        ("Make intake easier", "Intake efficiency"),
        ("Better-fit jobs and easier intake", "Conversion path"),
    )
    for goal, expected_theme in cases:
        plan = AdaptiveOutreachService().build(
            lead, [], None, offer, conversation=ConversationState(business_goal=goal),
        )
        assert plan.primary_theme == expected_theme
        assert f"Conversation context: {goal}" in plan.evidence_lines


def test_call_guide_has_lead_specific_recursive_if_then_paths(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "call-tree.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = adaptive_lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])

    busy = next(branch for branch in guide.branches if branch.key == "busy_enough")
    booked = next(item for item in busy.followups if item.label == "We're booked out")
    assert booked.followups
    assert {item.label for item in booked.followups} >= {"We want better-fit jobs", "We do not want changes"}
    assert str(guide.recommended_ask) in guide.price_answer.replace(",", "")
    assert guide.intelligence_level == "Moderate"
    assert "Conversion path" in guide.strategy


def test_email_decision_tree_changes_with_lead_and_uses_seller_price(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "email-tree.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = adaptive_lead()
        session.add(lead)
        session.flush()
        pricing = SellerPricingService().recommend_for_lead(session, lead, [])
        drafts = OutreachService(SenderInfo(name="Sam", opt_out_line="Reply opt out.")).generate_all(
            lead,
            city="Peoria",
            pricing=pricing,
            competitors=[],
            session=session,
        )

    assert OutreachKind.INTERESTED_REPLY in drafts
    assert OutreachKind.PRICE_REPLY in drafts
    assert OutreachKind.PROVIDER_REPLY in drafts
    assert OutreachKind.NOT_NOW_REPLY in drafts
    initial = drafts[OutreachKind.INITIAL_EMAIL][1]
    price_reply = drafts[OutreachKind.PRICE_REPLY][1]
    # This fixture has lead summaries, not a current recorded website audit.
    # It must not promote those summaries into a completed factual review.
    assert "Website audit explicitly recorded" not in initial
    assert "requires confirmation" in initial
    assert "manual verification" in initial
    assert f"${pricing.recommended:,}" in price_reply
    assert f"${pricing.easy_close:,}" in price_reply
    assert "revenue guarantee" not in price_reply.lower()
    assert "Reply opt out." in initial


def test_hold_plan_is_research_first_not_a_confident_pitch(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "hold.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="hold",
            name="Uncertain Local Business",
            category="business",
            lead_score=45,
            sales_priority_score=42,
            qualification_class="Hold",
            qualification_confidence="Low",
            recommended_offer="No-Track-Record Pilot",
        )
        lead.target_signals_json = json.dumps(["No verified revenue leak captured yet"])
        session.add(lead)
        session.flush()
        pricing = SellerPricingService().recommend_for_lead(session, lead, [])
        offer = generate_starting_offer(build_starting_offer_input(lead, []))
        plan = AdaptiveOutreachService().build(lead, [], pricing, offer)

    assert plan.segment == "Hold"
    assert "research" in plan.message_strategy.lower()
    assert "do not pitch" in plan.call_objective.lower()
    assert any("missing evidence" in item.lower() for item in plan.smart_offer.human_checks)
