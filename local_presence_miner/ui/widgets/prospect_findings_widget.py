"""Compact, source-bound finding review inside the existing lead workspace."""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.ai_discoverability import AI_MENTION_STATES, AI_PROVIDERS, AI_TOOL_STATES, ai_disclosure, ai_snapshot
from local_presence_miner.domain.commercial import canonical_json, fingerprint
from local_presence_miner.domain.prospect_findings import CONTACT_FACTS
from local_presence_miner.services.prospect_finding_service import (
    capture_contact_finding,
    contact_source_snapshot,
    finding_history,
    project_findings,
    record_ai_observation,
    record_owner_need,
    revise_finding,
)
from local_presence_miner.ui.components import DataTable, SectionHeader, table_item


class FindingEditorDialog(QDialog):
    def __init__(self, session_factory, lead_id: int, *, kind: str, head: dict | None = None, parent=None):
        super().__init__(parent)
        self.session_factory, self.lead_id, self.kind, self.head = session_factory, lead_id, kind, head
        self.current_snapshot: dict | None = None
        self.setWindowTitle("Review source-linked finding" if head else "Record source-linked finding")
        self.resize(820, 690)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("MainContent")
        form = QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        notice = QLabel("Review checks the wording against its recorded source. Business impact, owner agreement and contact permission "
                        "require their existing reviews. Original evidence and earlier revisions remain in history.")
        notice.setWordWrap(True)
        form.addRow(notice)
        self.actor = QLineEdit()
        self.actor.setMaxLength(160)
        form.addRow("Your name", self.actor)
        source = head.get('source', {}) if head else {}
        payload = source.get('payload', {})
        self.source_view = QPlainTextEdit()
        self.source_view.setReadOnly(True)
        self.source_view.setMaximumHeight(155)
        if kind == 'website_contact_path':
            self.fact = QComboBox()
            for fact_id, (_key, label) in CONTACT_FACTS.items():
                self.fact.addItem(label.capitalize(), fact_id)
            if head:
                self.fact.setCurrentIndex(self.fact.findData(head['fact_id']))
                self.fact.setEnabled(False)
            form.addRow("Recorded contact-path check", self.fact)
            self.capture_current = QCheckBox("Use the current scan as a new source revision")
            if head:
                form.addRow(self.capture_current)
                self.capture_current.toggled.connect(self.refresh_source)
            self.fact.currentIndexChanged.connect(self.refresh_source)
            form.addRow("Source being reviewed", self.source_view)
            self.refresh_source()
        elif kind == 'ai_discoverability':
            self.build_ai_form(form, payload)
            if head:
                self.source_view.setPlainText(head['source_snapshot_json'])
                form.addRow('Original immutable source', self.source_view)
        else:
            self.owner_label = QLineEdit(payload.get('owner_label', ''))
            self.source_text = QPlainTextEdit(payload.get('source_text', ''))
            self.source_text.setMaximumHeight(110)
            self.source_ref = QLineEdit(payload.get('source_ref', ''))
            legacy_time = bool(head and source.get('source_kind') == 'operator_attribution.v1')
            self.observed_at = QLineEdit('' if legacy_time else payload.get('observed_at_original') or '')
            self.observed_at.setPlaceholderText("ISO timestamp with original timezone offset; blank means unknown")
            if legacy_time and head is not None:
                time_notice = QLabel('Legacy source has no original timezone provenance. Its historical UTC rendering is not verified UTC. '
                                     'Enter an original timestamp only if its timezone is known; otherwise leave blank.')
                time_notice.setWordWrap(True)
                form.addRow(time_notice)
                self.source_view.setPlainText(head['source_snapshot_json'])
                form.addRow('Preserved historical source',self.source_view)
            self.attribution = QComboBox()
            self.attribution.addItem("Owner statement entered by operator", 'OPERATOR_REPORTED_OWNER')
            self.attribution.addItem("Operator observation / hypothesis", 'OPERATOR_OBSERVATION')
            self.attribution.setCurrentIndex(self.attribution.findData(payload.get('attribution', 'OPERATOR_REPORTED_OWNER')))
            self.text_mode = QComboBox()
            self.text_mode.addItems(['VERBATIM', 'PARAPHRASED'])
            self.text_mode.setCurrentText(payload.get('source_text_mode', 'PARAPHRASED'))
            for label, field in (("Person / context", self.owner_label), ("Original wording", self.source_text),
                                 ("Source / conversation reference", self.source_ref), ("Original time", self.observed_at),
                                 ("Attribution", self.attribution), ("Wording", self.text_mode)):
                form.addRow(label, field)
        self.inference = QLineEdit(head.get('inference', '') if head else '')
        self.question = QLineEdit(head.get('owner_question', '') if head else '')
        form.addRow("Possible consequence / inference", self.inference)
        form.addRow("Question for the owner", self.question)
        self.review_state = QComboBox()
        self.review_state.addItems(['UNREVIEWED', 'VERIFIED', 'UNKNOWN', 'DISPUTED'])
        self.review_state.setCurrentText(head.get('review_state', 'UNKNOWN') if head else 'UNREVIEWED')
        self.review_note = QPlainTextEdit()
        self.review_note.setMaximumHeight(80)
        self.source_checked = QCheckBox("I checked the source, date, attribution and exact wording recorded here")
        if head:
            form.addRow("Review state", self.review_state)
            form.addRow("What you checked / correction reason", self.review_note)
            form.addRow(self.source_checked)
            if kind == 'ai_discoverability':
                self.approve_customer_claim = QCheckBox('Approve the complete external-disclosure preview for proposal selection')
                form.addRow(self.approve_customer_claim)
                qualified = QLabel('Only the complete external preview may be disclosed. Original prompts, responses, context, citations '
                                   'and internal references stay internal. Each proposal requires selection; legacy approvals require '
                                   'a new disclosure review. Any new revision requires fresh approval.')
                qualified.setWordWrap(True)
                qualified.setTextFormat(Qt.TextFormat.PlainText)
                form.addRow(qualified)
        else:
            review_notice = QLabel("New findings start UNREVIEWED. Open the saved finding to record a source review.")
            review_notice.setWordWrap(True)
            form.addRow(review_notice)
        actions = QHBoxLayout()
        save = QPushButton("Save new revision" if head else "Capture finding")
        save.clicked.connect(self.save)
        close = QPushButton("Cancel")
        close.clicked.connect(self.reject)
        actions.addWidget(save)
        actions.addWidget(close)
        outer.addLayout(actions)

    def refresh_source(self, *_args) -> None:
        try:
            with self.session_factory() as session:
                self.current_snapshot = contact_source_snapshot(session, self.lead_id, self.fact.currentData())
            recorded = self.head['source_snapshot_json'] if self.head and not self.capture_current.isChecked() else canonical_json(self.current_snapshot)
            self.source_view.setPlainText(recorded)
        except ValueError as exc:
            self.current_snapshot = None
            self.source_view.setPlainText(self.head['source_snapshot_json'] if self.head else str(exc))

    def manual_source(self) -> dict:
        return {"owner_label": self.owner_label.text(), "source_text": self.source_text.toPlainText(),
                "source_ref": self.source_ref.text(), "source_text_mode": self.text_mode.currentText(),
                "attribution": self.attribution.currentData(), "observed_at": self.observed_at.text().strip() or None}

    def build_ai_form(self, form: QFormLayout, payload: dict) -> None:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead is None:
                raise ValueError('Business no longer exists.')
            self.ai_business = {'name': lead.name, 'place_id': lead.place_id or '', 'website': lead.website or ''}
        notice = QLabel('One manual response is one test, not overall AI visibility. Record the exact response and manually '
                        'annotate mentions; no model is queried and no business claim, offer or price is inferred.')
        notice.setWordWrap(True)
        form.addRow(notice)
        self.ai_fields: dict[str, Any] = {}
        lists = {'mentioned_businesses', 'omitted_businesses', 'prospect_aliases', 'competitor_mentions', 'citations', 'source_refs', 'observed_inaccuracies'}
        choices = {'provider': AI_PROVIDERS, 'browsing_available': AI_TOOL_STATES, 'browsing_used': AI_TOOL_STATES,
                   'prospect_mention': AI_MENTION_STATES}
        labels = {
            'provider': 'Provider', 'model': 'Model (UNKNOWN if unavailable)', 'model_version': 'Version (UNKNOWN if unavailable)',
            'captured_at': 'Original test timestamp (ISO with timezone; blank = unknown)', 'prompt': 'Exact prompt',
            'response': 'Exact response', 'test_context': 'Test context: location, language, account/session, instructions',
            'browsing_available': 'Search/browsing available?', 'browsing_used': 'Search/browsing actually used?',
            'prospect_mention': 'This prospect in this response (manual annotation)', 'mentioned_businesses': 'Mentioned businesses (one per line)',
            'prospect_aliases': 'Recorded prospect trading names / aliases (one per line; verify manually)',
            'omitted_businesses': 'Omitted businesses (manual annotation, one per line)', 'competitor_mentions': 'Competitor mentions (one per line)',
            'citations': 'Citations (one per line; blank = not recorded)', 'source_refs': 'Source/artifact references (one per line)',
            'repeat_group': 'Related test group (optional)', 'variability_notes': 'Repeated-test / variability notes (optional)',
            'observed_inaccuracies': 'Operator-noted inaccuracies (one per line; not authenticated facts)',
        }
        for key, label in labels.items():
            value = payload.get(key)
            field: Any
            if key in choices:
                field = QComboBox()
                field.addItems(list(choices[key]))
                if value:
                    field.setCurrentText(value)
            elif key in lists or key in {'prompt', 'response', 'test_context', 'variability_notes'}:
                field = QPlainTextEdit('\n'.join(value or []) if key in lists else value or '')
                field.setMaximumHeight(140 if key == 'response' else 80)
            else:
                field = QLineEdit(value or ('UNKNOWN' if key in {'model', 'model_version'} else ''))
            self.ai_fields[key] = field
            form.addRow(label, field)
        self.ai_preview = QPlainTextEdit()
        self.ai_preview.setReadOnly(True)
        self.ai_preview.setMaximumHeight(110)
        form.addRow('Complete external-disclosure preview', self.ai_preview)
        for field in self.ai_fields.values():
            signal = field.currentTextChanged if isinstance(field, QComboBox) else field.textChanged
            signal.connect(self.refresh_ai_preview)
        self.refresh_ai_preview()

    def refresh_ai_preview(self, *_args) -> None:
        try:
            self.ai_preview.setPlainText(ai_disclosure(ai_snapshot(self.lead_id, business=self.ai_business, **self.ai_source())))
        except (ValueError, TypeError) as exc:
            self.ai_preview.setPlainText('Incomplete source: ' + str(exc))

    def ai_source(self) -> dict:
        lists = {'mentioned_businesses', 'omitted_businesses', 'prospect_aliases', 'competitor_mentions', 'citations', 'source_refs', 'observed_inaccuracies'}
        result: dict[str, Any] = {}
        for key, field in self.ai_fields.items():
            value = field.currentText() if isinstance(field, QComboBox) else field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()
            result[key] = [item for item in value.splitlines() if item.strip()] if key in lists else value
        result['captured_at'] = result['captured_at'].strip() or None
        if not result['test_context'].strip():
            result['test_context'] = 'UNKNOWN'
        return result

    def save(self) -> None:
        try:
            with self.session_factory() as session:
                fields: dict[str, Any] = {"actor": self.actor.text(), "inference_text": self.inference.text(), "owner_question": self.question.text()}
                if self.head:
                    fields.update(review_state=self.review_state.currentText(), review_note=self.review_note.toPlainText(),
                                  source_checked=self.source_checked.isChecked())
                    if self.kind == 'website_contact_path':
                        fields.update(capture_current=self.capture_current.isChecked(),
                                      expected_source_sha256=fingerprint(self.current_snapshot) if self.current_snapshot else None)
                    elif self.kind == 'ai_discoverability':
                        fields['corrected_ai_source'] = self.ai_source()
                        fields['approve_customer_claim'] = self.approve_customer_claim.isChecked()
                    else:
                        fields['corrected_manual_source'] = self.manual_source()
                    revise_finding(session, self.lead_id, self.head['finding_key'], expected_revision=self.head['revision'], **fields)
                elif self.kind == 'website_contact_path':
                    # Capture remains unreviewed; no review is transferred from a preview.
                    capture_contact_finding(session, self.lead_id, self.fact.currentData(), **fields)
                elif self.kind == 'ai_discoverability':
                    record_ai_observation(session, self.lead_id, **self.ai_source(), **fields)
                else:
                    record_owner_need(session, self.lead_id, **self.manual_source(), **fields)
                session.commit()
            self.accept()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Finding not saved", str(exc))


