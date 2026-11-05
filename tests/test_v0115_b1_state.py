from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    delete_contact_interaction,
    lead_contact_readiness_errors,
    save_contact_interaction,
    update_lead_fields,
)
from local_presence_miner.database.schema import (
    AppSetting,
    CommercialDispositionRecord,
    ContactInteraction,
    ConversationAssertion,
    Lead,
)
from local_presence_miner.domain.enums import (
    AssertionConfidence,
    AssertionSourceKind,
    AssertionSourceTextMode,
    AssertionState,
    CommercialDisposition,
    EligibilityState,
    FollowUpPermission,
    LeadStatus,
)
from local_presence_miner.services.conversation_state_service import (
    SUBJECT_BUSINESS_GOAL,
    SUBJECT_CONCERN_AI,
    SUBJECT_CONTACT_NAME,
    SUBJECT_OBJECTION,
    ConversationStateService,
)
from local_presence_miner.services.disposition_service import DispositionService
from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService
from local_presence_miner.services.suppression_service import SuppressionService


def _factory(tmp_path, name: str = "b1.sqlite3"):
    factory = create_session_factory(tmp_path / name)
    initialize_database(factory)
    return factory


def _eligible_lead(place_id: str = "b1-lead") -> Lead:
    return Lead(
        place_id=place_id,
        name="B1 Roofing",
        category="roofers",
        phone="555-010-1000",
        status=LeadStatus.QUALIFIED.value,
        qualification_class="Qualified",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Qualified","confidence":"Strong"}',
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        offer_resolution_state="canonical_id",
    )


def test_b1_migration_is_additive_idempotent_and_non_inventive(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY,
            place_id VARCHAR(180) NOT NULL,
            name VARCHAR(240) NOT NULL,
            status VARCHAR(80) NOT NULL DEFAULT 'Lost'
        );
        CREATE TABLE contact_interactions (
            id INTEGER PRIMARY KEY,
            lead_id INTEGER NOT NULL,
            interaction_datetime VARCHAR(40) NOT NULL,
            method VARCHAR(40) NOT NULL DEFAULT 'Phone',
            direction VARCHAR(20) NOT NULL DEFAULT 'Outbound',
            outcome VARCHAR(160) NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO leads (id, place_id, name, status) VALUES (1, 'legacy-b1', 'Legacy B1', 'Lost');
        INSERT INTO contact_interactions (id, lead_id, interaction_datetime, outcome, notes)
        VALUES (1, 1, '2026-09-01T10:00', 'Follow up later', 'AI concern in old free text');
        """
    )
    connection.commit()
    connection.close()

    factory = create_session_factory(path)
    initialize_database(factory)

    with factory() as session:
        lead = session.get(Lead, 1)
        assert lead is not None
        assert lead.status == "Lost"  # CRM history preserved, not normalized away.
        assert lead.commercial_disposition == CommercialDisposition.UNKNOWN.value
        assert lead.commercial_disposition_revision == 0
        assert lead.follow_up_permission == FollowUpPermission.UNKNOWN.value
        assert session.scalar(select(ConversationAssertion.id)) is None
        assert session.scalar(select(CommercialDispositionRecord.id)) is None
        marker = session.get(AppSetting, "v0115_b1_state_migrated")
        assert marker is not None
        metadata = json.loads(marker.value)
        assert metadata["legacy_assertions_activated"] == 0
        assert metadata["legacy_dispositions_inferred"] == 0

    backup = path.with_suffix(path.suffix + ".backup-before-v0115-b1")
    assert backup.exists()
    with sqlite3.connect(backup) as copied:
        assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copied.execute("SELECT outcome FROM contact_interactions WHERE id=1").fetchone()[0] == "Follow up later"

    initialize_database(factory)
    with factory() as session:
        assert session.scalar(select(ConversationAssertion.id)) is None
        assert session.scalar(select(CommercialDispositionRecord.id)) is None
        assert session.get(AppSetting, "v0115_b1_state_migrated") is not None
    assert not Path(str(backup) + ".1").exists()



def test_corrupt_existing_b1_backup_blocks_migration_instead_of_overwriting_it(tmp_path) -> None:
    path = tmp_path / "corrupt-backup.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY,
            place_id VARCHAR(180) NOT NULL,
            name VARCHAR(240) NOT NULL,
            status VARCHAR(80) NOT NULL DEFAULT 'Lost'
        );
        INSERT INTO leads (id, place_id, name, status) VALUES (1, 'legacy', 'Legacy', 'Lost');
        """
    )
    connection.commit()
    connection.close()
    backup = path.with_suffix(path.suffix + ".backup-before-v0115-b1")
    backup.write_bytes(b"not a sqlite database")

    factory = create_session_factory(path)
    with pytest.raises(RuntimeError, match="backup is unreadable"):
        initialize_database(factory)
    assert backup.read_bytes() == b"not a sqlite database"
    assert not Path(str(backup) + ".1").exists()

