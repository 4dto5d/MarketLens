"""Synthetic exact-request privacy and canonical agreement regression controls."""
import json
from dataclasses import replace
from datetime import date, timedelta
from itertools import product
from threading import Event

import pytest
from sqlalchemy import select
from test_handoff4_payable_delivery import seed
from test_opportunity_intelligence import prepare
from test_opportunity_intelligence import setup as base_setup
from test_sales_delivery_corrections import storage

from local_presence_miner.database.pricing_repository import save_offer_history
from local_presence_miner.database.schema import Lead, ProspectFindingRevision, WebsiteAuditRecord
from local_presence_miner.domain.enums import AssertionSourceKind, AssertionSourceTextMode
from local_presence_miner.domain.opportunity_intelligence import MODES, canonical
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.conversation_state_service import ConversationStateService
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.opportunity_intelligence_service import LocalRequestBudget, OpportunityIntelligenceService
from local_presence_miner.services.owner_strategy_service import append_owner_strategy
from local_presence_miner.services.prospect_finding_service import capture_contact_finding, project_findings


@pytest.fixture(name="setup")
def setup_fixture(tmp_path):
    yield from base_setup.__wrapped__(tmp_path)


@pytest.mark.parametrize("mode", ["Focused", "Full Prospect", "Deep Investigation"])
def test_every_disclosure_combination_contains_only_selected_fact_and_opted_context(setup, monkeypatch, mode):
    _, factory, identity, service = setup
    sentinels = {"capacity": "PRIVATE_STRUCTURED_CAPACITY_941", "territory": "PRIVATE_TERRITORY_942",
                 "goal": "PRIVATE_LEGACY_GOAL_943", "second": "UNSELECTED_WEBSITE_FACT_944",
                 "explanation": "PRIVATE_DERIVED_REASON_945", "worksheet": "I want easier editing"}
    with factory() as session:
        lead = session.get(Lead, identity)
        audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == identity))
        audit.evidence_json = json.dumps({"tap_to_call": {"explanation": sentinels["second"]}})
        session.flush()
        capture_contact_finding(session, identity, "website.check.contact_form", actor="Synthetic")
        capture_contact_finding(session, identity, "website.check.tap_to_call", actor="Synthetic")
        append_owner_strategy(session, lead, {"schema_version": 1,
            "constraints": [{"kind": "capacity", "value": "available", "original_wording": sentinels["capacity"]}],
            "target_territories": [{"kind": "zip", "country": "US", "state": "CO", "postal_codes": ["80903"],
                                    "original_wording": sentinels["territory"]}]},
            source_text="Synthetic explicit owner instructions", owner_confirmed=True)
        ConversationStateService().append_assertion(session, lead, subject_key="business.goal", value=sentinels["goal"],
            source_kind=AssertionSourceKind.OWNER_LITERAL, source_text=sentinels["goal"],
            source_text_mode=AssertionSourceTextMode.VERBATIM)
        session.commit()
        reference = next(item["reference"] for item in project_findings(session, identity)
                         if item["fact_id"] == "website.check.contact_form")
        before = [(row.id, row.source_snapshot_json, row.source_sha256) for row in session.scalars(select(ProspectFindingRevision))]
    import local_presence_miner.services.opportunity_intelligence_service as module
    real_build = module.build_adaptive_sales_plan_with_context

    def derived_reason(*args, **kwargs):
        plan, pricing, context = real_build(*args, **kwargs)
        assessment = {**context.intervention_assessment, "summary": sentinels["explanation"]}
        return plan, pricing, replace(context, intervention_assessment=assessment)

    monkeypatch.setattr(module, "build_adaptive_sales_plan_with_context", derived_reason)
    import local_presence_miner.domain.opportunity_intelligence as contract
    captured = {}

    def capture_serialized_request(value):
        serialized = canonical(value)
        if isinstance(value, dict) and "instructions" in value and "input" in value:
            captured["body"] = serialized
        return serialized

    monkeypatch.setattr(contract, "canonical", capture_serialized_request)
    allowed_count = 0
    for owner, explanation, worksheet, market in product((False, True), repeat=4):
        captured.clear()
        try:
            prepared = prepare(service, identity, mode=mode, selected=[reference], include_owner_context=owner,
                               include_commercial_explanation=explanation, include_worksheet=worksheet, include_market=market)
            packet = prepared["packet"]
            outbound = canonical(prepared["body"])
            allowed_count += 1
        except ValueError as exc:
            # Some full explanations exceed Focused's unchanged complete-body
            # budget. Inspect that exact rejected body too; no dispatch exists.
            assert "complete request limit" in str(exc) and mode == "Focused"
            outbound = captured["body"]
            assert len(outbound.encode()) > MODES[mode][0]
            packet = json.loads(json.loads(outbound)["input"][0]["content"])
        assert sentinels["second"] not in outbound
        for name in ("capacity", "territory", "goal"):
            assert (sentinels[name] in outbound) is owner
        assert (sentinels["explanation"] in outbound) is explanation
        assert (sentinels["worksheet"] in outbound) is worksheet
        source = packet["evidence"][0]["source"]
        assert set(source["payload"]) == {"audit_id", "fact_id", "value"}
        assert source["reference"] == reference
        assert source["source_sha256"] == reference.rsplit(":", 1)[1]
        assert type(source["payload"]["value"]) is bool
        assert packet["coverage"]["owner_context"]["included"] is owner
    assert allowed_count > 0
    with factory() as session:
        assert before == [(row.id, row.source_snapshot_json, row.source_sha256)
                          for row in session.scalars(select(ProspectFindingRevision))]
        assert sentinels["second"] in before[0][1]


