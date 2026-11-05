from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.pricing_repository import PROOF_STATUSES, PROOF_TYPES, list_seller_projects, save_seller_proof
from local_presence_miner.database.schema import SellerProof
from local_presence_miner.services.adaptive_sales_asset_service import refresh_after_seller_proof_change
from local_presence_miner.ui.dialogs.seller_project_dialog import SellerProjectDialog


class SellerProofDialog(QDialog):
    def __init__(self, session_factory: sessionmaker[Session], proof_id: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Seller Proof & Experience")
        self.resize(720, 760)
        self.session_factory = session_factory
        self.proof_id = proof_id
        with session_factory() as session:
            proof = session.get(SellerProof, proof_id) if proof_id else None
            values = proof_values(proof)
        layout = QVBoxLayout(self)
        fields = QWidget()
        form = QFormLayout(fields)
        self.proof_type = QComboBox()
        self.proof_type.addItems(PROOF_TYPES)
        self.proof_type.setCurrentText(values["proof_type"])
        self.status = QComboBox()
        self.status.addItems(PROOF_STATUSES)
        self.status.setCurrentText(values["status"])
        self.title = QLineEdit(values["title"])
        self.project = QComboBox()
        self._load_projects(values["project_id"])
        self.new_project = QPushButton("New Project")
        self.new_project.clicked.connect(self._new_project)
        self.niche = QLineEdit(values["niche"])
        self.description = QTextEdit(values["description"])
        self.client_name = QLineEdit(values["client_name"])
        self.project_value = QSpinBox()
        self.project_value.setRange(0, 10_000_000)
        self.project_value.setSpecialValueText("Not recorded")
        self.project_value.setValue(values["project_value"])
        self.completion_date = QLineEdit(values["completion_date"])
        self.completion_date.setPlaceholderText("YYYY-MM-DD or blank")
        self.public_url = QLineEdit(values["public_url"])
        self.verified = QCheckBox("Operator has verified this evidence")
        self.verified.setChecked(values["verified"])
        self.client_work = QCheckBox("This is actual client work")
        self.client_work.setChecked(values["client_work"])
        self.software_ai_project = QCheckBox("Software / AI / automation project")
        self.software_ai_project.setChecked(values["software_ai_project"])
        self.testimonial_available = QCheckBox("Testimonial is available")
        self.testimonial_available.setChecked(values["testimonial_available"])
        self.measurable_result_available = QCheckBox("Measurable result is available")
        self.measurable_result_available.setChecked(values["measurable_result_available"])
        self.before_after_available = QCheckBox("Before / after evidence is available")
        self.before_after_available.setChecked(values["before_after_available"])
        self.internal_only = QCheckBox("Internal only — never use this proof in outbound material")
        self.internal_only.setChecked(values["internal_only"])
        self.share_client_name = QCheckBox("Permission to name the client")
        self.share_client_name.setChecked(values["share_client_name"])
        self.share_public_url = QCheckBox("Permission to share the public URL")
        self.share_public_url.setChecked(values["share_public_url"])
        self.share_testimonial = QCheckBox("Permission to quote/share the testimonial")
        self.share_testimonial.setChecked(values["share_testimonial"])
        self.share_case_study = QCheckBox("Permission to show before/after or case-study material")
        self.share_case_study.setChecked(values["share_case_study"])
        self.share_reference = QCheckBox("Permission to offer this client as a reference")
        self.share_reference.setChecked(values["share_reference"])
        self.provenance = QTextEdit(values["provenance"])
        self.provenance.setMaximumHeight(70)
        self.safe_claims = QTextEdit("\n".join(values["safe_claims"]))
        self.safe_claims.setPlaceholderText("One supportable claim per line")
        self.safe_claims.setMaximumHeight(80)
        self.prohibited_claims = QTextEdit("\n".join(values["prohibited_claims"]))
        self.prohibited_claims.setPlaceholderText("One claim the app must not make per line")
        self.prohibited_claims.setMaximumHeight(80)
        self.notes = QTextEdit(values["notes"])
        for label, widget in [
            ("Proof type", self.proof_type),
            ("Status", self.status),
            ("Title", self.title),
            ("Project", self.project),
            ("", self.new_project),
            ("Niche", self.niche),
            ("Description", self.description),
            ("Client name", self.client_name),
            ("Project value", self.project_value),
            ("Completion date", self.completion_date),
            ("Public URL", self.public_url),
            ("Verified", self.verified),
            ("Client work", self.client_work),
            ("Software / AI", self.software_ai_project),
            ("Testimonial", self.testimonial_available),
            ("Measurable result", self.measurable_result_available),
            ("Before / after", self.before_after_available),
            ("Privacy", self.internal_only),
            ("Client name sharing", self.share_client_name),
            ("URL sharing", self.share_public_url),
            ("Testimonial sharing", self.share_testimonial),
            ("Case-study sharing", self.share_case_study),
            ("Reference sharing", self.share_reference),
            ("Provenance", self.provenance),
            ("Safe claims", self.safe_claims),
            ("Do not claim", self.prohibited_claims),
            ("Private notes", self.notes),
        ]:
            form.addRow(label, widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        layout.addWidget(scroll)
        self.internal_only.toggled.connect(self._update_sharing_controls)
        self._update_sharing_controls()
        actions = QHBoxLayout()
        save = QPushButton("Save Proof")
        cancel = QPushButton("Cancel")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        actions.addWidget(save)
        actions.addWidget(cancel)
        layout.addLayout(actions)

    def _update_sharing_controls(self) -> None:
        for checkbox in (self.share_client_name, self.share_public_url, self.share_testimonial, self.share_case_study, self.share_reference):
            checkbox.setEnabled(not self.internal_only.isChecked())

    def save(self) -> None:
        try:
            with self.session_factory() as session:
                save_seller_proof(
                    session,
                    proof_id=self.proof_id,
                    project_id=self.project.currentData(),
                    proof_type=self.proof_type.currentText(),
                    title=self.title.text(),
                    status=self.status.currentText(),
                    niche=self.niche.text(),
                    description=self.description.toPlainText(),
                    client_name=self.client_name.text(),
                    project_value=self.project_value.value() or None,
                    completion_date=self.completion_date.text(),
                    public_url=self.public_url.text(),
                    verified=self.verified.isChecked(),
                    client_work=self.client_work.isChecked(),
                    software_ai_project=self.software_ai_project.isChecked(),
                    testimonial_available=self.testimonial_available.isChecked(),
                    measurable_result_available=self.measurable_result_available.isChecked(),
                    before_after_available=self.before_after_available.isChecked(),
                    provenance=self.provenance.toPlainText(),
                    safe_claims=self._lines(self.safe_claims.toPlainText()),
                    prohibited_claims=self._lines(self.prohibited_claims.toPlainText()),
                    internal_only=self.internal_only.isChecked(),
                    share_client_name=self.share_client_name.isChecked(),
                    share_public_url=self.share_public_url.isChecked(),
                    share_testimonial=self.share_testimonial.isChecked(),
                    share_case_study=self.share_case_study.isChecked(),
                    share_reference=self.share_reference.isChecked(),
                    notes=self.notes.toPlainText(),
                )
                refresh_after_seller_proof_change(session, AppConfig.load().sender)
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot save proof", str(exc))
            return
        self.accept()

    def _load_projects(self, selected_id: int | None = None) -> None:
        self.project.clear()
        self.project.addItem("Unlinked / non-project evidence", None)
        with self.session_factory() as session:
            for project in list_seller_projects(session):
                self.project.addItem(f"#{project.id} — {project.title}", project.id)
        if selected_id is not None:
            index = self.project.findData(selected_id)
            if index >= 0:
                self.project.setCurrentIndex(index)

    def _new_project(self) -> None:
        if SellerProjectDialog(self.session_factory, parent=self).exec() == QDialog.DialogCode.Accepted:
            self._load_projects()

    @staticmethod
    def _lines(value: str) -> list[str]:
        return [line.strip() for line in value.splitlines() if line.strip()]


def proof_values(proof: SellerProof | None) -> dict:
    return {
        "proof_type": proof.proof_type if proof else "Other",
        "project_id": proof.project_id if proof else None,
        "status": proof.status if proof else "Unclassified",
        "title": proof.title if proof else "",
        "niche": proof.niche if proof else "",
        "description": proof.description if proof else "",
        "client_name": proof.client_name or "" if proof else "",
        "project_value": proof.project_value or 0 if proof else 0,
        "completion_date": proof.completion_date or "" if proof else "",
        "public_url": proof.public_url or "" if proof else "",
        "verified": proof.verified if proof else False,
        "client_work": proof.client_work if proof else False,
        "software_ai_project": proof.software_ai_project if proof else False,
        "testimonial_available": proof.testimonial_available if proof else False,
        "measurable_result_available": proof.measurable_result_available if proof else False,
        "before_after_available": proof.before_after_available if proof else False,
        "internal_only": proof.internal_only if proof else True,
        "share_client_name": proof.share_client_name if proof else False,
        "share_public_url": proof.share_public_url if proof else False,
        "share_testimonial": proof.share_testimonial if proof else False,
        "share_case_study": proof.share_case_study if proof else False,
        "share_reference": proof.share_reference if proof else False,
        "provenance": proof.provenance if proof else "",
        "safe_claims": json.loads(proof.safe_claims_json or "[]") if proof else [],
        "prohibited_claims": json.loads(proof.prohibited_claims_json or "[]") if proof else [],
        "notes": proof.notes if proof else "",
    }
