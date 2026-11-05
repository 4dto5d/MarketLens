from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import select

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    add_suppression,
    is_suppressed,
    save_competitors,
    save_outreach_draft,
    set_outreach_approval,
    update_lead_fields,
    upsert_lead,
)
from local_presence_miner.database.schema import GooglePresenceAssessment
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.domain.models import BusinessProfile, CompetitorMatch, ScoreBreakdown
from local_presence_miner.services.google_places import haversine_miles
from local_presence_miner.services.google_presence_service import GooglePresenceService
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.v0111_backfill_service import V0111BackfillService


def score() -> ScoreBreakdown:
    return ScoreBreakdown(70, "A", [], "Focused Improvement", "Use evidence", ["Observed gap"])


def rich_profile(place_id: str = "rich") -> BusinessProfile:
    return BusinessProfile(
        place_id=place_id,
        name="Rich Roofing",
        category="roofers",
        address="1 Main St",
        phone="555-0100",
        website="https://rich.example",
        google_maps_url="https://maps.example/rich",
        rating=4.8,
        review_count=120,
        business_types=["roofing_contractor"],
        has_hours=True,
        photo_count=12,
        latitude=43.0,
        longitude=-83.0,
        business_status="OPERATIONAL",
        primary_type="roofing_contractor",
        retrieved_at="2026-08-28T12:00:00+00:00",
        raw={"_details_retrieved": True, "_detail_fields_requested": True, "_selected_for_details": True},
    )


def test_suppression_is_exact_not_substring(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "suppression.sqlite3")
    initialize_database(factory)
    with factory() as session:
        smith = upsert_lead(session, BusinessProfile("smith", "Smith Roofing", "roofers"), None, score())
        goldsmith = upsert_lead(session, BusinessProfile("goldsmith", "Goldsmith HVAC", "hvac"), None, score())
        session.commit()
        add_suppression(session, "Smith Roofing", "opt out")
        session.commit()
        session.refresh(smith)
        session.refresh(goldsmith)
        assert smith.suppressed is True
        assert goldsmith.suppressed is False
        assert is_suppressed(session, smith) is True
        assert is_suppressed(session, goldsmith) is False


