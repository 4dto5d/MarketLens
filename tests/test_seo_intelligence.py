"""Independent behavioral and adversarial checks for the SEO evidence contract."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from local_presence_miner.domain.seo_intelligence import analyze_seo, validate_payload

NOW = datetime(2026, 10, 2, 18, tzinfo=UTC)


def payload():
    return {
        "schema_version": 1,
        "subject": {"place_id": "target", "website": "https://target.example", "geography": "Denver, CO", "canonical_niche_id": "plumber"},
        "observed_at": NOW.isoformat(),
        "source": {"provider": "semrush", "report": "keyword export", "database": "us", "geography": "Denver, CO", "geo_resolution": "local",
                   "status": "complete", "reference": "offline-export:001", "demo": False},
        "queries": [{"query": "emergency plumber Denver", "service": "emergency plumbing", "service_state": "confirmed", "service_refs": ["owner:services"],
                     "intent": "local_commercial", "intent_basis": "Explicit local service request", "volume": 20, "difficulty": 30,
                     "organic_rank": 12, "maps_rank": 2, "organic_window": 20, "maps_window": 3, "organic_complete": True, "maps_complete": True,
                     "page_url": "https://target.example/emergency",
                     "competitors": [{"url": "https://other-plumber.example", "channel": "organic", "position": 1, "kind": "local_business"}],
                     "serp_features": [], "refs": ["serp:Denver:20261002"]}],
        "pages": [{"url": "https://target.example/emergency", "title": "Home", "h1": ["Local service team"], "meta_description": "", "canonical": "",
                   "robots": [], "status_code": 200, "indexability": "allowed", "word_count": 250, "internal_links": [], "schema_types": [],
                   "schema_errors": [], "services": ["emergency plumbing"], "service_refs": ["page:emergency:20261002"]}],
    }


def test_low_volume_local_purchase_demand_supports_narrow_improvement():
    data = payload()
    data["queries"][0]["volume"] = 1
    result = analyze_seo(data, now=NOW)
    opportunity = result["opportunities"][0]
    assert result["state"] == "complete"
    assert opportunity["action"] == "improve_page"
    assert opportunity["decision"] == "recommended"
    assert opportunity["scope"] == ["local SEO title/meta/H1 fixes"]
    assert opportunity["maps_visibility"] == "dominant"
    assert opportunity["volume"] == 1
    assert "price" not in opportunity
    assert opportunity["falsifier"]


def test_validator_does_not_mutate_input():
    data = payload()
    before = deepcopy(data)
    assert validate_payload(data)["schema_version"] == 1
    assert data == before


@pytest.mark.parametrize("state,delta,source_changes", [
    ("stale", -timedelta(days=31), {}), ("future", timedelta(microseconds=1), {}),
    ("partial", timedelta(), {"status": "partial"}), ("failed", timedelta(), {"status": "failed"}),
    ("demo", timedelta(), {"demo": True}),
])
def test_noncurrent_noncomplete_or_demo_evidence_never_recommends(state, delta, source_changes):
    data = payload()
    data["observed_at"] = (NOW + delta).isoformat()
    data["source"].update(source_changes)
    result = analyze_seo(data, now=NOW)
    assert result["state"] == state
    assert all(op["decision"] == "insufficient_evidence" for op in result["opportunities"])


@pytest.mark.parametrize("intent,query", [("informational", "how to fix a burst pipe"), ("navigational", "Target plumbing login"),
                                         ("curiosity", "funny plumbing memes"), ("local_commercial", "plumber salary Denver")])
def test_high_volume_nonpurchase_queries_are_rejected(intent, query):
    data = payload()
    data["queries"][0].update({"intent": intent, "query": query, "volume": 100000})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] == "no_sale"
    assert op["action"] == "no_seo_sale"


@pytest.mark.parametrize("service_state", ["likely", "possible_expansion", "unsupported", "unknown"])
def test_unconfirmed_or_unsupported_services_never_generate_paid_work(service_state):
    data = payload()
    data["queries"][0]["service_state"] = service_state
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] != "recommended"


def test_country_volume_and_local_rank_are_separate_provenance():
    data = payload()
    data["queries"][0].update({"volume": 50000, "volume_geo_resolution": "country", "volume_geography": "US", "volume_reference": "export:country"})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["demand_quality"] == "country_only"
    assert op["organic_visibility"] == "weak"
    assert op["decision"] == "insufficient_evidence"
    assert "export:country" in op["evidence_refs"]


def test_source_country_volume_does_not_prove_subject_locality():
    data = payload()
    data["source"].update({"geography": "US", "geo_resolution": "country"})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["demand_quality"] == "country_only"
    assert op["decision"] != "recommended"


def test_rank_dominance_returns_no_seo_sale():
    data = payload()
    data["queries"][0]["organic_rank"] = 1
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "no_seo_sale"
    assert op["decision"] == "no_sale"
    assert op["scope"] == []


def test_missing_page_gets_specific_unpriced_validation_not_rebuild():
    data = payload()
    data["pages"] = []
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "create_page"
    assert op["decision"] == "validate_first"
    assert "emergency plumbing" in op["scope"][0]
    assert "if absent" in op["scope"][0]
    assert "price" not in op
    assert "rebuild" not in " ".join(op["scope"])


@pytest.mark.parametrize("page_changes", [{"indexability": "blocked"}, {"robots": ["noindex, follow"]},
                                          {"status_code": 404}, {"canonical": "https://wrong.example/emergency"}])
def test_indexability_and_canonical_diagnosis_precedes_targeting(page_changes):
    data = payload()
    data["pages"][0].update(page_changes)
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "technical_repair"
    assert op["decision"] == "validate_first"
    assert op["scope"] != ["local SEO title/meta/H1 fixes"]


def test_alias_cluster_is_lower_bound_not_sum_or_max():
    data = payload()
    original = data["queries"][0]
    for query, volume, service in [("24h plumber Denver", 50, "24h plumbing"), ("burst pipe repair Denver", 70, "burst pipe repair")]:
        row = deepcopy(original)
        row.update({"query": query, "volume": volume, "service": service})
        data["queries"].append(row)
    result = analyze_seo(data, now=NOW)
    assert len(result["opportunities"]) == 1
    assert result["opportunities"][0]["volume"] == 20
    assert len(result["opportunities"][0]["queries"]) == 3
    assert "lower bound" in result["opportunities"][0]["volume_basis"]


def test_distinct_plumbing_subservices_are_not_overclustered():
    data = payload()
    row = deepcopy(data["queries"][0])
    row.update({"query": "drain cleaning Denver", "service": "drain cleaning"})
    data["queries"].append(row)
    services = {op["service"] for op in analyze_seo(data, now=NOW)["opportunities"]}
    assert services == {"emergency plumbing", "drain cleaning"}


def test_potential_page_overlap_is_validation_not_cannibalization_claim():
    data = payload()
    other = deepcopy(data["pages"][0])
    other["url"] = "https://target.example/24hour"
    data["pages"].append(other)
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "consolidate_validation"
    assert op["decision"] == "validate_first"
    assert any("not proof" in text for text in op["unknowns"])


@pytest.mark.parametrize("barrier", ["directories", "authority", "referring_domains", "ads", "lsa"])
def test_competitive_barriers_reduce_capturability_and_paid_confidence(barrier):
    data = payload()
    q = data["queries"][0]
    if barrier == "directories":
        q["competitors"] = [{"url": f"https://directory{index}.example", "channel": "organic", "position": index, "kind": "directory"}
                            for index in (1, 2)]
    elif barrier in {"authority", "referring_domains"}:
        data["prospect_authority"] = 10
        data["referring_domains"] = 2
        q["competitors"] = [{"url": "https://national.example", "channel": "organic", "position": 1, "kind": "national_brand",
                             "authority": 90 if barrier == "authority" else None, "referring_domains": 200 if barrier == "referring_domains" else None}]
    else:
        q["serp_features"] = [barrier]
    result = analyze_seo(data, now=NOW)
    op = result["opportunities"][0]
    assert op["capturability"] == "low"
    assert op["decision"] == "validate_first"
    assert op["confidence"] == "low"
    for competitor in result["competitors"]:
        assert competitor["geography"] == "Denver, CO"
        assert competitor["query"] == q["query"]
        assert competitor["channel"] == "organic"


def test_maps_gap_with_organic_strength_is_profile_validation():
    data = payload()
    data["queries"][0].update({"organic_rank": 2, "maps_rank": None})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "local_profile"
    assert op["decision"] == "validate_first"
    assert op["organic_visibility"] == "dominant"
    assert op["maps_visibility"] == "absent_in_window"


def test_well_targeted_existing_page_is_not_sold_title_fixes():
    data = payload()
    data["pages"][0].update({"title": "Emergency plumbing Denver", "h1": ["Emergency plumbing"], "meta_description": "Emergency local plumbing services"})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "validate"
    assert op["decision"] == "validate_first"


@pytest.mark.parametrize("volume,quality", [(None, "unknown"), (0, "zero_reported_volume")])
def test_unknown_volume_is_distinct_from_reported_zero(volume, quality):
    data = payload()
    data["queries"][0]["volume"] = volume
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["volume"] is volume
    assert op["demand_quality"] == quality
    assert op["decision"] == "insufficient_evidence"


@pytest.mark.parametrize("changes", [{"organic_complete": False}, {"service_refs": []}, {"refs": []}, {"intent_basis": ""}])
def test_missing_completeness_or_references_fail_closed(changes):
    data = payload()
    data["queries"][0].update(changes)
    assert analyze_seo(data, now=NOW)["opportunities"][0]["decision"] != "recommended"


@pytest.mark.parametrize("delta", [-timedelta(days=31), timedelta(seconds=1)])
def test_page_facts_cannot_be_laundered_by_current_keyword_timestamp(delta):
    data = payload()
    data["pages"][0].update({"observed_at": (NOW + delta).isoformat(), "source_ref": "website_audit:7:hash"})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] != "recommended"
    assert "website_audit:7:hash" in op["evidence_refs"]
    assert any("page snapshot is stale" in item for item in op["unknowns"])


@pytest.mark.parametrize("path,value", [
    (("schema_version",), True), (("schema_version",), 2), (("queries", 0, "volume"), True),
    (("queries", 0, "volume"), float("nan")), (("queries", 0, "volume"), float("inf")),
    (("queries", 0, "difficulty"), 101), (("queries", 0, "organic_rank"), 0),
    (("queries", 0, "organic_rank"), 21), (("queries", 0, "maps_rank"), 2.0),
    (("queries", 0, "organic_complete"), 1), (("queries", 0, "organic_window"), None),
    (("source", "demo"), "false"), (("source", "status"), "PASS"), (("source", "geography"), "Austin TX"),
    (("subject", "website"), "javascript:alert(1)"), (("subject", "website"), "https://user:password@target.example"),
    (("queries", 0, "page_url"), "https://unrelated.example/service"), (("pages", 0, "url"), "https://wrong.example/service"),
    (("observed_at",), "2026-10-02T18:00:00"), (("observed_at",), "not-a-date"),
    (("queries", 0, "service_state"), "definitely"), (("queries", 0, "query"), "x" * 501),
    (("economics",), {"margin": float("nan")}), (("queries", 0, "refs"), "unstructured"),
])
def test_adversarial_invalid_payloads_rejected_without_recommendations(path, value):
    data = payload()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_payload(data)
    result = analyze_seo(data, now=NOW)
    assert result["state"] == "invalid"
    assert result["opportunities"] == []


@pytest.mark.parametrize("field", ["queries", "pages"])
def test_duplicate_and_conflicting_observations_are_rejected(field):
    data = payload()
    duplicate = deepcopy(data[field][0])
    if field == "queries":
        duplicate["organic_rank"] = 1
    else:
        duplicate["indexability"] = "blocked"
    data[field].append(duplicate)
    with pytest.raises(ValueError, match="duplicate or conflicting"):
        validate_payload(data)


def test_duplicate_competitor_positions_and_subject_as_competitor_rejected():
    data = payload()
    data["queries"][0]["competitors"] = [{"url": "https://one.example", "channel": "organic", "position": 1, "kind": "local_business"},
                                          {"url": "https://two.example", "channel": "organic", "position": 1, "kind": "national_brand"}]
    with pytest.raises(ValueError):
        validate_payload(data)
    data["queries"][0]["competitors"] = [{"url": "https://www.target.example", "channel": "organic", "position": 1, "kind": "local_business"}]
    with pytest.raises(ValueError):
        validate_payload(data)


def test_future_and_stale_boundary_and_naive_now():
    data = payload()
    data["observed_at"] = (NOW - timedelta(days=30)).isoformat()
    assert analyze_seo(data, now=NOW)["state"] == "complete"
    with pytest.raises(ValueError, match="timezone-aware"):
        analyze_seo(data, now=NOW.replace(tzinfo=None))


def test_failed_source_can_record_no_queries_without_fabricating_absence():
    data = payload()
    data["source"]["status"] = "failed"
    data["queries"] = []
    result = analyze_seo(data, now=NOW)
    assert result["state"] == "failed"
    assert result["opportunities"] == []
    assert result["unknowns"]


def test_economics_changes_never_change_recommendation_or_generate_price():
    data = payload()
    before = analyze_seo(data, now=NOW)["opportunities"]
    data["economics"] = {"average_job_value": 50000, "gross_margin": .8, "repeat_customer_value": 90000}
    assert analyze_seo(data, now=NOW)["opportunities"] == before


def test_bounded_payload_and_unknown_injected_decision_rejected():
    data = payload()
    data["queries"][0]["action"] = "rebuild_everything"
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_payload(data)
    data = payload()
    data["queries"] = [deepcopy(data["queries"][0])] * 501
    with pytest.raises(ValueError, match="bounded list"):
        validate_payload(data)


def test_generic_multi_service_labels_do_not_overcluster_distinct_query_subtypes():
    data = payload()
    data["queries"][0].update({"query": "drain cleaning Denver", "service": "Drain & Sewer"})
    sewer = deepcopy(data["queries"][0])
    sewer["query"] = "sewer repair Denver"
    data["queries"].append(sewer)
    result = analyze_seo(data, now=NOW)
    assert len(result["opportunities"]) == 2
    assert len({op["cluster_id"] for op in result["opportunities"]}) == 2


def test_single_directory_repeated_across_aliases_is_not_multiple_entrenched_competitors():
    data = payload()
    data["queries"][0]["competitors"][0]["kind"] = "directory"
    alias = deepcopy(data["queries"][0])
    alias["query"] = "24h plumber Denver"
    data["queries"].append(alias)
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["capturability"] == "unmeasured"  # Repeated unknown strength is not new competitive proof.


@pytest.mark.parametrize("robots", [["bingbot: noindex"], ["noindexifembedded"]])
def test_other_bot_and_noindexifembedded_are_not_google_index_blocks(robots):
    data = payload()
    data["pages"][0]["robots"] = robots
    assert analyze_seo(data, now=NOW)["opportunities"][0]["action"] == "improve_page"


def test_unknown_competitor_evidence_and_unknown_page_indexability_require_validation():
    data = payload()
    data["queries"][0]["competitors"] = []
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["capturability"] == "unknown"
    assert op["decision"] == "validate_first"
    data = payload()
    data["pages"][0]["indexability"] = "unknown"
    assert analyze_seo(data, now=NOW)["opportunities"][0]["decision"] != "recommended"


@pytest.mark.parametrize("gross_margin", [0, -.1])
def test_trustworthy_nonpositive_margin_requires_economic_validation_before_spend(gross_margin):
    data = payload()
    data["economics"] = {"service": "emergency plumbing", "observed_at": NOW.isoformat(), "refs": ["owner:unit-economics"], "gross_margin": gross_margin}
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] == "validate_first"
    assert op["economics_state"] == "reported_current"
    assert "unit economics" in op["scope"][0]
    assert "owner:unit-economics" in op["evidence_refs"]
    assert "price" not in op


@pytest.mark.parametrize("change", [{"refs": []}, {"service": "drain cleaning"}, {"observed_at": (NOW - timedelta(days=31)).isoformat()}])
def test_untrusted_mismatched_or_stale_economics_do_not_become_facts(change):
    data = payload()
    data["economics"] = {"service": "emergency plumbing", "observed_at": NOW.isoformat(), "refs": ["owner:economics"], "gross_margin": 0}
    data["economics"].update(change)
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["economics_state"] == "unknown"
    assert op["action"] == "improve_page"
    assert "owner:economics" not in op["evidence_refs"]


def test_evidence_references_preserve_exact_source_identifiers():
    data = payload()
    data["source"]["reference"] = "offline export:row  7"
    data["queries"][0]["refs"] = ["manual source:row  12"]
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert "offline export:row  7" in op["evidence_refs"]
    assert "manual source:row  12" in op["evidence_refs"]


def test_ranked_contact_page_cannot_borrow_service_snapshot_for_paid_targeting():
    data = payload()
    assert analyze_seo(data, now=NOW)["opportunities"][0]["decision"] == "recommended"
    data["queries"][0]["page_url"] = "https://target.example/contact"
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] == "validate_first"
    assert op["action"] == "validate"
    assert any("query-to-page" in item for item in op["unknowns"])


def test_ranked_page_service_labels_without_proof_are_not_paid_targeting_evidence():
    data = payload()
    data["pages"][0]["service_refs"] = []
    assert analyze_seo(data, now=NOW)["opportunities"][0]["decision"] != "recommended"


def test_high_reported_difficulty_is_cautious_barrier_not_probability_or_price():
    data = payload()
    data["queries"][0]["difficulty"] = 90
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["capturability"] == "low"
    assert op["decision"] == "validate_first"
    assert any("provider estimate" in text for text in op["observations"])
    assert "price" not in op
    assert "probability" not in op


def test_local_pack_and_maps_strength_require_incremental_organic_validation():
    data = payload()
    data["queries"][0]["serp_features"] = ["local_pack"]
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "improve_page"
    assert op["decision"] == "validate_first"
    assert any("does not measure click share" in text for text in op["observations"])


def test_schema_error_requires_validation_and_never_becomes_paid_ranking_upsell():
    data = payload()
    data["pages"][0].update({"title": "Emergency plumbing", "h1": ["Emergency plumbing"], "meta_description": "Local emergency plumbing",
                             "schema_errors": ["Malformed JSON-LD"]})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] == "validate_first"
    assert any("do not establish a cause" in text for text in op["unknowns"])
    assert not any("schema" in text for text in op["scope"])


def test_cross_industry_query_cannot_override_confirmed_service_identity():
    data = payload()
    data["queries"][0].update({"service": "pest control", "query": "water heater repair Denver"})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] == "insufficient_evidence"
    assert op["demand_quality"] == "service_relevance_unvalidated"
    assert op["service"].startswith("pest control")


def test_roof_replacement_demand_cannot_authorize_work_for_repair_only_service():
    data = payload()
    data["subject"]["canonical_niche_id"] = "roofing"
    data["queries"][0].update({"service": "roof repair", "query": "roof replacement Denver"})
    data["pages"][0]["services"] = ["roof repair"]
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] != "recommended"
    assert op["demand_quality"] == "service_relevance_unvalidated"
    assert any("exact relevance" in text for text in op["unknowns"])


def test_referenced_service_heading_may_include_services_and_exact_local_geography():
    data = payload()
    heading = "Emergency Plumbing Services in Denver"
    data["pages"][0].update({"h1": [heading], "services": [heading], "service_refs": ["website:emergency:h1"]})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "improve_page"
    assert op["decision"] == "recommended"
    assert "website:emergency:h1" in op["evidence_refs"]


def test_generic_plumbing_targeting_does_not_establish_emergency_targeting():
    data = payload()
    data["pages"][0].update({"title": "Plumbing in Denver", "h1": ["Plumbing Services"], "meta_description": "Local plumbing services"})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["action"] == "improve_page"
    assert op["decision"] == "recommended"


@pytest.mark.parametrize("service,query", [("roof repair", "roof installation Denver"), ("roof repair", "roof maintenance Denver"),
                                           ("pest control", "commercial pest control Denver"), ("plumbing", "emergency plumber Denver")])
def test_distinct_service_actions_customer_segments_and_urgency_require_confirmation(service, query):
    data = payload()
    data["queries"][0].update({"service": service, "query": query})
    data["pages"][0]["services"] = [service]
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["decision"] != "recommended"
    assert op["demand_quality"] == "service_relevance_unvalidated"


def test_page_heading_replacement_does_not_confirm_repair_service():
    data = payload()
    data["queries"][0].update({"service": "roof repair", "query": "roof repair Denver"})
    data["pages"][0].update({"services": ["Roof Replacement Services in Denver"], "h1": ["Roof Replacement Services in Denver"]})
    assert analyze_seo(data, now=NOW)["opportunities"][0]["decision"] != "recommended"


@pytest.mark.parametrize("service,query,heading", [
    ("emergency plumbing", "24h plumber Denver", "Emergency Plumbing Services in Denver"),
    ("24h plumbing", "burst pipe repair Denver", "Emergency Plumbing Services in Denver"),
    ("burst pipe repair", "emergency plumber Denver", "24h Plumbing Services in Denver"),
])
def test_controlled_emergency_alias_family_preserves_reference_backed_paid_targeting(service, query, heading):
    data = payload()
    data["queries"][0].update({"service": service, "query": query})
    data["pages"][0].update({"services": [heading], "h1": [heading]})
    op = analyze_seo(data, now=NOW)["opportunities"][0]
    assert op["service"] == "emergency plumbing"
    assert op["action"] == "improve_page"
    assert op["decision"] == "recommended"
