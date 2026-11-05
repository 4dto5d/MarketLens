from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.schema import Lead, OfferHistory
from local_presence_miner.domain.models import StartingOfferInput
from local_presence_miner.domain.niche_taxonomy import niche_relation, resolve_niche
from local_presence_miner.domain.offer_registry import OfferID, resolve_offer
from local_presence_miner.services.comparable_offer_service import similarity
from local_presence_miner.services.offer_builder import generate_starting_offer
from local_presence_miner.services.pricing_calibration import estimate_project_value


def test_offer_resolution_is_exact_and_never_uses_pilot_as_a_fallback() -> None:
    assert resolve_offer("Google Profile Cleanup").offer_id == OfferID.GOOGLE_PRESENCE_CLEANUP
    assert resolve_offer("Website + Google Presence Improvement").offer_id is None
    assert resolve_offer("unknown bespoke offer").offer_id is None


def test_research_required_has_no_commercial_offer_identity_or_numeric_price() -> None:
    resolution = resolve_offer("Research-first", "research_first")
    assert resolution.offer_id is None
    assert resolution.status == "research_required"

    lead = Lead(
        place_id="research-required",
        name="Research Required",
        category="roofers",
        recommended_offer="Research-first",
        recommended_offer_id="research_first",
    )
    project = estimate_project_value(lead)
    assert project.offer_id == ""
    assert project.low is None
    assert project.high is None
    assert "$0" not in project.range_text
    assert project.range_text == "Research required"

    starting_offer = generate_starting_offer(
        StartingOfferInput(
            business_name=lead.name,
            niche=lead.category,
            city="",
            recommended_offer=lead.recommended_offer,
            recommended_offer_id=lead.recommended_offer_id,
        )
    )
    assert starting_offer.offer_id == ""
    assert starting_offer.resolution_status == "research_required"


def test_semantic_correction_preserves_raw_research_label_and_is_idempotent(tmp_path) -> None:
    path = tmp_path / "existing-v0114.sqlite3"
    factory = create_session_factory(path)
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="legacy-research",
            name="Legacy Research",
            category="roofers",
            recommended_offer="Research First",
            recommended_offer_id="research_first",
            offer_resolution_state="canonical_id",
            starting_offer_json=json.dumps({"offer_name": "Research First", "offer_id": "research_first"}),
        )
        session.add(lead)
        session.commit()
        session.execute(text("DELETE FROM app_settings WHERE key='v0114_a1_offer_taxonomy_delta_migrated'"))
        session.commit()

    initialize_database(factory)
    with factory() as session:
        migrated = session.get(Lead, lead.id)
        assert migrated is not None
        assert migrated.recommended_offer == "Research First"
        assert migrated.recommended_offer_id == ""
        assert migrated.offer_resolution_state == "research_required"
        plan = json.loads(migrated.starting_offer_json)
        assert plan["legacy_offer_label"] == "Research First"
        assert plan["offer_id"] == ""
        assert plan["resolution_status"] == "research_required"
    backup = path.with_suffix(path.suffix + ".backup-before-v0114-a1")
    assert backup.exists()
    backup_bytes = backup.read_bytes()

    initialize_database(factory)
    assert backup.read_bytes() == backup_bytes


def test_taxonomy_distinguishes_related_different_and_unknown_without_false_penalty() -> None:
    assert niche_relation("roofers", "plumbers") == "related"
    assert niche_relation("dental", "roofing contractor") == "different"
    assert niche_relation("mystery trade", "roofing contractor") == "unknown"

    unknown_niche_offer = OfferHistory(
        niche="mystery trade",
        package_name="Other",
        scope_summary="",
        offer_date=date.today().isoformat(),
        initial_ask=500,
    )
    lead = Lead(place_id="roofing-target", name="Roofing Target", category="roofers", lead_score=0)
    score, reasons = similarity(unknown_niche_offer, lead, "Other", "", 500, 900)
    assert score == 2
    assert "different niche" not in reasons


def test_taxonomy_handles_adversarial_categories_without_substring_collisions() -> None:
    assert resolve_niche("residential cleaning").canonical_id == "residential_cleaning"
    assert resolve_niche("residential painter").canonical_id == "painting"
    assert resolve_niche("home automation").canonical_id == "home_automation"
    assert niche_relation("home automation", "automotive repair") == "different"
    assert niche_relation("roofers", "roofing contractor") == "same"
