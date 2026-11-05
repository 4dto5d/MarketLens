"""Owner-confirmed preferences on the existing append-only assertion ledger."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import ConversationAssertion, Lead
from local_presence_miner.domain.commercial import canonical_json
from local_presence_miner.domain.enums import AssertionConfidence, AssertionSourceKind, AssertionSourceTextMode, AssertionState
from local_presence_miner.domain.owner_strategy import OWNER_STRATEGY_VERSION, conflicting_owner_constraints, validate_owner_strategy
from local_presence_miner.services.conversation_state_service import ConversationStateService

SUBJECT_OWNER_STRATEGY = "owner.strategy"


def append_owner_strategy(
    session: Session, lead: Lead, payload: dict, *, source_text: str,
    source_text_mode: AssertionSourceTextMode | str = AssertionSourceTextMode.VERBATIM,
    owner_confirmed: bool = False, interaction_id: int | None = None,
    supersedes_assertion_id: int | None = None, correction_reason: str = "", actor_id: str = "",
) -> ConversationAssertion:
    normalized = validate_owner_strategy(payload)
    if not isinstance(source_text, str) or not source_text.strip() or len(source_text) > 16000:
        raise ValueError("Owner strategy requires the original owner statement or explicitly identified paraphrase.")
    if type(owner_confirmed) is not bool:
        raise ValueError("Owner confirmation must be explicit.")
    if supersedes_assertion_id is not None and not correction_reason.strip():
        raise ValueError("Owner strategy corrections require a recorded reason.")
    row = ConversationStateService().append_assertion(
        session, lead, subject_key=SUBJECT_OWNER_STRATEGY, value=normalized,
        source_kind=AssertionSourceKind.OWNER_LITERAL if owner_confirmed else AssertionSourceKind.OPERATOR_INTERPRETATION,
        confidence=AssertionConfidence.CONFIRMED if owner_confirmed else AssertionConfidence.TENTATIVE,
        source_text=source_text, source_text_mode=source_text_mode, interaction_id=interaction_id,
        supersedes_assertion_id=supersedes_assertion_id, correction_reason=correction_reason, actor_id=actor_id,
    )
    from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

    recompute_lead_commercial_candidate(session, lead, "Recorded owner strategy changed")
    return row


def _empty(state: str = "unknown", reason: str = "Owner preferences for the exact scope require confirmation.") -> dict[str, Any]:
    return {"schema_version": OWNER_STRATEGY_VERSION, "state": state, "constraints": [], "target_territories": [],
            "territory_mode": "preferred", "evidence_refs": [], "revision": 0, "assertion_id": None,
            "provenance": [], "unknowns": [reason]}


def _provenance(row: ConversationAssertion) -> dict[str, Any]:
    return {"assertion_id": row.id, "interaction_id": row.interaction_id, "source_kind": row.source_kind,
            "confidence": row.confidence, "source_text": row.source_text, "source_text_mode": row.source_text_mode,
            "created_at": row.created_at.isoformat() if row.created_at else "", "actor_id": row.actor_id,
            "supersedes_assertion_id": row.supersedes_assertion_id, "correction_reason": row.correction_reason,
            "assertion_state": row.assertion_state}


def _decode(value: str) -> object:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate owner strategy field.")
            result[key] = item
        return result

    def invalid_number(_value):
        raise ValueError("Nonfinite values are not owner preferences.")

    if len(value.encode("utf-8")) > 100000:
        raise ValueError("Owner strategy exceeds the supported size.")
    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_number)


def project_owner_strategy(session: Session, lead: Lead) -> dict[str, Any]:
    all_rows = list(session.scalars(select(ConversationAssertion).where(
        ConversationAssertion.lead_id == lead.id,
        ConversationAssertion.subject_key.in_({SUBJECT_OWNER_STRATEGY, "business.goal", "business.capacity"}),
    ).order_by(ConversationAssertion.id)))
    superseded_all = {row.supersedes_assertion_id for row in all_rows if row.supersedes_assertion_id is not None}
    legacy_context = {}
    for field, subject in (("goal", "business.goal"), ("capacity", "business.capacity")):
        active = [row for row in all_rows if row.subject_key == subject and row.id not in superseded_all
                  and row.assertion_state == AssertionState.ACTIVE.value]
        if not active:
            continue
        try:
            texts = [json.loads(row.value_json) for row in active]
        except (ValueError, TypeError):
            texts = []
        latest = active[-1]
        legacy_context[field] = {**_provenance(latest), "value": texts[-1] if texts and isinstance(texts[-1], str) else "",
                                 "evidence_refs": [f"owner_assertion:{row.id}:{row.assertion_uid}" for row in active],
                                 "confirmed_owner": bool(texts) and len(set(str(value) for value in texts)) == 1
                                 and latest.source_kind == AssertionSourceKind.OWNER_LITERAL.value
                                 and latest.confidence == AssertionConfidence.CONFIRMED.value
                                 and bool(latest.source_text.strip())
                                 and latest.source_text_mode in {AssertionSourceTextMode.VERBATIM.value, AssertionSourceTextMode.PARAPHRASED.value}}
    rows = [row for row in all_rows if row.subject_key == SUBJECT_OWNER_STRATEGY]
    if not rows:
        return {**_empty(), "legacy_context": legacy_context}
    superseded = {row.supersedes_assertion_id for row in rows if row.supersedes_assertion_id is not None}
    current = [row for row in rows if row.id not in superseded]
    base = _empty()
    base["legacy_context"] = legacy_context
    base.update(revision=max(row.id for row in rows), provenance=[_provenance(row) for row in current],
                evidence_refs=[f"owner_assertion:{row.id}:{row.assertion_uid}" for row in current],
                current_assertion_ids=[row.id for row in current])
    by_id = {row.id: row for row in rows}
    for row in rows:
        if row.supersedes_assertion_id is not None and (
            row.supersedes_assertion_id not in by_id or row.supersedes_assertion_id >= row.id or not row.correction_reason.strip()
        ):
            return {**base, "state": "invalid", "unknowns": ["Owner correction chain is invalid; no previous approval is assumed."]}
    if not current:
        return {**base, "state": "invalid", "unknowns": ["Owner correction history has no valid current assertion."]}
    active = [row for row in current if row.assertion_state == AssertionState.ACTIVE.value]
    if not active:
        return {**base, "state": "unknown", "unknowns": ["Owner strategy was cleared, resolved or marked unknown; prior preferences are history."]}
    try:
        values = [validate_owner_strategy(_decode(row.value_json)) for row in active]
    except (ValueError, TypeError, RecursionError):
        return {**base, "state": "invalid", "unknowns": ["Current owner strategy is corrupt or unsupported; previous success is not reused."]}
    if (len({canonical_json(value) for value in values}) != 1 or len(active) != len(current)
            or any(conflicting_owner_constraints(value) for value in values)):
        return {**base, "state": "ambiguous", "unknowns": ["Multiple current owner instructions conflict; an explicit correction is required."]}
    latest = active[-1]
    confirmed = all(row.source_kind == AssertionSourceKind.OWNER_LITERAL.value
                    and row.confidence == AssertionConfidence.CONFIRMED.value and bool(row.source_text.strip())
                    and row.source_text_mode in {AssertionSourceTextMode.VERBATIM.value, AssertionSourceTextMode.PARAPHRASED.value}
                    for row in active)
    return {**base, **values[-1], "assertion_id": latest.id, "state": "confirmed" if confirmed else "unconfirmed",
            "unknowns": [] if confirmed else ["Strategy lacks explicit confirmed owner provenance; request validation."]}


def owner_strategy_history(session: Session, lead_id: int) -> list[dict[str, Any]]:
    """Inspect original wording and correction records without rewriting them."""
    rows = session.scalars(select(ConversationAssertion).where(
        ConversationAssertion.lead_id == lead_id, ConversationAssertion.subject_key == SUBJECT_OWNER_STRATEGY,
    ).order_by(ConversationAssertion.id))
    return [{**_provenance(row), "value_json": row.value_json} for row in rows]
