"""Off-by-default Qt surface, with no provider requests."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from test_opportunity_intelligence import setup as setup_fixture

from local_presence_miner.ui.widgets.opportunity_intelligence_widget import OpportunityIntelligenceWidget


@pytest.fixture(name="setup")
def storage(tmp_path):
    yield from setup_fixture.__wrapped__(tmp_path)

class NoNetwork:
    def __init__(self): self.calls = 0
    def account(self): return None
    def models(self):
        self.calls += 1
        raise AssertionError("Unexpected provider request")

def test_off_by_default_no_model_request_and_plain_text(setup):
    app = QApplication.instance() or QApplication([])
    _, factory, lead_id, service = setup
    auth = NoNetwork()
    widget = OpportunityIntelligenceWidget(factory, lead_id, auth=auth, inference=auth, service=service)
    widget.show()
    app.processEvents()
    assert not widget.enabled.isChecked()
    assert not widget.run_button.isEnabled()
    assert auth.calls == 0
    widget.enabled.setChecked(True)
    app.processEvents()
    assert widget.run_button.isEnabled() and auth.calls == 0
    assert widget.status.text().startswith("Enabled")
    widget.output.setPlainText("<script>private()</script>")
    assert widget.output.toPlainText() == "<script>private()</script>"
    widget.enabled.setChecked(False)
    assert widget.cancel_event.is_set() and not widget.adopt_button.isEnabled()
    widget.close()

def test_actual_dialog_hosts_panel_and_unsaved_guard(setup):
    from local_presence_miner.ui.dialogs.opportunity_workflow_dialog import OpportunityWorkflowDialog
    app = QApplication.instance() or QApplication([])
    _, factory, lead_id, _ = setup
    dialog = OpportunityWorkflowDialog(factory, lead_id)
    dialog.show()
    app.processEvents()
    dialog.intelligence.check_unsaved()
    dialog.fields["owner_question"].setText("Unsaved human question")
    with pytest.raises(ValueError, match="Save current"):
        dialog.intelligence.check_unsaved()
    assert dialog.intelligence.models.count() == 0
    dialog.reject()
    assert dialog.intelligence.cancel_event.is_set()


def test_readable_preview_preserves_disclosure_with_optional_exact_request(setup):
    import json

    from local_presence_miner.ui.widgets.opportunity_intelligence_widget import ContextPreviewDialog
    app=QApplication.instance() or QApplication([])
    _,_,identity,service=setup
    prepared=service.prepare(identity,question="What should I verify?",mode="Focused",model="fixture-model",account_binding="a"*64,include_worksheet=True)
    dialog=ContextPreviewDialog(prepared,{"label":"Synthetic account"})
    dialog.show()
    app.processEvents()
    text=dialog.summary.toPlainText()
    assert "I want easier editing" in text and "Human question retained" in text
    assert "Missing and excluded information" in text and "Instructions accompanying" in text
    assert not dialog.technical.isVisible()
    assert json.loads(dialog.technical.toPlainText()) == prepared["body"]
    dialog.reject()


def test_advice_main_view_is_readable_and_preserves_unknowns(setup):
    from test_opportunity_intelligence import advice_for

    from local_presence_miner.ui.widgets.opportunity_intelligence_widget import readable_advice
    _,_,identity,service=setup
    packet=service.prepare(identity,question="What should I verify?",mode="Focused",model="fixture-model",account_binding="a"*64)["packet"]
    text=readable_advice(advice_for(packet))
    assert "Which edit is blocked" in text and "Your delivery capability: unknown" in text
    assert "Conclusions the evidence does not support" in text and "No migration quote" in text
    assert "schema_version" not in text and "context_hash" not in text
