from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import median

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.pricing_repository import (
    SELLER_IDENTITY_TYPES,
    SELLER_LOCATION_MODES,
    delete_offer_history,
    delete_seller_proof,
    get_or_create_seller_profile,
    list_offer_history,
    list_seller_proof,
    save_seller_profile,
)
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.services.adaptive_sales_asset_service import refresh_after_seller_proof_change
from local_presence_miner.services.export_service import ExportService
from local_presence_miner.services.seller_pricing_service import SellerPricingService
from local_presence_miner.services.seller_proof_service import summarize_seller_proof
from local_presence_miner.ui.components import (
    DataTable,
    EmptyState,
    FieldMessage,
    InfoBanner,
    MetricCard,
    PricingRecommendationPanel,
    SectionHeader,
    StatusBadge,
    Toast,
    action_button,
    confirm_destructive,
    table_item,
)
from local_presence_miner.ui.dialogs.offer_history_dialog import OfferHistoryDialog
from local_presence_miner.ui.dialogs.seller_proof_dialog import SellerProofDialog

PRICE_BANDS = [
    ("Under $750", 0, 749),
    ("$750-$999", 750, 999),
    ("$1,000-$1,249", 1000, 1249),
    ("$1,250-$1,499", 1250, 1499),
    ("$1,500-$1,999", 1500, 1999),
    ("$2,000+", 2000, 10_000_000),
]


