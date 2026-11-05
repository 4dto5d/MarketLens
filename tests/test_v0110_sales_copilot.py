from __future__ import annotations

from local_presence_miner import __version__
from local_presence_miner.config import SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import save_contact_interaction
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.categories import opportunity_category_labels
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.outreach_service import OutreachService


def _lead() -> Lead:
    return Lead(
        place_id="v0110-test",
        name="ABC Roofing",
        owner="Jane",
        category="roofers",
        website="https://example.com",
        sales_priority_score=88,
        qualification_class="Demo Priority",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Demo Priority","confidence":"Strong","positives":["Active local business"]}',
        target_signals_json='["No obvious CTA"]',
    )


def test_version_and_profit_aware_categories() -> None:
    assert __version__ == "0.1.16"
    labels = opportunity_category_labels()
    assert labels[0].startswith("Top Opportunities /")
    assert any(label.endswith("roofers") for label in labels[:10])
    assert any(label.startswith("All Categories /") for label in labels)


def test_conversation_history_changes_smart_offer_and_email(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "state.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-08-27T09:00",
            method="Phone",
            direction="Outbound",
            outcome="Interested",
            notes="Booked out; wants fewer bad-fit calls",
            business_goal="Better-fit jobs",
            capacity_status="Booked/busy",
            buyer_questions=["SEO scope"],
            branch_path=["We're already busy enough", "We're booked out", "We want better-fit jobs"],
            next_action="Send comparison",
        )
        session.flush()
        plan, pricing = build_adaptive_sales_plan(session, lead, competitors=[])
        drafts = OutreachService(SenderInfo(name="Sam", opt_out_line="Reply opt out.")).generate_all(
            lead,
            pricing=pricing,
            competitors=[],
            session=session,
            adaptive_plan=plan,
        )
    assert plan.primary_theme == "Evidence validation"
    assert plan.smart_offer.intervention_assessment["state"] == "validate_first"
    assert "timing and capacity" in plan.smart_offer.intervention_assessment["summary"]
    assert not pricing.price_available and plan.smart_offer.scope == ()
    assert "better-fit jobs" in drafts[OutreachKind.INTERESTED_REPLY][1].lower()
    assert "seo" in drafts[OutreachKind.INTERESTED_REPLY][1].lower()


def test_call_tree_contains_big_missing_branches(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "tree.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])
    keys = {branch.key for branch in guide.branches}
    assert {"wrong_person", "provider", "credibility", "send_info", "buyer_questions"} <= keys
    buyer = next(branch for branch in guide.branches if branch.key == "buyer_questions")
    labels = {item.label for item in buyer.followups}
    assert {"Do I keep my domain?", "Is there a monthly fee / hosting?", "Do you do SEO?", "Will changing it hurt rankings?"} <= labels


def test_research_only_blocks_live_call_mode_flag(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "hold.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead()
        lead.qualification_class = "Hold"
        lead.qualification_json = '{"classification":"Hold","confidence":"Low"}'
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])
    assert guide.research_only is True