def test_nearby_business_wording_requires_competitor_review(tmp_path, outbound) -> None:
    factory = create_session_factory(tmp_path / "verification.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(session, rich_profile("verify"), None, score())
        lead.verification_json = json.dumps({
            "business_identity": True,
            "audit_claims": True,
            "outreach": True,
            "website": True,
            "competitors": False,
        })
        draft = save_outreach_draft(
            session,
            lead.id,
            OutreachKind.INITIAL_EMAIL,
            "Quick comparison",
            "I compared your public site against 3 nearby businesses.",
        )
        session.flush()
        with pytest.raises(ValueError, match="Competitors reviewed"):
            set_outreach_approval(session, draft.id, True, sender=outbound.sender)


def test_failed_rich_refresh_preserves_last_known_good_google_data(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "google-stale.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(session, rich_profile(), None, score())
        session.commit()
        lead_id = lead.id

    failed = BusinessProfile(
        place_id="rich",
        name="Rich Roofing",
        category="roofers",
        address="1 Main St",
        google_maps_url="https://maps.example/rich",
        latitude=43.0,
        longitude=-83.0,
        business_status="OPERATIONAL",
        primary_type="roofing_contractor",
        retrieved_at="2026-08-28T13:00:00+00:00",
        raw={
            "_details_retrieved": False,
            "_detail_fields_requested": True,
            "_selected_for_details": True,
            "details_error": "temporary 503",
        },
    )
    with factory() as session:
        lead = upsert_lead(session, failed, None, score())
        GooglePresenceService().evaluate_and_store(session, lead)
        qualification = QualificationService().evaluate_and_store(session, lead)
        session.commit()
        assert lead.id == lead_id
        assert lead.website == "https://rich.example"
        assert lead.phone == "555-0100"
        assert lead.rating == 4.8
        assert lead.review_count == 120
        assert lead.google_rich_data_stale is True
        assert lead.last_google_refresh_error == "temporary 503"
        assert qualification.classification == "Hold"


def test_evidence_change_invalidates_verification_and_approval(tmp_path, outbound) -> None:
    factory = create_session_factory(tmp_path / "evidence.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(session, rich_profile("evidence"), None, score())
        # The test isolates verification invalidation after approval. Its old
        # synthetic score is intentionally unmapped, so make eligibility explicit.
        lead.qualification_class = "Qualified"
        lead.qualification_confidence = "Strong"
        lead.qualification_json = '{"classification":"Qualified","confidence":"Strong"}'
        lead.recommended_offer = "Conversion Tune-Up"
        lead.recommended_offer_id = "conversion_tune_up"
        lead.offer_resolution_state = "canonical_id"
        old_profile = rich_profile("comp-old")
        save_competitors(session, lead.id, [CompetitorMatch("comp-old", "Old Competitor", 80, "same niche")], {"comp-old": old_profile})
        lead.verification_json = json.dumps({
            "business_identity": True,
            "website": True,
            "audit_claims": True,
            "competitors": True,
            "outreach": True,
        })
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Hi", outbound.body("Compared with nearby businesses"), proof_dependencies=[])
        session.flush()
        set_outreach_approval(session, draft.id, True, sender=outbound.sender)
        session.flush()
        assert draft.approved is True

        new_profile = rich_profile("comp-new")
        save_competitors(session, lead.id, [CompetitorMatch("comp-new", "New Competitor", 82, "same niche")], {"comp-new": new_profile})
        session.flush()
        values = json.loads(lead.verification_json)
        assert values["competitors"] is False
        assert values["outreach"] is False
        assert draft.approved is False


def test_manual_public_identity_change_invalidates_old_verification(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "manual-change.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(session, rich_profile("manual"), None, score())
        lead.verification_json = json.dumps({"website": True, "audit_claims": True, "outreach": True})
        session.flush()
        update_lead_fields(session, lead.id, website="https://different.example")
        values = json.loads(lead.verification_json)
        assert values["website"] is False
        assert values["audit_claims"] is False
        assert values["outreach"] is False


def test_v0111_migration_creates_dedicated_backup_and_refresh_columns(tmp_path) -> None:
    path = tmp_path / "old-v0110.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id VARCHAR(180) NOT NULL, name VARCHAR(240) NOT NULL)")
    connection.execute(
        "CREATE TABLE contact_interactions "
        "(id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, interaction_datetime VARCHAR(40) NOT NULL, "
        "branch_path_json TEXT NOT NULL DEFAULT '[]')"
    )
    connection.commit()
    connection.close()

    factory = create_session_factory(path)
    initialize_database(factory)
    assert path.with_suffix(path.suffix + ".backup-before-v0111").exists()
    connection = sqlite3.connect(path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.close()
    assert "google_presence_assessments" in tables
    assert {
        "last_rich_google_retrieved_at",
        "last_google_refresh_attempt_at",
        "last_google_refresh_error",
        "google_rich_data_stale",
    }.issubset(columns)


def test_v0111_backfill_only_fills_missing_google_assessments(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "backfill.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(session, rich_profile("backfill"), None, score())
        session.commit()
        assert session.execute(select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead.id)).scalar_one_or_none() is None
        changed = V0111BackfillService().run(session, SenderInfo())
        session.commit()
        assert changed == 1
        assert session.execute(select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead.id)).scalar_one_or_none() is not None
        assert lead.qualification_json not in {"", "{}"}
        assert V0111BackfillService().run(session, SenderInfo()) == 0


def test_radius_distance_helper_enforces_boundary() -> None:
    # Roughly 1 degree latitude ~= 69 miles. These deliberately straddle 10 miles.
    assert haversine_miles(39.0, -108.5, 39.13, -108.5) < 10
    assert haversine_miles(39.0, -108.5, 39.16, -108.5) > 10
