"""Advice is optional planning, never source evidence or commercial authority."""
import json
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from test_intervention_integration import BROKEN_ROUTE, add_business
from test_intervention_integration import storage as storage_fixture

from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.opportunity_intelligence_repository import IntelligenceResult, IntelligenceReview, IntelligenceRun
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.opportunity_intelligence import canonical, validate_advice
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.opportunity_intelligence_service import LocalRequestBudget, OpportunityIntelligenceService
from local_presence_miner.services.opportunity_workflow_service import NUMBER_FIELDS, TEXT_FIELDS, latest_worksheet, save_worksheet
from local_presence_miner.services.prospect_finding_service import capture_contact_finding, record_owner_need, revise_finding
from local_presence_miner.time_utils import utc_now


def advice_for(packet):
    unknown = {"assessment": "unknown", "evidence_ids": [], "assumptions": [], "missing_prerequisites": ["Owner access and operator readiness"]}
    return {"schema_version": 2, "context_hash": packet["context_hash"], "status": "insufficient_evidence",
            "summary": "Synthetic fixture, not actual provider reasoning.", "interpretations": [], "contradictions": [],
            "owner_questions": [{"id": "q1", "question": "Which edit is blocked, and who controls the account?", "reason": "Access is unknown",
                                 "evidence_ids": [], "priority": "next"}],
            "feasibility": {name: unknown for name in ("technical", "operator", "commercial", "execution")},
            "alternatives": [], "effort_uncertainty": [], "next_actions": [], "unsupported_conclusions": ["No migration quote"],
            "limitations": ["No platform documentation fetched"]}


class FakeTransport:
    def __init__(self, mutate=None):
        self.calls = 0
        self.mutate = mutate

    def run(self, body, **kwargs):
        self.calls += 1
        value = advice_for(json.loads(body["input"][0]["content"]))
        if self.mutate:
            self.mutate(value)
        return {"text": canonical(value), "usage": {"input_tokens": 123}, "request_id": "synthetic-not-provider"}


@pytest.fixture
def setup(tmp_path):
    config, factory = storage_fixture.__wrapped__(tmp_path)
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE)
        data = {**{key: "" for key in TEXT_FIELDS}, **{key: "" for key in NUMBER_FIELDS}, "route": "owner_report",
                "owner_reported": True, "source_ref": "Synthetic owner conversation", "observation": "I want easier editing",
                "owner_question": "Human question retained", "finding_refs": []}
        save_worksheet(session, lead, data)
        identity = lead.id
        session.commit()
    service = OpportunityIntelligenceService(factory, budget=LocalRequestBudget(tmp_path / "budget"))
    yield config, factory, identity, service
    factory.kw["bind"].dispose()


def prepare(service, identity, **changes):
    args = dict(question="Can I responsibly offer an editing fix?", mode="Focused", model="fixture-model", account_binding="a" * 64)
    args.update(changes)
    return service.prepare(identity, **args)


def execute(service, prepared, transport=None):
    return service.execute(prepared, transport or FakeTransport(), cancel=Event(), current_account=lambda: "a" * 64)


def test_real_worksheet_adoption_retains_human_text_and_reopens(setup):
    _, factory, identity, service = setup
    prepared = prepare(service, identity, include_worksheet=True)
    result = execute(service, prepared)
    with factory() as session:
        before = latest_worksheet(session, identity)
    new_id = service.adopt(result["run_id"], lead_id=identity, account_binding="a" * 64, item_id="q1", actor="Sammi",
                           edited_text="Which specific edit is blocked?")
    with factory() as session:
        after = latest_worksheet(session, identity)
        assert after["record_id"] == new_id != before["record_id"]
        assert after["data"]["owner_question"].startswith("Human question retained\nAI-assisted operator planning:")
        assert after["data"]["owner_reported"] is True  # original attribution retained, not created by advice
        assert after["data"]["finding_refs"] == []
        assert session.scalar(select(IntelligenceReview)).worksheet_id == new_id
        assert session.get(IntelligenceRun, result["run_id"]).body_json == canonical(prepared["body"])
    with pytest.raises(ValueError, match="stale"):
        service.adopt(result["run_id"], lead_id=identity, account_binding="a" * 64, item_id="q1", actor="Sammi", edited_text="Again")


def test_creation_cache_and_no_commercial_mutations(setup):
    _, factory, identity, service = setup
    with factory() as session:
        lead = session.get(Lead, identity)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        before = (lead.qualification_class, context.offer_id, context.scope, pricing.recommended, lead.verification_json)
    transport = FakeTransport()
    first = execute(service, prepare(service, identity), transport)
    second = execute(service, prepare(service, identity), transport)
    assert first["run_id"] == second["run_id"] and second["cached"] and transport.calls == 1
    with factory() as session:
        lead = session.get(Lead, identity)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        assert before == (lead.qualification_class, context.offer_id, context.scope, pricing.recommended, lead.verification_json)
        assert latest_worksheet(session, identity)["data"]["owner_question"] == "Human question retained"
    assert len(service.history(identity)) == 1


