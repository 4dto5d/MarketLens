"""Native Qt controls disclose selected context without implicit provider requests."""
import os
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog
from test_opportunity_intelligence import FakeTransport, execute, prepare
from test_opportunity_intelligence import setup as base_setup

from local_presence_miner.ui.widgets import opportunity_intelligence_widget as ui


@pytest.fixture(name='setup')
def setup_fixture(tmp_path):
    yield from base_setup.__wrapped__(tmp_path)


class Account:
    def account(self):
        return {'binding':'a'*64, 'label':'Synthetic account'}


def test_every_new_disclosure_control_reaches_exact_cancelled_preview(setup, monkeypatch):
    app = QApplication.instance() or QApplication([])
    _, factory, identity, service = setup
    widget = ui.OpportunityIntelligenceWidget(factory, identity, auth=Account(), service=service)
    assert not widget.enabled.isChecked()
    assert not widget.include_owner_context.isChecked()
    assert not widget.include_market.isChecked()
    assert not widget.include_commercial_explanation.isChecked()
    assert not widget.include_operator.isChecked()
    widget.enabled.setChecked(True)
    widget.models.addItem('Sol', 'gpt-6.1-sol')
    widget.effort.setCurrentIndex(widget.effort.findData('high'))
    widget.mode.setCurrentText('Full Prospect')
    widget.question.setText('Synthetic service decision?')
    for flag in [widget.include_owner_context, widget.include_market, widget.include_commercial_explanation,
                 widget.include_worksheet, widget.include_operator]:
        flag.setChecked(True)
    widget.operator_fields['experience'].setText('Synthetic self-report, not proven competence')
    widget.research.item(0).setCheckState(Qt.CheckState.Checked)
    captured = []
    class Preview:
        def __init__(self, prepared, *args):
            captured.append(prepared)
        def exec(self):
            return QDialog.DialogCode.Rejected
    monkeypatch.setattr(ui, 'ContextPreviewDialog', Preview)
    monkeypatch.setattr(widget, '_start', lambda *args: pytest.fail('Cancelled preview dispatched a worker'))
    widget.preview()
    assert len(captured) == 1, widget.status.text()
    packet = captured[0]['packet']
    assert packet['coverage']['owner_context']['included']
    assert packet['coverage']['commercial_explanation_included']
    assert packet['coverage']['market_included']
    assert packet['operator_context']['experience'].startswith('Synthetic')
    assert len(packet['research_context']) == 1
    assert captured[0]['body']['reasoning'] == {'effort':'high'}
    assert service.history(identity) == []
    widget.close()
    app.processEvents()


def test_readable_history_sources_and_no_automatic_adoption(setup):
    app = QApplication.instance() or QApplication([])
    _, factory, identity, service = setup
    execute(service, prepare(service, identity, include_worksheet=True))
    widget = ui.OpportunityIntelligenceWidget(factory, identity, auth=Account(), service=service)
    widget.enabled.setChecked(True)
    widget.history()
    text = widget.output.toPlainText()
    assert 'Current eligibility:' in text and 'Questions to ask next' in text
    assert 'context_hash' not in text
    assert widget.sources.count() >= 6
    assert not widget.adopt_button.isEnabled()
    widget.close()
    app.processEvents()


def test_existing_workflow_navigation_is_connected_and_can_save(setup):
    from local_presence_miner.ui.dialogs.opportunity_workflow_dialog import OpportunityWorkflowDialog
    app = QApplication.instance() or QApplication([])
    _, factory, identity, _ = setup
    dialog = OpportunityWorkflowDialog(factory, identity)
    dialog.intelligence.destination_requested.emit('Record Contact')
    assert dialog.destination == 'Record Contact'
    assert dialog.result() == QDialog.DialogCode.Accepted
    app.processEvents()


def configured_widget(factory, identity, service):
    widget = ui.OpportunityIntelligenceWidget(factory, identity, auth=Account(), service=service)
    widget.enabled.setChecked(True)
    widget.models.addItem('Synthetic model', 'fixture-model')
    widget.question.setText('What must I verify before preparing the sample?')
    widget.include_operator.setChecked(True)
    widget.operator_fields['assistance'].setText('Assistant available on Friday')
    return widget


