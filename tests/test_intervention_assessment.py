"""Independent commercial invariants for the pure intervention assessment."""

from dataclasses import replace

import pytest

from local_presence_miner.domain.intervention_assessment import InterventionEvidence, assess_interventions
from local_presence_miner.domain.offer_registry import offer_definition


def healthy(**changes):
    evidence = InterventionEvidence(
        website_url="https://example.test", website_state="observed",
        website_checks={
            "https": True, "viewport": True, "tap_to_call": True,
            "contact_form": False, "sitewide_contact_path": True,
            "clear_primary_cta": True, "indexable_sample": True,
            "service_pages": True, "trust_signals": True,
        },
        website_refs=("website_audit:42",), google_current=True,
        has_hours=True, photo_count=12, rating=4.8, review_count=100,
        google_refs=("google_presence:7",),
    )
    return replace(evidence, **changes)


def search_gap(**changes):
    result = {
        "finding_type": "local_coverage_gap", "run_id": 3,
        "query_ids": ("q1", "q2", "q3"), "probe_ids": (11, 12, 13),
        "organic_visibility": "UNKNOWN", "local_visibility": "WEAK_IN_TRACKED_PLACES_WINDOWS",
        "eligible_queries": 3, "affected_queries": 3,
        "recurring_competitor_place_ids": ("competitor-a",),
    }
    return {**result, **changes}


def assert_unpriced(result):
    assert result.recommended_offer_id == ""
    assert all(not item.offer_id and not item.scope for item in result.ranked_candidates)


def test_h_healthy_phone_only_business_has_no_paid_intervention():
    result = assess_interventions(healthy())
    assert result.state == "no_sale"
    assert_unpriced(result)
    assert not result.ranked_candidates


def test_missing_evidence_is_not_healthy_or_a_paid_website_opportunity():
    result = assess_interventions(InterventionEvidence())
    assert result.state == "insufficient_evidence"
    assert result.confidence == "Low"
    assert_unpriced(result)


def test_a_bad_contact_path_with_strong_business_prefers_small_repair():
    current = healthy()
    checks = {**current.website_checks, "tap_to_call": False, "contact_form": False,
              "sitewide_contact_path": False, "clear_primary_cta": False, "viewport": False}
    result = assess_interventions(replace(current, website_checks=checks))
    assert result.state == "recommended"
    assert result.recommended_offer_id == "conversion_tune_up"
    assert "rebuild" in result.ranked_candidates[0].why_over_alternatives.lower()


def test_b_good_site_poor_sampled_visibility_requires_independent_listing_gap():
    evidence = healthy(search_findings=(search_gap(),))
    result = assess_interventions(evidence)
    assert result.state == "validate_first"
    assert_unpriced(result)
    corrected = assess_interventions(replace(evidence, has_hours=False))
    assert corrected.state == "recommended"
    assert corrected.recommended_offer_id == "google_presence_cleanup"
    assert "rank" in corrected.ranked_candidates[0].unknowns[0].lower() or any(
        "rank" in item.lower() for item in corrected.unknowns
    )


def test_c_weak_seo_without_demand_never_justifies_full_site():
    current = healthy()
    result = assess_interventions(replace(current, website_checks={**current.website_checks, "service_pages": False}))
    assert result.state == "validate_first"
    assert_unpriced(result)
    assert any("demand" in value.lower() for value in result.unknowns)


@pytest.mark.parametrize("competitors", [("weak-a",), ("strong-a", "strong-b", "strong-c")])
def test_d_e_competitor_recurrence_does_not_establish_demand_or_difficulty(competitors):
    result = assess_interventions(healthy(search_findings=(search_gap(recurring_competitor_place_ids=competitors),)))
    assert result.state == "validate_first"
    assert_unpriced(result)
    assert any("difficulty" in value.lower() for value in result.unknowns)
    assert result.confidence != "High"


