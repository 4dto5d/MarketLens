from __future__ import annotations

from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.schema import ActivityLog


class ActivityLogWidget(QWidget):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        self.refresh()

    def refresh(self) -> None:
        with self.session_factory() as session:
            rows = list(session.execute(select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(200)).scalars())
        self.text.setPlainText("\n".join(f"{row.created_at} | {row.action} | {row.message}" for row in rows))
