"""Synthetic real-service controls for supported presentation and planning adoption."""
import json

import pytest
from sqlalchemy import select
from test_opportunity_intelligence import FakeTransport, advice_for, execute, prepare
from test_opportunity_intelligence import setup as base_setup

from local_presence_miner.database.opportunity_intelligence_repository import IntelligenceResult
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.intelligence_research import context_options
from local_presence_miner.domain.opportunity_intelligence import canonical, present_advice, request_body, validate_advice
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService
from local_presence_miner.services.prospect_finding_service import capture_contact_finding, project_findings, revise_finding
from local_presence_miner.ui.widgets.opportunity_intelligence_widget import readable_advice


@pytest.fixture
def setup(tmp_path):
    yield from base_setup.__wrapped__(tmp_path)


def decision(ref, **changes):
    return {"recommendation": "SYNTHETIC-PAID-RECOMMENDATION", "evidence_ids": [ref],
            "intended_use": "paid_recommendation", "evidence_use": "positive_premise",
            "action_kind": "internal_planning",
            "decisive_unknown": "Owner need", "would_change_if": "Provider already solves it", **changes}


@pytest.mark.parametrize("citation", ["withheld", "disputed"])
def test_real_service_dnc_and_ineligible_paid_premise_suppressed_everywhere(setup, citation):
    _, factory, identity, service = setup
    with factory() as session:
        session.get(Lead, identity).suppressed = True
        if citation == "disputed":
            row = capture_contact_finding(session, identity, "website.check.contact_form", actor="Synthetic")
            revise_finding(session, identity, row.finding_key, expected_revision=1, review_state="DISPUTED",
                           actor="Synthetic", review_note="Synthetic dispute")
        session.commit()
        refs = [item["reference"] for item in project_findings(session, identity)]

    def consumers():
        with factory() as session:
            lead = session.get(Lead, identity)
            _, price, context = build_adaptive_sales_plan_with_context(session, lead)
            delivery = DeliveryPacketService().build(session, lead)
            contact = OutreachEligibilityService().evaluate(session, lead)
            return (lead.suppressed, lead.qualification_class, context.offer_id, context.scope, price.recommended,
                    delivery["state"], delivery["ready_for_payment"], contact.state, contact.permits_live_use)

    before = consumers()
    prepared = prepare(service, identity, include_worksheet=True, selected=refs)
    ref = "F1" if citation == "disputed" else "market_context"
    assert not prepared["packet"]["source_registry"][ref]["eligible"]

    def response(raw):
        raw["status"] = "advisory"
        raw["summary"] = "SYNTHETIC-PAID-SUMMARY"
        raw["feasibility"]["execution"]["assessment"] = "blocked"
        raw["decision_review"] = decision(ref)
        raw["interpretations"] = [{"id": "i_paid", "statement": "SYNTHETIC-PAID-INTERPRETATION",
            "kind": "inference", "evidence_ids": [ref], "assumptions": [], "competing_explanations": [],
            "limitations": [], "intended_use": "paid_recommendation", "evidence_use": "positive_premise"}]
        raw["owner_questions"][0]["evidence_ids"] = [ref]
        raw["next_actions"] = [
            {"id": "a_paid", "action": "SYNTHETIC-PAID-ACTION", "reason": "Sell from disputed evidence",
             "evidence_ids": [ref], "destination": "Smart Offer", "intended_use": "paid_recommendation",
             "evidence_use": "positive_premise", "action_kind": "internal_planning"},
            {"id": "a_contact", "action": "SYNTHETIC-DNC-CALL-INSTRUCTION", "reason": "Call this suppressed lead",
             "evidence_ids": [], "destination": "Record Contact", "intended_use": "internal_verification",
             "evidence_use": "uncertainty", "action_kind": "contact"}]

    transport = FakeTransport(response)
    completed = execute(service, prepared, transport)
    assert completed["advice"]["decision_review"] is None
    assert completed["advice"]["next_actions"] == completed["advice"]["interpretations"] == []
    assert completed["advice"]["feasibility"]["execution"]["assessment"] == "blocked"
    for advice in (completed["advice"], execute(service, prepared, transport)["advice"], service.history(identity)[0]["advice"]):
        visible = readable_advice(advice, completed["packet"])
        assert "SYNTHETIC-PAID" not in visible and "SYNTHETIC-DNC" not in visible
        assert "Which edit is blocked" in visible
        assert present_advice(advice, completed["packet"]) == advice
    assert transport.calls == 1
    for item_id in ("a_paid", "a_contact"):
        with pytest.raises(ValueError, match="Only explicit"):
            service.adopt(completed["run_id"], lead_id=identity, account_binding="a" * 64,
                          item_id=item_id, actor="Synthetic", edited_text="Unsafe original")
    with factory() as session:
        raw = json.loads(session.scalar(select(IntelligenceResult)).response_json)["text"]
        assert "SYNTHETIC-PAID-RECOMMENDATION" in raw and "SYNTHETIC-DNC-CALL-INSTRUCTION" in raw
    service.adopt(completed["run_id"], lead_id=identity, account_binding="a" * 64, item_id="q1",
                  actor="Synthetic", edited_text="Which specific task remains unverified?")
    assert consumers() == before


