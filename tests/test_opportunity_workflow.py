"""Warm intake and planning never manufacture evidence or approval."""
import json

import pytest
from sqlalchemy import func, select
from test_a02_a03_page_eligibility import assert_withheld
from test_sales_delivery_corrections import storage as storage_fixture

from local_presence_miner.database.repositories import lead_google_details_retrieved
from local_presence_miner.database.schema import ActivityLog, ContactInteraction, Lead, OutreachDraft
from local_presence_miner.services.opportunity_workflow_service import (
    NUMBER_FIELDS,
    WORKSHEET_ACTION,
    create_warm_opportunity,
    latest_worksheet,
    normalize_worksheet,
    planning_cost,
    save_worksheet,
)


@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    config, factory = storage_fixture.__wrapped__(tmp_path)
    yield config, factory
    factory.kw["bind"].dispose()


def hypothetical():
    return {"route": "owner_report", "owner_reported": True,
            "source_ref": "Hypothetical Jarrod scenario — November 4, 2026; not a real account",
            "observation": "I want easier editing; could Serenity Now move from UENI to Wix?",
            "alternatives": "Current platform training or account permissions may solve this without migration.",
            "owner_question": "Which edits are difficult, and who owns the domain and current account?",
            "candidate_scope": "Assess editing workflow and migration feasibility; no agreed rebuild.",
            "platform_assumptions": "UENI access, exportability, domain/email ownership and Wix suitability UNKNOWN.",
            "next_action": "Clarify editing needs and permission before selecting a service."}


def test_warm_hypothetical_survives_reopen_without_discovery_or_paid_diagnosis(storage):
    config, factory = storage
    with factory() as session:
        lead = create_warm_opportunity(session, name="Hypothetical Serenity Now", website="https://serenity.example", data=hypothetical())
        identity = lead.id
        assert lead.search_id is None and lead.place_id.startswith("manual:")
        assert not lead_google_details_retrieved(lead)
        assert lead.qualification_class == "Hold" and lead.profile_verification_required
        assert_withheld(session, lead, config)
        session.commit()
    with factory() as session:
        lead = session.get(Lead, identity)
        worksheet = latest_worksheet(session, identity)
        assert worksheet["state"] == "recorded" and worksheet["recorded_at"]
        assert "UENI to Wix" in worksheet["data"]["observation"]
        assert worksheet["data"]["owner_reported"]
        assert not lead_google_details_retrieved(lead) and not lead.recommended_offer_id
        assert_withheld(session, lead, config)
        assert session.scalar(select(func.count()).select_from(ContactInteraction)) == 0
        assert session.scalar(select(func.count()).select_from(OutreachDraft)) == 0


@pytest.mark.parametrize("route", ["public_problem", "public_clue", "owner_report"])
def test_routes_and_revisions_preserve_history_without_promoting_scope(storage, route):
    _, factory = storage
    with factory() as session:
        data = {**hypothetical(), "route": route, "owner_reported": False}
        lead = create_warm_opportunity(session, name="Synthetic planning only", data=data)
        first = session.scalar(select(ActivityLog).where(ActivityLog.lead_id == lead.id))
        original = (first.message, first.created_at)
        before = (lead.qualification_class, lead.commercial_plan_snapshot_json, lead.recommended_offer_id, lead.verification_json)
        second = save_worksheet(session, lead, {**data, "next_action": "Ask owner before estimating."})
        assert second.id != first.id
        assert (first.message, first.created_at) == original
        assert latest_worksheet(session, lead.id)["data"]["route"] == route
        assert before == (lead.qualification_class, lead.commercial_plan_snapshot_json, lead.recommended_offer_id, lead.verification_json)


def test_cost_includes_all_effort_and_expenses_and_keeps_unknown_distinct():
    data = {**hypothetical(), "delivery_hours": "6", "acquisition_hours": "2", "travel_hours": "1",
            "support_hours": "3", "hourly_cost": "25", "direct_costs": "45"}
    assert "12 hours" in planning_cost(data) and "$345.00" in planning_cost(data)
    for field in NUMBER_FIELDS:
        assert planning_cost({**data, field: ""}).startswith("UNKNOWN")
    assert "$0.00" in planning_cost({**data, **dict.fromkeys(NUMBER_FIELDS, "0")})


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1000001", "abc", True])
def test_invalid_costs_fail_closed(value):
    with pytest.raises(ValueError):
        normalize_worksheet({**hypothetical(), "direct_costs": value})


def test_corrupt_latest_revision_does_not_fall_back_to_old_plan(storage):
    _, factory = storage
    with factory() as session:
        lead = create_warm_opportunity(session, name="Synthetic", data=hypothetical())
        session.add(ActivityLog(lead_id=lead.id, action=WORKSHEET_ACTION, message=json.dumps({"route": "invented"})))
        session.flush()
        assert latest_worksheet(session, lead.id)["state"] == "invalid"
        assert latest_worksheet(session, lead.id)["data"] == {}


def test_invalid_intake_creates_no_business(storage):
    _, factory = storage
    with factory() as session:
        with pytest.raises(ValueError):
            create_warm_opportunity(session, name="Synthetic", website="javascript:alert(1)", data=hypothetical())
        with pytest.raises(ValueError):
            create_warm_opportunity(session, name="Synthetic", data={**hypothetical(), "source_ref": ""})
        assert session.scalar(select(func.count()).select_from(Lead)) == 0


def test_offscreen_intake_save_reopen_and_existing_destination(storage):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QDialog, QScrollArea

    from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
    from local_presence_miner.ui.dialogs.opportunity_workflow_dialog import OpportunityWorkflowDialog
    from local_presence_miner.ui.theme import load_stylesheet

    app = QApplication.instance() or QApplication([])
    config, factory = storage
    dialog = OpportunityWorkflowDialog(factory)
    dialog.setStyleSheet(load_stylesheet())
    dialog.show()
    app.processEvents()
    body = dialog.findChild(QScrollArea).widget()
    assert body.palette().color(QPalette.ColorRole.Window).name() == "#0f172a"
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.name.setText("Hypothetical Serenity Now")
    for key, value in hypothetical().items():
        if key in dialog.fields:
            dialog.fields[key].setText(value)
    dialog.owner_reported.setChecked(True)
    assert dialog.save() and dialog.lead_id is not None
    original_id = dialog.lead_id
    dialog.go("Smart Offer")
    assert dialog.lead_id == original_id and dialog.destination == "Smart Offer"
    assert dialog.result() == QDialog.DialogCode.Accepted
    reopened = OpportunityWorkflowDialog(factory, original_id)
    assert "UENI to Wix" in reopened.fields["observation"].text()
    workspace = LeadDetailDialog(config, factory, original_id)
    workspace.open_workflow_destination("Smart Offer")
    assert workspace.tabs.tabText(workspace.tabs.currentIndex()) == "Smart Offer"
    app.processEvents()
    workspace.close()
    reopened.close()
    dialog.close()
