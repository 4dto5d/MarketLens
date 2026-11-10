"""Pass 1 persistence and commercial evidence boundaries, with synthetic leads."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from test_intervention_integration import BROKEN_ROUTE, add_business
from test_intervention_integration import storage as storage_fixture

from local_presence_miner.database.schema import GooglePresenceAssessment, ProspectFindingRevision
from local_presence_miner.services.prospect_finding_service import (
    capture_contact_finding,
    contact_source_snapshot,
    finding_history,
    project_findings,
    record_owner_need,
    reviewed_contact_audit,
    revise_finding,
    validate_finding_references,
)
from local_presence_miner.time_utils import utc_now


@pytest.fixture(name='storage')
def setup_storage(tmp_path):
    config, factory = storage_fixture.__wrapped__(tmp_path)
    yield config, factory
    factory.kw['bind'].dispose()


def test_capture_review_correct_reopen_retains_original_source(storage):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE, name='Synthetic Lakewood Service')
        row = capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        source = row.source_snapshot_json
        identity, key = lead.id, row.finding_key
        assert row.review_state == 'UNREVIEWED'
        reviewed = revise_finding(session, identity, key, expected_revision=1, review_state='VERIFIED',
                                  actor='Sammi', review_note='Checked the source URL, capture date, tel-link check and statement.', source_checked=True)
        assert reviewed.revision == 2 and reviewed.source_snapshot_json == source
        corrected = revise_finding(session, identity, key, expected_revision=2, review_state='DISPUTED',
                                   actor='Sammi', review_note='Owner reports a working alternative; recorded absence needs rechecking.')
        assert corrected.revision == 3
        session.commit()
    with factory() as session:
        history = finding_history(session, identity, key)
        assert [item['review_state'] for item in history] == ['UNREVIEWED', 'VERIFIED', 'DISPUTED']
        assert all(item['source_snapshot_json'] == source for item in history)
        assert project_findings(session, identity)[0]['review_state'] == 'DISPUTED'
        assert session.scalar(select(ProspectFindingRevision).where(ProspectFindingRevision.revision == 1)).source_snapshot_json == source


def test_attributed_need_does_not_become_owner_assertion(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        row = record_owner_need(session, lead.id, actor='Sammi', owner_label='Hypothetical Jarrod',
                                source_text='I want easier editing; could we move from UENI to Wix?',
                                source_ref='Synthetic conversation example', source_text_mode='PARAPHRASED',
                                attribution='OPERATOR_REPORTED_OWNER')
        assert row.assertion_kind == 'ATTRIBUTED_STATEMENT'
        assert row.review_state == 'UNREVIEWED'
        assert session.execute(text('SELECT COUNT(*) FROM conversation_assertions')).scalar_one() == 0
        assert 'UENI to Wix' in row.source_snapshot_json


def test_disputed_exact_fact_is_withheld_in_actual_consumers_but_hours_survive(storage):
    from local_presence_miner.config import SenderInfo
    from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
    from local_presence_miner.services.call_guide_service import CallGuideService
    from local_presence_miner.services.outreach_service import OutreachService
    from local_presence_miner.services.proposal_service import ProposalService

    config, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE, has_hours=False,
                                   verification_json='{"audit_claims":true,"google_presence":true}')
        original_claim = 'tap-to-call link not detected.'
        audit.weaknesses_json = json.dumps([original_claim, 'contact or quote form not detected.'])
        session.add(GooglePresenceAssessment(lead_id=lead.id, confidence='Moderate',
                                            observed_gaps_json='["Public hours were not returned."]'))
        session.flush()
        before = CallGuideService().build(session, lead, [])
        assert original_claim in before.opening_15s
        capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        revise_finding(session, lead.id, 'website.check.tap_to_call', expected_revision=1, review_state='DISPUTED',
                       actor='Sammi', review_note='Owner says the sampled route is not the route customers use.')
        raw = audit.weaknesses_json
        plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.scope == ('hours and contact cleanup checklist',)
        assert pricing.price_available and context.offer_id == 'google_presence_cleanup'
        guide = CallGuideService().build(session, lead, [])
        assert original_claim not in guide.opening_15s
        drafts = OutreachService(SenderInfo(name='Sammi')).generate_all(lead, session=session, adaptive_plan=plan, pricing=pricing)
        assert original_claim not in str(drafts)
        proposal = ProposalService(config).generate_proposal(session, lead, selected_price=350).read_text(encoding='utf-8')
        assert 'tap_to_call=False' not in proposal and original_claim not in proposal
        assert 'hours and contact cleanup checklist' in proposal
        assert audit.weaknesses_json == raw


def verify_contact(session, lead, fact='website.check.tap_to_call'):
    capture_contact_finding(session, lead.id, fact, actor='Sammi')
    return revise_finding(session, lead.id, fact, expected_revision=1, review_state='VERIFIED', actor='Sammi',
                          review_note='Compared URL, capture date, recorded check and exact statement.', source_checked=True)


def test_rescan_retains_original_source_and_requires_explicit_new_review(storage):
    from local_presence_miner.database.repositories import audit_from_record, save_audit
    from local_presence_miner.domain.commercial import fingerprint

    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        old = verify_contact(session, lead)
        original = (old.source_snapshot_json, old.source_sha256, old.created_at)
        value = audit_from_record(audit)
        value.evidence['capture_note'] = 'New synthetic capture, same passive check.'
        save_audit(session, lead.id, value)
        view = project_findings(session, lead.id)[0]
        assert view['review_state'] == 'VERIFIED' and not view['source_matches_current']
        assert 'tap_to_call' not in reviewed_contact_audit(session, lead, audit).checks
        current = contact_source_snapshot(session, lead.id, 'website.check.tap_to_call')
        with pytest.raises(ValueError, match='changed since preview'):
            revise_finding(session, lead.id, old.finding_key, expected_revision=2, review_state='VERIFIED', actor='Sammi',
                           review_note='New scan review', source_checked=True, capture_current=True, expected_source_sha256='0' * 64)
        new = revise_finding(session, lead.id, old.finding_key, expected_revision=2, review_state='VERIFIED', actor='Sammi',
                             review_note='Reviewed this exact new source.', source_checked=True, capture_current=True,
                             expected_source_sha256=fingerprint(current))
        assert new.source_sha256 != old.source_sha256
        assert project_findings(session, lead.id)[0]['commercial_fact_eligible']
        assert (old.source_snapshot_json, old.source_sha256, old.created_at) == original


@pytest.mark.parametrize('state', ['UNREVIEWED', 'UNKNOWN', 'DISPUTED'])
def test_nonverified_contact_fact_is_unknown_to_commercial_policy_only_for_its_key(storage, state):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        if state != 'UNREVIEWED':
            revise_finding(session, lead.id, 'website.check.tap_to_call', expected_revision=1, review_state=state,
                           actor='Sammi', review_note='This specific observation needs clarification.')
        current = reviewed_contact_audit(session, lead, audit)
        assert 'tap_to_call' not in current.checks
        assert current.checks['contact_form'] is False
        assert current.checks['https'] is True
        assert json.loads(audit.checks_json)['tap_to_call'] is False


@pytest.mark.parametrize('change', ['stale', 'future', 'url_changed', 'missing_value', 'nonbusiness'])
def test_verified_review_never_upgrades_source_eligibility(storage, change):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        if change == 'stale':
            audit.created_at = utc_now() - timedelta(days=31)
        elif change == 'future':
            audit.created_at = utc_now() + timedelta(days=1)
        elif change == 'url_changed':
            lead.website = 'https://new-owner-site.example'
        elif change == 'missing_value':
            audit.checks_json = json.dumps({**BROKEN_ROUTE, 'tap_to_call': 'false'})
        else:
            audit.title = 'Account Suspended'
        session.flush()
        verify_contact(session, lead)
        view = project_findings(session, lead.id)[0]
        assert view['review_state'] == 'VERIFIED'
        assert not view['commercial_fact_eligible']
        assert 'tap_to_call' not in reviewed_contact_audit(session, lead, audit).checks


def test_corrupt_latest_source_fails_closed_without_reviving_prior_verification(storage):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        old = verify_contact(session, lead)
        # Simulate an imported/corrupt new row while preserving immutable prior rows.
        copy = {column.name: getattr(old, column.name) for column in ProspectFindingRevision.__table__.columns
                if column.name != 'id'}
        copy.update(revision=3, previous_id=old.id, source_snapshot_json='{"corrupt":true}')
        session.execute(ProspectFindingRevision.__table__.insert().values(**copy))
        view = project_findings(session, lead.id)[0]
        assert not view['valid'] and view['review_state'] == 'UNKNOWN'
        assert view['recorded_review_state'] == 'VERIFIED'
        assert 'tap_to_call' not in reviewed_contact_audit(session, lead, audit).checks
        assert finding_history(session, lead.id, old.finding_key)[1]['source_snapshot_json'] == old.source_snapshot_json


def test_source_ownership_links_and_stale_revision_are_enforced(storage):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        other, other_audit = add_business(session, place_id='other-synthetic-business')
        with pytest.raises(ValueError, match='another business'):
            capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi', audit_id=other_audit.id)
        row = capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        ref = f'finding_revision:{row.id}:{row.source_sha256}'
        assert validate_finding_references(session, lead.id, [ref]) == [ref]
        with pytest.raises(ValueError, match='another business'):
            validate_finding_references(session, other.id, [ref])
        revise_finding(session, lead.id, row.finding_key, expected_revision=1, review_state='UNKNOWN',
                       actor='Sammi', review_note='Needs confirmation')
        with pytest.raises(ValueError, match='changed'):
            revise_finding(session, lead.id, row.finding_key, expected_revision=1, review_state='DISPUTED',
                           actor='Another reviewer', review_note='Stale editor must not overwrite newer review')
        assert len(finding_history(session, lead.id, row.finding_key)) == 2


def test_two_sessions_cannot_fork_one_review_history(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE)
        row = capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        identity, key = lead.id, row.finding_key
        session.commit()
    with factory() as first, factory() as second:
        assert project_findings(first, identity)[0]['revision'] == project_findings(second, identity)[0]['revision'] == 1
        revise_finding(first, identity, key, expected_revision=1, review_state='UNKNOWN', actor='First', review_note='First review')
        first.commit()
        with pytest.raises(ValueError, match='changed'):
            revise_finding(second, identity, key, expected_revision=1, review_state='DISPUTED', actor='Second', review_note='Outdated review')
        second.rollback()
    with factory() as session:
        assert len(finding_history(session, identity, key)) == 2


def test_caller_rollback_and_commercial_refresh_failure_leave_no_partial_review(storage, monkeypatch):
    from local_presence_miner.services import commercial_state_service

    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE)
        identity = lead.id
        session.commit()
    with factory() as session:
        capture_contact_finding(session, identity, 'website.check.tap_to_call', actor='Sammi')
        session.rollback()
    with factory() as session:
        assert project_findings(session, identity) == []
        def fail_refresh(*_args, **_kwargs):
            raise RuntimeError('Synthetic commercial refresh failure')
        monkeypatch.setattr(commercial_state_service, 'recompute_lead_commercial_candidate', fail_refresh)
        with pytest.raises(RuntimeError, match='Synthetic'):
            capture_contact_finding(session, identity, 'website.check.tap_to_call', actor='Sammi')
        session.commit()
    with factory() as session:
        assert project_findings(session, identity) == []


@pytest.mark.parametrize('operation', ['update', 'delete', 'replace', 'lead_delete', 'audit_delete', 'audit_reassign'])
def test_sql_guards_preserve_history_and_ownership_with_legacy_fk_off(storage, operation):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        row = capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        session.commit()
        commands = {
            'update': 'UPDATE prospect_finding_revisions SET claim_text=\'changed\' WHERE id=:id',
            'delete': 'DELETE FROM prospect_finding_revisions WHERE id=:id',
            'replace': 'INSERT OR REPLACE INTO prospect_finding_revisions SELECT * FROM prospect_finding_revisions WHERE id=:id',
            'lead_delete': 'DELETE FROM leads WHERE id=:lead',
            'audit_delete': 'DELETE FROM website_audits WHERE id=:audit',
            'audit_reassign': 'UPDATE website_audits SET lead_id=999999 WHERE id=:audit',
        }
        with pytest.raises(IntegrityError):
            session.execute(text(commands[operation]), {'id': row.id, 'lead': lead.id, 'audit': audit.id})
        session.rollback()
        assert session.get(ProspectFindingRevision, row.id).claim_text == row.claim_text


def test_manual_review_and_correction_preserve_verbatim_attribution_without_authority_upgrade(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        original = '  I want easier editing.\nCan we compare UENI and Wix?  '
        row = record_owner_need(session, lead.id, actor='Sammi', owner_label='Hypothetical owner', source_text=original,
                                source_ref='Synthetic conversation only', source_text_mode='VERBATIM', attribution='OPERATOR_REPORTED_OWNER')
        assert json.loads(row.source_snapshot_json)['payload']['source_text'] == original
        revised = revise_finding(session, lead.id, row.finding_key, expected_revision=1, actor='Sammi', review_state='VERIFIED',
                                 review_note='Compared the note to the original wording; owner authority remains unknown.', source_checked=True)
        assert not project_findings(session, lead.id)[0]['commercial_fact_eligible']
        assert json.loads(revised.source_snapshot_json)['payload']['source_text'] == original
        assert session.execute(text('SELECT COUNT(*) FROM conversation_assertions')).scalar_one() == 0
        corrected = revise_finding(session, lead.id, row.finding_key, expected_revision=2, actor='Sammi', review_state='UNKNOWN',
                                   review_note='Corrected paraphrase; original date remains unknown.',
                                   corrected_manual_source={'owner_label': 'Hypothetical owner', 'source_text': 'Compare editing options.',
                                       'source_ref': 'Corrected synthetic note', 'source_text_mode': 'PARAPHRASED',
                                       'attribution': 'OPERATOR_REPORTED_OWNER'})
        assert json.loads(corrected.source_snapshot_json)['observed_at'] is None
        assert finding_history(session, lead.id, row.finding_key)[0]['source_snapshot_json'] == row.source_snapshot_json
        assert not project_findings(session, lead.id)[0]['commercial_fact_eligible']


def test_review_requires_procedure_and_does_not_bypass_contact_protections(storage):
    from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService

    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE, status='Do Not Contact', suppressed=True)
        before = (lead.status, lead.suppressed, lead.qualification_class, lead.phone)
        row = capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        with pytest.raises(ValueError, match='Verified requires'):
            revise_finding(session, lead.id, row.finding_key, expected_revision=1, review_state='VERIFIED', actor='Sammi', review_note='Read it')
        revise_finding(session, lead.id, row.finding_key, expected_revision=1, review_state='VERIFIED', actor='Sammi',
                       review_note='Checked capture URL, timestamp and exact observation.', source_checked=True)
        assert OutreachEligibilityService().evaluate(session, lead).is_blocked
        assert (lead.status, lead.suppressed, lead.qualification_class, lead.phone) == before


def test_provider_neutral_envelope_can_describe_future_sources_without_enabling_an_adapter():
    from local_presence_miner.domain.commercial import canonical_json, fingerprint
    from local_presence_miner.domain.prospect_findings import decode_snapshot

    source = {'schema_version': 1, 'source_kind': 'future_provider_observation.v1', 'subject': {'lead_id': 7},
              'observed_at': None, 'payload': {'provider': 'synthetic', 'model_version': 'unknown',
                                            'prompt_ref': 'immutable:prompt', 'response_ref': 'immutable:response',
                                            'tool_availability': 'UNKNOWN', 'repeated_runs': [], 'claim_kind': 'source_observation'}}
    assert decode_snapshot(canonical_json(source), fingerprint(source), 7) == source


def test_review_change_revokes_approval_preserves_human_text_and_selected_offer(storage):
    from local_presence_miner.database.repositories import save_outreach_draft
    from local_presence_miner.domain.enums import OutreachKind
    from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
    from local_presence_miner.services.commercial_state_service import draft_commercial_errors, persist_current_plan
    from local_presence_miner.services.search_offer_intelligence import accept_advisory_offer

    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE, recommended_offer_id='conversion_tune_up', recommended_offer='Conversion Tune-Up')
        verify_contact(session, lead)
        accept_advisory_offer(session, lead, 'conversion_tune_up', operator_confirmed=True)
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=price, context=context)
        human_text = 'Human-authored wording and previously discussed scope must remain exactly as recorded.'
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, 'Human subject', human_text,
                                    commercial_snapshot=snapshot.to_dict())
        draft.approved = True
        session.flush()
        assert not draft_commercial_errors(session, draft)
        revise_finding(session, lead.id, 'website.check.tap_to_call', expected_revision=2, review_state='DISPUTED',
                       actor='Sammi', review_note='The specific passive check needs rechecking.')
        assert not draft.approved and draft.commercial_dependency_state == 'stale'
        assert draft.body == human_text and draft.subject == 'Human subject'
        assert draft_commercial_errors(session, draft)
        _, _, after = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert after.offer_id == context.offer_id == 'conversion_tune_up'


@pytest.mark.parametrize('qualification,phone,expected', [
    ('Hold', '555-0100', 'RESEARCH_ONLY'), ('Reject', '555-0100', 'RESEARCH_ONLY'),
    ('Qualified', '', 'CONTACT_RESEARCH_REQUIRED'), ('Qualified', '555-0100', 'ELIGIBLE_FOR_HUMAN_REVIEW'),
])
def test_source_review_does_not_redefine_qualification_or_contactability(storage, qualification, phone, expected):
    from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService

    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE, qualification_class=qualification, phone=phone,
                               offer_resolution_state='canonical_id', recommended_offer_id='conversion_tune_up')
        before = OutreachEligibilityService().evaluate(session, lead).state.value
        verify_contact(session, lead)
        assert OutreachEligibilityService().evaluate(session, lead).state.value == before == expected


def test_guided_opportunity_links_pin_revision_and_preserve_old_worksheets(storage):
    from local_presence_miner.services.opportunity_workflow_service import latest_worksheet, save_worksheet

    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE)
        original = {'route': 'public_clue', 'observation': 'A synthetic contact-path clue', 'source_ref': 'Synthetic capture'}
        old = save_worksheet(session, lead, original)
        original_bytes = old.message
        row = capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        reference = f'finding_revision:{row.id}:{row.source_sha256}'
        save_worksheet(session, lead, {**original, 'finding_refs': [reference]})
        revise_finding(session, lead.id, row.finding_key, expected_revision=1, review_state='DISPUTED', actor='Sammi',
                       review_note='Later revision does not move the worksheet link.')
        assert latest_worksheet(session, lead.id)['data']['finding_refs'] == [reference]
        assert old.message == original_bytes
        assert json.loads(original_bytes)['observation'] == original['observation']


@pytest.mark.parametrize('foreign_keys', [False, True])
def test_additive_migration_backup_integrity_and_repeatability(tmp_path, foreign_keys):
    import sqlite3
    from pathlib import Path

    from local_presence_miner.database.engine import create_session_factory
    from local_presence_miner.database.migrations import initialize_database
    from local_presence_miner.database.schema import Base, Lead

    path = tmp_path / 'existing.sqlite3'
    factory = create_session_factory(path)
    engine = factory.kw['bind']
    # All pre-existing tables have unchanged definitions; only the new ledger is excluded.
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name != 'prospect_finding_revisions'])
    with factory() as session:
        lead = Lead(place_id='migration-synthetic', name='Synthetic existing business', notes='Keep original human notes',
                    qualification_class='Hold', google_public_data_json='{"details_retrieved":false}')
        session.add(lead)
        session.commit()
    initialize_database(factory)
    backup = Path(str(path) + '.backup-before-prospect-findings')
    assert backup.exists()
    before = backup.read_bytes()
    with sqlite3.connect(backup) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='prospect_finding_revisions'").fetchone()[0] == 0
        assert connection.execute('SELECT notes FROM leads').fetchone()[0] == 'Keep original human notes'
    initialize_database(factory)
    assert backup.read_bytes() == before
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=' + ('ON' if foreign_keys else 'OFF'))
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM prospect_finding_revisions').scalar() == 0
    with factory() as session:
        lead = session.scalar(select(Lead))
        assert lead.notes == 'Keep original human notes' and lead.qualification_class == 'Hold'
    engine.dispose()


def test_commercial_snapshot_and_withholding_remain_consistent_after_database_reopen(storage):
    from local_presence_miner.database.schema import Lead
    from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
    from local_presence_miner.services.call_guide_service import CallGuideService
    from local_presence_miner.services.commercial_state_service import current_plan_dependency_errors, persist_current_plan
    from local_presence_miner.services.proposal_service import ProposalService

    config, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        audit.weaknesses_json = '["tap-to-call link not detected."]'
        verify_contact(session, lead)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        identity, source = lead.id, project_findings(session, lead.id)[0]['source_sha256']
        assert not current_plan_dependency_errors(session, lead)
        session.commit()
    with factory() as session:
        lead = session.get(Lead, identity)
        assert not current_plan_dependency_errors(session, lead)
        assert project_findings(session, identity)[0]['source_sha256'] == source
        revise_finding(session, identity, 'website.check.tap_to_call', expected_revision=2, actor='Sammi',
                       review_state='DISPUTED', review_note='Recheck the exact sampled contact route.')
        session.commit()
    with factory() as session:
        lead = session.get(Lead, identity)
        assert 'tap-to-call link not detected.' not in CallGuideService().build(session, lead, []).opening_15s
        with pytest.raises(ValueError, match='does not support a paid proposal'):
            ProposalService(config).generate_proposal(session, lead, selected_price=350)
        proposal = ProposalService(config).generate_proposal(session, lead).read_text(encoding='utf-8')
        assert 'tap_to_call=False' not in proposal
        assert project_findings(session, identity)[0]['review_state'] == 'DISPUTED'


@pytest.mark.parametrize('fact', [
    'website.check.tap_to_call', 'website.check.contact_form', 'website.check.sitewide_contact_path',
    'website.check.viewport', 'website.check.clear_primary_cta',
])
def test_each_supported_fact_has_precise_withholding_and_source_label_binding(storage, fact):
    from local_presence_miner.domain.prospect_findings import CONTACT_FACTS
    from local_presence_miner.services.conversation_state_service import ConversationState
    from local_presence_miner.services.intervention_evidence_service import collect_intervention_evidence

    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        key, label = CONTACT_FACTS[fact]
        audit.weaknesses_json = json.dumps([f'{label} not detected.', 'Independent unchanged source note'])
        audit.strengths_json = json.dumps([label, 'Independent unchanged strength'])
        capture_contact_finding(session, lead.id, fact, actor='Sammi')
        projected = reviewed_contact_audit(session, lead, audit)
        assert key not in projected.checks
        assert projected.checks == {k: v for k, v in BROKEN_ROUTE.items() if k != key}
        assert projected.weaknesses == ['Independent unchanged source note']
        assert projected.strengths == ['Independent unchanged strength']
        # Removing the last commercial fact must not fabricate a retrieval failure.
        audit.checks_json = json.dumps({key: False})
        evidence = collect_intervention_evidence(session, lead, conversation=ConversationState())
        assert evidence.website_state == 'observed' and evidence.website_checks == {}


@pytest.mark.parametrize('raw', ['[]', 'null', '"false"', '{broken'])
def test_malformed_contact_check_containers_remain_unknown(storage, raw):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session)
        audit.checks_json = raw
        capture_contact_finding(session, lead.id, 'website.check.tap_to_call', actor='Sammi')
        assert not project_findings(session, lead.id)[0]['commercial_fact_eligible']
        assert 'tap_to_call' not in reviewed_contact_audit(session, lead, audit).checks
