"""Optional, explicitly dispatched intelligence within Guided Opportunity."""
from __future__ import annotations

import json
from collections.abc import Callable
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from local_presence_miner.domain.opportunity_intelligence import MODES, canonical
from local_presence_miner.services.chatgpt_auth_service import ChatGPTAuth
from local_presence_miner.services.chatgpt_inference_service import ChatGPTInference
from local_presence_miner.services.opportunity_intelligence_service import OpportunityIntelligenceService
from local_presence_miner.services.prospect_finding_service import project_findings


class WorkerSignals(QObject):
    finished = Signal(object)


def readable_context(prepared: dict) -> str:
    """Show disclosure in ordinary language; exact transport details remain inspectable."""
    packet = prepared["packet"]
    lines = ["Your question", packet["question"], "", "What will be shared"]
    hidden = {"evidence_id", "context_hash", "source_sha256", "source_matches_current", "record_id", "id"}

    def render(value, indent=0):
        prefix = "  " * indent
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in hidden:
                    lines.append(prefix + key.replace("_", " ").capitalize() + ":")
                    render(item, indent + 1)
        elif isinstance(value, list):
            if not value:
                lines.append(prefix + "None supplied")
            for item in value:
                render(item, indent + 1)
        else:
            lines.append(prefix + ("Unknown" if value is None else "Yes" if value is True else "No" if value is False else str(value)))

    for title, key in (("Business context", "subject"), ("Selected findings", "evidence"), ("Owner information", "owner_context"),
                       ("Saved planning worksheet", "worksheet"), ("Current service decision", "commercial_context"),
                       ("Delivery requirements", "delivery_context"), ("Selected research", "research_context"),
                       ("Missing and excluded information", "coverage")):
        lines.extend(["", title])
        render(packet[key])
    lines.extend(["", "Instructions accompanying this information",
                  "Use the supplied evidence only. Explain uncertainty, competing explanations and the next owner questions. "
                  "Assess technical feasibility, operator capability, commercial viability and execution readiness separately. "
                  "Return structured internal advice. Do not browse, approve work, quote a price, or invent facts.",
                  "", "Nothing is sent until you choose Send once. You can cancel."])
    return "\n".join(lines)


def readable_advice(advice: dict) -> str:
    """Keep the main operator view practical; machine contracts stay in history."""
    lines = [advice["summary"], "", "Internal AI advice — confirm sources and owner facts before acting."]
    if advice["status"] == "insufficient_evidence":
        lines.append("More evidence is needed. This is not approval to quote or proceed.")
    for heading, items, field in (("Questions to ask next", advice["owner_questions"], "question"),
                                  ("Interpretations to check", advice["interpretations"], "statement"),
                                  ("Unresolved contradictions", advice["contradictions"], "issue")):
        if items:
            lines.extend(["", heading])
            for item in items:
                lines.append("• " + item[field])
                if item.get("reason"):
                    lines.append("  Why: " + item["reason"])
                if item.get("unresolved_question"):
                    lines.append("  Confirm: " + item["unresolved_question"])
                for limitation in item.get("limitations", []) + item.get("competing_explanations", []):
                    lines.append("  Consider: " + limitation)
    lines.extend(["", "Feasibility — four separate AI assessments, not readiness approval"])
    for key, title in (("technical", "Technical feasibility"), ("operator", "Your delivery capability"),
                       ("commercial", "Commercial viability"), ("execution", "Permission and execution readiness")):
        item = advice["feasibility"][key]
        lines.append(title + ": " + item["assessment"].replace("_", " "))
        lines.extend("  Needs confirmation: " + value for value in item["missing_prerequisites"])
        lines.extend("  Assumption: " + value for value in item["assumptions"])
    if advice["alternatives"]:
        lines.extend(["", "Possible approaches — candidate scope only"])
        for option in advice["alternatives"]:
            lines.append("• " + option["label"] + " — " + option["disposition"].replace("_", " "))
            for key, title in (("candidate_deliverables", "Possible work"), ("dependencies", "Dependency"),
                               ("exclusions", "Excludes"), ("risks", "Risk")):
                lines.extend("  " + title + ": " + value for value in option[key])
    if advice["effort_uncertainty"]:
        lines.extend(["", "Effort questions — unvalidated planning, not a quote"])
        for item in advice["effort_uncertainty"]:
            lines.append("• " + item["task"] + ": " + item["missing_driver"])
            if item["hours_low"] is not None:
                lines.append(f"  Unvalidated range: {item['hours_low']}–{item['hours_high']} hours. {item['rationale']}")
    for heading, values in (("Next actions", [item["action"] for item in advice["next_actions"]]),
                             ("Conclusions the evidence does not support", advice["unsupported_conclusions"]),
                             ("Limitations", advice["limitations"])):
        if values:
            lines.extend(["", heading, *("• " + value for value in values)])
    lines.extend(["", "Select a question or next action below to review and append it to a new worksheet revision. "
                  "Exact source references and the structured response remain available in retained history."])
    return "\n".join(lines)