def dispatch_pending(widget, monkeypatch):
    class Preview:
        def __init__(self, *args):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    pending = []
    monkeypatch.setattr(ui, 'ContextPreviewDialog', Preview)

    def start(function, kind):
        widget.cancel_event = Event()
        widget.busy = True
        widget.generation += 1
        pending.append((kind, widget.generation, function))
        widget.toggle(True)

    monkeypatch.setattr(widget, '_start', start)
    widget.inference = FakeTransport()
    widget.preview()
    assert len(pending) == 1, widget.status.text()
    return pending[0]


def finish_pending(widget, pending):
    kind, generation, function = pending
    widget._finished((True, (kind, generation, function())))


def test_assistance_change_blocks_obsolete_ui_adoption_and_fresh_question_saves(setup, monkeypatch):
    from local_presence_miner.services.opportunity_workflow_service import latest_worksheet

    app = QApplication.instance() or QApplication([])
    _, factory, identity, service = setup
    widget = configured_widget(factory, identity, service)
    finish_pending(widget, dispatch_pending(widget, monkeypatch))
    assert widget.adopt_button.isEnabled()
    original_run = widget.result['run_id']
    original_signature = widget._result_request_signature
    widget.items.setCurrentIndex(0)
    widget.operator_fields['assistance'].setText('No assistant available')
    assert widget.result is None and not widget.adopt_button.isEnabled()
    current = widget._prepare_current()
    assert current['request_signature'] != original_signature
    with pytest.raises(ValueError, match='request changed'):
        service.adopt(original_run, lead_id=identity, account_binding='a' * 64,
                      item_id='q1', actor='Synthetic operator', edited_text='Obsolete assistant planning',
                      active_request_signature=current['request_signature'])
    widget.adopt()
    with factory() as session:
        assert latest_worksheet(session, identity)['data']['owner_question'] == 'Human question retained'

    widget.question.setText('With no assistant, which capability must I verify?')
    finish_pending(widget, dispatch_pending(widget, monkeypatch))
    widget.items.setCurrentIndex(0)
    monkeypatch.setattr(ui.QInputDialog, 'getMultiLineText', lambda *args: ('Which task can I demonstrate without assistance?', True))
    monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args: ('Synthetic operator', True))
    widget.adopt()
    with factory() as session:
        saved = latest_worksheet(session, identity)['data']
        assert saved['owner_question'].startswith('Human question retained\nAI-assisted operator planning:')
        assert 'Which task can I demonstrate without assistance?' in saved['owner_question']
        assert 'Obsolete assistant planning' not in saved['owner_question']
    assert 'Saved planning note' in widget.status.text()
    assert len(service.history(identity)) == 2
    widget.close()
    app.processEvents()


@pytest.mark.parametrize('block_change_signal', [False, True])
def test_inflight_input_change_does_not_activate_late_completed_result(setup, monkeypatch, block_change_signal):
    app = QApplication.instance() or QApplication([])
    _, factory, identity, service = setup
    widget = configured_widget(factory, identity, service)
    pending = dispatch_pending(widget, monkeypatch)
    kind, generation, function = pending
    # Complete and retain the real service result before the UI receives its queued signal.
    result = function()
    widget.operator_fields['assistance'].blockSignals(block_change_signal)
    widget.operator_fields['assistance'].setText('No assistant available')
    widget.operator_fields['assistance'].blockSignals(False)
    widget._finished((True, (kind, generation, result)))
    assert widget.result is None and not widget.adopt_button.isEnabled()
    assert widget.items.count() == 0
    assert ('inputs changed' if block_change_signal else 'late results were not activated') in widget.status.text()
    assert len(service.history(identity)) == 1
    widget.close()
    app.processEvents()


