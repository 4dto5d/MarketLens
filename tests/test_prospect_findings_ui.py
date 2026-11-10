"""Exercise the existing Audit Evidence entry point with synthetic local data."""
import json

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from test_intervention_integration import BROKEN_ROUTE, add_business
from test_intervention_integration import storage as storage_fixture

from local_presence_miner.services.opportunity_workflow_service import latest_worksheet
from local_presence_miner.services.prospect_finding_service import project_findings
from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
from local_presence_miner.ui.dialogs.opportunity_workflow_dialog import OpportunityWorkflowDialog
from local_presence_miner.ui.widgets.prospect_findings_widget import FindingEditorDialog, ProspectFindingsWidget


@pytest.fixture(name='storage')
def setup_storage(tmp_path):
    config, factory = storage_fixture.__wrapped__(tmp_path)
    yield config, factory
    factory.kw['bind'].dispose()


def test_capture_from_audit_evidence_refreshes_workspace_and_links_immutable_revision(storage, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE)
        identity = lead.id
        session.commit()
    def unexpected_warning(_parent, _title, message):
        raise AssertionError(message)
    monkeypatch.setattr(QMessageBox, 'warning', unexpected_warning)
    workspace = LeadDetailDialog(config, factory, identity)
    workspace.show()
    workspace.select_tab('Audit Evidence')
    app.processEvents()
    panel = workspace.findChild(ProspectFindingsWidget)
    assert panel is not None
    errors = []
    def fill_capture():
        modal = app.activeModalWidget()
        try:
            assert isinstance(modal, FindingEditorDialog)
            modal.actor.setText('Sammi')
            modal.question.setText('Which contact route do your customers actually use?')
            modal.save()
        except Exception as exc:
            errors.append(str(exc))
            if modal:
                modal.reject()
    QTimer.singleShot(50, fill_capture)
    panel.capture_web()
    assert not errors
    app.processEvents()
    with factory() as session:
        captured = project_findings(session, identity)[0]
    assert captured['review_state'] == 'UNREVIEWED'
    assert workspace.tabs.tabText(workspace.tabs.currentIndex()) == 'Audit Evidence'
    worksheet = OpportunityWorkflowDialog(factory, identity)
    worksheet.fields['source_ref'].setText('Synthetic saved capture')
    worksheet.fields['observation'].setText('Contact observation needs owner confirmation')
    worksheet.finding_links.item(0).setCheckState(Qt.CheckState.Checked)
    assert worksheet.save()
    with factory() as session:
        assert latest_worksheet(session, identity)['data']['finding_refs'] == [captured['reference']]
    worksheet.close()
    workspace.close()
    app.processEvents()


def test_owner_need_editor_preserves_attribution_for_a_warm_business_without_audit(storage, monkeypatch):
    from local_presence_miner.services.opportunity_workflow_service import create_warm_opportunity

    app = QApplication.instance() or QApplication([])
    config, factory = storage
    with factory() as session:
        lead = create_warm_opportunity(session, name='Hypothetical Serenity Now',
                                       data={'route': 'owner_report', 'source_ref': 'Synthetic scenario', 'observation': 'Easier editing request'})
        identity = lead.id
        session.commit()
    def unexpected_warning(_parent, _title, message):
        raise AssertionError(message)
    monkeypatch.setattr(QMessageBox, 'warning', unexpected_warning)
    workspace = LeadDetailDialog(config, factory, identity)
    assert workspace.findChild(ProspectFindingsWidget) is not None
    editor = FindingEditorDialog(factory, identity, kind='manual_owner_need')
    editor.actor.setText('Sammi')
    editor.owner_label.setText('Hypothetical Jarrod')
    editor.source_text.setPlainText('Could we compare UENI and Wix for easier editing?')
    editor.source_ref.setText('Hypothetical conversation only')
    editor.save()
    with factory() as session:
        finding = project_findings(session, identity)[0]
        assert finding['assertion_kind'] == 'ATTRIBUTED_STATEMENT'
        assert not finding['commercial_fact_eligible']
        assert json.loads(finding['source_snapshot_json'])['payload']['source_text_mode'] == 'PARAPHRASED'
    editor.close()
    workspace.close()
    app.processEvents()


