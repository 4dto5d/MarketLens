from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.schema import AppSetting, Lead, LeadSearch, SearchMarketQuery, SearchMarketRun, SearchVisibilityProbe
from local_presence_miner.domain.models import SearchCriteria, SearchVisibilityAcquisition, VisibilityObservationCapture
from local_presence_miner.services.demo_data import load_demo_businesses
from local_presence_miner.services.google_places import GooglePlacesError
from local_presence_miner.services.query_universe_service import generate_query_universe
from local_presence_miner.services.search_market_analysis import project_search_market
from local_presence_miner.services.search_market_service import SearchMarketService
from local_presence_miner.services.search_visibility_service import (
    demo_visibility_acquisition,
    persist_visibility_acquisition,
    visibility_context_fingerprint,
)
from local_presence_miner.time_utils import utc_now


def test_query_universe_is_deterministic_clustered_provenanced_and_bounded() -> None:
    first = generate_query_universe("pest control", "Denver", "CO", limit=40)
    second = generate_query_universe("pest control", "Denver", "CO", limit=40)
    assert first == second
    assert 5 <= len(first) <= 24
    assert len({item.query_id for item in first}) == len(first)
    assert len({item.normalized_query for item in first}) == len(first)
    assert any(item.cluster_id.endswith(":rodent_control") for item in first)
    assert any(item.query_text == "mice exterminator Denver CO" for item in first)
    assert all(item.provenance_rule.startswith("taxonomy:") for item in first)
    assert all(item.generation_version for item in first)
    assert {item.query_id for item in first} != {
        item.query_id for item in generate_query_universe("pest control", "Boulder", "CO", limit=40)
    }


def test_unresolved_niche_cannot_generate_uncontrolled_queries() -> None:
    with pytest.raises(ValueError, match="controlled niche"):
        generate_query_universe("infinite futuristic business", "Denver", "CO")


def test_demo_multi_query_run_persists_distinct_probes_without_mutating_leads(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "market.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control", demo_mode=True)
    run_id = SearchMarketService(config, factory).run(criteria, "demo_001")
    with factory() as session:
        run = session.get(SearchMarketRun, run_id)
        assert run is not None and run.lifecycle_state == "Completed" and run.demo_mode
        queries = list(session.scalars(select(SearchMarketQuery).where(SearchMarketQuery.run_id == run_id)))
        probes = list(session.scalars(select(SearchVisibilityProbe).where(SearchVisibilityProbe.search_id == run.search_id)))
        assert len(queries) == len(probes) == 8
        assert len({probe.market_query_id for probe in probes}) == 8
        assert all(probe.source == "demo_fixture" and probe.collection_status == "demo" for probe in probes)
        assert session.scalar(select(func.count()).select_from(Lead)) == 0
    factory.kw["bind"].dispose()


