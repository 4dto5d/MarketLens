"""Manual AI captures remain response evidence, not an automatic sales engine."""
import json
from datetime import timedelta

import pytest
from test_intervention_integration import add_business
from test_prospect_findings import setup_storage as storage_fixture

from local_presence_miner.database.schema import Lead
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.prospect_finding_service import (
    approved_ai_observations,
    finding_history,
    project_findings,
    record_ai_observation,
    revise_finding,
    validate_finding_references,
)
from local_presence_miner.time_utils import utc_now


@pytest.fixture(name='storage')
def setup_storage(tmp_path):
    yield from storage_fixture.__wrapped__(tmp_path)


def source(**changes):
    return {'provider':'ChatGPT', 'model':'Recorded model', 'model_version':'UNKNOWN',
            'prompt':'Which sign shops near Alamosa could make a storefront sign?',
            'response':'  Synthetic Competitor Signs is one possibility.\nCheck current details.  ',
            'captured_at':utc_now().isoformat(), 'test_context':'Synthetic Alamosa context; location/account not independently verified',
            'browsing_available':'YES', 'browsing_used':'UNKNOWN', 'prospect_mention':'NOT_MENTIONED',
            'mentioned_businesses':['Synthetic Competitor Signs'], 'omitted_businesses':['Specific Local Service'],
            'competitor_mentions':['Synthetic Competitor Signs'], 'citations':['https://competitor.example/source'],
            'source_refs':['Synthetic manual transcript A'], **changes}


def approve(session, lead, row, **changes):
    return revise_finding(session, lead.id, row.finding_key, expected_revision=row.revision, actor='Sammi',
                          review_state='VERIFIED', review_note='Checked exact prompt, complete response, identity, date and manual annotation.',
                          source_checked=True, approve_customer_claim=True, **changes)


def test_manual_response_reopen_history_and_explicit_proposal_approval_do_not_change_offer_or_price(storage):
    config, factory = storage
    data = source()
    with factory() as session:
        lead, _ = add_business(session)
        before_plan, before_price, before_context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        row = record_ai_observation(session, lead.id, actor='Sammi', **data)
        assert approved_ai_observations(session, lead.id) == []
        original = row.source_snapshot_json
        assert json.loads(original)['payload']['response'] == data['response']
        identity, key = lead.id, row.finding_key
        reviewed = approve(session, lead, row)
        _, after_price, after_context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert before_context.dependency_dict() == after_context.dependency_dict()
        assert before_price.recommended == after_price.recommended and before_price.price_available == after_price.price_available
        assert not project_findings(session, identity)[0]['commercial_fact_eligible']
        assert not before_price.price_available
        with pytest.raises(ValueError, match='does not support a paid proposal'):
            ProposalService(config).generate_proposal(session, lead, selected_price=350)
        assert reviewed.customer_copy_approved
        session.commit()
    with factory() as session:
        lead = session.get(Lead, identity)
        eligible = approved_ai_observations(session, identity)
        assert len(eligible) == 1 and eligible[0]['customer_claim_eligible']
        assert approved_ai_observations(session, identity, now=utc_now()+timedelta(days=31)) == []
        assert validate_finding_references(session, identity, [eligible[0]['reference']])
        proposal_path = ProposalService(config).generate_proposal(session, lead, ai_finding_refs=[eligible[0]['reference']])
        html = proposal_path.read_text(encoding='utf-8')
        assert 'Reviewed Manual AI Response Observations' in html and data['prompt'] not in html
        assert data['response'] == eligible[0]['source']['payload']['response']
        assert 'single manually captured ChatGPT response' in html and 'not overall AI visibility' in html
        assert 'was not mentioned' in html and data['captured_at'] in html
        revise_finding(session, identity, key, expected_revision=2, actor='Sammi', review_state='DISPUTED',
                       review_note='A trading-name alias may have been missed.')
        assert approved_ai_observations(session, identity) == []
        new_path = ProposalService(config).generate_proposal(session, lead)
        assert new_path != proposal_path
        assert 'Reviewed Manual AI Response Observations' not in new_path.read_text(encoding='utf-8')
        assert proposal_path.read_text(encoding='utf-8') == html
        assert all(item['source_snapshot_json'] == original for item in finding_history(session, identity, key))