class ContextPreviewDialog(QDialog):
    def __init__(self, prepared: dict, account: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review what will be shared with OpenAI")
        self.resize(850, 650)
        layout = QVBoxLayout(self)
        label = QLabel(f"ChatGPT account: {account.get('label', 'Connected account')}\nModel: {prepared['model']} · {prepared['packet']['mode']}\n"
                       "Only the information below will be sent, with instructions for producing internal advice. "
                       "Sending does not approve a service, price or customer contact.")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.summary = QPlainTextEdit(readable_context(prepared))
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary)
        details = QPushButton("Technical details — exact request")
        details.setCheckable(True)
        layout.addWidget(details)
        self.technical = QPlainTextEdit(canonical(prepared["body"]))
        self.technical.setReadOnly(True)
        self.technical.setMaximumHeight(220)
        self.technical.hide()
        details.toggled.connect(self.technical.setVisible)
        layout.addWidget(self.technical)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Send once")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class Worker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self):
        try:
            value = self.function()
            self.signals.finished.emit((True, value))
        except Exception as exc:
            # Transport/auth errors may contain secrets: never echo arbitrary exception text.
            code = getattr(exc, "code", "")
            safe = {"quota": "ChatGPT plan/app usage limit reached. Review ChatGPT Settings → Usage; no automatic retry.",
                    "auth": "Connection permission expired or was revoked. Reconnect explicitly.",
                    "unavailable": "Selected model/service is unavailable. Retry later explicitly.",
                    "unsupported": "The endpoint rejected this capability. No fallback was used.",
                    "incomplete": "Response did not complete. Partial text is not eligible for adoption."}
            safe.update(timeout="The local deadline was reached. No partial answer was adopted; retry explicitly if needed.",
                        cancelled="Request cancelled. No partial answer was adopted; remote usage may already have occurred.",
                        processing_limit="The stream exceeded a local processing bound; no partial answer was adopted.")
            fallback = "Request unavailable, cancelled, or invalid. Review connection, evidence and local/provider limits."
            self.signals.finished.emit((False, safe.get(code, fallback)))