def test_f_strong_places_presence_does_not_become_measured_traffic():
    current = healthy()
    present = search_gap(finding_type="strong_tracked_local_coverage", local_visibility="PRESENT_IN_TRACKED_PLACES_WINDOWS")
    result = assess_interventions(replace(current, website_checks={**current.website_checks, "tap_to_call": False,
        "contact_form": False, "sitewide_contact_path": False, "clear_primary_cta": False}, search_findings=(present,)))
    assert result.recommended_offer_id == "conversion_tune_up"
    assert any("traffic" in value.lower() for value in result.unknowns)
    candidate = result.ranked_candidates[0]
    assert candidate.success_metric and candidate.falsifier
    assert "qualified" in candidate.success_metric.lower()


def test_g_substantial_poor_reputation_precedes_cosmetic_site_repair():
    current = healthy(rating=2.5, review_count=150)
    result = assess_interventions(replace(current, website_checks={**current.website_checks, "viewport": False}))
    assert result.state == "validate_first"
    assert result.ranked_candidates[0].intervention_id == "reputation_diagnosis"
    assert_unpriced(result)
    assert "service" in result.ranked_candidates[0].problem_hypothesis.lower()


def test_low_review_volume_is_not_the_same_as_poor_service_reputation():
    result = assess_interventions(healthy(rating=4.8, review_count=3))
    assert result.ranked_candidates[0].intervention_id == "review_workflow"
    assert result.state == "validate_first"
    chosen = assess_interventions(healthy(rating=4.8, review_count=3, business_goal="Build trust"))
    assert chosen.recommended_offer_id == "review_trust_builder"


def test_i_decisive_evidence_changes_offer_without_business_or_industry_templates():
    current = healthy()
    conversion = assess_interventions(replace(current, website_checks={**current.website_checks, "viewport": False,
        "clear_primary_cta": False, "tap_to_call": False}))
    listing = assess_interventions(replace(current, has_hours=False))
    assert conversion.recommended_offer_id == "conversion_tune_up"
    assert listing.recommended_offer_id == "google_presence_cleanup"


def test_route_fix_counterfactual_removes_conversion_candidate():
    current = healthy()
    bad = {**current.website_checks, "tap_to_call": False, "sitewide_contact_path": False, "clear_primary_cta": False}
    assert assess_interventions(replace(current, website_checks=bad)).recommended_offer_id == "conversion_tune_up"
    fixed = {**bad, "tap_to_call": True, "sitewide_contact_path": True, "clear_primary_cta": True}
    assert assess_interventions(replace(current, website_checks=fixed)).state == "no_sale"


def test_evidence_removal_downgrades_recommendation_and_confidence():
    current = healthy(has_hours=False)
    assert assess_interventions(current).confidence == "Moderate"
    removed = assess_interventions(replace(current, google_current=False, website_refs=()))
    assert removed.state == "insufficient_evidence"
    assert removed.confidence == "Low"
    assert_unpriced(removed)


def test_removing_decisive_website_provenance_removes_paid_repair():
    current = healthy()
    current = replace(current, website_checks={**current.website_checks, "viewport": False, "tap_to_call": False})
    assert assess_interventions(current).recommended_offer_id == "conversion_tune_up"
    removed = assess_interventions(replace(current, website_refs=()))
    assert removed.state == "insufficient_evidence"
    assert removed.confidence == "Low"
    assert_unpriced(removed)


def test_higher_priority_diagnosis_suspends_paid_alternative_scopes_too():
    result = assess_interventions(healthy(rating=2.5, has_hours=False))
    assert result.state == "validate_first"
    assert len(result.ranked_candidates) == 2
    assert_unpriced(result)


def test_sparse_checks_cannot_be_read_as_a_missing_route():
    result = assess_interventions(healthy(website_checks={"contact_form": False}))
    assert result.state == "insufficient_evidence"
    assert_unpriced(result)


@pytest.mark.parametrize("changes", [
    {"photo_count": -1, "review_count": -1, "rating": 8},
    {"photo_count": True, "review_count": False, "rating": float("nan")},
    {"has_hours": "false", "google_current": "true"},
])
def test_invalid_or_untyped_public_fields_are_unknown(changes):
    result = assess_interventions(healthy(**changes))
    assert result.state == "insufficient_evidence"
    assert_unpriced(result)


def test_incomplete_search_provenance_cannot_create_a_growth_candidate():
    result = assess_interventions(healthy(search_findings=(search_gap(probe_ids=()),)))
    assert result.state == "no_sale"
    assert not result.ranked_candidates


