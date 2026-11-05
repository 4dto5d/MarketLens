"""Explicit manual proof and exact-scope delivery review; never sends/publishes."""
from __future__ import annotations

import json

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout
from sqlalchemy import select

from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_state_service import persist_current_plan, recompute_lead_commercial_candidate
from local_presence_miner.services.delivery_packet_service import DELIVERY_FIELDS, DELIVERY_PREREQUISITES, DeliveryPacketService
from local_presence_miner.services.sales_evidence_service import SalesEvidenceService


class CommercialReviewDialog(QDialog):
    def __init__(self, session_factory, lead_id: int, parent=None):
        super().__init__(parent)
        self.session_factory, self.lead_id = session_factory, lead_id
        self.setWindowTitle("Sammi — evidence and delivery review")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        note = QLabel("Review actual source facts and owner instructions. Unknowns stay unknown. "
                      "This records manual review only: no sending, payment, access grant or live website change.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        layout.addWidget(self.source, 1)
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("Named reviewer")
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Traceable review notes: actual source checked / owner agreement")
        layout.addWidget(self.reviewer)
        layout.addWidget(self.notes)
        review = QPushButton("Record selected evidence fact review")
        review.clicked.connect(self.review_evidence)
        layout.addWidget(review)
        self.fields = QPlainTextEdit(json.dumps({key: "UNKNOWN" for key in DELIVERY_FIELDS}, indent=2))
        layout.addWidget(QLabel("Manual delivery facts — JSON; keep unknown fields UNKNOWN until discovered"))
        layout.addWidget(self.fields, 1)
        self.prerequisites = QPlainTextEdit(json.dumps({key: {"state": "unknown", "notes": ""} for key in DELIVERY_PREREQUISITES}, indent=2))
        prerequisite_note = QLabel("Scope-specific prerequisites — unknown / blocked / satisfied / not_applicable. "
                                  "Explain each satisfied or not-applicable decision; reviewing a blocker does not resolve it.")
        prerequisite_note.setWordWrap(True)
        layout.addWidget(prerequisite_note)
        layout.addWidget(self.prerequisites, 1)
        self.amount = QSpinBox()
        self.amount.setRange(0, 10_000_000)
        self.amount.setPrefix("Actual agreed amount $ ")
        layout.addWidget(self.amount)
        self.reviewed = QCheckBox("I reviewed every delivery fact, limitation and responsibility")
        self.owner_approved = QCheckBox("Owner actually approved this exact scope, amount and terms; notes identify that approval")
        layout.addWidget(self.reviewed)
        layout.addWidget(self.owner_approved)
        actions = QHBoxLayout()
        save = QPushButton("Record delivery packet")
        save.clicked.connect(self.record_delivery)
        actions.addWidget(save)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead is None:
                return
            _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
            evidence = SalesEvidenceService().build(session, lead, assessment=context.intervention_assessment,
                                                     offer_id=context.offer_id, scope=context.scope)
            packet = DeliveryPacketService().build(session, lead, context=context, selected_price=self.amount.value() or pricing.recommended)
            self.source.setPlainText(json.dumps({"current_scope": list(context.scope), "owner_fit": context.intervention_assessment,
                                                "selected_evidence": evidence.selected_evidence, "review_state": evidence.review_state,
                                                "delivery": packet}, indent=2))

    def _refresh_plan(self, session, lead):
        recompute_lead_commercial_candidate(session, lead, "Manual evidence/delivery review changed")
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        competitors = list(session.scalars(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)))
        persist_current_plan(session, lead, competitors=competitors, pricing=pricing, context=context)

    def review_evidence(self):
        try:
            with self.session_factory() as session:
                lead = session.get(Lead, self.lead_id)
                if lead is None:
                    raise ValueError("Business no longer exists")
                _, _, context = build_adaptive_sales_plan_with_context(session, lead)
                SalesEvidenceService().record_review(session, lead, context=context, reviewer=self.reviewer.text(), source_text=self.notes.text())
                self._refresh_plan(session, lead)
                session.commit()
            self.refresh()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Review not recorded", str(exc))

    def record_delivery(self):
        try:
            with self.session_factory() as session:
                lead = session.get(Lead, self.lead_id)
                if lead is None:
                    raise ValueError("Business no longer exists")
                fields = json.loads(self.fields.toPlainText())
                prerequisites = json.loads(self.prerequisites.toPlainText())
                DeliveryPacketService().record(session, lead, fields=fields, selected_price=self.amount.value(),
                                               reviewer=self.reviewer.text(), source_text=self.notes.text(),
                                               reviewed=self.reviewed.isChecked(), owner_approved=self.owner_approved.isChecked(),
                                               prerequisites=prerequisites)
                self._refresh_plan(session, lead)
                session.commit()
            self.refresh()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Delivery facts not recorded", str(exc))