def test_affirmative_operator_states_are_task_scoped_and_none_text_is_not_support():
    packet = {"mode": "Focused", "question": "Perform exact task A", "context_hash": "a" * 64, "evidence": [],
              "source_registry": {"operator_context": {"eligible": True, "supports": ["operator"]}},
              "operator_context": {"evidence_id": "operator_context", "experience": "None", "demonstration": "None",
                                   "limits": "No capability to do this task", "experience_state": "none",
                                   "demonstration_state": "none", "task_scope": "Perform exact task A"}}
    raw = advice_for(packet)
    raw["feasibility"]["operator"] = {"assessment": "appears_supported", "evidence_ids": ["operator_context"],
                                     "assumptions": [], "missing_prerequisites": []}
    assert present_advice(validate_advice(canonical(raw), packet), packet)["feasibility"]["operator"]["assessment"] != "appears_supported"
    packet["operator_context"].update(experience_state="affirmative", demonstration_state="affirmative")
    assert present_advice(raw, packet)["feasibility"]["operator"]["assessment"] != "appears_supported"
    packet["operator_context"].update(experience="Exact task A performed", demonstration="Exact task A sample",
                                      experience_state="affirmative", demonstration_state="affirmative", limits="")
    assert present_advice(raw, packet)["feasibility"]["operator"]["assessment"] == "appears_supported"
    packet["operator_context"]["task_scope"] = "Different task B"
    assert present_advice(raw, packet)["feasibility"]["operator"]["assessment"] != "appears_supported"
    options = context_options(operator_context={"experience": "None", "demonstration": "None"})
    assert options["operator_context"]["experience_state"] == options["operator_context"]["demonstration_state"] == "unknown"
    with pytest.raises(ValueError, match="states"):
        context_options(operator_context={"experience_state": "yes"})


def test_typed_paid_support_and_uncertainty_are_distinct():
    packet = {"mode": "Focused", "context_hash": "a" * 64, "evidence": [],
              "source_registry": {"F1": {"eligible": True, "paid_claim_eligible": True}}}
    raw = advice_for(packet)
    raw["decision_review"] = decision("F1")
    assert present_advice(validate_advice(canonical(raw), packet), packet)["decision_review"] is not None
    packet["source_registry"]["F1"]["paid_claim_eligible"] = False
    assert present_advice(raw, packet)["decision_review"] is None
    raw["decision_review"].update(intended_use="internal_verification", evidence_use="uncertainty")
    packet["source_registry"]["F1"]["eligible"] = False
    assert present_advice(raw, packet)["decision_review"] is not None
    raw["decision_review"].pop("intended_use")
    with pytest.raises(ValueError):
        validate_advice(canonical(raw), packet)


def test_declared_contact_decision_is_gated_even_as_a_verification_recommendation():
    packet = {"mode": "Focused", "context_hash": "a" * 64, "evidence": [],
              "source_registry": {"F1": {"eligible": True, "paid_claim_eligible": True}},
              "commercial_context": {"contact_eligibility": {"permits_live_use": False}}}
    raw = advice_for(packet)
    raw["decision_review"] = decision("F1", intended_use="internal_verification", evidence_use="uncertainty",
                                      action_kind="contact")
    assert present_advice(validate_advice(canonical(raw), packet), packet)["decision_review"] is None
    packet["commercial_context"]["contact_eligibility"]["permits_live_use"] = True
    assert present_advice(raw, packet)["decision_review"] is not None


@pytest.mark.parametrize("mode,limit", [("Focused", 2), ("Full Prospect", 3), ("Deep Investigation", 2)])
def test_only_full_prospect_accepts_three_distinct_alternatives(mode, limit):
    packet = {"mode": mode, "context_hash": "a" * 64, "evidence": [], "source_registry": {}}
    raw = advice_for(packet)
    alternative = {"id": "a0", "label": "Current provider", "existing_offer_id": None, "evidence_ids": [],
                   "candidate_deliverables": [], "exclusions": [], "dependencies": [], "risks": [],
                   "disposition": "investigate", "intended_use": "internal_verification", "evidence_use": "uncertainty"}
    raw["alternatives"] = [dict(alternative, id=f"a{i}") for i in range(limit)]
    validate_advice(canonical(raw), packet)
    assert ("three alternatives" if limit == 3 else "two alternatives") in request_body(packet, "fixture-model")["instructions"]
    raw["alternatives"].append(dict(alternative, id="extra"))
    with pytest.raises(ValueError, match="alternative limit"):
        validate_advice(canonical(raw), packet)
