from __future__ import annotations

import json
import webbrowser
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import (
    delete_contact_interaction,
    lead_contact_readiness_errors,
    lead_google_details_retrieved,
    list_contact_interactions,
    list_contact_points,
    loads,
    log_activity,
    outreach_approval_errors,
    replace_contact_points,
    set_outreach_approval,
    set_selected_contact_point,
    update_lead_fields,
    update_lead_status,
)
from local_presence_miner.database.schema import (
    CompetitorRecord,
    ContactInteraction,
    ContactPoint,
    Lead,
    OutreachDraft,
    SearchVisibilityObservation,
    SearchVisibilityProbe,
)
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.domain.offer_registry import offer_definition
from local_presence_miner.domain.verification import VERIFICATION_ITEMS, assess_verification, format_missing_requirements
from local_presence_miner.services.adaptive_outreach_service import format_smart_offer
from local_presence_miner.services.adaptive_sales_asset_service import (
    build_adaptive_sales_plan,
    refresh_adaptive_sales_assets,
    refresh_after_interaction_change,
)
from local_presence_miner.services.comparison_service import ComparisonService
from local_presence_miner.services.contact_discovery import WebsiteContactDiscovery
from local_presence_miner.services.google_presence_service import GooglePresenceService, assessment_to_dict
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.mockup_service import MockupService
from local_presence_miner.services.outreach_planner import build_outreach_channel_plan
from local_presence_miner.services.owner_brief import build_owner_brief
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.prospect_finding_service import proposal_ai_choices
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.search_offer_intelligence import accept_advisory_offer
from local_presence_miner.services.seller_pricing_service import SellerPricingService
from local_presence_miner.services.static_site_service import StaticSiteService
from local_presence_miner.services.suppression_service import SuppressionService
from local_presence_miner.services.website_builder_prompt_service import WebsiteBuilderPromptService
from local_presence_miner.ui.components import (
    ActionToolbar,
    DataTable,
    InfoBanner,
    MetricCard,
    PricingRecommendationPanel,
    RevenueLeakCard,
    ScoreBadge,
    SectionHeader,
    StatusBadge,
    action_button,
    confirm_destructive,
    table_item,
)
from local_presence_miner.ui.dialogs.commercial_review_dialog import CommercialReviewDialog
from local_presence_miner.ui.dialogs.contact_interaction_dialog import ContactInteractionDialog
from local_presence_miner.ui.dialogs.guided_call_dialog import GuidedCallDialog
from local_presence_miner.ui.dialogs.offer_history_dialog import OfferHistoryDialog
from local_presence_miner.ui.dialogs.opportunity_workflow_dialog import OpportunityWorkflowDialog
from local_presence_miner.ui.dialogs.outreach_editor_dialog import OutreachEditorDialog
from local_presence_miner.ui.dialogs.proposal_evidence_dialog import ProposalEvidenceDialog
from local_presence_miner.ui.widgets.prospect_findings_widget import ProspectFindingsWidget
from local_presence_miner.ui.widgets.seo_intelligence_widget import SEOIntelligenceWidget
from local_presence_miner.ui.workers import FunctionWorker


