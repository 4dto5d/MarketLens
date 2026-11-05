from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.repositories import list_leads, update_lead_fields, update_lead_status
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.ui.components import DataTable, FieldMessage, MetricCard, StatusBadge, table_item
from local_presence_miner.ui.components.action_toolbar import ActionToolbar


class PipelineWidget(QWidget):
    lead_open_requested = Signal(int)

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 22)
        root.setSpacing(12)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metric_cards = {
            "Overdue": MetricCard("Overdue", 0, "Past scheduled date", accent="danger"),
            "Today": MetricCard("Due Today", 0, "Needs action today", accent="warning"),
            "Upcoming": MetricCard("Upcoming", 0, "Future follow-ups", accent="primary"),
            "None": MetricCard("No Follow-up", 0, "Needs a next step", accent="neutral"),
        }
        for card in self.metric_cards.values():
            metrics.addWidget(card, 1)
        root.addLayout(metrics)
        toolbar = QHBoxLayout()
        self.due_filter = QComboBox()
        self.due_filter.addItems(["All follow-ups", "Overdue", "Today", "Upcoming", "None"])
        self.due_filter.currentTextChanged.connect(self.refresh)
        toolbar.addWidget(self.due_filter)
        toolbar.addStretch(1)
        self.actions = ActionToolbar()
        self.actions.add_action("Schedule Follow-up", self.schedule_follow_up, role="primary")
        self.actions.add_action("Open Lead", self.open_selected, role="secondary", icon="open")
        self.status_action = self.actions.add_action("Update Status", self.show_status_menu, role="secondary")
        toolbar.addWidget(self.actions)
        root.addLayout(toolbar)
        self.summary = QLabel()
        self.summary.setProperty("role", "sectionDescription")
        root.addWidget(self.summary)
        self.table = DataTable(["Growth", "Business", "Status", "Last Contact", "Next Follow-up", "Due", "Outcome"])
        self.table.cellDoubleClicked.connect(lambda row, _column: self.open_row(row))
        root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        with self.session_factory() as session:
            leads = list_leads(session)
        leads.sort(key=follow_up_sort_key)
        counts = {key: 0 for key in self.metric_cards}
        for lead in leads:
            counts[due_bucket(lead.next_follow_up_date)] += 1
        for key, card in self.metric_cards.items():
            card.set_value(counts[key])
        selected_filter = self.due_filter.currentText()
        if selected_filter != "All follow-ups":
            leads = [lead for lead in leads if due_bucket(lead.next_follow_up_date) == selected_filter]
        self.table.setRowCount(len(leads))
        for row, lead in enumerate(leads):
            bucket = due_bucket(lead.next_follow_up_date)
            values = [lead.lead_score, lead.name, lead.status, lead.last_contacted_date, lead.next_follow_up_date]
            for column, value in enumerate(values):
                if column == 2:
                    self.table.setCellWidget(row, column, StatusBadge(str(value)))
                else:
                    self.table.setItem(row, column, table_item(value, numeric=column == 0, user_data=lead.id if column == 1 else None))
            self.table.setCellWidget(row, 5, StatusBadge(due_label(lead.next_follow_up_date), due_tone(bucket)))
            self.table.setItem(row, 6, table_item(lead.contact_outcome, tooltip=lead.contact_outcome))
        self.table.fit_columns(stretch_column=1)
        self.summary.setText(f"Showing {len(leads)} leads · overdue work remains first")

    def selected_lead_id(self) -> int | None:
        row = self.table.currentRow()
        item = self.table.item(row, 1) if row >= 0 else None
        return int(item.data(256)) if item and item.data(256) else None

    def open_row(self, row: int) -> None:
        self.table.selectRow(row)
        self.open_selected()

    def open_selected(self) -> None:
        if lead_id := self.selected_lead_id():
            self.lead_open_requested.emit(lead_id)

    def schedule_follow_up(self) -> None:
        lead_id = self.selected_lead_id()
        if not lead_id:
            QMessageBox.information(self, "Select a lead", "Select a Pipeline row before scheduling a follow-up.")
            return
        with self.session_factory() as session:
            lead = session.get(Lead, lead_id)
            current = lead.next_follow_up_date if lead else ""
        dialog = FollowUpDialog(current, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        with self.session_factory() as session:
            update_lead_fields(session, lead_id, next_follow_up_date=dialog.follow_up_date)
            session.commit()
        self.refresh()

    def show_status_menu(self) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        for status in [LeadStatus.CONTACTED, LeadStatus.REPLIED, LeadStatus.MEETING_SCHEDULED, LeadStatus.WON, LeadStatus.LOST]:
            menu.addAction(status.value, lambda _checked=False, value=status.value: self.quick_status(value))
        menu.exec(self.status_action.mapToGlobal(self.status_action.rect().bottomLeft()))

    def quick_status(self, status: str) -> None:
        lead_id = self.selected_lead_id()
        if not lead_id:
            return
        with self.session_factory() as session:
            update_lead_status(session, lead_id, status)
            session.commit()
        self.refresh()


def follow_up_sort_key(lead) -> tuple[int, str, int]:
    order = {"Overdue": 0, "Today": 1, "Upcoming": 2, "None": 3}
    return order[due_bucket(lead.next_follow_up_date)], lead.next_follow_up_date or "9999-12-31", -lead.lead_score


def due_bucket(value: str) -> str:
    today = date.today().isoformat()
    if value and value < today:
        return "Overdue"
    if value == today:
        return "Today"
    if value:
        return "Upcoming"
    return "None"


def due_label(value: str) -> str:
    bucket = due_bucket(value)
    return {"Overdue": "OVERDUE", "Today": "TODAY", "Upcoming": "UPCOMING", "None": "NONE"}[bucket]


def due_tone(bucket: str) -> str:
    return {"Overdue": "danger", "Today": "warning", "Upcoming": "primary", "None": "neutral"}[bucket]


class FollowUpDialog(QDialog):
    def __init__(self, current: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Schedule Follow-up")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QLabel("Schedule the next action")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)
        self.follow_up = QLineEdit(current)
        self.follow_up.setPlaceholderText("YYYY-MM-DD, or blank to clear")
        layout.addWidget(self.follow_up)
        self.help = FieldMessage("Use YYYY-MM-DD. Leave blank only when the lead genuinely has no scheduled next step.")
        layout.addWidget(self.help)
        actions = ActionToolbar()
        actions.add_stretch()
        actions.add_action("Cancel", self.reject, role="tertiary")
        actions.add_action("Save Follow-up", self.validate_and_accept, role="primary")
        layout.addWidget(actions)

    @property
    def follow_up_date(self) -> str:
        return self.follow_up.text().strip()

    def validate_and_accept(self) -> None:
        self.help.clear_error(self.follow_up)
        if self.follow_up_date:
            try:
                date.fromisoformat(self.follow_up_date)
            except ValueError:
                self.help.set_error("Enter a valid date in YYYY-MM-DD format.", self.follow_up)
                return
        self.accept()
