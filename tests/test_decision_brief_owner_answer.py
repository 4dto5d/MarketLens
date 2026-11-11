"""The owner answer remains a separate authority after adopting an AI question."""
from threading import Event

import pytest
from test_handoff4_payable_delivery import seed
from test_opportunity_intelligence import FakeTransport
from test_owner_fit_corrections import strategy
from test_sales_delivery_corrections import storage

from local_presence_miner.database.pricing_repository import save_offer_history
from local_presence_miner.database.schema import Lead
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.opportunity_intelligence_service import LocalRequestBudget, OpportunityIntelligenceService
from local_presence_miner.services.opportunity_workflow_service import latest_worksheet, save_worksheet
from local_presence_miner.services.owner_strategy_service import append_owner_strategy


@pytest.mark.parametrize("acted_on", [False, True])
def test_real_owner_answer_after_planning_adoption_refreshes_decision(tmp_path, acted_on):
    _, factory = storage.__wrapped__(tmp_path)
    identity, _ = seed(factory, ready=acted_on)
    try:
        with factory() as session:
            lead = session.get(Lead, identity)
            _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
            original_offer = context.offer_id
            assert pricing.price_available
            if acted_on:
                save_offer_history(session, offer_date="2026-11-11", business_name=lead.name, niche=lead.category,
                    package_name="Exact synthetic accepted scope", scope_summary="; ".join(context.scope),
                    initial_ask=pricing.recommended, status="Accepted", lead_id=identity,
                    canonical_offer_id=context.offer_id)
            save_worksheet(session, lead, {"route": "owner_report", "owner_reported": True,
                "source_ref": "Synthetic owner discussion", "observation": "Confirm the current provider's scope",
                "owner_question": "Existing human question", "next_action": "Existing human action"})
            session.commit()
        service = OpportunityIntelligenceService(factory, budget=LocalRequestBudget(tmp_path / "budget"))
        request = dict(question="Is our current provider already responsible for this page?",
                       mode="Focused", model="fixture-model", account_binding="a" * 64,
                       include_worksheet=True, include_owner_context=True)
        preview = service.prepare(identity, **request)
        result = service.execute(preview, FakeTransport(), cancel=Event(), current_account=lambda: "a" * 64)
        service.adopt(result["run_id"], lead_id=identity, account_binding="a" * 64,
                      item_id="q1", actor="Synthetic operator", edited_text="Who is already correcting this page?")
        with factory() as session:
            lead = session.get(Lead, identity)
            _, _, context = build_adaptive_sales_plan_with_context(session, lead)
            assert context.offer_id == original_offer
            assert "AI-assisted operator planning" in latest_worksheet(session, identity)["data"]["owner_question"]
            append_owner_strategy(session, lead,
                strategy(("provider_work", "emergency plumbing", "Our provider is already correcting this exact page.")),
                source_text="Our provider is already correcting this exact page.", owner_confirmed=True)
            session.commit()
        fresh = service.prepare(identity, **request)
        assert fresh["cache_key"] != preview["cache_key"]
        assert fresh["packet"]["owner_context"]["state"] == "confirmed"
        assert fresh["packet"]["commercial_context"]["intervention_rationale"]["state"] == "validate_first"
        with factory() as session:
            _, _, context = build_adaptive_sales_plan_with_context(session, session.get(Lead, identity))
            if acted_on:
                assert context.offer_id == original_offer
        assert not service.history(identity)[0]["eligibility"]["current"]
    finally:
        factory.kw["bind"].dispose()
