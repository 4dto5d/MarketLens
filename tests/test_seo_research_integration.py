"""Real SQLite and commercial boundaries for query-scoped SEO research.

All observations are synthetic. No paid API, network or live ranking is used.
"""

import json
import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import log_activity, save_outreach_draft
from local_presence_miner.database.schema import Lead, LeadSearch, OutreachApprovalHistory, SEOResearchSnapshot, WebsiteAuditRecord
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_state_service import current_plan_dependency_errors, persist_current_plan
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.seo_research_service import (
    append_research,
    compare_research,
    parse_research_json,
    project_seo_research,
    research_binding,
    research_history,
    research_template,
)
from local_presence_miner.time_utils import utc_now

HEALTHY = {"https": True, "viewport": True, "tap_to_call": True, "contact_form": False,
           "sitewide_contact_path": True, "clear_primary_cta": True, "indexable_sample": True,
           "service_pages": True, "trust_signals": True}


@pytest.fixture
def storage(tmp_path):
    config = AppConfig(tmp_path, tmp_path / "seo.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    return config, factory


def business(session):
    search = LeadSearch(name="Recorded market", city="Austin", state_region="TX", niche="plumber")
    session.add(search)
    session.flush()
    now = utc_now()
    lead = Lead(search_id=search.id, place_id="seo-test-business", name="Local Plumbing", category="plumber",
                website="https://local.example", phone="555-0100", rating=4.8, review_count=100, has_hours=True, photo_count=12,
                recommended_offer="Full Local Authority Site", recommended_offer_id="full_local_authority_site",
                google_public_data_json='{"details_retrieved":true}', google_retrieved_at=now.isoformat(),
                last_rich_google_retrieved_at=now.isoformat(), qualification_class="Qualified", qualification_confidence="Moderate")
    session.add(lead)
    session.flush()
    audit = WebsiteAuditRecord(lead_id=lead.id, url=lead.website, reachable=True, status_code=200,
                              checks_json=json.dumps(HEALTHY), created_at=now)
    session.add(audit)
    session.flush()
    return lead, audit


def sample_payload(session, lead, **query_changes):
    query = {"query": "emergency plumber Austin TX", "service": "emergency plumbing", "service_state": "confirmed",
             "service_refs": ["https://local.example/emergency"], "intent": "local_commercial", "intent_basis": "Recorded service-intent SERP",
             "volume": 10, "difficulty": 20, "organic_rank": 12, "maps_rank": None,
             "organic_window": 50, "maps_window": None, "organic_complete": True, "maps_complete": False,
             "page_url": "https://local.example/emergency", "competitors": [
                 {"url": "https://other-plumber.example/emergency", "channel": "organic", "position": 3,
                  "kind": "local_business", "authority": 20, "referring_domains": 10}],
             "serp_features": [], "refs": ["manual:sample:1"]}
    return {"schema_version": 1, "subject": research_binding(session, lead)["subject"], "observed_at": utc_now().isoformat(),
            "source": {"provider": "manual_serp", "report": "synthetic-local-query-sample", "database": "manual",
                       "geography": "Austin TX", "geo_resolution": "local", "status": "complete", "reference": "synthetic:fixture", "demo": False},
            "queries": [{**query, **query_changes}],
            "pages": [{"url": "https://local.example/emergency", "title": "Home", "h1": ["Local service team"], "meta_description": "",
                       "canonical": "https://local.example/emergency", "robots": [], "status_code": 200, "indexability": "allowed",
                       "word_count": 500, "internal_links": [], "schema_types": ["Service"], "schema_errors": [],
                       "services": ["emergency plumbing"], "service_refs": ["https://local.example/emergency#service"]}]}


def plan(session, lead):
    return build_adaptive_sales_plan_with_context(session, lead, competitors=[])


def test_specific_rank_page_demand_changes_offer_and_scope_not_growth_score(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        before = plan(session, lead)
        assert before[2].intervention_assessment["state"] == "no_sale"
        row = append_research(session, lead, sample_payload(session, lead))
        after = plan(session, lead)
        assert after[2].offer_id == after[0].smart_offer.offer_id == after[1].project.offer_id == "conversion_tune_up"
        assert after[2].scope == ("local SEO title/meta/H1 fixes",)
        assert after[1].price_available
        assert any(ref.startswith(f"seo_snapshot:{row.id}:") for ref in after[2].intervention_assessment["evidence_refs"])
        price = after[1].recommended
        lead.lead_score = lead.sales_priority_score = 100
        assert plan(session, lead)[1].recommended == price
        assert lead.qualification_class == "Qualified"  # no lifecycle propagation


@pytest.mark.parametrize("field,value", [("target_zip_code", "78799"), ("target_radius_miles", 30),
                                           ("website", "https://other.example"), ("category", "roofer")])
def test_scope_changes_fail_closed_preserving_history(storage, field, value):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        row = append_research(session, lead, sample_payload(session, lead))
        original = row.payload_json
        setattr(lead, field, value)
        assert project_seo_research(session, lead)["state"] in {"mismatch", "invalid"}
        assert not project_seo_research(session, lead)["opportunities"]
        assert row.payload_json == original
        assert len(research_history(session, lead.id)) == 1


def test_latest_failed_or_partial_evidence_never_falls_back_to_old_success(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        payload = sample_payload(session, lead)
        first = append_research(session, lead, payload)
        for state in ("failed", "partial"):
            payload["source"]["status"] = state
            latest = append_research(session, lead, payload)
            report = project_seo_research(session, lead)
            assert report["state"] == state and not report["opportunities"]
            assert report["snapshot_id"] == latest.id != first.id
        assert len(research_history(session, lead.id)) == 3


def test_expiry_without_db_write_changes_material_commercial_dependency(storage, monkeypatch):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        row = append_research(session, lead, sample_payload(session, lead))
        _, pricing, context = plan(session, lead)
        persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        clock = utc_now() + timedelta(days=31)
        assert project_seo_research(session, lead, now=clock)["state"] == "stale"
        monkeypatch.setattr("local_presence_miner.services.intervention_evidence_service.utc_now", lambda: clock)
        assert current_plan_dependency_errors(session, lead)
        assert row.source_status == "complete"


def test_new_decisive_evidence_revokes_approval_not_human_body_or_historical_snapshot(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        payload = sample_payload(session, lead)
        append_research(session, lead, payload)
        _, pricing, context = plan(session, lead)
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        body = "Human approved and spoken text. Keep exactly this punctuation!"
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Human subject", body,
                                   commercial_snapshot=snapshot.to_dict())
        draft.approved = True
        session.flush()
        payload["queries"][0]["organic_rank"] = 2
        append_research(session, lead, payload)
        assert not draft.approved
        assert draft.body == body
        history = list(session.scalars(select(OutreachApprovalHistory).where(OutreachApprovalHistory.lead_id == lead.id)))
        assert history[-1].body == body
        assert lead.commercial_plan_state == "stale"


def test_human_selected_catalog_identity_stays_sticky(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        log_activity(session, "offer_selected", json.dumps({"offer_id": "google_presence_cleanup"}), lead.id)
        append_research(session, lead, sample_payload(session, lead))
        _, _, context = plan(session, lead)
        assert context.offer_id == "google_presence_cleanup"
        assert context.intervention_assessment["recommended_offer_id"] == "conversion_tune_up"
        assert context.selection_source == "intervention_advisory_locked"


def test_maps_gap_does_not_suppress_independently_observed_listing_correction(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        lead.has_hours = False
        append_research(session, lead, sample_payload(session, lead, organic_rank=2, maps_rank=12,
                                                     maps_window=20, maps_complete=True))
        _, pricing, context = plan(session, lead)
        assert context.offer_id == "google_presence_cleanup" and pricing.price_available
        assert context.scope == ("hours and contact cleanup checklist",)
        candidate = context.planning_inputs["intervention_decision"]["selected_candidate"]
        assert any(ref.startswith("seo_snapshot:") for ref in candidate["evidence_refs"])


def test_foreign_import_rejected_and_rollback_is_atomic(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        payload = sample_payload(session, lead)
        payload["subject"]["place_id"] = "different-business"
        prior = lead.commercial_plan_state
        with pytest.raises(ValueError, match="does not match"):
            append_research(session, lead, payload)
        assert not session.scalar(select(SEOResearchSnapshot))
        assert lead.commercial_plan_state == prior
        append_research(session, lead, sample_payload(session, lead))
        session.rollback()
        assert not session.scalar(select(SEOResearchSnapshot))


def test_ledger_is_immutable_at_orm_and_sql_boundaries_with_fk_off(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        row = append_research(session, lead, sample_payload(session, lead))
        session.commit()
        row.source_status = "failed"
        with pytest.raises(ValueError, match="immutable"):
            session.flush()
        session.rollback()
        for statement in ("UPDATE seo_research_snapshots SET source_status='failed'", "DELETE FROM seo_research_snapshots",
                          f"DELETE FROM leads WHERE id={lead.id}",
                          "INSERT INTO seo_research_snapshots "
                          "(lead_id,schema_version,binding_json,payload_json,payload_sha256,source_status,observed_at,created_at) "
                          "VALUES (999999,1,'{}','{}','bad','complete','now','now')"):
            with pytest.raises(IntegrityError):
                session.execute(text(statement))
            session.rollback()
        assert session.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_additive_migration_backup_idempotence_and_conservative_empty_state(storage):
    config, factory = storage
    with factory() as session:
        lead, _ = business(session)
        session.commit()
        lead_id = lead.id
    # Simulate a real parent DB: it has no new table or guards.
    with factory.kw["bind"].begin() as connection:
        for name in ("seo_snapshot_lead_fk", "seo_snapshot_no_update", "seo_snapshot_no_delete", "seo_snapshot_restrict_lead_delete"):
            connection.execute(text(f"DROP TRIGGER {name}"))
        connection.execute(text("DROP TABLE seo_research_snapshots"))
    initialize_database(factory)
    backup = config.database_path.with_suffix(".sqlite3.backup-before-seo-intelligence")
    assert backup.is_file()
    original = backup.read_bytes()
    initialize_database(factory)
    assert backup.read_bytes() == original
    with sqlite3.connect(backup) as before:
        assert not before.execute("SELECT name FROM sqlite_master WHERE name='seo_research_snapshots'").fetchall()
        assert before.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert project_seo_research(session, lead)["state"] == "missing"
        assert not session.scalar(select(SEOResearchSnapshot))
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_historical_rank_and_competitor_comparison_not_causal_lift(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        payload = sample_payload(session, lead)
        payload["queries"][0]["competitors"] = [{"url": "https://competitor.example/service", "channel": "organic", "position": 1,
                                                 "kind": "local_business", "authority": 20, "referring_domains": 10}]
        first = append_research(session, lead, payload)
        payload["queries"][0]["organic_rank"] = 8
        payload["queries"][0]["competitors"][0]["position"] = 2
        second = append_research(session, lead, payload)
        comparison = compare_research(session, lead.id, first.id, second.id)
        assert comparison["comparable"]
        assert comparison["changes"][0]["positions_improved"] == 4
        assert comparison["changes"][1]["before"] == 1 and comparison["changes"][1]["after"] == 2
        assert "causality" in comparison["limitation"]
        payload["queries"][0]["organic_window"] = 100
        third = append_research(session, lead, payload)
        assert not compare_research(session, lead.id, second.id, third.id)["changes"]


def test_generated_template_is_hypothesis_and_strict_json_rejects_corruption(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        row = append_research(session, lead, research_template(session, lead))
        assert row.source_status == "partial"
        assert not project_seo_research(session, lead)["opportunities"]
    for value in ('{"source":{},"source":{}}', '{"volume":NaN}', '[]'):
        with pytest.raises(ValueError):
            parse_research_json(value)


def test_internal_report_shows_research_owner_report_does_not_leak_advisory_actions(storage):
    config, factory = storage
    with factory() as session:
        lead, _ = business(session)
        append_research(session, lead, sample_payload(session, lead))
        service = ReportService(config)
        internal = service.generate_report(session, lead, "internal").read_text(encoding="utf-8")
        owner = service.generate_report(session, lead, "owner_full").read_text(encoding="utf-8")
        assert "Query-scoped SEO research" in internal
        assert "Query-scoped SEO research" not in owner
        assert "DO NOT SEND" not in owner and "SEND /" not in owner
        assert "local SEO title/meta/H1 fixes" in owner


def test_offscreen_panel_displays_missing_then_research_without_starting_acquisition(storage):
    from PySide6.QtWidgets import QApplication

    from local_presence_miner.ui.widgets.seo_intelligence_widget import SEOIntelligenceWidget

    _, factory = storage
    app = QApplication.instance() or QApplication([])
    with factory() as session:
        lead, _ = business(session)
        session.commit()
        lead_id = lead.id
    widget = SEOIntelligenceWidget(factory, lead_id)
    assert "MISSING" in widget.status.text()
    with factory() as session:
        lead = session.get(Lead, lead_id)
        append_research(session, lead, sample_payload(session, lead))
        session.commit()
    for width, height in ((1366, 768), (1920, 1080)):
        widget.resize(width, height)
        widget.refresh()
        widget.show()
        app.processEvents()
        assert widget.table.rowCount() == 1
        assert "COMPLETE" in widget.status.text()
        assert "seo_snapshot:" in widget.details.toPlainText()
    widget.close()


def test_cli_template_import_and_show_use_same_application_boundary(storage, tmp_path, capsys):
    from local_presence_miner.services.seo_research_cli import main

    config, factory = storage
    with factory() as session:
        lead, _ = business(session)
        session.commit()
        lead_id = lead.id
    output = tmp_path / "template.json"
    prefix = ["--database", str(config.database_path), "--lead", str(lead_id)]
    assert main([*prefix, "template", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["source"]["status"] == "partial"
    assert main([*prefix, "import-json", "--input", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "partial"
    assert main([*prefix, "show"]) == 0
    assert json.loads(capsys.readouterr().out)["opportunities"] == []


def test_cli_refuses_missing_database_without_creating_it(tmp_path):
    from local_presence_miner.services.seo_research_cli import main

    path = tmp_path / "never-created.sqlite3"
    with pytest.raises(SystemExit) as exc:
        main(["--database", str(path), "--lead", "1", "show"])
    assert exc.value.code == 2 and not path.exists()


def test_ledger_fk_guard_restricts_rekey_on_fk_off_connection(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        append_research(session, lead, sample_payload(session, lead))
        session.commit()
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE leads SET id=9999 WHERE id=:lead"), {"lead": lead.id})
        session.rollback()
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
