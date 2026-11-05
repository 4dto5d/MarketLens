"""Independent, local-only reproductions at SEO persistence and UI boundaries."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import save_outreach_draft
from local_presence_miner.database.schema import ActivityLog, Lead, LeadSearch, SEOResearchSnapshot, WebsiteAuditRecord
from local_presence_miner.domain.commercial import canonical_json, fingerprint
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_state_service import draft_commercial_errors, persist_current_plan
from local_presence_miner.services.seo_research_service import append_research, compare_research, project_seo_research, research_binding, research_history
from local_presence_miner.time_utils import utc_now


@pytest.fixture
def boundary_store(tmp_path):
    config = AppConfig(tmp_path, tmp_path / "boundary.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        search = LeadSearch(name="Independent recorded market", city="Denver", state_region="CO", niche="plumber")
        session.add(search)
        session.flush()
        now = utc_now() - timedelta(seconds=1)
        lead = Lead(search_id=search.id, place_id="independent-business", name="Independent Plumbing", category="plumber",
                    website="https://independent.example", phone="555-0100", has_hours=True, rating=4.9, review_count=50, photo_count=12,
                    google_public_data_json='{"details_retrieved":true}', google_retrieved_at=now.isoformat(),
                    last_rich_google_retrieved_at=now.isoformat(), qualification_class="Qualified", qualification_confidence="Moderate")
        session.add(lead)
        session.flush()
        checks = {"https": True, "viewport": True, "tap_to_call": True, "contact_form": False, "sitewide_contact_path": True,
                  "clear_primary_cta": True, "indexable_sample": True, "service_pages": True, "trust_signals": True}
        audit = WebsiteAuditRecord(lead_id=lead.id, url=lead.website, reachable=True, status_code=200, checks_json=json.dumps(checks),
                                  evidence_json=json.dumps({"seo_pages_v1": json.dumps([page_fact()])}), created_at=now)
        session.add(audit)
        session.commit()
        lead_id = lead.id
    yield config, factory, lead_id
    factory.kw["bind"].dispose()


def page_fact(url="https://independent.example/emergency"):
    return {"url": url, "title": "Home", "h1": ["Local service team"], "meta_description": "", "canonical": url,
            "robots": [], "status_code": 200, "indexability": "allowed", "word_count": 600, "internal_links": [],
            "schema_types": ["Service"], "schema_errors": [], "services": ["emergency plumbing"], "service_refs": [f"{url}#service"]}


def boundary_payload(session, lead):
    stamp = (utc_now() - timedelta(seconds=1)).isoformat()
    return {"schema_version": 1, "subject": research_binding(session, lead)["subject"], "observed_at": stamp,
            "source": {"provider": "manual_serp", "report": "independent query fixture", "database": "manual", "geography": "Denver CO",
                       "geo_resolution": "local", "status": "complete", "reference": "manual:capture:1", "demo": False},
            "queries": [{"query": "emergency plumber Denver CO", "service": "emergency plumbing", "service_state": "confirmed",
                         "service_refs": ["owner:service-confirmation:1"], "intent": "local_commercial", "intent_basis": "Explicit local service request",
                         "volume": 5, "difficulty": 20, "organic_rank": 12, "maps_rank": 2, "organic_window": 20, "maps_window": 3,
                         "organic_complete": True, "maps_complete": True, "page_url": "https://independent.example/emergency",
                         "competitors": [{"url": "https://competitor.example/emergency", "channel": "organic", "position": 1,
                                          "kind": "local_business", "authority": 20, "referring_domains": 10}],
                         "serp_features": [], "refs": ["manual:serp:Denver:1"]}],
            "pages": [page_fact()]}


def insert_checkpoint(session, lead, payload, *, binding=None, sha256=None, schema_version=1):
    row = SEOResearchSnapshot(lead_id=lead.id, schema_version=schema_version,
                              binding_json=canonical_json(binding or research_binding(session, lead)),
                              payload_json=canonical_json(payload), payload_sha256=sha256 or fingerprint(payload),
                              source_status=payload["source"]["status"], observed_at=payload["observed_at"])
    session.add(row)
    session.flush()
    return row


def test_committed_audit_pages_attach_with_original_timezone_and_capture_age(boundary_store):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        payload = boundary_payload(session, lead)
        payload["pages"] = []
        original_audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead_id))
        row = append_research(session, lead, payload)
        attached = json.loads(row.payload_json)["pages"]
        assert len(attached) == 1
        assert attached[0]["source_ref"].startswith(f"website_audit:{original_audit.id}:")
        assert attached[0]["observed_at"].startswith(original_audit.created_at.date().isoformat())


@pytest.mark.parametrize("days", [-1, 31])
def test_old_or_future_persisted_audit_cannot_be_relabelled_as_current_page(boundary_store, days):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead_id))
        audit.created_at = utc_now() - timedelta(days=days)
        session.commit()
    with factory() as session:
        lead = session.get(Lead, lead_id)
        payload = boundary_payload(session, lead)
        payload["pages"] = []
        row = append_research(session, lead, payload)
        assert json.loads(row.payload_json)["pages"] == []
        assert not any(op["decision"] == "recommended" for op in project_seo_research(session, lead)["opportunities"])


def test_query_returning_contact_page_cannot_borrow_other_page_for_paid_targeting(boundary_store):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        payload = boundary_payload(session, lead)
        append_research(session, lead, payload)
        assert any(op["decision"] == "recommended" for op in project_seo_research(session, lead)["opportunities"])
        payload["queries"][0]["page_url"] = "https://independent.example/contact"
        # The SERP-observed URL differs from the service page in the supplied sample.
        append_research(session, lead, payload)
        report = project_seo_research(session, lead)
        assert not any(op["decision"] == "recommended" for op in report["opportunities"])
        _, _, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.intervention_assessment["state"] != "recommended"


@pytest.mark.parametrize("corruption", ["hash", "binding", "schema", "subject"])
def test_current_projection_fails_closed_for_corrupt_metadata(boundary_store, corruption):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        payload = boundary_payload(session, lead)
        binding = research_binding(session, lead)
        options = {}
        if corruption == "hash":
            options["sha256"] = "0" * 64
        elif corruption == "binding":
            binding["target_zip_code"] = "80299"
            options["binding"] = binding
        elif corruption == "schema":
            options["schema_version"] = 2
        else:
            payload["subject"]["place_id"] = "other-business"
        insert_checkpoint(session, lead, payload, **options)
        report = project_seo_research(session, lead)
        assert report["state"] in {"mismatch", "invalid"} and report["opportunities"] == []


def test_corrupted_historical_binding_is_not_comparable_even_when_equal(boundary_store):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        before = boundary_payload(session, lead)
        after = deepcopy(before)
        after["queries"][0]["organic_rank"] = 4
        foreign_binding = {"subject": {**before["subject"], "place_id": "foreign"}}
        first = insert_checkpoint(session, lead, before, binding=foreign_binding)
        second = insert_checkpoint(session, lead, after, binding=foreign_binding)
        assert not compare_research(session, lead_id, first.id, second.id)["comparable"]


def test_future_historical_capture_cannot_claim_positions_improved(boundary_store):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        before = boundary_payload(session, lead)
        first = append_research(session, lead, before)
        after = deepcopy(before)
        after["observed_at"] = (utc_now() + timedelta(days=1)).isoformat()
        after["queries"][0]["organic_rank"] = 4
        second = append_research(session, lead, after)
        report = project_seo_research(session, lead)
        assert report["state"] == "future" and not report["opportunities"]
        assert not compare_research(session, lead_id, first.id, second.id)["comparable"]


def test_past_historical_captures_remain_comparable_after_current_evidence_expires(boundary_store):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        before = boundary_payload(session, lead)
        before["observed_at"] = (utc_now() - timedelta(days=90)).isoformat()
        before["pages"][0]["observed_at"] = before["observed_at"]
        first = append_research(session, lead, before)
        after = deepcopy(before)
        after["observed_at"] = (utc_now() - timedelta(days=60)).isoformat()
        after["pages"][0]["observed_at"] = after["observed_at"]
        after["queries"][0]["organic_rank"] = 8
        second = append_research(session, lead, after)
        assert project_seo_research(session, lead)["state"] == "stale"
        comparison = compare_research(session, lead_id, first.id, second.id)
        assert comparison["comparable"]
        rank_change = next(item for item in comparison["changes"] if "positions_improved" in item)
        assert rank_change["positions_improved"] == 4


def test_insert_or_replace_cannot_overwrite_immutable_checkpoint(boundary_store):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        row = append_research(session, lead, boundary_payload(session, lead))
        session.commit()
        original = row.payload_json
        replacement = json.loads(original)
        replacement["source"]["status"] = "failed"
        statement = text("INSERT OR REPLACE INTO seo_research_snapshots "
                         "(id,lead_id,schema_version,binding_json,payload_json,payload_sha256,source_status,observed_at,created_at) "
                         "VALUES (:identity,:lead,1,:binding,:payload,:sha,'failed',:observed,:created)")
        with pytest.raises(IntegrityError):
            session.execute(statement, {"identity": row.id, "lead": lead.id, "binding": row.binding_json,
                                        "payload": canonical_json(replacement), "sha": fingerprint(replacement),
                                        "observed": replacement["observed_at"], "created": row.created_at})
        session.rollback()
        session.expire_all()
        assert session.get(SEOResearchSnapshot, row.id).payload_json == original


def test_commercial_refresh_exception_preserves_source_and_records_warning(boundary_store, monkeypatch):
    _, factory, lead_id = boundary_store

    def fail_projection(*_args, **_kwargs):
        raise RuntimeError("Independent injected projection failure")

    monkeypatch.setattr("local_presence_miner.services.commercial_state_service.recompute_lead_commercial_candidate", fail_projection)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        lead.commercial_plan_state = "current"
        payload = boundary_payload(session, lead)
        row = append_research(session, lead, payload)
        row_id = row.id
        assert lead.commercial_plan_state == "stale"
        session.commit()
    with factory() as session:
        row = session.get(SEOResearchSnapshot, row_id)
        assert row.source_status == "complete" and json.loads(row.payload_json)["source"]["status"] == "complete"
        warnings = list(session.scalars(select(ActivityLog).where(ActivityLog.action == "seo_commercial_refresh_warning")))
        assert len(warnings) == 1 and "RuntimeError" in warnings[0].message


def test_preledger_backup_failure_aborts_before_mutating_parent_database(boundary_store, monkeypatch):
    config, factory, lead_id = boundary_store
    with factory.kw["bind"].begin() as connection:
        triggers = connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'seo_snapshot_%'")).scalars().all()
        for name in triggers:
            connection.execute(text(f"DROP TRIGGER {name}"))
        connection.execute(text("DROP TABLE seo_research_snapshots"))
    original = hashlib.sha256(config.database_path.read_bytes()).hexdigest()

    def fail_backup(_engine):
        raise RuntimeError("Independent injected preledger backup failure")

    with monkeypatch.context() as patch:
        patch.setattr("local_presence_miner.database.migrations.backup_database_before_seo_research", fail_backup)
        with pytest.raises(RuntimeError, match="preledger backup failure"):
            initialize_database(factory)
    assert hashlib.sha256(config.database_path.read_bytes()).hexdigest() == original
    with factory() as session:
        assert session.get(Lead, lead_id).place_id == "independent-business"
        assert not session.execute(text("SELECT name FROM sqlite_master WHERE name='seo_research_snapshots'")).all()
    initialize_database(factory)
    with factory() as session:
        assert session.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert not session.scalar(select(SEOResearchSnapshot))


def test_page_age_expiry_blocks_copy_without_rewriting_human_draft(boundary_store, monkeypatch):
    _, factory, lead_id = boundary_store
    with factory() as session:
        lead = session.get(Lead, lead_id)
        payload = boundary_payload(session, lead)
        capture = utc_now() - timedelta(days=29)
        payload["pages"][0]["observed_at"] = capture.isoformat()
        row = append_research(session, lead, payload)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.intervention_assessment["state"] == "recommended"
        plan = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        body = "Human quoted copy: exact wording and punctuation remain untouched."
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Quoted human subject", body,
                                   commercial_snapshot=plan.to_dict())
        draft.approved = True
        session.flush()
        clock = utc_now() + timedelta(days=2)
        monkeypatch.setattr("local_presence_miner.services.intervention_evidence_service.utc_now", lambda: clock)
        assert draft_commercial_errors(session, draft)
        assert not draft.approved and draft.body == body
        assert row.source_status == "complete"
        assert json.loads(row.payload_json)["pages"][0]["observed_at"] == capture.isoformat()


def test_ui_current_refresh_survives_corrupt_historical_json_and_clears_prior_advice(boundary_store):
    from PySide6.QtWidgets import QApplication

    from local_presence_miner.ui.widgets.seo_intelligence_widget import SEOIntelligenceWidget

    _, factory, lead_id = boundary_store
    app = QApplication.instance() or QApplication([])
    with factory() as session:
        lead = session.get(Lead, lead_id)
        append_research(session, lead, boundary_payload(session, lead))
        session.commit()
    widget = SEOIntelligenceWidget(factory, lead_id)
    assert widget.table.rowCount() == 1
    with factory() as session:
        session.execute(text("INSERT INTO seo_research_snapshots "
                             "(lead_id,schema_version,binding_json,payload_json,payload_sha256,source_status,observed_at,created_at) "
                             "VALUES (:lead,1,'{}','broken JSON','bad','complete','bad','2026-10-02 00:00:00')"), {"lead": lead_id})
        session.commit()
    try:
        refresh_error = ""
        try:
            widget.refresh()
        except ValueError as exc:
            refresh_error = str(exc)
        app.processEvents()
        assert widget.table.rowCount() == 0, f"Prior advice still displayed after corrupt current checkpoint; refresh error: {refresh_error}"
        assert "INVALID" in widget.status.text()
        with factory() as session:
            assert len(research_history(session, lead_id)) == 2
    finally:
        widget.close()
