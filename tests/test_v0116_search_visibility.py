from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.schema import (
    AppSetting,
    LeadSearch,
    SearchRunLead,
    SearchVisibilityObservation,
    SearchVisibilityProbe,
)
from local_presence_miner.domain.models import BusinessProfile, SearchCriteria, WebsiteAudit
from local_presence_miner.domain.scoring import score_lead
from local_presence_miner.services.comparison_service import comparison_scores
from local_presence_miner.services.demo_data import load_demo_businesses
from local_presence_miner.services.google_places import GooglePlacesClient, GooglePlacesError
from local_presence_miner.services.search_visibility_service import (
    assess_absence_claim,
    demo_visibility_acquisition,
    persist_visibility_acquisition,
)
from local_presence_miner.services.search_workflow import SearchWorkflow


class Response:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def test_google_places_capture_preserves_raw_and_retained_positions(monkeypatch) -> None:
    def fake_post(_url, *, json, headers, timeout, allow_redirects):
        del headers, timeout, allow_redirects
        if json["textQuery"] == "48502, MI, United States":
            return Response(
                {
                    "places": [
                        {
                            "id": "center",
                            "displayName": {"text": "Flint"},
                            "types": ["postal_code"],
                            "addressComponents": [
                                {"longText": "48502", "shortText": "48502", "types": ["postal_code"]},
                                {"longText": "Michigan", "shortText": "MI", "types": ["administrative_area_level_1", "political"]},
                                {"longText": "United States", "shortText": "US", "types": ["country", "political"]},
                            ],
                            "formattedAddress": "Flint, MI 48502",
                            "location": {"latitude": 43.0125, "longitude": -83.6875},
                        }
                    ]
                }
            )
        return Response(
            {
                "places": [
                    {
                        "id": "accepted-one",
                        "displayName": {"text": "Accepted One"},
                        "location": {"latitude": 43.0125, "longitude": -83.6875},
                    },
                    {"id": "missing-location", "displayName": {"text": "Missing Location"}},
                    {
                        "id": "outside-radius",
                        "displayName": {"text": "Outside Radius"},
                        "location": {"latitude": 44.0125, "longitude": -83.6875},
                    },
                    {
                        "id": "accepted-one",
                        "displayName": {"text": "Duplicate"},
                        "location": {"latitude": 43.0125, "longitude": -83.6875},
                    },
                    {
                        "id": "accepted-two",
                        "displayName": {"text": "Accepted Two"},
                        "location": {"latitude": 43.0135, "longitude": -83.6875},
                    },
                ]
            }
        )

    def fake_get(url, *, headers, timeout, allow_redirects):
        del headers, timeout, allow_redirects
        place_id = url.rsplit("/", 1)[-1]
        return Response({"id": place_id, "displayName": {"text": place_id}, "websiteUri": "https://example.test"})

    monkeypatch.setattr("local_presence_miner.services.google_places.requests.post", fake_post)
    monkeypatch.setattr("local_presence_miner.services.google_places.requests.get", fake_get)

    acquisition = GooglePlacesClient("test-key").search_with_visibility(
        SearchCriteria(
            "Flint",
            "MI",
            "roofers",
            target_zip_code="48502",
            target_radius_miles=10,
            radius_meters=16_093,
            max_results=5,
        )
    )

    assert [item.source_position for item in acquisition.observations] == [1, 2, 3, 4, 5]
    assert [item.disposition for item in acquisition.observations] == [
        "accepted",
        "missing_coordinates",
        "outside_radius",
        "duplicate",
        "accepted",
    ]
    assert [item.retained_position for item in acquisition.observations] == [1, None, None, None, 2]
    assert [profile.search_position for profile in acquisition.profiles] == [1, 2]
    assert acquisition.raw_result_count == 5
    assert acquisition.retained_result_count == 2
    assert acquisition.selected_result_count == 2
    assert acquisition.collection_status == "complete"
    assert acquisition.truncated is False


