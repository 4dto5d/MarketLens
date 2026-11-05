"""Local-only evidence import and inspectable query/channel research history."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.schema import Lead
from local_presence_miner.services.seo_research_service import (
    MAX_IMPORT_BYTES,
    append_research,
    compare_research,
    parse_research_json,
    project_seo_research,
    research_history,
    research_template,
)


class SEOIntelligenceWidget(QWidget):
    def __init__(self, session_factory: sessionmaker[Session], lead_id: int, parent=None) -> None:
        super().__init__(parent)
        self.session_factory = session_factory
        self.lead_id = lead_id
        layout = QVBoxLayout(self)
        note = QLabel(
            "Query-scoped research, not a ranking guarantee. Organic, Maps and Places coverage are distinct. "
            "Import records operator-supplied source evidence; it does not call Semrush or validate metrics live. "
            "UNKNOWN is not zero. Country-level volume is not local demand. Research never sends outreach."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        toolbar = QHBoxLayout()
        for label, handler in (("Export research template", self.export_template), ("Import research JSON", self.import_json),
                               ("Export current research", self.export_current)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Service / queries", "Organic", "Maps", "Capturability", "Action", "Decision"])
        layout.addWidget(self.table)
        history_bar = QHBoxLayout()
        history_bar.addWidget(QLabel("Historical comparison"))
        self.before = QComboBox()
        self.after = QComboBox()
        history_bar.addWidget(self.before, 1)
        history_bar.addWidget(self.after, 1)
        compare = QPushButton("Compare exact observations")
        compare.clicked.connect(self.compare)
        history_bar.addWidget(compare)
        layout.addLayout(history_bar)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        self.refresh()

    def refresh(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead is None:
                return
            self.report = project_seo_research(session, lead)
            history = research_history(session, self.lead_id)
        self.status.setText(f"{self.report['state'].upper()} — {self.report['summary']} {self.report.get('commercial_warning', '')}")
        opportunities = self.report.get("opportunities", [])
        self.table.setRowCount(len(opportunities))
        for row, item in enumerate(opportunities):
            values = [f"{item.get('service', '')}: {', '.join(item.get('queries', []))}", item.get("organic_visibility", "unknown"),
                      item.get("maps_visibility", "unknown"), item.get("capturability", "unknown"),
                      item.get("action", "validate"), item.get("decision", "insufficient_evidence")]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, cell)
        self.table.resizeColumnsToContents()
        self.details.setPlainText(json.dumps(self.report, ensure_ascii=False, indent=2))
        for combo in (self.before, self.after):
            combo.clear()
            for item in history:
                combo.addItem(f"#{item['id']} · {item['source_status']} · {item['observed_at']}", item["id"])
        if len(history) >= 2:
            self.before.setCurrentIndex(1)

    def _save(self, payload: dict, name: str) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export SEO research", name, "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def export_template(self) -> None:
        try:
            with self.session_factory() as session:
                lead = session.get(Lead, self.lead_id)
                if lead is None:
                    return
                payload = research_template(session, lead)
            self._save(payload, "seo-research-template.json")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Research unavailable", str(exc))

    def export_current(self) -> None:
        self.refresh()
        try:
            self._save(self.report, "seo-research-current.json")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import recorded SEO source evidence", "", "JSON (*.json)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > MAX_IMPORT_BYTES:
                raise ValueError("Research import exceeds the bounded two-megabyte limit.")
            payload = parse_research_json(Path(path).read_text(encoding="utf-8-sig"))
            with self.session_factory() as session:
                lead = session.get(Lead, self.lead_id)
                if lead is None:
                    raise ValueError("Business no longer exists.")
                append_research(session, lead, payload)
                session.commit()
            self.refresh()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Import rejected — no source change", str(exc))

    def compare(self) -> None:
        before, after = self.before.currentData(), self.after.currentData()
        if not isinstance(before, int) or not isinstance(after, int):
            return
        with self.session_factory() as session:
            comparison = compare_research(session, self.lead_id, before, after)
        self.details.setPlainText(json.dumps(comparison, ensure_ascii=False, indent=2))
