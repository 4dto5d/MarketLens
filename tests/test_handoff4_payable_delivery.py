"""Real persistence/Qt checks for exact, feasible forward payable agreements."""
import json
from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import select
from test_sales_delivery_corrections import business, payload
from test_sales_delivery_corrections import storage as storage_fixture

from local_presence_miner.database.pricing_repository import save_offer_history
from local_presence_miner.database.schema import Lead, OfferHistory
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.delivery_packet_service import DELIVERY_FIELDS, DELIVERY_PREREQUISITES, DeliveryPacketService
from local_presence_miner.services.sales_evidence_service import SalesEvidenceService
from local_presence_miner.services.seo_research_service import append_research
from local_presence_miner.ui.dialogs.commercial_review_dialog import CommercialReviewDialog
from local_presence_miner.ui.dialogs.offer_history_dialog import OfferHistoryDialog


@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    return storage_fixture.__wrapped__(tmp_path)


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(str(args[-1])))
    return app, warnings


def scope_facts():
    return {key: f"Recorded page-text correction agreement: {label}; owner/provider confirms responsibility."
            for key, label in DELIVERY_FIELDS.items()}


def prerequisite_facts():
    return {key: {"state": "satisfied", "notes": "Owner/provider confirms actual access and feasibility for this exact page-text scope."}
            for key in DELIVERY_PREREQUISITES}


def seed(factory, *, ready=False):
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        if ready:
            SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi", source_text="Synthetic source/page checked.")
            DeliveryPacketService().record(session, lead, context=context, fields=scope_facts(), selected_price=pricing.recommended,
                                           reviewer="Sammi", source_text="Owner approves exact scope/amount.", reviewed=True,
                                           owner_approved=True, prerequisites=prerequisite_facts())
        identity, amount = lead.id, pricing.recommended
        session.commit()
    return identity, amount


@pytest.mark.parametrize("status", ["Accepted", "Won"])
@pytest.mark.parametrize("supply_lead", [False, True])
def test_actual_draft_edit_refuses_payable_transition_without_readiness(storage, qt, status, supply_lead):
    _, factory = storage
    identity, amount = seed(factory)
    draft = OfferHistoryDialog(factory, lead_id=identity)
    draft.save()
    draft.close()
    with factory() as session:
        offer_id = session.scalar(select(OfferHistory.id))
    dialog = OfferHistoryDialog(factory, offer_id=offer_id, lead_id=identity if supply_lead else None)
    assert dialog.lead_id == identity
    dialog.status.setCurrentText(status)
    if status == "Won":
        dialog.closed_amount.setValue(amount)
    dialog.save()
    assert qt[1] and "delivery packet" in qt[1][-1]
    with factory() as session:
        offer = session.get(OfferHistory, offer_id)
        assert offer.status == "Draft" and offer.lead_id == identity
    dialog.close()


@pytest.mark.parametrize("status", ["Accepted", "Won"])
def test_exact_ready_forward_agreement_succeeds(storage, qt, status):
    _, factory = storage
    identity, amount = seed(factory, ready=True)
    dialog = OfferHistoryDialog(factory, lead_id=identity, default_status=status)
    if status == "Won":
        dialog.closed_amount.setValue(amount)
    dialog.save()
    assert not qt[1]
    with factory() as session:
        offer = session.scalar(select(OfferHistory))
        assert offer.status == status and offer.lead_id == identity
        assert offer.canonical_offer_id == "conversion_tune_up"
    dialog.close()


@pytest.mark.parametrize("change", ["package", "scope", "amount"])
def test_material_agreement_change_requires_its_own_binding(storage, qt, change):
    _, factory = storage
    identity, amount = seed(factory, ready=True)
    dialog = OfferHistoryDialog(factory, lead_id=identity, default_status="Accepted")
    if change == "package":
        dialog.package_name.setText("Full Local Authority Site")
    elif change == "scope":
        dialog.scope_summary.setPlainText("Full website rebuild")
    else:
        dialog.initial_ask.setValue(amount + 50)
    dialog.save()
    assert qt[1]
    with factory() as session:
        assert session.scalars(select(OfferHistory)).all() == []
    dialog.close()


def test_persistence_guards_transition_and_preserves_lead_when_omitted(storage):
    _, factory = storage
    identity, amount = seed(factory)
    with factory() as session:
        args = dict(lead_id=identity, offer_date=date.today().isoformat(), business_name="Synthetic", niche="plumber",
                    package_name="Conversion Tune-Up", scope_summary="local SEO title/meta/H1 fixes", initial_ask=amount)
        draft = save_offer_history(session, status="Draft", **args)
        edit_args = {k: v for k, v in args.items() if k != "lead_id"}
        with pytest.raises(ValueError, match="delivery packet"):
            save_offer_history(session, offer_id=draft.id, status="Accepted", **edit_args)
        saved = save_offer_history(session, offer_id=draft.id, status="Draft", notes="Private note", **edit_args)
        assert saved.lead_id == identity and saved.notes == "Private note"


