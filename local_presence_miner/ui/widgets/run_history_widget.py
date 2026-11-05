from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.schema import (
    LeadSearch,
    SearchMarketRun,
    SearchVisibilityObservation,
    SearchVisibilityProbe,
)


def visibility_source_label(source: str) -> str:
    if source == "google_places_text_search":
        return "Google Places"
    if source == "demo_fixture":
        return "Demo fixture"
    return source or "Not captured"


def visibility_window_label(probe: SearchVisibilityProbe | None) -> str:
    if probe is None:
        return "Legacy / unknown"
    if probe.source == "demo_fixture":
        return "Demo — not live evidence"
    if probe.collection_status not in {"complete", "demo"}:
        return "UNKNOWN — collection incomplete"
    if probe.truncated:
        return f"Collected window capped at {probe.retained_result_count} retained results"
    return "Complete collected response window"


class RunHistoryWidget(QWidget):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Run History</h2>"))
        note = QLabel(
            "Search Visibility is a query-scoped Places result proxy. It is not an exact Google Maps or Map Pack rank. "
            "Double-click a run to inspect its observation ledger."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        self.table = QTableWidget()
        self.table.setColumnCount(17)
        self.table.setHorizontalHeaderLabels([
            "ID", "Name", "City", "State", "Category", "Lifecycle", "Candidates",
            "Succeeded", "Failed", "Skipped", "New", "Rediscovered", "Visibility Source",
            "Probe State", "Observed", "Retained", "Collection Window",
        ])
        self.table.cellDoubleClicked.connect(self.open_observations)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        with self.session_factory() as session:
            rows = list(
                session.execute(
                    select(LeadSearch, SearchVisibilityProbe)
                    .outerjoin(SearchVisibilityProbe, SearchVisibilityProbe.search_id == LeadSearch.id)
                    .outerjoin(SearchMarketRun, SearchMarketRun.search_id == LeadSearch.id)
                    .where(SearchMarketRun.id.is_(None))
                    .order_by(LeadSearch.id.desc(), SearchVisibilityProbe.id.desc())
                )
            )
        self.table.setRowCount(len(rows))
        for row, (search, probe) in enumerate(rows):
            values = [
                search.id, search.name, search.city, search.state_region, search.niche,
                search.lifecycle_state, search.total_candidates, search.succeeded_count,
                search.failed_count, search.skipped_count, search.new_count, search.rediscovered_count,
                visibility_source_label(probe.source) if probe else "Not captured",
                probe.collection_status.title() if probe else "Unknown",
                probe.raw_result_count if probe else "—",
                probe.retained_result_count if probe else "—",
                visibility_window_label(probe),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def open_observations(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        search_id = int(item.text())
        with self.session_factory() as session:
            probe = session.scalars(
                select(SearchVisibilityProbe)
                .where(SearchVisibilityProbe.search_id == search_id)
                .order_by(SearchVisibilityProbe.id.desc())
            ).first()
            observations = [] if probe is None else list(
                session.scalars(
                    select(SearchVisibilityObservation)
                    .where(SearchVisibilityObservation.probe_id == probe.id)
                    .order_by(SearchVisibilityObservation.source_position)
                )
            )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Search Visibility Evidence — Run {search_id}")
        dialog.resize(1000, 560)
        layout = QVBoxLayout(dialog)
        if probe is None:
            layout.addWidget(QLabel("No canonical visibility probe exists for this legacy Search Run."))
        else:
            summary = QLabel(
                f"{visibility_source_label(probe.source)} · {probe.query_text} · "
                f"{visibility_window_label(probe)}\n"
                "Positions below are provider-response observations, not exact Google Maps or Map Pack rankings."
            )
            summary.setWordWrap(True)
            layout.addWidget(summary)
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(
            ["Source Position", "Retained", "Business", "Place ID", "Page", "Outcome", "Distance", "Reason"]
        )
        table.setRowCount(len(observations))
        for observation_row, observation in enumerate(observations):
            values = [
                observation.source_position,
                observation.retained_position if observation.retained_position is not None else "—",
                observation.place_name,
                observation.place_id or "Unknown",
                f"{observation.page_number}:{observation.page_position}",
                observation.disposition.replace("_", " ").title(),
                f"{observation.distance_miles:.2f} mi" if observation.distance_miles is not None else "—",
                observation.exclusion_reason,
            ]
            for column, value in enumerate(values):
                table.setItem(observation_row, column, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
