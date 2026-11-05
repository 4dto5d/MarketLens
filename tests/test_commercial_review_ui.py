"""Reachable manual review and payable-offer safeguards on the real offscreen UI."""
import json

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import select
from test_sales_delivery_corrections import business, payload
from test_sales_delivery_corrections import storage as storage_fixture

from local_presence_miner.database.schema import OfferHistory
from local_presence_miner.services.seo_research_service import append_research
from local_presence_miner.ui.dialogs.commercial_review_dialog import CommercialReviewDialog
from local_presence_miner.ui.dialogs.offer_history_dialog import OfferHistoryDialog


@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    return storage_fixture.__wrapped__(tmp_path)


@pytest.mark.parametrize("width,height", [(1366, 768), (1920, 1080)])
def test_manual_review_surface_is_offscreen_usable_and_never_preapproves(storage, monkeypatch, width, height):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        identity = lead.id
        session.commit()
    dialog = CommercialReviewDialog(factory, identity)
    dialog.resize(width, height)
    dialog.show()
    app.processEvents()
    assert not dialog.reviewed.isChecked() and not dialog.owner_approved.isChecked()
    assert dialog.amount.value() == 0
    assert "REVIEW_REQUIRED" in dialog.source.toPlainText()
    assert all(value == "UNKNOWN" for value in json.loads(dialog.fields.toPlainText()).values())
    dialog.reviewer.setText("Sammi")
    dialog.notes.setText("Manually checked the synthetic original query/page source; this is not a live audit")
    dialog.review_evidence()
    assert '"review_state": "REVIEWED"' in dialog.source.toPlainText()
    assert '"ready_for_payment": false' in dialog.source.toPlainText()
    dialog.close()


def test_new_payable_offer_refused_without_reviewed_exact_delivery_packet(storage, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(str(args[-1])))
    _, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        identity = lead.id
        session.commit()
    dialog = OfferHistoryDialog(factory, lead_id=identity, default_status="Accepted")
    dialog.save()
    assert messages and "delivery packet" in messages[0]
    with factory() as session:
        assert session.scalars(select(OfferHistory)).all() == []
    dialog.close()
    app.processEvents()
