"""R1-R4 observable boundaries, with confidential synthetic source text."""
import inspect
import json
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup
from test_ai_discoverability_findings import approve, source
from test_intervention_integration import add_business
from test_intervention_integration import storage as base_storage

from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.prospect_finding_service import (
    approved_ai_observations,
    finding_history,
    project_findings,
    proposal_ai_choices,
    record_ai_observation,
    record_owner_need,
    revise_finding,
)
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.time_utils import utc_now


@pytest.fixture(name='storage')
def setup_storage(tmp_path):
    config, factory = base_storage.__wrapped__(tmp_path)
    yield config, factory
    factory.kw['bind'].dispose()


def selected_argument(reference):
    # Enables the same behavioral reproduction against the immutable parent,
    # which had automatic inclusion and no selection argument.
    return {'ai_finding_refs':[reference]} if 'ai_finding_refs' in inspect.signature(ProposalService.generate_proposal).parameters else {}


def test_r1_confidential_source_is_preserved_internally_but_never_exported_without_disclosure_approval(storage):
    config, factory = storage
    private = 'CONFIDENTIAL_SYNTHETIC_OWNER_BUDGET_12345'
    with factory() as session:
        lead, _ = add_business(session)
        row = record_ai_observation(session, lead.id, actor='Sammi', **source(prompt=f'Find sign shops. Private note: {private}',
                    test_context=private, citations=[private], source_refs=[private], response='Synthetic Competitor Signs.'))
        approve(session, lead, row)
        observation = project_findings(session, lead.id)[0]
        assert private in observation['source_snapshot_json']
        path = ProposalService(config).generate_proposal(session, lead, **selected_argument(observation['reference']))
        assert private not in path.read_text(encoding='utf-8')
        assert private not in path.with_suffix('.commercial.json').read_text(encoding='utf-8')


def test_r2_proposals_default_to_no_ai_evidence(storage):
    config, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        row = record_ai_observation(session, lead.id, actor='Sammi', **source())
        approve(session, lead, row)
        path = ProposalService(config).generate_proposal(session, lead)
        assert 'Reviewed Manual AI Response Observations' not in path.read_text(encoding='utf-8')
        assert json.loads(path.with_suffix('.commercial.json').read_text())['dependencies']['manual_ai_observations'] == []
        assert project_findings(session, lead.id)[0]['customer_copy_approved']


@pytest.mark.parametrize('consumer',['proposal','report'])
def test_r3_customer_html_escapes_untrusted_text_and_retains_real_template_formatting(storage, consumer):
    config, factory = storage
    hostile = '<img src=x onerror="SYNTHETIC_ATTACK()"> O\'Brien & Sons'
    with factory() as session:
        lead, _ = add_business(session, name=hostile)
        path = (ProposalService(config).generate_proposal(session, lead) if consumer == 'proposal'
                else ReportService(config).generate_report(session, lead, 'owner_short'))
        html = path.read_text(encoding='utf-8')
        soup = BeautifulSoup(html,'html.parser')
        assert not soup.find('img',onerror=True)
        assert hostile in soup.get_text()
        assert soup.find('main') is not None and soup.find('h1') is not None
        assert '&lt;img' in html


