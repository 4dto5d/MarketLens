from __future__ import annotations

from pathlib import Path

import pytest

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import backup_database_before_v0114_b04, initialize_database
from local_presence_miner.database.pricing_repository import (
    save_offer_history,
    save_seller_profile,
    save_seller_project,
    save_seller_proof,
)
from local_presence_miner.database.repositories import save_competitors, update_lead_fields
from local_presence_miner.database.schema import AppSetting, GooglePresenceAssessment, Lead, OutreachDraft, WebsiteAuditRecord
from local_presence_miner.domain.models import CompetitorMatch
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.commercial_plan_service import build_current_offer_context
from local_presence_miner.services.commercial_state_service import persist_current_plan
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.report_service import ReportService


def _lead(*, place_id: str = "chatfix-roofing") -> Lead:
    return Lead(
        place_id=place_id,
        name="ChatFix Roofing",
        category="roofing",
        phone="555-0101",
        website="https://example.test",
        lead_score=80,
        sales_priority_score=78,
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        qualification_class="Qualified",
        qualification_confidence="Moderate",
        qualification_json=(
            '{"classification":"Qualified","confidence":"Moderate",'
            '"positives":["Clear service need"],"disconfirmers":[],"unknowns":[]}'
        ),
        target_signals_json='["No obvious quote request path"]',
        audit=WebsiteAuditRecord(url="https://example.test", reachable=True, status_code=200,
                                checks_json='{"sitewide_contact_path":false,"tap_to_call":false,"contact_form":false}'),
    )


def _persist_current(session, lead: Lead):
    plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
    snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
    return plan, pricing, context, snapshot


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(tmp_path, tmp_path / "artifacts.sqlite3", tmp_path / "app.log", tmp_path)


