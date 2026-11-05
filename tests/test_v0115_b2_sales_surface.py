from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import local_presence_miner.database.repositories as repository_module
import local_presence_miner.ui.dialogs.guided_call_dialog as guided_call_module
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    is_suppressed,
    list_contact_interactions,
    save_audit,
    save_contact_interaction,
)
from local_presence_miner.database.schema import GooglePresenceAssessment, Lead, WebsiteAuditRecord
from local_presence_miner.services.call_guide_service import (
    CallBranch,
    CallFollowUp,
    CallGuide,
    CallGuideService,
)
from local_presence_miner.services.commercial_plan_service import build_current_offer_context
from local_presence_miner.services.conversation_state_service import (
    SUBJECT_OBJECTION,
    ConversationStateService,
)
from local_presence_miner.services.sales_evidence_service import (
    USAGE_INTERNAL_GUIDANCE,
    USAGE_OWNER_COPIED,
    USAGE_OWNER_SPOKEN,
    SalesEvidenceService,
)
from local_presence_miner.ui.dialogs.guided_call_dialog import GuidedCallDialog


def _factory(tmp_path):
    factory = create_session_factory(tmp_path / "b2-sales-surface.sqlite3")
    initialize_database(factory)
    return factory


def _lead() -> Lead:
    return Lead(
        place_id="b2-sales-surface",
        name="B2 Roofing",
        category="roofers",
        phone="555-010-2000",
        website="https://example.test",
        qualification_class="Qualified",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Qualified","confidence":"Strong"}',
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        offer_resolution_state="canonical_id",
    )