@pytest.mark.parametrize("status", ["Accepted", "Won"])
@pytest.mark.parametrize("change", [None, "scope", "amount", "offer", "historical"])
def test_exact_current_agreement_is_distinct_from_candidate_and_history(tmp_path, status, change):
    _, factory = storage.__wrapped__(tmp_path)
    try:
        identity, amount = seed(factory, ready=True)
        service = OpportunityIntelligenceService(factory, budget=LocalRequestBudget(tmp_path / "budget"))
        candidate = prepare(service, identity)["packet"]
        assert candidate["commercial_context"]["agreement"]["state"] == "candidate"
        with factory() as session:
            lead = session.get(Lead, identity)
            _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
            args = dict(lead_id=identity, offer_date=date.today().isoformat(), business_name="Synthetic agreement",
                niche=lead.category, package_name="Conversion Tune-Up", canonical_offer_id=context.offer_id,
                scope_summary="; ".join(context.scope), initial_ask=amount, status=status,
                closed_amount=amount if status == "Won" else None)
            if change == "historical":
                args.update(offer_date=(date.today() - timedelta(days=30)).isoformat(),
                            historical_record=True, notes="Explicit synthetic historical agreement")
            offer = save_offer_history(session, **args)
            if change == "scope":
                offer.scope_summary = "A different indivisible task"
            elif change == "amount":
                offer.closed_amount = amount + 50
            elif change == "offer":
                offer.canonical_offer_id = "starter_website"
            session.commit()
        with factory() as session:
            lead = session.get(Lead, identity)
            ordinary = DeliveryPacketService().build(session, lead)  # no intelligence adapter/context
        packet = prepare(service, identity)["packet"]
        assert packet["delivery_context"]["state"] == ordinary["state"]
        assert packet["delivery_context"]["ready_for_payment"] is ordinary["ready_for_payment"]
        assert packet["delivery_context"]["binding"] == ordinary["binding"]
        agreement = packet["commercial_context"]["agreement"]
        assert agreement["current_accepted"] is (change is None)
        assert agreement["state"] == ("current_accepted" if change is None else "historical" if change == "historical" else "candidate")
        if change is None:
            assert ordinary["ready_for_payment"] is True
            assert "candidate" not in packet["commercial_context"]["scope_status"].casefold()
        private_notes = "Owner/provider confirms actual access and feasibility for this exact page-text scope."
        assert private_notes not in canonical(prepare(service, identity)["body"])
        if change in (None, "historical"):
            assert private_notes in canonical(prepare(service, identity, mode="Full Prospect", include_commercial_explanation=True)["body"])
    finally:
        factory.kw["bind"].dispose()


class QuestionTransport:
    def run(self, body, **kwargs):
        packet = json.loads(body["input"][0]["content"])
        unknown = {"assessment": "unknown", "evidence_ids": [], "assumptions": [], "missing_prerequisites": []}
        advice = {"schema_version": 2, "context_hash": packet["context_hash"], "status": "insufficient_evidence",
            "summary": "Synthetic planning only", "interpretations": [], "contradictions": [],
            "owner_questions": [{"id": "q1", "question": "Who can demonstrate this exact task?", "reason": "Verify assistance",
                                 "evidence_ids": [], "priority": "next"}],
            "feasibility": {key: unknown for key in ("technical", "operator", "commercial", "execution")},
            "alternatives": [], "effort_uncertainty": [], "next_actions": [],
            "unsupported_conclusions": [], "limitations": []}
        return {"text": canonical(advice), "usage": None, "request_id": "synthetic"}


def test_active_request_change_rejects_adoption_and_fresh_question_can_be_saved(setup):
    _, _, identity, service = setup
    prepared = prepare(service, identity, include_worksheet=True,
                       operator_context={"assistance": "Assistant available on Friday"})
    stable = prepare(service, identity, include_worksheet=True,
                     operator_context={"assistance": "Assistant available on Friday"})
    assert prepared["request_signature"] == stable["request_signature"]
    result = service.execute(prepared, QuestionTransport(), cancel=Event(), current_account=lambda: "a" * 64)
    changed = prepare(service, identity, include_worksheet=True, operator_context={"assistance": "No assistant available"})
    with pytest.raises(ValueError, match="Active request changed"):
        service.adopt(result["run_id"], lead_id=identity, account_binding="a" * 64, item_id="q1", actor="Synthetic",
                      edited_text="Prepare with assistance", active_request_signature=changed["request_signature"])
    fresh = service.execute(changed, QuestionTransport(), cancel=Event(), current_account=lambda: "a" * 64)
    assert service.adopt(fresh["run_id"], lead_id=identity, account_binding="a" * 64, item_id="q1", actor="Synthetic",
                         edited_text="Who can demonstrate this exact task?", active_request_signature=changed["request_signature"])


@pytest.mark.parametrize("states,expected", [(('none', 'none'), False), (('unknown', 'unknown'), False),
                                            (('affirmative', 'none'), False), (('affirmative', 'affirmative'), True)])
def test_operator_support_requires_two_task_specific_affirmative_attestations(setup, states, expected):
    _, _, identity, service = setup
    operator = {"experience_state": states[0], "demonstration_state": states[1],
                "experience": "None" if states[0] != "affirmative" else "Synthetic exact-task experience",
                "demonstration": "None" if states[1] != "affirmative" else "Synthetic exact-task demonstration",
                "limits": "No capability to do this task" if not expected else "Self-report remains unverified"}
    packet = prepare(service, identity, operator_context=operator)["packet"]
    assert (packet["source_registry"]["operator_context"]["supports"] == ["operator"]) is expected
    assert packet["operator_context"]["task_scope"] == packet["question"]
    assert packet["operator_context"]["self_reported"] is True
    assert packet["source_registry"]["operator_context"]["paid_claim_eligible"] is False
