from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.repositories import list_leads, loads, update_lead_status
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.domain.verification import assess_verification, format_missing_requirements
from local_presence_miner.ui.components import (
    InfoBanner,
    RevenueLeakCard,
    ScoreBadge,
    SectionHeader,
    StatusBadge,
    VerificationProgress,
)
from local_presence_miner.ui.components.action_toolbar import ActionToolbar


class ReviewQueueWidget(QWidget):
    lead_open_requested = Signal(int)

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.leads = []
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 22)
        root.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(SectionHeader("Review Inbox", "New and Needs Review leads, highest Sales Priority first."))
        self.queue = QListWidget()
        self.queue.currentRowChanged.connect(self.show_selected)
        self.queue.itemDoubleClicked.connect(lambda _item: self.open_selected())
        left.addWidget(self.queue)
        root.addLayout(left, 2)
        self.detail = QVBoxLayout()
        self.detail.setSpacing(10)
        self.name = QLabel("Select a lead")
        self.name.setProperty("role", "pageTitle")
        self.meta = QLabel()
        self.meta.setProperty("role", "pageDescription")
        self.detail.addWidget(self.name)
        self.detail.addWidget(self.meta)
        self.badges = QHBoxLayout()
        self.detail.addLayout(self.badges)
        self.verification = VerificationProgress()
        self.detail.addWidget(self.verification)
        self.blocker = InfoBanner("Select a lead", "Choose an item from the review inbox.")
        self.detail.addWidget(self.blocker)
        self.leaks = QVBoxLayout()
        self.detail.addWidget(SectionHeader("Top Revenue Leaks"))
        self.detail.addLayout(self.leaks)
        self.actions = ActionToolbar()
        self.actions.add_action("Reject", lambda: self.set_status(LeadStatus.NOT_QUALIFIED.value), role="danger")
        self.actions.add_action("Needs More Review", lambda: self.set_status(LeadStatus.NEEDS_REVIEW.value))
        self.actions.add_action("Qualify", lambda: self.set_status(LeadStatus.QUALIFIED.value), role="primary")
        self.actions.add_action("Open Full Lead", self.open_selected, role="secondary")
        self.actions.add_action("Next Lead", self.next_lead, role="tertiary", icon="next")
        self.detail.addWidget(self.actions)
        self.detail.addStretch(1)
        detail_widget = QWidget()
        detail_widget.setLayout(self.detail)
        root.addWidget(detail_widget, 3)
        self.refresh()

    def refresh(self) -> None:
        current_id = self.selected_id()
        with self.session_factory() as session:
            self.leads = [lead for lead in list_leads(session) if lead.status in {LeadStatus.NEW.value, LeadStatus.NEEDS_REVIEW.value}]
        self.queue.clear()
        for lead in self.leads:
            item = QListWidgetItem(
                f"{lead.sales_priority_score:>3}   {lead.name}\n      {lead.qualification_class} · Growth {lead.lead_score} · {assess_verification(lead).state}"
            )
            item.setData(256, lead.id)
            item.setToolTip(lead.address or lead.name)
            self.queue.addItem(item)
        if self.leads:
            index = next((i for i, lead in enumerate(self.leads) if lead.id == current_id), 0)
            self.queue.setCurrentRow(index)
        else:
            self.name.setText("Review queue is clear")
            self.meta.setText("New leads will appear here after a search.")

    def show_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.leads):
            return
        lead = self.leads[row]
        assessment = assess_verification(lead)
        self.name.setText(lead.name)
        self.meta.setText(f"{lead.category} · {lead.address or 'Location not recorded'}")
        while self.badges.count():
            item = self.badges.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.badges.addWidget(ScoreBadge(lead.sales_priority_score, compact=True))
        self.badges.addWidget(StatusBadge(lead.qualification_class))
        self.badges.addWidget(StatusBadge(lead.status))
        self.badges.addStretch(1)
        self.verification.set_progress(assessment.completed, assessment.total, assessment.state)
        if assessment.missing_required:
            self.blocker.set_content("OUTREACH BLOCKED", "Missing: " + format_missing_requirements(assessment.missing_required))
            self.blocker.setProperty("bannerTone", "warning")
        else:
            self.blocker.set_content("READY FOR OUTREACH REVIEW", "Required verification is complete. Review the exact draft before approval.")
            self.blocker.setProperty("bannerTone", "success")
        self.blocker.style().unpolish(self.blocker)
        self.blocker.style().polish(self.blocker)
        while self.leaks.count():
            item = self.leaks.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for signal in loads(lead.target_signals_json, [])[:4]:
            self.leaks.addWidget(RevenueLeakCard(signal, revenue_leak_explanation(signal), "Observed in the collected public audit."))

    def selected_id(self) -> int | None:
        item = self.queue.currentItem()
        return int(item.data(256)) if item and item.data(256) else None

    def open_selected(self) -> None:
        if lead_id := self.selected_id():
            self.lead_open_requested.emit(lead_id)

    def set_status(self, status: str) -> None:
        if not (lead_id := self.selected_id()):
            return
        with self.session_factory() as session:
            update_lead_status(session, lead_id, status)
            session.commit()
        self.refresh()

    def next_lead(self) -> None:
        if self.queue.count():
            self.queue.setCurrentRow(min(self.queue.currentRow() + 1, self.queue.count() - 1))


def revenue_leak_explanation(signal: str) -> str:
    lowered = signal.lower()
    if "website" in lowered:
        return "Customers may have a weaker path to understand services, trust the business, or take the next step."
    if "review" in lowered:
        return "Trust evidence may be less visible than nearby alternatives."
    if "contact" in lowered or "quote" in lowered or "call" in lowered:
        return "Prospects may need extra effort to request an estimate or contact the business."
    return "This public-facing gap may add friction to the customer's decision or contact path."