def test_b2_evidence_contract_fails_closed_then_allows_only_verified_bounded_claim(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        session.add(
            WebsiteAuditRecord(
                lead_id=lead.id,
                url=lead.website,
                final_url=lead.website,
                reachable=True,
                weaknesses_json='["The public contact path is hard to find."]',
                evidence_json='{"contact_path":"https://example.test/contact"}',
            )
        )
        session.flush()

        unverified = SalesEvidenceService().build(session, lead)
        assert unverified.for_usage(USAGE_OWNER_SPOKEN) == ()
        assert unverified.for_usage(USAGE_OWNER_COPIED) == ()
        assert len(unverified.for_usage(USAGE_INTERNAL_GUIDANCE)) == 1
        assert unverified.findings[0].verification_state == "REVIEW_REQUIRED"

        lead.verification_json = '{"audit_claims": true}'
        verified = SalesEvidenceService().build(session, lead)
        owner_finding = verified.for_usage(USAGE_OWNER_SPOKEN)[0]
        assert owner_finding.claim == "The public contact path is hard to find."
        assert owner_finding.source_identity == "https://example.test"
        assert owner_finding.observed_at != ""
        assert owner_finding.freshness == "OBSERVED"
        assert owner_finding.allowed_usages == (USAGE_INTERNAL_GUIDANCE, USAGE_OWNER_SPOKEN, USAGE_OWNER_COPIED)


def test_b2_current_assertion_identity_is_a_commercial_plan_dependency(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()

        before, _ = build_current_offer_context(session, lead, competitors=[])
        ConversationStateService().append_assertion(
            session,
            lead,
            subject_key=SUBJECT_OBJECTION,
            value="Too expensive",
        )
        after, _ = build_current_offer_context(session, lead, competitors=[])

        assert before.planning_input_fingerprint != after.planning_input_fingerprint
        assert after.planning_inputs["conversation"]["objections"] == ["Too expensive"]
        assert after.planning_inputs["conversation"]["assertion_revision"] > 0
        assert after.planning_inputs["commercial_disposition"]["value"] == "UNKNOWN"
        assert after.planning_inputs["sales_evidence"] == []


def test_b2_branch_models_keep_authored_quick_copy_and_descendant_text() -> None:
    followup = CallFollowUp(
        "I do not understand",
        "That is on me. Let me put it plainly.",
        quick_response="That is on me. Let me put it plainly.",
    )
    branch = CallBranch(
        "price",
        "That is too expensive",
        "Before we change the price, let us separate budget from value.",
        followups=(followup,),
        quick_response="Is the concern budget, scope, or value?",
    )

    assert branch.quick_response == "Is the concern budget, scope, or value?"
    assert branch.followups[0].quick_response == branch.followups[0].response
    # The dialog search walks this nested response rather than only root labels.
    assert "understand" in GuidedCallDialog._branch_search_text(branch)


def test_b2_live_dnc_requires_a_confirmed_manual_outcome(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Choice:
        def __init__(self, value: str) -> None:
            self.value = value

        def currentText(self) -> str:
            return self.value

    class _OutcomeDialog:
        def __init__(self, *args, **kwargs) -> None:
            captured["args"] = args
            captured["kwargs"] = kwargs

        def exec(self) -> int:
            captured["executed"] = True
            return 0

    monkeypatch.setattr(guided_call_module, "ContactInteractionDialog", _OutcomeDialog)
    dialog = GuidedCallDialog.__new__(GuidedCallDialog)
    dialog.mode = _Choice("Live Call")
    dialog.interaction_channel = _Choice("In person")
    dialog.state = {"objections": ["Value uncertainty"]}
    dialog.path = ["I need to think about it", "I’m not sure it would matter"]
    dialog.session_factory = object()
    dialog.lead_id = 7
    dialog.config = None

    dialog.do_not_contact()

    defaults = captured["kwargs"]["defaults"]
    assert captured["kwargs"]["default_method"] == "In person"
    assert defaults["outcome"] == "Do not contact me again"
    assert defaults["next_action"] == "Do Not Contact"
    assert defaults["branch_path"] == dialog.path
    assert captured["executed"] is True


def test_b2_owner_copy_excludes_internal_send_guidance_and_in_person_opening_is_distinct(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()

        guide = CallGuideService().build(session, lead, [])

    owner_surface = "\n".join(
        (
            guide.opening_15s,
            guide.opening_30s,
            guide.full_opening,
            guide.in_person_opening_15s,
            guide.in_person_opening_30s,
            guide.in_person_full_opening,
            *(branch.response for branch in guide.branches),
        )
    )
    assert "SEND:" not in owner_surface
    assert "DO NOT SEND" not in owner_surface
    assert guide.in_person_opening_30s != guide.opening_30s
    assert "[your name]" in guide.in_person_opening_30s


def test_b2_explicit_manual_dnc_writes_interaction_and_suppression_together(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()

        interaction = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-09-11T12:30:00Z",
            method="In person",
            direction="Outbound",
            outcome="Do not contact me again",
            notes="Confirmed in the manual outcome dialog.",
            next_action="Do Not Contact",
        )
        session.flush()

        assert interaction.id is not None
        assert [item.id for item in list_contact_interactions(session, lead.id)] == [interaction.id]
        assert session.get(Lead, lead.id).suppressed is True
        assert is_suppressed(session, lead)


def test_b2_website_evidence_requires_current_age_and_preserves_google_stale_semantics(tmp_path) -> None:
    now = datetime(2026, 9, 11, 18, 0, tzinfo=UTC)
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        lead.verification_json = '{"audit_claims": true, "google_presence": true}'
        session.add(lead)
        session.flush()
        audit = WebsiteAuditRecord(
            lead_id=lead.id,
            url=lead.website,
            final_url=lead.website,
            reachable=True,
            weaknesses_json='["The public contact path is hard to find."]',
            evidence_json='{"contact_path":"https://example.test/contact"}',
            created_at=(now - timedelta(days=1)).replace(tzinfo=None),
        )
        session.add(audit)
        session.flush()

        current = SalesEvidenceService().build(session, lead, now=now)
        website = current.findings[0]
        assert website.freshness == "OBSERVED"
        assert website.allowed_usages == (USAGE_INTERNAL_GUIDANCE, USAGE_OWNER_SPOKEN, USAGE_OWNER_COPIED)

        audit.created_at = (now - timedelta(days=31)).replace(tzinfo=None)
        stale = SalesEvidenceService().build(session, lead, now=now).findings[0]
        assert stale.freshness == "STALE"
        assert stale.allowed_usages == (USAGE_INTERNAL_GUIDANCE,)

        audit.created_at = (now - timedelta(hours=1)).replace(tzinfo=None)
        audit.reachable = False
        failed_refresh = SalesEvidenceService().build(session, lead, now=now).findings[0]
        assert failed_refresh.freshness == "UNKNOWN"
        assert failed_refresh.allowed_usages == (USAGE_INTERNAL_GUIDANCE,)

        session.add(
            GooglePresenceAssessment(
                lead_id=lead.id,
                confidence="High",
                observed_gaps_json='["Business hours were not observed."]',
                generated_at=(now - timedelta(days=1)).replace(tzinfo=None),
            )
        )
        lead.google_rich_data_stale = True
        session.flush()
        findings = SalesEvidenceService().build(session, lead, now=now).findings
        google = next(item for item in findings if item.source_identity == "Google public presence assessment")
        assert google.freshness == "STALE"
        assert google.allowed_usages == (USAGE_INTERNAL_GUIDANCE,)


def test_b2_refresh_preserves_conversation_memory_and_rebinds_fresh_guidance(tmp_path, monkeypatch) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.commit()
        lead_id = lead.id

    old_followup = CallFollowUp("Budget concern", "Old follow-up response")
    old_branch = CallBranch("price", "That is too expensive", "Old response", followups=(old_followup,))
    new_followup = CallFollowUp("Budget concern", "Fresh follow-up response")
    new_branch = CallBranch("price", "That is too expensive", "Fresh response", followups=(new_followup,))
    new_guide = CallGuide(
        "B2 Roofing",
        "phone 15",
        "phone 30",
        "phone full",
        "lead",
        "price",
        (new_branch,),
        commercial_dependency_fingerprint="fresh-snapshot",
    )

    class _GuideService:
        def build(self, session, lead, competitors):
            return new_guide

    class _Index:
        def currentIndex(self) -> int:
            return 0

    class _Text:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def setText(self, value: str) -> None:
            self.value = value

        def setPlainText(self, value: str) -> None:
            self.value = value

        def toPlainText(self) -> str:
            return self.value

    class _Choice:
        def currentText(self) -> str:
            return "Other"

    monkeypatch.setattr(guided_call_module, "CallGuideService", _GuideService)
    dialog = GuidedCallDialog.__new__(GuidedCallDialog)
    dialog.session_factory = factory
    dialog.lead_id = lead_id
    dialog.guide = SimpleNamespace(call_phase="OLD")
    dialog.current = old_followup
    dialog.path = ["That is too expensive", "Budget concern"]
    dialog.history = [(old_branch, ["That is too expensive"], {"objections": ["Earlier concern"]})]
    dialog.state = {
        "objections": ["Too expensive"],
        "business_goal": "More booked work",
        "prospect_responses": ["Budget is tight"],
        "call_phase": "PRICE / OBJECTIONS",
    }
    dialog._active_mode = "Live Call"
    dialog._rescue_text = ""
    dialog._spoken_response = "Old follow-up response"
    dialog.interaction_channel = _Choice()
    dialog.opening_choice = _Index()
    dialog.response = _Text("Old follow-up response")
    dialog.next_step = _Text()
    dialog.phase_label = _Text()
    dialog.breadcrumb = _Text()
    dialog.copy_button = SimpleNamespace(setEnabled=lambda _enabled: None)
    dialog.followup_layout = object()
    dialog.show_opening = lambda _index: None
    dialog.render_root_branches = lambda: None
    dialog.clear_layout = lambda _layout: None

    def render_current() -> None:
        dialog._spoken_response = dialog.current.response
        dialog.response.setPlainText(dialog.current.response)

    dialog.render_current = render_current

    dialog.refresh_current_plan()

    assert dialog.guide.commercial_dependency_fingerprint == "fresh-snapshot"
    assert dialog.path == ["That is too expensive", "Budget concern"]
    assert dialog.state["objections"] == ["Too expensive"]
    assert dialog.state["business_goal"] == "More booked work"
    assert dialog.state["prospect_responses"] == ["Budget is tight"]
    assert dialog.current is new_followup
    assert dialog.history[0][0] is new_branch
    assert dialog.history[0][1] == ["That is too expensive"]
    assert dialog.history[0][2]["objections"] == ["Earlier concern"]
    assert dialog.response.toPlainText() == "Fresh follow-up response"
    assert dialog.interaction_channel.currentText() == "Other"


def test_b2_factual_outcome_capture_is_not_blocked_by_stale_guidance(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Choice:
        def __init__(self, value: str) -> None:
            self.value = value

        def currentText(self) -> str:
            return self.value

    class _OutcomeDialog:
        def __init__(self, *args, **kwargs) -> None:
            captured["kwargs"] = kwargs

        def exec(self) -> int:
            captured["executed"] = True
            return 0

    monkeypatch.setattr(guided_call_module, "ContactInteractionDialog", _OutcomeDialog)
    dialog = GuidedCallDialog.__new__(GuidedCallDialog)
    dialog.mode = _Choice("Live Call")
    dialog.interaction_channel = _Choice("Phone")
    dialog.state = {"objections": ["Too expensive"], "business_goal": "More booked work"}
    dialog.path = ["That is too expensive"]
    dialog.session_factory = object()
    dialog.lead_id = 7
    dialog.config = None
    dialog._live_contact_allowed = lambda: True
    dialog._commercial_guidance_current = lambda: False

    dialog.record_outcome()

    defaults = captured["kwargs"]["defaults"]
    assert captured["executed"] is True
    assert defaults["outcome"] == ""
    assert defaults["objections"] == ["Too expensive"]
    assert defaults["business_goal"] == "More booked work"
    assert defaults["branch_path"] == ["That is too expensive"]


def test_b2_copy_boundary_tracks_visible_reply_and_enforces_copied_usage(monkeypatch) -> None:
    class _Text:
        def __init__(self, value: str) -> None:
            self.value = value

        def setPlainText(self, value: str) -> None:
            self.value = value

        def toPlainText(self) -> str:
            return self.value

    class _Button:
        def __init__(self) -> None:
            self.enabled = False

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

    class _Clipboard:
        def __init__(self) -> None:
            self.values: list[str] = []

        def setText(self, value: str) -> None:
            self.values.append(value)

    clipboard = _Clipboard()
    monkeypatch.setattr(guided_call_module, "QGuiApplication", SimpleNamespace(clipboard=lambda: clipboard))
    dialog = GuidedCallDialog.__new__(GuidedCallDialog)
    dialog.current = CallBranch(
        "spoken-only",
        "Spoken only",
        "I noticed a spoken-only public observation.",
        node_id="gc.spoken-only",
        strategy_id="gc.strategy.spoken-only",
    )
    dialog._rescue_text = ""
    dialog._spoken_response = "I noticed a spoken-only public observation."
    dialog.response = _Text(dialog._spoken_response)
    dialog.copy_button = _Button()
    dialog._current_reply_identity = {}
    dialog._guide_events = []
    dialog._guide_sequence = 0
    dialog.guide = SimpleNamespace(
        tree_id="marketlens-guided-call",
        tree_version="test-v1",
        evidence_claims=("spoken-only public observation",),
        owner_spoken_claims=("spoken-only public observation",),
        owner_copied_claims=(),
    )
    dialog._live_contact_allowed = lambda: True
    dialog._commercial_guidance_current = lambda: True
    dialog._set_current_reply_identity(dialog._spoken_response)

    dialog._update_copy_button()
    assert dialog.copy_button.enabled is False
    dialog.copy_reply()
    assert clipboard.values == []

    dialog.current = CallBranch(
        "legitimate",
        "Legitimate",
        "First legitimate reply",
        node_id="gc.legitimate",
        strategy_id="gc.strategy.legitimate",
    )
    dialog._spoken_response = "First legitimate reply"
    dialog.response.setPlainText("First legitimate reply")
    dialog.guide = SimpleNamespace(
        tree_id="marketlens-guided-call",
        tree_version="test-v1",
        evidence_claims=(),
        owner_spoken_claims=(),
        owner_copied_claims=(),
    )
    dialog._set_current_reply_identity(dialog._spoken_response)
    dialog._update_copy_button()
    assert dialog.copy_button.enabled is True
    dialog.copy_reply()
    assert clipboard.values[-1] == "First legitimate reply"

    dialog._spoken_response = "Second legitimate reply"
    dialog.response.setPlainText("Second legitimate reply")
    dialog._set_current_reply_identity(dialog._spoken_response)
    dialog._update_copy_button()
    dialog.copy_reply()
    assert clipboard.values[-1] == "Second legitimate reply"

    dialog._spoken_response = "Stale hidden reply"
    dialog.response.setPlainText("Different visible reply")
    dialog._update_copy_button()
    assert dialog.copy_button.enabled is False
    before = list(clipboard.values)
    dialog.copy_reply()
    assert clipboard.values == before


def test_b2_back_to_root_clears_previous_copy_target(monkeypatch) -> None:
    class _Text:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def setPlainText(self, value: str) -> None:
            self.value = value

        def toPlainText(self) -> str:
            return self.value

        def setText(self, value: str) -> None:
            self.value = value

    class _Button:
        def __init__(self) -> None:
            self.enabled = True

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

    clipboard = SimpleNamespace(values=[])
    clipboard.setText = clipboard.values.append
    monkeypatch.setattr(guided_call_module, "QGuiApplication", SimpleNamespace(clipboard=lambda: clipboard))
    dialog = GuidedCallDialog.__new__(GuidedCallDialog)
    dialog.current = object()
    dialog.path = ["That is too expensive"]
    dialog.state = {"objections": ["Too expensive"]}
    dialog.history = [(None, [], {})]
    dialog._active_mode = "Live Call"
    dialog._rescue_text = ""
    dialog._spoken_response = "Previous branch reply"
    dialog.response = _Text("Previous branch reply")
    dialog.copy_button = _Button()
    dialog.breadcrumb = _Text()
    dialog.next_step = _Text()
    dialog.phase_label = _Text()
    dialog.followup_layout = object()
    dialog.guide = SimpleNamespace(call_phase="IDENTITY", owner_spoken_claims=(), owner_copied_claims=())
    dialog.clear_layout = lambda _layout: None
    dialog._live_contact_allowed = lambda: True
    dialog._commercial_guidance_current = lambda: True

    dialog.go_back()

    assert dialog.current is None
    assert dialog._spoken_response == ""
    assert dialog.copy_button.enabled is False
    assert dialog.response.toPlainText().startswith("Live Call ready")
    dialog.copy_reply()
    assert clipboard.values == []


def test_b2_other_opening_is_neutral_distinct_and_used_by_dialog(tmp_path) -> None:
    class _Choice:
        def __init__(self, value: str) -> None:
            self.value = value

        def currentText(self) -> str:
            return self.value

    class _Text:
        def __init__(self) -> None:
            self.value = ""

        def setPlainText(self, value: str) -> None:
            self.value = value

    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])

    assert len({guide.opening_30s, guide.in_person_opening_30s, guide.other_opening_30s}) == 3
    assert "phone" not in guide.other_opening_30s.casefold()
    assert "in person" not in guide.other_opening_30s.casefold()

    dialog = GuidedCallDialog.__new__(GuidedCallDialog)
    dialog.guide = guide
    dialog.opening = _Text()
    dialog.interaction_channel = _Choice("Other")
    dialog.show_opening(1)
    assert dialog.opening.value == guide.other_opening_30s


def test_b2_dnc_failure_rolls_back_interaction_and_suppression_together(tmp_path, monkeypatch) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.commit()
        lead_id = lead.id

    original_add_suppression = repository_module.add_suppression
    calls = 0

    def fail_during_suppression(session, value: str, reason: str = ""):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_add_suppression(session, value, reason)
        raise RuntimeError("injected suppression failure")

    monkeypatch.setattr(repository_module, "add_suppression", fail_during_suppression)
    with factory() as session:
        with pytest.raises(RuntimeError, match="injected suppression failure"):
            save_contact_interaction(
                session,
                lead_id,
                interaction_datetime="2026-09-11T12:30:00Z",
                method="Phone",
                direction="Outbound",
                outcome="Do not contact me again",
                notes="Atomic rollback test.",
                next_action="Do Not Contact",
            )
        session.rollback()

    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert list_contact_interactions(session, lead_id) == []
        assert lead is not None and lead.suppressed is False
        assert not is_suppressed(session, lead)


def test_b2_neutral_identity_and_experience_questions_do_not_prejudge_skepticism(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])

    branches = {branch.key: branch for branch in guide.branches}
    identity = branches["who_are_you"]
    experience = branches["experience"]

    assert "credibility_concern" not in identity.state_updates
    assert "decision_maker_skeptical" not in identity.state_updates
    assert experience.state_updates == {"seller_experience_question": True}

    identity_followups = {item.label: item for item in identity.followups}
    assert identity_followups["What company are you with?"].state_updates == {}
    assert identity_followups["Are you local?"].state_updates == {"local_presence_question": True}
    assert identity_followups["Is this AI?"].state_updates == {}


def test_b2_ambiguous_stop_disengage_does_not_preload_dnc(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])

    stop = next(branch for branch in guide.branches if branch.key == "stop_disengage")
    assert stop.state_updates.get("outcome") not in {"Do not contact", "Do not contact me again"}
    assert stop.state_updates.get("next_action") != "Do Not Contact"
    assert stop.state_updates == {"next_action": "End conversation"}


def test_b2_owner_surface_does_not_claim_unverified_comparison_or_finding(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])

    branches = {branch.key: branch for branch in guide.branches}
    gatekeeper = branches["gatekeeper_what_regarding"].response.casefold()
    happy = branches["happy"].response.casefold()

    assert "i compared the public website" not in gatekeeper
    assert "found one specific" not in gatekeeper
    assert "what i found" not in happy
    assert "specific customer path" not in happy


