from __future__ import annotations

import json

import pytest

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import save_audit, upsert_lead
from local_presence_miner.database.schema import CompetitorRecord, GooglePresenceAssessment, Lead
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown, SearchCriteria, WebsiteAudit
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan
from local_presence_miner.services.google_places import (
    DETAIL_FIELD_MASK,
    DISCOVERY_FIELD_MASK,
    ENRICHMENT_LIMITS,
    REVIEW_DETAILS_FIELD_MASK,
    GooglePlacesClient,
    estimate_places_api_calls,
    parse_place,
    select_preliminary_candidates,
)
from local_presence_miner.services.google_presence_service import (
    GooglePresenceService,
    assessment_to_dict,
    compare_with_competitors,
)
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.search_workflow import SearchWorkflow
from local_presence_miner.time_utils import utc_now


def _audit(strong: bool) -> WebsiteAudit:
    checks = {
        "https": strong,
        "viewport": strong,
        "has_title": True,
        "has_meta_description": strong,
        "has_h1": True,
        "tap_to_call": strong,
        "contact_form": strong,
        "booking_or_quote_language": strong,
        "service_pages": strong,
        "trust_signals": strong,
        "map_embed": strong,
        "local_schema": strong,
        "social_links": strong,
        "clear_primary_cta": strong,
        "local_wording": True,
    }
    return WebsiteAudit(
        url="https://example.test",
        reachable=True,
        status_code=200,
        final_url="https://example.test",
        checks=checks,
        strengths=["Strong site"] if strong else [],
        weaknesses=[] if strong else ["Weak conversion path"],
    )


def _profile(
    place_id: str,
    *,
    rating: float | None = 4.7,
    reviews: int = 45,
    website: bool = True,
    phone: bool = True,
    hours: bool = True,
    photos: int = 12,
    status: str = "OPERATIONAL",
    service_area: bool = False,
) -> BusinessProfile:
    return BusinessProfile(
        place_id=place_id,
        name=f"Business {place_id}",
        category="roofers",
        address="" if service_area else "1 Main St",
        phone="555-0100" if phone else "",
        website="https://example.test" if website else "",
        google_maps_url=f"https://maps.example/{place_id}",
        rating=rating,
        review_count=reviews,
        business_types=["roofing_contractor"],
        has_hours=hours,
        photo_count=photos,
        business_status=status,
        primary_type="roofing_contractor",
        pure_service_area_business=service_area,
        retrieved_at=utc_now().isoformat(),
    )


def _lead(session, profile: BusinessProfile, *, strong_site: bool, lead_score: int = 70) -> Lead:
    lead = upsert_lead(
        session,
        profile,
        None,
        ScoreBreakdown(lead_score, "A", [], "Focused Improvement", "Use evidence", ["Observed public gap"]),
    )
    if profile.website:
        save_audit(session, lead.id, _audit(strong_site))
    session.flush()
    return lead


def _add_competitors(session, lead: Lead, *, ratings=(4.6, 4.7, 4.5), reviews=(120, 85, 200)) -> None:
    for index, (rating, review_count) in enumerate(zip(ratings, reviews, strict=True), start=1):
        session.add(
            CompetitorRecord(
                lead_id=lead.id,
                competitor_place_id=f"comp-{index}",
                competitor_name=f"Competitor {index}",
                match_score=80,
                reason="Comparable local roofer",
                google_snapshot_json=json.dumps(
                    {
                        "place_id": f"comp-{index}",
                        "name": f"Competitor {index}",
                        "rating": rating,
                        "review_count": review_count,
                        "website": True,
                        "phone": True,
                        "hours": True,
                        "photo_count": 20,
                        "details_retrieved": True,
                        "retrieved_at": utc_now().isoformat(),
                    }
                ),
            )
        )
    session.flush()


def test_places_parser_retains_supported_public_fields() -> None:
    profile = parse_place(
        {
            "id": "place-1",
            "displayName": {"text": "Public Roofer"},
            "formattedAddress": "1 Main St",
            "nationalPhoneNumber": "555-0100",
            "internationalPhoneNumber": "+15550100",
            "websiteUri": "https://roofer.example",
            "googleMapsUri": "https://maps.example/place-1",
            "businessStatus": "OPERATIONAL",
            "primaryType": "roofing_contractor",
            "types": ["roofing_contractor"],
            "rating": 4.8,
            "userRatingCount": 33,
            "regularOpeningHours": {"weekdayDescriptions": ["Monday: 8-5"]},
            "currentOpeningHours": {"openNow": True},
            "photos": [{"name": "one"}],
            "reviews": [{"rating": 5}],
            "pureServiceAreaBusiness": True,
            "priceLevel": "PRICE_LEVEL_MODERATE",
            "priceRange": {"startPrice": {"units": "100"}},
        },
        "roofers",
    )
    assert profile.business_status == "OPERATIONAL"
    assert profile.primary_type == "roofing_contractor"
    assert profile.pure_service_area_business is True
    assert profile.public_reviews == [{"rating": 5}]
    assert profile.current_hours_available is True
    assert profile.retrieved_at


