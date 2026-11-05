from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.schema import (
    Lead,
    SearchMarketQuery,
    SearchMarketRun,
    SearchVisibilityObservation,
    SearchVisibilityProbe,
)
from local_presence_miner.services.search_market_analysis import SearchMarketProjection, project_search_market
from local_presence_miner.services.search_market_service import COMMERCIAL_REFRESH_WARNING


class SearchMarketWidget(QWidget):
    run_requested = Signal(int, bool, int)

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        layout = QVBoxLayout(self)
        title = QLabel("<h2>Search Market</h2>")
        layout.addWidget(title)
        note = QLabel(
            "Controlled local Places queries only. Coverage describes collected result windows, not exact Maps rank, "
            "Local Pack position, search demand, or market share. Current evidence can inform a reviewed commercial "
            "plan; it never approves or sends outreach."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Prospect"))
        self.prospect = QComboBox()
        self.prospect.setMinimumWidth(260)
        controls.addWidget(self.prospect, 1)
        controls.addWidget(QLabel("Queries"))
        self.query_limit = QSpinBox()
        self.query_limit.setRange(1, 24)
        self.query_limit.setValue(12)
        controls.addWidget(self.query_limit)
        self.demo = QCheckBox("Demo fixtures")
        self.demo.setChecked(True)
        controls.addWidget(self.demo)
        self.run_button = QPushButton("Run Search Market")
        self.run_button.clicked.connect(self._request_run)
        controls.addWidget(self.run_button)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.status = QLabel("Select an existing lead with a recorded search city and state.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Run", "Prospect", "Mode", "State", "Tracked", "Observed", "Unknown", "Coverage",
        ])
        self.table.cellDoubleClicked.connect(self.open_detail)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        selected = self.prospect.currentData()
        with self.session_factory() as session:
            leads = list(session.scalars(select(Lead).order_by(Lead.name).limit(500)))
            runs = list(session.scalars(select(SearchMarketRun).order_by(SearchMarketRun.id.desc()).limit(100)))
            rows = [(run, project_search_market(session, run.id)) for run in runs]
        self.prospect.clear()
        for lead in leads:
            self.prospect.addItem(f"{lead.name} · {lead.place_id}", lead.id)
        if selected is not None:
            index = self.prospect.findData(selected)
            if index >= 0:
                self.prospect.setCurrentIndex(index)
        self.table.setRowCount(len(rows))
        for row, (run, projection) in enumerate(rows):
            display_state = run.lifecycle_state
            if COMMERCIAL_REFRESH_WARNING in run.error_summary:
                display_state += " — commercial review"
            values = [
                run.id, run.prospect_place_id, "Demo — not live" if run.demo_mode else "Live Places",
                display_state, projection.tracked_queries, projection.observed_queries,
                projection.unknown_queries,
                f"{projection.coverage_percent:.1f}% of {projection.coverage_denominator} eligible"
                if projection.coverage_percent is not None else "Unknown — no eligible denominator",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, run.id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()

    def _request_run(self) -> None:
        lead_id = self.prospect.currentData()
        if not isinstance(lead_id, int):
            QMessageBox.information(self, "Select a prospect", "Choose an existing lead before running Search Market.")
            return
        self.run_button.setEnabled(False)
        self.status.setText("Search Market is collecting one immutable probe per tracked query in the background.")
        self.run_requested.emit(lead_id, self.demo.isChecked(), self.query_limit.value())

    def run_finished(self, run_id: int) -> None:
        self.run_button.setEnabled(True)
        with self.session_factory() as session:
            run = session.get(SearchMarketRun, run_id)
            commercial_warning = run is not None and COMMERCIAL_REFRESH_WARNING in run.error_summary
        if commercial_warning:
            self.status.setText(
                f"Search Market run {run_id} finished; commercial refresh needs review before using its plan. "
                "The query evidence is preserved."
            )
        else:
            self.status.setText(f"Search Market run {run_id} finished. Double-click it to inspect query and observation evidence.")
        self.refresh()

    def run_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.status.setText(message)

    def open_detail(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        run_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(run_id, int):
            SearchMarketDetailDialog(self.session_factory, run_id, self).exec()


class SearchMarketDetailDialog(QDialog):
    def __init__(self, session_factory: sessionmaker[Session], run_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Search Market Evidence — Run {run_id}")
        self.resize(1100, 700)
        layout = QVBoxLayout(self)
        with session_factory() as session:
            run = session.get(SearchMarketRun, run_id)
            commercial_warning = run is not None and COMMERCIAL_REFRESH_WARNING in run.error_summary
            projection = project_search_market(session, run_id)
            query_rows = list(session.scalars(
                select(SearchMarketQuery).where(SearchMarketQuery.run_id == run_id).order_by(SearchMarketQuery.ordinal)
            ))
            probe_rows = {
                query.id: list(session.scalars(
                    select(SearchVisibilityProbe).where(SearchVisibilityProbe.market_query_id == query.id)
                    .order_by(SearchVisibilityProbe.id)
                )) for query in query_rows
            }
            observations = {
                probe.id: list(session.scalars(
                    select(SearchVisibilityObservation).where(SearchVisibilityObservation.probe_id == probe.id)
                    .order_by(SearchVisibilityObservation.source_position)
                ))
                for probes in probe_rows.values() for probe in probes
            }
            # Convert ORM rows into immutable display tuples before closing the session.
            query_info = [
                (query.id, query.query_id, query.cluster_id, query.cluster_name, query.query_text,
                 query.provenance_rule, query.generation_version) for query in query_rows
            ]
            probe_info = {
                query_id: [(probe.id, probe.collection_status, probe.truncated, probe.source,
                            probe.observed_at.isoformat(), probe.attempt_id) for probe in probes]
                for query_id, probes in probe_rows.items()
            }
            observation_info = {
                probe_id: [
                    (item.source_position, item.retained_position, item.place_name, item.place_id,
                     item.disposition, item.exclusion_reason) for item in rows
                ] for probe_id, rows in observations.items()
            }

        layout.addWidget(self._summary(projection))
        if commercial_warning:
            warning = QLabel("Commercial refresh needs review before using this run's plan. Query evidence is preserved.")
            warning.setWordWrap(True)
            layout.addWidget(warning)
        cluster_table = QTableWidget()
        cluster_table.setColumnCount(7)
        cluster_table.setHorizontalHeaderLabels(["Cluster", "Tracked", "Observed", "Present", "Absent", "Unknown", "Coverage"])
        cluster_table.setRowCount(len(projection.clusters))
        for row, cluster in enumerate(projection.clusters):
            values = [
                cluster.cluster_name, cluster.tracked, cluster.observed, cluster.present,
                cluster.absent, cluster.unknown,
                f"{cluster.coverage_percent:.1f}% of {cluster.denominator} eligible"
                if cluster.coverage_percent is not None else "Unknown",
            ]
            for column, value in enumerate(values):
                cluster_table.setItem(row, column, QTableWidgetItem(str(value)))
        cluster_table.resizeColumnsToContents()
        layout.addWidget(cluster_table, 1)

        layout.addWidget(QLabel("<b>Top Search Competitors</b> — repeated capture on complete queries where the prospect was not returned"))
        self.competitors = QTableWidget()
        self.competitors.setColumnCount(5)
        self.competitors.setHorizontalHeaderLabels(["Business", "Gap captures", "All appearances", "Top-10 source positions", "Clusters"])
        self.competitors.setRowCount(len(projection.top_search_competitors))
        for row, competitor in enumerate(projection.top_search_competitors):
            values = [competitor.name, competitor.gap_capture_queries, competitor.appearance_queries,
                      competitor.top10_gap_queries, competitor.cluster_count]
            for column, value in enumerate(values):
                self.competitors.setItem(row, column, QTableWidgetItem(str(value)))
        self.competitors.cellDoubleClicked.connect(lambda row, _column: self._show_competitor(projection, row))
        self.competitors.resizeColumnsToContents()
        layout.addWidget(self.competitors, 1)

        layout.addWidget(QLabel("<b>Query-gap intelligence</b> — observed fact is separate from interpretation"))
        gap_table = QTableWidget()
        gap_table.setColumnCount(3)
        gap_table.setHorizontalHeaderLabels(["Scope", "Observed fact", "Bounded interpretation"])
        gap_table.setRowCount(len(projection.gaps))
        for row, gap in enumerate(projection.gaps):
            for column, value in enumerate((gap.scope, gap.fact, gap.interpretation)):
                gap_table.setItem(row, column, QTableWidgetItem(value))
        gap_table.resizeColumnsToContents()
        layout.addWidget(gap_table, 1)

        layout.addWidget(QLabel("<b>Evidence drill-down</b> — expand Cluster → Query → Probe → Observation"))
        tree = QTreeWidget()
        tree.setHeaderLabels(["Evidence", "State / ordinal", "Context"])
        coverage_by_id = {item.query_id: item for item in projection.queries}
        clusters: dict[str, QTreeWidgetItem] = {}
        for query_id, stable_id, cluster_id, cluster_name, query_text, provenance, version in query_info:
            parent_item = clusters.get(cluster_id)
            if parent_item is None:
                parent_item = QTreeWidgetItem(tree, [cluster_name, "Cluster", cluster_id])
                clusters[cluster_id] = parent_item
            coverage = coverage_by_id[stable_id]
            query_item = QTreeWidgetItem(parent_item, [query_text, coverage.state.upper(), f"{provenance} · {version}"])
            query_item.setToolTip(0, coverage.reason)
            for probe_id, status, truncated, source, observed_at, attempt_id in probe_info[query_id]:
                probe_item = QTreeWidgetItem(query_item, [
                    f"Probe {probe_id}", status.upper() + (" · TRUNCATED" if truncated else ""),
                    f"{source} · {observed_at} · attempt {attempt_id[:12]}",
                ])
                for source_position, retained, name, place_id, disposition, reason in observation_info[probe_id]:
                    QTreeWidgetItem(probe_item, [
                        name or place_id or "Unknown place", f"Source #{source_position} · retained {retained if retained is not None else '—'}",
                        f"{disposition}: {reason}" if reason else disposition,
                    ])
        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)
        layout.addWidget(tree, 3)
        limitation = QLabel(" ".join(projection.limitations))
        limitation.setWordWrap(True)
        layout.addWidget(limitation)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    @staticmethod
    def _summary(projection: SearchMarketProjection) -> QLabel:
        coverage = (
            f"{projection.coverage_percent:.1f}% of {projection.coverage_denominator} eligible queries"
            if projection.coverage_percent is not None else "Unknown — no eligible query denominator"
        )
        label = QLabel(
            f"<b>{projection.evidence_mode.upper()} EVIDENCE</b> · Tracked {projection.tracked_queries} · "
            f"Observed {projection.observed_queries} · Unknown {projection.unknown_queries} · "
            f"Excluded {projection.excluded_queries} · Coverage {coverage}<br>"
            f"Strongest cluster: {projection.strongest_cluster or 'Unknown'} · "
            f"Weakest cluster: {projection.weakest_cluster or 'Unknown'}"
        )
        label.setWordWrap(True)
        return label

    def _show_competitor(self, projection: SearchMarketProjection, row: int) -> None:
        competitor = projection.top_search_competitors[row]
        evidence = "\n".join(
            f"• {item.query_text}: source #{item.source_position}; prospect {item.prospect_state}"
            for item in competitor.evidence
        )
        QMessageBox.information(self, competitor.name, f"{competitor.why}\n\nObserved query evidence:\n{evidence}")