@pytest.mark.parametrize('change', ['unreviewed','source_review_only','unknown_date','future','stale','unclear','identity_changed','corrupt'])
def test_uncertain_or_unapproved_response_claims_fail_closed_precisely(storage, change):

    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        data = source()
        if change == 'unknown_date':
            data['captured_at'] = None
        if change == 'future':
            data['captured_at'] = (utc_now()+timedelta(days=1)).isoformat()
        if change == 'stale':
            data['captured_at'] = (utc_now()-timedelta(days=31)).isoformat()
        if change == 'unclear':
            data['prospect_mention'] = 'UNCLEAR'
        row = record_ai_observation(session, lead.id, actor='Sammi', **data)
        if change == 'source_review_only':
            revise_finding(session, lead.id, row.finding_key, expected_revision=1, actor='Sammi', review_state='VERIFIED',
                           review_note='Checked source; no approval for customer-facing wording.', source_checked=True)
        elif change != 'unreviewed':
            row = approve(session, lead, row)
        if change == 'identity_changed':
            lead.name = 'Different business identity'
        if change == 'corrupt':
            copy = {column.name:getattr(row,column.name) for column in row.__table__.columns if column.name != 'id'}
            copy.update(revision=3, previous_id=row.id, source_sha256='0'*64)
            session.execute(row.__table__.insert().values(**copy))
        assert approved_ai_observations(session, lead.id) == []
        # An unrelated, separately reviewed observation is not suppressed.
        second = record_ai_observation(session, lead.id, actor='Sammi', **source(provider='Claude', prospect_mention='MENTIONED',
                                               response=f'{lead.name} was mentioned in this synthetic test.', omitted_businesses=[]))
        approve(session, lead, second)
        assert len(approved_ai_observations(session, lead.id)) == 1
        assert approved_ai_observations(session, lead.id)[0]['source']['payload']['provider'] == 'Claude'


def test_correction_does_not_transfer_copy_approval_and_keeps_exact_source_and_links(storage):
    from local_presence_miner.services.opportunity_workflow_service import latest_worksheet, save_worksheet

    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        row = record_ai_observation(session, lead.id, actor='Sammi', **source())
        old = approve(session, lead, row)
        reference = project_findings(session, lead.id)[0]['reference']
        save_worksheet(session, lead, {'route':'public_clue', 'observation':'One manual response needs owner discussion',
                                      'source_ref':'Synthetic AI capture', 'finding_refs':[reference]})
        revised = revise_finding(session, lead.id, row.finding_key, expected_revision=2, actor='Sammi', review_state='VERIFIED',
                                 review_note='Corrected transcript; customer copy has not been reapproved.', source_checked=True,
                                 corrected_ai_source=source(response='Different exact response.', prospect_mention='UNCLEAR'))
        assert revised.source_sha256 != old.source_sha256 and not revised.customer_copy_approved
        assert approved_ai_observations(session, lead.id) == []
        assert validate_finding_references(session, lead.id, [reference]) == [reference]
        assert latest_worksheet(session, lead.id)['data']['finding_refs'] == [reference]
        assert finding_history(session, lead.id, row.finding_key)[1]['source_snapshot_json'] == old.source_snapshot_json


@pytest.mark.parametrize('changes', [{'provider':'Other'}, {'prompt':''}, {'response':''},
                                    {'captured_at':'2026-11-08T12:00:00'}, {'browsing_available':'NO','browsing_used':'YES'},
                                    {'response':'Specific Local Service appears here.'},
                                    {'mentioned_businesses':['Specific Local Service']}])
def test_bad_capture_metadata_rejected_without_querying_a_provider(storage, changes):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        with pytest.raises(ValueError):
            record_ai_observation(session, lead.id, actor='Sammi', **source(**changes))
        assert project_findings(session, lead.id) == []


def test_proposal_keeps_prompt_private_escapes_approved_fields_and_never_repeats_model_facts(storage):
    config, factory = storage
    with factory() as session:
        lead, _ = add_business(session, status='Do Not Contact', suppressed=True)
        row = record_ai_observation(session, lead.id, actor='Sammi', **source(prompt='<script>unsafe()</script>', model='<b>Recorded model</b>',
                                                       response='MODEL CLAIM: The business revenue is $999999.'))
        approve(session, lead, row)
        reference = project_findings(session,lead.id)[0]['reference']
        html = ProposalService(config).generate_proposal(session, lead, ai_finding_refs=[reference]).read_text(encoding='utf-8')
        assert 'unsafe()' not in html and '&lt;b&gt;Recorded model&lt;/b&gt;' in html
        assert 'MODEL CLAIM' not in html and '$999999' not in html
        assert lead.status == 'Do Not Contact' and lead.suppressed


def test_explicit_trading_alias_can_support_only_its_recorded_response_mention(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        row = record_ai_observation(session, lead.id, actor='Sammi', **source(response='SLS is one option.', prospect_mention='MENTIONED',
                                   prospect_aliases=['SLS'], mentioned_businesses=['SLS'], omitted_businesses=[]))
        approve(session, lead, row)
        assert approved_ai_observations(session, lead.id)[0]['source']['payload']['prospect_aliases'] == ['SLS']
