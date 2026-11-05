from __future__ import annotations

import json
import sqlite3

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    add_suppression,
    list_leads,
    save_audit,
    save_outreach_draft,
    set_outreach_approval,
    upsert_lead,
)
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.enums import LeadStatus, OutreachKind
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown, WebsiteAudit


def test_sqlite_persistence(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "test.sqlite3")
    initialize_database(factory)
    with factory() as session:
        upsert_lead(
            session,
            BusinessProfile(place_id="p1", name="Test Biz", category="plumbers"),
            None,
            ScoreBreakdown(42, "C", [], "Conversion Tune-Up", "Lead with calls", []),
        )
        session.commit()
    with factory() as session:
        leads = list_leads(session)
        assert len(leads) == 1
        assert leads[0].name == "Test Biz"


def test_initialize_database_adds_missing_columns_to_old_sqlite_db(tmp_path) -> None:
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id VARCHAR(180) NOT NULL, name VARCHAR(240) NOT NULL)")
    connection.execute("CREATE TABLE website_audits (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL)")
    connection.execute("CREATE TABLE competitors (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL)")
    connection.commit()
    connection.close()

    factory = create_session_factory(path)
    initialize_database(factory)

    connection = sqlite3.connect(path)
    lead_columns = {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
    audit_columns = {row[1] for row in connection.execute("PRAGMA table_info(website_audits)")}
    competitor_columns = {row[1] for row in connection.execute("PRAGMA table_info(competitors)")}
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.execute("INSERT INTO leads (place_id, name) VALUES (?, ?)", ("legacy-google", "Legacy Google Lead"))
    google_defaults = connection.execute(
        "SELECT business_status, primary_type, pure_service_area_business, google_public_data_json, google_retrieved_at "
        "FROM leads WHERE place_id = ?",
        ("legacy-google",),
    ).fetchone()
    connection.commit()
    connection.close()

    assert {"next_follow_up_date", "starting_offer_json", "suppressed", "target_radius_miles"}.issubset(lead_columns)
    assert "verification_json" in lead_columns
    assert {"checks_json", "metrics_json", "weaknesses_json"}.issubset(audit_columns)
    assert {"rendered_checks_json", "pagespeed_status", "desktop_screenshot"}.issubset(audit_columns)
    assert (path.with_suffix(path.suffix + ".backup-before-v0105")).exists()
    assert {"competitor_place_id", "competitor_name", "website_url", "evidence_notes", "checklist_json", "match_score", "reason"}.issubset(competitor_columns)
    assert "google_snapshot_json" in competitor_columns
    assert "google_presence_assessments" in tables
    assert google_defaults == ("", "", 0, "{}", "")


def test_outreach_approval_updates_lead_and_blocks_suppressed_lead(tmp_path, outbound) -> None:
    factory = create_session_factory(tmp_path / "approval.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(
            session,
            BusinessProfile(place_id="approval-1", name="Approval Test", category="roofers"),
            None,
            ScoreBreakdown(80, "A", [], "Starter Site", "Lead with audit", []),
        )
        lead.status = LeadStatus.NEEDS_REVIEW.value
        # This fixture exercises approval/suppression, not qualification. Make its
        # commercial preconditions explicit under the v0.1.15 eligibility gate.
        lead.qualification_class = "Qualified"
        lead.qualification_confidence = "Strong"
        lead.qualification_json = '{"classification":"Qualified","confidence":"Strong"}'
        lead.phone = "555-010-9000"
        lead.verification_json = json.dumps({"business_identity": True, "audit_claims": True, "outreach": True})
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Hello", outbound.body("Draft"), proof_dependencies=[])
        session.commit()
        draft_id = draft.id
        lead_id = lead.id

    with factory() as session:
        set_outreach_approval(session, draft_id, True, sender=outbound.sender)
        session.commit()
        assert session.get(type(draft), draft_id).approved is True
        assert session.get(type(lead), lead_id).status == LeadStatus.APPROVED_TO_CONTACT.value

    with factory() as session:
        set_outreach_approval(session, draft_id, False)
        add_suppression(session, "Approval Test")
        session.commit()

    with factory() as session:
        try:
            set_outreach_approval(session, draft_id, True, sender=outbound.sender)
        except ValueError as exc:
            assert "Suppressed" in str(exc)
        else:
            raise AssertionError("Suppressed lead outreach was approved")


def test_rendered_and_pagespeed_audit_metadata_persists(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "audit-metadata.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = Lead(place_id="audit-meta", name="Audit Metadata")
        session.add(lead)
        session.flush()
        save_audit(
            session,
            lead.id,
            WebsiteAudit(
                rendered_checks={"contact_form": True},
                pagespeed_status="successful",
                rendered_status="successful",
                desktop_screenshot="C:/screens/desktop.png",
                mobile_screenshot="C:/screens/mobile.png",
            ),
        )
        session.commit()
        assert lead.audit.rendered_status == "successful"
        assert lead.audit.pagespeed_status == "successful"
        assert "contact_form" in lead.audit.rendered_checks_json