class PricingWidget(QWidget):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        self._proofs = []
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(12)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(10)
        self.presented_metric = MetricCard("PRESENTED", "0", "Non-draft offers", accent="primary")
        self.wins_metric = MetricCard("WINS", "0", "Observed outcomes", accent="success")
        self.ask_metric = MetricCard("MEDIAN ASK", "—", "Presented offers")
        self.close_metric = MetricCard("MEDIAN CLOSE", "—", "Won offers")
        self.won_value_metric = MetricCard("TOTAL WON", "$0", "Recorded closed value", accent="success")
        for column, card in enumerate([self.presented_metric, self.wins_metric, self.ask_metric, self.close_metric, self.won_value_metric]):
            metrics.addWidget(card, 0, column)
            metrics.setColumnStretch(column, 1)
        root.addLayout(metrics)
        root.addWidget(
            InfoBanner(
                "Private seller-side evidence",
                "These records stay in your local database. Project Value describes the prospect-side opportunity; "
                "your recommended ask is calibrated separately from verified proof and recorded offer history.",
            )
        )

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self.overview_tab(), "Seller Profile")
        self.tabs.addTab(self.offer_history_tab(), "Offer History")
        self.tabs.addTab(self.proof_tab(), "Credibility & Proof")
        self.tabs.addTab(self.comparables_tab(), "Comparable Deals")
        self.tabs.addTab(self.performance_tab(), "Performance")
        self.refresh()

    def overview_tab(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(12, 14, 12, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        profile_card = QFrame()
        profile_card.setProperty("surface", "card")
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(16, 14, 16, 14)
        profile_layout.addWidget(SectionHeader("Seller identity", "Used to contextualize your private pricing evidence."))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        self.display_name = QLineEdit()
        self.business_name = QLineEdit()
        self.identity_type = QComboBox()
        self.identity_type.addItems(SELLER_IDENTITY_TYPES)
        self.location_mode = QComboBox()
        self.location_mode.addItems(SELLER_LOCATION_MODES)
        self.location_label = QLineEdit()
        self.location_label.setPlaceholderText("City / region; leave blank if not configured")
        self.service_area = QLineEdit()
        self.service_area.setPlaceholderText("Actual service area or remote coverage")
        self.experience_start = QLineEdit()
        self.experience_start.setPlaceholderText("YYYY-MM-DD or leave blank")
        self.profile_notes = QTextEdit()
        self.profile_notes.setPlaceholderText("Private context about your background, positioning, or pricing comfort.")
        self.profile_notes.setMaximumHeight(110)
        self.profile_error = FieldMessage()
        form.addRow("Display name", self.display_name)
        form.addRow("Business name", self.business_name)
        form.addRow("Identity type", self.identity_type)
        form.addRow("Location model", self.location_mode)
        form.addRow("Location", self.location_label)
        form.addRow("Service area", self.service_area)
        form.addRow("Experience started", self.experience_start)
        form.addRow("Private notes", self.profile_notes)
        profile_layout.addLayout(form)
        profile_layout.addWidget(self.profile_error)
        actions = QHBoxLayout()
        actions.addStretch(1)
        save = action_button("Save Seller Profile", self.save_profile, role="primary")
        actions.addWidget(save)
        profile_layout.addLayout(actions)

        evidence_card = QFrame()
        evidence_card.setProperty("surface", "card")
        evidence_layout = QVBoxLayout(evidence_card)
        evidence_layout.setContentsMargins(16, 14, 16, 14)
        evidence_layout.addWidget(SectionHeader("Proof strength", "What currently supports your ask—without pretending to predict a close."))
        self.evidence_grid = QGridLayout()
        self.paid_value = self._evidence_value("Paid projects", 0, 0)
        self.testimonial_value = self._evidence_value("Testimonials", 0, 1)
        self.case_study_value = self._evidence_value("Case studies", 1, 0)
        self.verified_value = self._evidence_value("Verified items", 1, 1)
        self.offer_count_value = self._evidence_value("Recorded offers", 2, 0)
        self.confidence_badge = StatusBadge("Low", "warning")
        self.evidence_grid.addWidget(QLabel("Evidence confidence"), 2, 1)
        self.evidence_grid.addWidget(self.confidence_badge, 3, 1, Qt.AlignmentFlag.AlignLeft)
        evidence_layout.addLayout(self.evidence_grid)
        self.evidence_note = QLabel()
        self.evidence_note.setWordWrap(True)
        self.evidence_note.setProperty("tone", "muted")
        evidence_layout.addWidget(self.evidence_note)
        evidence_layout.addStretch(1)

        grid.addWidget(profile_card, 0, 0)
        grid.addWidget(evidence_card, 0, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        return widget

    def _evidence_value(self, label: str, row: int, column: int) -> QLabel:
        block = QVBoxLayout()
        title = QLabel(label.upper())
        title.setProperty("role", "metricLabel")
        value = QLabel("0")
        value.setProperty("role", "metricValue")
        block.addWidget(title)
        block.addWidget(value)
        self.evidence_grid.addLayout(block, row * 2, column)
        return value

    def offer_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 14, 12, 12)
        header = SectionHeader("Real offer history", "Record asks and outcomes so recommendations can learn from your actual experience.")
        header.add_action(action_button("Add Offer", self.add_offer, role="primary"))
        header.add_action(action_button("Edit", self.edit_offer, role="secondary"))
        header.add_action(action_button("Delete", self.delete_offer, role="danger"))
        header.add_action(action_button("Export CSV", self.export_offers, role="tertiary"))
        layout.addWidget(header)
        self.offers_table = DataTable(["Date", "Business", "Niche", "Package", "Asked", "Final", "Closed", "Outcome"])
        self.offers_table.cellDoubleClicked.connect(lambda _row, _column: self.edit_offer())
        layout.addWidget(self.offers_table, 1)
        self.offers_empty = EmptyState(
            "No offers recorded yet",
            "Add a real ask after you prepare or present it. Drafts are kept separate from observed sales outcomes.",
            "Add First Offer",
        )
        self.offers_empty.action_requested.connect(self.add_offer)
        layout.addWidget(self.offers_empty)
        return widget

    def proof_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 14, 12, 12)
        header = SectionHeader(
            "Credibility & proof ledger",
            "Separate completed, in-progress, prototype, and concept evidence. Only supportable claims flow into calls and follow-up.",
        )
        header.add_action(action_button("Add Proof", self.add_proof, role="primary"))
        header.add_action(action_button("Edit", self.edit_proof, role="secondary"))
        header.add_action(action_button("Delete", self.delete_proof, role="danger"))
        header.add_action(action_button("Export CSV", self.export_proof, role="tertiary"))
        layout.addWidget(header)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Show"))
        self.proof_filter = QComboBox()
        self.proof_filter.addItems(["All proof", "Projects", "Testimonials", "Case Studies", "Portfolio", "Verified only"])
        self.proof_filter.currentIndexChanged.connect(self.apply_proof_filter)
        filter_row.addWidget(self.proof_filter)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)
        self.proof_table = DataTable(["Type", "Title", "Status", "Niche", "Client", "Completed", "Verified"])
        self.proof_table.cellDoubleClicked.connect(lambda _row, _column: self.edit_proof())
        layout.addWidget(self.proof_table, 1)
        self.proof_empty = EmptyState(
            "No proof entered yet",
            "Add only work or evidence you can support. Verification is a manual seller responsibility.",
            "Add Proof",
        )
        self.proof_empty.action_requested.connect(self.add_proof)
        layout.addWidget(self.proof_empty)
        return widget

    def comparables_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)
        header = SectionHeader("Comparable-deal analysis", "Separate the business-supported value from the ask your own evidence currently supports.")
        layout.addWidget(header)
        row = QHBoxLayout()
        self.comparable_lead = QComboBox()
        self.comparable_lead.setMinimumWidth(420)
        analyze = action_button("Analyze Selected Lead", self.analyze_lead, role="primary")
        row.addWidget(self.comparable_lead, 1)
        row.addWidget(analyze)
        layout.addLayout(row)
        self.pricing_panel = PricingRecommendationPanel()
        layout.addWidget(self.pricing_panel)
        self.comparable_output = QTextEdit()
        self.comparable_output.setReadOnly(True)
        self.comparable_output.setPlaceholderText("Choose a lead to see project context, comparable history, reasoning, and phased options.")
        layout.addWidget(self.comparable_output, 1)
        return widget

    def performance_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 14, 12, 12)
        header = SectionHeader(
            "Observed pricing performance",
            "Descriptive history only. Small samples are suppressed and correlations are not claims of causation.",
        )
        header.add_action(action_button("Refresh", self.refresh, role="secondary"))
        layout.addWidget(header)
        self.performance_output = QTextEdit()
        self.performance_output.setReadOnly(True)
        layout.addWidget(self.performance_output, 1)
        return widget

    def refresh(self) -> None:
        with self.session_factory() as session:
            profile = get_or_create_seller_profile(session)
            session.commit()
            profile_values = (
                profile.display_name,
                profile.business_name,
                profile.identity_type,
                profile.location_mode,
                profile.location_label,
                profile.service_area,
                profile.experience_start_date or "",
                profile.notes,
            )
            offers = list_offer_history(session, profile.id)
            proofs = list_seller_proof(session, profile.id)
            leads = list(session.execute(select(Lead).order_by(Lead.lead_score.desc(), Lead.name)).scalars())
            summary = summarize_seller_proof(session)
        self.display_name.setText(profile_values[0])
        self.business_name.setText(profile_values[1])
        self.identity_type.setCurrentText(profile_values[2])
        self.location_mode.setCurrentText(profile_values[3])
        self.location_label.setText(profile_values[4])
        self.service_area.setText(profile_values[5])
        self.experience_start.setText(profile_values[6])
        self.profile_notes.setPlainText(profile_values[7])
        self.fill_offers(offers)
        self._proofs = proofs
        self.apply_proof_filter()
        current_id = self.comparable_lead.currentData()
        self.comparable_lead.clear()
        for lead in leads:
            self.comparable_lead.addItem(f"{lead.name} · {lead.category} · Growth {lead.lead_score}", lead.id)
        if current_id is not None:
            index = self.comparable_lead.findData(current_id)
            if index >= 0:
                self.comparable_lead.setCurrentIndex(index)
        self.refresh_metrics(offers)
        self.refresh_evidence(summary, len(offers))
        self.performance_output.setPlainText(pricing_performance_text(offers, proofs, summary.recent_pricing_trend))

    def refresh_metrics(self, offers) -> None:
        presented = [offer for offer in offers if offer.status != "Draft"]
        won = [offer for offer in presented if offer.status == "Won" and offer.closed_amount]
        median_ask = round(median([offer.initial_ask for offer in presented])) if presented else None
        median_close = round(median([offer.closed_amount for offer in won])) if won else None
        self.presented_metric.set_value(len(presented))
        self.wins_metric.set_value(len(won), f"{len(won)} of {len(presented)} presented" if presented else "No observed outcomes")
        self.ask_metric.set_value(money(median_ask))
        self.close_metric.set_value(money(median_close))
        self.won_value_metric.set_value(money(sum(offer.closed_amount for offer in won)) if won else "$0")

    def refresh_evidence(self, summary, total_offers: int) -> None:
        self.paid_value.setText(str(summary.completed_paid_projects))
        self.testimonial_value.setText(str(summary.testimonials))
        self.case_study_value.setText(str(summary.case_studies))
        self.verified_value.setText(str(summary.verified_items))
        self.offer_count_value.setText(str(total_offers))
        self.confidence_badge.set_status(summary.evidence_confidence)
        self.evidence_note.setText(
            f"Median closed project: {money(summary.median_closed_project)} · Recent pricing trend: {summary.recent_pricing_trend}. "
            "Confidence describes evidence coverage, not a predicted acceptance rate."
        )

    def fill_offers(self, offers) -> None:
        self.offers_table.setRowCount(len(offers))
        for row, offer in enumerate(offers):
            values = [
                offer.offer_date,
                offer.business_name,
                offer.niche,
                offer.package_name,
                money(offer.initial_ask),
                money(offer.final_ask),
                money(offer.closed_amount),
            ]
            for column, value in enumerate(values):
                self.offers_table.setItem(row, column, table_item(value, user_data=offer.id if column == 0 else None))
            self.offers_table.setCellWidget(row, 7, StatusBadge(offer.status))
        self.offers_table.fit_columns(stretch_column=1)
        self.offers_table.setVisible(bool(offers))
        self.offers_empty.setVisible(not offers)

    def apply_proof_filter(self) -> None:
        selected = self.proof_filter.currentText() if hasattr(self, "proof_filter") else "All proof"
        proofs = self._proofs
        if selected == "Projects":
            proofs = [proof for proof in proofs if "Project" in proof.proof_type]
        elif selected == "Testimonials":
            proofs = [proof for proof in proofs if proof.proof_type == "Testimonial"]
        elif selected == "Case Studies":
            proofs = [proof for proof in proofs if proof.proof_type == "Case Study"]
        elif selected == "Portfolio":
            proofs = [proof for proof in proofs if proof.proof_type in {"Portfolio Example", "Before / After"}]
        elif selected == "Verified only":
            proofs = [proof for proof in proofs if proof.verified]
        self.fill_proof(proofs)

    def fill_proof(self, proofs) -> None:
        self.proof_table.setRowCount(len(proofs))
        for row, proof in enumerate(proofs):
            values = [
                proof.proof_type,
                proof.title,
                proof.status,
                proof.niche,
                proof.client_name or "—",
                proof.completion_date or "—",
            ]
            for column, value in enumerate(values):
                self.proof_table.setItem(row, column, table_item(value, user_data=proof.id if column == 0 else None))
            self.proof_table.setCellWidget(row, 6, StatusBadge("Verified" if proof.verified else "Unverified"))
        self.proof_table.fit_columns(stretch_column=1)
        self.proof_table.setVisible(bool(proofs))
        self.proof_empty.setVisible(not proofs)

    def save_profile(self) -> None:
        try:
            with self.session_factory() as session:
                save_seller_profile(
                    session,
                    display_name=self.display_name.text(),
                    business_name=self.business_name.text(),
                    identity_type=self.identity_type.currentText(),
                    location_mode=self.location_mode.currentText(),
                    location_label=self.location_label.text(),
                    service_area=self.service_area.text(),
                    experience_start_date=self.experience_start.text(),
                    notes=self.profile_notes.toPlainText(),
                )
                session.commit()
        except ValueError as exc:
            self.profile_error.set_message(str(exc), "error")
            return
        self.profile_error.clear_message()
        self.refresh()
        Toast.show_message(self, "Seller profile saved")

    def add_offer(self) -> None:
        if OfferHistoryDialog(self.session_factory, parent=self).exec() == OfferHistoryDialog.DialogCode.Accepted:
            self.refresh()

    def edit_offer(self) -> None:
        record_id = selected_id(self.offers_table)
        if record_id and OfferHistoryDialog(self.session_factory, offer_id=record_id, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def delete_offer(self) -> None:
        record_id = selected_id(self.offers_table)
        if not record_id or not confirm_destructive(
            self, "Delete private offer record?", "This removes the offer from pricing history and future comparable analysis."
        ):
            return
        with self.session_factory() as session:
            delete_offer_history(session, record_id)
            session.commit()
        self.refresh()
        Toast.show_message(self, "Offer record deleted")

    def add_proof(self) -> None:
        if SellerProofDialog(self.session_factory, parent=self).exec() == SellerProofDialog.DialogCode.Accepted:
            self.refresh()

    def edit_proof(self) -> None:
        record_id = selected_id(self.proof_table)
        if record_id and SellerProofDialog(self.session_factory, record_id, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def delete_proof(self) -> None:
        record_id = selected_id(self.proof_table)
        if not record_id or not confirm_destructive(
            self, "Delete private proof record?", "This removes the item from proof-strength and relevant-niche calculations."
        ):
            return
        with self.session_factory() as session:
            delete_seller_proof(session, record_id)
            refresh_after_seller_proof_change(session, AppConfig.load().sender)
            session.commit()
        self.refresh()
        Toast.show_message(self, "Proof record deleted")

    def analyze_lead(self) -> None:
        lead_id = self.comparable_lead.currentData()
        if lead_id is None:
            self.comparable_output.setPlainText("No lead is available yet. Run a search or load the demo data first.")
            return
        with self.session_factory() as session:
            lead = session.get(Lead, lead_id)
            competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead_id)).scalars())
            if not lead:
                return
            recommendation = SellerPricingService().recommend_for_lead(session, lead, competitors)
            self.pricing_panel.set_recommendation(recommendation)
            self.comparable_output.setPlainText(recommendation_detail_text(recommendation))

    def export_offers(self) -> None:
        self.export_private_csv("offers.csv", "offers")

    def export_proof(self) -> None:
        self.export_private_csv("seller_proof.csv", "proof")

    def export_private_csv(self, default_name: str, kind: str) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Export private pricing data", default_name, "CSV files (*.csv)")
        if not path:
            return
        with self.session_factory() as session:
            service = ExportService()
            saved = service.export_offer_history_csv(session, Path(path)) if kind == "offers" else service.export_seller_proof_csv(session, Path(path))
        QMessageBox.information(self, "Private CSV exported", f"Created:\n{saved}")


