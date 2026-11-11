"""A small saved planning path into existing evidence, sales and CRM screens."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from local_presence_miner.database.schema import Lead
from local_presence_miner.services.opportunity_workflow_service import (
    NUMBER_FIELDS,
    ROUTES,
    TEXT_FIELDS,
    create_warm_opportunity,
    latest_worksheet,
    planning_cost,
    save_worksheet,
)
from local_presence_miner.services.prospect_finding_service import project_findings, project_linked_findings


class OpportunityWorkflowDialog(QDialog):
    def __init__(self, session_factory, lead_id: int | None = None, parent=None):
        super().__init__(parent)
        self.session_factory, self.lead_id = session_factory, lead_id
        self.destination = ""
        self.setWindowTitle("Guided opportunity — operator planning")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("MainContent")
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        note = QLabel("Business → evidence → owner confirmation → service → economics/delivery → conversation → next action → outcome. "
                      "This worksheet records plans and reported needs. Saving it does not approve outreach, select a Smart Offer, "
                      "verify a diagnosis or accept scope. Record actual owner confirmations and outcomes through Record Contact.")
        note.setWordWrap(True)
        form.addRow(note)
        self.name, self.website, self.category = QLineEdit(), QLineEdit(), QLineEdit()
        data = {}
        state = "empty"
        if lead_id is not None:
            with session_factory() as session:
                lead = session.get(Lead, lead_id)
                if lead is None:
                    raise ValueError("Business no longer exists.")
                self.name.setText(lead.name)
                self.website.setText(lead.website)
                self.category.setText(lead.category)
                stored = latest_worksheet(session, lead_id)
                data, state = stored["data"], stored["state"]
            for field in (self.name, self.website, self.category):
                field.setReadOnly(True)
        form.addRow("Business", self.name)
        form.addRow("Website (optional)", self.website)
        form.addRow("Business type (optional)", self.category)
        self.route = QComboBox()
        for value, label in ROUTES.items():
            self.route.addItem(label, value)
        self.route.setCurrentIndex(self.route.findData(data.get("route", "owner_report")))
        form.addRow("Discovery route", self.route)
        self.owner_reported = QCheckBox("Owner reported this need — operator attribution, not scope approval")
        self.owner_reported.setChecked(data.get("owner_reported", False))
        form.addRow(self.owner_reported)
        self.fields = {}
        for key, label in {**TEXT_FIELDS, **NUMBER_FIELDS}.items():
            field = QLineEdit(data.get(key, ""))
            field.setMaxLength(8000 if key in TEXT_FIELDS else 30)
            if key in NUMBER_FIELDS:
                field.setPlaceholderText("Blank = unknown; estimates only")
            self.fields[key] = field
            form.addRow(label, field)
        self.finding_links = QListWidget()
        self.finding_links.setMaximumHeight(120)
        if lead_id is not None:
            with session_factory() as session:
                choices = {item['reference']: item for item in project_findings(session, lead_id)}
                for item in project_linked_findings(session, lead_id, data.get('finding_refs', [])):
                    choices.setdefault(item['reference'], item)
            for reference, finding in choices.items():
                text = f"{finding['claim']} — {finding.get('review_state', 'UNKNOWN')} (revision {finding.get('revision', '?')})"
                link_item = QListWidgetItem(text)
                link_item.setData(Qt.ItemDataRole.UserRole, reference)
                link_item.setFlags(link_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                link_item.setCheckState(Qt.CheckState.Checked if reference in data.get('finding_refs', []) else Qt.CheckState.Unchecked)
                self.finding_links.addItem(link_item)
        form.addRow("Linked finding revisions", self.finding_links)
        self.feedback_label = QLabel("No worksheet recorded." if state == "empty" else
                             "Latest worksheet is invalid; review and save a new version. History remains unchanged." if state == "invalid" else
                             "Saved worksheet loaded. Review changing assumptions before use.")
        self.feedback_label.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback_label.setWordWrap(True)
        form.addRow(self.feedback_label)
        if lead_id is not None:
            from local_presence_miner.ui.widgets.opportunity_intelligence_widget import OpportunityIntelligenceWidget

            self.intelligence = OpportunityIntelligenceWidget(session_factory, lead_id, self)
            self.intelligence.worksheet_reader = self.data
            self.intelligence.worksheet_adopted.connect(self._adopted_worksheet)
            self.intelligence.destination_requested.connect(self.go)
            self.finished.connect(lambda _result: self.intelligence.cancel())
            form.addRow(self.intelligence)
        review = QPushButton("Calculate planning cost")
        review.clicked.connect(self.calculate)
        form.addRow(review)
        for title, destination in (
            ("1. Review source evidence and competing explanations", "Audit Evidence"),
            ("2. Record actual owner confirmation / conversation outcome", "Record Contact"),
            ("3. Review supported Smart Offer and actual canonical scope", "Smart Offer"),
            ("4. Check evidence, platform access, scope and delivery approval", "Delivery Review"),
            ("5. Open conversation guidance", "Guided Call"),
            ("6. Set follow-up / review outcome", "CRM"),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, target=destination: self.go(target))
            form.addRow(button)
        actions = QHBoxLayout()
        save = QPushButton("Save worksheet")
        save.clicked.connect(self.save)
        close = QPushButton("Close without saving")
        close.clicked.connect(self.reject)
        actions.addWidget(save)
        actions.addWidget(close)
        layout.addLayout(actions)

    def data(self) -> dict:
        return {"route": self.route.currentData(), "owner_reported": self.owner_reported.isChecked(),
                **{key: field.text() for key, field in self.fields.items()},
                "finding_refs": [self.finding_links.item(index).data(Qt.ItemDataRole.UserRole)
                                 for index in range(self.finding_links.count())
                                 if self.finding_links.item(index).checkState() == Qt.CheckState.Checked]}

    def _adopted_worksheet(self, data: dict) -> None:
        for key, field in self.fields.items():
            field.setText(data.get(key, ""))
        self.feedback_label.setText("AI-assisted planning appended to a new saved worksheet revision; prior human text retained.")

    def calculate(self) -> None:
        try:
            self.feedback_label.setText(planning_cost(self.data()))
        except ValueError as exc:
            self.feedback_label.setText(str(exc))

    def save(self) -> bool:
        try:
            with self.session_factory() as session:
                if self.lead_id is None:
                    lead = create_warm_opportunity(session, name=self.name.text(), website=self.website.text(),
                                                   category=self.category.text(), data=self.data())
                else:
                    lead = session.get(Lead, self.lead_id)
                    if lead is None:
                        raise ValueError("Business no longer exists.")
                    save_worksheet(session, lead, self.data())
                identity = lead.id
                session.commit()
            self.lead_id = identity
            self.feedback_label.setText("Saved as operator planning. Commercial approvals and qualification remain separate.")
            for field in (self.name, self.website, self.category):
                field.setReadOnly(True)
            return True
        except ValueError as exc:
            QMessageBox.warning(self, "Worksheet not saved", str(exc))
            return False

    def go(self, destination: str) -> None:
        if self.save():
            self.destination = destination
            self.accept()