def test_google_places_preserves_partial_observations_when_later_page_fails(monkeypatch) -> None:
    calls = 0

    def fake_post(_client, payload, _headers):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response(
                {
                    "places": [
                        {
                            "id": "center",
                            "displayName": {"text": "Flint"},
                            "types": ["postal_code"],
                            "addressComponents": [
                                {"longText": "48502", "shortText": "48502", "types": ["postal_code"]},
                                {"longText": "Michigan", "shortText": "MI", "types": ["administrative_area_level_1", "political"]},
                                {"longText": "United States", "shortText": "US", "types": ["country", "political"]},
                            ],
                            "formattedAddress": "Flint, MI 48502",
                            "location": {"latitude": 43.0125, "longitude": -83.6875},
                        }
                    ]
                }
            )
        if calls == 2:
            assert "pageToken" not in payload
            return Response(
                {
                    "places": [
                        {
                            "id": "first-page",
                            "displayName": {"text": "First Page"},
                            "location": {"latitude": 43.0125, "longitude": -83.6875},
                        }
                    ],
                    "nextPageToken": "next",
                }
            )
        raise GooglePlacesError("second page unavailable")

    monkeypatch.setattr(GooglePlacesClient, "_post_with_retry", fake_post)
    monkeypatch.setattr("local_presence_miner.services.google_places.time.sleep", lambda _seconds: None)

    with pytest.raises(GooglePlacesError, match="second page unavailable") as stopped:
        GooglePlacesClient("test-key").search_with_visibility(
            SearchCriteria("Flint", "MI", "roofers", target_zip_code="48502", max_results=20)
        )

    acquisition = stopped.value.acquisition
    assert acquisition is not None
    assert acquisition.collection_status == "partial"
    assert acquisition.page_count == 1
    assert acquisition.raw_result_count == 1
    assert acquisition.retained_result_count == 1
    assert acquisition.observations[0].place_id == "first-page"
    assert acquisition.profiles == ()


