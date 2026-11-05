from __future__ import annotations

import json
import sqlite3

import pytest

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    delete_contact_interaction,
    save_audit,
    save_contact_interaction,
    save_outreach_draft,
    set_outreach_approval,
    update_lead_fields,
)
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.enums import LeadStatus, OutreachKind
from local_presence_miner.domain.models import WebsiteAudit
from local_presence_miner.domain.verification import assess_verification
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.ui.widgets.industry_intelligence_widget import industry_summary_html


def make_lead(session, *, place_id: str = "lead-1", website: str = "https://example.com", phone: str = "555-0101") -> Lead:
    lead = Lead(
        place_id=place_id,
        name="Integrity Test",
        website=website,
        phone=phone,
        status=LeadStatus.NEEDS_REVIEW.value,
        qualification_class="High Priority",
        qualification_json='{"qualification_class":"High Priority"}',
        recommended_offer_id="one_page_conversion_site",
        offer_resolution_state="canonical_id",
    )
    session.add(lead)
    session.flush()
    return lead


def complete_verification(lead: Lead) -> None:
    lead.verification_json = json.dumps(
        {
            "business_identity": True,
            "phone": True,
            "website": True,
            "google_url": True,
            "competitors": True,
            "audit_claims": True,
            "offer": True,
            "price": True,
            "outreach": True,
        }
    )


def test_editing_older_interaction_does_not_replace_newest_summary(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "contacts.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        older = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-08-11T09:00:45",
            method="Email",
            direction="Outbound",
            outcome="Sent",
            notes="Original",
            follow_up_date="2026-08-12",
        )
        save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-08-15T14:30",
            method="Phone",
            direction="Inbound",
            outcome="Interested",
            notes="Newest",
            follow_up_date="2026-08-20",
        )
        older_id = older.id
        lead_id = lead.id
        session.commit()

    with factory() as session:
        save_contact_interaction(
            session,
            lead_id,
            interaction_id=older_id,
            interaction_datetime="2026-08-11 10:15",
            method="Email",
            direction="Outbound",
            outcome="Corrected",
            notes="Edited older entry",
            follow_up_date="2026-08-13",
        )
        session.commit()
        lead = session.get(Lead, lead_id)
        assert lead.last_contacted_date == "2026-08-15"
        assert lead.contact_method == "Phone"
        assert lead.contact_outcome == "Interested"
        assert lead.next_follow_up_date == "2026-08-20"
        assert session.get(type(older), older_id).interaction_datetime == "2026-08-11T10:15"


def test_deleting_newest_falls_back_and_deleting_final_clears_summary(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "deletion.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        older = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-08-10T08:00",
            method="Email",
            direction="Outbound",
            outcome="Sent",
            notes="",
            follow_up_date="2026-08-12",
        )
        newest = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-08-12T09:00",
            method="Phone",
            direction="Outbound",
            outcome="Voicemail",
            notes="",
            follow_up_date="2026-08-15",
        )
        lead_id, older_id, newest_id = lead.id, older.id, newest.id
        session.commit()

    with factory() as session:
        delete_contact_interaction(session, newest_id)
        session.commit()
        lead = session.get(Lead, lead_id)
        assert (lead.last_contacted_date, lead.contact_method, lead.contact_outcome, lead.next_follow_up_date) == (
            "2026-08-10",
            "Email",
            "Sent",
            "2026-08-12",
        )
        delete_contact_interaction(session, older_id)
        session.commit()
        lead = session.get(Lead, lead_id)
        assert (lead.last_contacted_date, lead.contact_method, lead.contact_outcome, lead.next_follow_up_date) == (
            "",
            "",
            "",
            "",
        )


def test_contact_dates_are_canonical_and_draft_link_is_lead_scoped(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "canonical.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        other = make_lead(session, place_id="other")
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Hello", "Body")
        other_draft = save_outreach_draft(session, other.id, OutreachKind.INITIAL_EMAIL, "Other", "Body")
        interaction = save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-08-11 09:30:59",
            method="Email",
            direction="Outbound",
            outcome="Sent",
            notes="",
            follow_up_date="2026-08-14",
            outreach_draft_id=draft.id,
        )
        assert interaction.interaction_datetime == "2026-08-11T09:30"
        assert interaction.outreach_draft_id == draft.id
        with pytest.raises(ValueError, match="does not belong"):
            save_contact_interaction(
                session,
                lead.id,
                interaction_datetime="2026-08-12T10:00",
                method="Email",
                direction="Outbound",
                outcome="",
                notes="",
                outreach_draft_id=other_draft.id,
            )
        with pytest.raises(ValueError, match="ISO format"):
            save_contact_interaction(
                session,
                lead.id,
                interaction_datetime="next Tuesday",
                method="Phone",
                direction="Outbound",
                outcome="",
                notes="",
            )


