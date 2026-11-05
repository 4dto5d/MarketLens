from __future__ import annotations

import json
import sqlite3

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import save_audit
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.models import WebsiteAudit
from local_presence_miner.services.qualification_service import QualificationService, review_activity_points


def weak_audit() -> WebsiteAudit:
    return WebsiteAudit(
        url="https://small.example",
        reachable=True,
        status_code=200,
        final_url="https://small.example",
        checks={
            "https": True,
            "viewport": True,
            "has_title": True,
            "has_meta_description": False,
            "has_h1": True,
            "tap_to_call": False,
            "contact_form": False,
            "booking_or_quote_language": False,
            "service_pages": True,
            "trust_signals": False,
            "map_embed": False,
            "local_schema": False,
            "social_links": False,
            "clear_primary_cta": False,
            "local_wording": True,
        },
    )


def strong_audit() -> WebsiteAudit:
    keys = [
        "https",
        "viewport",
        "has_title",
        "has_meta_description",
        "has_h1",
        "tap_to_call",
        "contact_form",
        "booking_or_quote_language",
        "service_pages",
        "trust_signals",
        "map_embed",
        "local_schema",
        "social_links",
        "clear_primary_cta",
        "local_wording",
    ]
    return WebsiteAudit(
        url="https://strong.example",
        reachable=True,
        status_code=200,
        final_url="https://strong.example",
        checks={key: True for key in keys},
    )


def add_competitor(session, lead: Lead, *, place_id: str = "comp-1") -> Lead:
    competitor = Lead(
        place_id=place_id,
        name="Strong Local Competitor",
        category=lead.category,
        website="https://strong.example",
        rating=4.7,
        review_count=80,
        lead_score=20,
    )
    session.add(competitor)
    session.flush()
    save_audit(session, competitor.id, strong_audit())
    session.add(
        CompetitorRecord(
            lead_id=lead.id,
            competitor_place_id=competitor.place_id,
            competitor_name=competitor.name,
            website_url=competitor.website,
            match_score=88,
            reason="Same local service category and nearby.",
        )
    )
    session.flush()
    return competitor


def test_review_count_is_weighted_not_a_hard_cutoff() -> None:
    assert review_activity_points(4) > 0
    assert review_activity_points(12) > review_activity_points(4)
    assert review_activity_points(40) > review_activity_points(12)


def test_small_healthy_roofer_can_be_high_priority(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "small-roofer.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="small-roofer",
            name="Small Family Roofing",
            category="roofing contractor",
            phone="555-0100",
            website="https://small.example",
            address="1 Main St",
            rating=4.8,
            review_count=12,
            has_hours=True,
            photo_count=8,
            lead_score=76,
            priority="A",
            recommended_offer="One-Page Conversion Site + Google Cleanup",
        )
        session.add(lead)
        session.flush()
        save_audit(session, lead.id, weak_audit())
        add_competitor(session, lead)
        session.flush()
        result = QualificationService().evaluate_and_store(session, lead)
        assert result.score >= 65
        assert result.classification in {"High Priority", "Demo Priority"}
        assert not any("review" in item.lower() and "reject" in item.lower() for item in result.disconfirmers)
        assert lead.sales_priority_score == result.score
        assert json.loads(lead.qualification_json)["classification"] == result.classification


def test_more_reviews_do_not_rescue_a_low_opportunity_prospect(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "strong-site.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="busy-salon",
            name="Busy Salon",
            category="salon",
            phone="555-0199",
            website="https://strong.example",
            address="2 Main St",
            rating=4.8,
            review_count=180,
            has_hours=True,
            photo_count=10,
            lead_score=20,
            priority="C",
            recommended_offer="Monitoring + Review Growth Plan",
        )
        session.add(lead)
        session.flush()
        save_audit(session, lead.id, strong_audit())
        result = QualificationService().evaluate_and_store(session, lead)
        assert result.score < 65
        assert result.classification in {"Hold", "Qualified"}
        assert any("little improvement" in item.lower() or "strong" in item.lower() for item in result.disconfirmers)


def test_zero_reviews_alone_does_not_force_reject(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "zero-review.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="new-hvac",
            name="New HVAC Co",
            category="hvac contractor",
            phone="555-0177",
            website="https://small.example",
            address="3 Main St",
            rating=None,
            review_count=0,
            has_hours=True,
            photo_count=6,
            lead_score=82,
            priority="A",
            recommended_offer="One-Page Conversion Site + Google Cleanup",
        )
        session.add(lead)
        session.flush()
        save_audit(session, lead.id, weak_audit())
        add_competitor(session, lead, place_id="hvac-comp")
        result = QualificationService().evaluate_and_store(session, lead)
        assert result.classification != "Reject"
        assert "No public reviews were collected; activity needs more manual confirmation." in result.unknowns


def test_v0109_migration_adds_qualification_fields_and_backup(tmp_path) -> None:
    path = tmp_path / "old-v018.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id VARCHAR(180) NOT NULL, name VARCHAR(240) NOT NULL, lead_score INTEGER NOT NULL DEFAULT 0)"
    )
    connection.commit()
    connection.close()
    factory = create_session_factory(path)
    initialize_database(factory)
    connection = sqlite3.connect(path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
    connection.close()
    assert {"sales_priority_score", "qualification_class", "qualification_confidence", "qualification_json"}.issubset(columns)
    assert path.with_suffix(path.suffix + ".backup-before-v0109").exists()