def test_one_query_failure_and_one_truncated_window_do_not_corrupt_other_queries(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "partial.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control")
    calls = 0

    def capture(query, request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise GooglePlacesError("second query failed")
        acquisition = demo_visibility_acquisition(request, load_demo_businesses(request)[:2])
        return replace(
            acquisition, source="google_places_text_search", collection_status="complete",
            query_text=query.query_text, truncated=calls == 3,
        )

    run_id = SearchMarketService(config, factory).run(criteria, "demo_001", capture=capture)
    with factory() as session:
        run = session.get(SearchMarketRun, run_id)
        assert run is not None and run.lifecycle_state == "Partial"
        probes = list(session.scalars(
            select(SearchVisibilityProbe).where(SearchVisibilityProbe.search_id == run.search_id)
        ))
        assert len(probes) == 8
        assert sum(probe.collection_status == "failed" for probe in probes) == 1
        assert sum(probe.truncated for probe in probes) == 1
        assert sum(probe.collection_status == "complete" and not probe.truncated for probe in probes) == 6
        assert session.scalar(select(func.count()).select_from(Lead)) == 0
    factory.kw["bind"].dispose()


def test_coverage_denominator_clusters_and_top_three_use_only_eligible_query_evidence(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "coverage.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control")
    ordinal = 0

    def capture(query, request):
        nonlocal ordinal
        ordinal += 1
        if ordinal == 5:
            raise GooglePlacesError("query five unavailable")
        rows = []
        if ordinal in {1, 2}:
            rows.append(VisibilityObservationCapture(1, 1, 1, "target", "Target", retained_position=1))
        if ordinal == 7:
            rows.append(VisibilityObservationCapture(1, 1, 1, "target", "Target", disposition="outside_radius"))
        rows.append(VisibilityObservationCapture(len(rows) + 1, 1, len(rows) + 1, "comp-a", "ABC Pest", retained_position=1))
        if ordinal in {3, 4, 8}:
            rows.append(VisibilityObservationCapture(len(rows) + 1, 1, len(rows) + 1, "comp-b", "XYZ Pest", retained_position=2))
        if ordinal in {3, 4}:
            rows.append(VisibilityObservationCapture(len(rows) + 1, 1, len(rows) + 1, "comp-c", "Third Pest", retained_position=3))
        return SearchVisibilityAcquisition(
            source="google_places_text_search", query_text=query.query_text,
            resolved_latitude=39.7, resolved_longitude=-104.9,
            radius_meters=request.radius_meters, requested_result_limit=request.max_results,
            collection_status="complete", truncated=ordinal == 6, page_count=1,
            raw_result_count=len(rows),
            retained_result_count=sum(row.disposition == "accepted" for row in rows),
            selected_result_count=0, observed_at=utc_now(), profiles=(), observations=tuple(rows),
        )

    run_id = SearchMarketService(config, factory).run(criteria, "target", capture=capture)
    with factory() as session:
        result = project_search_market(session, run_id)
        assert result.evidence_mode == "live"
        assert (result.tracked_queries, result.observed_queries, result.unknown_queries) == (8, 6, 2)
        assert (result.present_queries, result.absent_queries, result.excluded_queries) == (2, 3, 1)
        assert result.coverage_denominator == 5
        assert result.coverage_percent == 40.0
        assert result.strongest_cluster == "Pest Control"
        assert result.weakest_cluster == "Rodent Control"
        assert [item.place_id for item in result.top_search_competitors] == ["comp-a", "comp-b", "comp-c"]
        assert result.top_search_competitors[0].gap_capture_queries == 3
        assert all("complete tracked queries" in item.why for item in result.top_search_competitors)
        assert any(gap.kind == "multi_competitor_query" for gap in result.gaps)
        assert any(gap.kind == "weak_cluster" for gap in result.gaps)
        assert any(gap.kind == "recurring_cluster_competitor" for gap in result.gaps)
        assert all("Google prefers" not in gap.interpretation for gap in result.gaps)
        assert any("truncated" in item.reason for item in result.queries if item.state == "unknown")
        assert all("Maps rank" not in item.reason for item in result.queries)
    factory.kw["bind"].dispose()


def test_freshness_demo_live_separation_and_retry_attempts_fail_closed(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "retry.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control", demo_mode=True)
    run_id = SearchMarketService(config, factory).run(criteria, "demo_001", query_limit=2)
    with factory() as session:
        run = session.get(SearchMarketRun, run_id)
        assert run is not None
        query = session.scalars(
            select(SearchMarketQuery).where(SearchMarketQuery.run_id == run_id).order_by(SearchMarketQuery.ordinal)
        ).first()
        assert query is not None
        original = session.scalars(select(SearchVisibilityProbe).where(SearchVisibilityProbe.market_query_id == query.id)).one()
        baseline = project_search_market(session, run_id)
        assert baseline.queries[0].state in {"present", "absent"}
        future = project_search_market(session, run_id, now=utc_now() + timedelta(days=31))
        assert future.queries[0].state == "unknown"
        assert "stale" in future.queries[0].reason
        query_id = query.id
        original_id = original.id
        search_id = run.search_id

        retry = replace(
            demo_visibility_acquisition(criteria, load_demo_businesses(criteria)[:1]),
            query_text=query.query_text, attempt_id=uuid4().hex,
            observed_at=utc_now() + timedelta(seconds=1),
        )
        persisted = persist_visibility_acquisition(
            session, search_id, criteria, retry, market_query_id=query_id
        )
        assert persisted.id != original_id
        session.commit()
        assert persist_visibility_acquisition(
            session, search_id, criteria, retry, market_query_id=query_id
        ).id == persisted.id
        session.commit()
        session.expire_all()
        assert project_search_market(session, run_id, now=utc_now() + timedelta(seconds=2)).queries[0].attempt_count == 2
        with pytest.raises(ValueError, match="different evidence"):
            persist_visibility_acquisition(
                session, search_id, criteria,
                replace(retry, collection_status="failed"), market_query_id=query_id,
            )
        altered_observation = replace(retry.observations[0], place_id="forged-place")
        with pytest.raises(ValueError, match="different evidence"):
            persist_visibility_acquisition(
                session, search_id, criteria,
                replace(retry, observations=(altered_observation,)), market_query_id=query_id,
            )
        with pytest.raises(ValueError, match="different evidence|resolved center"):
            persist_visibility_acquisition(
                session, search_id, criteria,
                replace(retry, resolved_latitude=1.0), market_query_id=query_id,
            )
        with pytest.raises(ValueError, match="Search Market"):
            persist_visibility_acquisition(
                session, search_id, criteria,
                replace(retry, attempt_id=uuid4().hex, resolved_latitude=40.0),
                market_query_id=query_id,
            )
        run.demo_mode = False
        session.commit()
        assert project_search_market(session, run_id).queries[0].state == "unknown"
        assert "frozen" in project_search_market(session, run_id).queries[0].reason
    factory.kw["bind"].dispose()


def test_market_probe_write_rejects_cross_run_query_link(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "cross-run.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control", demo_mode=True)
    service = SearchMarketService(config, factory)
    first_id = service.run(criteria, "demo_001", query_limit=1)
    second_id = service.run(criteria, "demo_001", query_limit=1)
    with factory() as session:
        first = session.get(SearchMarketRun, first_id)
        second = session.get(SearchMarketRun, second_id)
        first_query = session.scalars(select(SearchMarketQuery).where(SearchMarketQuery.run_id == first_id)).one()
        assert first is not None and second is not None
        attempt = replace(
            demo_visibility_acquisition(criteria, load_demo_businesses(criteria)[:1]),
            query_text=first_query.query_text,
        )
        with pytest.raises(ValueError, match="Search Market"):
            persist_visibility_acquisition(
                session, second.search_id, criteria, attempt, market_query_id=first_query.id
            )
        assert session.scalar(select(func.count()).select_from(SearchVisibilityProbe)) == 2
    factory.kw["bind"].dispose()


@pytest.mark.parametrize("change", [
    {"city": "Boulder"},
    {"radius_meters": 5000},
    {"niche": "roofing"},
])
def test_market_probe_write_rejects_wrong_frozen_context_even_with_exact_query(tmp_path, change) -> None:
    config = AppConfig(tmp_path, tmp_path / "wrong-context.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control", demo_mode=True)
    run_id = SearchMarketService(config, factory).run(criteria, "demo_001", query_limit=1)
    wrong = replace(criteria, **change)
    with factory() as session:
        run = session.get(SearchMarketRun, run_id)
        query = session.scalars(select(SearchMarketQuery).where(SearchMarketQuery.run_id == run_id)).one()
        assert run is not None
        attempt = replace(
            demo_visibility_acquisition(wrong, load_demo_businesses(wrong)[:1]),
            query_text=query.query_text,
        )
        with pytest.raises(ValueError, match="Search Market"):
            persist_visibility_acquisition(
                session, run.search_id, wrong, attempt, market_query_id=query.id
            )
        assert session.scalar(select(func.count()).select_from(SearchVisibilityProbe)) == 1
    factory.kw["bind"].dispose()


@pytest.mark.parametrize("field,value", [
    ("location_label", "Boulder, CO"),
    ("radius_meters", 5000),
    ("normalized_niche", "roofing"),
    ("resolved_latitude", 40.0),
])
def test_market_projection_rejects_corrupted_newer_probe_context(tmp_path, field, value) -> None:
    config = AppConfig(tmp_path, tmp_path / "tampered.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control", demo_mode=True)
    fixtures = load_demo_businesses(criteria)

    def capture(query, request):
        return replace(demo_visibility_acquisition(request, fixtures), query_text=query.query_text)

    run_id = SearchMarketService(config, factory).run(criteria, fixtures[0].place_id, query_limit=1, capture=capture)
    with factory() as session:
        run = session.get(SearchMarketRun, run_id)
        query = session.scalars(select(SearchMarketQuery).where(SearchMarketQuery.run_id == run_id)).one()
        assert run is not None
        assert project_search_market(session, run_id).queries[0].state == "present"
        retry = replace(
            demo_visibility_acquisition(criteria, []), query_text=query.query_text,
            observed_at=utc_now() + timedelta(seconds=1),
        )
        probe = persist_visibility_acquisition(
            session, run.search_id, criteria, retry, market_query_id=query.id
        )
        session.commit()
        session.expire_all()
        assert project_search_market(session, run_id, now=utc_now() + timedelta(seconds=2)).queries[0].state == "absent"
        setattr(probe, field, value)
        if field == "resolved_latitude":
            probe.comparability_fingerprint = visibility_context_fingerprint(criteria, probe)
            probe.context_fingerprint = hashlib.sha256(
                f"{probe.comparability_fingerprint}:{probe.attempt_id}".encode()
            ).hexdigest()
        session.commit()
        session.expire_all()
        result = project_search_market(session, run_id, now=utc_now() + timedelta(seconds=2))
        assert result.queries[0].attempt_count == 2
        assert result.queries[0].state == "unknown"
        assert "context" in result.queries[0].reason
        assert result.coverage_denominator == 0
    factory.kw["bind"].dispose()


def test_market_projection_rejects_cross_run_probe_even_with_matching_query_text(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "cross-run-read.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control", demo_mode=True)
    service = SearchMarketService(config, factory)
    first_id = service.run(criteria, "demo_001", query_limit=1)
    second_id = service.run(criteria, "demo_001", query_limit=1)
    with factory() as session:
        first_query = session.scalars(select(SearchMarketQuery).where(SearchMarketQuery.run_id == first_id)).one()
        second_query = session.scalars(select(SearchMarketQuery).where(SearchMarketQuery.run_id == second_id)).one()
        first_probe = session.scalars(
            select(SearchVisibilityProbe).where(SearchVisibilityProbe.market_query_id == first_query.id)
        ).one()
        second_probe = session.scalars(
            select(SearchVisibilityProbe).where(SearchVisibilityProbe.market_query_id == second_query.id)
        ).one()
        second_probe.market_query_id = first_query.id
        second_probe.observed_at = first_probe.observed_at + timedelta(seconds=1)
        session.commit()
        session.expire_all()
        result = project_search_market(session, first_id, now=utc_now() + timedelta(seconds=2))
        assert result.queries[0].attempt_count == 2
        assert result.queries[0].state == "unknown"
        assert "run" in result.queries[0].reason
    factory.kw["bind"].dispose()


def test_search_market_offscreen_ui_has_separate_summary_and_hierarchical_drilldown(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QTreeWidget

    from local_presence_miner.ui.widgets.search_market_widget import SearchMarketDetailDialog, SearchMarketWidget

    app = QApplication.instance() or QApplication([])
    config = AppConfig(tmp_path, tmp_path / "ui.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    run_id = SearchMarketService(config, factory).run(
        SearchCriteria("Denver", "CO", "pest control", demo_mode=True), "demo_001"
    )
    widget = SearchMarketWidget(factory)
    dialog = SearchMarketDetailDialog(factory, run_id)
    try:
        assert widget.table.rowCount() == 1
        assert widget.table.item(0, 2).text() == "Demo — not live"
        labels = " ".join(item.text() for item in dialog.findChildren(QLabel))
        assert "DEMO EVIDENCE" in labels
        assert "not exact Maps rank" in labels or "not live public evidence" in labels
        tree = dialog.findChild(QTreeWidget)
        assert tree is not None and tree.topLevelItemCount() >= 3
        first_cluster = tree.topLevelItem(0)
        assert first_cluster.childCount() >= 1
        assert first_cluster.child(0).childCount() == 1
        assert first_cluster.child(0).child(0).childCount() >= 1
    finally:
        dialog.close()
        widget.close()
        app.processEvents()
        factory.kw["bind"].dispose()


def test_search_market_migration_preserves_existing_visibility_without_inference(tmp_path) -> None:
    path = tmp_path / "prior-visibility.sqlite3"
    factory = create_session_factory(path)
    initialize_database(factory)
    criteria = SearchCriteria("Denver", "CO", "pest control", demo_mode=True)
    with factory() as session:
        parent = LeadSearch(name="Prior search", city="Denver", state_region="CO", niche="pest control", criteria_json="{}")
        session.add(parent)
        session.flush()
        probe = persist_visibility_acquisition(
            session, parent.id, criteria, demo_visibility_acquisition(criteria, load_demo_businesses(criteria)[:1])
        )
        probe_id = probe.id
        session.commit()
    factory.kw["bind"].dispose()

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DELETE FROM app_settings WHERE key='v0116_search_market_migrated'")
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='search_visibility_probes'"
        ).fetchone()[0]
        legacy_ddl = re.sub(r"\s*market_query_id INTEGER,", "", ddl)
        legacy_ddl = re.sub(
            r",\s*FOREIGN KEY\(market_query_id\) REFERENCES search_market_queries \(id\)",
            "", legacy_ddl,
        ).replace("CREATE TABLE search_visibility_probes", "CREATE TABLE search_visibility_probes_legacy")
        connection.execute(legacy_ddl)
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(search_visibility_probes)")
            if row[1] != "market_query_id"
        ]
        column_sql = ", ".join(f'"{name}"' for name in columns)
        connection.execute(
            f"INSERT INTO search_visibility_probes_legacy ({column_sql}) "
            f"SELECT {column_sql} FROM search_visibility_probes"
        )
        connection.execute("DROP TABLE search_visibility_probes")
        connection.execute("ALTER TABLE search_visibility_probes_legacy RENAME TO search_visibility_probes")
        connection.execute("DROP TABLE search_market_queries")
        connection.execute("DROP TABLE search_market_runs")
        connection.commit()

    factory = create_session_factory(path)
    initialize_database(factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0116-search-market")
    assert backup.exists()
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    with factory() as session:
        assert session.get(SearchVisibilityProbe, probe_id) is not None
        assert session.get(SearchVisibilityProbe, probe_id).market_query_id is None
        assert session.scalar(select(func.count()).select_from(SearchMarketRun)) == 0
        assert session.scalar(select(func.count()).select_from(SearchMarketQuery)) == 0
        assert session.get(AppSetting, "v0116_search_market_migrated") is not None
    initialize_database(factory)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    factory.kw["bind"].dispose()
