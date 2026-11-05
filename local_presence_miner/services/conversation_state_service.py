from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import ContactInteraction, ConversationAssertion, Lead
from local_presence_miner.domain.enums import (
    AssertionConfidence,
    AssertionSourceKind,
    AssertionSourceTextMode,
    AssertionState,
)

SEMANTIC_CAPTURE_VERSION = "v0115_b1"

SUBJECT_CONTACT_NAME = "contact.name"
SUBJECT_CONTACT_ROLE = "contact.role"
SUBJECT_AUTHORITY = "contact.authority"
SUBJECT_BUSINESS_GOAL = "business.goal"
SUBJECT_CAPACITY = "business.capacity"
SUBJECT_OWNER_STRATEGY = "owner.strategy"
SUBJECT_DELIVERY_PACKET = "delivery.packet"
SUBJECT_SALES_EVIDENCE_REVIEW = "sales.evidence_review"
SUBJECT_BUYER_QUESTION = "buyer.question"
SUBJECT_OBJECTION = "buyer.objection"
SUBJECT_COMMITMENT = "buyer.commitment"
SUBJECT_NEXT_ACTION = "next_action"
SUBJECT_FOLLOW_UP_PERMISSION = "follow_up.permission"
SUBJECT_DISPOSITION = "commercial.disposition"
SUBJECT_CONCERN_CREDIBILITY = "concern.credibility"
SUBJECT_CONCERN_EXAMPLES = "concern.examples"
SUBJECT_CONCERN_REFERENCES = "concern.references"
SUBJECT_CONCERN_AI = "concern.ai"
SUBJECT_CONCERN_PROOF = "concern.proof"
SUBJECT_CONCERN_EXPERIENCE = "concern.experience"
SUBJECT_CONCERN_LOCALITY = "concern.locality"
SUBJECT_CONCERN_DECISION_MAKER_SKEPTICISM = "concern.decision_maker_skepticism"
SUBJECT_CONCERN_LEGITIMACY = "concern.legitimacy"

CONTROLLED_SUBJECTS = frozenset(
    {
        SUBJECT_CONTACT_NAME,
        SUBJECT_CONTACT_ROLE,
        SUBJECT_AUTHORITY,
        SUBJECT_BUSINESS_GOAL,
        SUBJECT_CAPACITY,
        SUBJECT_OWNER_STRATEGY,
        SUBJECT_DELIVERY_PACKET,
        SUBJECT_SALES_EVIDENCE_REVIEW,
        SUBJECT_BUYER_QUESTION,
        SUBJECT_OBJECTION,
        SUBJECT_COMMITMENT,
        SUBJECT_NEXT_ACTION,
        SUBJECT_FOLLOW_UP_PERMISSION,
        SUBJECT_DISPOSITION,
        SUBJECT_CONCERN_CREDIBILITY,
        SUBJECT_CONCERN_EXAMPLES,
        SUBJECT_CONCERN_REFERENCES,
        SUBJECT_CONCERN_AI,
        SUBJECT_CONCERN_PROOF,
        SUBJECT_CONCERN_EXPERIENCE,
        SUBJECT_CONCERN_LOCALITY,
        SUBJECT_CONCERN_DECISION_MAKER_SKEPTICISM,
        SUBJECT_CONCERN_LEGITIMACY,
    }
)

MULTI_VALUE_SUBJECTS = frozenset({SUBJECT_BUYER_QUESTION, SUBJECT_OBJECTION, SUBJECT_COMMITMENT})

CONCERN_SUBJECT_TO_FIELD = {
    SUBJECT_CONCERN_CREDIBILITY: "credibility_concern",
    SUBJECT_CONCERN_EXAMPLES: "wants_examples",
    SUBJECT_CONCERN_REFERENCES: "wants_references",
    SUBJECT_CONCERN_AI: "concerned_about_ai",
    SUBJECT_CONCERN_PROOF: "wants_proof",
    SUBJECT_CONCERN_EXPERIENCE: "seller_experience_question",
    SUBJECT_CONCERN_LOCALITY: "local_presence_question",
    SUBJECT_CONCERN_DECISION_MAKER_SKEPTICISM: "decision_maker_skeptical",
    SUBJECT_CONCERN_LEGITIMACY: "legitimacy_concern",
}

