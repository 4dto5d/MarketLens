"""Real-storage checks for Smart Offer's evidence and commercial boundaries.

The observations are synthetic; no acquisition, network calls or paid APIs run.
Expected outcomes come from the commercial requirements, not ranking internals.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import log_activity, save_outreach_draft
from local_presence_miner.database.schema import Lead, OfferHistory, OutreachApprovalHistory, SellerProfile, WebsiteAuditRecord
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.domain.offer_registry import offer_definition
from local_presence_miner.services.adaptive_outreach_service import format_smart_offer
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.commercial_state_service import (
    draft_commercial_errors,
    persist_current_plan,
    recompute_lead_commercial_candidate,
)
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.search_offer_intelligence import accept_advisory_offer
from local_presence_miner.time_utils import utc_now

HEALTHY_CHECKS = {
    "https": True, "viewport": True, "tap_to_call": True, "contact_form": False,
    "booking_or_quote_language": True, "sitewide_contact_path": True,
    "clear_primary_cta": True, "indexable_sample": True,
    "service_pages": True, "trust_signals": True,
}
BROKEN_ROUTE = {
    **HEALTHY_CHECKS, "tap_to_call": False, "contact_form": False,
    "sitewide_contact_path": False, "clear_primary_cta": False,
}


@pytest.fixture
def storage(tmp_path):
    config = AppConfig(tmp_path, tmp_path / "interventions.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    return config, factory


def add_business(session, *, checks=None, **changes):
    now = utc_now()
    defaults = {
        "place_id": "intervention-target", "name": "Specific Local Service", "category": "pest control",
        "website": "https://business.example", "phone": "555-010-0123", "has_hours": True,
        "photo_count": 12, "rating": 4.8, "review_count": 100, "search_position": 1,
        "business_status": "OPERATIONAL", "status": "New",
        "recommended_offer_id": "one_page_conversion_site", "recommended_offer": "One-Page Conversion Site + Google Cleanup",
        "qualification_class": "Qualified", "qualification_confidence": "Moderate",
        "qualification_json": '{"classification":"Qualified","confidence":"Moderate"}',
        "google_public_data_json": '{"details_retrieved":true}',
        "last_rich_google_retrieved_at": now.isoformat(), "google_retrieved_at": now.isoformat(),
        "google_rich_data_stale": False, "target_signals_json": "[]",
    }
    lead = Lead(**{**defaults, **changes})
    session.add(lead)
    session.flush()
    audit = WebsiteAuditRecord(
        lead_id=lead.id, url=lead.website, final_url=lead.website,
        reachable=True, status_code=200, created_at=now,
        checks_json=json.dumps(HEALTHY_CHECKS if checks is None else checks),
        evidence_json=json.dumps({"pages_sampled": lead.website}),
    )
    session.add(audit)
    session.flush()
    return lead, audit


def plan_for(session, lead):
    return build_adaptive_sales_plan_with_context(session, lead, competitors=[])


def assert_no_commercial_scope(plan, pricing, context):
    assert context.scope == ()
    assert plan.smart_offer.scope == ()
    assert plan.smart_offer.recommended_ask is None
    assert plan.smart_offer.easy_close is None
    assert plan.smart_offer.stretch is None
    assert not pricing.price_available
    assert pricing.project.low is None and pricing.project.high is None


def test_observed_contact_and_listing_counterfactual_selects_different_canonical_offer(storage):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        contact_plan, contact_price, contact_context = plan_for(session, lead)
        assert contact_context.offer_id == contact_plan.smart_offer.offer_id == contact_price.project.offer_id == "conversion_tune_up"
        assert contact_price.price_available
        audit.checks_json = json.dumps(HEALTHY_CHECKS)
        lead.has_hours = False
        session.flush()
        listing_plan, listing_price, listing_context = plan_for(session, lead)
        assert listing_context.offer_id == listing_plan.smart_offer.offer_id == listing_price.project.offer_id == "google_presence_cleanup"
        assert listing_price.price_available
        assert listing_context.context_fingerprint != contact_context.context_fingerprint
        assert tuple(listing_plan.smart_offer.scope) == listing_context.scope
        assert any(ref.startswith("google_places:") for ref in listing_context.intervention_assessment["evidence_refs"])


def test_raw_target_labels_and_filtered_candidate_position_cannot_create_a_need(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, lead_score=0)
        before = plan_for(session, lead)
        lead.target_signals_json = '["No CTA", "Missing service pages", "Mobile friction", "Huge search demand"]'
        lead.search_position = 99
        lead.lead_score = 100
        lead.sales_priority_score = 100
        after = plan_for(session, lead)
        assert before[2].intervention_assessment["state"] == after[2].intervention_assessment["state"] == "no_sale"
        assert after[2].intervention_assessment["ranked_candidates"] == before[2].intervention_assessment["ranked_candidates"]
        assert_no_commercial_scope(*after)


@pytest.mark.parametrize("corruption", ["stale", "future", "url_mismatch", "string_booleans"])
def test_ineligible_website_evidence_cannot_enable_paid_scope(storage, corruption):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE)
        if corruption == "stale":
            audit.created_at = utc_now() - timedelta(days=31)
        elif corruption == "future":
            audit.created_at = utc_now() + timedelta(days=1)
        elif corruption == "url_mismatch":
            audit.url = "https://unrelated.example"
        else:
            audit.checks_json = json.dumps({key: "false" for key in BROKEN_ROUTE})
        session.flush()
        result = plan_for(session, lead)
        assert result[2].intervention_assessment["state"] == "insufficient_evidence"
        assert_no_commercial_scope(*result)


@pytest.mark.parametrize("corruption", ["stale", "future", "refresh_failed", "untyped_details_flag"])
def test_ineligible_google_evidence_cannot_enable_listing_sale(storage, corruption):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, has_hours=False)
        if corruption == "stale":
            lead.last_rich_google_retrieved_at = (utc_now() - timedelta(days=31)).isoformat()
        elif corruption == "future":
            lead.last_rich_google_retrieved_at = (utc_now() + timedelta(days=1)).isoformat()
        elif corruption == "refresh_failed":
            lead.google_rich_data_stale = True
        else:
            lead.google_public_data_json = '{"details_retrieved":"true"}'
        result = plan_for(session, lead)
        assert result[2].intervention_assessment["state"] == "insufficient_evidence"
        assert_no_commercial_scope(*result)


def test_no_sale_has_no_new_price_or_scope_at_canonical_boundary(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        result = plan_for(session, lead)
        assert result[2].intervention_assessment["state"] == "no_sale"
        assert_no_commercial_scope(*result)
        assert "no" in result[0].smart_offer.offer_name.lower()
        rendered = format_smart_offer(result[0].smart_offer)
        assert "Pricing: no paid recommendation" in rendered
        assert "review Seller Pricing Intelligence" not in rendered


def test_no_sale_outreach_drafts_render_without_paid_pitch_or_indexing_empty_scope(storage, outbound):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        plan, pricing, _ = plan_for(session, lead)
        drafts = OutreachService(outbound.sender).generate_all(lead, session=session, adaptive_plan=plan, pricing=pricing)
        assert drafts
        for kind, (subject, body) in drafts.items():
            assert not re.search(r"\$\s*\d", subject + body), kind
            assert "One-Page Conversion Site" not in body, kind
            assert "the recommended scope begins with" not in body.lower(), kind
            assert "a focused first phase can start" not in body.lower(), kind


def test_no_sale_guided_call_contains_no_paid_offer_and_handles_empty_scope(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        guide = CallGuideService().build(session, lead, [])
        rendered = json.dumps(asdict(guide))
        assert guide.recommended_ask is None
        assert guide.research_only is True
        assert not re.search(r"\$\s*\d", rendered)
        assert "One-Page Conversion Site" not in rendered
        assert "the useful full-scope version" not in rendered.lower()


def test_no_sale_owner_reports_have_no_paid_menu_or_supported_scope_claim(storage):
    config, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        for kind in ("owner_full", "owner_short"):
            path = ReportService(config).generate_report(session, lead, report_kind=kind)
            rendered = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text(" ", strip=True)
            assert "No paid recommendation" in rendered
            assert not re.search(r"\$\s*\d", rendered)
            assert "One-Page Conversion Site" not in rendered
            assert "one-page mobile-first conversion website" not in rendered.lower()


def test_human_selection_stays_sticky_until_supported_advisory_is_explicitly_accepted(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, has_hours=False)
        selected = lead.recommended_offer_id
        log_activity(session, "offer_selected", json.dumps({"offer_id": selected}), lead.id)
        session.flush()
        prior_plan, prior_pricing, prior_context = plan_for(session, lead)
        assert prior_context.offer_id == selected
        assert prior_context.intervention_assessment["recommended_offer_id"] == "google_presence_cleanup"
        # The human may retain a catalog quote without that choice becoming the
        # machine's best-intervention claim. Acceptance alone changes identity.
        assert prior_plan.smart_offer.offer_id == prior_pricing.project.offer_id == selected
        assert prior_plan.smart_offer.offer_type == offer_definition(selected).semantic_family
        assert prior_context.scope == tuple(prior_plan.smart_offer.scope)
        assert prior_pricing.price_available
        assert "retained human-selected" in prior_plan.smart_offer.positioning.lower()
        assert "does not establish" in prior_plan.smart_offer.positioning.lower()
        assert "highest-leverage" in prior_plan.smart_offer.positioning.lower()
        with pytest.raises(ValueError):
            accept_advisory_offer(session, lead, "google_presence_cleanup", operator_confirmed=False)
        assert lead.recommended_offer_id == selected
        accept_advisory_offer(session, lead, "google_presence_cleanup", operator_confirmed=True)
        accepted_plan, accepted_pricing, accepted_context = plan_for(session, lead)
        assert accepted_context.offer_id == accepted_plan.smart_offer.offer_id == accepted_pricing.project.offer_id == "google_presence_cleanup"
        assert accepted_pricing.price_available


def test_unsupported_advisory_cannot_be_accepted_as_a_ranked_offer(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, has_hours=False)
        with pytest.raises(ValueError, match="current ranked candidate"):
            accept_advisory_offer(session, lead, "full_local_authority_site", operator_confirmed=True)
        assert lead.recommended_offer_id == "one_page_conversion_site"


def test_growth_score_does_not_inflate_catalog_cost_or_seller_ask(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE, lead_score=0)
        _, low, _ = plan_for(session, lead)
        lead.lead_score = 100
        lead.sales_priority_score = 100
        lead.search_position = 50
        _, high, _ = plan_for(session, lead)
        catalog = offer_definition("conversion_tune_up")
        assert (low.project.low, low.project.high) == (catalog.price_low, catalog.price_high)
        assert (high.project.low, high.project.high) == (catalog.price_low, catalog.price_high)
        assert (low.recommended, low.easy_close, low.stretch) == (high.recommended, high.easy_close, high.stretch)


@pytest.mark.parametrize("offer_id,score,expected_points", [
    ("google_presence_cleanup", 80, 10),
    ("google_presence_cleanup", 55, 8),
    ("conversion_tune_up", 30, 10),
    ("one_page_conversion_site", 30, 13),
])
def test_quote_band_change_does_not_redefine_legacy_qualification(storage, offer_id, score, expected_points):
    # Historical thresholds: high-value niche contributes 7, plus legacy band
    # midpoint points of 3, 1, 3 and 6 respectively. Quoting must not rewrite
    # these separate triage rules as a side effect of removing score premiums.
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, category="roofing", lead_score=score,
                               recommended_offer_id=offer_id, recommended_offer=offer_definition(offer_id).display_name)
        result = QualificationService().evaluate(session, lead)
        factor = next(item for item in result.factors if item.key == "commercial_potential")
        assert factor.points == expected_points


def test_growth_score_cannot_select_a_different_pricing_comparison_set(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = add_business(session, checks=BROKEN_ROUTE, lead_score=0)
        seller = SellerProfile(display_name="Synthetic seller")
        session.add(seller)
        session.flush()
        for index in range(12):
            session.add(OfferHistory(
                seller_profile_id=seller.id, offer_date="2026-09-30", business_name=f"Historic {index}",
                niche=lead.category, canonical_offer_id="conversion_tune_up", package_name="Conversion Tune-Up",
                scope_summary="mobile call/quote button; homepage CTA rewrite", initial_ask=500 + index * 20,
                status="Won", closed_amount=500 + index * 20, growth_score_at_offer=0 if index < 6 else 100,
            ))
        session.flush()
        _, low, _ = plan_for(session, lead)
        lead.lead_score = 100
        _, high, _ = plan_for(session, lead)
        assert [item.offer.id for item in low.comparable.offers] == [item.offer.id for item in high.comparable.offers]
        assert low.recommended == high.recommended


def test_approving_unpriced_research_does_not_manufacture_quote_authority(storage):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, google_public_data_json="{}")
        audit.checks_json = "{}"
        session.flush()
        plan, pricing, context = plan_for(session, lead)
        assert_no_commercial_scope(plan, pricing, context)
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Review", "Exact neutral body",
                                   proof_dependencies=[], commercial_snapshot=snapshot.to_dict())
        draft.approved = True
        session.flush()
        repeated = plan_for(session, lead)
        assert_no_commercial_scope(*repeated)
        assert draft_commercial_errors(session, draft) == ()


def test_no_sale_cannot_be_exported_as_a_priced_proposal(storage):
    from local_presence_miner.services.proposal_service import ProposalService

    config, factory = storage
    with factory() as session:
        lead, _ = add_business(session)
        with pytest.raises(ValueError, match="does not support a paid proposal"):
            ProposalService(config).generate_proposal(session, lead, selected_price=900)
        path = ProposalService(config).generate_proposal(session, lead)
        rendered = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text(" ", strip=True)
        assert "No paid recommendation" in rendered
        assert not re.search(r"\$\s*\d", rendered)


def test_approved_body_is_preserved_but_revoked_when_decisive_evidence_changes(storage):
    _, factory = storage
    with factory() as session:
        lead, audit = add_business(session, checks=BROKEN_ROUTE,
            recommended_offer_id="conversion_tune_up", recommended_offer="Conversion Tune-Up")
        _, pricing, context = plan_for(session, lead)
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        body = "Exact human-approved body; preserve the punctuation and agreed wording."
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Human subject", body,
                                   commercial_snapshot=snapshot.to_dict())
        draft.approved = True
        session.flush()
        assert draft_commercial_errors(session, draft) == ()
        audit.checks_json = json.dumps(HEALTHY_CHECKS)
        session.flush()
        assert recompute_lead_commercial_candidate(session, lead, "The owner verified the repaired contact path") == 1
        assert not draft.approved
        assert draft.commercial_dependency_state == "stale"
        assert draft.body == body
        history = list(session.scalars(select(OutreachApprovalHistory).where(OutreachApprovalHistory.lead_id == lead.id)))
        assert history and history[-1].body == body
        assert history[-1].commercial_dependency_fingerprint == snapshot.dependency_fingerprint