def test_owner_private_content_is_opt_in_and_no_raw_credentials(setup):
    _, factory, identity, service = setup
    secret = "SYNTHETIC-CONFIDENTIAL-OWNER-TEXT"
    with factory() as session:
        row = record_owner_need(session, identity, actor="Sammi", owner_label="Owner", source_text=secret,
                                source_ref="private fixture", source_text_mode="VERBATIM", attribution="OPERATOR_REPORTED_OWNER")
        session.commit()
    packet = prepare(service, identity)
    assert secret not in canonical(packet["body"])
    assert "I want easier editing" not in canonical(packet["body"])
    with factory() as session:
        from local_presence_miner.services.prospect_finding_service import project_findings
        reference = project_findings(session, identity)[0]["reference"]
    selected = prepare(service, identity, selected=[reference])
    assert secret in canonical(selected["body"])
    assert "access_token" not in canonical(packet["body"])
    assert row.id


def test_disputed_stale_unknown_and_cross_lead_fail_closed(setup):
    _, factory, identity, service = setup
    with factory() as session:
        row = capture_contact_finding(session, identity, "website.check.tap_to_call", actor="Sammi")
        revise_finding(session, identity, row.finding_key, expected_revision=1, review_state="DISPUTED", actor="Sammi", review_note="Unknown route")
        session.commit()
    from local_presence_miner.services.prospect_finding_service import project_findings
    with factory() as session:
        ref = project_findings(session, identity)[0]["reference"]
    packet = prepare(service, identity, selected=[ref])["packet"]
    assert packet["evidence"][0]["review_state"] == "DISPUTED"
    assert not packet["evidence"][0]["commercial_fact_eligible"]
    with pytest.raises(ValueError, match="belonging"):
        prepare(service, identity, selected=["finding_revision:999:unknown"])
    old = prepare(service, identity, selected=[ref], now=utc_now() + timedelta(days=40))
    assert old["packet"]["evidence"][0]["freshness"] != "CURRENT"


def test_rescan_or_concurrent_owner_evidence_blocks_dispatch(setup):
    _, factory, identity, service = setup
    prepared = prepare(service, identity)
    with factory() as session:
        record_owner_need(session, identity, actor="Sammi", owner_label="Owner", source_text="Changed request",
                          source_ref="synthetic revision", source_text_mode="VERBATIM", attribution="OPERATOR_REPORTED_OWNER")
        session.commit()
    transport = FakeTransport()
    with pytest.raises(ValueError, match="changed"):
        execute(service, prepared, transport)
    assert transport.calls == 0


@pytest.mark.parametrize("mutation", [lambda a: a.update(approved=True), lambda a: a.update(context_hash="0" * 64),
                                      lambda a: a["owner_questions"][0].update(evidence_ids=["foreign"]),
                                      lambda a: a.update(schema_version=99)])
def test_invalid_output_retained_as_failed_not_adoptable(setup, mutation):
    _, factory, identity, service = setup
    with pytest.raises(ValueError):
        execute(service, prepare(service, identity), FakeTransport(mutation))
    with factory() as session:
        assert session.scalar(select(IntelligenceResult)).status == "failed"
    with pytest.raises(ValueError):
        service.adopt(1, lead_id=identity, account_binding="a" * 64, item_id="q1", actor="Sammi", edited_text="Unsafe")


def test_preview_tampering_cancel_account_change_no_dispatch(setup):
    _, _, identity, service = setup
    packet = prepare(service, identity)
    packet["body"]["instructions"] += "Modified"
    with pytest.raises(ValueError, match="changed"):
        execute(service, packet)
    with pytest.raises(ValueError, match="account changed"):
        service.execute(prepare(service, identity), FakeTransport(), cancel=Event(), current_account=lambda: "other")
    cancel = Event()
    cancel.set()
    with pytest.raises(ValueError, match="cancelled"):
        service.execute(prepare(service, identity), FakeTransport(), cancel=cancel, current_account=lambda: "a" * 64)


def test_append_only_migration_integrity_and_wrong_worksheet(setup):
    _, factory, identity, service = setup
    result = execute(service, prepare(service, identity))
    initialize_database(factory)
    initialize_database(factory)
    with factory() as session:
        assert session.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    for sql in ("UPDATE opportunity_intelligence_runs SET model='changed'", "DELETE FROM opportunity_intelligence_results",
                f"DELETE FROM leads WHERE id={identity}"):
        with factory() as session, pytest.raises(IntegrityError):
            session.execute(text(sql))
    with pytest.raises(ValueError):
        service.adopt(result["run_id"], lead_id=identity + 1, account_binding="a" * 64, item_id="q1", actor="Sammi", edited_text="No")