class ProspectFindingsWidget(QWidget):
    findings_changed = Signal()

    def __init__(self, session_factory, lead_id: int, parent=None):
        super().__init__(parent)
        self.session_factory, self.lead_id = session_factory, lead_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(SectionHeader("Source-linked findings", "Review a contact check, attributed owner need or manually captured AI response."))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = DataTable(['Finding', 'Review', 'Source age', 'Current source', 'Revision'])
        self.table.setMaximumHeight(180)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        for title, callback in (("Capture contact check", self.capture_web), ("Record owner need", self.capture_owner),
                                ("Record AI response", self.capture_ai),
                                ("Review / correct", self.review_selected), ("History / source", self.show_history)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self) -> None:
        with self.session_factory() as session:
            findings = project_findings(session, self.lead_id)
        self.table.setRowCount(0)
        for finding in findings:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (finding['claim'], finding['review_state'], finding['freshness'],
                      'Approved observation' if finding['customer_claim_eligible'] else
                      'AI response only' if finding['finding_type'] == 'ai_discoverability' else
                      'Eligible observation' if finding['commercial_fact_eligible'] else
                      'Attributed only' if finding['finding_type'] == 'manual_owner_need' else 'Review required', str(finding['revision']))
            for column, value in enumerate(values):
                item = table_item(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, finding)
                self.table.setItem(row, column, item)
        self.table.fit_columns(stretch_column=0)
        self.table.setVisible(bool(findings))
        self.summary.setText("Select a finding to review its exact source or correction history." if findings else
                             "No finding recorded. Capture a contact check, attributed owner need or manual AI response.")

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def _edit(self, kind: str, head: dict | None = None) -> None:
        dialog = FindingEditorDialog(self.session_factory, self.lead_id, kind=kind, head=head, parent=self)
        if dialog.exec():
            self.refresh()
            self.findings_changed.emit()

    def capture_web(self) -> None:
        self._edit('website_contact_path')

    def capture_owner(self) -> None:
        self._edit('manual_owner_need')

    def capture_ai(self) -> None:
        self._edit('ai_discoverability')

    def review_selected(self) -> None:
        selected = self._selected()
        if selected:
            self._edit(selected['finding_type'], selected)

    def show_history(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        with self.session_factory() as session:
            history = finding_history(session, self.lead_id, selected['finding_key'])
        dialog = QDialog(self)
        dialog.setWindowTitle("Original finding sources and review history")
        dialog.resize(800, 640)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(json.dumps(history, indent=2, ensure_ascii=False))
        view.setReadOnly(True)
        layout.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