def test_ai_capture_review_preview_and_explicit_copy_approval_use_the_existing_panel(storage, monkeypatch):
    from local_presence_miner.time_utils import utc_now

    app = QApplication.instance() or QApplication([])
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        identity = lead.id
        session.commit()
    def unexpected_warning(_parent, _title, message):
        raise AssertionError(message)
    monkeypatch.setattr(QMessageBox, 'warning', unexpected_warning)
    capture = FindingEditorDialog(factory, identity, kind='ai_discoverability')
    capture.actor.setText('Sammi')
    capture.ai_fields['prompt'].setPlainText('Which synthetic sign shops serve Alamosa?')
    capture.ai_fields['response'].setPlainText('Synthetic Competitor Signs is listed in this response.')
    capture.ai_fields['captured_at'].setText(utc_now().isoformat())
    capture.ai_fields['prospect_mention'].setCurrentText('NOT_MENTIONED')
    assert 'was not mentioned' in capture.ai_preview.toPlainText()
    capture.save()
    with factory() as session:
        head = project_findings(session, identity)[0]
        assert not head['customer_claim_eligible']
    review = FindingEditorDialog(factory, identity, kind='ai_discoverability', head=head)
    review.actor.setText('Sammi')
    review.review_state.setCurrentText('VERIFIED')
    review.source_checked.setChecked(True)
    review.review_note.setPlainText('Checked complete response, aliases, prompt, date and exact bounded wording.')
    review.approve_customer_claim.setChecked(True)
    review.ai_fields['provider'].setCurrentText('Claude')
    assert 'Claude' in review.ai_preview.toPlainText()
    review.save()
    with factory() as session:
        approved = project_findings(session, identity)[0]
        assert approved['customer_claim_eligible'] and not approved['commercial_fact_eligible']
        assert approved['source']['payload']['provider'] == 'Claude'
    capture.close()
    review.close()
    app.processEvents()


@pytest.mark.parametrize('mode',['none','one','cancel','raced_dispute'])
def test_proposal_workflow_requires_per_artifact_selection_and_rechecks_raced_reviews(storage,monkeypatch,mode):
    from PySide6.QtWidgets import QDialog, QInputDialog
    from test_ai_discoverability_findings import approve, source

    from local_presence_miner.services.prospect_finding_service import proposal_ai_choices, record_ai_observation, revise_finding
    from local_presence_miner.ui.dialogs.proposal_evidence_dialog import ProposalEvidenceDialog
    app=QApplication.instance() or QApplication([])
    config,factory=storage
    with factory() as session:
        lead,_=add_business(session,checks=BROKEN_ROUTE)
        row=record_ai_observation(session,lead.id,actor='Sammi',**source(prompt='SYNTHETIC_CONFIDENTIAL_PROMPT'))
        approve(session,lead,row)
        identity,key=lead.id,row.finding_key
        expected=proposal_ai_choices(session,identity)[0]['disclosure']
        session.commit()
    warnings=[]
    opened=[]
    monkeypatch.setattr(QInputDialog,'getInt',lambda *_args,**_kwargs:(350,True))
    monkeypatch.setattr(QMessageBox,'warning',lambda _p,_t,message:warnings.append(message))
    monkeypatch.setattr('local_presence_miner.services.proposal_service.webbrowser.open',lambda uri:opened.append(uri))
    def choose(dialog):
        assert dialog.selected_references()==[]
        assert dialog.preview.toPlainText()==expected and 'SYNTHETIC_CONFIDENTIAL_PROMPT' not in dialog.preview.toPlainText()
        if mode=='cancel':
            return QDialog.DialogCode.Rejected
        if mode in {'one','raced_dispute'}:
            dialog.observations.item(0).setCheckState(Qt.CheckState.Checked)
        if mode=='raced_dispute':
            with factory() as session:
                revise_finding(session,identity,key,expected_revision=2,actor='Sammi',review_state='DISPUTED',review_note='Changed after selection')
                session.commit()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ProposalEvidenceDialog,'exec',choose)
    workspace=LeadDetailDialog(config,factory,identity)
    workspace.generate_proposal()
    artifacts=list((config.output_dir/'proposals').glob('*.html'))
    if mode in {'cancel','raced_dispute'}:
        assert not artifacts and not opened
        assert bool(warnings)==(mode=='raced_dispute')
    else:
        assert len(artifacts)==1 and len(opened)==1 and not warnings
        html=artifacts[0].read_text(encoding='utf-8')
        assert ('Reviewed Manual AI Response Observations' in html)==(mode=='one')
        assert 'SYNTHETIC_CONFIDENTIAL_PROMPT' not in html
    workspace.close()
    app.processEvents()
