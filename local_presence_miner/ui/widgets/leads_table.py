from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.repositories import lead_google_details_retrieved, list_leads, loads
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.domain.verification import assess_verification
from local_presence_miner.services.commercial_triage_service import commercial_triage_overlay
from local_presence_miner.ui.components import DataTable, EmptyState, StatusBadge, table_item
from local_presence_miner.ui.components.action_toolbar import action_button


class LeadsTableWidget(QWidget):
    lead_open_requested = Signal(int)
    new_search_requested = Signal()

    def __init__(self, session_factory: sessionmaker[Session], *, statuses: set[str] | None = None, empty_message: str = "No leads found.") -> None:
        super().__init__()
        self.session_factory = session_factory
        self.statuses = statuses
        self.empty_message = empty_message
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 22)
        root.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search business, category, location, or opportunity...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search, 2)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses")
        self.status_filter.addItems([status.value for status in LeadStatus])
        self.status_filter.currentTextChanged.connect(self.refresh)
        toolbar.addWidget(self.status_filter)
        self.verification_filter = QComboBox()
        self.verification_filter.addItems(["All verification", "Unverified", "Verification incomplete", "Ready for outreach", "Suppressed / blocked"])
        self.verification_filter.currentTextChanged.connect(self.refresh)
        toolbar.addWidget(self.verification_filter)
        self.commercial_filter = QComboBox()
        for label, state in (("All commercial", ""), ("Scoped opportunity", "recommended"), ("Validation first", "validate_first"),
                             ("No paid recommendation", "no_sale"), ("Research only", "insufficient_evidence")):
            self.commercial_filter.addItem(label, state)
        self.commercial_filter.setToolTip("Current commercial review only; does not change Qualification or contact permission.")
        self.commercial_filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.commercial_filter)
        self.niche_filter = QComboBox()
        self.niche_filter.addItem("All niches")
        self.niche_filter.currentTextChanged.connect(self.refresh)
        toolbar.addWidget(self.niche_filter)
        self.sales_filter = QSpinBox()
        self.sales_filter.setRange(0, 100)
        self.sales_filter.setPrefix("Sales ≥ ")
        self.sales_filter.valueChanged.connect(self.refresh)
        self.sales_filter.setToolTip("Minimum Sales Priority. This is a prioritization score, not a close probability or proof of budget.")
        toolbar.addWidget(self.sales_filter)
        self.score_filter = QSpinBox()
        self.score_filter.setRange(0, 100)
        self.score_filter.setPrefix("Growth ≥ ")
        self.score_filter.valueChanged.connect(self.refresh)
        self.score_filter.setToolTip("Minimum Growth Score. Growth Score measures observable improvement opportunity.")
        toolbar.addWidget(self.score_filter)
        toolbar.addWidget(action_button("Clear", self.clear_filters, role="tertiary"))
        root.addLayout(toolbar)
        self.result_summary = QLabel()
        self.result_summary.setProperty("role", "sectionDescription")
        root.addWidget(self.result_summary)
        self.table = DataTable(["Sales", "Class", "Growth", "Business", "Category", "Location", "Website", "Reviews", "Status",
                                "Verification", "Next action", "Commercial review"])
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self.open_current)
        root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text().lower().strip()
        with self.session_factory() as session:
            all_leads = list_leads(session)
            commercial = {lead.id: commercial_triage_overlay(session, lead) for lead in all_leads}
        niches = sorted({lead.category for lead in all_leads if lead.category})
        current_niche = self.niche_filter.currentText()
        self.niche_filter.blockSignals(True)
        self.niche_filter.clear()
        self.niche_filter.addItem("All niches")
        self.niche_filter.addItems(niches)
        if current_niche in niches:
            self.niche_filter.setCurrentText(current_niche)
        self.niche_filter.blockSignals(False)
        leads = [lead for lead in all_leads if not self.statuses or lead.status in self.statuses]
        if self.commercial_filter.currentData():
            leads = [lead for lead in leads if commercial[lead.id]["state"] == self.commercial_filter.currentData()]
        if self.status_filter.currentText() != "All statuses":
            leads = [lead for lead in leads if lead.status == self.status_filter.currentText()]
        if self.verification_filter.currentText() != "All verification":
            leads = [lead for lead in leads if verification_state(lead) == self.verification_filter.currentText()]
        if self.niche_filter.currentText() != "All niches":
            leads = [lead for lead in leads if lead.category == self.niche_filter.currentText()]
        leads = [lead for lead in leads if lead.sales_priority_score >= self.sales_filter.value()]
        leads = [lead for lead in leads if lead.lead_score >= self.score_filter.value()]
        if query:
            leads = [lead for lead in leads if query in " ".join([lead.name, lead.category, lead.address, lead.status, lead.recommended_offer]).lower()]
        self.table.setSortingEnabled(False)
        self.table.clearSpans()
        self.table.setRowCount(len(leads))
        if not leads:
            self.table.setRowCount(1)
            self.table.setSpan(0, 0, 1, self.table.columnCount())
            self.table.setCellWidget(0, 0, EmptyState("No matching leads", self.empty_message, "Start Search", self.new_search_requested.emit))
            self.result_summary.setText("0 leads match the current filters")
            return
        for row, lead in enumerate(leads):
            assessment = assess_verification(lead)
            location = lead.address or (f"ZIP {lead.target_zip_code}" if lead.target_zip_code else "Not recorded")
            details_retrieved = lead_google_details_retrieved(lead)
            website = (
                lead.website.replace("https://", "").replace("http://", "").rstrip("/")
                if lead.website
                else "No website" if details_retrieved else "Unknown"
            )
            next_action = lead.next_follow_up_date or ("Review outreach" if assessment.state == "Ready for outreach" else "Complete verification")
            qualification = loads(lead.qualification_json, {})
            next_action = qualification.get("next_action") or next_action
            reviews = lead.review_count if details_retrieved else "Unknown"
            values = [lead.sales_priority_score, lead.qualification_class, lead.lead_score, lead.name, lead.category, location, website, reviews]
            for column, value in enumerate(values):
                self.table.setItem(
                    row,
                    column,
                    table_item(value, numeric=column in {0, 2} or (column == 7 and details_retrieved), user_data=lead.id if column == 3 else None),
                )
            self.table.setCellWidget(row, 8, StatusBadge(lead.status))
            self.table.setCellWidget(row, 9, StatusBadge(assessment.state))
            self.table.setItem(row, 10, table_item(next_action, tooltip=next_action))
            self.table.setItem(row, 11, table_item(commercial[lead.id]["label"], tooltip=commercial[lead.id]["reason"]))
        self.table.fit_columns(stretch_column=3)
        self.table.setColumnWidth(5, min(self.table.columnWidth(5), 220))
        self.table.setColumnWidth(6, min(self.table.columnWidth(6), 200))
        self.table.setSortingEnabled(True)
        self.result_summary.setText(f"Showing {len(leads)} of {len(all_leads)} leads")

    def clear_filters(self) -> None:
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        self.verification_filter.setCurrentIndex(0)
        self.commercial_filter.setCurrentIndex(0)
        self.niche_filter.setCurrentIndex(0)
        self.sales_filter.setValue(0)
        self.score_filter.setValue(0)
        self.refresh()

    def open_current(self, row: int, _column: int) -> None:
        item = self.table.item(row, 3)
        lead_id = item.data(256) if item else None
        if lead_id:
            self.lead_open_requested.emit(int(lead_id))


def verification_progress(lead) -> str:
    assessment = assess_verification(lead)
    return f"{assessment.completed} / {assessment.total} — {assessment.state}"


def verification_state(lead) -> str:
    return assess_verification(lead).state
