"""Registry v5 catalog pricing and the internal minimum-earnings check (F1-F2).

Clients are always quoted a flat price. The minimum hourly earnings is an
internal check; by default MarketLens keeps the catalog flat price and warns
when it pays under the minimum, and only raises the quote when the
"raise quotes to minimum" setting is on.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from local_presence_miner.config import AppConfig, minimum_hourly_earnings, raise_quotes_to_minimum
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.pricing_repository import save_seller_proof
from local_presence_miner.database.repositories import log_activity
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.offer_registry import (
    ACQUISITION_ROUTES,
    EVIDENCE_CLASSES,
    OFFER_DEFINITIONS,
    OfferID,
    offer_definition,
    resolve_offer,
)
from local_presence_miner.domain.seller_economics import minimum_price, pricing_stage
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.seller_pricing_service import SellerPricingService


def _lead(session, package: str, place_id: str = "catalog-lead") -> Lead:
    lead = Lead(
        place_id=place_id,
        name="Catalog Pricing Prospect",
        category="roofing",
        lead_score=70,
        recommended_offer=package,
        starting_offer_json=json.dumps({"scope": ["Homepage conversion refresh", "Quote flow", "Review proof"]}),
    )
    session.add(lead)
    session.flush()
    selected = resolve_offer(package)
    assert selected.offer_id is not None
    log_activity(session, "offer_selected", json.dumps({"offer_id": selected.offer_id.value}), lead.id)
    session.flush()
    return lead


def _factory(tmp_path, name: str):
    factory = create_session_factory(tmp_path / f"{name}.sqlite3")
    initialize_database(factory)
    return factory


def test_every_offer_has_ascending_stage_quotes_mirrored_by_the_band() -> None:
    assert {offer.offer_id for offer in OFFER_DEFINITIONS} == set(OfferID)
    for offer in OFFER_DEFINITIONS:
        low, mid, high = offer.stage_quotes
        assert low < mid < high, offer.offer_id
        assert (offer.price_low, offer.price_high) == (low, high)
        assert offer.acquisition_route in ACQUISITION_ROUTES
        assert offer.evidence_class in EVIDENCE_CLASSES
        assert offer.billing in {"project", "monthly"}
        assert offer.delivery_hours > 0


@pytest.mark.parametrize("offer_id,stage_one", [
    ("five_page_service_site", 3_400),
    ("five_page_b2b_site", 3_600),
    ("full_local_authority_site", 5_500),
    ("multi_location_site", 6_900),
    ("sign_quote_intake", 2_550),
    ("sign_intake_approval_bundle", 3_400),
    ("platform_migration", 1_800),
    ("paid_fix", 500),
    ("google_presence_cleanup", 750),
    ("review_trust_builder", 850),
    ("website_care_plan", 249),
    ("consultation_project_proof", 3_200),
])
def test_stage_one_quotes_match_the_service_catalog(offer_id: str, stage_one: int) -> None:
    assert offer_definition(offer_id).stage_quotes[0] == stage_one


def test_monthly_offers_show_a_monthly_range() -> None:
    assert offer_definition("website_care_plan").price_range == "$249-$349/mo"
    assert offer_definition("five_page_service_site").price_range == "$3,400-$4,500"


@pytest.mark.parametrize("projects,stage", [(0, 1), (2, 1), (3, 2), (7, 2), (8, 3), (20, 3)])
def test_pricing_stage_thresholds(projects: int, stage: int) -> None:
    assert pricing_stage(projects) == stage


def test_minimum_price_matches_the_catalog_method() -> None:
    site = offer_definition("five_page_service_site")
    cold = minimum_price(site, rate=35, stage=1)
    assert cold is not None
    # 30 h x 1.35 + 27 cold acquisition + 6 setup + 10 sample = 83.5 h; cash 90 + 80 + 60 + 40 = 270.
    assert (cold.hours, cold.cash, cold.amount, cold.route) == (83.5, 270, 3_300, "cold")
    assert round(cold.effective_hourly(3_400)) == 36
    assert minimum_price(site, rate=45, stage=1).amount == 4_150
    warm = minimum_price(site, rate=35, stage=1, route="warm")
    assert warm.amount < cold.amount
    # Stage 2 reuses setup and the sample, so the minimum drops.
    assert minimum_price(site, rate=35, stage=2).amount < cold.amount
    # Monthly care has no acquisition or setup inside the monthly fee.
    assert minimum_price(offer_definition("website_care_plan"), rate=35).amount == 150


def test_first_time_seller_gets_the_flat_catalog_quote_not_a_discount(tmp_path) -> None:
    factory = _factory(tmp_path, "first-time")
    with factory() as session:
        lead = _lead(session, "Five-Page Service Site + Booking Route")
        pricing = SellerPricingService(minimum_hourly_earnings=35).recommend_for_lead(session, lead)
        assert pricing.pricing_stage == 1
        assert pricing.recommended == 3_400
        assert pricing.minimum_price == 3_300
        assert pricing.easy_close == 3_300  # one $500 step down is held at the minimum
        assert pricing.stretch == 3_900  # the stage-2 quote
        assert not pricing.below_minimum and not pricing.warnings
        assert any("Minimum-earnings check" in line for line in pricing.reasoning)


def test_default_keeps_the_flat_price_and_warns_when_below_minimum(tmp_path) -> None:
    factory = _factory(tmp_path, "warn")
    with factory() as session:
        lead = _lead(session, "Technical SEO Repair", place_id="tech-repair")
        pricing = SellerPricingService(minimum_hourly_earnings=35, raise_to_minimum=False).recommend_for_lead(session, lead)
        # Cold technical repair: the $2,050 flat quote pays under $35/h (needs $2,150).
        assert pricing.minimum_price == 2_150
        assert pricing.recommended == 2_050
        assert pricing.easy_close == 2_050  # no lower ask below the minimum
        assert pricing.below_minimum and not pricing.raised_to_minimum
        assert pricing.warnings and pricing.warnings[0].startswith("Below your minimum")


def test_raise_setting_lifts_the_flat_price_to_the_minimum(tmp_path) -> None:
    factory = _factory(tmp_path, "raise")
    with factory() as session:
        lead = _lead(session, "Technical SEO Repair", place_id="tech-raise")
        pricing = SellerPricingService(minimum_hourly_earnings=35, raise_to_minimum=True).recommend_for_lead(session, lead)
        assert pricing.recommended == 2_150
        assert pricing.easy_close == 2_150
        assert pricing.below_minimum and pricing.raised_to_minimum
        assert "raised to $2,150" in pricing.warnings[0]


def test_higher_minimum_warns_without_changing_the_flat_price(tmp_path) -> None:
    factory = _factory(tmp_path, "rate")
    with factory() as session:
        lead = _lead(session, "Five-Page Service Site + Booking Route", place_id="rate-lead")
        at_60 = SellerPricingService(minimum_hourly_earnings=60, raise_to_minimum=False).recommend_for_lead(session, lead)
        assert at_60.minimum_hourly_earnings == 60
        assert at_60.minimum_price == 5_450
        assert at_60.recommended == 3_400
        assert at_60.below_minimum and at_60.warnings


def test_completed_paid_projects_move_to_stage_two(tmp_path) -> None:
    factory = _factory(tmp_path, "stage")
    with factory() as session:
        lead = _lead(session, "Five-Page Service Site + Booking Route", place_id="stage-lead")
        for index in range(3):
            save_seller_proof(
                session, proof_type="Paid Project", title=f"Site {index}", niche="roofing",
                status="Completed", client_work=True, verified=True,
            )
        pricing = SellerPricingService(minimum_hourly_earnings=35).recommend_for_lead(session, lead)
        assert pricing.pricing_stage == 2
        assert pricing.recommended == 3_900
        assert pricing.stretch == 4_500


def test_pricing_settings_are_read_and_clamped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LPM_APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LPM_MINIMUM_HOURLY_EARNINGS", "45")
    monkeypatch.delenv("LPM_RAISE_QUOTES_TO_MINIMUM", raising=False)
    assert minimum_hourly_earnings() == 45
    assert raise_quotes_to_minimum() is False
    (tmp_path / "settings.json").write_text(
        json.dumps({"minimum_hourly_earnings": "55", "raise_quotes_to_minimum": "true"}), encoding="utf-8",
    )
    assert minimum_hourly_earnings() == 55
    assert raise_quotes_to_minimum() is True
    (tmp_path / "settings.json").write_text(json.dumps({"minimum_hourly_earnings": "nonsense"}), encoding="utf-8")
    assert minimum_hourly_earnings() == 35
    monkeypatch.setenv("LPM_MINIMUM_HOURLY_EARNINGS", "5000")
    monkeypatch.setenv("LPM_RAISE_QUOTES_TO_MINIMUM", "yes")
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    assert minimum_hourly_earnings() == 35
    assert raise_quotes_to_minimum() is True


def test_minimum_check_never_reaches_customer_material(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "customer.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = _lead(session, "Technical SEO Repair", place_id="customer-lead")
        customer = ProposalService(config).generate_proposal(session, lead, selected_price=2_050)
        package = LeadPackageService(config).export_package(session, lead)
    customer_text = customer.read_text(encoding="utf-8").casefold()
    assert "$2,050" in customer_text
    for private in ("minimum-earnings", "below your minimum", "walk-away", "realistic hours"):
        assert private not in customer_text
    with zipfile.ZipFile(package) as archive:
        exported = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore") for name in archive.namelist() if name.endswith((".html", ".json", ".txt", ".md"))
        ).casefold()
    for private in ("minimum-earnings", "below your minimum", "walk-away", "realistic hours"):
        assert private not in exported