def test_new_interaction_dual_writes_canonical_current_state(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        interaction = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Interested",
            notes="Structured capture",
            contact_name="Jamie",
            contact_role="Owner",
            decision_maker_status="Decision maker",
            business_goal="Better-fit jobs",
            capacity_status="Booked/busy",
            buyer_questions=["SEO scope"],
            commitments=["Review proposal Friday"],
            objection="Timing",
            next_action="Send comparison",
            concerned_about_ai=True,
        )
        state = ConversationStateService().build(session, lead)
        assertions = list(session.scalars(select(ConversationAssertion).where(ConversationAssertion.interaction_id == interaction.id)))

        assert state.contact_name == "Jamie"
        assert state.business_goal == "Better-fit jobs"
        assert state.buyer_questions == ("SEO scope",)
        assert state.objections == ("Timing",)
        assert state.commitments == ("Review proposal Friday",)
        assert state.concerned_about_ai is True
        assert state.legacy_history_present is False
        assert assertions
        ai = next(row for row in assertions if row.subject_key == SUBJECT_CONCERN_AI)
        assert ai.source_kind == AssertionSourceKind.OPERATOR_INTERPRETATION.value
        assert ai.confidence == AssertionConfidence.TENTATIVE.value


def test_resolved_and_unknown_do_not_revive_old_ai_concern(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="AI concern",
            notes="Asked about AI",
            concerned_about_ai=True,
        )
        service = ConversationStateService()
        active = session.scalar(
            select(ConversationAssertion).where(
                ConversationAssertion.lead_id == lead.id,
                ConversationAssertion.subject_key == SUBJECT_CONCERN_AI,
                ConversationAssertion.assertion_state == AssertionState.ACTIVE.value,
            )
        )
        assert active is not None
        resolved = service.correct_assertion(
            session,
            active.id,
            value=True,
            assertion_state=AssertionState.RESOLVED,
            source_kind=AssertionSourceKind.OPERATOR_OBSERVATION,
            confidence=AssertionConfidence.CONFIRMED,
            correction_reason="Owner clarified concern was resolved",
        )
        assert service.build(session, lead).concerned_about_ai is False

        service.correct_assertion(
            session,
            resolved.id,
            value=None,
            assertion_state=AssertionState.UNKNOWN,
            source_kind=AssertionSourceKind.OPERATOR_OBSERVATION,
            confidence=AssertionConfidence.UNKNOWN,
            correction_reason="Current state cannot be established",
        )
        state = service.build(session, lead)
        assert state.concerned_about_ai is False
        assert state.requires_clarification is False
        assert session.scalar(select(ConversationAssertion).where(ConversationAssertion.id == active.id)) is active


