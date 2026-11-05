from __future__ import annotations

import json

import pytest

from local_presence_miner.config import AppConfig, SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    list_contact_points,
    replace_contact_points,
    save_outreach_draft,
    set_outreach_approval,
    update_lead_status,
)
from local_presence_miner.database.schema import ContactPoint, Lead, OutreachDraft
from local_presence_miner.domain.enums import LeadStatus, OutreachKind
from local_presence_miner.services import batch_contact_discovery_service as batch_discovery_module
from local_presence_miner.services.batch_contact_discovery_service import BatchContactDiscoveryService
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.outreach_batch_service import OutreachBatchService
from local_presence_miner.services.outreach_planner import build_outreach_channel_plan
from local_presence_miner.services.outreach_service import OutreachService


def verified_lead() -> Lead:
    lead = Lead(
        place_id="lead-1",
        name="ABC Roofing",
        category="roofers",
        phone="555-0100",
        lead_score=80,
        qualification_class="Qualified",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Qualified","confidence":"Strong"}',
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        offer_resolution_state="canonical_id",
    )
    lead.verification_json = json.dumps({"business_identity": True, "audit_claims": True, "outreach": True})
    lead.target_signals_json = json.dumps(["No obvious CTA", "No contact form"])
    return lead


def test_outreach_channel_plan_prefers_public_email() -> None:
    lead = verified_lead()
    contacts = [
        ContactPoint(lead_id=1, kind="phone", value="555-0100", selected=False),
        ContactPoint(lead_id=1, kind="email", value="owner@example.com", selected=True),
    ]
    plan = build_outreach_channel_plan(lead, contacts)
    assert plan.primary_channel == "Email"
    assert plan.recipient == "owner@example.com"
    assert plan.secondary_channel == "Phone"


def test_operator_selected_phone_overrides_email_first_plan() -> None:
    lead = verified_lead()
    contacts = [
        ContactPoint(lead_id=1, kind="email", value="owner@example.com", selected=False),
        ContactPoint(lead_id=1, kind="phone", value="555-0100", selected=True),
    ]
    plan = build_outreach_channel_plan(lead, contacts)
    assert plan.primary_channel == "Phone"
    assert plan.secondary_channel == "Email"


def test_outreach_channel_plan_blocks_suppressed() -> None:
    lead = verified_lead()
    lead.suppressed = True
    plan = build_outreach_channel_plan(lead, [])
    assert plan.state == "Blocked"
    assert plan.primary_channel == "Do not contact"