def test_adoption_rechecks_active_inputs_even_when_change_signals_are_blocked(setup, monkeypatch):
    from local_presence_miner.services.opportunity_workflow_service import latest_worksheet

    app = QApplication.instance() or QApplication([])
    _, factory, identity, service = setup
    widget = configured_widget(factory, identity, service)
    finish_pending(widget, dispatch_pending(widget, monkeypatch))
    widget.items.setCurrentIndex(0)
    widget.operator_fields['assistance'].blockSignals(True)
    widget.operator_fields['assistance'].setText('No assistant available')
    widget.operator_fields['assistance'].blockSignals(False)
    monkeypatch.setattr(ui.QInputDialog, 'getMultiLineText', lambda *args: ('Obsolete suggestion', True))
    monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args: ('Synthetic operator', True))
    warnings = []
    monkeypatch.setattr(ui.QMessageBox, 'warning', lambda *args: warnings.append(args[-1]))
    widget.adopt()
    assert warnings and 'inputs changed' in warnings[0]
    assert widget.result is None and not widget.adopt_button.isEnabled()
    with factory() as session:
        assert latest_worksheet(session, identity)['data']['owner_question'] == 'Human question retained'
    widget.close()
    app.processEvents()


@pytest.mark.parametrize('metadata, expected_model, expected_effort', [
    ({}, 'Unavailable', 'Unavailable'),
    ({'provider_model': 'synthetic-build', 'provider_reasoning_effort': 'medium'}, 'synthetic-build', 'medium'),
])
def test_history_distinguishes_requested_provider_settings_and_policy(setup, metadata, expected_model, expected_effort):
    from local_presence_miner.domain.opportunity_intelligence import VERSION

    class Receipt(FakeTransport):
        def run(self, *args, **kwargs):
            return {**super().run(*args, **kwargs), **metadata}

    app = QApplication.instance() or QApplication([])
    _, factory, identity, service = setup
    execute(service, prepare(service, identity, model='gpt-6.1-sol', reasoning_effort='high'), Receipt())
    widget = ui.OpportunityIntelligenceWidget(factory, identity, auth=Account(), service=service)
    widget.enabled.setChecked(True)
    widget.history()
    text = widget.output.toPlainText()
    assert 'Requested model: gpt-6.1-sol' in text and 'Requested effort: high' in text
    assert 'Provider-reported model: ' + expected_model in text
    assert 'Provider-reported effective effort: ' + expected_effort in text
    assert 'Interpretation policy: ' + VERSION in text
    widget.close()
    app.processEvents()


def test_explicit_operator_states_are_disclosed_for_the_request_task(setup):
    app = QApplication.instance() or QApplication([])
    _, factory, identity, service = setup
    widget = configured_widget(factory, identity, service)
    for field in ('experience_state', 'demonstration_state'):
        control = widget.operator_states[field]
        assert control.currentData() == 'unknown'
        control.setCurrentIndex(control.findData('none'))
    widget.operator_fields['experience'].setText('None')
    widget.operator_fields['demonstration'].setText('None')
    widget.operator_fields['limits'].setText('No capability to do this task')
    packet = widget._prepare_current()['packet']
    assert packet['operator_context']['experience_state'] == 'none'
    assert packet['operator_context']['demonstration_state'] == 'none'
    widget.close()
    app.processEvents()


def test_readable_scope_label_comes_from_packet_and_filtering_retains_diagnostics(setup):
    from test_opportunity_intelligence import advice_for

    _, _, identity, service = setup
    packet = prepare(service, identity)['packet']
    packet['commercial_context']['scope_status'] = 'Matching current Accepted/Won agreement; delivery readiness is checked separately.'
    packet['commercial_context']['contact_eligibility'] = {'permits_live_use': False}
    raw = advice_for(packet)
    raw['next_actions'] = [{
        'id': 'blocked-contact', 'action': 'SYNTHETIC-UNAUTHORIZED-CONTACT', 'reason': 'Synthetic control',
        'evidence_ids': [], 'destination': 'Record Contact', 'action_kind': 'contact',
        'intended_use': 'internal_planning', 'evidence_use': 'context',
    }]
    text = ui.readable_advice(raw, packet)
    assert 'Matching current Accepted/Won agreement' in text
    assert 'Current application decision — candidate scope' not in text
    assert 'SYNTHETIC-UNAUTHORIZED-CONTACT' not in text
    assert 'Contact instruction withheld' in text and 'Support checks' in text
    assert raw['next_actions'][0]['action'] == 'SYNTHETIC-UNAUTHORIZED-CONTACT'
