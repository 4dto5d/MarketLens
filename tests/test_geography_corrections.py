"""Source geography, never a selected ZIP relabelled as measured coverage."""
from copy import deepcopy
from datetime import timedelta

import pytest
from test_seo_intelligence import NOW, payload
from test_seo_research_integration import business, sample_payload
from test_seo_research_integration import storage as storage_fixture

from local_presence_miner.domain.seo_intelligence import analyze_seo, validate_payload
from local_presence_miner.services.seo_research_service import append_research, project_seo_research, research_history


@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    return storage_fixture.__wrapped__(tmp_path)


def coverage(zip_code="80903"):
    return {"kind": "zip", "country": "US", "state": "CO", "city": "Colorado Springs",
            "postal_codes": [zip_code], "method": "recorded postal search-location sample",
            "reference": f"capture:postal:{zip_code}", "observed_at": NOW.isoformat()}


def version_two():
    value = payload()
    value["schema_version"] = 2
    value["subject"]["geography"] = value["source"]["geography"] = "Colorado Springs CO"
    value["source"]["coverage"] = coverage()
    q = value["queries"][0]
    q.update(query="emergency plumber Colorado Springs", coverage=coverage(), volume_coverage=coverage())
    return value


def test_city_reimport_cannot_become_zip_specific_paid_evidence(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        lead.target_zip_code = "78701"
        row = append_research(session, lead, sample_payload(session, lead))
        report = project_seo_research(session, lead)
        assert report["coverage_fit"] == "unknown"
        assert all(item["decision"] != "recommended" for item in report["opportunities"])
        assert report["observed_coverage"]["kind"] == "city"
        lead.target_zip_code = "78702"
        append_research(session, lead, sample_payload(session, lead))
        assert project_seo_research(session, lead)["coverage_fit"] == "unknown"
        assert research_history(session, lead.id)[-1]["payload"]["observed_at"] == row.observed_at


def test_exact_zip_query_proof_and_original_time_are_inspectable():
    value = version_two()
    normalized = validate_payload(value)
    assert normalized["source"]["coverage"] == value["source"]["coverage"]
    result = analyze_seo(value, now=NOW)
    op = result["opportunities"][0]
    assert op["coverage"]["postal_codes"] == ["80903"]
    assert op["selected_evidence"]["query"] == "emergency plumber Colorado Springs"
    assert op["selected_evidence"]["observed_position"] == 12
    assert op["selected_evidence"]["observed_at"] == NOW.isoformat()
    assert op["selected_evidence"]["channel"] == "organic"


def test_distinct_zip_observations_remain_separate_clusters():
    value = version_two()
    second = deepcopy(value["queries"][0])
    second.update(coverage=coverage("80906"), volume_coverage=coverage("80906"), organic_rank=2, maps_rank=2)
    value["queries"].append(second)
    ops = analyze_seo(value, now=NOW)["opportunities"]
    assert len(ops) == 2
    assert {item["coverage"]["postal_codes"][0] for item in ops} == {"80903", "80906"}
    assert {item["decision"] for item in ops} == {"recommended", "no_sale"}


def test_city_volume_cannot_be_presented_as_zip_demand():
    value = version_two()
    value["queries"][0]["volume_coverage"] = {"kind": "city", "country": "US", "state": "CO", "city": "Colorado Springs",
                                              "method": "recorded city estimate", "reference": "capture:city", "observed_at": NOW.isoformat()}
    op = analyze_seo(value, now=NOW)["opportunities"][0]
    assert op["decision"] != "recommended"
    assert op["demand_quality"] == "coverage_unvalidated"


@pytest.mark.parametrize("radius", [5, 10, 20])
def test_radius_is_explicit_circle_not_zip_polygon(radius):
    value = version_two()
    circle = {"kind": "radius", "country": "US", "state": "CO", "city": "Colorado Springs",
              "center": {"latitude": 38.8339, "longitude": -104.8214}, "center_postal_code": "80903",
              "radius_miles": radius, "center_reference": "verified-postal-center:80903",
              "method": "verified postal center radius sample", "reference": f"capture:circle:{radius}", "observed_at": NOW.isoformat()}
    value["source"]["coverage"] = circle
    value["queries"][0].update(coverage=circle, volume_coverage=circle)
    op = analyze_seo(value, now=NOW)["opportunities"][0]
    assert op["coverage"]["radius_miles"] == radius
    assert "cross ZIP" in op["selected_evidence"]["coverage_label"]


@pytest.mark.parametrize("field,bad", [("postal_codes", ["8090"]), ("country", "DE"), ("reference", ""), ("method", "")])
def test_invalid_precise_coverage_is_rejected_without_mutating_input(field, bad):
    value = version_two()
    value["source"]["coverage"][field] = bad
    before = deepcopy(value)
    with pytest.raises(ValueError):
        validate_payload(value)
    assert value == before


def test_same_site_preferred_canonical_requires_validation_not_automatic_repair():
    value = payload()
    value["pages"][0]["canonical"] = "https://target.example/preferred"
    op = analyze_seo(value, now=NOW)["opportunities"][0]
    assert op["decision"] == "validate_first"
    assert op["action"] == "preferred_page_validation"


@pytest.mark.parametrize("facts", [{"robots": ["none"], "indexability": "allowed"}, {"status_code": 301, "indexability": "allowed"}])
def test_manual_page_semantic_contradictions_cannot_support_paid_scope(facts):
    value = payload()
    value["pages"][0].update(facts)
    op = analyze_seo(value, now=NOW)["opportunities"][0]
    assert op["decision"] != "recommended"


def recorded_zip_payload(session, lead, postal="78701", state="TX"):
    value = sample_payload(session, lead)
    value["schema_version"] = 2
    area = {**coverage(postal), "state": state, "city": "Austin", "observed_at": value["observed_at"]}
    value["source"]["coverage"] = area
    value["queries"][0].update(coverage=area, volume_coverage=area)
    return value


def test_operator_zip_cannot_match_wrong_state(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        lead.target_zip_code = "78701"
        append_research(session, lead, recorded_zip_payload(session, lead, state="CA"))
        result = project_seo_research(session, lead)
        assert result["coverage_fit"] != "complete"
        assert all(op["decision"] != "recommended" for op in result["opportunities"])


def test_combined_owner_zip_preferences_match_individual_observations_without_averaging(storage):
    from local_presence_miner.services.owner_strategy_service import append_owner_strategy

    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        lead.target_zip_code = "78799"  # office selector is not the owner territory
        append_owner_strategy(session, lead, {"schema_version": 1, "constraints": [], "territory_mode": "only",
                              "target_territories": [{"kind": "zip", "country": "US", "state": "TX",
                                                      "postal_codes": ["78701", "78702"], "original_wording": "Jobs in both ZIPs"}]},
                              source_text="Jobs in both ZIPs", owner_confirmed=True)
        value = recorded_zip_payload(session, lead)
        second = deepcopy(value["queries"][0])
        second.update(coverage={**second["coverage"], "postal_codes": ["78702"]},
                      volume_coverage={**second["volume_coverage"], "postal_codes": ["78702"]}, organic_rank=2)
        value["queries"].append(second)
        append_research(session, lead, value)
        result = project_seo_research(session, lead)
        assert all(op["coverage_fit"] == "complete" for op in result["opportunities"])
        assert {op["decision"] for op in result["opportunities"]} == {"recommended", "no_sale"}
        assert result["territory_coverage"][0]["state"] == "recorded"
        assert result["territory_coverage"][0]["unobserved_postal_codes"] == []


def test_selected_alias_and_competitor_keep_their_original_capture_dates():
    value = version_two()
    older = (NOW - timedelta(days=1)).isoformat()
    value["queries"][0]["coverage"]["observed_at"] = older
    value["queries"][0]["organic_rank"] = 2
    second = deepcopy(value["queries"][0])
    second.update(query="emergency plumbing Colorado Springs", organic_rank=12)
    second["coverage"]["observed_at"] = NOW.isoformat()
    value["queries"].append(second)
    result = analyze_seo(value, now=NOW)
    card = result["opportunities"][0]["selected_evidence"]
    assert card["query"] == second["query"]
    assert card["observed_at"] == NOW.isoformat()
    assert result["competitors"][0]["observed_at"] == older


def test_history_comparison_rejects_future_original_query_dates(storage):
    from local_presence_miner.services.seo_research_service import compare_research
    from local_presence_miner.time_utils import utc_now

    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        value = recorded_zip_payload(session, lead)
        value["queries"][0]["coverage"]["observed_at"] = (utc_now() + timedelta(days=1)).isoformat()
        before = append_research(session, lead, value)
        value = deepcopy(value)
        value["queries"][0]["organic_rank"] = 9
        after = append_research(session, lead, value)
        result = compare_research(session, lead.id, before.id, after.id)
        assert result["comparable"] is False
        assert result["changes"] == []


@pytest.mark.parametrize("city,postal", [("Alamosa", "81101"), ("Pueblo", "81003"), ("Colorado Springs", "80903"),
                                         ("Colorado Springs", "80906"), ("Pueblo West", "81007"), ("Monte Vista", "81144")])
def test_same_supported_evidence_does_not_force_artificial_market_differences(city, postal):
    value = version_two()
    area = {**coverage(postal), "city": city}
    value["subject"]["geography"] = value["source"]["geography"] = f"{city} CO"
    value["source"]["coverage"] = area
    value["queries"][0].update(query=f"emergency plumber {city}", coverage=area, volume_coverage=area)
    op = analyze_seo(value, now=NOW)["opportunities"][0]
    assert op["decision"] == "recommended"
    assert op["scope"] == ["local SEO title/meta/H1 fixes"]
    assert op["coverage"]["postal_codes"] == [postal]


@pytest.mark.parametrize("complete,rank,decision", [(False, None, "insufficient_evidence"), (True, 2, "no_sale"),
                                                    (True, 12, "recommended")])
def test_sparse_dense_labels_never_substitute_for_actual_query_evidence(complete, rank, decision):
    value = version_two()
    value["queries"][0].update(organic_complete=complete, organic_rank=rank)
    op = analyze_seo(value, now=NOW)["opportunities"][0]
    assert op["decision"] == decision