def test_b2_website_weakness_or_reachability_change_invalidates_claim_verification(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        lead.verification_json = '{"audit_claims": true, "outreach": true}'
        session.add(lead)
        session.flush()

        def audit(*, weakness: str, reachable: bool = True):
            return SimpleNamespace(
                url=lead.website,
                reachable=reachable,
                status_code=200 if reachable else 0,
                final_url=lead.website if reachable else "",
                response_time_ms=25,
                title="B2 Roofing",
                meta_description="",
                checks={"viewport": reachable},
                metrics={},
                strengths=[],
                weaknesses=[weakness],
                rendered_checks={},
                evidence={"contact_path": "https://example.test/contact"} if reachable else {},
                pagespeed_status="",
                rendered_status="",
                desktop_screenshot="",
                mobile_screenshot="",
            )

        save_audit(session, lead.id, audit(weakness="Old verified weakness"))
        lead.verification_json = '{"audit_claims": true, "outreach": true}'
        session.flush()

        save_audit(session, lead.id, audit(weakness="Materially changed weakness"))
        session.refresh(lead)
        assert '"audit_claims": false' in lead.verification_json

        lead.verification_json = '{"audit_claims": true, "outreach": true}'
        session.flush()
        save_audit(session, lead.id, audit(weakness="Materially changed weakness", reachable=False))
        session.refresh(lead)
        assert '"audit_claims": false' in lead.verification_json
