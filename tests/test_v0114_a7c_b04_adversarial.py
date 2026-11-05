from __future__ import annotations

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database, migrate_v0114_b04_commercial_state
from local_presence_miner.database.pricing_repository import (
    deactivate_seller_project,
    save_seller_profile,
    save_seller_project,
)
from local_presence_miner.database.repositories import save_outreach_draft
from local_presence_miner.database.schema import AppSetting, CompetitorRecord, Lead, OutreachApprovalHistory
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_state_service import persist_current_plan
from local_presence_miner.services.report_service import ReportService


def _lead() -> Lead:
    return Lead(
        place_id="a7c-roofing",
        name="A7C Roofing",
        category="roofing",
        website="https://example.test",
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        qualification_class="Qualified",
        qualification_confidence="Moderate",
        qualification_json='{"classification":"Qualified","confidence":"Moderate"}',
        target_signals_json='["No obvious quote request path"]',
    )


def _current(session, lead: Lead):
    _plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
    return persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)


def _approved(session, lead: Lead):
    snapshot = _current(session, lead)
    draft = save_outreach_draft(
        session, lead.id, OutreachKind.INITIAL_EMAIL, "Subject", "Historical body", commercial_snapshot=snapshot.to_dict()
    )
    draft.approved = True
    return draft


def test_project_count_change_revokes_dependent_approval_without_artifact(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "project-count.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        project = save_seller_project(
            session, project_type="Paid Project", title="Completed site", status="Completed", niche="roofing", client_work=True,
            counting_state="confirmed",
        )
        draft = _approved(session, lead)
        deactivate_seller_project(session, project.id)
        assert lead.commercial_plan_state == "stale"
        assert not draft.approved
        assert session.query(OutreachApprovalHistory).one().body == "Historical body"


def test_unrelated_incomplete_project_is_a_noop(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "unrelated-project.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        draft = _approved(session, lead)
        save_seller_project(
            session, project_type="Unpaid Project", title="Incomplete", status="In Progress", niche="dentist", client_work=False,
            counting_state="incomplete",
        )
        assert lead.commercial_plan_state == "current"
        assert draft.approved


def test_private_profile_notes_do_not_revoke_current_assets(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "private-profile.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        draft = _approved(session, lead)
        save_seller_profile(session, display_name="", business_name="", notes="private reminder")
        assert lead.commercial_plan_state == "current"
        assert draft.approved


def test_used_profile_field_does_not_revoke_when_not_consumed(tmp_path) -> None:
    """Current B04 plans do not render seller identity fields, so no dependency exists."""
    factory = create_session_factory(tmp_path / "public-profile.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        draft = _approved(session, lead)
        save_seller_profile(session, display_name="MarketLens", business_name="", notes="")
        assert lead.commercial_plan_state == "current"
        assert draft.approved


def test_recomputed_snapshot_is_bound_to_plan_context(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "context.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        snapshot = _current(session, lead)
        assert snapshot.dependencies["current_offer_context"]["context_fingerprint"] == snapshot.current_offer_context_fingerprint


def test_legacy_approved_draft_is_preserved_then_revoked_once(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "legacy-b04.sqlite3")
    initialize_database(factory)
    with factory.begin() as session:
        session.delete(session.get(AppSetting, "v0114_b04_commercial_state_migrated"))
        lead = _lead()
        lead.starting_offer_json = '{"scope":["legacy raw scope"]}'
        session.add(lead)
        session.flush()
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Legacy", "Exact legacy body")
        draft.approved = True
    migrate_v0114_b04_commercial_state(factory)
    migrate_v0114_b04_commercial_state(factory)
    with factory() as session:
        draft = session.query(type(draft)).one()
        assert not draft.approved
        assert draft.commercial_dependency_state == "legacy_unknown_review_required"
        history = session.query(OutreachApprovalHistory).all()
        assert len(history) == 1
        assert history[0].body == "Exact legacy body"
        assert session.get(Lead, lead.id).legacy_starting_offer_json == '{"scope":["legacy raw scope"]}'


def test_dependency_distinct_reports_do_not_overwrite_prior_bytes(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "artifacts.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory.begin() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        competitor = CompetitorRecord(
            lead_id=lead.id, competitor_place_id="competitor-1", competitor_name="Rival", website_url="https://rival.test"
        )
        session.add(competitor)
        session.flush()
        first = ReportService(config).generate_report(session, lead)
        before = first.read_bytes()
        competitor.website_url = "https://new-rival.test"
        second = ReportService(config).generate_report(session, lead)
        assert first != second
        assert first.read_bytes() == before