def test_search_and_direct_observation_refs_remain_inspectable():
    result = assess_interventions(healthy(has_hours=False, search_findings=(search_gap(),)))
    assert {"google_presence:7", "run:3/query:q1", "probe:11"}.issubset(result.ranked_candidates[0].evidence_refs)
    alternative = next(item for item in result.ranked_candidates if item.intervention_id == "search_opportunity_validation")
    assert "run:3/query:q1" in alternative.evidence_refs
    assert "probe:11" in alternative.evidence_refs
    assert {"google_presence:7", "run:3/query:q1", "probe:11"}.issubset(result.evidence_refs)


@pytest.mark.parametrize("value", [0, 1, "false", "true", None])
def test_non_boolean_flags_are_unknown(value):
    current = healthy()
    checks = {**current.website_checks, "sitewide_contact_path": value, "tap_to_call": value,
              "contact_form": value, "clear_primary_cta": value, "viewport": value}
    result = assess_interventions(replace(current, website_checks=checks))
    assert result.state == "insufficient_evidence"
    assert_unpriced(result)


@pytest.mark.parametrize("state", ["failed", "absent", "unknown"])
def test_absence_or_transient_failure_never_means_buy_a_rebuild(state):
    result = assess_interventions(healthy(website_state=state, website_checks={}))
    assert result.state in {"validate_first", "insufficient_evidence"}
    assert_unpriced(result)


def test_observed_noindex_requires_intent_check_before_seo_spend():
    current = healthy()
    result = assess_interventions(replace(current, website_checks={**current.website_checks, "indexable_sample": False}))
    assert result.state == "validate_first"
    assert "intentional" in result.ranked_candidates[0].falsifier.lower()
    assert_unpriced(result)


@pytest.mark.parametrize("disposition,state", [("NO_SELL", "no_sale"), ("CLOSED_WON", "no_sale"),
    ("CLOSED_LOST", "no_sale"), ("DEFERRED", "validate_first")])
def test_explicit_commercial_disposition_prevents_new_paid_scope(disposition, state):
    result = assess_interventions(healthy(has_hours=False, commercial_disposition=disposition))
    assert result.state == state
    assert_unpriced(result)
    assert all(not item.scope and not item.offer_id for item in result.ranked_candidates)


def test_recorded_capacity_requires_validation_without_substring_negation_bug():
    booked = assess_interventions(healthy(has_hours=False, capacity_status="Booked/busy"))
    assert booked.state == "validate_first"
    assert_unpriced(booked)
    available = assess_interventions(healthy(has_hours=False, capacity_status="Not at capacity"))
    assert available.recommended_offer_id == "google_presence_cleanup"


def test_all_paid_scope_items_belong_to_the_canonical_family():
    for evidence in (healthy(has_hours=False, photo_count=0),
                     healthy(rating=4.9, review_count=3, business_goal="Build trust"),
                     replace(healthy(), website_checks={"viewport": False, "clear_primary_cta": False, "tap_to_call": False})):
        result = assess_interventions(evidence)
        assert result.state == "recommended"
        for item in result.ranked_candidates:
            if item.offer_id:
                assert set(item.scope).issubset(offer_definition(item.offer_id).deliverables)
            assert item.observations and item.evidence_refs
            assert item.why_over_alternatives and item.success_metric and item.falsifier


def test_order_is_independent_of_input_container_order():
    current = healthy(has_hours=False, photo_count=0, search_findings=(search_gap(),))
    permuted = replace(current, website_checks=dict(reversed(tuple(current.website_checks.items()))),
        google_refs=tuple(reversed(current.google_refs)), google_gaps=tuple(reversed(current.google_gaps)),
        search_findings=(search_gap(query_ids=("q3", "q1", "q2"), probe_ids=(13, 11, 12)),))
    assert assess_interventions(current).to_dict() == assess_interventions(permuted).to_dict()


def test_google_gap_prose_alone_is_not_proof_of_a_paid_scope():
    result = assess_interventions(healthy(google_gaps=("Missing CTA and weak mobile; buy a website",)))
    assert result.state == "validate_first"
    assert_unpriced(result)