SINGLE_FIELD_TO_SUBJECT = {
    "contact_name": SUBJECT_CONTACT_NAME,
    "contact_role": SUBJECT_CONTACT_ROLE,
    "decision_maker_status": SUBJECT_AUTHORITY,
    "business_goal": SUBJECT_BUSINESS_GOAL,
    "capacity_status": SUBJECT_CAPACITY,
    "next_action": SUBJECT_NEXT_ACTION,
}

LIST_FIELD_TO_SUBJECT = {
    "buyer_questions": SUBJECT_BUYER_QUESTION,
    "objections": SUBJECT_OBJECTION,
    "commitments": SUBJECT_COMMITMENT,
}


@dataclass(frozen=True)
class ConversationState:
    contact_name: str = ""
    contact_role: str = ""
    decision_maker_status: str = "Unknown"
    business_goal: str = ""
    capacity_status: str = ""
    buyer_questions: tuple[str, ...] = ()
    objections: tuple[str, ...] = ()
    commitments: tuple[str, ...] = ()
    branch_path: tuple[str, ...] = ()
    next_action: str = ""
    last_outcome: str = ""
    interaction_count: int = 0
    credibility_concern: bool = False
    wants_examples: bool = False
    wants_references: bool = False
    concerned_about_ai: bool = False
    wants_proof: bool = False
    seller_experience_question: bool = False
    local_presence_question: bool = False
    decision_maker_skeptical: bool = False
    legitimacy_concern: bool = False
    ambiguous_subjects: tuple[str, ...] = ()
    legacy_history_present: bool = False
    assertion_revision: int = 0

    @property
    def has_history(self) -> bool:
        return self.interaction_count > 0

    @property
    def requires_clarification(self) -> bool:
        return bool(self.ambiguous_subjects)


