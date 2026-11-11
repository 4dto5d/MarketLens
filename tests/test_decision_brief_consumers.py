"""Independent consumer-boundary controls for the decision brief."""
import json
from threading import Event

import pytest
from test_intervention_integration import BROKEN_ROUTE, HEALTHY_CHECKS, add_business, storage
from test_opportunity_intelligence import FakeTransport

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.schema import Lead
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.opportunity_intelligence_service import LocalRequestBudget, OpportunityIntelligenceService
from local_presence_miner.services.opportunity_workflow_service import latest_worksheet, save_worksheet
from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.proposal_service import ProposalService


@pytest.mark.parametrize('category,checks,changes', [
    ('sign shop', HEALTHY_CHECKS, {}),
    ('commercial cleaning', BROKEN_ROUTE, {}),
    ('plumber', BROKEN_ROUTE, {'qualification_class': 'Hold'}),
    ('sign shop', HEALTHY_CHECKS, {'suppressed': True}),
    ('wellness', HEALTHY_CHECKS, {'qualification_class': 'Hold'}),
])
def test_actual_consumers_unchanged_after_inference_and_explicit_adoption(tmp_path, category, checks, changes):
    config, factory = storage.__wrapped__(tmp_path)
    with factory() as session:
        lead, _ = add_business(session, category=category, checks=checks, **changes)
        save_worksheet(session, lead, {'route': 'owner_report', 'owner_reported': True,
            'source_ref': 'Synthetic owner conversation; no real outreach',
            'observation': 'An owner request remains to be confirmed.',
            'owner_question': 'Original human question', 'next_action': 'Original human action'})
        identity = lead.id
        session.commit()
    service = OpportunityIntelligenceService(factory, budget=LocalRequestBudget(tmp_path/'budget'))

    def consumers():
        with factory() as session:
            lead = session.get(Lead, identity)
            plan, price, context = build_adaptive_sales_plan_with_context(session, lead)
            delivery = DeliveryPacketService().build(session, lead)
            guide = CallGuideService().build(session, lead, [])
            eligibility = OutreachEligibilityService().evaluate(session, lead)
            try:
                proposal = ProposalService(config).generate_proposal(session, lead).read_text(encoding='utf-8')
            except ValueError as error:
                proposal = str(error)
            return {'canonical': context.offer_id, 'scope': list(context.scope),
                'price': str(price.recommended), 'price_available': price.price_available,
                'qualification': lead.qualification_class, 'suppressed': lead.suppressed,
                'delivery_ready': delivery['ready_for_payment'], 'delivery_state': delivery['state'],
                'eligibility': eligibility.state.value, 'eligibility_reasons': list(eligibility.reasons),
                'guide': guide.opening_15s,
                'drafts': str(OutreachService(SenderInfo(name='Synthetic')).generate_all(
                    lead, session=session, adaptive_plan=plan, pricing=price)), 'proposal': proposal}
    before = consumers()
    prepared = service.prepare(identity, question='Which owner question comes next?', mode='Focused',
        model='fixture-model', account_binding='a'*64, include_worksheet=True)
    result = service.execute(prepared, FakeTransport(), cancel=Event(), current_account=lambda: 'a'*64)
    assert consumers() == before
    service.adopt(result['run_id'], lead_id=identity, account_binding='a'*64,
        item_id='q1', actor='Synthetic operator', edited_text='Which specific task is blocked?')
    assert consumers() == before
    with factory() as session:
        worksheet = latest_worksheet(session, identity)
        assert worksheet['data']['owner_question'].startswith('Original human question\nAI-assisted operator planning:')
        assert worksheet['data']['next_action'] == 'Original human action'
    assert consumers() == before  # independent sessions reopen all consumers
    if changes.get('suppressed'):
        assert before['eligibility'] == 'BLOCKED_COMPLIANCE'
    if changes.get('qualification_class') == 'Hold':
        assert not before['delivery_ready']
    (tmp_path/'consumer_receipt.json').write_text(json.dumps({'before':before,'after':consumers()},indent=2))
    factory.kw['bind'].dispose()
