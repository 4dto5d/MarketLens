from __future__ import annotations

import sys
from pathlib import Path

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.logging_config import configure_logging
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.v0111_backfill_service import V0111BackfillService


def main() -> int:
    config = AppConfig.load()
    configure_logging(config)
    session_factory = create_session_factory(config.database_path)
    initialize_database(session_factory)
    with session_factory() as session:
        changed = V0111BackfillService().run(session, config.sender)
        if QualificationService().recalculate_missing(session):
            changed += 1
        if changed:
            session.commit()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from local_presence_miner.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app.setWindowIcon(QIcon(str(resource_root / "local_presence_miner" / "assets" / "app-icon.ico")))
    window = MainWindow(config=config, session_factory=session_factory)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