def test_contradictory_active_single_value_is_review_required_not_arbitrarily_newest(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        service = ConversationStateService()
        service.append_assertion(session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value="More leads")
        service.append_assertion(session, lead, subject_key=SUBJECT_BUSINESS_GOAL, value="Fewer better-fit leads")
        state = service.build(session, lead)
        assert state.business_goal == ""
        assert SUBJECT_BUSINESS_GOAL in state.ambiguous_subjects
        assert state.requires_clarification is True


def test_modern_interaction_edit_appends_correction_without_rewriting_old_assertion(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        interaction = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Interested",
            notes="Initial",
            business_goal="More leads",
        )
        original = session.scalar(
            select(ConversationAssertion).where(
                ConversationAssertion.interaction_id == interaction.id,
                ConversationAssertion.subject_key == SUBJECT_BUSINESS_GOAL,
            )
        )
        assert original is not None
        original_json = original.value_json

        save_contact_interaction(
            session,
            lead.id,
            interaction_id=interaction.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Interested",
            notes="Corrected",
            business_goal="Better-fit leads",
        )
        rows = list(
            session.scalars(
                select(ConversationAssertion)
                .where(ConversationAssertion.interaction_id == interaction.id, ConversationAssertion.subject_key == SUBJECT_BUSINESS_GOAL)
                .order_by(ConversationAssertion.id)
            )
        )
        assert len(rows) == 2
        assert rows[0].value_json == original_json
        assert rows[1].supersedes_assertion_id == rows[0].id
        assert ConversationStateService().build(session, lead).business_goal == "Better-fit leads"


def test_resolving_one_objection_removes_it_from_current_state_but_preserves_history(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        first = save_contact_interaction(
            session, lead.id, interaction_datetime="2026-09-09T10:00", method="Phone", direction="Outbound",
            outcome="Price objection", notes="Price", objection="Too expensive",
        )
        save_contact_interaction(
            session, lead.id, interaction_datetime="2026-09-09T10:05", method="Phone", direction="Outbound",
            outcome="Needs approval", notes="Approval", objection="Needs approval",
        )
        service = ConversationStateService()
        assert set(service.build(session, lead).objections) == {"Too expensive", "Needs approval"}
        price = session.scalar(
            select(ConversationAssertion).where(
                ConversationAssertion.interaction_id == first.id,
                ConversationAssertion.subject_key == SUBJECT_OBJECTION,
            )
        )
        assert price is not None
        service.correct_assertion(
            session,
            price.id,
            value="Too expensive",
            assertion_state=AssertionState.RESOLVED,
            correction_reason="Price concern resolved",
        )
        assert service.build(session, lead).objections == ("Needs approval",)
        assert session.get(ConversationAssertion, price.id) is not None


def test_legacy_interaction_is_historical_unknown_not_current_psychology(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        session.add(
            ContactInteraction(
                lead_id=lead.id,
                interaction_datetime="2026-09-01T10:00",
                method="Phone",
                direction="Outbound",
                outcome="AI concern",
                notes="Legacy",
                business_goal="Old goal",
                concerned_about_ai=True,
            )
        )
        session.flush()
        state = ConversationStateService().build(session, lead)
        assert state.business_goal == ""
        assert state.concerned_about_ai is False
        assert state.legacy_history_present is True


def test_identity_question_path_does_not_infer_skepticism(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Replied",
            notes="Identity question only",
            branch_path=["Who are you?"],
        )
        state = ConversationStateService().build(session, lead)
        assert state.credibility_concern is False
        assert state.legitimacy_concern is False
        assert state.decision_maker_skeptical is False


def test_delete_interaction_deletes_its_canonical_assertions_for_privacy(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        interaction = save_contact_interaction(
            session, lead.id, interaction_datetime="2026-09-09T10:00", method="Phone", direction="Outbound",
            outcome="Interested", notes="Delete me", business_goal="Private goal",
        )
        interaction_id = interaction.id
        assert session.scalar(select(ConversationAssertion.id).where(ConversationAssertion.interaction_id == interaction_id)) is not None
        delete_contact_interaction(session, interaction_id)
        assert session.get(ContactInteraction, interaction_id) is None
        assert session.scalar(select(ConversationAssertion.id).where(ConversationAssertion.interaction_id == interaction_id)) is None
        assert ConversationStateService().build(session, lead).business_goal == ""


def test_disposition_is_explicit_append_only_and_separate_from_crm(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        lead.status = LeadStatus.REPLIED.value
        session.add(lead)
        session.flush()
        service = DispositionService()
        with pytest.raises(ValueError, match="reason"):
            service.set_disposition(session, lead, CommercialDisposition.DEFERRED, reason="", confirmed=True)

        first = service.set_disposition(
            session,
            lead,
            CommercialDisposition.DEFERRED,
            reason="Owner asked for October",
            confirmed=True,
            not_before="2026-10-01",
            follow_up_permission=FollowUpPermission.AGREED,
        )
        assert lead.status == LeadStatus.REPLIED.value
        assert lead.next_follow_up_date == "2026-10-01"
        assert first.revision == 1

        second = service.set_disposition(session, lead, CommercialDisposition.CLOSED_LOST, reason="Owner declined", confirmed=True)
        assert lead.status == LeadStatus.LOST.value
        assert second.revision == 2
        records = list(
            session.scalars(
                select(CommercialDispositionRecord)
                .where(CommercialDispositionRecord.lead_id == lead.id)
                .order_by(CommercialDispositionRecord.id)
            )
        )
        assert [row.disposition for row in records] == [CommercialDisposition.DEFERRED.value, CommercialDisposition.CLOSED_LOST.value]
        assert records[0].reason == "Owner asked for October"



def test_disposition_revision_is_unique_per_lead(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("revision-unique")
        session.add(lead)
        session.flush()
        DispositionService().set_disposition(
            session, lead, CommercialDisposition.OPEN, reason="Initial review", confirmed=True
        )
        duplicate = CommercialDispositionRecord(
            lead_id=lead.id,
            disposition=CommercialDisposition.DEFERRED.value,
            previous_disposition=CommercialDisposition.OPEN.value,
            not_before="2026-10-01",
            follow_up_permission=FollowUpPermission.AGREED.value,
            reason="Simulated concurrent duplicate revision",
            revision=1,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()

def test_deferred_permission_and_date_gate_contact(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        disposition = DispositionService()
        eligibility = OutreachEligibilityService()

        disposition.set_disposition(
            session, lead, CommercialDisposition.DEFERRED, reason="Not now", confirmed=True, not_before="2026-10-01",
            follow_up_permission=FollowUpPermission.UNKNOWN,
        )
        assert eligibility.evaluate(session, lead, today=date(2026, 10, 2)).state is EligibilityState.BLOCKED_DEFERRED

        disposition.set_disposition(
            session, lead, CommercialDisposition.DEFERRED, reason="Owner agreed to October follow-up", confirmed=True, not_before="2026-10-01",
            follow_up_permission=FollowUpPermission.AGREED,
        )
        assert eligibility.evaluate(session, lead, today=date(2026, 9, 30)).state is EligibilityState.BLOCKED_DEFERRED
        assert eligibility.evaluate(session, lead, today=date(2026, 10, 1)).state is EligibilityState.ELIGIBLE_FOR_HUMAN_REVIEW


def test_compliance_and_disposition_precedence_cannot_be_overridden_by_high_score(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        lead.lead_score = 100
        lead.sales_priority_score = 100
        session.add(lead)
        session.flush()
        DispositionService().set_disposition(session, lead, CommercialDisposition.OPEN, reason="Operator reviewed", confirmed=True)
        SuppressionService().suppress_lead(session, lead, "Owner requested DNC")
        result = OutreachEligibilityService().evaluate(session, lead)
        assert result.state is EligibilityState.BLOCKED_COMPLIANCE
        assert lead_contact_readiness_errors(session, lead)


def test_terminal_disposition_blocks_even_when_qualification_is_strong(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        for value in (CommercialDisposition.NO_SELL, CommercialDisposition.CLOSED_LOST):
            DispositionService().set_disposition(session, lead, value, reason=f"Set {value.value}", confirmed=True)
            assert OutreachEligibilityService().evaluate(session, lead).state is EligibilityState.BLOCKED_DISPOSITION
            DispositionService().set_disposition(session, lead, CommercialDisposition.OPEN, reason="Explicit reopen", confirmed=True)

        DispositionService().set_disposition(session, lead, CommercialDisposition.CLOSED_WON, reason="Engagement accepted", confirmed=True)
        assert OutreachEligibilityService().evaluate(session, lead).state is EligibilityState.BLOCKED_DISPOSITION
        with pytest.raises(ValueError, match="new opportunity"):
            DispositionService().set_disposition(session, lead, CommercialDisposition.OPEN, reason="Do not reopen won work", confirmed=True)


def test_research_offer_qualification_and_missing_route_are_distinct_states(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        service = OutreachEligibilityService()

        lead.qualification_class = "Hold"
        assert service.evaluate(session, lead).state is EligibilityState.RESEARCH_ONLY
        lead.qualification_class = "Qualified"
        lead.recommended_offer_id = ""
        lead.offer_resolution_state = "research_required"
        assert service.evaluate(session, lead).state is EligibilityState.RESEARCH_ONLY
        lead.recommended_offer_id = "conversion_tune_up"
        lead.offer_resolution_state = "canonical_id"
        lead.phone = ""
        assert service.evaluate(session, lead).state is EligibilityState.CONTACT_RESEARCH_REQUIRED



def test_offer_eligibility_fails_closed_on_unknown_resolution_state_or_offer_id(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("offer-corrupt")
        session.add(lead)
        session.flush()
        service = OutreachEligibilityService()

        lead.offer_resolution_state = "future_successish_state"
        assert service.evaluate(session, lead).state is EligibilityState.RESEARCH_ONLY

        lead.offer_resolution_state = "canonical_id"
        lead.recommended_offer_id = "not_a_real_offer"
        assert service.evaluate(session, lead).state is EligibilityState.RESEARCH_ONLY

        lead.recommended_offer_id = "conversion_tune_up"
        for state in ("canonical_id", "display_label", "legacy_alias"):
            lead.offer_resolution_state = state
            assert service.evaluate(session, lead).state is EligibilityState.ELIGIBLE_FOR_HUMAN_REVIEW

def test_clean_current_state_reaches_human_review_not_consent(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead()
        session.add(lead)
        session.flush()
        result = OutreachEligibilityService().evaluate(session, lead)
        assert result.state is EligibilityState.ELIGIBLE_FOR_HUMAN_REVIEW
        assert result.permits_live_use is True
        assert "not consent" in result.reasons[0].lower()




def test_generic_lead_update_cannot_bypass_disposition_service(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("direct-disposition-bypass")
        session.add(lead)
        session.flush()
        with pytest.raises(ValueError, match="DispositionService"):
            update_lead_fields(session, lead.id, commercial_disposition="OPEN")
        with pytest.raises(ValueError, match="DispositionService"):
            update_lead_fields(session, lead.id, follow_up_permission="AGREED")
        assert lead.commercial_disposition == CommercialDisposition.UNKNOWN.value
        assert lead.follow_up_permission == FollowUpPermission.UNKNOWN.value
        assert session.scalar(select(CommercialDispositionRecord.id)) is None

def test_disposition_requires_explicit_confirmation_and_rejects_semantic_noop(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("confirm")
        session.add(lead)
        session.flush()
        service = DispositionService()
        with pytest.raises(ValueError, match="confirmation"):
            service.set_disposition(session, lead, CommercialDisposition.OPEN, reason="Reviewed")
        assert lead.commercial_disposition == CommercialDisposition.UNKNOWN.value
        assert session.scalar(select(CommercialDispositionRecord.id)) is None

        service.set_disposition(session, lead, CommercialDisposition.OPEN, reason="Reviewed", confirmed=True)
        revision = lead.commercial_disposition_revision
        with pytest.raises(ValueError, match="does not change"):
            service.set_disposition(session, lead, CommercialDisposition.OPEN, reason="Repeated click", confirmed=True)
        assert lead.commercial_disposition_revision == revision
        assert len(list(session.scalars(select(CommercialDispositionRecord)))) == 1


def test_disposition_cannot_overwrite_dnc_crm_projection(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("dnc-disposition")
        session.add(lead)
        session.flush()
        SuppressionService().suppress_lead(session, lead, "Owner requested DNC")
        assert lead.status == LeadStatus.DO_NOT_CONTACT.value

        record = DispositionService().set_disposition(
            session,
            lead,
            CommercialDisposition.CLOSED_LOST,
            reason="Commercial opportunity also ended",
            confirmed=True,
        )
        assert lead.status == LeadStatus.DO_NOT_CONTACT.value
        assert lead.suppressed is True
        assert record.crm_status_before == LeadStatus.DO_NOT_CONTACT.value
        assert record.crm_status_after == LeadStatus.DO_NOT_CONTACT.value
        assert OutreachEligibilityService().evaluate(session, lead).state is EligibilityState.BLOCKED_COMPLIANCE


def test_leaving_deferred_clears_only_disposition_projected_follow_up(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("reopen-deferred")
        lead.status = LeadStatus.REPLIED.value
        session.add(lead)
        session.flush()
        service = DispositionService()
        service.set_disposition(
            session,
            lead,
            CommercialDisposition.DEFERRED,
            reason="Agreed revisit",
            confirmed=True,
            not_before="2026-10-01",
            follow_up_permission=FollowUpPermission.AGREED,
        )
        assert lead.next_follow_up_date == "2026-10-01"
        service.set_disposition(session, lead, CommercialDisposition.OPEN, reason="Owner reopened early", confirmed=True)
        assert lead.next_follow_up_date == ""
        assert lead.status == LeadStatus.REPLIED.value


def test_deferred_requires_both_agreement_and_date_to_become_reviewable(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        eligibility = OutreachEligibilityService()
        for key, permission, not_before in (
            ("not-agreed", FollowUpPermission.NOT_AGREED, "2026-10-01"),
            ("agreed-no-date", FollowUpPermission.AGREED, ""),
        ):
            lead = _eligible_lead(key)
            session.add(lead)
            session.flush()
            DispositionService().set_disposition(
                session,
                lead,
                CommercialDisposition.DEFERRED,
                reason="Deferred fixture",
                confirmed=True,
                not_before=not_before,
                follow_up_permission=permission,
            )
            assert eligibility.evaluate(session, lead, today=date(2026, 11, 1)).state is EligibilityState.BLOCKED_DEFERRED


def test_recalculate_contact_summary_cannot_turn_unpermitted_defer_into_follow_up(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("defer-recalc")
        session.add(lead)
        session.flush()
        DispositionService().set_disposition(
            session,
            lead,
            CommercialDisposition.DEFERRED,
            reason="No permission recorded",
            confirmed=True,
            not_before="2026-10-01",
            follow_up_permission=FollowUpPermission.UNKNOWN,
        )
        save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Reached owner",
            notes="Legacy-style date must not authorize contact",
            follow_up_date="2026-09-20",
        )
        assert lead.next_follow_up_date == ""
        assert OutreachEligibilityService().evaluate(session, lead, today=date(2026, 11, 1)).state is EligibilityState.BLOCKED_DEFERRED


def test_legacy_interaction_edit_does_not_silently_activate_current_semantics(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("legacy-edit")
        session.add(lead)
        session.flush()
        legacy = ContactInteraction(
            lead_id=lead.id,
            interaction_datetime="2026-09-01T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Old call",
            notes="Legacy row",
            business_goal="Old legacy goal",
        )
        session.add(legacy)
        session.flush()

        save_contact_interaction(
            session,
            lead.id,
            interaction_id=legacy.id,
            interaction_datetime="2026-09-01T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Old call edited",
            notes="Edited legacy row",
            business_goal="Edited legacy goal",
        )
        assert session.scalar(select(ConversationAssertion.id).where(ConversationAssertion.interaction_id == legacy.id)) is None
        state = ConversationStateService().build(session, lead)
        assert state.business_goal == ""
        assert state.legacy_history_present is True


def test_modern_blank_interaction_can_be_semantically_edited_later(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("modern-blank")
        session.add(lead)
        session.flush()
        interaction = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Reached owner",
            notes="No semantic fields yet",
        )
        assert interaction.semantic_capture_version == "v0115_b1"
        save_contact_interaction(
            session,
            lead.id,
            interaction_id=interaction.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Reached owner",
            notes="Added reviewed goal",
            business_goal="Better-fit jobs",
        )
        assert ConversationStateService().build(session, lead).business_goal == "Better-fit jobs"


def test_unknown_contact_assertion_does_not_fall_back_to_legacy_owner(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("unknown-contact")
        lead.owner = "Legacy Owner Name"
        session.add(lead)
        session.flush()
        service = ConversationStateService()
        active = service.append_assertion(session, lead, subject_key=SUBJECT_CONTACT_NAME, value="Jamie")
        service.correct_assertion(
            session,
            active.id,
            value=None,
            assertion_state=AssertionState.UNKNOWN,
            confidence=AssertionConfidence.UNKNOWN,
            correction_reason="Current contact identity uncertain",
        )
        assert service.build(session, lead).contact_name == ""


def test_source_text_requires_explicit_verbatim_or_paraphrased_marker(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("source-text")
        session.add(lead)
        session.flush()
        service = ConversationStateService()
        with pytest.raises(ValueError, match="VERBATIM or PARAPHRASED"):
            service.append_assertion(
                session,
                lead,
                subject_key=SUBJECT_OBJECTION,
                value="Too expensive",
                source_text="That is too much right now",
            )
        row = service.append_assertion(
            session,
            lead,
            subject_key=SUBJECT_OBJECTION,
            value="Too expensive",
            source_text="That is too much right now",
            source_text_mode=AssertionSourceTextMode.PARAPHRASED,
        )
        assert row.source_text_mode == AssertionSourceTextMode.PARAPHRASED.value


def test_assertion_correction_cannot_cross_lead_or_subject(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        first = _eligible_lead("first")
        second = _eligible_lead("second")
        session.add_all([first, second])
        session.flush()
        service = ConversationStateService()
        target = service.append_assertion(session, first, subject_key=SUBJECT_BUSINESS_GOAL, value="More leads")
        with pytest.raises(ValueError, match="does not belong"):
            service.append_assertion(
                session,
                second,
                subject_key=SUBJECT_BUSINESS_GOAL,
                value="Other",
                supersedes_assertion_id=target.id,
            )
        with pytest.raises(ValueError, match="same subject"):
            service.append_assertion(
                session,
                first,
                subject_key=SUBJECT_OBJECTION,
                value="Price",
                supersedes_assertion_id=target.id,
            )


def test_deleting_older_interaction_detaches_later_correction_without_dangling_fk(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("delete-chain")
        session.add(lead)
        session.flush()
        first = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Reached owner",
            notes="First",
            business_goal="More leads",
        )
        second = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:05",
            method="Phone",
            direction="Outbound",
            outcome="Clarified",
            notes="Second",
        )
        original = session.scalar(
            select(ConversationAssertion).where(
                ConversationAssertion.interaction_id == first.id,
                ConversationAssertion.subject_key == SUBJECT_BUSINESS_GOAL,
            )
        )
        assert original is not None
        correction = ConversationStateService().correct_assertion(
            session,
            original.id,
            value="Better-fit jobs",
            correction_reason="Later clarification",
            interaction_id=second.id,
        )
        assert correction.supersedes_assertion_id == original.id

        delete_contact_interaction(session, first.id)
        session.flush()
        surviving = session.get(ConversationAssertion, correction.id)
        assert surviving is not None
        assert surviving.supersedes_assertion_id is None
        assert ConversationStateService().build(session, lead).business_goal == "Better-fit jobs"
        assert session.execute(text("PRAGMA foreign_key_check")).fetchall() == []



def test_deleting_disposition_source_interaction_preserves_audit_record_and_detaches_pointer(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("delete-disposition-source")
        session.add(lead)
        session.flush()
        interaction = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Not now",
            notes="Owner asked for later follow-up",
        )
        record = DispositionService().set_disposition(
            session,
            lead,
            CommercialDisposition.DEFERRED,
            reason="Owner requested October follow-up",
            confirmed=True,
            not_before="2026-10-01",
            follow_up_permission=FollowUpPermission.AGREED,
            source_interaction_id=interaction.id,
        )
        record_id = record.id

        delete_contact_interaction(session, interaction.id)
        session.flush()

        surviving = session.get(CommercialDispositionRecord, record_id)
        assert surviving is not None
        assert surviving.source_interaction_id is None
        assert surviving.disposition == CommercialDisposition.DEFERRED.value
        assert session.execute(text("PRAGMA foreign_key_check")).fetchall() == []

def test_repeated_objection_is_preserved_per_interaction_and_survives_one_delete(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("repeat-objection")
        session.add(lead)
        session.flush()
        first = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Price question",
            notes="First mention",
            objection="Too expensive",
        )
        second = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:10",
            method="Phone",
            direction="Outbound",
            outcome="Price question again",
            notes="Repeated mention",
            objection="Too expensive",
        )
        rows = list(
            session.scalars(
                select(ConversationAssertion).where(
                    ConversationAssertion.lead_id == lead.id,
                    ConversationAssertion.subject_key == SUBJECT_OBJECTION,
                )
            )
        )
        assert {row.interaction_id for row in rows} == {first.id, second.id}
        assert ConversationStateService().build(session, lead).objections == ("Too expensive",)

        delete_contact_interaction(session, first.id)
        assert ConversationStateService().build(session, lead).objections == ("Too expensive",)
        remaining = list(
            session.scalars(
                select(ConversationAssertion).where(
                    ConversationAssertion.lead_id == lead.id,
                    ConversationAssertion.subject_key == SUBJECT_OBJECTION,
                )
            )
        )
        assert len(remaining) == 1 and remaining[0].interaction_id == second.id


def test_repeated_concern_is_preserved_per_interaction_and_survives_one_clear(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _eligible_lead("repeat-concern")
        session.add(lead)
        session.flush()
        first = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="AI concern",
            notes="First",
            concerned_about_ai=True,
        )
        second = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-09T10:10",
            method="Phone",
            direction="Outbound",
            outcome="AI concern repeated",
            notes="Second",
            concerned_about_ai=True,
        )
        rows = list(
            session.scalars(
                select(ConversationAssertion).where(
                    ConversationAssertion.lead_id == lead.id,
                    ConversationAssertion.subject_key == SUBJECT_CONCERN_AI,
                    ConversationAssertion.assertion_state == AssertionState.ACTIVE.value,
                )
            )
        )
        assert {row.interaction_id for row in rows} == {first.id, second.id}
        assert ConversationStateService().build(session, lead).concerned_about_ai is True

        save_contact_interaction(
            session,
            lead.id,
            interaction_id=first.id,
            interaction_datetime="2026-09-09T10:00",
            method="Phone",
            direction="Outbound",
            outcome="AI concern clarified",
            notes="First occurrence corrected",
            concerned_about_ai=False,
        )
        # The second independent occurrence remains active.
        assert ConversationStateService().build(session, lead).concerned_about_ai is True
