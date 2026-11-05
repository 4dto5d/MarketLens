from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QInputDialog
from sqlalchemy import select

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import replace_contact_points
from local_presence_miner.database.schema import CompetitorRecord, ContactInteraction, Lead, OutreachDraft, WebsiteAuditRecord
from local_presence_miner.services.suppression_service import SuppressionService
from local_presence_miner.ui.dialogs import guided_call_dialog as guided_call_module
from local_presence_miner.ui.dialogs.contact_interaction_dialog import ContactInteractionDialog
from local_presence_miner.ui.dialogs.guided_call_dialog import GuidedCallDialog
from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
from local_presence_miner.ui.dialogs.new_search_dialog import NewSearchDialog
from local_presence_miner.ui.widgets.outreach_widget import OutreachWidget


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_new_search_google_depth_and_call_estimate(tmp_path) -> None:
    app()
    config = AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "search-ui.sqlite3",
        log_path=tmp_path / "app.log",
        output_dir=tmp_path / "output",
    )
    dialog = NewSearchDialog(config)
    dialog.demo_mode.setChecked(False)
    dialog.max_results.setValue(100)
    dialog.google_data_depth.setCurrentText("Balanced")
    assert "4 Text Search + 20 Place Details" in dialog.api_estimate.text()
    assert dialog.criteria().google_data_depth == "Balanced"

    dialog.safe_live_test.setChecked(True)
    assert "2 Text Search + 5 Place Details" in dialog.api_estimate.text()
    assert dialog.google_data_depth.isEnabled() is False
    assert dialog.criteria().safe_live_test is True
    dialog.close()


class CapturingThreadPool:
    def __init__(self) -> None:
        self.worker = None

    def start(self, worker) -> None:
        self.worker = worker


def configured_lead(tmp_path):
    config = AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "outreach-ui.sqlite3",
        log_path=tmp_path / "app.log",
        output_dir=tmp_path / "output",
        request_delay_seconds=0,
    )
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="ui-lead",
            name="UI Roofing",
            category="Roofing",
            phone="555-0100",
            lead_score=80,
            sales_priority_score=76,
            qualification_class="High Priority",
            qualification_confidence="Moderate",
            qualification_json='{"qualification_class":"High Priority"}',
            recommended_offer_id="one_page_conversion_site",
            offer_resolution_state="canonical_id",
            website="https://ui.example",
            audit=WebsiteAuditRecord(url="https://ui.example", reachable=True, status_code=200,
                                    checks_json='{"sitewide_contact_path":false,"tap_to_call":false,"contact_form":false}'),
        )
        lead.target_signals_json = '["No obvious CTA", "No contact form"]'
        session.add(lead)
        session.commit()
        lead_id = lead.id
    return config, factory, lead_id


def test_contact_discovery_actions_schedule_background_workers_and_keep_batch_size(tmp_path, monkeypatch) -> None:
    qt_app = app()
    config, factory, lead_id = configured_lead(tmp_path)

    detail = LeadDetailDialog(config, factory, lead_id)
    detail_pool = CapturingThreadPool()
    detail.thread_pool = detail_pool
    detail.discover_public_contacts()
    assert detail_pool.worker is not None
    assert detail_pool.worker.func == detail._discover_public_contacts_job

    outreach = OutreachWidget(factory, config)
    outreach_pool = CapturingThreadPool()
    outreach.thread_pool = outreach_pool
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *_args, **_kwargs: (7, True)))
    outreach.discover_batch_contacts()
    assert outreach_pool.worker is not None
    assert outreach_pool.worker.args == (7,)

    detail.close()
    outreach.close()
    qt_app.processEvents()


def test_guided_call_renders_recursive_branches_and_requests_phone_outcome(tmp_path, monkeypatch) -> None:
    qt_app = app()
    _config, factory, lead_id = configured_lead(tmp_path)
    dialog = GuidedCallDialog(factory, lead_id)
    assert dialog.opening_choice.count() == 3
    assert dialog.current is None
    assert dialog.state == {}
    assert dialog.guide.intelligence_level == "Moderate"
    dialog.show_branch("busy_enough")
    busy = next(branch for branch in dialog.guide.branches if branch.key == "busy_enough")
    booked = next(item for item in busy.followups if item.label == "We're booked out")
    dialog.show_followup(booked)
    assert dialog.followup_layout.count() == len(booked.followups) + 1

    captured: dict[str, object] = {}

    class FakeInteractionDialog:
        def __init__(
            self,
            _factory,
            _lead_id,
            parent=None,
            default_method="Email",
            defaults=None,
            config=None,
        ) -> None:
            captured["lead_id"] = _lead_id
            captured["parent"] = parent
            captured["method"] = default_method
            captured["defaults"] = defaults
            captured["config"] = config

        def exec(self) -> int:
            captured["executed"] = True
            return 0

    monkeypatch.setattr(guided_call_module, "ContactInteractionDialog", FakeInteractionDialog)
    dialog.mode.setCurrentText("Live Call")
    dialog.show_branch("busy_enough")
    dialog.show_followup(booked)
    dialog.record_outcome()
    assert captured["lead_id"] == lead_id
    assert captured["parent"] is dialog
    assert captured["method"] == "Phone"
    assert captured["defaults"]["branch_path"] == ["We're already busy enough", "We're booked out"]
    assert captured["defaults"]["capacity_status"] == "Booked/busy"
    assert captured["config"] is dialog.config
    assert captured["executed"] is True
    dialog.close()
    qt_app.processEvents()