def test_historical_mode_cannot_relabel_current_draft_as_payable(storage, qt):
    _, factory = storage
    identity, amount = seed(factory)
    draft = OfferHistoryDialog(factory, lead_id=identity)
    draft.save()
    draft.close()
    with factory() as session:
        record_id = session.scalar(select(OfferHistory.id))
    dialog = OfferHistoryDialog(factory, offer_id=record_id)
    dialog.historical_record.setChecked(True)
    dialog.offer_date.setText((date.today() - timedelta(days=30)).isoformat())
    dialog.notes.setPlainText("Attempt to relabel a current Draft as old history")
    dialog.status.setCurrentText("Won")
    dialog.closed_amount.setValue(amount)
    dialog.save()
    assert qt[1]
    with factory() as session:
        assert session.get(OfferHistory, record_id).status == "Draft"
    dialog.close()


def test_explicit_history_and_unchanged_historical_edits_preserve_snapshot(storage):
    _, factory = storage
    with factory() as session:
        args = dict(offer_date=(date.today() - timedelta(days=30)).isoformat(), business_name="Historic client", niche="plumber",
                    package_name="Conversion Tune-Up", scope_summary="Historical text scope", initial_ask=300, status="Won", closed_amount=280)
        with pytest.raises(ValueError, match="history explicitly"):
            save_offer_history(session, **args)
        historical = save_offer_history(session, historical_record=True, proof_snapshot={"historical": "unchanged"}, **args)
        original = historical.proof_snapshot_json
        changed = save_offer_history(session, offer_id=historical.id, notes="History note correction", **args)
        assert changed.status == "Won" and changed.closed_amount == 280 and changed.proof_snapshot_json == original


def test_reviewed_blocker_and_legacy_text_only_packet_are_not_ready(storage, qt):
    _, factory = storage
    identity, amount = seed(factory)
    with factory() as session:
        lead = session.get(Lead, identity)
        _, _, context = build_adaptive_sales_plan_with_context(session, lead)
        SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi", source_text="Source checked")
        fields = scope_facts()
        fields.update(platform_inventory="Read-only page; owner and Sammi cannot edit.",
                      collaborator_access="Access denied; provider refuses editor rights.", provider_cooperation="Provider refuses changes.")
        service = DeliveryPacketService()
        old = service.record(session, lead, fields=fields, selected_price=amount, reviewer="Sammi", source_text="Owner approves buying; access denied.",
                             reviewed=True, owner_approved=True)
        original = old.value_json
        assert not service.build(session, lead)["ready_for_payment"]
        decisions = prerequisite_facts()
        decisions["change_access"] = {"state": "blocked", "notes": "Page edits cannot be authorized."}
        service.record(session, lead, fields=fields, selected_price=amount, reviewer="Sammi", source_text="Access blocker classified.",
                       reviewed=True, owner_approved=True, prerequisites=decisions)
        assert not service.build(session, lead)["ready_for_payment"]
        assert old.value_json == original
        session.commit()
    dialog = OfferHistoryDialog(factory, lead_id=identity, default_status="Accepted")
    dialog.save()
    assert qt[1]
    with factory() as session:
        assert not session.scalars(select(OfferHistory)).all()
        lead = session.get(Lead, identity)
        DeliveryPacketService().record(session, lead, fields=scope_facts(), selected_price=amount, reviewer="Sammi",
                                       source_text="Provider resolved access; owner agrees.", reviewed=True, owner_approved=True,
                                       prerequisites=prerequisite_facts())
        assert DeliveryPacketService().build(session, lead)["ready_for_payment"]
    dialog.close()


def test_not_applicable_with_reason_preserves_narrow_work_and_old_packets_are_unknown(storage):
    _, factory = storage
    identity, amount = seed(factory)
    with factory() as session:
        lead = session.get(Lead, identity)
        _, _, context = build_adaptive_sales_plan_with_context(session, lead)
        SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi", source_text="Selected source checked")
        decisions = prerequisite_facts()
        decisions["provider_dependencies"] = {"state": "not_applicable", "notes": "Owner edits text; no provider/DNS/hosting change."}
        service = DeliveryPacketService()
        row = service.record(session, lead, fields=scope_facts(), selected_price=amount, reviewer="Sammi", source_text="Limited page edits approved.",
                             reviewed=True, owner_approved=True, prerequisites=decisions)
        assert service.build(session, lead)["ready_for_payment"]
        value = json.loads(row.value_json)
        value.pop("prerequisites")
        row.value_json = json.dumps(value)
        session.flush()
        assert not service.build(session, lead)["ready_for_payment"]


@pytest.mark.parametrize("prerequisites", [[], {"invented": {"state": "satisfied", "notes": "Anything"}},
    {"change_access": {"state": ["satisfied"], "notes": "Invalid"}}, {"change_access": {"state": "not_applicable", "notes": ""}}])
def test_corrupt_prerequisite_cannot_be_reviewed_as_ready(storage, prerequisites):
    _, factory = storage
    identity, amount = seed(factory)
    with factory() as session:
        lead = session.get(Lead, identity)
        with pytest.raises(ValueError, match="prerequisite"):
            DeliveryPacketService().record(session, lead, fields=scope_facts(), selected_price=amount, reviewer="Sammi",
                                           source_text="Malformed classification", prerequisites=prerequisites)


def test_review_ui_defaults_prerequisites_to_unknown(storage, qt):
    _, factory = storage
    identity, _ = seed(factory)
    dialog = CommercialReviewDialog(factory, identity)
    decisions = json.loads(dialog.prerequisites.toPlainText())
    assert all(value["state"] == "unknown" for value in decisions.values())
    assert not dialog.reviewed.isChecked() and not dialog.owner_approved.isChecked()
    dialog.close()
