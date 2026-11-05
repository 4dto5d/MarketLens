from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.pricing_repository import list_seller_proof
from local_presence_miner.database.repositories import edit_outreach_draft, revalidate_outreach_evidence
from local_presence_miner.database.schema import OutreachDraft
from local_presence_miner.services.proof_dependency_service import PERMISSION_FIELDS, parse_dependencies, proof_allows_external_use


class OutreachEditorDialog(QDialog):
    def __init__(self, session_factory: sessionmaker[Session], draft_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Outreach Draft")
        self.session_factory = session_factory
        self.draft_id = draft_id
        self.resize(760, 720)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        with self.session_factory() as session:
            draft = session.get(OutreachDraft, draft_id)
            subject = draft.subject if draft else ""
            body = draft.body if draft else ""
            previous_ids = {item.get("proof_id") for item in parse_dependencies(draft.proof_dependencies_json)} if draft else set()
            proofs = list_seller_proof(session)
        self.subject = QLineEdit(subject)
        self.body = QTextEdit(body)
        form.addRow("Subject", self.subject)
        form.addRow("Body", self.body)
        layout.addLayout(form)
        note = QLabel(
            "Every text edit revokes approval and invalidates the old dependency snapshot. "
            "Select every proof used below, or none only when the text makes no Seller Proof claim. "
            "Review all disclosure permissions before confirming."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        proof_panel = QWidget()
        proof_layout = QVBoxLayout(proof_panel)
        self.proof_checks: dict[int, QCheckBox] = {}
        for proof in proofs:
            usages = [usage for usage in PERMISSION_FIELDS if proof_allows_external_use(proof, usage)]
            checkbox = QCheckBox(f"#{proof.id} {proof.title} — allowed: {', '.join(usages) or 'none / internal only'}")
            checkbox.setEnabled(bool(usages))
            checkbox.setChecked(proof.id in previous_ids and bool(usages))
            self.proof_checks[proof.id] = checkbox
            proof_layout.addWidget(checkbox)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(proof_panel)
        scroll.setMaximumHeight(180)
        layout.addWidget(scroll)
        self.confirm_evidence = QCheckBox(
            "I reviewed this exact text and its selected proof/disclosure permissions (none selected means no Seller Proof claims)."
        )
        layout.addWidget(self.confirm_evidence)
        buttons = QHBoxLayout()
        save = QPushButton("Save")
        cancel = QPushButton("Cancel")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def save(self) -> None:
        try:
            with self.session_factory() as session:
                edit_outreach_draft(session, self.draft_id, self.subject.text().strip(), self.body.toPlainText().strip())
                if self.confirm_evidence.isChecked():
                    selected = [proof_id for proof_id, checkbox in self.proof_checks.items() if checkbox.isChecked() and checkbox.isEnabled()]
                    revalidate_outreach_evidence(session, self.draft_id, selected, operator_confirmed=True)
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Evidence review required", str(exc))
            return
        self.accept()