def test_r4_naive_owner_need_time_is_rejected_or_qualified_as_unknown_timezone(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        try:
            row = record_owner_need(session, lead.id, actor='Sammi', owner_label='Synthetic owner', source_text='Need easier editing',
                    source_ref='Synthetic conversation', source_text_mode='PARAPHRASED', attribution='OPERATOR_REPORTED_OWNER',
                    observed_at='2026-11-08T09:15:00')
        except ValueError as exc:
            assert 'timezone' in str(exc).casefold()
        else:
            snapshot=json.loads(row.source_snapshot_json)
            view=project_findings(session,lead.id)[0]
            assert snapshot['observed_at'] is None or (view['freshness']=='UNKNOWN' and 'timezone' in view.get('timestamp_qualification','').casefold())


@pytest.mark.parametrize('state',['selected','unselected','stale','disputed','superseded','other_business'])
def test_r2_selection_revalidated_against_current_exact_eligible_revisions(storage,state):
    config, factory = storage
    with factory() as session:
        lead,_=add_business(session)
        row=record_ai_observation(session,lead.id,actor='Sammi',**source())
        reviewed=approve(session,lead,row)
        reference=project_findings(session,lead.id)[0]['reference']
        if state=='stale':
            revised=revise_finding(session,lead.id,row.finding_key,expected_revision=2,actor='Sammi',review_state='VERIFIED',
                review_note='Historical test review',source_checked=True,approve_customer_claim=True,
                corrected_ai_source=source(captured_at=(utc_now()-timedelta(days=31)).isoformat()))
            reference=f'finding_revision:{revised.id}:{revised.source_sha256}'
        elif state in {'disputed','superseded'}:
            revise_finding(session,lead.id,row.finding_key,expected_revision=2,actor='Sammi',review_state='DISPUTED',review_note='Recheck this response')
        if state=='other_business':
            from local_presence_miner.database.schema import Lead
            other=Lead(name='Other synthetic business',place_id='other-correction-target')
            session.add(other)
            session.flush()
            lead=other
        references=[] if state=='unselected' else [reference]
        if state in {'stale','disputed','superseded','other_business'}:
            with pytest.raises(ValueError,match='eligible'):
                ProposalService(config).generate_proposal(session,lead,ai_finding_refs=references)
        else:
            path=ProposalService(config).generate_proposal(session,lead,ai_finding_refs=references)
            assert ('Reviewed Manual AI Response Observations' in path.read_text(encoding='utf-8')) == (state=='selected')
        assert session.get(type(reviewed),reviewed.id).customer_copy_approved


def test_r1_review_preview_exactly_matches_complete_external_disclosure_and_survives_reopen(storage):
    from local_presence_miner.database.schema import Lead
    config,factory=storage
    with factory() as session:
        lead,_=add_business(session)
        row=record_ai_observation(session,lead.id,actor='Sammi',**source(prompt='SYNTHETIC_PRIVATE_QUERY',test_context='PRIVATE_CONTEXT'))
        approve(session,lead,row)
        identity=lead.id
        session.commit()
    with factory() as session:
        choices=proposal_ai_choices(session,identity)
        lead=session.get(Lead,identity)
        path=ProposalService(config).generate_proposal(session,lead,ai_finding_refs=[choices[0]['reference']])
        soup=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
        disclosure=soup.find('p',style='white-space: pre-wrap').get_text()
        assert disclosure==choices[0]['disclosure']
        assert 'SYNTHETIC_PRIVATE_QUERY' not in str(soup) and 'PRIVATE_CONTEXT' not in str(soup)


def test_r4_legacy_timezone_is_unknown_without_rewriting_source_and_explicit_correction_preserves_history(storage):
    from local_presence_miner.database.schema import Lead, ProspectFindingRevision
    from local_presence_miner.domain.commercial import canonical_json, fingerprint
    _,factory=storage
    original={'schema_version':1,'source_kind':'operator_attribution.v1','subject':{},'observed_at':'2026-11-08T09:15:00+00:00',
              'payload':{'owner_label':'Synthetic owner','source_text':'Need easier editing','source_ref':'Synthetic legacy note',
                         'source_text_mode':'PARAPHRASED','attribution':'OPERATOR_REPORTED_OWNER'}}
    with factory() as session:
        lead,_=add_business(session)
        original['subject']={'lead_id':lead.id}
        row=ProspectFindingRevision(lead_id=lead.id,finding_key='owner_need:legacy-test',revision=1,finding_type='manual_owner_need',
            assertion_kind='ATTRIBUTED_STATEMENT',fact_id='',source_snapshot_json=canonical_json(original),source_sha256=fingerprint(original),
            claim_text='Need easier editing',review_state='VERIFIED',source_checked=True,customer_copy_approved=False,
            actor_id='Sammi',review_note='Historical source review')
        session.add(row)
        session.flush()
        old_bytes=row.source_snapshot_json
        view=project_findings(session,lead.id)[0]
        assert view['valid'] and view['review_state']=='VERIFIED' and view['freshness']=='UNKNOWN'
        assert 'not verified UTC' in view['timestamp_qualification']
        revised=revise_finding(session,lead.id,row.finding_key,expected_revision=1,actor='Sammi',review_state='UNKNOWN',
            review_note='Original local offset established from the note',
            corrected_manual_source={**original['payload'],'observed_at':'2026-11-08T09:15:00-07:00'})
        stamp=json.loads(revised.source_snapshot_json)
        assert stamp['observed_at']=='2026-11-08T16:15:00+00:00'
        assert stamp['payload']['observed_at_original']=='2026-11-08T09:15:00-07:00'
        identity,key=lead.id,row.finding_key
        session.commit()
    with factory() as session:
        assert session.get(Lead,identity)
        history=finding_history(session,identity,key)
        assert history[0]['source_snapshot_json']==old_bytes
        assert history[0]['freshness']=='UNKNOWN'
        assert history[1]['source']['payload']['timezone_provenance']=='EXPLICIT_OFFSET'


def test_existing_finding_ledger_upgrade_preserves_rows_and_requires_new_disclosure_approval(storage):
    import sqlite3
    from pathlib import Path

    from local_presence_miner.database.migrations import initialize_database
    from local_presence_miner.database.schema import Lead
    config,factory=storage
    engine=factory.kw['bind']
    with factory() as session:
        lead,_=add_business(session)
        row=record_ai_observation(session,lead.id,actor='Sammi',**source())
        reviewed=approve(session,lead,row)
        original=(reviewed.source_snapshot_json,reviewed.source_sha256,reviewed.review_state,reviewed.customer_copy_approved)
        identity=lead.id
        session.commit()
    # A disposable fixture recreates the exact missing-column condition of Pass 1.
    with engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE prospect_finding_revisions DROP COLUMN customer_copy_contract_version')
    initialize_database(factory)
    backup=Path(str(config.database_path)+'.backup-before-finding-disclosure-v2')
    assert backup.exists()
    original_backup=backup.read_bytes()
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert 'customer_copy_contract_version' not in {r[1] for r in db.execute('PRAGMA table_info(prospect_finding_revisions)')}
    initialize_database(factory)
    assert backup.read_bytes()==original_backup
    with factory() as session:
        lead=session.get(Lead,identity)
        heads=project_findings(session,identity)
        assert heads[0]['customer_copy_approved'] and heads[0]['customer_copy_contract_version']==0
        assert approved_ai_observations(session,identity)==[]
        assert (heads[0]['source_snapshot_json'],heads[0]['source_sha256'],heads[0]['review_state'],heads[0]['customer_copy_approved'])==original
        revised=revise_finding(session,identity,heads[0]['finding_key'],expected_revision=2,actor='Sammi',review_state='VERIFIED',
            review_note='Approved the complete v2 external disclosure',source_checked=True,approve_customer_claim=True)
        assert revised.customer_copy_contract_version==2 and len(approved_ai_observations(session,identity))==1
        assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').fetchall()==[]


def test_r2_selecting_one_of_two_keeps_other_approval_private_and_intact(storage):
    config,factory=storage
    with factory() as session:
        lead,_=add_business(session)
        first=record_ai_observation(session,lead.id,actor='Sammi',**source())
        approve(session,lead,first)
        second=record_ai_observation(session,lead.id,actor='Sammi',**source(provider='Claude',prompt='SYNTHETIC_EXCLUDED_PROMPT'))
        approve(session,lead,second)
        choices=proposal_ai_choices(session,lead.id)
        selected=next(choice for choice in choices if 'ChatGPT response' in choice['disclosure'])
        path=ProposalService(config).generate_proposal(session,lead,ai_finding_refs=[selected['reference']])
        text=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser').get_text()
        assert 'ChatGPT response' in text and 'Claude response' not in text
        packet=json.loads(path.with_suffix('.commercial.json').read_text())['dependencies']['manual_ai_observations']
        assert packet==[selected]
        assert len(approved_ai_observations(session,lead.id))==2
