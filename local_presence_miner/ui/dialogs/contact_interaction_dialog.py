from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import loads, save_contact_interaction
from local_presence_miner.database.schema import ContactInteraction, Lead, OutreachDraft
from local_presence_miner.services.adaptive_sales_asset_service import refresh_after_interaction_change
from local_presence_miner.services.owner_strategy_service import append_owner_strategy, project_owner_strategy
from local_presence_miner.ui.components import ActionToolbar, FieldMessage, InfoBanner, SectionHeader

OUTCOMES = [
    "No answer",
    "Voicemail",
    "Replied",
    "Interested",
    "Meeting scheduled",
    "Price objection",
    "Not interested",
    "Already has provider",
    "Requested information",
    "Needs approval",
    "AI concern",
    "Already busy enough",
    "Wrong decision maker",
    "Follow up later",
    "Do not contact me again",
    "Won",
    "Lost",
    "Other",
]
RESPONSE_SIGNALS = ["Competitor comparison", "Website design", "Google presence", "Price", "Mockup"]
CREDIBILITY_SIGNALS = {
    "credibility_concern": "General credibility concern",
    "wants_examples": "Wants examples",
    "wants_references": "Wants references",
    "concerned_about_ai": "Concerned about AI",
    "wants_proof": "Wants proof",
    "seller_experience_question": "Asked about experience",
    "local_presence_question": "Asked whether seller is local",
    "decision_maker_skeptical": "Decision maker is skeptical",
    "legitimacy_concern": "Legitimacy / scam concern",
}
OBJECTIONS = [
    "",
    "Too expensive",
    "Budget unavailable",
    "Already has provider",
    "Cheaper provider",
    "AI concern",
    "Already busy enough",
    "Timing",
    "Not decision maker",
    "No perceived need",
    "Needs approval",
    "Other",
]


