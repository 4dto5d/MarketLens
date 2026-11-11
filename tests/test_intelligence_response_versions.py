"""Response versions are bound to the originating request, including stored results."""
import json
from copy import deepcopy

import pytest
from sqlalchemy import select
from test_opportunity_intelligence import FakeTransport, advice_for, execute, prepare
from test_opportunity_intelligence import setup as base_setup

from local_presence_miner.database.opportunity_intelligence_repository import IntelligenceResult, IntelligenceRun
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.opportunity_intelligence import canonical, digest, validate_advice
from local_presence_miner.ui.widgets.opportunity_intelligence_widget import readable_advice


@pytest.fixture(name="setup")
def version_fixture(tmp_path):
    yield from base_setup.__wrapped__(tmp_path)


def old_response(packet):
    value = advice_for(packet)
    value.update(schema_version=1, decision_review={
        "recommendation": "Call this owner now and sell the repair.", "evidence_ids": ["market_context"],
        "decisive_unknown": "None", "would_change_if": "Never"})
    value["feasibility"]["execution"]["assessment"] = "blocked"
    return value


def stored_result(factory, prepared, packet, value):
    with factory() as session:
        row = IntelligenceRun(lead_id=prepared["lead_id"], account_binding=prepared["account_binding"],
            model=prepared["model"], packet_json=canonical(packet), body_json=canonical(prepared["body"]),
            context_hash=packet["context_hash"], state_hash=prepared["state_hash"], cache_key=prepared["cache_key"])
        session.add(row)
        session.flush()
        session.add(IntelligenceResult(run_id=row.id, status="completed", response_json=canonical({"text": canonical(value)})))
        identity = row.id
        session.commit()
    return identity


def test_current_mismatched_completion_is_raw_failed_and_unavailable(setup):
    _, factory, identity, service = setup
    with factory() as session:
        session.get(Lead, identity).suppressed = True
        session.commit()
    preview = prepare(service, identity)
    def legacy(value):
        value.clear()
        value.update(old_response(preview["packet"]))
    transport = FakeTransport(legacy)
    with pytest.raises(ValueError, match="version"):
        execute(service, preview, transport)
    assert transport.calls == 1
    history = service.history(identity)[0]
    assert history["status"] == "failed" and not history["eligibility"]["current"]
    assert history["advice"] is None
    assert "Call this owner" in history["result"]["text"]
    with pytest.raises(ValueError):
        service.adopt(history["id"], lead_id=identity, account_binding="a"*64,
                      item_id="q1", actor="Synthetic operator", edited_text="Obsolete advice")
    fresh = execute(service, prepare(service, identity))
    assert not fresh["cached"] and fresh["advice"]["schema_version"] == 2
    assert "Call this owner" not in readable_advice(fresh["advice"], fresh["packet"])


def test_already_stored_mismatch_remains_raw_but_cannot_poison_cache(setup):
    _, factory, identity, service = setup
    preview = prepare(service, identity)
    old_id = stored_result(factory, preview, preview["packet"], old_response(preview["packet"]))
    with factory() as session:
        before = session.scalar(select(IntelligenceResult.response_json).where(IntelligenceResult.run_id == old_id))
    row = service.history(identity)[0]
    assert not row["eligibility"]["current"] and row["advice"] is None
    with pytest.raises(ValueError, match="version"):
        service.adopt(old_id, lead_id=identity, account_binding="a"*64,
                      item_id="q1", actor="Synthetic operator", edited_text="No reuse")
    transport = FakeTransport()
    fresh = execute(service, preview, transport)
    assert not fresh["cached"] and fresh["run_id"] != old_id and transport.calls == 1
    cached = execute(service, prepare(service, identity), transport)
    assert cached["cached"] and cached["run_id"] == fresh["run_id"] and transport.calls == 1
    with factory() as session:
        assert session.scalar(select(IntelligenceResult.response_json).where(IntelligenceResult.run_id == old_id)) == before


@pytest.mark.parametrize("policy", ["opportunity-advice.v1", "opportunity-advice.v2", "opportunity-advice.v3"])
def test_genuine_older_packet_is_retained_inspectable_and_noncurrent(setup, policy):
    _, factory, identity, service = setup
    preview = prepare(service, identity)
    packet = deepcopy(preview["packet"])
    packet.update(policy_version=policy, schema_version=1)
    packet["context_hash"] = digest({k:v for k,v in packet.items() if k != "context_hash"})
    raw = old_response(packet)
    stored_result(factory, preview, packet, raw)
    row = service.history(identity)[0]
    assert row["packet"]["policy_version"] == policy
    assert json.loads(row["result"]["text"]) == raw
    assert row["advice"]["schema_version"] == 1
    assert not row["eligibility"]["current"]
    with pytest.raises(ValueError, match="interpretation"):
        service.adopt(row["id"], lead_id=identity, account_binding="a"*64,
                      item_id="q1", actor="Synthetic operator", edited_text="Historical only")


def test_legacy_parser_is_not_available_to_an_unknown_or_current_policy():
    packet = {"mode":"Focused", "context_hash":"a"*64, "evidence":[],
              "source_registry":{"market_context":{}}, "policy_version":"opportunity-advice.future"}
    with pytest.raises(ValueError, match="version"):
        validate_advice(canonical(old_response(packet)), packet)