class LeadDetailDialog(QDialog):
    def __init__(self, config: AppConfig, session_factory: sessionmaker[Session], lead_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lead Workspace")
        self.resize(1180, 780)
        self.setMinimumSize(1020, 680)
        self.config = config
        self.session_factory = session_factory
        self.lead_id = lead_id
        self.thread_pool = QThreadPool.globalInstance()
        self.header = QWidget()
        self.header_layout = QVBoxLayout(self.header)
        self.header_layout.setContentsMargins(18, 14, 18, 6)
        self.tabs = QTabWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addWidget(self.tabs)
        self.load()

    def load(self) -> None:
        self.tabs.clear()
        while self.header_layout.count():
            item = self.header_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

            previous_plan_state = lead.commercial_plan_state
            recompute_lead_commercial_candidate(session, lead, "Current commercial evidence changed or expired")
            # A query inside invalidation can autoflush and clear dirty before
            # this boundary commits the newly stale state.
            if lead.commercial_plan_state != previous_plan_state or session.dirty or session.new:
                session.commit()
            competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
            drafts = list(session.execute(select(OutreachDraft).where(OutreachDraft.lead_id == lead.id)).scalars())
            interactions = list_contact_interactions(session, lead.id)
            contacts = list_contact_points(session, lead.id)
            self.build_header(lead, competitors, session)
            self.tabs.addTab(self.overview_tab(lead, competitors), "Before You Contact")
            self.tabs.addTab(self.contact_intelligence_tab(lead, contacts), "Contact Intelligence")
            self.tabs.addTab(self.audit_tab(lead), "Audit Evidence")
            self.tabs.addTab(self.google_tab(lead), "Google Presence")
            self.tabs.addTab(self.visibility_tab(session, lead), "Search Visibility")
            self.tabs.addTab(SEOIntelligenceWidget(self.session_factory, lead.id), "SEO Intelligence")
            self.tabs.addTab(self.competitor_tab(competitors), "Competitors")
            self.tabs.addTab(self.owner_mode_tab(session, lead, competitors), "Owner Mode")
            self.tabs.addTab(self.offer_tab(session, lead, competitors), "Smart Offer")
            self.tabs.addTab(self.outreach_tab(drafts), "Outreach")
            self.tabs.addTab(self.contact_history_tab(interactions, drafts), "Activity")
            self.tabs.addTab(self.crm_tab(lead), "CRM")
            self.tabs.addTab(self.verification_tab(lead), "Verification")
            self.tabs.addTab(self.actions_tab(lead), "Reports & Actions")

    def build_header(self, lead: Lead, competitors: list[CompetitorRecord], session: Session) -> None:
        top = QHBoxLayout()
        title = QVBoxLayout()
        name = QLabel(lead.name)
        name.setProperty("role", "pageTitle")
        meta = QLabel(f"{lead.category} · {lead.address or 'Location not captured'} · {lead.status}")
        meta.setProperty("role", "pageDescription")
        title.addWidget(name)
        title.addWidget(meta)
        top.addLayout(title, 1)
        top.addWidget(ScoreBadge(lead.sales_priority_score, compact=True))
        top.addWidget(StatusBadge(lead.status))
        actions = ActionToolbar()
        actions.add_action("Copy Website URL", self.open_website, role="secondary")
        actions.add_action("Open Google", self.open_google, role="secondary")
        actions.add_action("Record Contact", self.add_interaction, role="primary")
        actions.add_action("Guided Opportunity", self.open_opportunity_workflow, role="secondary")
        actions.add_action("Evidence / Delivery Review", self.review_commercial_evidence, role="secondary")
        top.addWidget(actions)
        self.header_layout.addLayout(top)
        assessment = assess_verification(lead)
        metrics = QGridLayout()
        recommendation = SellerPricingService().recommend_for_lead(session, lead, competitors)
        google_presence = assessment_to_dict(lead.google_presence)
        values = [
            ("SALES PRIORITY", f"{lead.sales_priority_score}/100", f"{lead.qualification_class} · {lead.qualification_confidence} confidence", "success"),
            ("GROWTH SCORE", f"{lead.lead_score}/100", "Legacy triage, not buyer value", "primary"),
            ("SERVICE-COST BAND", recommendation.project.range_text, "Catalog reference, not ROI", "success"),
            ("RECOMMENDED ASK", recommendation.recommended_text, f"{recommendation.confidence} evidence", "primary"),
            ("VERIFICATION", f"{assessment.completed}/{assessment.total}", assessment.state, "warning"),
            ("COMPETITOR GAP", competitor_gap_label(lead, competitors), f"{len(competitors)} selected", "warning"),
            (
                "GOOGLE OPPORTUNITY",
                f"{google_presence.get('opportunity_score', 0)}/100" if google_presence else "Not assessed",
                f"{google_presence.get('confidence', 'Low')} confidence" if google_presence else "Run search or Demo Mode",
                "primary",
            ),
            ("NEXT FOLLOW-UP", lead.next_follow_up_date or "—", lead.contact_outcome or "Not yet contacted", "neutral"),
        ]
        for index, (label, value, support, accent) in enumerate(values):
            row, column = divmod(index, 4)
            metrics.addWidget(MetricCard(label, value, support, accent=accent), row, column)
            metrics.setColumnStretch(column, 1)
        self.header_layout.addLayout(metrics)

    def overview_tab(self, lead: Lead, competitors: list[CompetitorRecord]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        with self.session_factory() as session:
            brief = build_owner_brief(lead, competitors, session)
            pricing = SellerPricingService().recommend_for_lead(session, lead, competitors)
        assessment = assess_verification(lead)
        tone = "success" if assessment.state == "Ready for outreach" else "warning"
        layout.addWidget(
            InfoBanner(
                "READY TO CONTACT" if tone == "success" else "PRE-CONTACT CHECK",
                "Required verification is complete. Review the exact draft before sending."
                if tone == "success"
                else (
                    "Finish: " + format_missing_requirements(assessment.missing_required)
                    if assessment.missing_required
                    else "Use professional judgment and manually confirm the public-facing claims."
                ),
                tone,
            )
        )
        grid = QGridLayout()
        why = QFrame()
        why.setProperty("surface", "card")
        why_layout = QVBoxLayout(why)
        why_layout.setContentsMargins(14, 12, 14, 12)
        why_layout.addWidget(SectionHeader("Why this lead", "Observable public signals, not a close prediction."))
        review_summary = (
            f"{lead.review_count} Google review(s)" + (f" at {lead.rating}" if lead.rating else "")
            if lead_google_details_retrieved(lead)
            else "Google rating and reviews: Unknown — rich details were not retrieved"
        )
        why_layout.addWidget(QLabel(f"• {review_summary}"))
        for signal in (loads(lead.target_signals_json, []) or ["No verified revenue leak captured yet."])[:3]:
            why_layout.addWidget(QLabel(f"• {signal}"))
        why_layout.addWidget(QLabel(f"• {len(competitors)} selected competitor(s); gap: {competitor_gap_label(lead, competitors)}"))
        qualification = loads(lead.qualification_json, {})
        why_layout.addWidget(
            QLabel(f"• Sales Priority {lead.sales_priority_score}/100 · {lead.qualification_class} · {lead.qualification_confidence} confidence")
        )
        if qualification.get("next_action"):
            next_step = QLabel("Next: " + str(qualification["next_action"]))
            next_step.setWordWrap(True)
            why_layout.addWidget(next_step)
        lead_with = QFrame()
        lead_with.setProperty("surface", "card")
        lead_layout = QVBoxLayout(lead_with)
        lead_layout.setContentsMargins(14, 12, 14, 12)
        lead_layout.addWidget(SectionHeader("Lead with", "Keep this grounded in the public evidence."))
        opening = QLabel(f"“{brief.recommended_opening}”")
        opening.setWordWrap(True)
        opening.setStyleSheet("font-size: 15px; color: #BFDBFE;")
        lead_layout.addWidget(opening)
        lead_layout.addStretch(1)
        grid.addWidget(why, 0, 0)
        grid.addWidget(lead_with, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        pricing_panel = PricingRecommendationPanel(pricing)
        layout.addWidget(pricing_panel)
        proof = QLabel(
            "RELEVANT PROOF\n"
            + (pricing.relevant_proof_sentence or "No relevant verified proof is recorded yet. Keep the opening focused on the observed opportunity.")
        )
        proof.setWordWrap(True)
        proof.setProperty("surface", "subtle")
        layout.addWidget(proof)
        actions = ActionToolbar()
        actions.add_action("Guided Call", self.open_guided_call, role="secondary")
        actions.add_action("Review Email", lambda: self.select_tab("Outreach"), role="secondary")
        actions.add_action("View Competitors", lambda: self.select_tab("Competitors"), role="secondary")
        actions.add_action("Record Contact", self.add_interaction, role="primary")
        layout.addWidget(actions)
        layout.addStretch(1)
        return widget

    def review_commercial_evidence(self) -> None:
        CommercialReviewDialog(self.session_factory, self.lead_id, self).exec()
        self.load()

    def open_opportunity_workflow(self) -> None:
        dialog = OpportunityWorkflowDialog(self.session_factory, self.lead_id, self)
        if dialog.exec():
            self.open_workflow_destination(dialog.destination)

    def open_workflow_destination(self, destination: str) -> None:
        actions = {"Record Contact": self.add_interaction, "Guided Call": self.open_guided_call,
                   "Delivery Review": self.review_commercial_evidence}
        if destination in actions:
            actions[destination]()
        elif destination:
            self.select_tab(destination)

    def contact_intelligence_tab(self, lead: Lead, contacts: list[ContactPoint]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        plan = build_outreach_channel_plan(lead, contacts)
        tone = "success" if plan.state == "Contactable" else ("warning" if plan.state in {"Limited", "Research required"} else "error")
        layout.addWidget(
            InfoBanner(
                f"BEST CURRENT ROUTE: {plan.primary_channel.upper()}",
                plan.reason + (f" Secondary: {plan.secondary_channel}." if plan.secondary_channel else ""),
                tone,
            )
        )
        actions = ActionToolbar()
        actions.add_action("Discover / Refresh Public Contacts", self.discover_public_contacts, role="primary")
        actions.add_action("Guided Call", self.open_guided_call, role="secondary")
        if plan.recipient:
            actions.add_action("Copy Email", lambda: QGuiApplication.clipboard().setText(plan.recipient), role="secondary", icon="copy")
        if plan.phone:
            actions.add_action("Copy Phone", lambda: QGuiApplication.clipboard().setText(plan.phone), role="secondary", icon="copy")
        layout.addWidget(actions)
        layout.addWidget(
            SectionHeader(
                "Public contact points", "Only details visibly published by the business or already present in Google Places are stored. No guessed emails."
            )
        )
        if not contacts:
            layout.addWidget(
                InfoBanner(
                    "No discovered contact details yet",
                    "Run public contact discovery. It checks the official homepage and a small number of contact/about/team pages only.",
                    "info",
                )
            )
        else:
            preferred_row = ActionToolbar()
            preferred = QComboBox()
            for contact in contacts:
                preferred.addItem(f"{contact.kind.title()} · {contact.value}", contact.id)
                if contact.selected:
                    preferred.setCurrentIndex(preferred.count() - 1)
            preferred_row.layout.addWidget(QLabel("Preferred route:"))
            preferred_row.layout.addWidget(preferred)
            preferred_row.add_action("Set Preferred", lambda: self.set_primary_contact(preferred.currentData()), role="secondary")
            layout.addWidget(preferred_row)
            table = DataTable(["Use", "Type", "Value", "Confidence", "Source", "Evidence page"])
            table.setHorizontalHeaderLabels(["Use", "Type", "Value", "Confidence", "Source", "Evidence page"])
            for contact in contacts:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, table_item("Primary" if contact.selected else ""))
                table.setItem(row, 1, table_item(contact.kind.title()))
                table.setItem(row, 2, table_item(contact.value))
                table.setItem(row, 3, table_item(contact.confidence))
                table.setItem(row, 4, table_item(contact.source_type.replace("_", " ").title()))
                table.setItem(row, 5, table_item(contact.source_url))
            table.resizeColumnsToContents()
            layout.addWidget(table)
        if plan.warnings:
            layout.addWidget(InfoBanner("Contact notes", " ".join(plan.warnings), "warning"))
        layout.addWidget(
            InfoBanner(
                "Enrichment boundary",
                "This version finds ordinary public contact information from the official business website. "
                "Decision-maker enrichment such as Apollo should be a later controlled provider step, not guessed locally.",
                "private",
            )
        )
        layout.addStretch(1)
        return widget

    def verification_tab(self, lead: Lead) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Confirm these items manually before describing the lead as ready for outreach."))
        saved = loads(lead.verification_json, {})
        self.verification_boxes: dict[str, QCheckBox] = {}
        for key, label in VERIFICATION_ITEMS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(bool(saved.get(key, False)))
            self.verification_boxes[key] = checkbox
            layout.addWidget(checkbox)
        save = QPushButton("Save Verification Checklist")
        save.clicked.connect(self.save_verification)
        layout.addWidget(save)
        completed = sum(box.isChecked() for box in self.verification_boxes.values())
        layout.addWidget(QLabel(f"Progress: {completed} / {len(VERIFICATION_ITEMS)} verified"))
        assessment = assess_verification(lead)
        layout.addWidget(QLabel(f"Outreach state: <b>{assessment.state}</b>"))
        if assessment.missing_required:
            layout.addWidget(QLabel("Required before approval: " + format_missing_requirements(assessment.missing_required)))
        if lead.suppressed:
            layout.addWidget(QLabel("BLOCKED: this lead is suppressed and cannot become ready for outreach."))
        return widget

    def contact_history_tab(self, interactions: list[ContactInteraction], drafts: list[OutreachDraft]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        header = SectionHeader("Contact activity", "Record what actually happened after each manual call, email, or follow-up.")
        header.add_action(action_button("Record Contact", self.add_interaction, role="primary"))
        layout.addWidget(header)
        if not interactions:
            layout.addWidget(InfoBanner("No contact activity", "When you reach out manually, capture the outcome and the signal they responded to.", "info"))
        drafts_by_id = {draft.id: draft for draft in drafts}
        for interaction in interactions:
            linked = drafts_by_id.get(interaction.outreach_draft_id)
            linked_text = f"Linked draft: #{linked.id} — {linked.kind}<br>" if linked else ""
            card = QFrame()
            card.setProperty("surface", "card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.addWidget(QLabel(f"{interaction.interaction_datetime} · {interaction.direction} {interaction.method}"))
            line = QLabel(
                f"Outcome: {interaction.outcome or 'Not recorded'} · Follow-up: {interaction.follow_up_date or 'None'}"
                + (f" · Objection: {interaction.objection}" if interaction.objection else "")
            )
            line.setProperty("tone", "muted")
            card_layout.addWidget(line)
            signals = loads(interaction.response_signals_json, [])
            if signals:
                card_layout.addWidget(QLabel("Responded to: " + ", ".join(signals)))
            if linked_text or interaction.notes:
                detail = QLabel((linked_text.replace("<br>", "") + interaction.notes).strip())
                detail.setWordWrap(True)
                card_layout.addWidget(detail)
            row = ActionToolbar()
            row.add_action("Edit", lambda _checked=False, item_id=interaction.id: self.edit_interaction(item_id), role="secondary")
            row.add_action("Delete", lambda _checked=False, item_id=interaction.id: self.delete_interaction(item_id), role="danger")
            card_layout.addWidget(row)
            layout.addWidget(card)
        layout.addStretch(1)
        return widget

    def owner_mode_tab(self, session: Session, lead: Lead, competitors: list[CompetitorRecord]) -> QWidget:
        brief = build_owner_brief(lead, competitors, session)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            f"{lead.name}\n\n"
            f"Sales Priority\n{lead.sales_priority_score}/100 · {lead.qualification_class} · {lead.qualification_confidence} confidence\n\n"
            f"Growth Score\n{lead.lead_score}/100\n\n"
            f"Estimated Opportunity\n{brief.opportunity}\n\n"
            f"Business Size\n{brief.business_size}\n\n"
            f"Likely Decision Maker\n{brief.likely_decision_maker}\n\n"
            "Primary Revenue Leaks\n- " + "\n- ".join(brief.revenue_leaks) + f"\n\nRecommended Opening\n{brief.recommended_opening}\n\n"
            f"Estimated Build Difficulty\n{brief.build_difficulty}\n\n"
            f"Suggested Package\n{brief.suggested_package}\n{brief.suggested_range}\n\n"
            f"Evidence Confidence\n{brief.evidence_confidence}%\n{brief.confidence_note}\n\n"
            f"SERVICE-COST BAND (not ROI)\n{brief.project_value_range}\n\n"
            f"YOUR CURRENT PRICING\n"
            f"Easy-close: {format_money(brief.easy_close_ask)}\n"
            f"Recommended: {format_money(brief.recommended_ask)}\n"
            f"Stretch: {format_money(brief.stretch_ask)}\n"
            f"Seller evidence confidence: {brief.pricing_confidence}\n\n"
            "WHY THIS NUMBER?\n- " + "\n- ".join(brief.pricing_reasoning) + f"\n\nWHAT TO SAY IF PRICE COMES UP\n{brief.price_answer}\n\n"
            "What To Verify Before Calling\n- " + "\n- ".join(brief.verify_before_calling or ["Checklist complete; still use professional judgment."])
        )
        layout.addWidget(text)
        return widget

    def crm_tab(self, lead: Lead) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.address = QLineEdit(lead.address)
        self.phone = QLineEdit(lead.phone)
        self.website = QLineEdit(lead.website)
        self.google_maps_url = QLineEdit(lead.google_maps_url)
        self.crm_yelp_url = QLineEdit(lead.yelp_url)
        self.owner = QLineEdit(lead.owner)
        self.tags = QLineEdit(lead.tags)
        self.next_follow_up = QLineEdit(lead.next_follow_up_date)
        self.next_follow_up.setPlaceholderText("YYYY-MM-DD")
        self.last_contacted = QLineEdit(lead.last_contacted_date)
        self.last_contacted.setPlaceholderText("YYYY-MM-DD")
        self.contact_method = QLineEdit(lead.contact_method)
        self.contact_outcome = QLineEdit(lead.contact_outcome)
        self.notes = QTextEdit(lead.operator_notes)
        form.addRow("Address", self.address)
        form.addRow("Phone", self.phone)
        form.addRow("Website", self.website)
        form.addRow("Google Maps URL", self.google_maps_url)
        form.addRow("Yelp/other URL", self.crm_yelp_url)
        form.addRow("Lead owner", self.owner)
        form.addRow("Tags", self.tags)
        form.addRow("Next follow-up", self.next_follow_up)
        form.addRow("Last contacted", self.last_contacted)
        form.addRow("Contact method", self.contact_method)
        form.addRow("Contact outcome", self.contact_outcome)
        form.addRow("Operator notes", self.notes)
        layout.addLayout(form)
        save = QPushButton("Save Lead And CRM Fields")
        save.clicked.connect(self.save_crm_fields)
        layout.addWidget(save)
        return widget

    def audit_tab(self, lead: Lead) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        widget = QWidget()
        widget.setObjectName("MainContent")
        scroll.setWidget(widget)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        findings = ProspectFindingsWidget(self.session_factory, lead.id)
        findings.findings_changed.connect(self.refresh_after_finding_change)
        layout.addWidget(findings)
        audit = lead.audit
        if not audit:
            layout.addWidget(
                InfoBanner("No audit captured yet", "Run or refresh a search with website auditing enabled to collect public-site evidence.", "warning")
            )
            return scroll
        layout.addWidget(SectionHeader("Captured audit evidence", "Raw observations remain below. Use Source-linked findings above "
                                       "for durable contact-fact review; legacy row annotations do not override that review."))
        layout.addWidget(
            InfoBanner(
                "Collected public evidence",
                f"Reachable: {'Yes' if audit.reachable else 'No'} · HTTP {audit.status_code or '—'} · "
                f"Rendered audit: {audit.rendered_status} · PageSpeed: {audit.pagespeed_status}",
            )
        )
        review_values = loads(lead.verification_json, {})
        evidence = loads(audit.evidence_json, {})
        for index, weakness in enumerate(loads(audit.weaknesses_json, [])[:8]):
            card = QFrame()
            card.setProperty("surface", "card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.addWidget(RevenueLeakCard(weakness, audit_explanation(weakness), evidence.get(str(index), "Auto-observed public audit"), "High"))
            row = QHBoxLayout()
            row.addWidget(QLabel("Verification"))
            state = QComboBox()
            state.addItems(["Unverified", "Auto-observed", "Human verified", "Rejected / false positive"])
            saved = review_values.get(f"audit_review_{index}", "Auto-observed")
            state.setCurrentText(saved if saved in [state.itemText(i) for i in range(state.count())] else "Auto-observed")
            state.currentTextChanged.connect(lambda value, key=f"audit_review_{index}": self.save_audit_review(key, value))
            row.addWidget(state)
            row.addStretch(1)
            card_layout.addLayout(row)
            layout.addWidget(card)
        screen_row = ActionToolbar()
        if audit.desktop_screenshot and Path(audit.desktop_screenshot).exists():
            screen_row.add_action("View Desktop Screenshot", lambda: self.open_local_file(audit.desktop_screenshot), role="secondary")
        if audit.mobile_screenshot and Path(audit.mobile_screenshot).exists():
            screen_row.add_action("View Mobile Screenshot", lambda: self.open_local_file(audit.mobile_screenshot), role="secondary")
        if screen_row.layout.count():
            layout.addWidget(screen_row)
        details = QTextEdit(
            "Raw checks\n"
            + json.dumps(loads(audit.checks_json, {}), indent=2)
            + "\n\nRendered checks\n"
            + json.dumps(loads(audit.rendered_checks_json, {}), indent=2)
            + "\n\nMetrics\n"
            + json.dumps(loads(audit.metrics_json, {}), indent=2)
        )
        details.setReadOnly(True)
        details.setMaximumHeight(155)
        layout.addWidget(details)
        layout.addStretch(1)
        return scroll

    def refresh_after_finding_change(self) -> None:
        self.load()
        self.select_tab("Audit Evidence")

    def save_audit_review(self, key: str, value: str) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            values = loads(lead.verification_json, {})
            values[key] = value
            update_lead_fields(session, self.lead_id, verification_json=json.dumps(values))
            session.commit()

    def open_local_file(self, path: str) -> None:
        webbrowser.open(Path(path).resolve().as_uri())

    def google_tab(self, lead: Lead) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        widget = QWidget()
        scroll.setWidget(widget)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        assessment = assessment_to_dict(lead.google_presence)
        layout.addWidget(
            InfoBanner(
                "PUBLIC GOOGLE EVIDENCE ONLY",
                "This uses supported public Places fields. It does not access a private Business Profile dashboard, "
                "prove ownership, or claim exact Maps ranking.",
                "info",
            )
        )
        if not assessment:
            layout.addWidget(
                InfoBanner(
                    "Not assessed",
                    "Run Demo Mode or a configured Google Places search to create a Google Presence assessment.",
                    "warning",
                )
            )
            layout.addStretch(1)
            return scroll
        metrics = QGridLayout()
        metrics.addWidget(MetricCard("STRENGTH", f"{assessment['strength_score']}/100", "Observable public presence", accent="primary"), 0, 0)
        metrics.addWidget(MetricCard("OPPORTUNITY", f"{assessment['opportunity_score']}/100", "Evidence-backed improvement", accent="warning"), 0, 1)
        metrics.addWidget(MetricCard("CONFIDENCE", assessment["confidence"], "Low, Moderate, or Strong", accent="success"), 0, 2)
        metrics.addWidget(MetricCard("RECOMMENDED", assessment["recommended_action"], "Feeds Smart Offer", accent="primary"), 0, 3)
        layout.addLayout(metrics)
        layout.addWidget(SectionHeader("Top issue", assessment["top_issue"]))
        for title, key in (
            ("Observed strengths", "observed_strengths"),
            ("Observed gaps", "observed_gaps"),
            ("Competitor context", "competitor_summary"),
            ("Unknowns requiring review", "unknowns"),
        ):
            frame = QFrame()
            frame.setProperty("surface", "card")
            frame_layout = QVBoxLayout(frame)
            frame_layout.addWidget(SectionHeader(title))
            values = assessment.get(key, []) or ["None recorded."]
            for value in values:
                label = QLabel(f"• {value}")
                label.setWordWrap(True)
                frame_layout.addWidget(label)
            layout.addWidget(frame)
        source_count = len([item for item in assessment.get("provenance", []) if not item.get("derived")])
        layout.addWidget(QLabel(f"Provenance: {source_count} public source snapshot(s) plus transparent local derivation."))
        layout.addStretch(1)
        return scroll

    def visibility_tab(self, session: Session, lead: Lead) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(
            InfoBanner(
                "QUERY-SCOPED PLACES EVIDENCE",
                "These positions describe specific collected Places response windows. They are not exact Google Maps "
                "or Map Pack rankings, and Demo fixture rows are not live evidence.",
                "info",
            )
        )
        rows = list(
            session.execute(
                select(SearchVisibilityObservation, SearchVisibilityProbe)
                .join(SearchVisibilityProbe, SearchVisibilityProbe.id == SearchVisibilityObservation.probe_id)
                .where(SearchVisibilityObservation.lead_id == lead.id)
                .order_by(SearchVisibilityProbe.observed_at.desc(), SearchVisibilityObservation.source_position)
            )
        )
        if not rows:
            layout.addWidget(
                InfoBanner(
                    "No canonical visibility history",
                    "Legacy search_position values are intentionally not converted into visibility observations.",
                    "warning",
                )
            )
            layout.addStretch(1)
            return widget

        table = DataTable(["Observed", "Source", "Query", "Source Position", "Retained", "Collection", "Context"])
        table.setRowCount(len(rows))
        for row_index, (observation, probe) in enumerate(rows):
            source = "Demo fixture" if probe.source == "demo_fixture" else "Google Places"
            collection = probe.collection_status.title()
            if probe.truncated:
                collection += " · capped window"
            values = [
                probe.observed_at.isoformat(timespec="seconds"),
                source,
                probe.query_text,
                observation.source_position,
                observation.retained_position if observation.retained_position is not None else "—",
                collection,
                (probe.comparability_fingerprint or probe.context_fingerprint)[:12],
            ]
            for column, value in enumerate(values):
                table.setItem(row_index, column, table_item(value, numeric=column in {3, 4}))
        table.fit_columns(stretch_column=2)
        layout.addWidget(table)
        layout.addWidget(
            QLabel(
                "Only fresh, complete live observations with matching strategy and query context can support a "
                "reviewed absence comparison. Partial, failed, truncated, demo, and legacy captures cannot."
            )
        )
        layout.addStretch(1)
        return widget

    def competitor_tab(self, competitors: list[CompetitorRecord]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(
            SectionHeader("Visual competitor comparison", "Use the matrix as a review aid. Confirm competitor relevance manually before claiming a gap.")
        )
        self.competitor_review_fields: dict[int, tuple[QCheckBox, QLineEdit]] = {}
        if not competitors:
            layout.addWidget(
                InfoBanner("No competitors selected", "Collect comparable businesses in a new search, then manually review their relevance here.", "warning")
            )
            return widget
        with self.session_factory() as session:
            target = session.get(Lead, self.lead_id)
            if target:
                _ = target.audit
            competitor_leads = {
                record.id: session.execute(select(Lead).where(Lead.place_id == record.competitor_place_id)).scalar_one_or_none() for record in competitors
            }
            for comp_lead in competitor_leads.values():
                if comp_lead:
                    _ = comp_lead.audit
        layout.addWidget(
            InfoBanner(
                f"Competitor Gap: {competitor_gap_label(target, competitors)}",
                "The target is compared with selected records using observed website checks. Missing audit data remains unknown, not a negative claim.",
                "warning" if competitor_gap_label(target, competitors) != "Low" else "info",
            )
        )
        matrix = DataTable(["Signal", "Target", *[record.competitor_name[:20] for record in competitors]])
        checks = [
            ("Quote CTA", "clear_primary_cta"),
            ("Tap-to-call", "tap_to_call"),
            ("Services", "service_pages"),
            ("Reviews / trust", "trust_signals"),
            ("FAQ", "faq_content"),
            ("Local schema", "local_schema"),
        ]
        matrix.setRowCount(len(checks))
        for row, (label, key) in enumerate(checks):
            matrix.setItem(row, 0, table_item(label))
            matrix.setItem(row, 1, table_item(check_mark(target.audit, key)))
            for column, record in enumerate(competitors, start=2):
                comp_lead = competitor_leads[record.id]
                matrix.setItem(row, column, table_item(check_mark(comp_lead.audit if comp_lead else None, key)))
        matrix.fit_columns(stretch_column=0)
        layout.addWidget(matrix)
        layout.addWidget(SectionHeader("Why these competitors", "Selection evidence and operator confirmation are kept separately."))
        for competitor in competitors:
            comp_lead = competitor_leads[competitor.id]
            card = QFrame()
            card.setProperty("surface", "card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            heading = QHBoxLayout()
            heading.addWidget(QLabel(f"{competitor.competitor_name} · match {competitor.match_score}"))
            heading.addStretch(1)
            heading.addWidget(StatusBadge("Audited" if comp_lead and comp_lead.audit else "Manual review"))
            card_layout.addLayout(heading)
            details = QLabel(
                f"Why this competitor: {competitor.reason or 'Manual selection requires review.'}\n"
                f"Website: {competitor.website_url or 'Not captured'} · "
                f"Rating / reviews: {f'{comp_lead.rating} / {comp_lead.review_count}' if comp_lead else 'Not collected'}"
            )
            details.setWordWrap(True)
            details.setProperty("tone", "muted")
            card_layout.addWidget(details)
            checklist = loads(competitor.checklist_json, {})
            approved = QCheckBox("Operator confirms this is a relevant competitor")
            approved.setChecked(bool(checklist.get("operator_approved", False)))
            evidence = QLineEdit(competitor.evidence_notes)
            evidence.setPlaceholderText("Manual comparison notes")
            self.competitor_review_fields[competitor.id] = (approved, evidence)
            card_layout.addWidget(approved)
            card_layout.addWidget(evidence)
            buttons = ActionToolbar()
            if comp_lead and comp_lead.audit:
                if comp_lead.audit.desktop_screenshot and Path(comp_lead.audit.desktop_screenshot).exists():
                    buttons.add_action("Desktop Screenshot", lambda path=comp_lead.audit.desktop_screenshot: self.open_local_file(path), role="tertiary")
                if comp_lead.audit.mobile_screenshot and Path(comp_lead.audit.mobile_screenshot).exists():
                    buttons.add_action("Mobile Screenshot", lambda path=comp_lead.audit.mobile_screenshot: self.open_local_file(path), role="tertiary")
            buttons.add_action("Replace Competitor", lambda _checked=False, item_id=competitor.id: self.replace_competitor(item_id), role="secondary")
            card_layout.addWidget(buttons)
            layout.addWidget(card)
        save = action_button("Save Competitor Review", self.save_competitor_review, role="primary")
        layout.addWidget(save)
        layout.addStretch(1)
        return widget

    def replace_competitor(self, competitor_id: int) -> None:
        name, accepted = QInputDialog.getText(self, "Replace competitor", "Replacement business name (manual research required):")
        if not accepted or not name.strip():
            return
        with self.session_factory() as session:
            competitor = session.get(CompetitorRecord, competitor_id)
            if competitor:
                competitor.competitor_name = name.strip()
                competitor.competitor_place_id = ""
                competitor.website_url = ""
                competitor.reason = "Manually replaced; add comparison notes and verify relevance."
                competitor.checklist_json = "{}"
                competitor.google_snapshot_json = "{}"
                lead = session.get(Lead, self.lead_id)
                if lead:
                    GooglePresenceService().evaluate_and_store(session, lead)
                    QualificationService().evaluate_and_store(session, lead)
                    self._refresh_adaptive_assets(session, lead)
                log_activity(session, "competitor_replaced", f"Manually replaced competitor with {name.strip()}", self.lead_id)
                session.commit()
        self.load()

    def offer_tab(self, session: Session, lead: Lead, competitors: list[CompetitorRecord]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.target_zip = QLineEdit(lead.target_zip_code)
        self.target_radius = QSpinBox()
        self.target_radius.setRange(1, 30)
        self.target_radius.setValue(lead.target_radius_miles or 10)
        self.yelp_url = QLineEdit(lead.yelp_url)
        self.past_sales = QTextEdit(lead.past_sales_notes)
        form.addRow("Target ZIP", self.target_zip)
        form.addRow("Target miles away", self.target_radius)
        form.addRow("Yelp/other page", self.yelp_url)
        form.addRow("Previous sales/proof notes", self.past_sales)
        layout.addLayout(form)
        adaptive, pricing = build_adaptive_sales_plan(session, lead, competitors=competitors)
        layout.addWidget(
            InfoBanner(
                f"Recommendation evidence: {adaptive.intelligence_level}",
                f"{adaptive.primary_theme} · {adaptive.message_strategy}",
                "success",
            )
        )
        self.offer_preview = QTextEdit()
        self.offer_preview.setPlainText(format_smart_offer(adaptive.smart_offer))
        self.offer_preview.setReadOnly(True)
        layout.addWidget(self.offer_preview)
        fusion = adaptive.offer_fusion or {}
        ranked = fusion.get("ranked_offers") or []
        if fusion.get("selection_source") in {"search_market_advisory_locked", "intervention_advisory_locked"} and ranked:
            alternative_id = str(ranked[0].get("offer_id") or "")
            if alternative_id and alternative_id != adaptive.smart_offer.offer_id:
                alternative_name = offer_definition(alternative_id).display_name
                layout.addWidget(QLabel("A stronger current alternative is advisory only; the existing offer remains selected."))
                accept = QPushButton(f"Review and select {alternative_name}")
                accept.setObjectName("accept_search_offer_alternative")
                accept.clicked.connect(
                    lambda _checked=False, selected=alternative_id: self.accept_search_offer_alternative(selected)
                )
                layout.addWidget(accept)
        save = QPushButton("Save Fields And Regenerate Offer")
        save.clicked.connect(self.save_offer_fields)
        layout.addWidget(save)
        return widget

    def accept_search_offer_alternative(self, offer_id: str) -> None:
        name = offer_definition(offer_id).display_name
        if QMessageBox.question(
            self, "Change canonical Smart Offer?",
            f"Select {name} as the canonical offer for this lead? Pricing and drafts will be recalculated. "
            "Previously approved copy will not be silently rewritten.",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            with self.session_factory() as session:
                lead = session.get(Lead, self.lead_id)
                if lead is None:
                    raise ValueError("Lead no longer exists.")
                accept_advisory_offer(session, lead, offer_id, operator_confirmed=True)
                self._refresh_adaptive_assets(session, lead)
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Offer selection changed", str(exc))
            return
        self.load()

    def outreach_tab(self, drafts: list[OutreachDraft]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for draft in drafts:
            box = QTextEdit((f"Subject: {draft.subject}\n\n" if draft.subject else "") + draft.body)
            box.setReadOnly(True)
            copy = QPushButton(f"Copy {'approved ' if draft.approved else ''}{draft.kind}")
            draft_text = box.toPlainText()
            copy.clicked.connect(lambda _checked=False, draft_id=draft.id, text=draft_text, approved=draft.approved: self.copy_draft(draft_id, text, approved))
            edit = QPushButton(f"Edit {draft.kind}")
            edit.clicked.connect(lambda _checked=False, draft_id=draft.id: self.edit_draft(draft_id))
            approval_label = "Unapprove" if draft.approved else "Approve after review"
            approve = QPushButton(f"{approval_label}: {draft.kind}")
            approve.clicked.connect(lambda _checked=False, draft_id=draft.id, approved=not draft.approved: self.set_draft_approval(draft_id, approved))
            layout.addWidget(QLabel(f"<b>{draft.kind}</b>"))
            layout.addWidget(box)
            layout.addWidget(copy)
            layout.addWidget(edit)
            layout.addWidget(approve)
        return widget

    def actions_tab(self, lead: Lead) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        status = QComboBox()
        status.addItems([item.value for item in LeadStatus])
        status.setCurrentText(lead.status)
        save_status = QPushButton("Save Status")
        save_status.clicked.connect(lambda: self.save_status(status.currentText()))
        layout.addWidget(status)
        layout.addWidget(save_status)

        buttons = QGridLayout()
        for index, (label, callback) in enumerate(
            [
                ("Open website", self.open_website),
                ("Copy Google Maps URL", self.open_google),
                ("Copy phone", self.copy_phone),
                ("Generate owner report", self.generate_report),
                ("Generate internal report", self.generate_internal_report),
                ("Generate mockup", self.generate_mockup),
                ("Open competitor comparison", self.open_comparison),
                ("Generate AI website-builder prompts", self.generate_builder_prompts),
                ("Generate customer proposal", self.generate_proposal),
                ("Generate internal pricing proposal", self.generate_internal_proposal),
                ("Record as Presented Offer", self.record_presented_offer),
                ("Export paid-style website", self.export_static_site),
                ("Export lead package ZIP", self.export_package),
                ("Show pricing guidance", self.show_pricing_guidance),
                ("Mark qualified", lambda _checked=False: self.save_status(LeadStatus.QUALIFIED.value)),
                ("Mark contacted today", self.mark_contacted_today),
                ("Mark replied", lambda _checked=False: self.save_status(LeadStatus.REPLIED.value)),
                ("Meeting scheduled", lambda _checked=False: self.save_status(LeadStatus.MEETING_SCHEDULED.value)),
                ("Mark won", lambda _checked=False: self.save_status(LeadStatus.WON.value)),
                ("Mark lost", lambda _checked=False: self.save_status(LeadStatus.LOST.value)),
                ("Mark not qualified", lambda _checked=False: self.save_status(LeadStatus.NOT_QUALIFIED.value)),
                ("Add to suppression list", self.suppress),
            ]
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button, index // 3, index % 3)
        layout.addLayout(buttons)
        return widget

    def save_offer_fields(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            update_lead_fields(
                session,
                lead.id,
                target_zip_code=self.target_zip.text().strip(),
                target_radius_miles=self.target_radius.value(),
                yelp_url=self.yelp_url.text().strip(),
                past_sales_notes=self.past_sales.toPlainText().strip(),
            )
            session.flush()
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            self._refresh_adaptive_assets(session, lead)
            session.commit()
        self.load()

    def save_crm_fields(self) -> None:
        date_fields = {
            "Next follow-up": self.next_follow_up.text().strip(),
            "Last contacted": self.last_contacted.text().strip(),
        }
        invalid = [label for label, value in date_fields.items() if value and not valid_iso_date(value)]
        if invalid:
            QMessageBox.warning(self, "Invalid date", f"Use YYYY-MM-DD for: {', '.join(invalid)}")
            return
        with self.session_factory() as session:
            update_lead_fields(
                session,
                self.lead_id,
                address=self.address.text().strip(),
                phone=self.phone.text().strip(),
                website=self.website.text().strip(),
                google_maps_url=self.google_maps_url.text().strip(),
                yelp_url=self.crm_yelp_url.text().strip(),
                owner=self.owner.text().strip(),
                tags=self.tags.text().strip(),
                next_follow_up_date=self.next_follow_up.text().strip(),
                last_contacted_date=self.last_contacted.text().strip(),
                contact_method=self.contact_method.text().strip(),
                contact_outcome=self.contact_outcome.text().strip(),
                operator_notes=self.notes.toPlainText().strip(),
            )
            session.commit()
        self.load()

    def save_verification(self) -> None:
        values = {key: checkbox.isChecked() for key, checkbox in self.verification_boxes.items()}
        with self.session_factory() as session:
            update_lead_fields(session, self.lead_id, verification_json=json.dumps(values))
            session.commit()
        self.load()

    def save_competitor_review(self) -> None:
        with self.session_factory() as session:
            for competitor_id, (approved, evidence) in self.competitor_review_fields.items():
                competitor = session.get(CompetitorRecord, competitor_id)
                if competitor:
                    checklist = loads(competitor.checklist_json, {})
                    checklist["operator_approved"] = approved.isChecked()
                    competitor.checklist_json = json.dumps(checklist)
                    competitor.evidence_notes = evidence.text().strip()
            lead = session.get(Lead, self.lead_id)
            if lead:
                GooglePresenceService().evaluate_and_store(session, lead)
                QualificationService().evaluate_and_store(session, lead)
                self._refresh_adaptive_assets(session, lead)
            log_activity(session, "competitors_reviewed", "Saved manual competitor review", self.lead_id)
            session.commit()
        self.load()

    def save_status(self, status: str) -> None:
        try:
            with self.session_factory() as session:
                update_lead_status(session, self.lead_id, status)
                session.commit()
            self.load()
        except ValueError as exc:
            QMessageBox.warning(self, "Status blocked", str(exc))

    def mark_contacted_today(self) -> None:
        with self.session_factory() as session:
            update_lead_fields(session, self.lead_id, last_contacted_date=date.today().isoformat())
            update_lead_status(session, self.lead_id, LeadStatus.CONTACTED.value)
            session.commit()
        self.load()

    def set_draft_approval(self, draft_id: int, approved: bool) -> None:
        try:
            with self.session_factory() as session:
                set_outreach_approval(session, draft_id, approved, sender=self.config.sender)
                session.commit()
            self.load()
        except ValueError as exc:
            QMessageBox.warning(self, "Approval blocked", str(exc))

    def select_tab(self, title: str) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == title:
                self.tabs.setCurrentIndex(index)
                return

    def open_guided_call(self) -> None:
        dialog = GuidedCallDialog(self.session_factory, self.lead_id, self)
        dialog.exec()

    def set_primary_contact(self, contact_point_id: int | None) -> None:
        if contact_point_id is None:
            return
        with self.session_factory() as session:
            set_selected_contact_point(session, self.lead_id, int(contact_point_id))
            session.commit()
        self.load()

    def discover_public_contacts(self) -> None:
        worker = FunctionWorker(self._discover_public_contacts_job)
        worker.signals.finished.connect(self._public_contacts_finished)
        worker.signals.failed.connect(self._public_contacts_failed)
        self.thread_pool.start(worker)

    def _discover_public_contacts_job(self) -> tuple[int, tuple[str, ...]]:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                raise ValueError("Lead not found")
            result = WebsiteContactDiscovery(self.config.request_timeout_seconds).discover(lead)
            replace_contact_points(session, lead.id, [contact.to_record() for contact in result.contacts])
            QualificationService().evaluate_and_store(session, lead)
            self._refresh_adaptive_assets(session, lead)
            session.commit()
            return len(result.contacts), result.warnings

    def _public_contacts_finished(self, result: object) -> None:
        count, warnings = result if isinstance(result, tuple) and len(result) == 2 else (0, ())
        message = f"Saved {count} public contact point(s)."
        if warnings:
            message += "\n\n" + "\n".join(str(item) for item in warnings)
        QMessageBox.information(self, "Contact discovery complete", message)
        self.load()

    def _public_contacts_failed(self, details: str) -> None:
        QMessageBox.warning(self, "Contact discovery failed", details.splitlines()[-1] if details else "Unknown error")

    def _refresh_adaptive_assets(self, session: Session, lead: Lead) -> None:
        refresh_adaptive_sales_assets(session, lead, self.config.sender)

    def add_interaction(self) -> None:
        dialog = ContactInteractionDialog(self.session_factory, self.lead_id, parent=self, config=self.config)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.load()

    def edit_interaction(self, interaction_id: int) -> None:
        dialog = ContactInteractionDialog(self.session_factory, self.lead_id, interaction_id, self, config=self.config)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.load()

    def delete_interaction(self, interaction_id: int) -> None:
        if not confirm_destructive(self, "Delete interaction?", "This removes the selected contact-history entry."):
            return
        with self.session_factory() as session:
            delete_contact_interaction(session, interaction_id)
            refresh_after_interaction_change(session, self.lead_id, self.config.sender)
            session.commit()
        self.load()

    def open_website(self) -> None:
        self.open_url("website")

    def open_google(self) -> None:
        self.open_url("google_maps_url")

    def open_url(self, field: str) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            value = getattr(lead, field, "") if lead else ""
        if value:
            QGuiApplication.clipboard().setText(value)
            QMessageBox.information(
                self, "URL copied for manual review",
                "The URL was copied, not opened. External browser redirects and subresources are outside the app's "
                "validated network transport. Use Website Audit for guarded fetching, or independently review the URL "
                "before choosing to visit it in your own browser.",
            )

    def copy_phone(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            QGuiApplication.clipboard().setText(lead.phone if lead else "")

    def generate_report(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead:
                ReportService(self.config).open_report(session, lead, "owner_full")

    def generate_internal_report(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead:
                ReportService(self.config).open_report(session, lead, "internal")

    def generate_mockup(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead:
                MockupService(self.config).open_mockup(lead)

    def open_comparison(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead:
                ComparisonService(self.config).open_comparison(session, lead, ai_mode="prompt")

    def generate_builder_prompts(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            paths = WebsiteBuilderPromptService(self.config).write_bundle(session, lead)
        details = "\n".join(f"{name.title()}: {path}" for name, path in paths.items())
        QMessageBox.information(self, "AI website-builder prompts created", details)

    def generate_proposal(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
            recommendation = SellerPricingService().recommend_for_lead(session, lead, competitors)
            if not recommendation.price_available or recommendation.recommended is None:
                QMessageBox.information(self, "Commercial offer unresolved", recommendation.price_answer)
                return
            selected_price, accepted = QInputDialog.getInt(
                self,
                "Select customer-facing price",
                "Price to place in the customer proposal:",
                recommendation.recommended,
                50,
                10_000_000,
                50,
            )
            if accepted:
                choices = proposal_ai_choices(session, lead.id)
                references: list[str] = []
                if choices:
                    selection = ProposalEvidenceDialog(choices,self)
                    if not selection.exec():
                        return
                    references = selection.selected_references()
                try:
                    ProposalService(self.config).open_proposal(session, lead, selected_price=selected_price, ai_finding_refs=references)
                except ValueError as exc:
                    QMessageBox.warning(self,'Proposal not generated',str(exc))

    def generate_internal_proposal(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead:
                ProposalService(self.config).open_proposal(session, lead, internal=True)

    def record_presented_offer(self) -> None:
        dialog = OfferHistoryDialog(
            self.session_factory,
            lead_id=self.lead_id,
            default_status="Presented",
            parent=self,
        )
        if dialog.exec() == dialog.DialogCode.Accepted:
            QMessageBox.information(self, "Offer recorded", "The presented amount and pricing snapshot were saved.")

    def export_static_site(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            path = StaticSiteService(self.config).export_site(lead, session=session)
        QMessageBox.information(self, "Website export created", f"Exported:\n{path}")

    def export_package(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            path = LeadPackageService(self.config).export_package(session, lead, ai_mode="prompt")
        QMessageBox.information(self, "Lead package exported", f"Exported:\n{path}")

    def show_pricing_guidance(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if not lead:
                return
            competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
            recommendation = SellerPricingService().recommend_for_lead(session, lead, competitors)
        text = (
            f"SERVICE-COST BAND (not ROI)\n{recommendation.project.range_text}\n\n"
            f"YOUR CURRENT PRICING\n"
            f"Easy-close: {recommendation.easy_close_text}\n"
            f"Recommended: {recommendation.recommended_text}\n"
            f"Stretch: {recommendation.stretch_text}\n"
            f"Evidence confidence: {recommendation.confidence}\n\n"
            "WHY THIS NUMBER?\n- " + "\n- ".join(recommendation.reasoning) + "\n\nIF PRICE COMES UP\n" + recommendation.price_answer
        )
        QMessageBox.information(self, "Seller Pricing Intelligence", text)

    def suppress(self) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead:
                SuppressionService().suppress_lead(session, lead, "manual suppression from lead detail")
                session.commit()
        self.load()

    def edit_draft(self, draft_id: int) -> None:
        dialog = OutreachEditorDialog(self.session_factory, draft_id, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.load()

    def copy_draft(self, draft_id: int, text: str, approved: bool) -> None:
        with self.session_factory() as session:
            current = session.get(OutreachDraft, draft_id)
            if current is None:
                return
            lead = session.get(Lead, current.lead_id)
            readiness_errors = lead_contact_readiness_errors(session, lead) if lead is not None else ("Lead no longer exists.",)
            if readiness_errors:
                QMessageBox.warning(self, "Copy blocked", " ".join(readiness_errors))
                return
            approved = current.approved and not outreach_approval_errors(session, current, self.config.sender)
            text = (f"Subject: {current.subject}\n\n" if current.subject else "") + current.body
        if not approved:
            answer = QMessageBox.warning(
                self,
                "Draft is not approved",
                "This draft has not been approved after human review. Copy it anyway for editing only?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QGuiApplication.clipboard().setText(text)
        with self.session_factory() as session:
            log_activity(
                session,
                "outreach_copied",
                f"Copied {'approved' if approved else 'unapproved'} outreach draft #{draft_id}",
                self.lead_id,
            )
            session.commit()


def format_offer(offer) -> str:
    return (
        f"{offer.headline}\n\n"
        f"Opening angle:\n{offer.opening_angle}\n\n"
        f"Offer: {offer.offer_name} | {offer.price_range}\n\n"
        f"Scope:\n- " + "\n- ".join(offer.scope) + "\n\n"
        "Proof plan:\n- " + "\n- ".join(offer.proof_plan) + "\n\n"
        f"First ask: {offer.first_ask}\n\n"
        f"Risk reversal: {offer.risk_reversal}\n\n"
        f"Talk track:\n{offer.talk_track}"
    )


def valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def format_money(value: int | None) -> str:
    return f"${value:,}" if value is not None else "Limited seller history"


def check_mark(audit, key: str) -> str:
    if not audit:
        return "—"
    return "✓" if loads(audit.checks_json, {}).get(key, False) else "✕"


def competitor_gap_label(lead: Lead | None, competitors: list[CompetitorRecord]) -> str:
    if not lead or not competitors:
        return "Unknown"
    target_checks = loads(lead.audit.checks_json, {}) if lead.audit else {}
    target_strength = sum(bool(target_checks.get(key)) for key in ("clear_primary_cta", "tap_to_call", "service_pages", "trust_signals"))
    stronger = sum(1 for competitor in competitors if competitor.match_score >= 70)
    if target_strength <= 1 and stronger >= 2:
        return "High"
    if target_strength <= 2 or stronger:
        return "Moderate"
    return "Low"


def audit_explanation(weakness: str) -> str:
    lower = weakness.lower()
    if "cta" in lower or "quote" in lower or "contact" in lower:
        return "Visitors may not have an obvious path to request an estimate or start a conversation."
    if "trust" in lower or "review" in lower:
        return "Visitors may see less visible social proof before deciding whether to contact the business."
    if "mobile" in lower or "viewport" in lower:
        return "Mobile visitors may face extra friction when trying to understand services or make contact."
    if "service" in lower:
        return "Visitors may have less clarity about what the business does and whether it fits their need."
    return "This observed public-site gap may add friction to a visitor's decision or contact path."