class ContactInteractionDialog(QDialog):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        lead_id: int,
        interaction_id: int | None = None,
        parent=None,
        default_method: str = "Email",
        defaults: dict[str, object] | None = None,
        config: AppConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Record Contact Outcome" if interaction_id is None else "Edit Contact Outcome")
        self.setMinimumSize(720, 760)
        self.session_factory = session_factory
        self.lead_id = lead_id
        self.interaction_id = interaction_id
        self.defaults = defaults or {}
        self.config = config
        with session_factory() as session:
            interaction = session.get(ContactInteraction, interaction_id) if interaction_id else None
            lead = session.get(Lead, lead_id)
            self.owner_strategy = project_owner_strategy(session, lead) if lead else {}

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(
            SectionHeader(
                "What happened?", "Most live-call context can be prefilled from Guided Call. Confirm or correct it instead of reconstructing the conversation."
            )
        )
        form = QFormLayout()
        self.when = QLineEdit(interaction.interaction_datetime if interaction else datetime.now().isoformat(timespec="minutes"))
        self.method = QComboBox()
        self.method.addItems(["Email", "Phone", "Voicemail", "SMS", "In person", "Other"])
        self.method.setCurrentText(interaction.method if interaction else default_method)
        self.direction = QComboBox()
        self.direction.addItems(["Outbound", "Inbound"])
        self.direction.setCurrentText(interaction.direction if interaction else "Outbound")
        self.outcome = QComboBox()
        self.outcome.setEditable(True)
        self.outcome.addItems(["", *OUTCOMES])
        self.outcome.setCurrentText(interaction.outcome if interaction else str(self.defaults.get("outcome", "")))
        if self.outcome.lineEdit() is not None:
            self.outcome.lineEdit().setPlaceholderText("Select or type the truthful outcome")
        form.addRow("Date/time", self.when)
        form.addRow("Method", self.method)
        form.addRow("Direction", self.direction)
        form.addRow("Outcome", self.outcome)
        layout.addLayout(form)

        identity = QFormLayout()
        self.contact_name = QLineEdit(interaction.contact_name if interaction else str(self.defaults.get("contact_name", getattr(lead, "owner", "") or "")))
        self.contact_role = QLineEdit(interaction.contact_role if interaction else str(self.defaults.get("contact_role", "")))
        self.decision_status = QComboBox()
        self.decision_status.setEditable(True)
        self.decision_status.addItems(
            ["Unknown", "Decision maker", "Owner identified", "Manager identified", "Not decision maker", "Outside provider", "Corporate control"]
        )
        self.decision_status.setCurrentText(interaction.decision_maker_status if interaction else str(self.defaults.get("decision_maker_status", "Unknown")))
        identity.addRow("Contact name", self.contact_name)
        identity.addRow("Role", self.contact_role)
        identity.addRow("Decision status", self.decision_status)
        layout.addLayout(identity)

        layout.addWidget(QLabel("WHAT DID THEY RESPOND TO?"))
        grid = QGridLayout()
        saved_signals = set(loads(interaction.response_signals_json, []) if interaction else [])
        self.signal_boxes: list[QCheckBox] = []
        for index, signal in enumerate(RESPONSE_SIGNALS):
            box = QCheckBox(signal)
            box.setChecked(signal in saved_signals)
            self.signal_boxes.append(box)
            grid.addWidget(box, index // 3, index % 3)
        layout.addLayout(grid)

        layout.addWidget(QLabel("CREDIBILITY / EARLY-CALL CONTEXT"))
        credibility_grid = QGridLayout()
        self.credibility_boxes: dict[str, QCheckBox] = {}
        for index, (key, label) in enumerate(CREDIBILITY_SIGNALS.items()):
            box = QCheckBox(label)
            value = bool(getattr(interaction, key, False)) if interaction else bool(self.defaults.get(key, False))
            box.setChecked(value)
            self.credibility_boxes[key] = box
            credibility_grid.addWidget(box, index // 3, index % 3)
        layout.addLayout(credibility_grid)

        detail = QFormLayout()
        self.objection = QComboBox()
        self.objection.addItems(OBJECTIONS)
        self.objection.setCurrentText(interaction.objection if interaction else str(self.defaults.get("objection", "")))
        self.business_goal = QLineEdit(interaction.business_goal if interaction else str(self.defaults.get("business_goal", "")))
        self.capacity = QLineEdit(interaction.capacity_status if interaction else str(self.defaults.get("capacity_status", "")))
        self.buyer_questions = QLineEdit(
            ", ".join(loads(interaction.buyer_questions_json, []) if interaction else list(self.defaults.get("buyer_questions", []) or []))
        )
        self.commitments = QLineEdit(", ".join(loads(interaction.commitments_json, []) if interaction else list(self.defaults.get("commitments", []) or [])))
        self.branch_path = QLineEdit(" > ".join(loads(interaction.branch_path_json, []) if interaction else list(self.defaults.get("branch_path", []) or [])))
        default_guided_call_identity = self.defaults.get("guided_call_identity", {})
        default_guided_call_sequence = self.defaults.get("guided_call_sequence", [])
        self.guided_call_identity = (
            loads(interaction.guided_call_identity_json, {})
            if interaction
            else dict(default_guided_call_identity)
            if isinstance(default_guided_call_identity, dict)
            else {}
        )
        self.guided_call_sequence = (
            loads(interaction.guided_call_sequence_json, [])
            if interaction
            else list(default_guided_call_sequence)
            if isinstance(default_guided_call_sequence, list)
            else []
        )
        self.next_action = QLineEdit(interaction.next_action if interaction else str(self.defaults.get("next_action", "")))
        self.follow_up = QLineEdit(interaction.follow_up_date if interaction else "")
        self.follow_up.setPlaceholderText("YYYY-MM-DD or leave blank")
        self.draft = QComboBox()
        self.draft.addItem("No linked outreach draft", None)
        with session_factory() as session:
            drafts = list(session.execute(select(OutreachDraft).where(OutreachDraft.lead_id == lead_id).order_by(OutreachDraft.updated_at.desc())).scalars())
        for draft in drafts:
            self.draft.addItem(f"#{draft.id} · {draft.kind}" + (" · approved" if draft.approved else " · needs review"), draft.id)
        if interaction and interaction.outreach_draft_id:
            idx = self.draft.findData(interaction.outreach_draft_id)
            if idx >= 0:
                self.draft.setCurrentIndex(idx)
        self.notes = QTextEdit(interaction.notes if interaction else str(self.defaults.get("notes", "")))
        self.notes.setMaximumHeight(90)
        detail.addRow("Objection", self.objection)
        detail.addRow("Business goal", self.business_goal)
        detail.addRow("Capacity", self.capacity)
        detail.addRow("Buyer questions", self.buyer_questions)
        detail.addRow("Commitments", self.commitments)
        detail.addRow("Call path", self.branch_path)
        detail.addRow("Next action", self.next_action)
        detail.addRow("Next follow-up", self.follow_up)
        detail.addRow("Linked draft", self.draft)
        detail.addRow("Notes", self.notes)
        layout.addLayout(detail)
        self._add_owner_preferences(layout)
        layout.addWidget(
            InfoBanner(
                "Conversation memory",
                "Saving this interaction updates structured sales context. If configuration is available, "
                "Smart Offer and scripts regenerate from the new context.",
                "info",
            )
        )
        self.error = FieldMessage()
        layout.addWidget(self.error)
        actions = ActionToolbar()
        actions.add_stretch()
        actions.add_action("Cancel", self.reject, role="tertiary")
        actions.add_action("Save Outcome", self.save, role="primary")
        layout.addWidget(actions)

    def _add_owner_preferences(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Owner preferences for the proposed work")
        form = QFormLayout(group)
        self.record_owner_preferences = QCheckBox("Record or correct structured owner preferences")
        form.addRow(self.record_owner_preferences)
        if self.owner_strategy.get("provenance"):
            source_history = QTextEdit("\n\n".join(
                f"Recorded #{row['assertion_id']} · {row['source_kind']} · {row['source_text_mode']}\n{row['source_text']}"
                for row in self.owner_strategy["provenance"]
            ))
            source_history.setReadOnly(True)
            source_history.setMaximumHeight(90)
            form.addRow("Current recorded source", source_history)
        self.owner_confirmation = QComboBox()
        self.owner_confirmation.addItems(["Needs owner confirmation", "Owner explicitly confirmed"])
        form.addRow("Confirmation", self.owner_confirmation)
        self.owner_wording = QTextEdit()
        self.owner_wording.setMaximumHeight(70)
        self.owner_wording.setPlaceholderText("Record the owner's original words, or identify the paraphrase below.")
        self.owner_text_mode = QComboBox()
        self.owner_text_mode.addItems(["VERBATIM", "PARAPHRASED"])
        form.addRow("Owner statement", self.owner_wording)
        form.addRow("Statement wording", self.owner_text_mode)
        facts = self.owner_strategy.get("constraints", [])

        def values(kind: str) -> str:
            return ", ".join(fact["value"] for fact in facts if fact["kind"] == kind)

        self.desired_services = QLineEdit(values("desired_service"))
        self.excluded_services = QLineEdit(values("excluded_service"))
        self.desired_services.setPlaceholderText("Exact existing service names, separated by commas")
        self.excluded_services.setPlaceholderText("For example: emergency plumbing")
        form.addRow("Desired services", self.desired_services)
        form.addRow("Excluded services", self.excluded_services)
        self.owner_customer_type = QComboBox()
        self.owner_customer_type.addItems(["Unknown / not specified", "Commercial only", "Residential only", "Both"])
        desired = values("desired_customer_type")
        if desired in {"commercial", "residential"}:
            self.owner_customer_type.setCurrentText(f"{desired.title()} only")
        elif "commercial" in desired and "residential" in desired:
            self.owner_customer_type.setCurrentText("Both")
        form.addRow("Desired customers", self.owner_customer_type)
        self.owner_target_zips = QLineEdit(", ".join(code for area in self.owner_strategy.get("target_territories", [])
                                                   if area["kind"] == "zip" for code in area["postal_codes"]))
        self.owner_target_state = QLineEdit(next((area["state"] for area in self.owner_strategy.get("target_territories", [])
                                                if area["kind"] == "zip"), ""))
        self.owner_target_zips.setPlaceholderText("Multiple desired US ZIPs, separated by commas; these are preferences")
        self.owner_target_state.setPlaceholderText("Two-letter state, for example CO")
        self.owner_territory_mode = QComboBox()
        self.owner_territory_mode.addItems(["Preferred areas", "Only these areas"])
        self.owner_territory_mode.setCurrentIndex(1 if self.owner_strategy.get("territory_mode") == "only" else 0)
        form.addRow("Desired US ZIPs", self.owner_target_zips)
        form.addRow("Desired ZIP state", self.owner_target_state)
        form.addRow("Territory preference", self.owner_territory_mode)
        self.owner_capacity = QComboBox()
        self.owner_capacity.addItem("Unknown / not confirmed", "unknown")
        self.owner_capacity.addItem("Can consider more customers", "available")
        self.owner_capacity.addItem("Cannot accept more customers now", "growth_constrained")
        self.owner_capacity.addItem("Defer growth work", "deferred")
        capacity = values("capacity")
        if self.owner_capacity.findData(capacity) >= 0:
            self.owner_capacity.setCurrentIndex(self.owner_capacity.findData(capacity))
        form.addRow("Confirmed capacity", self.owner_capacity)
        self.owner_provider_work = QLineEdit(values("provider_work"))
        self.owner_low_priority = QLineEdit(values("low_economic_priority"))
        self.owner_intentional_conditions = QLineEdit(values("intentional_condition"))
        self.owner_provider_work.setPlaceholderText("Services the current provider is already changing; comma-separated")
        self.owner_low_priority.setPlaceholderText("Services the owner says have low priority; no numeric margin inferred")
        self.owner_intentional_conditions.setPlaceholderText("Existing check names, for example indexable_sample or tap_to_call")
        form.addRow("Current provider work", self.owner_provider_work)
        form.addRow("Low economic priority", self.owner_low_priority)
        form.addRow("Intentional conditions", self.owner_intentional_conditions)
        self.owner_correction_reason = QLineEdit()
        self.owner_correction_reason.setPlaceholderText("Required when correcting a recorded strategy")
        form.addRow("Correction reason", self.owner_correction_reason)
        form.addRow(QLabel("Ambiguous statements need owner confirmation. Desired ZIPs do not establish measured source coverage."))
        for widget in (self.desired_services, self.excluded_services, self.owner_target_zips, self.owner_target_state,
                       self.owner_provider_work, self.owner_low_priority, self.owner_intentional_conditions, self.owner_correction_reason):
            widget.textEdited.connect(lambda _text: self.record_owner_preferences.setChecked(True))
        self.owner_wording.textChanged.connect(lambda: self.record_owner_preferences.setChecked(True))
        for combo in (self.owner_confirmation, self.owner_text_mode, self.owner_customer_type, self.owner_territory_mode, self.owner_capacity):
            combo.currentIndexChanged.connect(lambda _index: self.record_owner_preferences.setChecked(True))
        layout.addWidget(group)

    def _owner_preferences_payload(self) -> dict:
        wording = self.owner_wording.toPlainText().strip()
        facts = []
        previous = self.owner_strategy.get("constraints", [])

        def add(kind: str, value: str) -> None:
            original = next((fact["original_wording"] for fact in previous
                             if fact["kind"] == kind and fact["value"] == value), wording)
            fact = {"kind": kind, "value": value, "original_wording": original}
            # Preserve a previously recorded exact provider scope/page rather
            # than broadening it merely because this form shows service names.
            old: dict[str, Any] = next((item for item in previous if item["kind"] == kind and item["value"] == value), {})
            facts.append({**old, **fact})

        for kind, widget in (("desired_service", self.desired_services), ("excluded_service", self.excluded_services),
                             ("provider_work", self.owner_provider_work), ("low_economic_priority", self.owner_low_priority),
                             ("intentional_condition", self.owner_intentional_conditions)):
            for value in self._csv(widget.text()):
                add(kind, value)
        customers = self.owner_customer_type.currentText()
        if customers in {"Commercial only", "Residential only"}:
            desired = customers.split()[0].casefold()
            add("desired_customer_type", desired)
            add("excluded_customer_type", "residential" if desired == "commercial" else "commercial")
        elif customers == "Both":
            add("desired_customer_type", "commercial")
            add("desired_customer_type", "residential")
        if self.owner_capacity.currentData() != "unknown":
            add("capacity", self.owner_capacity.currentData())
        old_zip_areas = [area for area in self.owner_strategy.get("target_territories", []) if area["kind"] == "zip"]
        old_codes = {code for area in old_zip_areas for code in area["postal_codes"]}
        new_codes = set(self._csv(self.owner_target_zips.text()))
        if old_zip_areas and old_codes == new_codes and self.owner_target_state.text().strip().upper() == old_zip_areas[0]["state"]:
            areas = list(old_zip_areas)
        else:
            areas = [{"kind": "zip", "country": "US", "state": self.owner_target_state.text().strip().upper(),
                      "postal_codes": sorted(new_codes), "original_wording": wording}] if new_codes else []
        # This form edits US ZIP preferences only; other explicitly recorded
        # preference geometry remains in the corrected snapshot.
        areas.extend(area for area in self.owner_strategy.get("target_territories", []) if area["kind"] != "zip")
        return {"schema_version": 1, "constraints": facts, "target_territories": areas,
                "territory_mode": "only" if self.owner_territory_mode.currentIndex() else "preferred"}

    @staticmethod
    def _csv(text: str) -> list[str]:
        return [item.strip() for item in text.split(",") if item.strip()]

    def save(self) -> None:
        try:
            with self.session_factory() as session:
                interaction = save_contact_interaction(
                    session,
                    self.lead_id,
                    interaction_datetime=self.when.text().strip(),
                    method=self.method.currentText(),
                    direction=self.direction.currentText(),
                    outcome=self.outcome.currentText().strip(),
                    response_signals=[box.text() for box in self.signal_boxes if box.isChecked()],
                    objection=self.objection.currentText(),
                    notes=self.notes.toPlainText().strip(),
                    follow_up_date=self.follow_up.text().strip(),
                    outreach_draft_id=self.draft.currentData(),
                    interaction_id=self.interaction_id,
                    contact_name=self.contact_name.text().strip(),
                    contact_role=self.contact_role.text().strip(),
                    decision_maker_status=self.decision_status.currentText(),
                    business_goal=self.business_goal.text().strip(),
                    capacity_status=self.capacity.text().strip(),
                    buyer_questions=self._csv(self.buyer_questions.text()),
                    commitments=self._csv(self.commitments.text()),
                    branch_path=[item.strip() for item in self.branch_path.text().split(">") if item.strip()],
                    guided_call_identity=self.guided_call_identity,
                    guided_call_sequence=self.guided_call_sequence,
                    next_action=self.next_action.text().strip(),
                    **{key: box.isChecked() for key, box in self.credibility_boxes.items()},
                )
                if self.record_owner_preferences.isChecked():
                    lead = session.get(Lead, self.lead_id)
                    if lead is None:
                        raise ValueError("The business no longer exists.")
                    # A complete explicitly corrected snapshot can resolve all
                    # current conflicting records without deleting any of them.
                    targets = self.owner_strategy.get("current_assertion_ids", []) or [None]
                    for target_id in targets:
                        append_owner_strategy(
                            session, lead, self._owner_preferences_payload(),
                            source_text=self.owner_wording.toPlainText().strip(), source_text_mode=self.owner_text_mode.currentText(),
                            owner_confirmed=self.owner_confirmation.currentText() == "Owner explicitly confirmed",
                            interaction_id=interaction.id, supersedes_assertion_id=target_id,
                            correction_reason=self.owner_correction_reason.text().strip(),
                        )
                if self.config:
                    refresh_after_interaction_change(session, self.lead_id, self.config.sender)
                session.commit()
        except ValueError as exc:
            self.error.set_message(str(exc), "error")
            return
        self.accept()