class OpportunityIntelligenceWidget(QWidget):
    worksheet_adopted = Signal(object)

    def __init__(self, factory, lead_id: int, parent=None, *, auth=None, inference=None, service=None):
        super().__init__(parent)
        self.factory, self.lead_id = factory, lead_id
        self.auth = auth or ChatGPTAuth()
        self.inference = inference or ChatGPTInference(self.auth)
        self.service = service or OpportunityIntelligenceService(factory)
        self.cancel_event = Event()
        self.generation = 0
        self.worker: Worker | None = None
        self.result = None
        self.busy = False
        self.worksheet_reader: Callable[[], dict] | None = None
        layout = QFormLayout(self)
        self.enabled = QCheckBox("Optional intelligence — Off by default")
        self.enabled.toggled.connect(self.toggle)
        layout.addRow(self.enabled)
        note = QLabel("Internal advice only. Each request needs an outbound preview. Deep Investigation uses supplied evidence only; no web research. "
                      "Save the worksheet first. Existing commercial and contact approvals remain required.")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow(note)
        self.details = QWidget()
        layout.addRow(self.details)
        layout = QFormLayout(self.details)
        self.account_label = QLabel("Not connected")
        self.account_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow("Account", self.account_label)
        self.connect_button = QPushButton("Continue with ChatGPT")
        self.connect_button.clicked.connect(self.connect_account)
        layout.addRow(self.connect_button)
        self.disconnect_button = QPushButton("Disconnect ChatGPT")
        self.disconnect_button.clicked.connect(self.disconnect_account)
        layout.addRow(self.disconnect_button)
        self.models = QComboBox()
        layout.addRow("Account-supported model", self.models)
        self.mode = QComboBox()
        self.mode.addItems(list(MODES))
        layout.addRow("Mode", self.mode)
        self.question = QLineEdit()
        self.question.setMaxLength(4000)
        self.question.setPlaceholderText("What should I verify before offering this service?")
        layout.addRow("Question", self.question)
        self.include_worksheet = QCheckBox("Include saved operator worksheet (may contain private owner text)")
        layout.addRow(self.include_worksheet)
        self.findings = QListWidget()
        self.findings.setMaximumHeight(100)
        self.refresh_findings()
        layout.addRow("Optional evidence (none selected)", self.findings)
        self.limit = QSpinBox()
        self.limit.setRange(1, 100)
        self.limit.setValue(self.service.budget.daily_limit)
        self.limit.setToolTip("Local request policy; does not measure or cap remote tokens or subscription use.")
        layout.addRow("Local requests/day", self.limit)
        self.run_button = QPushButton("Review context and run once")
        self.run_button.clicked.connect(self.preview)
        layout.addRow(self.run_button)
        self.cancel_button = QPushButton("Cancel current request")
        self.cancel_button.clicked.connect(self.cancel)
        layout.addRow(self.cancel_button)
        self.status = QLabel("Off — no model requests on opening this screen.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(250)
        layout.addRow(self.output)
        self.items = QComboBox()
        layout.addRow("Select one planning item", self.items)
        self.adopt_button = QPushButton("Review and append selected question / next action")
        self.adopt_button.clicked.connect(self.adopt)
        layout.addRow(self.adopt_button)
        self.note_button = QPushButton("Record review — noted, not verified")
        self.note_button.clicked.connect(lambda: self.review("noted"))
        layout.addRow(self.note_button)
        self.reject_button = QPushButton("Record rejection of this advice")
        self.reject_button.clicked.connect(lambda: self.review("rejected"))
        layout.addRow(self.reject_button)
        history = QPushButton("View retained advice history")
        history.clicked.connect(self.history)
        layout.addRow(history)
        usage = QLabel('<a href="https://chatgpt.com/#settings/Usage">ChatGPT Settings → Usage</a>')
        usage.setOpenExternalLinks(True)
        layout.addRow(usage)
        self.controls = [self.connect_button, self.disconnect_button, self.models, self.mode, self.question,
                         self.include_worksheet, self.findings, self.limit, self.run_button]
        self.toggle(False)

    def refresh_findings(self):
        self.findings.clear()
        with self.factory() as session:
            for finding in project_findings(session, self.lead_id):
                item = QListWidgetItem(f"{finding['claim']} — {finding['review_state']}/{finding['freshness']}")
                item.setData(Qt.ItemDataRole.UserRole, finding['reference'])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.findings.addItem(item)

    @Slot(bool)
    def toggle(self, enabled):
        self.details.setVisible(enabled)
        if not enabled:
            self.cancel()
        for control in self.controls:
            control.setEnabled(enabled and not self.busy)
        self.cancel_button.setEnabled(self.busy)
        self.adopt_button.setEnabled(enabled and not self.busy and self.result is not None)
        self.note_button.setEnabled(enabled and not self.busy and self.result is not None)
        self.reject_button.setEnabled(enabled and not self.busy and self.result is not None)
        if not enabled:
            self.status.setText("Off — deterministic workflows remain available.")
        elif self.status.text().startswith("Off"):
            self.status.setText("Enabled — no inference until you review context and choose Send once.")

    def cancel(self):
        self.cancel_event.set()
        self.generation += 1
        self.result = None
        self.items.clear()
        self.adopt_button.setEnabled(False)

    def _start(self, function, kind):
        if self.busy:
            return
        self.cancel_event = Event()
        self.busy = True
        self.generation += 1
        generation = self.generation
        worker = Worker(lambda: (kind, generation, function()))
        worker.signals.finished.connect(self._finished)
        self.worker = worker
        self.toggle(self.enabled.isChecked())
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def _finished(self, message):
        self.busy = False
        ok, value = message
        if ok:
            kind, generation, result = value
            if generation != self.generation or not self.enabled.isChecked():
                self.status.setText("Cancelled — late results were not activated.")
            elif kind == "connect":
                account, models = result
                self.account_label.setText(account.get("label", "Connected account"))
                self.models.clear()
                for model in models:
                    self.models.addItem(model["display_name"], model["slug"])
                self.status.setText("Connected. Review the exact context before sending.")
            elif kind == "disconnect":
                self.account_label.setText("Disconnected")
                self.models.clear()
                self.status.setText("Signed out." if result else "Signed out locally; remote revocation was not confirmed. Disconnect in ChatGPT Settings.")
            else:
                self.result = result
                self.output.setPlainText(readable_advice(result["advice"]))
                self.items.clear()
                for item in result["advice"]["owner_questions"]:
                    self.items.addItem(item["question"], (item["id"], item["question"]))
                for item in result["advice"]["next_actions"]:
                    self.items.addItem(item["action"], (item["id"], item["action"]))
                self.items.setCurrentIndex(-1)
                self.status.setText("Retained advice — review sources before use." + (" Cache hit; no new request." if result["cached"] else ""))
        else:
            self.status.setText(value)
        self.toggle(self.enabled.isChecked())

    def connect_account(self):
        self.cancel()
        def connect():
            account = self.auth.account() or self.auth.sign_in(self.cancel_event)
            return account, self.inference.models()
        self._start(connect, "connect")

    def disconnect_account(self):
        self.cancel()
        self._start(self.auth.sign_out, "disconnect")

    def preview(self):
        try:
            self.check_unsaved()
            account = self.auth.account()
            if account is None:
                raise ValueError("Continue with ChatGPT first.")
            selected = [self.findings.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.findings.count())
                        if self.findings.item(i).checkState() == Qt.CheckState.Checked]
            prepared = self.service.prepare(self.lead_id, question=self.question.text(), mode=self.mode.currentText(),
                                            model=self.models.currentData(), account_binding=account["binding"],
                                            selected=selected, include_worksheet=self.include_worksheet.isChecked())
            dialog = ContextPreviewDialog(prepared, account, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.result = None
            self.service.budget.set_limit(self.limit.value())
            def execute():
                return self.service.execute(prepared, self.inference, cancel=self.cancel_event,
                                            current_account=lambda: (self.auth.account() or {}).get("binding"))
            self._start(execute, "advice")
        except (ValueError, TypeError) as exc:
            self.status.setText(str(exc))

    def adopt(self):
        selection = self.items.currentData()
        if not self.enabled.isChecked() or self.busy or self.result is None or selection is None:
            return
        item_id, original = selection
        edited, ok = QInputDialog.getMultiLineText(self, "Review planning text", "Append to a new worksheet; prior text will be preserved:", original)
        if not ok:
            return
        actor, ok = QInputDialog.getText(self, "Attribution", "Operator name")
        if not ok:
            return
        try:
            self.check_unsaved()
            account = self.auth.account() or {}
            identity = self.service.adopt(self.result["run_id"], lead_id=self.lead_id, account_binding=account.get("binding", ""),
                                          item_id=item_id, actor=actor, edited_text=edited)
            self.result = None
            self.adopt_button.setEnabled(False)
            self.status.setText(f"Appended as operator planning in worksheet {identity}. Reopen Guided Opportunity to load the new revision.")
            from local_presence_miner.services.opportunity_workflow_service import latest_worksheet

            with self.factory() as session:
                self.worksheet_adopted.emit(latest_worksheet(session, self.lead_id)["data"])
        except ValueError as exc:
            QMessageBox.warning(self, "Planning item not adopted", str(exc))

    def check_unsaved(self):
        if self.worksheet_reader is not None:
            from local_presence_miner.services.opportunity_workflow_service import latest_worksheet

            with self.factory() as session:
                saved = latest_worksheet(session, self.lead_id)
            if saved["state"] != "recorded" or saved["data"] != self.worksheet_reader():
                raise ValueError("Save current worksheet edits before running or adopting intelligence.")

    def history(self):
        self.result = None
        self.items.clear()
        self.adopt_button.setEnabled(False)
        self.output.setPlainText(json.dumps(self.service.history(self.lead_id), indent=2, ensure_ascii=False))

    def review(self, action):
        if not self.enabled.isChecked() or self.busy or self.result is None:
            return
        actor, ok = QInputDialog.getText(self, "Review attribution", "Operator name (review does not verify facts or authorize work)")
        if not ok:
            return
        try:
            account = self.auth.account() or {}
            self.service.review(self.result["run_id"], lead_id=self.lead_id, account_binding=account.get("binding", ""), actor=actor, action=action)
            self.status.setText(f"Review recorded: {action}. No commercial state changed.")
            if action == "rejected":
                self.result = None
                self.items.clear()
                self.toggle(self.enabled.isChecked())
        except ValueError as exc:
            self.status.setText(str(exc))

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)
