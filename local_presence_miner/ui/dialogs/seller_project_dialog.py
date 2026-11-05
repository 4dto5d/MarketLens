from __future__ import annotations

from typing import cast

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTextEdit, QVBoxLayout
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.pricing_repository import PROOF_STATUSES, PROOF_TYPES, deactivate_seller_project, save_seller_project
from local_presence_miner.database.schema import SellerProject


class SellerProjectDialog(QDialog):
    """Explicit engagement editor; artifacts are linked separately in Seller Proof."""

    def __init__(self, session_factory: sessionmaker[Session], project_id: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.session_factory = session_factory
        self.project_id = project_id
        self.setWindowTitle("Seller Project")
        with session_factory() as session:
            project = session.get(SellerProject, project_id) if project_id else None
            values = project_values(project)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.project_type = QComboBox()
        self.project_type.addItems(PROOF_TYPES)
        self.project_type.setCurrentText(str(values["project_type"]))
        self.title = QLineEdit(str(values["title"]))
        self.status = QComboBox()
        self.status.addItems(PROOF_STATUSES)
        self.status.setCurrentText(str(values["status"]))
        self.niche = QLineEdit(str(values["niche"]))
        self.client_name = QLineEdit(str(values["client_name"]))
        self.project_value = QSpinBox()
        self.project_value.setRange(0, 10_000_000)
        self.project_value.setSpecialValueText("Not recorded")
        self.project_value.setValue(cast(int, values["project_value"]))
        self.completion_date = QLineEdit(str(values["completion_date"]))
        self.completion_date.setPlaceholderText("YYYY-MM-DD or blank")
        self.client_work = QCheckBox("This is actual client work")
        self.client_work.setChecked(bool(values["client_work"]))
        self.verified = QCheckBox("Operator has verified the project record")
        self.verified.setChecked(bool(values["verified"]))
        self.counting_state = QComboBox()
        self.counting_state.addItem("Incomplete", "incomplete")
        self.counting_state.addItem("Confirmed completed project", "confirmed")
        self.counting_state.addItem("Legacy unresolved", "legacy_unresolved")
        self.counting_state.setCurrentIndex(max(0, self.counting_state.findData(values["counting_state"])))
        self.provenance = QTextEdit(str(values["provenance"]))
        self.notes = QTextEdit(str(values["notes"]))
        for label, widget in [
            ("Project type", self.project_type), ("Title", self.title), ("Status", self.status), ("Niche", self.niche),
            ("Client", self.client_name), ("Project value", self.project_value), ("Completion date", self.completion_date),
            ("Client work", self.client_work), ("Verified", self.verified), ("Count state", self.counting_state),
            ("Provenance", self.provenance), ("Private notes", self.notes),
        ]:
            form.addRow(label, widget)
        layout.addLayout(form)
        actions = QHBoxLayout()
        save = QPushButton("Save Project")
        save.clicked.connect(self.save)
        actions.addWidget(save)
        if project_id is not None:
            invalidate = QPushButton("Invalidate Project")
            invalidate.clicked.connect(self.invalidate)
            actions.addWidget(invalidate)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        layout.addLayout(actions)

    def save(self) -> None:
        try:
            with self.session_factory() as session:
                save_seller_project(
                    session,
                    project_id=self.project_id,
                    project_type=self.project_type.currentText(),
                    title=self.title.text(),
                    status=self.status.currentText(),
                    niche=self.niche.text(),
                    client_name=self.client_name.text(),
                    project_value=self.project_value.value() or None,
                    completion_date=self.completion_date.text(),
                    client_work=self.client_work.isChecked(),
                    verified=self.verified.isChecked(),
                    counting_state=str(self.counting_state.currentData()),
                    provenance=self.provenance.toPlainText(),
                    notes=self.notes.toPlainText(),
                )
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot save project", str(exc))
            return
        self.accept()

    def invalidate(self) -> None:
        if self.project_id is None:
            return
        with self.session_factory() as session:
            deactivate_seller_project(session, self.project_id)
            session.commit()
        self.accept()


def project_values(project: SellerProject | None) -> dict[str, object]:
    return {
        "project_type": project.project_type if project else "Other",
        "title": project.title if project else "",
        "status": project.status if project else "Unclassified",
        "niche": project.niche if project else "",
        "client_name": project.client_name or "" if project else "",
        "project_value": project.project_value or 0 if project else 0,
        "completion_date": project.completion_date or "" if project else "",
        "client_work": project.client_work if project else False,
        "verified": project.verified if project else False,
        "counting_state": project.counting_state if project else "incomplete",
        "provenance": project.provenance if project else "",
        "notes": project.notes if project else "",
    }