def test_demo_workflow_persists_tagged_visibility_without_changing_memberships(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "visibility.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)

    criteria = SearchCriteria("Peoria", "IL", "roofers", demo_mode=True, top_mockups=0)
    search_id = SearchWorkflow(config, factory).run(criteria)

    with factory() as session:
        probe = session.scalars(
            select(SearchVisibilityProbe).where(SearchVisibilityProbe.search_id == search_id)
        ).one()
        observations = list(
            session.scalars(
                select(SearchVisibilityObservation)
                .where(SearchVisibilityObservation.probe_id == probe.id)
                .order_by(SearchVisibilityObservation.source_position)
            )
        )
        memberships = list(
            session.scalars(select(SearchRunLead).where(SearchRunLead.search_id == search_id))
        )
        assert probe.source == "demo_fixture"
        assert probe.collection_status == "demo"
        assert probe.raw_result_count == len(observations) == len(memberships)
        assert all(item.disposition == "accepted" for item in observations)
        assert all(item.lead_id is not None for item in observations)
        assert all(item.search_run_lead_id is not None for item in observations)
        retry = demo_visibility_acquisition(criteria, load_demo_businesses(criteria))
        persisted_again = persist_visibility_acquisition(
            session,
            search_id,
            criteria,
            retry,
        )
        same_attempt = persist_visibility_acquisition(session, search_id, criteria, retry)
        session.commit()
        assert persisted_again.id != probe.id
        assert same_attempt.id == persisted_again.id
        assert persisted_again.comparability_fingerprint == probe.comparability_fingerprint
        assert session.scalar(select(func.count()).select_from(SearchVisibilityProbe)) == 2
        assert session.scalar(select(func.count()).select_from(SearchVisibilityObservation)) == 2 * len(observations)
    factory.kw["bind"].dispose()


def test_retry_attempts_preserve_context_and_absence_claim_requires_complete_live_evidence(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "retries.sqlite3")
    initialize_database(factory)
    criteria = SearchCriteria("Peoria", "IL", "roofers", demo_mode=False)
    original = demo_visibility_acquisition(criteria, load_demo_businesses(criteria)[:1])
    live = replace(original, source="google_places_text_search", collection_status="complete")
    partial = replace(
        live, attempt_id="partial-retry", collection_status="partial", error_summary="page unavailable"
    )
    absent = replace(
        live, attempt_id="completed-retry", observed_at=live.observed_at + timedelta(seconds=1),
        observations=(), profiles=(), raw_result_count=0,
        retained_result_count=0, selected_result_count=0,
    )
    with factory() as session:
        search = LeadSearch(name="Retry", city="Peoria", state_region="IL", niche="roofers", criteria_json="{}")
        session.add(search)
        session.flush()
        earlier = persist_visibility_acquisition(session, search.id, criteria, live)
        search_id = search.id
        earlier_id = earlier.id
        interrupted = persist_visibility_acquisition(session, search.id, criteria, partial)
        later = persist_visibility_acquisition(session, search.id, criteria, absent)
        session.flush()
        place_id = original.observations[0].place_id
        claim_time = absent.observed_at + timedelta(seconds=1)
        assert len({earlier.id, interrupted.id, later.id}) == 3
        assert len({earlier.comparability_fingerprint, interrupted.comparability_fingerprint, later.comparability_fingerprint}) == 1
        assert "not_complete_live_evidence" in assess_absence_claim(earlier, interrupted, place_id, now=claim_time).reasons
        assert assess_absence_claim(earlier, later, place_id, now=claim_time).allowed
        assert not assess_absence_claim(earlier, later, "not-in-first", now=claim_time).allowed
        later.truncated = True
        assert "truncated_collection" in assess_absence_claim(earlier, later, place_id, now=claim_time).reasons
        later.truncated = False
        later.collection_status = "demo"
        assert "not_complete_live_evidence" in assess_absence_claim(earlier, later, place_id, now=claim_time).reasons
        later.collection_status = "complete"
        later.comparability_fingerprint = "different-context"
        assert "incomparable_context" in assess_absence_claim(earlier, later, place_id, now=claim_time).reasons
        later.comparability_fingerprint = earlier.comparability_fingerprint
        assert "stale_or_future_evidence" in assess_absence_claim(
            earlier, later, place_id, now=claim_time + timedelta(days=31)
        ).reasons
        with pytest.raises(ValueError, match="cannot be reused"):
            persist_visibility_acquisition(session, search.id, criteria, replace(live, collection_status="partial"))
        session.commit()
    with factory() as session:
        assert persist_visibility_acquisition(session, search_id, criteria, live).id == earlier_id
    factory.kw["bind"].dispose()


def test_visibility_ui_exposes_demo_provenance_and_proxy_warning(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
    from local_presence_miner.ui.widgets.run_history_widget import RunHistoryWidget

    app = QApplication.instance() or QApplication([])
    config = AppConfig(tmp_path, tmp_path / "ui.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    SearchWorkflow(config, factory).run(
        SearchCriteria("Peoria", "IL", "roofers", demo_mode=True, top_mockups=0)
    )

    history = RunHistoryWidget(factory)
    assert history.table.columnCount() == 17
    assert history.table.item(0, 12).text() == "Demo fixture"
    assert history.table.item(0, 16).text() == "Demo — not live evidence"

    with factory() as session:
        lead_id = session.scalar(select(SearchVisibilityObservation.lead_id).where(SearchVisibilityObservation.lead_id.is_not(None)))
    assert lead_id is not None
    detail = LeadDetailDialog(config, factory, lead_id)
    try:
        titles = [detail.tabs.tabText(index) for index in range(detail.tabs.count())]
        assert "Search Visibility" in titles
        visibility_tab = detail.tabs.widget(titles.index("Search Visibility"))
        labels = " ".join(label.text() for label in visibility_tab.findChildren(QLabel))
        assert "not exact Google Maps or Map Pack rankings" in labels
    finally:
        detail.close()
        history.close()
        app.processEvents()
        factory.kw["bind"].dispose()


def test_failed_live_collection_is_persisted_as_unknown_evidence(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        tmp_path,
        tmp_path / "failed.sqlite3",
        tmp_path / "app.log",
        tmp_path,
        google_maps_api_key="test-key",
    )
    factory = create_session_factory(config.database_path)
    initialize_database(factory)

    def fail(_client, _criteria):
        raise GooglePlacesError("controlled discovery failure")

    monkeypatch.setattr(GooglePlacesClient, "search_with_visibility", fail)
    with pytest.raises(GooglePlacesError, match="controlled discovery failure"):
        SearchWorkflow(config, factory).run(
            SearchCriteria("Peoria", "IL", "roofers", demo_mode=False, top_mockups=0)
        )

    with factory() as session:
        search = session.scalars(select(LeadSearch)).one()
        probe = session.scalars(select(SearchVisibilityProbe)).one()
        assert search.lifecycle_state == "Failed"
        assert probe.collection_status == "failed"
        assert probe.error_summary == "controlled discovery failure"
        assert probe.raw_result_count == 0
        assert session.scalar(select(func.count()).select_from(SearchVisibilityObservation)) == 0
    factory.kw["bind"].dispose()


def test_unimplemented_search_toggles_are_visibly_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from local_presence_miner.ui.dialogs.new_search_dialog import NewSearchDialog

    app = QApplication.instance() or QApplication([])
    config = AppConfig(tmp_path, tmp_path / "toggles.sqlite3", tmp_path / "app.log", tmp_path)
    dialog = NewSearchDialog(config)
    try:
        controls = (dialog.include_no_website, dialog.include_weak_website, dialog.include_low_rank, dialog.include_review_growth)
        assert all(not control.isEnabled() for control in controls)
        assert all(not control.isChecked() for control in controls)
        assert all("not applied" in control.toolTip() for control in controls)
    finally:
        dialog.close()
        app.processEvents()


def test_unattempted_website_audit_has_unknown_comparison_scores() -> None:
    assert all(value is None for value in comparison_scores("https://example.test", WebsiteAudit()).values())


def test_unattempted_website_audit_does_not_create_negative_site_claims() -> None:
    profile = BusinessProfile(
        place_id="unknown-site", name="Unknown Site", category="roofers", website="https://example.test",
        raw={"_details_retrieved": True},
    )
    scored = score_lead(profile, WebsiteAudit())
    forbidden = {"weak_website", "unreachable_website", "no_https", "no_contact_form", "missing_service_pages"}
    assert not forbidden.intersection(factor.key for factor in scored.factors)
    assert scored.recommended_offer == "Research-first"
    assert "Audit the linked website" in scored.approach_angle


def test_v0116_migration_is_additive_idempotent_and_does_not_infer_legacy_visibility(tmp_path) -> None:
    path = tmp_path / "legacy-b2.sqlite3"
    factory = create_session_factory(path)
    initialize_database(factory)
    with factory() as session:
        search = LeadSearch(name="Legacy", city="Peoria", state_region="IL", niche="roofers", criteria_json="{}")
        session.add(search)
        session.flush()
        session.add(
            SearchRunLead(
                search_id=search.id,
                candidate_place_id="legacy-place",
                candidate_name="Legacy Place",
                discovery_order=1,
                search_position=17,
                discovery_kind="legacy_unknown",
            )
        )
        session.commit()
    factory.kw["bind"].dispose()

    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM app_settings WHERE key='v0116_search_visibility_migrated'")
        connection.execute("DROP TABLE search_visibility_observations")
        connection.execute("DROP TABLE search_visibility_probes")
        connection.commit()

    factory = create_session_factory(path)
    initialize_database(factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0116")
    assert backup.exists()
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    with factory() as session:
        marker = session.get(AppSetting, "v0116_search_visibility_migrated")
        assert marker is not None
        payload = json.loads(marker.value)
        assert payload["legacy_visibility_observations_inferred"] == 0
        assert session.scalar(select(func.count()).select_from(SearchVisibilityProbe)) == 0
        assert session.scalar(select(func.count()).select_from(SearchVisibilityObservation)) == 0
        assert session.scalar(select(func.count()).select_from(SearchRunLead)) == 1

    initialize_database(factory)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash
    assert not path.with_suffix(path.suffix + ".backup-before-v0116.1").exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    factory.kw["bind"].dispose()


def test_existing_visibility_probe_schema_gains_attempt_columns_without_rewriting_rows(tmp_path) -> None:
    path = tmp_path / "existing-visibility.sqlite3"
    factory = create_session_factory(path)
    initialize_database(factory)
    criteria = SearchCriteria("Peoria", "IL", "roofers", demo_mode=True)
    with factory() as session:
        search = LeadSearch(name="Existing", city="Peoria", state_region="IL", niche="roofers", criteria_json="{}")
        session.add(search)
        session.flush()
        probe = persist_visibility_acquisition(
            session, search.id, criteria, demo_visibility_acquisition(criteria, load_demo_businesses(criteria)[:1])
        )
        prior_id = probe.id
        prior_fingerprint = probe.context_fingerprint
        session.commit()
    factory.kw["bind"].dispose()
    with sqlite3.connect(path) as connection:
        for column in ("comparability_fingerprint", "attempt_id", "acquisition_strategy_version"):
            connection.execute(f"ALTER TABLE search_visibility_probes DROP COLUMN {column}")
        connection.commit()
    factory = create_session_factory(path)
    initialize_database(factory)
    initialize_database(factory)
    with factory() as session:
        restored = session.get(SearchVisibilityProbe, prior_id)
        assert restored is not None
        assert restored.context_fingerprint == prior_fingerprint
        assert restored.comparability_fingerprint == ""
        assert restored.attempt_id == ""
        assert restored.acquisition_strategy_version == "legacy-v1"
        assert len(restored.observations) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    factory.kw["bind"].dispose()



def test_owner_facing_angle_describes_only_the_collected_batch() -> None:
    profile = BusinessProfile(
        place_id="positioned",
        name="Positioned Roofing",
        category="roofers",
        phone="555-0100",
        website="https://example.test",
        review_count=50,
        photo_count=20,
        has_hours=True,
        search_position=18,
    )
    score = score_lead(profile, WebsiteAudit(reachable=True, checks={"tap_to_call": True, "contact_form": True}))
    # Candidate order is collection bookkeeping, not an owner-facing sales case.
    assert "position 18" not in score.approach_angle
    assert "do not infer a paid opportunity" in score.approach_angle
    assert "low local visibility" not in score.approach_angle.lower()
