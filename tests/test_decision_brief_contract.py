"""Decision support checks do not turn fluent model prose into evidence."""
from copy import deepcopy
from threading import Event

import pytest
from test_chatgpt_inference import HTTP, Auth, Stream, body
from test_opportunity_intelligence import advice_for

from local_presence_miner.domain.opportunity_intelligence import (
    VERSION,
    canonical,
    present_advice,
    request_body,
    supported_efforts,
    validate_advice,
)
from local_presence_miner.services.chatgpt_inference_service import ChatGPTInference


def packet():
    return {"mode": "Focused", "question": "Can I perform the exact task?", "context_hash": "a" * 64, "evidence": [],
            "worksheet": {"evidence_id": "worksheet"},
            "delivery_context": {"evidence_id": "delivery_context", "ready_for_payment": False},
            "source_registry": {}, "policy_version": VERSION}


def positive_advice(context):
    advice = advice_for(context)
    advice["summary"] = "Synthetic overconfident output, not a provider response."
    advice["status"] = "advisory"
    for readiness in advice["feasibility"].values():
        readiness.update(assessment="appears_supported", evidence_ids=[], assumptions=[], missing_prerequisites=[])
    advice["decision_review"] = {"recommendation": "Investigate first", "evidence_ids": [],
                                 "intended_use": "internal_verification", "evidence_use": "uncertainty",
                                 "action_kind": "internal_verification",
                                 "decisive_unknown": "Exact task", "would_change_if": "Provider can solve it"}
    return advice


def test_unsupported_readiness_and_numeric_effort_are_not_presented_as_supported():
    context = packet()
    raw = positive_advice(context)
    raw["effort_uncertainty"] = [{"task": "Migration", "missing_driver": "Unknown platform", "assumptions": [],
                                 "hours_low": 2.0, "hours_high": 3.0, "rationale": "Unsupported model invention"}]
    structural = validate_advice(canonical(raw), context)
    before = deepcopy(structural)
    shown = present_advice(structural, context)
    assert structural == before  # Original text, ranges and classifications remain inspectable.
    assert shown["feasibility"]["operator"]["assessment"] == "unknown"
    assert shown["feasibility"]["execution"]["assessment"] == "blocked"
    assert shown["effort_uncertainty"][0]["hours_low"] is None
    assert shown["effort_uncertainty"][0]["hours_high"] is None
    assert shown["status"] == "insufficient_evidence" and shown["support_diagnostics"]
    assert "overconfident" not in shown["summary"]


@pytest.mark.parametrize("source", [
    {"eligible": False, "supports": ["operator"]},  # disputed/stale/corrupt source
    {"eligible": True, "supports": []},  # right ID but wrong source applicability
    {"eligible": True, "supports": ["technical"]},
    {"eligible": True, "supports": ["operator"], "support_allowed": False},
])
def test_valid_citation_membership_alone_cannot_establish_operator_readiness(source):
    context = packet()
    context["source_registry"] = {"operator_context": source}
    context["operator_context"] = {"evidence_id": "operator_context", "experience": "Self-reported experience",
                                   "demonstration": "Self-reported example"}
    raw = positive_advice(context)
    raw["feasibility"]["operator"]["evidence_ids"] = ["operator_context"]
    validated = validate_advice(canonical(raw), context)
    shown = present_advice(validated, context)
    assert shown["feasibility"]["operator"]["assessment"] != "appears_supported"


def test_explicit_applicable_operator_evidence_retains_self_report_qualification():
    context = packet()
    context["source_registry"] = {"operator_context": {"eligible": True, "supports": ["operator"]}}
    context["operator_context"] = {"evidence_id": "operator_context", "experience": "Built a sample on exact tool",
                                   "demonstration": "Synthetic sample record, operator attested",
                                   "experience_state": "affirmative", "demonstration_state": "affirmative",
                                   "task_scope": context["question"]}
    raw = positive_advice(context)
    raw["feasibility"]["operator"]["evidence_ids"] = ["operator_context"]
    shown = present_advice(validate_advice(canonical(raw), context), context)
    assessment = shown["feasibility"]["operator"]
    assert assessment["assessment"] == "appears_supported"
    assert any("self-reported" in text for text in assessment["assumptions"])
    context["operator_context"]["demonstration"] = ""
    assert present_advice(raw, context)["feasibility"]["operator"]["assessment"] != "appears_supported"


def test_legacy_answer_has_explicit_missing_decision_review_diagnostic():
    context = packet() | {"policy_version": "opportunity-advice.v3"}
    legacy = advice_for(context) | {"schema_version": 1}
    shown = present_advice(validate_advice(canonical(legacy), context), context)
    assert shown["decision_review"] is None
    assert any("Decision review missing" in text for text in shown["support_diagnostics"])
    assert shown["owner_questions"] == shown["next_actions"] == []
    assert shown["status"] == "insufficient_evidence"


def test_decision_review_unknown_citation_is_rejected_without_fuzzy_repair():
    context = packet()
    raw = positive_advice(context)
    raw["decision_review"]["evidence_ids"] = ["foreign-prospect"]
    with pytest.raises(ValueError, match="outside this packet"):
        validate_advice(canonical(raw), context)


def test_modes_define_different_decision_tasks_without_automatic_research():
    bodies = [request_body(packet() | {"mode": mode}, "gpt-6.1-sol")
              for mode in ("Focused", "Full Prospect", "Deep Investigation")]
    assert len({value["instructions"] for value in bodies}) == 3
    assert "one operator decision" in bodies[0]["instructions"]
    assert "current-provider and no-sale" in bodies[1]["instructions"]
    assert "Try to disprove" in bodies[2]["instructions"]
    assert all("tools" not in value and "reasoning" not in value for value in bodies)


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-astra"])
def test_explicit_effort_is_in_exact_request_and_supported_transport(model):
    selected = request_body(packet() | {"reasoning_effort": "high"}, model)
    assert selected["reasoning"] == {"effort": "high"}
    assert "high" in supported_efforts(model)
    http = HTTP(Stream([{"type": "response.output_text.delta", "delta": "{}"},
                        {"type": "response.completed", "response": {"status": "completed"}}]))
    ChatGPTInference(Auth(), http=http).run(selected, Event(), 5, 100)
    assert len(http.calls) == 1


@pytest.mark.parametrize("model,effort", [("unknown-catalog-model", "high"), ("gpt-6.1-sol", "none"),
                                          ("gpt-6-astra", "invented"), ("gpt-6.1-sol", True)])
def test_unsupported_model_effort_does_not_silently_fallback(model, effort):
    with pytest.raises(ValueError, match="Unsupported"):
        request_body(packet() | {"reasoning_effort": effort}, model)


@pytest.mark.parametrize("configuration", [{"effort": "high"}, {"effort": None}, {"effort": "medium", "extra": 1}])
def test_transport_rejects_unsupported_effort_before_auth_or_network(configuration):
    http = HTTP(Stream())
    with pytest.raises(ValueError, match="Unsupported"):
        ChatGPTInference(Auth(), http=http).run(body() | {"reasoning": configuration}, Event(), 5, 100)
    assert not http.calls