class ConversationStateService:
    """Append/correct conversation assertions and project current truth.

    Canonical assertions are ordered by recording sequence (their primary key),
    not by a possibly backdated encounter time. Legacy ContactInteraction fields
    remain historical compatibility data and never become active current truth
    merely because they were once recorded.
    """

    def append_assertion(
        self,
        session: Session,
        lead: Lead,
        *,
        subject_key: str,
        value: Any = None,
        assertion_state: AssertionState | str = AssertionState.ACTIVE,
        source_kind: AssertionSourceKind | str = AssertionSourceKind.OPERATOR_OBSERVATION,
        confidence: AssertionConfidence | str = AssertionConfidence.CONFIRMED,
        interaction_id: int | None = None,
        source_text: str = "",
        source_text_mode: AssertionSourceTextMode | str = AssertionSourceTextMode.NOT_RECORDED,
        supersedes_assertion_id: int | None = None,
        actor_id: str = "",
        correction_reason: str = "",
        supersede_current: bool = False,
    ) -> ConversationAssertion:
        if subject_key not in CONTROLLED_SUBJECTS:
            raise ValueError(f"Unsupported conversation assertion subject: {subject_key!r}")
        state = self._enum_value(AssertionState, assertion_state, "assertion state")
        source = self._enum_value(AssertionSourceKind, source_kind, "assertion source")
        certainty = self._enum_value(AssertionConfidence, confidence, "assertion confidence")
        text_mode = self._enum_value(AssertionSourceTextMode, source_text_mode, "source text mode")
        clean_source_text = source_text.strip()
        if not clean_source_text:
            text_mode = AssertionSourceTextMode.NOT_RECORDED.value
        elif text_mode == AssertionSourceTextMode.NOT_RECORDED.value:
            raise ValueError("Recorded source text must be explicitly marked VERBATIM or PARAPHRASED.")
        if interaction_id is not None:
            interaction = session.get(ContactInteraction, interaction_id)
            if interaction is None or interaction.lead_id != lead.id:
                raise ValueError("Conversation assertion interaction does not belong to this lead.")

        if supersedes_assertion_id is None and supersede_current and subject_key not in MULTI_VALUE_SUBJECTS:
            current = self._unsuperseded_active(session, lead.id, subject_key)
            distinct = self._distinct_values(current)
            if len(distinct) == 1 and current:
                # If duplicate identical current assertions exist, superseding the
                # newest one is conservative; the projection stays unchanged.
                supersedes_assertion_id = current[-1].id
            elif len(distinct) > 1:
                # Never silently choose which contradictory assertion was meant.
                supersedes_assertion_id = None

        if supersedes_assertion_id is not None:
            target = session.get(ConversationAssertion, supersedes_assertion_id)
            if target is None or target.lead_id != lead.id:
                raise ValueError("Superseded assertion does not belong to this lead.")
            if target.subject_key != subject_key:
                raise ValueError("A correction must supersede an assertion with the same subject.")

        row = ConversationAssertion(
            assertion_uid=str(uuid4()),
            lead_id=lead.id,
            interaction_id=interaction_id,
            subject_key=subject_key,
            value_json=json.dumps(value, ensure_ascii=False, sort_keys=True),
            assertion_state=state,
            source_kind=source,
            source_text=clean_source_text,
            source_text_mode=text_mode,
            confidence=certainty,
            supersedes_assertion_id=supersedes_assertion_id,
            actor_id=actor_id.strip(),
            correction_reason=correction_reason.strip(),
        )
        session.add(row)
        session.flush()
        return row

    def correct_assertion(
        self,
        session: Session,
        assertion_id: int,
        *,
        value: Any = None,
        assertion_state: AssertionState | str = AssertionState.ACTIVE,
        source_kind: AssertionSourceKind | str = AssertionSourceKind.OPERATOR_OBSERVATION,
        confidence: AssertionConfidence | str = AssertionConfidence.CONFIRMED,
        source_text: str = "",
        source_text_mode: AssertionSourceTextMode | str = AssertionSourceTextMode.NOT_RECORDED,
        actor_id: str = "",
        correction_reason: str,
        interaction_id: int | None = None,
    ) -> ConversationAssertion:
        target = session.get(ConversationAssertion, assertion_id)
        if target is None:
            raise ValueError("Conversation assertion not found.")
        lead = session.get(Lead, target.lead_id)
        if lead is None:
            raise ValueError("Conversation assertion lead no longer exists.")
        return self.append_assertion(
            session,
            lead,
            subject_key=target.subject_key,
            value=value,
            assertion_state=assertion_state,
            source_kind=source_kind,
            confidence=confidence,
            interaction_id=interaction_id if interaction_id is not None else target.interaction_id,
            source_text=source_text,
            source_text_mode=source_text_mode,
            supersedes_assertion_id=target.id,
            actor_id=actor_id,
            correction_reason=correction_reason,
        )

    def record_interaction_summary(
        self,
        session: Session,
        interaction: ContactInteraction,
        *,
        previous: dict[str, Any] | None = None,
    ) -> None:
        """Dual-write explicit modern interaction inputs into canonical assertions.

        Blank/false values on a *new* interaction do not mean a correction. On an
        explicit edit of a modern interaction, changed fields append correction
        records instead of mutating prior semantic history.
        """
        lead = session.get(Lead, interaction.lead_id)
        if lead is None:
            return
        previous = previous or {}
        is_edit = bool(previous)

        current_single = {
            "contact_name": (interaction.contact_name or "").strip(),
            "contact_role": (interaction.contact_role or "").strip(),
            "decision_maker_status": (interaction.decision_maker_status or "").strip(),
            "business_goal": (interaction.business_goal or "").strip(),
            "capacity_status": (interaction.capacity_status or "").strip(),
            "next_action": (interaction.next_action or "").strip(),
        }
        for field, subject in SINGLE_FIELD_TO_SUBJECT.items():
            old = str(previous.get(field, "") or "").strip()
            new = current_single[field]
            if field == "decision_maker_status":
                old_normalized = "" if old.casefold() == "unknown" else old
                new_normalized = "" if new.casefold() == "unknown" else new
            else:
                old_normalized, new_normalized = old, new
            if is_edit and old_normalized == new_normalized:
                continue
            target = self._latest_interaction_assertion(session, interaction.id, subject, old_normalized) if is_edit else None
            if new_normalized:
                self.append_assertion(
                    session,
                    lead,
                    subject_key=subject,
                    value=new_normalized,
                    assertion_state=AssertionState.ACTIVE,
                    source_kind=AssertionSourceKind.OPERATOR_OBSERVATION,
                    confidence=AssertionConfidence.CONFIRMED,
                    interaction_id=interaction.id,
                    supersedes_assertion_id=target.id if target else None,
                    supersede_current=not is_edit or target is None,
                    correction_reason="Interaction edit" if is_edit else "",
                )
            elif is_edit and old_normalized:
                self.append_assertion(
                    session,
                    lead,
                    subject_key=subject,
                    value=old_normalized,
                    assertion_state=AssertionState.UNKNOWN if field == "decision_maker_status" else AssertionState.CLEARED,
                    source_kind=AssertionSourceKind.OPERATOR_OBSERVATION,
                    confidence=AssertionConfidence.CONFIRMED,
                    interaction_id=interaction.id,
                    supersedes_assertion_id=target.id if target else None,
                    correction_reason="Interaction edit cleared prior value",
                )

        current_lists = {
            "buyer_questions": self._json_list(interaction.buyer_questions_json),
            "objections": ((interaction.objection or "").strip(),) if (interaction.objection or "").strip() else (),
            "commitments": self._json_list(interaction.commitments_json),
        }
        previous_lists = {
            "buyer_questions": tuple(str(v).strip() for v in previous.get("buyer_questions", ()) if str(v).strip()),
            "objections": tuple(str(v).strip() for v in previous.get("objections", ()) if str(v).strip()),
            "commitments": tuple(str(v).strip() for v in previous.get("commitments", ()) if str(v).strip()),
        }
        for field, subject in LIST_FIELD_TO_SUBJECT.items():
            old_values = previous_lists[field] if is_edit else ()
            new_values = current_lists[field]
            old_map = {v.casefold(): v for v in old_values}
            new_map = {v.casefold(): v for v in new_values}
            for key, value in new_map.items():
                if key in old_map:
                    continue
                # Preserve each interaction's observation even when the same
                # objection/question/commitment was recorded elsewhere. The
                # current projection de-duplicates display values; history does not.
                self.append_assertion(
                    session,
                    lead,
                    subject_key=subject,
                    value=value,
                    assertion_state=AssertionState.ACTIVE,
                    source_kind=AssertionSourceKind.OPERATOR_OBSERVATION,
                    confidence=AssertionConfidence.CONFIRMED,
                    interaction_id=interaction.id,
                    correction_reason="Interaction edit added value" if is_edit else "",
                )
            if is_edit:
                for key, value in old_map.items():
                    if key in new_map:
                        continue
                    target = self._latest_interaction_assertion(session, interaction.id, subject, value)
                    self.append_assertion(
                        session,
                        lead,
                        subject_key=subject,
                        value=value,
                        assertion_state=AssertionState.CLEARED,
                        source_kind=AssertionSourceKind.OPERATOR_OBSERVATION,
                        confidence=AssertionConfidence.CONFIRMED,
                        interaction_id=interaction.id,
                        supersedes_assertion_id=target.id if target else None,
                        correction_reason="Interaction edit removed value",
                    )

        for subject, field in CONCERN_SUBJECT_TO_FIELD.items():
            old_concern = bool(previous.get(field, False)) if is_edit else False
            new_concern = bool(getattr(interaction, field, False))
            if is_edit and old_concern == new_concern:
                continue
            target = self._latest_interaction_assertion(session, interaction.id, subject, True) if is_edit else None
            if new_concern:
                # A repeated concern in a later interaction is separate historical
                # evidence. Do not collapse it into the first interaction's row.
                self.append_assertion(
                    session,
                    lead,
                    subject_key=subject,
                    value=True,
                    assertion_state=AssertionState.ACTIVE,
                    source_kind=AssertionSourceKind.OPERATOR_INTERPRETATION,
                    confidence=AssertionConfidence.TENTATIVE,
                    interaction_id=interaction.id,
                    supersedes_assertion_id=target.id if target else None,
                    correction_reason="Interaction edit" if is_edit else "",
                )
            elif is_edit and old_concern:
                self.append_assertion(
                    session,
                    lead,
                    subject_key=subject,
                    value=True,
                    assertion_state=AssertionState.CLEARED,
                    source_kind=AssertionSourceKind.OPERATOR_INTERPRETATION,
                    confidence=AssertionConfidence.CONFIRMED,
                    interaction_id=interaction.id,
                    supersedes_assertion_id=target.id if target else None,
                    correction_reason="Interaction edit cleared interpretation",
                )

    def build(self, session: Session, lead: Lead) -> ConversationState:
        interactions = list(
            session.execute(
                select(ContactInteraction)
                .where(ContactInteraction.lead_id == lead.id)
                .order_by(ContactInteraction.interaction_datetime.desc(), ContactInteraction.id.desc())
            ).scalars()
        )
        assertions = list(
            session.execute(
                select(ConversationAssertion)
                .where(ConversationAssertion.lead_id == lead.id)
                .order_by(ConversationAssertion.id.asc())
            ).scalars()
        )
        if not interactions and not assertions:
            return ConversationState(contact_name=(lead.owner or "").strip())

        superseded = {row.supersedes_assertion_id for row in assertions if row.supersedes_assertion_id is not None}
        current_rows = [row for row in assertions if row.id not in superseded]
        by_subject: dict[str, list[ConversationAssertion]] = {}
        for row in current_rows:
            by_subject.setdefault(row.subject_key, []).append(row)

        ambiguous: set[str] = set()

        def single(subject: str, default: str = "") -> str:
            rows = by_subject.get(subject, ())
            active = [r for r in rows if r.assertion_state == AssertionState.ACTIVE.value]
            distinct = self._distinct_values(active)
            if len(distinct) > 1:
                ambiguous.add(subject)
                return default if subject == SUBJECT_AUTHORITY else ""
            if not active:
                # A current RESOLVED/CLEARED/UNKNOWN record is itself semantic
                # information. Do not fill it from legacy/public fallback data.
                if rows:
                    return default if subject == SUBJECT_AUTHORITY else ""
                return default
            value = self._decode(active[-1].value_json)
            return str(value).strip() if value is not None else default

        def multi(subject: str) -> tuple[str, ...]:
            values: list[str] = []
            seen: set[str] = set()
            for row in reversed(by_subject.get(subject, ())):
                if row.assertion_state != AssertionState.ACTIVE.value:
                    continue
                value = self._decode(row.value_json)
                text = str(value).strip() if value is not None else ""
                key = text.casefold()
                if text and key not in seen:
                    seen.add(key)
                    values.append(text)
            return tuple(values)

        def concern(subject: str) -> bool:
            active = [r for r in by_subject.get(subject, ()) if r.assertion_state == AssertionState.ACTIVE.value]
            distinct = {bool(self._decode(r.value_json)) for r in active}
            if len(distinct) > 1:
                ambiguous.add(subject)
                return False
            return True in distinct

        legacy_history_present = any(
            (item.semantic_capture_version or "").strip() != SEMANTIC_CAPTURE_VERSION
            for item in interactions
        )

        branch_path: tuple[str, ...] = ()
        for item in interactions:
            path = self._json_list(item.branch_path_json)
            if path:
                branch_path = path
                break

        return ConversationState(
            contact_name=single(SUBJECT_CONTACT_NAME, (lead.owner or "").strip()),
            contact_role=single(SUBJECT_CONTACT_ROLE),
            decision_maker_status=single(SUBJECT_AUTHORITY, "Unknown"),
            business_goal=single(SUBJECT_BUSINESS_GOAL),
            capacity_status=single(SUBJECT_CAPACITY),
            buyer_questions=multi(SUBJECT_BUYER_QUESTION),
            objections=multi(SUBJECT_OBJECTION),
            commitments=multi(SUBJECT_COMMITMENT),
            branch_path=branch_path,
            next_action=single(SUBJECT_NEXT_ACTION),
            last_outcome=str(interactions[0].outcome or "").strip() if interactions else "",
            interaction_count=len(interactions),
            credibility_concern=concern(SUBJECT_CONCERN_CREDIBILITY),
            wants_examples=concern(SUBJECT_CONCERN_EXAMPLES),
            wants_references=concern(SUBJECT_CONCERN_REFERENCES),
            concerned_about_ai=concern(SUBJECT_CONCERN_AI),
            wants_proof=concern(SUBJECT_CONCERN_PROOF),
            seller_experience_question=concern(SUBJECT_CONCERN_EXPERIENCE),
            local_presence_question=concern(SUBJECT_CONCERN_LOCALITY),
            decision_maker_skeptical=concern(SUBJECT_CONCERN_DECISION_MAKER_SKEPTICISM),
            legitimacy_concern=concern(SUBJECT_CONCERN_LEGITIMACY),
            ambiguous_subjects=tuple(sorted(ambiguous)),
            legacy_history_present=legacy_history_present,
            assertion_revision=max((row.id or 0 for row in assertions), default=0),
        )

    @staticmethod
    def semantic_snapshot(interaction: ContactInteraction) -> dict[str, Any]:
        return {
            "contact_name": interaction.contact_name,
            "contact_role": interaction.contact_role,
            "decision_maker_status": interaction.decision_maker_status,
            "business_goal": interaction.business_goal,
            "capacity_status": interaction.capacity_status,
            "buyer_questions": ConversationStateService._json_list(interaction.buyer_questions_json),
            "objections": ((interaction.objection or "").strip(),) if (interaction.objection or "").strip() else (),
            "commitments": ConversationStateService._json_list(interaction.commitments_json),
            "next_action": interaction.next_action,
            **{field: bool(getattr(interaction, field, False)) for field in CONCERN_SUBJECT_TO_FIELD.values()},
        }

    @staticmethod
    def _enum_value(enum_cls, value: Any, label: str) -> str:
        try:
            return cast(str, enum_cls(value).value)
        except ValueError as exc:
            raise ValueError(f"Unsupported {label}: {value!r}") from exc

    @staticmethod
    def _decode(raw: str) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _json_list(raw: str) -> tuple[str, ...]:
        try:
            data = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            return ()
        if not isinstance(data, list):
            return ()
        return tuple(str(v).strip() for v in data if str(v).strip())

    def _unsuperseded_active(self, session: Session, lead_id: int, subject: str) -> list[ConversationAssertion]:
        rows = list(
            session.scalars(
                select(ConversationAssertion)
                .where(ConversationAssertion.lead_id == lead_id, ConversationAssertion.subject_key == subject)
                .order_by(ConversationAssertion.id.asc())
            )
        )
        superseded = {row.supersedes_assertion_id for row in rows if row.supersedes_assertion_id is not None}
        return [row for row in rows if row.id not in superseded and row.assertion_state == AssertionState.ACTIVE.value]

    def _has_unsuperseded_active_value(self, session: Session, lead_id: int, subject: str, value: Any) -> bool:
        target = self._normalized_value(value)
        return any(self._normalized_value(self._decode(row.value_json)) == target for row in self._unsuperseded_active(session, lead_id, subject))

    def _latest_interaction_assertion(
        self, session: Session, interaction_id: int | None, subject: str, value: Any
    ) -> ConversationAssertion | None:
        if interaction_id is None:
            return None
        rows = list(
            session.scalars(
                select(ConversationAssertion)
                .where(ConversationAssertion.interaction_id == interaction_id, ConversationAssertion.subject_key == subject)
                .order_by(ConversationAssertion.id.asc())
            )
        )
        superseded = {row.supersedes_assertion_id for row in rows if row.supersedes_assertion_id is not None}
        target = self._normalized_value(value)
        candidates = [
            row for row in rows
            if row.id not in superseded and self._normalized_value(self._decode(row.value_json)) == target
        ]
        return candidates[-1] if candidates else None

    def _distinct_values(self, rows: list[ConversationAssertion]) -> set[str]:
        return {self._normalized_value(self._decode(row.value_json)) for row in rows}

    @staticmethod
    def _normalized_value(value: Any) -> str:
        if isinstance(value, str):
            return " ".join(value.casefold().split())
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