def test_budget_restart_backwards_clock_and_exclusive_lock(tmp_path):
    budget = LocalRequestBudget(tmp_path / "usage", daily_limit=1)
    with budget.reserve(now=datetime(2026, 11, 9, tzinfo=UTC)), pytest.raises(ValueError, match="active"), LocalRequestBudget(tmp_path / "usage").reserve():
        pass
    with pytest.raises(ValueError, match="limit"), LocalRequestBudget(tmp_path / "usage", daily_limit=1).reserve(now=datetime(2026, 11, 9, tzinfo=UTC)):
        pass
    with pytest.raises(ValueError, match="backwards"), budget.reserve(now=datetime(2026, 11, 8, tzinfo=UTC)):
        pass


@pytest.mark.parametrize("mode", ["Focused", "Full Prospect", "Deep Investigation"])
def test_modes_are_one_tools_off_explicit_request(setup, mode):
    _, _, identity, service = setup
    packet = prepare(service, identity, mode=mode)
    assert packet["body"]["store"] is False and packet["body"]["stream"] is True
    assert "tools" not in packet["body"] and "max_output_tokens" not in packet["body"]
    validate_advice(canonical(advice_for(packet["packet"])), packet["packet"])


def test_computed_strategy_change_without_db_mutation_blocks_dispatch(setup, monkeypatch):
    import local_presence_miner.services.opportunity_intelligence_service as module
    _, _, identity, service = setup
    prepared = prepare(service, identity)
    monkeypatch.setattr(module, "project_owner_strategy", lambda *a: {"state": "unknown", "unknowns": ["Natural evidence expiry"]})
    transport = FakeTransport()
    with pytest.raises(ValueError, match="changed"):
        execute(service, prepared, transport)
    assert transport.calls == 0


def test_corrupt_finding_contributes_diagnostic_without_its_claim(setup, monkeypatch):
    import local_presence_miner.services.opportunity_intelligence_service as module
    _, _, identity, service = setup
    corrupt = {"reference": "finding_revision:invalid:hash", "finding_type": "manual_owner_need", "valid": False,
               "claim": "UNTRUSTWORTHY-CLAIM", "inference": "UNTRUSTWORTHY-INFERENCE", "freshness": "UNKNOWN", "review_state": "UNKNOWN"}
    monkeypatch.setattr(module, "project_findings", lambda *a, **k: [corrupt])
    packet = prepare(service, identity, selected=[corrupt["reference"]])
    assert "UNTRUSTWORTHY" not in canonical(packet["body"])
    assert "corrupt" in canonical(packet["body"])


def test_review_actions_preserved_and_limits_persist(setup):
    _, _, identity, service = setup
    result = execute(service, prepare(service, identity))
    service.review(result["run_id"], lead_id=identity, account_binding="a"*64, actor="Sammi", action="rejected")
    assert service.history(identity)[0]["reviews"][0]["review"]["action"] == "rejected"
    service.budget.set_limit(3)
    assert LocalRequestBudget(service.budget.directory).daily_limit == 3


def test_actual_proposal_call_guide_and_outreach_unchanged(setup):
    from local_presence_miner.config import SenderInfo
    from local_presence_miner.services.call_guide_service import CallGuideService
    from local_presence_miner.services.outreach_service import OutreachService
    from local_presence_miner.services.proposal_service import ProposalService
    config, factory, identity, service = setup
    def outputs():
        with factory() as session:
            lead = session.get(Lead, identity)
            plan, pricing, _ = build_adaptive_sales_plan_with_context(session, lead)
            proposal = ProposalService(config).generate_proposal(session, lead, selected_price=350).read_text(encoding="utf-8")
            guide = CallGuideService().build(session, lead, [])
            drafts = OutreachService(SenderInfo(name="Sammi")).generate_all(lead, session=session, adaptive_plan=plan, pricing=pricing)
            return proposal, guide.opening_15s, str(drafts)
    before = outputs()
    execute(service, prepare(service, identity))
    assert outputs() == before


def test_interrupted_run_is_reconciled_without_repeating_request(setup):
    _, factory, identity, service = setup
    prepared = prepare(service, identity)
    with factory() as session:
        old = IntelligenceRun(lead_id=identity, account_binding="a"*64, model=prepared["model"], packet_json=canonical(prepared["packet"]),
                              body_json=canonical(prepared["body"]),context_hash=prepared["packet"]["context_hash"],
                              state_hash=prepared["state_hash"], cache_key=prepared["cache_key"])
        session.add(old)
        session.flush()
        old_id = old.id
        session.commit()
    transport = FakeTransport()
    execute(service, prepared, transport)
    assert transport.calls == 1
    with factory() as session:
        result = session.scalar(select(IntelligenceResult).where(IntelligenceResult.run_id==old_id))
        assert result.status == "interrupted" and json.loads(result.response_json)["usage"] is None


def test_context_evidence_can_be_cited_without_becoming_factual_proof(setup):
    _, _, identity, service = setup
    packet=prepare(service,identity,include_worksheet=True)["packet"]
    advice=advice_for(packet)
    advice["owner_questions"][0]["evidence_ids"]=[packet["worksheet"]["evidence_id"],packet["delivery_context"]["evidence_id"]]
    assert validate_advice(canonical(advice),packet)["status"]=="insufficient_evidence"