def recommendation_detail_text(recommendation) -> str:
    lines = [
        "PROJECT CONTEXT",
        f"Market-supported value: {recommendation.project.range_text}",
        "",
        f"COMPARABLE HISTORY · {recommendation.comparable.sample_count} offer(s)",
        f"Median ask: {money(recommendation.comparable.median_ask)}",
        f"Median won: {money(recommendation.comparable.median_won_price)}",
        recommendation.comparable.success_text,
        "",
        "WHY THIS NUMBER",
        *[f"• {reason}" for reason in recommendation.reasoning],
        "",
        "PHASED OPTIONS",
        *[f"• {phase.name}: ${phase.amount:,} — {phase.scope}" for phase in recommendation.phases],
        "",
        "IF PRICE COMES UP",
        recommendation.price_answer,
    ]
    if recommendation.relevant_proof_sentence:
        lines.extend(["", "RELEVANT VERIFIED PROOF", recommendation.relevant_proof_sentence])
    return "\n".join(lines)


def recommendation_text(recommendation) -> str:
    """Backward-compatible plain-text export of a pricing recommendation."""
    return "\n".join(
        [
            "CATALOG SERVICE-COST BAND (NOT ROI)",
            recommendation.project.range_text,
            "",
            "YOUR CURRENT PRICING",
            f"Easy-close: {recommendation.easy_close_text}",
            f"Recommended: {recommendation.recommended_text}",
            f"Stretch: {recommendation.stretch_text}",
            f"Evidence confidence: {recommendation.confidence}",
            "",
            recommendation_detail_text(recommendation),
        ]
    )


