"""Source disclosure and consumed dependency changes through real SQLite services."""
from datetime import timedelta
from threading import Event

import pytest
from test_opportunity_intelligence import FakeTransport, execute, prepare
from test_opportunity_intelligence import setup as base_setup
from test_search_offer_integration import _run, _setup

from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.enums import AssertionSourceKind, AssertionSourceTextMode
from local_presence_miner.domain.intelligence_research import research_cards
from local_presence_miner.domain.opportunity_intelligence import canonical
from local_presence_miner.services.conversation_state_service import ConversationStateService
from local_presence_miner.services.opportunity_intelligence_service import LocalRequestBudget, OpportunityIntelligenceService
from local_presence_miner.services.owner_strategy_service import append_owner_strategy
from local_presence_miner.time_utils import utc_now


@pytest.fixture(name='setup')
def setup_fixture(tmp_path):
    yield from base_setup.__wrapped__(tmp_path)


def test_goal_is_precisely_opt_in_and_withheld_coverage_is_visible(setup):
    _, factory, identity, service = setup
    text = 'CONFIDENTIAL: reduce estimator calls; do not add demand.'
    with factory() as session:
        ConversationStateService().append_assertion(session, session.get(Lead, identity), subject_key='business.goal', value=text,
            source_kind=AssertionSourceKind.OWNER_LITERAL, source_text=text, source_text_mode=AssertionSourceTextMode.VERBATIM)
        session.commit()
    private = prepare(service, identity)
    assert text not in canonical(private['body'])
    assert private['packet']['coverage']['owner_context']['recorded_fields'] == ['goal']
    included = prepare(service, identity, include_owner_context=True)
    assert text in canonical(included['body'])
    assert included['packet']['source_registry']['owner_goal']['type'] == 'owner_report'
    assert included['cache_key'] != private['cache_key']


@pytest.mark.parametrize('area', [
    *[{'kind':'zip','country':'US','state':'CO','postal_codes':[code], 'original_wording':'Synthetic desired ZIP'}
      for code in ['81101', '81003', '80903']],
    {'kind':'city','country':'US','state':'CO','city':'Colorado Springs','original_wording':'Synthetic city preference'},
    {'kind':'radius','country':'US','state':'CO','center':{'latitude':38.83,'longitude':-104.82},
     'radius_miles':10,'original_wording':'Synthetic radius preference'},
])
def test_owner_area_never_becomes_measured_geography(setup, area):
    _, factory, identity, service = setup
    with factory() as session:
        append_owner_strategy(session, session.get(Lead, identity),
            {'schema_version':1, 'constraints':[], 'target_territories':[area]}, source_text='Synthetic owner preference', owner_confirmed=True)
        session.commit()
    packet = prepare(service, identity, include_market=True, include_owner_context=True)['packet']
    assert packet['subject']['geography']['owner_desired_area'][0]['kind'] == area['kind']
    assert not packet['market_context']['eligible']
    assert 'preference' in packet['subject']['geography']['measured_market_area']


def test_cards_operator_context_reasoning_are_bound_and_raw_response_survives(setup):
    _, _, identity, service = setup
    cards = research_cards()
    prepared = prepare(service, identity, mode='Full Prospect', model='gpt-6.1-sol', reasoning_effort='high',
                       research_ids=[cards[0]['id']], operator_context={'experience':'Self-report', 'demonstration':'Synthetic sample'})
    assert prepared['body']['reasoning'] == {'effort':'high'}
    assert prepared['packet']['source_registry']['R1']['type'] == 'research_method'
    result = execute(service, prepared)
    history = service.history(identity)[0]
    assert history['result']['text']
    assert history['result']['presentation'] == result['advice']
    assert history['eligibility']['current']
    with pytest.raises(ValueError, match='different|Unsupported'):
        prepare(service, identity, model='not-supported', reasoning_effort='high')


def test_selected_card_corruption_blocks_dispatch_without_network(setup, monkeypatch, tmp_path):
    import local_presence_miner.domain.intelligence_research as research
    _, _, identity, service = setup
    prepared = prepare(service, identity, research_ids=['sign_print'], mode='Full Prospect')
    corrupt = tmp_path/'corrupt.json'
    corrupt.write_text('{}')
    monkeypatch.setattr(research, 'RESEARCH_PATH', corrupt)
    transport = FakeTransport()
    with pytest.raises(ValueError, match='catalog'):
        execute(service, prepared, transport)
    assert transport.calls == 0


def test_rejected_advice_is_historical_and_requires_a_new_explicit_request(setup):
    _, _, identity, service = setup
    prepared = prepare(service, identity, include_worksheet=True)
    transport = FakeTransport()
    first = execute(service, prepared, transport)
    service.review(first['run_id'], lead_id=identity, account_binding='a'*64, actor='Operator', action='rejected')
    assert not service.history(identity)[0]['eligibility']['current']
    with pytest.raises(ValueError, match='rejected'):
        service.adopt(first['run_id'], lead_id=identity, account_binding='a'*64,
                      item_id='q1', actor='Operator', edited_text='Do not restore rejected advice')
    second = execute(service, prepare(service, identity, include_worksheet=True), transport)
    assert second['run_id'] != first['run_id'] and not second['cached']
    assert transport.calls == 2


def test_consumed_real_market_expiry_and_new_partial_run_invalidate(tmp_path):
    config, factory, identity = _setup(tmp_path, google=True)
    _run(config, factory)
    service = OpportunityIntelligenceService(factory, budget=LocalRequestBudget(tmp_path/'budget'))
    prepared = prepare(service, identity, include_market=True, mode='Full Prospect')
    assert prepared['packet']['market_context']['eligible']
    with factory() as session:
        future, _ = service._projection(session, identity, [], False, utc_now()+timedelta(days=31),
                                         prepared['packet']['context_options'])
    assert not future['market_context']['eligible']
    _run(config, factory, mode='truncated')
    transport = FakeTransport()
    with pytest.raises(ValueError, match='changed'):
        service.execute(prepared, transport, cancel=Event(), current_account=lambda:'a'*64)
    assert transport.calls == 0
    assert not prepare(service, identity, include_market=True, include_owner_context=True)['packet']['market_context']['eligible']
    factory.kw['bind'].dispose()
