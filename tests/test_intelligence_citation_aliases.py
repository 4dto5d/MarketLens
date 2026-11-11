"""Short citation labels must preserve exact provenance and fail-closed binding."""
import json
from copy import deepcopy

import pytest
from test_opportunity_intelligence import FakeTransport, advice_for, execute, prepare
from test_opportunity_intelligence import setup as setup_fixture

from local_presence_miner.database.opportunity_intelligence_repository import IntelligenceResult, IntelligenceRun
from local_presence_miner.domain.opportunity_intelligence import VERSION, canonical, digest, request_body, validate_advice
from local_presence_miner.services.prospect_finding_service import capture_contact_finding, project_findings


@pytest.fixture(name="setup")
def storage(tmp_path):
    yield from setup_fixture.__wrapped__(tmp_path)


def test_context_citations_are_short_without_replacing_integrity_hashes(setup):
    _, _, identity, service = setup
    packet = prepare(service, identity, include_worksheet=True)["packet"]
    for section in ("worksheet", "owner_context", "commercial_context", "delivery_context"):
        assert packet[section]["evidence_id"] == section
    assert len(packet["context_hash"]) == 64
    assert packet["policy_version"] == VERSION


def test_finding_alias_keeps_canonical_revision_and_source_hash(setup):
    _, factory, identity, service = setup
    with factory() as session:
        capture_contact_finding(session, identity, "website.check.tap_to_call", actor="Sammi")
        session.commit()
    with factory() as session:
        finding = project_findings(session, identity)[0]
    packet = prepare(service, identity, selected=[finding["reference"]])["packet"]
    assert packet["evidence"][0]["id"] == "F1"
    assert packet["evidence"][0]["reference"] == finding["reference"]
    assert packet["evidence"][0]["source_sha256"] == finding["source_sha256"]
    assert packet["coverage"]["findings"][0]["reference"] == finding["reference"]


def test_prompt_schema_enumerates_only_packet_local_labels(setup):
    _, _, identity, service = setup
    prepared = prepare(service, identity)
    instructions = prepared["body"]["instructions"]
    schema = json.loads(instructions.split("matching this schema: ", 1)[1])
    expected = ["commercial_context", "delivery_context", "market_context", "operator_context", "owner_context", "worksheet"]
    fields = [definition["properties"]["evidence_ids"] for definition in schema["$defs"].values()
              if "evidence_ids" in definition.get("properties", {})]
    assert fields and all(field["items"]["enum"] == expected for field in fields)


@pytest.mark.parametrize("reference", ["delivery_context:3d7ecb82896a73129a916355fb6bc5af2023435bfc0a7be8024ef996b5cc0a7be8024ef996b5cc0bbf",
                                      "delivery_contex", "F999", "worksheet.record_id"])
def test_unrecognized_citations_still_fail_without_fuzzy_repair(setup, reference):
    _, _, identity, service = setup
    packet = prepare(service, identity)["packet"]
    answer = advice_for(packet)
    answer["owner_questions"][0]["evidence_ids"] = [reference]
    with pytest.raises(ValueError, match="outside this packet") as error:
        validate_advice(canonical(answer), packet)
    assert error.value.code == "invalid_citation"


def test_valid_short_citation_can_be_adopted_with_original_finding_binding(setup):
    _, factory, identity, service = setup
    with factory() as session:
        capture_contact_finding(session, identity, "website.check.tap_to_call", actor="Sammi")
        session.commit()
    with factory() as session:
        ref = project_findings(session, identity)[0]["reference"]
    result = execute(service, prepare(service, identity, selected=[ref]), FakeTransport(
        lambda answer: answer["owner_questions"][0].update(evidence_ids=["F1", "worksheet"])))
    assert service.adopt(result["run_id"], lead_id=identity, account_binding="a" * 64, item_id="q1", actor="Sammi",
                         edited_text="Which path should we confirm?")
    with factory() as session:
        packet = json.loads(session.get(IntelligenceRun, result["run_id"]).packet_json)
        assert packet["evidence"][0]["reference"] == ref


def test_changed_context_rejects_answer_even_when_short_labels_match(setup):
    _, _, identity, service = setup
    one = prepare(service, identity, question="First question")["packet"]
    two = prepare(service, identity, question="Different question")["packet"]
    answer = advice_for(one)
    answer["owner_questions"][0]["evidence_ids"] = ["worksheet"]
    with pytest.raises(ValueError, match="different context"):
        validate_advice(canonical(answer), two)


@pytest.mark.parametrize("old_policy", ["opportunity-advice.v1", "opportunity-advice.v2"])
def test_old_policy_cannot_dispatch_or_adopt_but_history_is_preserved(setup, old_policy):
    _, factory, identity, service = setup
    prepared = prepare(service, identity)
    old = deepcopy(prepared)
    old["packet"]["policy_version"] = old_policy
    old["body"] = request_body(old["packet"], old["model"])
    old["preview_hash"] = digest(old["body"])
    transport = FakeTransport()
    with pytest.raises(ValueError, match="interpretation changed"):
        execute(service, old, transport)
    assert transport.calls == 0
    with factory() as session:
        run = IntelligenceRun(lead_id=identity, account_binding="a" * 64, model="fixture-model", packet_json=canonical(old["packet"]),
                              body_json=canonical(old["body"]), context_hash=old["packet"]["context_hash"],
                              state_hash=prepared["state_hash"], cache_key="old-policy")
        session.add(run)
        session.flush()
        run_id = run.id
        text = canonical(advice_for(old["packet"]))
        session.add(IntelligenceResult(run_id=run_id, status="completed", response_json=canonical({"text": text})))
        session.commit()
    with pytest.raises(ValueError, match="interpretation changed"):
        service.adopt(run_id, lead_id=identity, account_binding="a" * 64, item_id="q1", actor="Sammi", edited_text="Never silently accept")
    assert service.history(identity)[0]["packet"]["policy_version"] == old_policy
    assert VERSION == "opportunity-advice.v4"