def test_verification_gates_approval_and_unchecking_revokes_it(tmp_path, outbound) -> None:
    factory = create_session_factory(tmp_path / "verification.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Hello", outbound.body("I reviewed your website."), proof_dependencies=[])
        lead.verification_json = json.dumps({"business_identity": True, "audit_claims": True, "outreach": True})
        session.flush()
        with pytest.raises(ValueError, match="Website/public presence verified"):
            set_outreach_approval(session, draft.id, True, sender=outbound.sender)

        complete_verification(lead)
        set_outreach_approval(session, draft.id, True, sender=outbound.sender)
        assert draft.approved is True
        assert lead.status == LeadStatus.APPROVED_TO_CONTACT.value

        incomplete = json.loads(lead.verification_json)
        incomplete["outreach"] = False
        update_lead_fields(session, lead.id, verification_json=json.dumps(incomplete))
        assert draft.approved is False
        assert lead.status == LeadStatus.NEEDS_REVIEW.value


def test_phone_and_competitor_requirements_are_conditional(tmp_path, outbound) -> None:
    factory = create_session_factory(tmp_path / "conditional.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session, phone="555-0101")
        complete_verification(lead)
        values = json.loads(lead.verification_json)
        values["phone"] = False
        values["competitors"] = False
        lead.verification_json = json.dumps(values)
        competitor = CompetitorRecord(
            lead_id=lead.id,
            competitor_place_id="competitor-1",
            competitor_name="Nearby Co",
        )
        session.add(competitor)
        session.flush()
        # Establish the commercial input before drafting: a later competitor
        # addition correctly makes an earlier draft stale at approval time.
        email = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Hello", outbound.body("I reviewed your website."), proof_dependencies=[])
        call = save_outreach_draft(session, lead.id, OutreachKind.CALL_OPENING, "", "Call opening")
        competitor_email = save_outreach_draft(
            session,
            lead.id,
            OutreachKind.REPORT_DELIVERY,
            "Comparison",
            "Your competitors make contacting them easier.",
        )
        session.flush()
        set_outreach_approval(session, email.id, True, sender=outbound.sender)
        with pytest.raises(ValueError, match="Phone or intended contact verified"):
            set_outreach_approval(session, call.id, True)
        with pytest.raises(ValueError, match="Competitors reviewed"):
            set_outreach_approval(session, competitor_email.id, True)


def test_internal_report_embeds_existing_screenshot_and_ignores_missing(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "report.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    screenshot = tmp_path / "desktop.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\nportable-test")
    with factory() as session:
        lead = make_lead(session)
        save_audit(
            session,
            lead.id,
            WebsiteAudit(
                reachable=True,
                desktop_screenshot=str(screenshot),
                mobile_screenshot=str(tmp_path / "missing.png"),
            ),
        )
        session.flush()
        session.expire(lead, ["audit"])
        path = ReportService(config).generate_report(session, lead, "internal")
    html = path.read_text(encoding="utf-8")
    assert "data:image/png;base64," in html
    assert "Desktop Evidence Screenshot" in html
    assert "Mobile Evidence Screenshot" not in html
    assert str(screenshot) not in html


def test_v0106_backup_and_date_normalization_for_existing_database(tmp_path) -> None:
    path = tmp_path / "existing-v0105.sqlite3"
    factory = create_session_factory(path)
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        session.commit()
        lead_id = lead.id
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO contact_interactions "
        "(lead_id, interaction_datetime, method, direction, outcome, notes, follow_up_date, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (lead_id, "2026-08-11 09:30:45", "Email", "Outbound", "Sent", "", "2026-08-14"),
    )
    connection.commit()
    connection.close()

    initialize_database(factory)

    assert path.with_suffix(path.suffix + ".backup-before-v0106").exists()
    connection = sqlite3.connect(path)
    saved = connection.execute("SELECT interaction_datetime FROM contact_interactions").fetchone()[0]
    connection.close()
    assert saved == "2026-08-11T09:30"


def test_review_state_and_industry_export_are_truthful() -> None:
    lead = Lead(place_id="state", name="State", website="https://example.com")
    assert assess_verification(lead).state == "Unverified"
    lead.verification_json = json.dumps({"business_identity": True})
    assert assess_verification(lead).state == "Verification incomplete"
    complete_verification(lead)
    assert assess_verification(lead).state == "Ready for outreach"
    lead.suppressed = True
    assert assess_verification(lead).state == "Suppressed / blocked"
    exported = industry_summary_html("Roofers < collected sample")
    assert "Roofers &lt; collected sample" in exported
    assert "Roofers < collected sample" not in exported