def proof_summary_text(summary, total_offers: int) -> str:
    """Backward-compatible summary used by report and test consumers."""
    return "\n".join(
        [
            "SELLER PROOF SUMMARY",
            f"Completed paid projects: {summary.completed_paid_projects}",
            f"Testimonials: {summary.testimonials}",
            f"Case studies: {summary.case_studies}",
            f"Verified proof items: {summary.verified_items}",
            f"Recorded offers: {total_offers}",
            f"Median closed project: {money(summary.median_closed_project)}",
            f"Recent pricing trend: {summary.recent_pricing_trend}",
            f"Evidence confidence: {summary.evidence_confidence}",
            "",
            "Confidence is a qualitative evidence label, not a predicted close probability.",
        ]
    )


def pricing_performance_text(offers, proofs, trend: str) -> str:
    presented = [offer for offer in offers if offer.status != "Draft"]
    won = [offer for offer in presented if offer.status == "Won" and offer.closed_amount]
    lost = [offer for offer in presented if offer.status in {"Lost", "Rejected"}]
    no_response = [offer for offer in presented if offer.status == "No Response" or offer.lost_reason == "No response"]
    lines = [
        "OUTCOMES",
        f"Presented / non-draft: {len(presented)}",
        f"Won: {len(won)} of {len(presented)} presented offers",
        f"Lost / rejected: {len(lost)} of {len(presented)}",
        f"No response: {len(no_response)} of {len(presented)}",
        "",
        "VALUE",
        f"Median ask: {money(round(median([offer.initial_ask for offer in presented]))) if presented else 'Not enough data'}",
        f"Median closed price: {money(round(median([offer.closed_amount for offer in won]))) if won else 'Not enough data'}",
        f"Average won value: {money(round(sum(offer.closed_amount for offer in won) / len(won))) if won else 'Not enough data'}",
        f"Total won value: {money(sum(offer.closed_amount for offer in won)) if won else '$0'}",
        f"Recent pricing trend: {trend}",
        f"Proof inventory: {len(proofs)} item(s)",
        "",
        "PRICE BANDS · observed correlation only; not causal",
    ]
    for label, low, high in PRICE_BANDS:
        band = [offer for offer in presented if low <= offer.initial_ask <= high]
        band_wins = [offer for offer in band if offer.status == "Won" and offer.closed_amount]
        band_losses = [offer for offer in band if offer.status in {"Lost", "Rejected"}]
        rate = f"{len(band_wins) / len(band) * 100:.1f}%" if len(band) >= 5 else "suppressed (n<5)"
        closed = round(median([offer.closed_amount for offer in band_wins])) if band_wins else None
        lines.append(f"{label}: {len(band)} offers · {len(band_wins)} wins · {len(band_losses)} losses · win rate {rate} · median closed {money(closed)}")
    niche_wins: dict[str, list[int]] = defaultdict(list)
    for offer in won:
        niche_wins[offer.niche or "Uncategorized"].append(offer.closed_amount)
    if niche_wins:
        lines.extend(["", "WON VALUE BY NICHE"])
        for niche, amounts in sorted(niche_wins.items(), key=lambda item: sum(item[1]), reverse=True)[:5]:
            lines.append(f"{niche}: {len(amounts)} win(s) · {money(sum(amounts))} total")
    return "\n".join(lines)


def selected_id(table: DataTable) -> int | None:
    row = table.currentRow()
    item = table.item(row, 0) if row >= 0 else None
    value = item.data(Qt.ItemDataRole.UserRole) if item else None
    return int(value) if value is not None else None


def money(value: int | None) -> str:
    return f"${value:,}" if value is not None else "Not enough data"