def test_call_guide_contains_common_if_then_branches(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "call.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = verified_lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])
        labels = {branch.label for branch in guide.branches}
        assert "How much?" in labels
        assert "That's too expensive" in labels
        assert "We already have someone" in labels
        assert "Send me information" in labels
        assert "I need to think about it" in labels
        assert "not assuming you need a redesign" in guide.opening_30s


def test_outreach_service_uses_shorter_specific_sequence() -> None:
    lead = verified_lead()
    drafts = OutreachService(SenderInfo(name="Sam", opt_out_line="Reply opt out.")).generate_all(lead, city="Peoria")
    initial = drafts[OutreachKind.INITIAL_EMAIL][1]
    # A detached lead summary has no current source/review attestation. Keep
    # permission-based discovery, without asserting the summary as a fact.
    assert "No obvious CTA" not in initial
    assert "requires a recorded, reviewed observation" in initial
    assert "I can prepare a short comparison after manual verification" in initial
    assert "Would that be useful?" in initial
    assert "Reply opt out." in initial
    assert "unclaimed" not in initial.lower()


def test_contact_points_persist_and_batch_exports_only_approved_verified(tmp_path, outbound) -> None:
    factory = create_session_factory(tmp_path / "outreach.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = verified_lead()
        session.add(lead)
        session.flush()
        replace_contact_points(
            session,
            lead.id,
            [
                {
                    "kind": "email",
                    "value": "hello@abc.example",
                    "label": "Email",
                    "source_type": "official_website",
                    "source_url": "https://abc.example/contact",
                    "confidence": "Strong",
                    "verified_public": True,
                    "selected": True,
                }
            ],
        )
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Hello", outbound.body("Grounded draft"), proof_dependencies=[])
        session.commit()
        draft_id = draft.id
        lead_id = lead.id

    with factory() as session:
        assert list_contact_points(session, lead_id)[0].value == "hello@abc.example"
        set_outreach_approval(session, draft_id, True, sender=outbound.sender)
        session.commit()
        summary = OutreachBatchService(outbound.sender).export_ready_csv(session, tmp_path / "exports")
        assert summary.exported == 1
        text = summary.path.read_text(encoding="utf-8-sig")
        assert "hello@abc.example" in text
        assert "Grounded draft" in text


def test_do_not_contact_and_opted_out_statuses_block_planning_approval_and_export(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "blocked.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = verified_lead()
        lead.place_id = "blocked"
        lead.status = LeadStatus.DO_NOT_CONTACT.value
        session.add(lead)
        session.flush()
        replace_contact_points(
            session,
            lead.id,
            [{"kind": "email", "value": "blocked@example.com", "selected": True, "verified_public": True}],
        )
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Do not send", "Verified message")
        draft.approved = True
        session.commit()
        lead_id, draft_id = lead.id, draft.id

        plan = build_outreach_channel_plan(lead, list_contact_points(session, lead.id))
        assert (plan.state, plan.primary_channel) == ("Blocked", "Do not contact")
        with pytest.raises(ValueError):
            set_outreach_approval(session, draft.id, True)
        summary = OutreachBatchService().export_ready_csv(session, tmp_path / "blocked-export")
        assert (summary.exported, summary.skipped) == (0, 1)
        assert "Do Not Contact" in summary.review_path.read_text(encoding="utf-8-sig")

        lead.status = LeadStatus.APPROVED_TO_CONTACT.value
        lead.suppressed = False
        draft.approved = True
        update_lead_status(session, lead.id, LeadStatus.OPTED_OUT)
        session.commit()

    with factory() as session:
        stored_lead = session.get(Lead, lead_id)
        stored_draft = session.get(OutreachDraft, draft_id)
        assert stored_lead is not None and stored_lead.status == LeadStatus.OPTED_OUT.value and stored_lead.suppressed
        assert stored_draft is not None and stored_draft.approved is False


def test_contact_refresh_preserves_exactly_one_operator_selected_phone(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "preferred-route.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = verified_lead()
        lead.place_id = "preferred-route"
        session.add(lead)
        session.flush()
        replace_contact_points(
            session,
            lead.id,
            [
                {"kind": "email", "value": "hello@example.com", "selected": False},
                {"kind": "phone", "value": "555-0100", "selected": True},
            ],
        )
        replace_contact_points(
            session,
            lead.id,
            [
                {"kind": "email", "value": "hello@example.com", "selected": True},
                {"kind": "phone", "value": "555-0100", "selected": False},
            ],
        )
        points = list_contact_points(session, lead.id)
        assert [(point.kind, point.selected) for point in points if point.selected] == [("phone", True)]
        assert build_outreach_channel_plan(lead, points).primary_channel == "Phone"


def test_batch_discovery_honors_the_full_configured_delay(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        tmp_path,
        tmp_path / "batch-delay.sqlite3",
        tmp_path / "app.log",
        tmp_path / "output",
        request_delay_seconds=2.5,
    )
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        session.add(Lead(place_id="delay-lead", name="Delay Lead", phone="555-0100"))
        session.commit()
    delays: list[float] = []
    monkeypatch.setattr(batch_discovery_module.time, "sleep", delays.append)
    summary = BatchContactDiscoveryService(config, factory).run(limit=1)
    assert summary.attempted == 1
    assert delays == [2.5]


def test_hold_and_reject_qualification_are_explained_in_needs_review_export(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "qualification-export.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = verified_lead()
        lead.place_id = "hold-export"
        lead.qualification_class = "Hold"
        lead.qualification_json = json.dumps({"classification": "Hold", "confidence": "Low"})
        session.add(lead)
        session.flush()
        replace_contact_points(
            session,
            lead.id,
            [{"kind": "email", "value": "hold@example.com", "selected": True, "verified_public": True}],
        )
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Hold", "Verified message")
        draft.approved = True
        session.commit()
        summary = OutreachBatchService().export_ready_csv(session, tmp_path / "qualification-export")
        review = summary.review_path.read_text(encoding="utf-8-sig")
        assert summary.exported == 0
        assert "Qualification is Hold" in review
