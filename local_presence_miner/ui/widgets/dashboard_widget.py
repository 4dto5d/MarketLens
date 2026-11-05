from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.repositories import dashboard_stats, list_leads, loads
from local_presence_miner.database.schema import ActivityLog, OfferHistory
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.domain.verification import assess_verification
from local_presence_miner.ui.components import DataTable, EmptyState, MetricCard, SectionHeader, StatusBadge, table_item
from local_presence_miner.ui.components.action_toolbar import action_button


class DashboardWidget(QWidget):
    lead_open_requested = Signal(int)
    new_search_requested = Signal()
    view_all_requested = Signal()

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 22)
        root.setSpacing(16)

        self.metrics = QGridLayout()
        self.metrics.setHorizontalSpacing(12)
        self.metrics.setVerticalSpacing(12)
        self.metric_cards = {
            "high": MetricCard("High Priority", 0, "Sales Priority 65+", accent="success"),
            "review": MetricCard("Needs Review", 0, "New or incomplete", accent="warning"),
            "followups": MetricCard("Follow-ups Due", 0, "Overdue or today", accent="danger"),
            "ready": MetricCard("Ready for Outreach", 0, "Verification complete", accent="primary"),
            "meetings": MetricCard("Meetings", 0, "Currently scheduled", accent="success"),
            "offers": MetricCard("Open Offers", 0, "Presented or negotiating", accent="primary"),
        }
        for index, card in enumerate(self.metric_cards.values()):
            self.metrics.addWidget(card, 0, index)
            self.metrics.setColumnStretch(index, 1)
        root.addLayout(self.metrics)

        body = QHBoxLayout()
        body.setSpacing(16)
        work_column = QVBoxLayout()
        work_column.setSpacing(8)
        work_column.addWidget(SectionHeader("Today's Work", "Follow-ups and qualified work ordered by urgency."))
        self.work_table = DataTable(["State", "Business", "What needs attention", "Sales", "Growth"])
        self.work_table.cellDoubleClicked.connect(lambda row, _column: self._open_table_lead(self.work_table, row))
        work_column.addWidget(self.work_table)
        body.addLayout(work_column, 3)

        activity_column = QVBoxLayout()
        activity_column.setSpacing(8)
        activity_column.addWidget(SectionHeader("Recent Activity", "Latest durable operator and system events."))
        self.activity_table = DataTable(["Time", "Activity"])
        activity_column.addWidget(self.activity_table)
        body.addLayout(activity_column, 2)
        root.addLayout(body, 3)

        opportunities_header = SectionHeader(
            "Top Prospects",
            "Highest Sales Priority leads currently in the workspace.",
            action_button("View All Leads", self.view_all_requested.emit, role="tertiary"),
        )
        root.addWidget(opportunities_header)
        self.opportunities = DataTable(["Sales", "Class", "Growth", "Business", "Niche", "Location", "Primary Opportunity", "Status"])
        self.opportunities.cellDoubleClicked.connect(lambda row, _column: self._open_table_lead(self.opportunities, row))
        root.addWidget(self.opportunities, 2)
        self.refresh()

    def refresh(self) -> None:
        today = date.today().isoformat()
        with self.session_factory() as session:
            stats = dashboard_stats(session)
            leads = list_leads(session)
            activities = list(session.execute(select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(8)).scalars())
            open_offers = list(session.execute(select(OfferHistory).where(OfferHistory.status.in_(["Presented", "Negotiating", "Accepted"]))).scalars())
        high = [lead for lead in leads if lead.sales_priority_score >= 65]
        review = [lead for lead in leads if lead.status in {LeadStatus.NEW.value, LeadStatus.NEEDS_REVIEW.value}]
        due = [lead for lead in leads if lead.next_follow_up_date and lead.next_follow_up_date <= today]
        ready = [lead for lead in leads if assess_verification(lead).state == "Ready for outreach"]
        meetings = [lead for lead in leads if lead.status == LeadStatus.MEETING_SCHEDULED.value]
        self.metric_cards["high"].set_value(len(high), f"{stats['total_leads']} total leads")
        self.metric_cards["review"].set_value(len(review), "Review before outreach")
        self.metric_cards["followups"].set_value(len(due), "Overdue and due today")
        self.metric_cards["ready"].set_value(len(ready), "Required checks complete")
        self.metric_cards["meetings"].set_value(len(meetings), "Active meeting status")
        self.metric_cards["offers"].set_value(len(open_offers), "Presented / negotiating")
        self._fill_work(leads, today)
        self._fill_opportunities(leads[:8])
        self.activity_table.setRowCount(len(activities))
        for row, activity in enumerate(activities):
            self.activity_table.setItem(row, 0, table_item(activity.created_at.strftime("%b %d %H:%M")))
            self.activity_table.setItem(row, 1, table_item(activity.message, tooltip=activity.message))
        self.activity_table.fit_columns(stretch_column=1)

    def _fill_work(self, leads, today: str) -> None:
        work: list[tuple[int, str, object, str]] = []
        for lead in leads:
            assessment = assess_verification(lead)
            if lead.next_follow_up_date and lead.next_follow_up_date < today:
                work.append((0, "OVERDUE", lead, f"Follow-up was due {lead.next_follow_up_date}"))
            elif lead.next_follow_up_date == today:
                work.append((1, "TODAY", lead, "Follow-up is due today"))
            elif assessment.state == "Ready for outreach" and lead.status not in {LeadStatus.CONTACTED.value, LeadStatus.WON.value}:
                work.append((2, "READY", lead, "Verification complete; review approved outreach"))
            elif lead.sales_priority_score >= 65 and assessment.state != "Ready for outreach":
                work.append((3, "REVIEW", lead, f"{lead.qualification_class}; {assessment.state.lower()}"))
            elif lead.status == LeadStatus.REPLIED.value:
                work.append((4, "REPLIED", lead, "Prospect replied; decide the next action"))
        work.sort(key=lambda item: (item[0], item[2].next_follow_up_date or "9999", -item[2].sales_priority_score, -item[2].lead_score))
        work = work[:10]
        self.work_table.setRowCount(len(work))
        for row, (_priority, state, lead, reason) in enumerate(work):
            self.work_table.setCellWidget(row, 0, StatusBadge(state))
            self.work_table.setItem(row, 1, table_item(lead.name, user_data=lead.id))
            self.work_table.setItem(row, 2, table_item(reason, tooltip=reason))
            self.work_table.setItem(row, 3, table_item(lead.sales_priority_score, numeric=True))
            self.work_table.setItem(row, 4, table_item(lead.lead_score, numeric=True))
        if not work:
            self.work_table.setRowCount(1)
            self.work_table.setSpan(0, 0, 1, 5)
            self.work_table.setCellWidget(
                0,
                0,
                EmptyState("You're caught up", "Run a search or review the Leads workspace to create today's work."),
            )
        self.work_table.fit_columns(stretch_column=2)

    def _fill_opportunities(self, leads) -> None:
        self.opportunities.setRowCount(len(leads))
        for row, lead in enumerate(leads):
            signals = loads(lead.target_signals_json, [])
            location = lead.address or (f"ZIP {lead.target_zip_code}" if lead.target_zip_code else "Not recorded")
            values = [
                lead.sales_priority_score,
                lead.qualification_class,
                lead.lead_score,
                lead.name,
                lead.category,
                location,
                signals[0] if signals else "Review opportunity",
                lead.status,
            ]
            for column, value in enumerate(values):
                if column == 7:
                    self.opportunities.setCellWidget(row, column, StatusBadge(str(value)))
                else:
                    self.opportunities.setItem(
                        row,
                        column,
                        table_item(value, numeric=column in {0, 2}, user_data=lead.id if column == 3 else None),
                    )
        self.opportunities.fit_columns(stretch_column=6)

    def _open_table_lead(self, table: DataTable, row: int) -> None:
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item and item.data(256):
                self.lead_open_requested.emit(int(item.data(256)))
                return
