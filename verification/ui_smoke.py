from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from local_presence_miner.config import AppConfig, SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.schema import Lead, LeadSearch
from local_presence_miner.domain.models import SearchCriteria
from local_presence_miner.services.search_workflow import SearchWorkflow
from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
from local_presence_miner.ui.dialogs.seller_proof_dialog import SellerProofDialog
from local_presence_miner.ui.main_window import MainWindow


def main() -> int:
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = AppConfig(
        output,
        output / "ui-smoke.sqlite3",
        output / "ui-smoke.log",
        output,
        request_delay_seconds=0,
        sender=SenderInfo(
            name="Fixture Operator",
            business_name="Fixture Studio",
            reply_email="operator@example.com",
            phone="555-010-0100",
            postal_address="123 Fixture Street",
            opt_out_line="Reply opt out.",
        ),
    )
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    search_id = SearchWorkflow(config, factory).run(
        SearchCriteria("Peoria", "IL", "roofers", demo_mode=True, top_mockups=0)
    )
    with factory() as session:
        lead_id = session.query(Lead.id).first()[0]
    app = QApplication.instance() or QApplication([])
    window = MainWindow(config, factory)
    assert window.run_history.table.columnCount() == 17
    assert window.run_history.table.item(0, 12).text() == "Demo fixture"
    with factory() as session:
        run = session.get(LeadSearch, search_id)
        assert run is not None and run.lifecycle_state == "Completed" and run.succeeded_count > 0
    results = []
    for width, height in ((1366, 768), (1920, 1080)):
        window.resize(width, height)
        window.show()
        app.processEvents()
        assert (window.width(), window.height()) == (width, height)
        for row in range(window.nav.count()):
            window.nav.setCurrentRow(row)
            app.processEvents()
            assert window.stack.currentWidget() is not None and window.stack.currentWidget().isVisible()
        capture = output / f"main-{width}x{height}.png"
        assert window.grab().save(str(capture)) and capture.stat().st_size > 0
        results.append({"surface": "MainWindow", "size": [width, height], "navigation_rows": window.nav.count(), "capture": capture.name})
    detail = LeadDetailDialog(config, factory, lead_id)
    detail.show()
    app.processEvents()
    assert detail.tabs.count() >= 10
    assert "Search Visibility" in [detail.tabs.tabText(index) for index in range(detail.tabs.count())]
    for index in range(detail.tabs.count()):
        detail.tabs.setCurrentIndex(index)
        app.processEvents()
        assert detail.tabs.currentWidget().isVisible()
    proof = SellerProofDialog(factory)
    proof.resize(720, 700)
    proof.show()
    app.processEvents()
    assert proof.height() <= 768 and proof.internal_only.isChecked() and not proof.share_client_name.isEnabled()
    (output / "ui-smoke.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "results": results,
                "lead_detail_tabs": [detail.tabs.tabText(index) for index in range(detail.tabs.count())],
                "proof_dialog_size": [proof.width(), proof.height()],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    proof.close()
    detail.close()
    window.close()
    app.processEvents()
    factory.kw["bind"].dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