def test_unrelated_completed_unpaid_other_niche_project_is_not_material(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "unrelated.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        _persist_current(session, lead)
        original_fingerprint = lead.commercial_dependency_fingerprint

        save_seller_project(
            session,
            project_type="Unpaid Project",
            title="Unrelated dental project",
            status="Completed",
            niche="dentist",
            client_work=True,
            counting_state="confirmed",
        )

        assert lead.commercial_plan_state == "current"
        assert lead.commercial_dependency_fingerprint == original_fingerprint



def test_truly_unrelated_proof_change_does_not_stale_commercial_plan(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "unrelated-proof.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        proof = save_seller_proof(
            session,
            proof_type="Certification",
            title="Unrelated dental certification",
            status="Completed + Verified",
            niche="dentist",
            verified=True,
            internal_only=True,
        )
        _persist_current(session, lead)
        original_fingerprint = lead.commercial_dependency_fingerprint

        save_seller_proof(
            session,
            proof_id=proof.id,
            proof_type="Certification",
            title="Unrelated dental certification updated",
            status="Completed",
            niche="dentist",
            verified=False,
            internal_only=True,
        )

        assert lead.commercial_plan_state == "current"
        assert lead.commercial_dependency_fingerprint == original_fingerprint

def test_same_niche_testimonial_change_is_material_to_pricing(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "testimonial.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        _persist_current(session, lead)

        save_seller_proof(
            session,
            proof_type="Testimonial",
            title="Roofing testimonial",
            status="Completed + Testimonial",
            niche="roofing",
            verified=True,
            testimonial_available=True,
            internal_only=True,
        )

        assert lead.commercial_plan_state == "stale"


def test_selected_offer_history_lost_reason_change_is_material(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "offer-history.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        offer = save_offer_history(
            session,
            offer_date="2026-09-01",
            business_name="Prior Roofing",
            niche="roofing",
            package_name="Conversion Tune-Up",
            canonical_offer_id="conversion_tune_up",
            scope_summary="Homepage CTA and estimate/request flow",
            initial_ask=1200,
            status="Lost",
            lost_reason="Other",
            growth_score_at_offer=80,
            project_value_low_at_offer=700,
            project_value_high_at_offer=1800,
        )
        _plan, pricing, context, _snapshot = _persist_current(session, lead)
        assert any(item.offer.id == offer.id for item in pricing.comparable.offers)

        save_offer_history(
            session,
            offer_id=offer.id,
            offer_date=offer.offer_date,
            business_name=offer.business_name,
            niche=offer.niche,
            package_name=offer.package_name,
            canonical_offer_id=offer.canonical_offer_id,
            scope_summary=offer.scope_summary,
            initial_ask=offer.initial_ask,
            status="Lost",
            lost_reason="Too expensive",
            growth_score_at_offer=offer.growth_score_at_offer,
            project_value_low_at_offer=offer.project_value_low_at_offer,
            project_value_high_at_offer=offer.project_value_high_at_offer,
        )

        assert context.offer_id == "conversion_tune_up"
        assert lead.commercial_plan_state == "stale"


def test_call_guide_fingerprint_covers_rendered_seller_identity(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "guide.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        save_seller_profile(session, display_name="Alice", business_name="Alpha")
        first = CallGuideService().build(session, lead, [])
        first_identity = next(branch.response for branch in first.branches if branch.key == "who_are_you")

        save_seller_profile(session, display_name="Bob", business_name="Beta")
        second = CallGuideService().build(session, lead, [])
        second_identity = next(branch.response for branch in second.branches if branch.key == "who_are_you")

        assert first_identity != second_identity
        assert first.commercial_dependency_fingerprint != second.commercial_dependency_fingerprint


def test_current_context_fingerprint_covers_google_and_qualification_inputs(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "context-inputs.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        assessment = GooglePresenceAssessment(
            lead_id=lead.id,
            google_presence_score=40,
            opportunity_score=50,
            confidence="Low",
            observed_gaps_json='["Weak Google evidence"]',
            competitor_summary_json='["Competitor has fuller profile"]',
            recommended_action="Website + Google Presence",
        )
        session.add(assessment)
        session.flush()

        first, _ = build_current_offer_context(session, lead, competitors=[])
        assessment.google_presence_score = 75
        assessment.opportunity_score = 65
        assessment.confidence = "Strong"
        session.flush()
        second, _ = build_current_offer_context(session, lead, competitors=[])
        assert first.context_fingerprint != second.context_fingerprint

        lead.qualification_json = (
            '{"classification":"High Priority","confidence":"Strong",'
            '"positives":["Owner confirmed need"],"disconfirmers":[],"unknowns":[]}'
        )
        session.flush()
        third, _ = build_current_offer_context(session, lead, competitors=[])
        assert second.context_fingerprint != third.context_fingerprint



def test_lead_score_and_first_competitor_mutation_recompute_freshness(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "mutation-seams.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        _persist_current(session, lead)

        update_lead_fields(session, lead.id, lead_score=35)
        assert lead.commercial_plan_state == "stale"

    # Use a fresh DB so the first-competitor assertion starts from CURRENT.
    factory = create_session_factory(tmp_path / "competitor-seam.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead(place_id="chatfix-competitor")
        session.add(lead)
        session.flush()
        _persist_current(session, lead)
        save_competitors(
            session,
            lead.id,
            [CompetitorMatch("comp-1", "Nearby Roofer", 90, "same niche")],
        )
        assert lead.commercial_plan_state == "stale"

def test_existing_corrupt_b04_backup_is_rejected(tmp_path) -> None:
    database = tmp_path / "backup.sqlite3"
    factory = create_session_factory(database)
    initialize_database(factory)
    with factory.begin() as session:
        marker = session.get(AppSetting, "v0114_b04_commercial_state_migrated")
        if marker is not None:
            session.delete(marker)
    backup = database.with_suffix(database.suffix + ".backup-before-v0114-b04")
    backup.write_bytes(b"not a sqlite database")

    with pytest.raises(RuntimeError, match="backup is unreadable"):
        backup_database_before_v0114_b04(factory.kw["bind"])


def test_report_identity_covers_exact_rendered_draft_and_lead_fields(tmp_path) -> None:
    config = _config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        draft = OutreachDraft(lead_id=lead.id, kind="initial_email", subject="Subject", body="Body one")
        session.add(draft)
        session.flush()

        first_internal = ReportService(config).generate_report(session, lead, "internal")
        first_internal_bytes = first_internal.read_bytes()
        draft.body = "Body two"
        session.flush()
        second_internal = ReportService(config).generate_report(session, lead, "internal")
        assert first_internal != second_internal
        assert first_internal.read_bytes() == first_internal_bytes

        first_owner = ReportService(config).generate_report(session, lead, "owner_full")
        first_owner_bytes = first_owner.read_bytes()
        lead.phone = "555-0102"
        session.flush()
        second_owner = ReportService(config).generate_report(session, lead, "owner_full")
        assert first_owner != second_owner
        assert first_owner.read_bytes() == first_owner_bytes


def test_proposal_and_package_identity_cover_rendered_or_manifest_only_changes(tmp_path) -> None:
    config = _config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()

        # Legacy triage factors are internal-only, not owner-facing claims.
        first_proposal = ProposalService(config).generate_proposal(session, lead, internal=True)
        first_proposal_bytes = first_proposal.read_bytes()
        lead.score_breakdown_json = '[{"label":"manual evidence change","points":1}]'
        session.flush()
        second_proposal = ProposalService(config).generate_proposal(session, lead, internal=True)
        assert first_proposal != second_proposal
        assert first_proposal.read_bytes() == first_proposal_bytes

        first_package = LeadPackageService(config).export_package(session, lead)
        first_package_bytes = first_package.read_bytes()
        lead.phone = "555-0109"
        session.flush()
        second_package = LeadPackageService(config).export_package(session, lead)
        assert first_package != second_package
        assert first_package.read_bytes() == first_package_bytes
