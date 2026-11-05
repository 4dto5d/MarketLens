from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.pricing_repository import LOST_REASONS, OFFER_STATUSES, save_offer_history
from local_presence_miner.database.schema import CompetitorRecord, Lead, OfferHistory
from local_presence_miner.services.seller_pricing_service import SellerPricingRecommendation, SellerPricingService


class OfferHistoryDialog(QDialog):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        offer_id: int | None = None,
        lead_id: int | None = None,
        default_status: str = "Draft",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sales Offer History")
        self.resize(680, 650)
        self.session_factory = session_factory
        self.offer_id = offer_id
        self.lead_id = lead_id
        self.recommendation: SellerPricingRecommendation | None = None
        with session_factory() as session:
            offer = session.get(OfferHistory, offer_id) if offer_id else None
            if offer is not None:
                if lead_id is not None and offer.lead_id is not None and lead_id != offer.lead_id:
                    raise ValueError("Offer record belongs to a different business.")
                self.lead_id = offer.lead_id if offer.lead_id is not None else lead_id
                lead_id = self.lead_id
            lead = session.get(Lead, lead_id) if lead_id else None
            if lead and not offer:
                competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
                self.recommendation = SellerPricingService().recommend_for_lead(session, lead, competitors)
            values = offer_values(offer, lead, self.recommendation, default_status)

        layout = QVBoxLayout(self)
        if self.recommendation:
            layout.addWidget(
                QLabel(
                    f"Project Value: <b>{self.recommendation.project.range_text}</b> | "
                    f"Recommended: <b>{self.recommendation.recommended_text}</b>. "
                    "The actual presented amount below is an operator decision."
                )
            )
        form = QFormLayout()
        self.offer_date = QLineEdit(values["offer_date"])
        self.business_name = QLineEdit(values["business_name"])
        self.niche = QLineEdit(values["niche"])
        self.city = QLineEdit(values["city"])
        self.package_name = QLineEdit(values["package_name"])
        self.scope_summary = QTextEdit(values["scope_summary"])
        self.initial_ask = money_box(values["initial_ask"])
        self.final_ask = money_box(values["final_ask"], optional=True)
        self.closed_amount = money_box(values["closed_amount"], optional=True)
        self.status = QComboBox()
        self.status.addItems(OFFER_STATUSES)
        self.status.setCurrentText(values["status"])
        self.lost_reason = QComboBox()
        self.lost_reason.addItem("")
        self.lost_reason.addItems(LOST_REASONS)
        self.lost_reason.setCurrentText(values["lost_reason"])
        self.notes = QTextEdit(values["notes"])
        for label, widget in [
            ("Offer date", self.offer_date),
            ("Business", self.business_name),
            ("Niche", self.niche),
            ("City", self.city),
            ("Package", self.package_name),
            ("Scope", self.scope_summary),
            ("Actual initial ask", self.initial_ask),
            ("Final negotiated ask", self.final_ask),
            ("Closed amount", self.closed_amount),
            ("Status", self.status),
            ("Lost reason", self.lost_reason),
            ("Private notes", self.notes),
        ]:
            form.addRow(label, widget)
        layout.addLayout(form)
        self.historical_record = QCheckBox("Record a past agreement for history only; this does not authorize new work")
        self.historical_record.setChecked(False)
        layout.addWidget(self.historical_record)
        actions = QHBoxLayout()
        save = QPushButton("Save Offer Record")
        cancel = QPushButton("Cancel")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        actions.addWidget(save)
        actions.addWidget(cancel)
        layout.addLayout(actions)

    def save(self) -> None:
        try:
            with self.session_factory() as session:
                lead = session.get(Lead, self.lead_id) if self.lead_id else None
                recommendation = self.recommendation
                save_offer_history(
                    session,
                    offer_id=self.offer_id,
                    lead_id=self.lead_id,
                    offer_date=self.offer_date.text(),
                    business_name=self.business_name.text(),
                    niche=self.niche.text(),
                    city=self.city.text(),
                    package_name=self.package_name.text(),
                    scope_summary=self.scope_summary.toPlainText(),
                    initial_ask=self.initial_ask.value(),
                    recommended_ask_at_offer=(recommendation.recommended if recommendation else self.existing("recommended_ask_at_offer")),
                    final_ask=self.final_ask.value() or None,
                    closed_amount=self.closed_amount.value() or None,
                    status=self.status.currentText(),
                    lost_reason=self.lost_reason.currentText(),
                    notes=self.notes.toPlainText(),
                    historical_record=self.historical_record.isChecked(),
                    growth_score_at_offer=(lead.lead_score if lead and recommendation else self.existing("growth_score_at_offer")),
                    project_value_low_at_offer=(recommendation.project.low if recommendation else self.existing("project_value_low_at_offer")),
                    project_value_high_at_offer=(recommendation.project.high if recommendation else self.existing("project_value_high_at_offer")),
                    seller_confidence_at_offer=(recommendation.confidence if recommendation else self.existing("seller_confidence_at_offer") or ""),
                    proof_snapshot=(recommendation.proof.snapshot() if recommendation else None),
                )
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot save offer", str(exc))
            return
        self.accept()

    def existing(self, field: str):
        if not self.offer_id:
            return None
        with self.session_factory() as session:
            offer = session.get(OfferHistory, self.offer_id)
            return getattr(offer, field, None) if offer else None


def offer_values(
    offer: OfferHistory | None,
    lead: Lead | None,
    recommendation: SellerPricingRecommendation | None,
    default_status: str,
) -> dict:
    # Historical Smart Offer JSON is never a current scope authority.  The
    # recommendation is computed from the same fresh CurrentOfferContext that
    # produced its price.
    scope = recommendation.phases[1].scope if recommendation and len(recommendation.phases) > 1 else ""
    return {
        "offer_date": offer.offer_date if offer else date.today().isoformat(),
        "business_name": offer.business_name if offer else (lead.name if lead else ""),
        "niche": offer.niche if offer else (lead.category if lead else ""),
        "city": offer.city or "" if offer else "",
        "package_name": offer.package_name if offer else (recommendation.project.offer_name if recommendation else ""),
        "scope_summary": offer.scope_summary if offer else scope,
        "initial_ask": offer.initial_ask if offer else (recommendation.recommended or 0 if recommendation else 0),
        "final_ask": offer.final_ask or 0 if offer else 0,
        "closed_amount": offer.closed_amount or 0 if offer else 0,
        "status": offer.status if offer else default_status,
        "lost_reason": offer.lost_reason or "" if offer else "",
        "notes": offer.notes if offer else "",
    }


def money_box(value: int, optional: bool = False) -> QSpinBox:
    box = QSpinBox()
    box.setRange(0 if optional else 50, 10_000_000)
    box.setPrefix("$")
    if optional:
        box.setSpecialValueText("Not recorded")
    box.setValue(value)
    return box