def test_places_uses_preliminary_shortlist_before_rich_details(monkeypatch) -> None:
    class Response:
        ok = True
        status_code = 200
        text = ""

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    seen = {"post_mask": "", "get_masks": [], "include_service_area": False}

    def fake_post(_url, *, json, headers, timeout, allow_redirects):
        assert allow_redirects is False
        del timeout
        if json["textQuery"] == "Flint, MI":
            return Response(
                {
                    "places": [
                        {
                            "id": "flint-center",
                            "displayName": {"text": "Flint"},
                            "formattedAddress": "Flint, MI, USA",
                            "types": ["locality"],
                            "location": {"latitude": 43.0125, "longitude": -83.6875},
                        }
                    ]
                }
            )
        seen["post_mask"] = headers["X-Goog-FieldMask"]
        seen["include_service_area"] = json["includePureServiceAreaBusinesses"]
        return Response(
            {
                "places": [
                    {
                        "id": f"p-{index}",
                        "displayName": {"text": "Walmart Roofing" if index == 0 else f"Place {index}"},
                        "businessStatus": "CLOSED_TEMPORARILY" if index == 1 else "OPERATIONAL",
                        "primaryType": "roofing_contractor",
                        "types": ["roofing_contractor"],
                        "formattedAddress": "1 Main St",
                        "location": {"latitude": 43.0125 + index * 0.001, "longitude": -83.6875},
                    }
                    for index in range(10)
                ]
            }
        )

    def fake_get(url, *, headers, timeout, allow_redirects):
        assert allow_redirects is False
        del timeout
        seen["get_masks"].append(headers["X-Goog-FieldMask"])
        place_id = url.rsplit("/", 1)[-1]
        return Response({"id": place_id, "displayName": {"text": place_id}, "websiteUri": "https://example.test"})

    monkeypatch.setattr("local_presence_miner.services.google_places.requests.post", fake_post)
    monkeypatch.setattr("local_presence_miner.services.google_places.requests.get", fake_get)
    profiles = GooglePlacesClient("test-key").search(
        SearchCriteria("Flint", "MI", "roofers", max_results=10, google_data_depth="Economy")
    )
    assert len(profiles) == ENRICHMENT_LIMITS["Economy"]
    assert seen["post_mask"] == DISCOVERY_FIELD_MASK
    assert "places.reviews" not in DISCOVERY_FIELD_MASK
    assert "places.rating" not in DISCOVERY_FIELD_MASK
    assert seen["include_service_area"] is True
    enriched_ids = {profile.place_id for profile in profiles if profile.raw.get("_details_retrieved")}
    assert len(seen["get_masks"]) == ENRICHMENT_LIMITS["Economy"]
    assert "p-0" not in enriched_ids
    assert "p-1" not in enriched_ids
    assert {"p-8", "p-9"}.issubset(enriched_ids)
    assert all(profile.raw.get("_selected_for_details") for profile in profiles)
    assert all(mask == DETAIL_FIELD_MASK for mask in seen["get_masks"])
    assert "reviews" not in DETAIL_FIELD_MASK
    assert "priceLevel" not in DETAIL_FIELD_MASK
    assert REVIEW_DETAILS_FIELD_MASK.endswith(",reviews")


