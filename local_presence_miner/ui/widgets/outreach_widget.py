from __future__ import annotations

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import list_contact_points, outreach_approval_errors, set_outreach_approval
from local_presence_miner.database.schema import Lead, OutreachDraft
from local_presence_miner.domain.verification import assess_verification, format_missing_requirements
from local_presence_miner.services.batch_contact_discovery_service import BatchContactDiscoveryService
from local_presence_miner.services.outreach_batch_service import OutreachBatchService
from local_presence_miner.services.outreach_planner import build_outreach_channel_plan
from local_presence_miner.ui.components import InfoBanner, SectionHeader, StatusBadge
from local_presence_miner.ui.components.action_toolbar import ActionToolbar
from local_presence_miner.ui.workers import FunctionWorker


class OutreachWidget(QWidget):
    lead_open_requested = Signal(int)

    def __init__(self, session_factory: sessionmaker[Session], config: AppConfig) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.config = config
        self.drafts: list[OutreachDraft] = []
        self.thread_pool = QThreadPool.globalInstance()
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 22)
        root.setSpacing(10)
        self.summary = QLabel()
        self.summary.setProperty("role", "sectionDescription")
        root.addWidget(self.summary)
        batch_actions = ActionToolbar()
        batch_actions.add_action("Discover Public Contacts (Top 25)", self.discover_batch_contacts, role="primary")
        batch_actions.add_action("Export Outreach-Ready CSV", self.export_ready_batch, role="secondary")
        root.addWidget(batch_actions)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.addWidget(SectionHeader("Drafts", "Select one draft to review."))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show_selected)
        left_layout.addWidget(self.list)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.business = QLabel("Select a draft")
        self.business.setProperty("role", "sectionTitle")
        self.meta = QLabel()
        self.meta.setProperty("role", "sectionDescription")
        self.approval = StatusBadge("Unapproved")
        header_layout.addWidget(self.business)
        header_layout.addWidget(self.meta)
        header_layout.addWidget(self.approval)
        right_layout.addWidget(header)
        self.blocker = InfoBanner("Human review required", "Approval is explicit. The app never sends outreach automatically.", "private")
        right_layout.addWidget(self.blocker)
        self.subject = QLabel()
        self.subject.setWordWrap(True)
        right_layout.addWidget(self.subject)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        right_layout.addWidget(self.body, 1)
        self.actions = ActionToolbar()
        self.approve_button = self.actions.add_action("Approve Draft", self.toggle_approval, role="primary")
        self.copy_button = self.actions.add_action("Copy Approved Draft", self.copy_selected, role="secondary", icon="copy")
        self.actions.add_action("Open Lead", self.open_selected, role="tertiary", icon="open")
        right_layout.addWidget(self.actions)
        splitter.addWidget(right)
        splitter.setSizes([360, 760])
        root.addWidget(splitter, 1)
        self.refresh()

    def refresh(self) -> None:
        current_id = self.selected_id()
        with self.session_factory() as session:
            self.drafts = list(session.execute(select(OutreachDraft).order_by(OutreachDraft.updated_at.desc()).limit(100)).scalars())
            leads = list(session.execute(select(Lead)).scalars())
            lead_names = {lead.id: lead.name for lead in leads}
            plans = [build_outreach_channel_plan(lead, list_contact_points(session, lead.id)) for lead in leads if not lead.suppressed]
        self.lead_names = lead_names
        self.list.clear()
        for draft in self.drafts:
            state = "APPROVED" if draft.approved else "REVIEW REQUIRED"
            item = QListWidgetItem(f"{lead_names.get(draft.lead_id, f'Lead #{draft.lead_id}')}\n{draft.kind}  ·  {state}")
            item.setData(256, draft.id)
            self.list.addItem(item)
        approved = sum(draft.approved for draft in self.drafts)
        email_ready = sum(plan.primary_channel == "Email" for plan in plans)
        phone_ready = sum(plan.primary_channel == "Phone" for plan in plans)
        research_needed = sum(plan.state == "Research required" for plan in plans)
        self.summary.setText(
            f"{len(self.drafts)} drafts · {approved} approved · "
            f"{email_ready} email-first · {phone_ready} phone-first · {research_needed} need contact research · nothing sends automatically"
        )
        if self.drafts:
            index = next((i for i, draft in enumerate(self.drafts) if draft.id == current_id), 0)
            self.list.setCurrentRow(index)
        else:
            self.body.setPlainText("")
            self.business.setText("No outreach drafts yet")
            self.meta.setText("Run a lead search to generate grounded drafts.")

    def selected(self) -> OutreachDraft | None:
        row = self.list.currentRow()
        return self.drafts[row] if 0 <= row < len(self.drafts) else None

    def selected_id(self) -> int | None:
        draft = self.selected()
        return draft.id if draft else None

    def show_selected(self, _row: int) -> None:
        draft = self.selected()
        if not draft:
            return
        with self.session_factory() as session:
            lead = session.get(Lead, draft.lead_id)
            assessment = assess_verification(lead, draft_kind=draft.kind, draft_text=draft.body) if lead else None
            approval_errors = outreach_approval_errors(session, draft, self.config.sender)
        self.business.setText(self.lead_names.get(draft.lead_id, f"Lead #{draft.lead_id}"))
        self.meta.setText(f"{draft.kind} · updated {draft.updated_at.strftime('%b %d, %Y %H:%M')}")
        self.approval.set_status("Approved" if draft.approved else "Review required")
        self.subject.setText(f"<b>Subject:</b> {draft.subject or 'Not used for this draft type'}")
        self.body.setPlainText(draft.body)
        self.approve_button.setText("Unapprove Draft" if draft.approved else "Approve Draft")
        self.approve_button.setProperty("role", "secondary" if draft.approved else "primary")
        self.copy_button.setEnabled(draft.approved)
        if approval_errors:
            self.blocker.set_content("APPROVAL BLOCKED", " ".join(approval_errors))
            self.blocker.setProperty("bannerTone", "warning")
        elif assessment and assessment.missing_required:
            self.blocker.set_content("APPROVAL BLOCKED", "Missing: " + format_missing_requirements(assessment.missing_required))
            self.blocker.setProperty("bannerTone", "warning")
        else:
            self.blocker.set_content("READY FOR HUMAN REVIEW", "Read the exact text, verify claims, then approve. Sending remains manual.")
            self.blocker.setProperty("bannerTone", "success" if draft.approved else "info")
        self.blocker.style().unpolish(self.blocker)
        self.blocker.style().polish(self.blocker)

    def toggle_approval(self) -> None:
        draft = self.selected()
        if not draft:
            return
        try:
            with self.session_factory() as session:
                set_outreach_approval(session, draft.id, not draft.approved, sender=self.config.sender)
                session.commit()
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Approval blocked", str(exc))

    def copy_selected(self) -> None:
        draft = self.selected()
        if not draft or not draft.approved:
            return
        with self.session_factory() as session:
            current = session.get(OutreachDraft, draft.id)
            if current is None or not current.approved:
                QMessageBox.warning(self, "Approval required", "This draft is no longer approved. Refresh and review it.")
                return
            errors = outreach_approval_errors(session, current, self.config.sender)
            if errors:
                QMessageBox.warning(self, "Approval blocked", " ".join(errors))
                return
            text = (f"Subject: {current.subject}\n\n" if current.subject else "") + current.body
        QGuiApplication.clipboard().setText(text)

    def open_selected(self) -> None:
        if draft := self.selected():
            self.lead_open_requested.emit(draft.lead_id)

    def export_ready_batch(self) -> None:
        with self.session_factory() as session:
            summary = OutreachBatchService(self.config.sender).export_ready_csv(session, self.config.output_dir / "exports")
        QMessageBox.information(
            self,
            "Outreach-ready batch exported",
            f"Ready: {summary.exported} lead(s). Needs review: {summary.skipped} lead(s).\n\n"
            f"Ready batch:\n{summary.path}\n\nNeeds-review reasons:\n{summary.review_path}",
        )

    def discover_batch_contacts(self) -> None:
        limit, accepted = QInputDialog.getInt(
            self,
            "Batch public contact discovery",
            "How many top unsuppressed leads should be checked?",
            25,
            1,
            100,
            5,
        )
        if not accepted:
            return
        worker = FunctionWorker(BatchContactDiscoveryService(self.config, self.session_factory).run, limit)
        worker.signals.finished.connect(self._batch_contacts_finished)
        worker.signals.failed.connect(self._batch_contacts_failed)
        self.thread_pool.start(worker)

    def _batch_contacts_finished(self, result: object) -> None:
        attempted = getattr(result, "attempted", 0)
        leads_with_contacts = getattr(result, "leads_with_contacts", 0)
        contacts_saved = getattr(result, "contacts_saved", 0)
        warnings = getattr(result, "warnings", ())
        text = f"Checked {attempted} lead(s).\nFound public contact paths for {leads_with_contacts} lead(s).\nSaved {contacts_saved} contact point(s)."
        if warnings:
            text += "\n\nNotes (first few):\n" + "\n".join(warnings[:8])
        QMessageBox.information(self, "Batch public contact discovery complete", text)
        self.refresh()

    def _batch_contacts_failed(self, details: str) -> None:
        QMessageBox.warning(self, "Batch contact discovery failed", details.splitlines()[-1] if details else "Unknown error")