def test_phone_contact_outcome_dialog_persists_structured_interaction(tmp_path) -> None:
    qt_app = app()
    _config, factory, lead_id = configured_lead(tmp_path)
    dialog = ContactInteractionDialog(factory, lead_id, default_method="Phone")
    assert dialog.method.currentText() == "Phone"
    dialog.outcome.setCurrentText("Requested information")
    dialog.notes.setPlainText("Asked for the comparison by email.")
    dialog.save()

    with factory() as session:
        interaction = session.execute(select(ContactInteraction).where(ContactInteraction.lead_id == lead_id)).scalar_one()
        assert interaction.method == "Phone"
        assert interaction.outcome == "Requested information"
        assert interaction.notes == "Asked for the comparison by email."
    dialog.close()
    qt_app.processEvents()


def test_lead_detail_renders_contact_intelligence_and_smart_offer(tmp_path) -> None:
    qt_app = app()
    config, factory, lead_id = configured_lead(tmp_path)
    with factory() as session:
        replace_contact_points(
            session,
            lead_id,
            [{"kind": "email", "value": "hello@example.com", "selected": True, "verified_public": True}],
        )
        session.commit()
    dialog = LeadDetailDialog(config, factory, lead_id)
    tab_names = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
    assert "Contact Intelligence" in tab_names
    assert "Smart Offer" in tab_names
    assert "Smart Offer" in dialog.offer_preview.toPlainText()
    assert "Catalog-based ask" in dialog.offer_preview.toPlainText()
    assert "Would falsify:" in dialog.offer_preview.toPlainText()
    assert dialog.offer_preview.toPlainText().count("\n") > 12
    assert "Upper planning ask (same scope)" in dialog.offer_preview.toPlainText()
    dialog.close()
    qt_app.processEvents()


def test_contact_discovery_recalculates_qualification_and_adaptive_assets(tmp_path) -> None:
    qt_app = app()
    config, factory, lead_id = configured_lead(tmp_path)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        lead.website = ""
        lead.sales_priority_score = 0
        lead.qualification_json = "{}"
        session.commit()

    dialog = LeadDetailDialog(config, factory, lead_id)
    count, _warnings = dialog._discover_public_contacts_job()
    assert count == 1
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        assert lead.sales_priority_score > 0
        assert lead.qualification_json not in {"", "{}"}
        assert "recommended_ask" in lead.starting_offer_json
        assert session.query(OutreachDraft).filter_by(lead_id=lead_id).count() == 11
    dialog.close()
    qt_app.processEvents()


def test_manual_competitor_review_recalculates_qualification_and_scripts(tmp_path) -> None:
    qt_app = app()
    config, factory, lead_id = configured_lead(tmp_path)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        lead.sales_priority_score = 0
        lead.qualification_json = "{}"
        session.add(
            CompetitorRecord(
                lead_id=lead_id,
                competitor_place_id="",
                competitor_name="Reviewed Competitor",
                match_score=70,
                reason="Manual comparison candidate",
            )
        )
        session.commit()

    dialog = LeadDetailDialog(config, factory, lead_id)
    assert dialog.competitor_review_fields
    first = next(iter(dialog.competitor_review_fields.values()))
    first[0].setChecked(True)
    first[1].setText("Operator confirmed local relevance.")
    dialog.save_competitor_review()
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None and lead.sales_priority_score > 0
        assert lead.qualification_json not in {"", "{}"}
        assert session.query(OutreachDraft).filter_by(lead_id=lead_id).count() == 11
    dialog.close()
    qt_app.processEvents()


def test_open_guided_call_rechecks_suppression_before_live_outcome(tmp_path) -> None:
    app()
    _config, factory, lead_id = configured_lead(tmp_path)
    dialog = GuidedCallDialog(factory, lead_id)
    dialog.mode.setCurrentText("Live Call")
    assert dialog.mode.currentText() == "Live Call"
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        SuppressionService().suppress_lead(session, lead, "Explicit DNC after dialog opened")
        session.commit()
    dialog.record_outcome()
    assert "Live Call blocked" in dialog.response.toPlainText()
    dialog.close()


def test_guided_call_back_restores_structured_state(tmp_path) -> None:
    qt_app = app()
    _config, factory, lead_id = configured_lead(tmp_path)
    dialog = GuidedCallDialog(factory, lead_id)
    dialog.mode.setCurrentText("Live Call")
    dialog.show_branch("busy_enough")
    busy = next(branch for branch in dialog.guide.branches if branch.key == "busy_enough")
    booked = next(item for item in busy.followups if item.label == "We're booked out")
    dialog.show_followup(booked)
    better_fit = next(item for item in booked.followups if item.label == "We want better-fit jobs")
    dialog.show_followup(better_fit)
    assert dialog.state.get("business_goal") == "Better-fit jobs"
    dialog.go_back()
    assert dialog.state.get("business_goal") != "Better-fit jobs"
    dialog.close()
    qt_app.processEvents()


def test_practice_call_cannot_record_or_leak_into_live(tmp_path, monkeypatch) -> None:
    qt_app = app()
    _config, factory, lead_id = configured_lead(tmp_path)
    dialog = GuidedCallDialog(factory, lead_id)
    dialog.show_branch("interested")
    assert dialog.state.get("commitments")
    called = {"value": False}

    class FakeInteractionDialog:
        def __init__(self, *_args, **_kwargs):
            called["value"] = True
        def exec(self):
            return 0

    monkeypatch.setattr(guided_call_module, "ContactInteractionDialog", FakeInteractionDialog)
    dialog.record_outcome()
    assert called["value"] is False
    dialog.mode.setCurrentText("Live Call")
    assert dialog.state == {}
    assert dialog.current is None
    dialog.close()
    qt_app.processEvents()
