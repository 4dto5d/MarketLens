from __future__ import annotations

from copy import deepcopy
from typing import cast

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QSplitter, QVBoxLayout, QWidget
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import lead_contact_readiness_errors, list_contact_points
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.services.call_guide_service import CallBranch, CallFollowUp, CallGuideService, response_fingerprint
from local_presence_miner.services.outreach_planner import build_outreach_channel_plan
from local_presence_miner.ui.components import ActionToolbar, InfoBanner, SectionHeader
from local_presence_miner.ui.dialogs.contact_interaction_dialog import ContactInteractionDialog


class GuidedCallDialog(QDialog):
    def __init__(self, session_factory: sessionmaker[Session], lead_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sales Copilot")
        self.resize(1080, 760)
        self.setMinimumSize(900, 650)
        self.session_factory = session_factory
        self.lead_id = lead_id
        self.config = AppConfig.load()
        with session_factory() as session:
            lead = session.get(Lead, lead_id)
            if not lead:
                raise ValueError("Lead not found")
            competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead_id)).scalars())
            contacts = list_contact_points(session, lead_id)
            self.lead_name = lead.name
            self.lead_phone = lead.phone
            self.channel_plan = build_outreach_channel_plan(lead, contacts)
            self.guide = CallGuideService().build(session, lead, competitors)

        self.path: list[str] = []
        self.history: list[tuple[CallBranch | CallFollowUp | None, list[str], dict[str, object]]] = []
        self.current: CallBranch | CallFollowUp | None = None
        self.state: dict[str, object] = {}
        self._active_mode = "Practice Call"
        self._show_all = False
        self._rescue_text = ""
        self._spoken_response = ""
        self._current_reply_identity: dict[str, object] = {}
        self._guide_events: list[dict[str, object]] = []
        self._guide_sequence = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(8)
        root.addWidget(
            SectionHeader(
                f"Sales Copilot — {self.guide.business_name}",
                "Practice the flow or use it live. Keep replies natural; every click can become conversation memory.",
            )
        )

        top = ActionToolbar()
        self.mode = QComboBox()
        self.mode.addItems(["Practice Call", "Live Call"])
        top.layout.addWidget(self.mode)
        self.interaction_channel = QComboBox()
        self.interaction_channel.addItems(["Phone", "In person", "Other"])
        cast(QHBoxLayout, top.layout).addWidget(self.interaction_channel)
        self.length = QComboBox()
        self.length.addItems(["Quick", "Normal", "Detailed"])
        top.layout.addWidget(self.length)
        top.add_action("Back", self.go_back, role="tertiary")
        top.add_action("Refresh current plan", self.refresh_current_plan, role="secondary")
        top.add_action("Record Outcome", self.record_outcome, role="primary")
        top.add_action("Do Not Contact", self.do_not_contact, role="danger")
        root.addWidget(top)

        self.phase_label = QLabel(f"CALL PHASE · {self.guide.call_phase}")
        self.phase_label.setProperty("role", "metricLabel")
        root.addWidget(self.phase_label)

        if self.guide.research_only:
            root.addWidget(
                InfoBanner(
                    "Research first",
                    "This lead is Hold/Reject. Practice is available, but do not use a confident sales pitch "
                    "until qualification is resolved or manually overridden.",
                    "warning",
                )
            )
        else:
            root.addWidget(InfoBanner("Human-led call", "No dialing or AI voice. Use this as decision support; you control the conversation.", "info"))

        contact_text = f"Preferred route: {self.channel_plan.primary_channel}."
        if self.channel_plan.phone:
            contact_text += f" Phone: {self.channel_plan.phone}."
        if self.channel_plan.recipient:
            contact_text += f" Email: {self.channel_plan.recipient}."
        root.addWidget(InfoBanner("Contact route", contact_text, "success" if self.channel_plan.state == "Contactable" else "warning"))
        why_you_text = "\n".join(self.guide.why_you)
        if self.guide.do_not_claim:
            why_you_text += "\nDO NOT CLAIM: " + "; ".join(self.guide.do_not_claim[:2])
        root.addWidget(InfoBanner("WHY YOU", why_you_text, "info"))

        self.opening_choice = QComboBox()
        self.opening_choice.addItems(["15-second opening", "30-second opening", "Full opening"])
        self.opening_choice.currentIndexChanged.connect(self.show_opening)
        root.addWidget(self.opening_choice)
        self.opening = QPlainTextEdit()
        self.opening.setReadOnly(True)
        self.opening.setMaximumHeight(115)
        root.addWidget(self.opening)

        self.breadcrumb = QLabel("Opening")
        self.breadcrumb.setWordWrap(True)
        self.breadcrumb.setProperty("role", "sectionDescription")
        root.addWidget(self.breadcrumb)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.addWidget(SectionHeader("What did they say?", "Choose the closest meaning, not necessarily their exact words."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter responses: owner, provider, price, SEO, hosting...")
        self.search.textChanged.connect(self.render_root_branches)
        left_layout.addWidget(self.search)
        branch_tools = ActionToolbar()
        branch_tools.add_action("Search all", self.toggle_all_branches, role="tertiary")
        branch_tools.add_action("Other", lambda: self.show_branch("other"), role="tertiary")
        branch_tools.add_action("I don't know what they mean", lambda: self.show_branch("other"), role="tertiary")
        left_layout.addWidget(branch_tools)
        self.branch_box = QWidget()
        self.branch_layout = QVBoxLayout(self.branch_box)
        self.branch_layout.setContentsMargins(0, 0, 0, 0)
        self.branch_layout.setSpacing(5)
        self.branch_scroll = QScrollArea()
        self.branch_scroll.setWidgetResizable(True)
        self.branch_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.branch_scroll.setWidget(self.branch_box)
        left_layout.addWidget(self.branch_scroll, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(SectionHeader("Suggested reply", "Quick = one core line. Normal = full recommended reply. Detailed includes the next-step cue."))
        self.response = QPlainTextEdit()
        self.response.setReadOnly(True)
        right_layout.addWidget(self.response, 1)
        self.next_step = QLabel()
        self.next_step.setWordWrap(True)
        self.next_step.setProperty("role", "sectionDescription")
        right_layout.addWidget(self.next_step)
        self.followup_box = QWidget()
        self.followup_layout = QVBoxLayout(self.followup_box)
        self.followup_layout.setContentsMargins(0, 0, 0, 0)
        self.followup_layout.setSpacing(5)
        self.followup_scroll = QScrollArea()
        self.followup_scroll.setWidgetResizable(True)
        self.followup_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.followup_scroll.setMinimumHeight(100)
        self.followup_scroll.setMaximumHeight(230)
        self.followup_scroll.setWidget(self.followup_box)
        right_layout.addWidget(self.followup_scroll)
        rescue = ActionToolbar()
        rescue.add_action("Clarify", lambda: self.show_branch("other"), role="tertiary")
        rescue.add_action(
            "Ask a Question",
            lambda: self.rescue("What matters most to you about this right now?", "gc.rescue.ask_question"),
            role="tertiary",
        )
        rescue.add_action(
            "Send Info Instead",
            lambda: self.rescue(
                "No problem — I can send a short written summary of what I can verify. What’s the best email?",
                "gc.rescue.send_info",
            ),
            role="tertiary",
        )
        rescue.add_action("Wrong Person", lambda: self.show_branch("wrong_person"), role="tertiary")
        rescue.add_action(
            "I Need a Second",
            lambda: self.rescue("One second — I want to make sure I answer that accurately.", "gc.rescue.pause"),
            role="tertiary",
        )
        rescue.add_action(
            "Credibility Reset",
            lambda: self.rescue(
                "I don't want to overstate anything. Let me separate what I can verify from what I'm not sure about, and you can decide whether it's useful.",
                "gc.rescue.credibility_reset",
            ),
            role="tertiary",
        )
        rescue.add_action(
            "Wrap Up",
            lambda: self.rescue("Thanks for your time. I’ll keep the next step to what we actually agreed on.", "gc.rescue.wrap_up"),
            role="tertiary",
        )
        right_layout.addWidget(rescue)
        copy = ActionToolbar()
        self.copy_button = copy.add_action("Copy Current Reply", self.copy_reply, role="secondary", icon="copy")
        self.copy_button.setEnabled(False)
        self.used_button = copy.add_action("Mark Reply Used", self.mark_reply_used, role="secondary")
        self.used_button.setEnabled(False)
        right_layout.addWidget(copy)
        splitter.addWidget(right)
        splitter.setSizes([430, 650])
        root.addWidget(splitter, 1)

        self.mode.currentTextChanged.connect(self.enforce_mode)
        self.interaction_channel.currentTextChanged.connect(lambda _v: self.show_opening(self.opening_choice.currentIndex()))
        self.length.currentTextChanged.connect(lambda _v: self.render_current())
        self.show_opening(0)
        self.render_root_branches()
        self.reset_call_session("Practice Call")
        self.enforce_mode(self.mode.currentText())

    def enforce_mode(self, mode: str) -> None:
        if mode == "Live Call" and self.guide.research_only:
            self.mode.blockSignals(True)
            self.mode.setCurrentText("Practice Call")
            self.mode.blockSignals(False)
            mode = "Practice Call"
        if mode == "Live Call" and not self._live_contact_allowed():
            self.mode.blockSignals(True)
            self.mode.setCurrentText("Practice Call")
            self.mode.blockSignals(False)
            self.response.setPlainText("Live Call blocked: this lead is currently suppressed or otherwise not contactable.")
            mode = "Practice Call"
        if mode == "Live Call" and not self._commercial_guidance_current():
            self.mode.blockSignals(True)
            self.mode.setCurrentText("Practice Call")
            self.mode.blockSignals(False)
            self.response.setPlainText("Live Call blocked: commercial guidance is stale. Select Refresh current plan before using pricing or current replies.")
            mode = "Practice Call"
        if mode != self._active_mode:
            self.reset_call_session(mode)

    def reset_call_session(self, mode: str | None = None) -> None:
        self._active_mode = mode or self.mode.currentText()
        self.path = []
        self.history = []
        self.current = None
        self.state = {}
        self._show_all = False
        self._rescue_text = ""
        self._guide_events = []
        self._guide_sequence = 0
        self._clear_current_reply()
        self.phase_label.setText(f"CALL PHASE · {self.guide.call_phase}")
        self.breadcrumb.setText("Opening")
        self.response.setPlainText(
            "Practice: choose a response to rehearse the next move."
            if self._active_mode == "Practice Call"
            else "Live Call ready. No prospect response is recorded until you choose what they actually said."
        )
        self.next_step.setText("")
        self.clear_layout(self.followup_layout)

    def show_opening(self, index: int) -> None:
        values = [self.guide.opening_15s, self.guide.opening_30s, self.guide.full_opening]
        channel = self.interaction_channel.currentText()
        if channel == "In person":
            values = [
                self.guide.in_person_opening_15s or self.guide.opening_15s,
                self.guide.in_person_opening_30s or self.guide.opening_30s,
                self.guide.in_person_full_opening or self.guide.full_opening,
            ]
        elif channel == "Other":
            values = [
                self.guide.other_opening_15s or self.guide.opening_15s,
                self.guide.other_opening_30s or self.guide.opening_30s,
                self.guide.other_full_opening or self.guide.full_opening,
            ]
        self.opening.setPlainText(values[max(0, min(index, 2))])

    def clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def render_root_branches(self) -> None:
        self.clear_layout(self.branch_layout)
        needle = self.search.text().strip().casefold() if hasattr(self, "search") else ""
        visible = self.guide.branches
        if not needle and not self._show_all:
            keys = set(self.guide.initial_branch_keys)
            visible = tuple(branch for branch in visible if branch.key in keys)
        for branch in visible:
            if needle and needle not in self._branch_search_text(branch):
                continue
            actions = ActionToolbar()
            actions.add_action(branch.label, lambda _checked=False, key=branch.key: self.show_branch(key), role="secondary")
            self.branch_layout.addWidget(actions)

    def toggle_all_branches(self) -> None:
        self._show_all = not self._show_all
        self.render_root_branches()

    @staticmethod
    def _branch_search_text(branch) -> str:
        """Search branch descendants too, so a buried follow-up remains reachable."""
        pieces = [branch.key, branch.label, branch.response, branch.quick_response, branch.next_prompt]

        def add_followups(items) -> None:
            for item in items:
                pieces.extend((item.label, item.response, item.quick_response, item.next_prompt))
                add_followups(item.followups)

        add_followups(branch.followups)
        return " ".join(str(item) for item in pieces if item).casefold()

    def apply_updates(self, updates: dict[str, object]) -> None:
        for key, value in updates.items():
            if isinstance(value, list):
                existing = list(self.state.get(key, []) or [])
                for item in value:
                    if item not in existing:
                        existing.append(item)
                self.state[key] = existing
            elif value not in (None, ""):
                self.state[key] = value

    def show_branch(self, key: str) -> None:
        branch = next((item for item in self.guide.branches if item.key == key), None)
        if not branch:
            return
        self.history.append((self.current, list(self.path), deepcopy(self.state)))
        self.current = branch
        self.path = [branch.label]
        self._rescue_text = ""
        self.apply_updates(branch.state_updates)
        self.state["call_phase"] = self._phase_for_key(key)
        self.render_current()

    def show_followup(self, followup) -> None:
        self.history.append((self.current, list(self.path), deepcopy(self.state)))
        self.current = followup
        self.path.append(followup.label)
        self._rescue_text = ""
        self.apply_updates(followup.state_updates)
        self.render_current()

    def render_current(self) -> None:
        if self.current is None:
            return
        response = self._rescue_text or self.current.response
        mode = self.length.currentText()
        if mode == "Quick" and not self._rescue_text:
            # A missing authored quick reply intentionally falls back to the
            # complete spoken reply; it is never meaning-changing truncation.
            response = self.current.quick_response or self.current.response
        # Next-step/coaching stays in the separate internal surface below.  It
        # is never concatenated into owner-facing/copyable spoken wording.
        self._spoken_response = response
        self.response.setPlainText(response)
        self._set_current_reply_identity(response)
        self._update_copy_button()
        self.next_step.setText(("NEXT: " + self.current.next_prompt) if self.current.next_prompt else "")
        self.phase_label.setText(f"CALL PHASE · {self.state.get('call_phase', self.guide.call_phase)}")
        self.breadcrumb.setText("Opening > " + " > ".join(self.path) if self.path else "Opening")
        self.clear_layout(self.followup_layout)
        if self.current.followups:
            label = QLabel("THEN IF THEY SAY…")
            label.setProperty("role", "sectionDescription")
            self.followup_layout.addWidget(label)
            for followup in self.current.followups:
                actions = ActionToolbar()
                actions.add_action(followup.label, lambda _checked=False, item=followup: self.show_followup(item), role="tertiary")
                self.followup_layout.addWidget(actions)

    def go_back(self) -> None:
        if not self.history:
            return
        self.current, self.path, self.state = self.history.pop()
        if self.current is None:
            self._rescue_text = ""
            self._clear_current_reply()
            self.breadcrumb.setText("Opening")
            self.response.setPlainText(
                "Practice: choose a response to rehearse the next move."
                if self._active_mode == "Practice Call"
                else "Live Call ready. No prospect response is recorded until you choose what they actually said."
            )
            self.next_step.setText("")
            self.phase_label.setText(f"CALL PHASE · {self.guide.call_phase}")
            self.clear_layout(self.followup_layout)
        else:
            self.render_current()

    def rescue(self, text: str, rescue_id: str = "gc.rescue.custom") -> None:
        self._rescue_text = text
        self._spoken_response = text
        self.response.setPlainText(text)
        selected_node_id = str(getattr(self.current, "node_id", "") or "")
        tree_id = str(getattr(self.guide, "tree_id", "") or "")
        tree_version = str(getattr(self.guide, "tree_version", "") or "")
        self._current_reply_identity = {
            "schema_version": 1,
            "tree_id": tree_id,
            "tree_version": tree_version,
            "recommended_node_id": rescue_id,
            "selected_node_id": selected_node_id,
            "strategy_id": "gc.strategy.rescue",
            "response_version": 1,
            "response_fingerprint": response_fingerprint(
                tree_id=tree_id,
                tree_version=tree_version,
                node_id=rescue_id,
                response_version=1,
                response=text,
            ),
            "response_snapshot": text,
            "usage_state": "displayed",
            "rescue_id": rescue_id,
        }
        self._append_guide_event("rescue_displayed")
        self._update_copy_button()
        self.next_step.setText("RESCUE: stabilize the conversation, then choose the closest branch.")

    @staticmethod
    def _phase_for_key(key: str) -> str:
        if key in {"who_are_you", "how_found", "what_about", "how_number"}:
            return "IDENTITY / RELEVANCE"
        if key in {"experience", "credibility", "ai_skepticism", "why_you"}:
            return "LEGITIMACY / EVIDENCE"
        if key in {"price", "too_expensive"}:
            return "PRICE / OBJECTIONS"
        if key in {"interested", "send_info"}:
            return "EVIDENCE / NEXT ACTION"
        return "DISCOVERY / OBJECTIONS"

    def copy_reply(self) -> None:
        if not self._live_contact_allowed():
            self._clear_copyable_reply()
            self.response.setPlainText("Copy blocked: this lead is not currently eligible for commercial contact/use.")
            return
        if not self._commercial_guidance_current():
            self._clear_copyable_reply()
            self.response.setPlainText("Copy blocked: commercial guidance is stale. Refresh current plan before copying a current reply.")
            return
        text, reason = self._copyable_reply_text()
        if not text:
            self._clear_copyable_reply()
            self.response.setPlainText(reason)
            return
        QGuiApplication.clipboard().setText(text)
        self._record_reply_usage("copied")

    def mark_reply_used(self) -> None:
        if self.mode.currentText() != "Live Call":
            self.response.setPlainText("Practice only: a reply can be marked used only during a Live Call.")
            return
        if not self._live_contact_allowed():
            self.response.setPlainText("Use blocked: this lead is not currently eligible for commercial contact/use.")
            return
        if not self._commercial_guidance_current():
            self.response.setPlainText("Use blocked: commercial guidance is stale. Refresh current plan before using a current reply.")
            return
        text, reason = self._reply_text_for_usage("spoken")
        if not text:
            self.response.setPlainText(reason)
            return
        self._record_reply_usage("used")
        self.next_step.setText("Recorded: this exact reply was actually used in the live interaction.")

    def _copyable_reply_text(self) -> tuple[str, str]:
        return self._reply_text_for_usage("copied")

    def _reply_text_for_usage(self, usage: str) -> tuple[str, str]:
        text = self._spoken_response.strip()
        if not text or (self.current is None and not self._rescue_text):
            return "", "Copy blocked: there is no current owner-facing reply to copy."
        visible = self.response.toPlainText().strip()
        if visible != text:
            return "", "Copy blocked: the visible reply is no longer the current owner-facing reply."
        identity = getattr(self, "_current_reply_identity", {})
        if not identity or identity.get("response_snapshot") != text:
            return "", "Use blocked: the current reply has no matching durable identity."
        expected_fingerprint = response_fingerprint(
            tree_id=str(identity.get("tree_id") or ""),
            tree_version=str(identity.get("tree_version") or ""),
            node_id=str(identity.get("recommended_node_id") or ""),
            response_version=int(identity.get("response_version") or 0),
            response=text,
        )
        if identity.get("response_fingerprint") != expected_fingerprint:
            return "", "Use blocked: the current reply identity does not match its visible text."
        spoken_claims = getattr(self.guide, "owner_spoken_claims", ())
        copied_claims = getattr(self.guide, "owner_copied_claims", ())
        allowed_claims = copied_claims if usage == "copied" else spoken_claims
        allowed = {claim.casefold() for claim in allowed_claims if claim}
        evidence_claims = getattr(self.guide, "evidence_claims", spoken_claims)
        restricted_claims = {
            claim.casefold() for claim in evidence_claims if claim and claim.casefold() not in allowed
        }
        if any(claim in text.casefold() for claim in restricted_claims):
            boundary = "copied" if usage == "copied" else "spoken"
            return "", f"Use blocked: the current reply contains evidence not approved for owner-{boundary} use."
        return text, ""

    def _clear_copyable_reply(self) -> None:
        self._spoken_response = ""
        button = getattr(self, "copy_button", None)
        if button is not None:
            button.setEnabled(False)

    def _clear_current_reply(self) -> None:
        self._clear_copyable_reply()
        self._current_reply_identity = {}
        button = getattr(self, "used_button", None)
        if button is not None:
            button.setEnabled(False)

    def _update_copy_button(self) -> None:
        button = getattr(self, "copy_button", None)
        if button is not None:
            text, _reason = self._copyable_reply_text()
            button.setEnabled(bool(text))
        used_button = getattr(self, "used_button", None)
        if used_button is not None:
            text, _reason = self._reply_text_for_usage("spoken")
            used_button.setEnabled(bool(text))

    def _set_current_reply_identity(self, response: str) -> None:
        node_id = str(getattr(self.current, "node_id", "") or "")
        strategy_id = str(getattr(self.current, "strategy_id", "") or "")
        tree_id = str(getattr(self.guide, "tree_id", "") or "")
        tree_version = str(getattr(self.guide, "tree_version", "") or "")
        if not node_id or not strategy_id or not tree_id or not tree_version:
            self._current_reply_identity = {}
            return
        response_version = int(getattr(self.current, "response_version", 1) or 1)
        self._current_reply_identity = {
            "schema_version": 1,
            "tree_id": tree_id,
            "tree_version": tree_version,
            "recommended_node_id": node_id,
            "selected_node_id": node_id,
            "strategy_id": strategy_id,
            "response_version": response_version,
            "response_fingerprint": response_fingerprint(
                tree_id=tree_id,
                tree_version=tree_version,
                node_id=node_id,
                response_version=response_version,
                response=response,
            ),
            "response_snapshot": response,
            "usage_state": "displayed",
            "rescue_id": "",
        }
        self._append_guide_event("reply_displayed")

    def _record_reply_usage(self, usage_state: str) -> None:
        if not getattr(self, "_current_reply_identity", {}):
            return
        self._current_reply_identity = {**self._current_reply_identity, "usage_state": usage_state}
        self._append_guide_event(f"reply_{usage_state}")

    def _append_guide_event(self, event: str) -> None:
        if not self._current_reply_identity:
            return
        self._guide_sequence = int(getattr(self, "_guide_sequence", 0)) + 1
        events = getattr(self, "_guide_events", None)
        if events is None:
            events = []
            self._guide_events = events
        events.append({**self._current_reply_identity, "event": event, "sequence": self._guide_sequence})

    def refresh_current_plan(self, quiet: bool = False) -> None:
        """Refresh commercial guidance without erasing factual conversation state."""
        current_path = list(self.path)
        current_node_id = str(getattr(self.current, "node_id", "") or "")
        history_snapshot = [
            (str(getattr(node, "node_id", "") or ""), list(path), deepcopy(state))
            for node, path, state in self.history
        ]
        current_state = deepcopy(self.state)
        rescue_text = self._rescue_text
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead is None:
                return
            competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == self.lead_id)).scalars())
            self.guide = CallGuideService().build(session, lead, competitors)
        self.path = current_path
        self.state = current_state
        self._rescue_text = rescue_text
        self.current = self._node_for_id(current_node_id) if current_node_id else self._node_for_path(current_path)
        self.history = [
            ((self._node_for_id(node_id) if node_id else self._node_for_path(path)), path, state)
            for node_id, path, state in history_snapshot
        ]
        self.show_opening(self.opening_choice.currentIndex())
        self.render_root_branches()
        if self.current is not None:
            self.render_current()
            if not quiet:
                self.next_step.setText("Commercial guidance refreshed. Existing conversation history and captured state were preserved.")
            return

        self._rescue_text = ""
        self._clear_current_reply()
        self.breadcrumb.setText("Opening" if not self.path else "Opening > " + " > ".join(self.path))
        self.phase_label.setText(f"CALL PHASE · {self.state.get('call_phase', self.guide.call_phase)}")
        self.clear_layout(self.followup_layout)
        if self.path:
            self.response.setPlainText(
                "The previous response path is no longer available in the refreshed guide. "
                "Captured conversation facts were preserved; choose the closest current branch before using or copying guidance."
            )
        else:
            self.response.setPlainText(
                "Practice: choose a response to rehearse the next move."
                if self._active_mode == "Practice Call"
                else "Live Call ready. No prospect response is recorded until you choose what they actually said."
            )
        self.next_step.setText(
            "Commercial guidance refreshed. Existing conversation history and captured state were preserved." if not quiet else ""
        )

    def _node_for_path(self, path: list[str]) -> CallBranch | CallFollowUp | None:
        if not path:
            return None
        current: CallBranch | CallFollowUp | None = next(
            (item for item in self.guide.branches if item.label == path[0]), None
        )
        if current is None:
            return None
        for label in path[1:]:
            current = next((item for item in current.followups if item.label == label), None)
            if current is None:
                return None
        return current

    def _node_for_id(self, node_id: str) -> CallBranch | CallFollowUp | None:
        pending: list[CallBranch | CallFollowUp] = list(self.guide.branches)
        while pending:
            item = pending.pop()
            if item.node_id == node_id:
                return item
            pending.extend(item.followups)
        return None

    def record_outcome(self) -> None:
        if self.mode.currentText() == "Practice Call":
            self.response.setPlainText("Practice only: outcomes are not written to the CRM. Switch to Live Call to record a real conversation.")
            return
        if not self._live_contact_allowed():
            self.response.setPlainText("Live Call blocked: this lead is currently suppressed or otherwise not contactable.")
            return
        # Factual interaction capture is independent from recommendation
        # freshness. Stale guidance still cannot be copied or used for current
        # pricing, but it must not prevent preserving what actually happened.
        defaults = deepcopy(self.state)
        defaults.setdefault("outcome", "")
        defaults["branch_path"] = list(self.path)
        defaults["guided_call_identity"] = deepcopy(getattr(self, "_current_reply_identity", {}))
        defaults["guided_call_sequence"] = deepcopy(getattr(self, "_guide_events", []))
        defaults.setdefault("notes", "Guided Call path: " + " > ".join(self.path))
        ContactInteractionDialog(
            self.session_factory,
            self.lead_id,
            parent=self,
            default_method=self.interaction_channel.currentText(),
            defaults=defaults,
            config=self.config,
        ).exec()

    def do_not_contact(self) -> None:
        if self.mode.currentText() == "Practice Call":
            self.response.setPlainText("Practice only: this would suppress the lead in Live Call mode.")
            return
        # A DNC must be an explicit, operator-confirmed outcome.  Saving this
        # dialog records the interaction and invokes the same canonical DNC
        # transition as the ordinary outcome route in a single transaction.
        defaults = deepcopy(self.state)
        defaults.update(
            {
                "outcome": "Do not contact me again",
                "next_action": "Do Not Contact",
                "branch_path": list(self.path),
                "guided_call_identity": deepcopy(getattr(self, "_current_reply_identity", {})),
                "guided_call_sequence": deepcopy(getattr(self, "_guide_events", [])),
            }
        )
        defaults.setdefault("notes", "Guided Call DNC path: " + " > ".join(self.path))
        ContactInteractionDialog(
            self.session_factory,
            self.lead_id,
            parent=self,
            default_method=self.interaction_channel.currentText(),
            defaults=defaults,
            config=self.config,
        ).exec()

    def _live_contact_allowed(self) -> bool:
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            return lead is not None and not lead_contact_readiness_errors(session, lead)

    def _commercial_guidance_current(self) -> bool:
        """Open guides are snapshots: compare their commercial fingerprint at use boundaries."""
        with self.session_factory() as session:
            lead = session.get(Lead, self.lead_id)
            if lead is None:
                return False
            competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == self.lead_id)).scalars())
            fresh = CallGuideService().build(session, lead, competitors)
            return bool(
                self.guide.commercial_dependency_fingerprint
                and self.guide.commercial_dependency_fingerprint == fresh.commercial_dependency_fingerprint
            )