def test_non_enriched_discovery_fields_remain_unknown_and_are_not_scored_as_missing(tmp_path) -> None:
    profile = parse_place(
        {
            "id": "discovery-only",
            "displayName": {"text": "Discovery Only Roofer"},
            "businessStatus": "OPERATIONAL",
            "primaryType": "roofing_contractor",
            "types": ["roofing_contractor"],
            "formattedAddress": "1 Main St",
        },
        "roofers",
    )
    profile = BusinessProfile(**{**profile.__dict__, "raw": {**profile.raw, "_details_retrieved": False, "_detail_fields_requested": False}})

    from local_presence_miner.domain.scoring import score_lead

    score = score_lead(profile, WebsiteAudit())
    labels = {factor.label for factor in score.factors}
    signals = set(score.target_signals)
    assert "No website listed" not in labels | signals
    assert "Profile appears incomplete" not in labels | signals
    assert "Few public photos" not in labels
    assert "Would benefit from 10-20 stronger reviews" not in labels
    assert score.recommended_offer == "Research-first"

    factory = create_session_factory(tmp_path / "discovery-only.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead(session, profile, strong_site=False, lead_score=score.total)
        result = GooglePresenceService().evaluate_and_store(session, lead)
        qualification = QualificationService().evaluate_and_store(session, lead)
        combined_gaps = " ".join(result.observed_gaps).lower()
        combined_unknowns = " ".join((*result.unknowns, *qualification.unknowns)).lower()
        assert "no website" not in combined_gaps
        assert "0 public review" not in combined_gaps
        assert "not requested" in combined_unknowns
        assert qualification.classification == "Hold"


def test_depth_caps_call_estimate_and_safe_live_test_are_deterministic() -> None:
    assert ENRICHMENT_LIMITS == {"Economy": 8, "Balanced": 20, "Deep Prospecting": 40}
    balanced = SearchCriteria("Flint", "MI", "roofers", max_results=100, google_data_depth="Balanced")
    assert estimate_places_api_calls(balanced) == (4, 20, 24)
    safe = SearchCriteria("Flint", "MI", "roofers", max_results=100, google_data_depth="Economy", safe_live_test=True)
    assert estimate_places_api_calls(safe) == (2, 5, 7)

    candidates = [
        BusinessProfile(
            place_id=f"candidate-{index}",
            name="Walmart Roofing" if index == 0 else f"Local Roofer {index}",
            category="roofers",
            business_status="OPERATIONAL",
            primary_type="roofing_contractor",
            business_types=["roofing_contractor"],
            address="1 Main St",
            search_position=index + 1,
        )
        for index in range(10)
    ]
    selected = select_preliminary_candidates(candidates, "roofers", 8)
    assert len(selected) == 8
    assert "candidate-0" not in selected
    assert "candidate-8" in selected


@pytest.mark.parametrize(
    ("profile", "strong_site", "expected_action"),
    [
        (_profile("strong-google-weak-site", website=False, reviews=90, photos=20), False, "Website-only"),
        (_profile("weak-google-strong-site", rating=4.0, reviews=4, phone=False, hours=False, photos=0), True, "Google Presence-only"),
        (_profile("both-weak", rating=3.8, reviews=7, website=False, phone=False, hours=False, photos=0), False, "Website + Google Presence"),
        (_profile("both-strong", rating=4.9, reviews=220, photos=30), True, "Research-first / already strong"),
    ],
)
def test_offer_mode_follows_separate_website_and_google_opportunity(tmp_path, profile, strong_site, expected_action) -> None:
    factory = create_session_factory(tmp_path / f"{profile.place_id}.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead(session, profile, strong_site=strong_site)
        _add_competitors(session, lead)
        result = GooglePresenceService().evaluate_and_store(session, lead)
        QualificationService().evaluate_and_store(session, lead)
        session.commit()
        assert result.recommended_action == expected_action
        plan, _pricing = build_adaptive_sales_plan(session, lead)
        # The Google assessment remains descriptive, not authority to infer a
        # new paid product from the fixture's unmapped "Focused Improvement".
        assert plan.smart_offer.offer_type == "no_paid_recommendation"
        assert _pricing.price_available is False
        assert plan.smart_offer.scope == ()


def test_low_review_business_is_viable_and_service_area_is_not_penalized_as_missing_address(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "low-review.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead(session, _profile("low-review", reviews=3, service_area=True), strong_site=False)
        _add_competitors(session, lead, reviews=(8, 12, 20))
        result = GooglePresenceService().evaluate_and_store(session, lead)
        qualification = QualificationService().evaluate_and_store(session, lead)
        assert result.opportunity_score > 0
        assert "address" not in " ".join(result.observed_gaps).lower()
        assert qualification.classification != "Reject"


def test_permanently_closed_and_insufficient_data_are_conservative(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "conservative.sqlite3")
    initialize_database(factory)
    with factory() as session:
        closed = _lead(
            session,
            _profile("closed", status="CLOSED_PERMANENTLY", website=False, phone=False, reviews=40),
            strong_site=False,
        )
        closed_result = GooglePresenceService().evaluate_and_store(session, closed)
        assert closed_result.opportunity_score == 0
        assert QualificationService().evaluate(session, closed).classification == "Reject"

        unknown = _lead(
            session,
            _profile("unknown", status="", website=False, phone=False, rating=None, reviews=0, hours=False, photos=0),
            strong_site=False,
        )
        unknown.primary_type = ""
        unknown.business_types_json = "[]"
        unknown.google_maps_url = ""
        unknown.google_retrieved_at = ""
        unknown_result = GooglePresenceService().evaluate_and_store(session, unknown)
        assert unknown_result.confidence == "Low"
        assert unknown_result.opportunity_score <= 35
        assert unknown_result.recommended_action == "Research-first / insufficient evidence"
        assert any("not requested" in item for item in unknown_result.unknowns)
        assert not any("public phone was not returned" in item.lower() for item in unknown_result.observed_gaps)


def test_google_opportunity_is_a_transparent_sales_priority_input(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "qualification.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead(session, _profile("qualification", reviews=8, phone=False, hours=False, photos=0), strong_site=True)
        _add_competitors(session, lead)
        GooglePresenceService().evaluate_and_store(session, lead)
        result = QualificationService().evaluate_and_store(session, lead)
        factor = next(item for item in result.factors if item.key == "google_presence_opportunity")
        assert 0 <= factor.points <= 12
        assert "Google Presence Opportunity" in factor.evidence


def test_demo_mode_persists_four_google_presence_scenarios_without_network(tmp_path, monkeypatch) -> None:
    factory = create_session_factory(tmp_path / "demo.sqlite3")
    initialize_database(factory)
    config = AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "demo.sqlite3",
        output_dir=tmp_path / "output",
        log_path=tmp_path / "app.log",
    )
    monkeypatch.setattr(
        "local_presence_miner.services.google_places.requests.post",
        lambda *args, **kwargs: pytest.fail("Demo Mode must not call Google Places"),
    )
    search_id = SearchWorkflow(config, factory).run(
        SearchCriteria("Flint", "MI", "roofers", max_results=4, top_mockups=0, demo_mode=True)
    )
    with factory() as session:
        leads = list(session.query(Lead).filter(Lead.search_id == search_id).all())
        assessments = list(session.query(GooglePresenceAssessment).all())
        actions = {item.recommended_action for item in assessments}
        assert len(leads) == 4
        assert len(assessments) == 4
        assert {"Website-only", "Google Presence-only", "Website + Google Presence"}.issubset(actions)


def test_provenance_and_reports_avoid_unsupported_maps_ranking_claims(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "report.sqlite3")
    initialize_database(factory)
    config = AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "report.sqlite3",
        output_dir=tmp_path / "output",
        log_path=tmp_path / "app.log",
    )
    with factory() as session:
        lead = _lead(session, _profile("report", reviews=30, phone=False, hours=False, photos=1), strong_site=True)
        _add_competitors(session, lead)
        GooglePresenceService().evaluate_and_store(session, lead)
        QualificationService().evaluate_and_store(session, lead)
        session.commit()
        payload = assessment_to_dict(lead.google_presence)
        assert any(item["derived"] for item in payload["provenance"])
        assert all(item["place_id"] for item in payload["provenance"])
        report = ReportService(config).generate_report(session, lead, "internal").read_text(encoding="utf-8")
        assert "Google Presence" in report
        assert "exact Google Maps ranking" in report
        assert "competitors are stealing traffic" not in report.lower()


def test_unaudited_linked_website_remains_unknown_and_cannot_drive_website_offer(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "unknown-website.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(
            session, _profile("unknown-website"), None,
            ScoreBreakdown(0, "C", [], "Research-first", "Audit first", []),
        )
        result = GooglePresenceService().evaluate(session, lead)
        assert result.recommended_action == "Research-first / website audit required"
        assert not any("website experience" in gap for gap in result.observed_gaps)
        assert all("/100" not in factor.evidence or "Target website" not in factor.evidence
                   for factor in QualificationService().evaluate(session, lead).factors)
    factory.kw["bind"].dispose()


def test_stale_rich_fields_do_not_increase_strength_or_advance_observation_date(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "stale-rich.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead(session, _profile("stale-rich"), strong_site=True)
        current = GooglePresenceService().evaluate(session, lead)
        lead.last_rich_google_retrieved_at = "2026-08-27T12:00:00+00:00"
        lead.google_retrieved_at = "2026-09-22T12:00:00+00:00"
        lead.google_rich_data_stale = True
        stale = GooglePresenceService().evaluate(session, lead)
        assert stale.strength_score < current.strength_score
        assert stale.recommended_action != "Website-only"
        rich = next(item for item in stale.provenance if item["subject"].startswith("Target rich details"))
        assert rich["retrieved_at"] == "2026-08-27T12:00:00+00:00"
        assert "not current" in rich["human_readable"]
    factory.kw["bind"].dispose()


def test_stale_or_undated_competitor_snapshots_do_not_create_gap_points(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "old-competitors.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead(session, _profile("old-competitors", reviews=5), strong_site=True)
        old = {
            "rating": 5.0, "review_count": 500, "details_retrieved": True,
            "website": True, "hours": True, "retrieved_at": "2020-01-01T00:00:00+00:00",
        }
        summary, points = compare_with_competitors(lead, [old, {**old, "retrieved_at": ""}])
        assert points == 0
        assert "older or undated" in summary[0]
    factory.kw["bind"].dispose()
