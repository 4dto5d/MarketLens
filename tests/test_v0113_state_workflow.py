from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest
import requests
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from local_presence_miner.config import AppConfig, SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    lead_contact_readiness_errors,
    outreach_approval_errors,
    save_outreach_draft,
    update_lead_fields,
    upsert_lead_with_outcome,
)
from local_presence_miner.database.schema import (
    Lead,
    LeadSearch,
    OutreachApprovalHistory,
    OutreachDraft,
    SearchRunLead,
    SearchRunLease,
)
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown, SearchCriteria
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.outreach_batch_service import OutreachBatchService
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.services.report_service import lead_artifact_slug
from local_presence_miner.services.search_workflow import SearchAlreadyRunningError, SearchWorkflow

PYTHON_SENDER = SenderInfo(
    name="Fixture Operator",
    business_name="Fixture Studio",
    reply_email="operator@example.com",
    phone="555-010-9999",
    postal_address="123 Fixture Street, Test City",
    opt_out_line="Reply opt out to stop contact.",
)


def app_config(tmp_path, name: str = "state.sqlite3") -> AppConfig:
    return AppConfig(tmp_path, tmp_path / name, tmp_path / "fixture.log", tmp_path, sender=PYTHON_SENDER)


def run_demo(config: AppConfig, factory) -> int:
    return SearchWorkflow(config, factory).run(
        SearchCriteria("Peoria", "IL", "roofers", demo_mode=True, top_mockups=0)
    )


@pytest.mark.parametrize(
    "preserved_status",
    ["Qualified", "Contacted", "Replied", "Meeting Scheduled", "Won", "Lost", "Do Not Contact"],
)
def test_rediscovery_preserves_crm_state_and_operator_notes(tmp_path, preserved_status):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    first_search = run_demo(config, factory)
    with factory() as session:
        lead = session.scalars(select(Lead).order_by(Lead.id)).first()
        lead_id = lead.id
        lead.status = preserved_status
        lead.operator_notes = "Operator-authored note that must survive rediscovery."
        if preserved_status == "Do Not Contact":
            lead.suppressed = True
        original_legacy_search = lead.search_id
        session.commit()

    second_search = run_demo(config, factory)
    with factory() as session:
        lead = session.get(Lead, lead_id)
        memberships = list(session.scalars(
            select(SearchRunLead).where(SearchRunLead.lead_id == lead_id).order_by(SearchRunLead.search_id)
        ))
        assert first_search != second_search
        assert [item.search_id for item in memberships] == [first_search, second_search]
        assert memberships[0].discovery_kind == "new"
        assert memberships[1].discovery_kind == "rediscovered"
        assert lead.status == preserved_status
        assert lead.operator_notes == "Operator-authored note that must survive rediscovery."
        assert lead.system_notes
        assert lead.search_id == original_legacy_search
    factory.kw["bind"].dispose()


def test_single_flight_blocks_second_service_run_for_same_database(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    entered = Event()
    release = Event()

    def blocked_run(self, criteria):
        entered.set()
        assert release.wait(5)
        return 77

    monkeypatch.setattr(SearchWorkflow, "_run_single", blocked_run)
    criteria = SearchCriteria("Peoria", "IL", "roofers", demo_mode=True)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(SearchWorkflow(config, factory).run, criteria)
        assert entered.wait(5)
        assert SearchWorkflow.is_running(factory)
        with pytest.raises(SearchAlreadyRunningError):
            SearchWorkflow(config, factory).run(criteria)
        release.set()
        assert first.result(timeout=5) == 77
    assert not SearchWorkflow.is_running(factory)
    with factory() as session:
        assert list(session.scalars(select(LeadSearch))) == []
    factory.kw["bind"].dispose()


def test_single_flight_blocks_a_separate_process_and_preserves_its_running_state(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    ready = tmp_path / "child-ready.txt"
    release = tmp_path / "release-child.txt"
    finished = tmp_path / "child-finished.txt"
    helper = tmp_path / "cross_process_search.py"
    helper.write_text(
        """
import sys
import time
import traceback
from pathlib import Path

project_root = Path(sys.argv[1])
sys.path.insert(0, str(project_root))

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import create_search, finish_search
from local_presence_miner.domain.models import SearchCriteria
from local_presence_miner.services.search_workflow import SearchWorkflow

database = Path(sys.argv[2])
ready = Path(sys.argv[3])
release = Path(sys.argv[4])
finished = Path(sys.argv[5])
config = AppConfig(database.parent, database, database.parent / "child.log", database.parent)
factory = create_session_factory(database)
initialize_database(factory)
criteria = SearchCriteria("Peoria", "IL", "roofers", demo_mode=True, top_mockups=0)
workflow = SearchWorkflow(config, factory)

def hold_run(criteria):
    with factory() as session:
        search = create_search(session, criteria)
        workflow._require_search_lease().bind_search(session, search.id)
        session.commit()
        search_id = search.id
    ready.write_text(str(search_id), encoding="utf-8")
    deadline = time.monotonic() + 15
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not release.exists():
        raise TimeoutError("Parent did not release child search")
    with factory() as session:
        finish_search(session, search_id, "Completed")
        session.commit()
    return search_id

workflow._run_single = hold_run
try:
    result = workflow.run(criteria)
    finished.write_text(f"completed:{result}", encoding="utf-8")
except Exception:
    finished.write_text(traceback.format_exc(), encoding="utf-8")
    raise
finally:
    factory.kw["bind"].dispose()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(project_root), environment.get("PYTHONPATH", "")) if value
    )
    child = subprocess.Popen(
        [
            sys.executable,
            str(helper),
            str(project_root),
            str(config.database_path),
            str(ready),
            str(release),
            str(finished),
        ],
        cwd=project_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), child.communicate(timeout=2)

        # Simulate startup of a second application instance. It must neither
        # steal the lock nor misclassify the active child's run as interrupted.
        initialize_database(factory)
        search_id = int(ready.read_text(encoding="utf-8"))
        with factory() as session:
            assert session.get(LeadSearch, search_id).lifecycle_state == "Running"
        assert SearchWorkflow.is_running(factory)
        monkeypatch.setattr(SearchWorkflow, "_run_single", lambda *_: 999)
        with pytest.raises(SearchAlreadyRunningError):
            SearchWorkflow(config, factory).run(
                SearchCriteria("Peoria", "IL", "dentists", demo_mode=True, top_mockups=0)
            )
    finally:
        release.touch()
        stdout, stderr = child.communicate(timeout=10)
        if child.returncode != 0:
            pytest.fail(f"Child failed ({child.returncode}). stdout={stdout!r} stderr={stderr!r}")
    assert finished.read_text(encoding="utf-8").startswith("completed:")
    with factory() as session:
        assert session.get(LeadSearch, int(ready.read_text(encoding="utf-8"))).lifecycle_state == "Completed"
        assert session.get(SearchRunLease, "search-workflow") is None
    factory.kw["bind"].dispose()


def test_abrupt_process_death_releases_lock_and_startup_recovers_run(tmp_path):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    ready = tmp_path / "crash-child-ready.txt"
    helper = tmp_path / "crashing_search.py"
    helper.write_text(
        """
import sys
import time
from pathlib import Path

project_root = Path(sys.argv[1])
sys.path.insert(0, str(project_root))

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import create_search
from local_presence_miner.database.schema import SearchRunLead
from local_presence_miner.domain.models import SearchCriteria
from local_presence_miner.services.search_workflow import SearchWorkflow

database = Path(sys.argv[2])
ready = Path(sys.argv[3])
config = AppConfig(database.parent, database, database.parent / "crash-child.log", database.parent)
factory = create_session_factory(database)
initialize_database(factory)
criteria = SearchCriteria("Peoria", "IL", "roofers", demo_mode=True, top_mockups=0)
workflow = SearchWorkflow(config, factory, lease_seconds=2)

def hold_until_killed(criteria):
    with factory() as session:
        search = create_search(session, criteria)
        session.flush()
        workflow._require_search_lease().bind_search(session, search.id)
        session.add(
            SearchRunLead(
                search_id=search.id,
                candidate_place_id="checkpointed-before-crash",
                candidate_name="Checkpointed Lead",
                discovery_order=1,
                processing_status="Succeeded",
                discovery_kind="new",
            )
        )
        session.commit()
        search_id = search.id
    ready.write_text(str(search_id), encoding="utf-8")
    while True:
        time.sleep(1)

workflow._run_single = hold_until_killed
workflow.run(criteria)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(project_root), environment.get("PYTHONPATH", "")) if value
    )
    child = subprocess.Popen(
        [
            sys.executable,
            str(helper),
            str(project_root),
            str(config.database_path),
            str(ready),
        ],
        cwd=project_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), child.communicate(timeout=2)
        assert SearchWorkflow.is_running(factory)
        search_id = int(ready.read_text(encoding="utf-8"))
        # A lease longer than its configured TTL proves the child heartbeat is
        # renewing it rather than relying only on the initial acquisition.
        time.sleep(2.5)
        assert SearchWorkflow.is_running(factory)
        child.terminate()
        child.communicate(timeout=10)
        with factory() as session:
            stale_lease = session.get(SearchRunLease, "search-workflow")
            assert stale_lease is not None and stale_lease.search_id == search_id
            assert stale_lease.heartbeat_at_epoch > stale_lease.acquired_at_epoch
        deadline = time.monotonic() + 5
        while SearchWorkflow.is_running(factory) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not SearchWorkflow.is_running(factory)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

    initialize_database(factory)
    with factory() as session:
        recovered = session.get(LeadSearch, search_id)
        assert recovered.lifecycle_state == "Interrupted / Partial"
        assert recovered.completed
        assert recovered.completed_at is not None
        assert recovered.succeeded_count == 1
        assert "no active database search lease" in recovered.error_summary
    factory.kw["bind"].dispose()


def test_concurrent_unique_place_upsert_is_conflict_safe(tmp_path):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    barrier = Barrier(2)
    profile = BusinessProfile(place_id="race-place", name="Race Roofing", category="roofers")
    score = ScoreBreakdown(70, "B", [], "Starter", "Evidence first", [])

    def worker():
        with factory() as session:
            barrier.wait(timeout=5)
            outcome = upsert_lead_with_outcome(session, profile, None, score)
            session.commit()
            return outcome.is_new, outcome.lead.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result(timeout=10) for future in [executor.submit(worker), executor.submit(worker)]]
    assert sorted(is_new for is_new, _lead_id in outcomes) == [False, True]
    assert len({lead_id for _is_new, lead_id in outcomes}) == 1
    with factory() as session:
        assert len(list(session.scalars(select(Lead).where(Lead.place_id == "race-place")))) == 1
    factory.kw["bind"].dispose()


def test_candidate_failure_continues_and_records_honest_counters(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    original = QualificationService.evaluate_and_store
    calls = 0

    def fail_second(self, session, lead):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("controlled candidate failure")
        return original(self, session, lead)

    monkeypatch.setattr(QualificationService, "evaluate_and_store", fail_second)
    search_id = run_demo(config, factory)
    with factory() as session:
        search = session.get(LeadSearch, search_id)
        memberships = list(session.scalars(select(SearchRunLead).where(SearchRunLead.search_id == search_id)))
        assert search.lifecycle_state == "Completed With Errors"
        assert search.total_candidates == len(memberships)
        assert search.processed_count == len(memberships)
        assert search.failed_count == 1
        assert search.succeeded_count == len(memberships) - 1
        assert len(list(session.scalars(select(Lead)))) == search.succeeded_count
        assert any(item.processing_status == "Failed" and "controlled" in item.error_summary for item in memberships)
    factory.kw["bind"].dispose()


def test_missing_candidate_place_id_is_failed_locally_and_later_candidate_continues(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    profiles = [
        BusinessProfile(place_id="", name="Malformed candidate", category="roofers"),
        BusinessProfile(
            place_id="good-1",
            name="Good Roofing",
            category="roofers",
            phone="555-010-4040",
            business_status="OPERATIONAL",
        ),
    ]
    monkeypatch.setattr(
        "local_presence_miner.services.search_workflow.load_demo_businesses",
        lambda _criteria: profiles,
    )

    search_id = run_demo(config, factory)
    with factory() as session:
        search = session.get(LeadSearch, search_id)
        memberships = list(
            session.scalars(
                select(SearchRunLead)
                .where(SearchRunLead.search_id == search_id)
                .order_by(SearchRunLead.discovery_order)
            )
        )
        leads = list(session.scalars(select(Lead)))
        assert search.lifecycle_state == "Completed With Errors"
        assert search.total_candidates == 2
        assert search.processed_count == 2
        assert search.failed_count == 1
        assert search.succeeded_count == 1
        assert memberships[0].candidate_place_id == "missing-place-id:1"
        assert memberships[0].processing_status == "Failed"
        assert "Missing canonical Google Place ID" in memberships[0].error_summary
        assert memberships[1].candidate_place_id == "good-1"
        assert memberships[1].processing_status == "Succeeded"
        assert [(lead.place_id, lead.name) for lead in leads] == [("good-1", "Good Roofing")]
    factory.kw["bind"].dispose()


def test_systemic_database_failure_stops_run_and_marks_partial(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    original = QualificationService.evaluate_and_store
    calls = 0

    def fail_second(self, session, lead):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OperationalError("UPDATE leads", {}, sqlite3.OperationalError("database unavailable"))
        return original(self, session, lead)

    monkeypatch.setattr(QualificationService, "evaluate_and_store", fail_second)
    with pytest.raises(OperationalError):
        run_demo(config, factory)
    with factory() as session:
        search = session.scalars(select(LeadSearch).order_by(LeadSearch.id.desc())).one()
        assert search.lifecycle_state == "Partial"
        assert search.succeeded_count == 1
        assert search.failed_count == 0
        assert search.processed_count == 1
        assert "database unavailable" in search.error_summary
    factory.kw["bind"].dispose()


@pytest.mark.parametrize(
    ("processing_status", "expected_state"),
    [("Succeeded", "Interrupted / Partial"), ("Pending", "Interrupted / Failed")],
)
def test_startup_reconciles_orphaned_running_search(tmp_path, processing_status, expected_state):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        search = LeadSearch(
            name="Interrupted fixture",
            city="Peoria",
            state_region="IL",
            niche="roofers",
            criteria_json="{}",
            lifecycle_state="Running",
        )
        session.add(search)
        session.flush()
        session.add(
            SearchRunLead(
                search_id=search.id,
                candidate_place_id="crash-candidate",
                candidate_name="Crash Candidate",
                discovery_order=1,
                processing_status=processing_status,
                discovery_kind="new" if processing_status == "Succeeded" else "pending",
            )
        )
        session.commit()
        search_id = search.id
    factory.kw["bind"].dispose()

    reopened = create_session_factory(config.database_path)
    initialize_database(reopened)
    with reopened() as session:
        recovered = session.get(LeadSearch, search_id)
        assert recovered.lifecycle_state == expected_state
        assert recovered.completed
        assert recovered.completed_at is not None
        assert recovered.processed_count == int(processing_status == "Succeeded")
        assert recovered.succeeded_count == int(processing_status == "Succeeded")
        assert "interrupted" in recovered.error_summary.lower()
        membership = session.scalars(
            select(SearchRunLead).where(SearchRunLead.search_id == search_id)
        ).one()
        assert membership.processing_status == processing_status
    reopened.kw["bind"].dispose()


def test_current_viability_revokes_exact_approval_and_never_reapproves(tmp_path):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="viability-fixture",
            name="Viability Roofing",
            phone="555-010-2000",
            qualification_class="Promote",
            qualification_json='{"classification": "Promote"}',
            recommended_offer="Conversion Tune-Up",
            recommended_offer_id="conversion_tune_up",
            offer_resolution_state="canonical_id",
            status="Approved to Contact",
        )
        session.add(lead)
        session.flush()
        draft = OutreachDraft(
            lead_id=lead.id,
            kind="Cold Email",
            subject="Exact approved subject",
            body="Exact approved body",
            approved=True,
            dependency_state="generated",
        )
        session.add(draft)
        session.commit()
        lead_id = lead.id
        draft_id = draft.id

    with factory() as session:
        update_lead_fields(session, lead_id, business_status="CLOSED_PERMANENTLY")
        session.commit()
        lead = session.get(Lead, lead_id)
        draft = session.get(OutreachDraft, draft_id)
        history = session.scalars(select(OutreachApprovalHistory).where(
            OutreachApprovalHistory.outreach_draft_id == draft_id
        )).one()
        assert not draft.approved
        assert draft.body == history.body == "Exact approved body"
        assert lead.status == "Needs Review"
        assert "permanently closed" in " ".join(lead_contact_readiness_errors(session, lead)).lower()
        assert any("permanently closed" in error.lower() for error in outreach_approval_errors(session, draft, PYTHON_SENDER))
        batch = OutreachBatchService(PYTHON_SENDER).export_ready_csv(session, tmp_path / "batch")
        assert batch.exported == 0 and batch.skipped == 1
        assert "permanently closed" in batch.review_path.read_text(encoding="utf-8").lower()

        update_lead_fields(session, lead_id, business_status="OPERATIONAL")
        session.commit()
        assert not session.get(OutreachDraft, draft_id).approved
    factory.kw["bind"].dispose()


def test_qualification_reject_preserves_revoked_copy_during_asset_refresh(tmp_path):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="reject-fixture",
            name="Reject Roofing",
            phone="555-010-2001",
            qualification_class="Promote",
            qualification_json='{"classification": "Promote"}',
            status="Approved to Contact",
        )
        session.add(lead)
        session.flush()
        draft = OutreachDraft(
            lead_id=lead.id,
            kind=OutreachKind.INITIAL_EMAIL.value,
            subject="Exact approved subject",
            body="Exact approved body",
            approved=True,
            dependency_state="generated",
        )
        session.add(draft)
        session.commit()
        lead_id = lead.id
        draft_id = draft.id

    with factory() as session:
        update_lead_fields(
            session,
            lead_id,
            qualification_class="Reject",
            qualification_json='{"classification": "Reject"}',
        )
        session.commit()
        draft = session.get(OutreachDraft, draft_id)
        assert not draft.approved
        assert draft.body == "Exact approved body"
        assert "Qualification is Reject" in " ".join(
            lead_contact_readiness_errors(session, session.get(Lead, lead_id))
        )

        refreshed = save_outreach_draft(
            session,
            lead_id,
            OutreachKind.INITIAL_EMAIL,
            "Replacement subject",
            "Replacement body",
            proof_dependencies=[],
        )
        session.commit()
        assert refreshed.id == draft_id
        assert refreshed.subject == "Exact approved subject"
        assert refreshed.body == "Exact approved body"
        history = session.scalars(
            select(OutreachApprovalHistory).where(
                OutreachApprovalHistory.outreach_draft_id == draft_id
            )
        ).one()
        assert history.subject == "Exact approved subject"
        assert history.body == "Exact approved body"
    factory.kw["bind"].dispose()


def test_harmless_evidence_update_preserves_valid_approval(tmp_path):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = Lead(
            place_id="harmless-fixture",
            name="Harmless Roofing",
            phone="555-010-2002",
            qualification_class="Promote",
            qualification_json='{"classification": "Promote"}',
            recommended_offer="Conversion Tune-Up",
            recommended_offer_id="conversion_tune_up",
            offer_resolution_state="canonical_id",
            status="Approved to Contact",
        )
        session.add(lead)
        session.flush()
        draft = OutreachDraft(
            lead_id=lead.id,
            kind=OutreachKind.INITIAL_EMAIL.value,
            subject="Still valid subject",
            body="Still valid body",
            approved=True,
            dependency_state="generated",
        )
        session.add(draft)
        session.commit()
        lead_id = lead.id
        draft_id = draft.id

    with factory() as session:
        update_lead_fields(session, lead_id, operator_notes="A harmless operator note.")
        session.commit()
        draft = session.get(OutreachDraft, draft_id)
        assert draft.approved
        assert draft.subject == "Still valid subject"
        assert draft.body == "Still valid body"
        assert not list(session.scalars(select(OutreachApprovalHistory)))
    factory.kw["bind"].dispose()


def test_artifact_slug_is_stable_and_collision_resistant():
    first = Lead(id=1, place_id="place-alpha", name="A" * 120 + " Roofing")
    second = Lead(id=2, place_id="place-beta", name="A" * 120 + " Roofing")
    assert lead_artifact_slug(first) == lead_artifact_slug(first)
    assert lead_artifact_slug(first) != lead_artifact_slug(second)
    assert len(lead_artifact_slug(first).split("--", 1)[0]) <= 56


def test_colliding_readable_names_export_isolated_lead_packages(tmp_path):
    config = app_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        first = Lead(
            place_id="package-alpha",
            name="A+B Roofing",
            category="roofers",
            phone="555-010-3001",
        )
        second = Lead(
            place_id="package-beta",
            name="A B Roofing",
            category="roofers",
            phone="555-010-3002",
        )
        session.add_all([first, second])
        session.flush()
        assert lead_artifact_slug(first).split("--", 1)[0] == lead_artifact_slug(second).split("--", 1)[0]
        first_package = LeadPackageService(config).export_package(session, first, ai_mode="off")
        second_package = LeadPackageService(config).export_package(session, second, ai_mode="off")
        session.commit()

    assert first_package != second_package
    assert first_package.exists() and second_package.exists()
    for package_path, own_name, other_name, own_phone, other_phone in (
        (first_package, "A+B Roofing", "A B Roofing", "555-010-3001", "555-010-3002"),
        (second_package, "A B Roofing", "A+B Roofing", "555-010-3002", "555-010-3001"),
    ):
        with zipfile.ZipFile(package_path) as archive:
            names = archive.namelist()
            exported_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith((".html", ".txt", ".md", ".json", ".css"))
            )
            assert len(names) == len(set(names))
            assert any(name.endswith("-manifest.json") for name in names)
            assert own_name in exported_text
            assert own_phone in exported_text
            assert other_name not in exported_text
            assert other_phone not in exported_text
    factory.kw["bind"].dispose()


def test_safe_request_caps_fixture_transport_response():
    from local_presence_miner.services.public_url_safety import PublicResponseTooLargeError, safe_request

    class Transport:
        def request(self, method, target, **kwargs):
            response = requests.Response()
            response.url = target.url
            response.status_code = 200
            response._content = b"123456"
            return response

    with pytest.raises(PublicResponseTooLargeError):
        safe_request(
            None,
            "GET",
            "https://fixture.example.com",
            resolver=lambda *_: ("93.184.216.34",),
            transport=Transport(),
            max_response_bytes=5,
        )


def test_pinned_transport_caps_streamed_decoded_body(monkeypatch):
    import local_presence_miner.services.public_url_safety as policy

    released = []

    class Raw:
        status = 200
        headers = {}

        def stream(self, **kwargs):
            assert kwargs["decode_content"] is True
            yield b"123"
            yield b"456"

        def release_conn(self):
            released.append(True)

    class Pool:
        def __init__(self, *args, **kwargs):
            pass

        def urlopen(self, *args, **kwargs):
            assert kwargs["preload_content"] is False
            return Raw()

        def close(self):
            pass

    monkeypatch.setattr(policy.urllib3, "HTTPSConnectionPool", Pool)
    target = policy.validate_public_url(
        "https://fixture.example.com",
        resolver=lambda *_: ("93.184.216.34",),
    )
    with pytest.raises(policy.PublicResponseTooLargeError):
        policy.PinnedPublicTransport(max_response_bytes=5).request("GET", target, timeout=1, headers={})
    assert released == [True]


def test_v0113_migration_backup_membership_and_notes_are_idempotent(tmp_path):
    path = tmp_path / "legacy-v0112.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE lead_searches (id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL, "
            "state_region TEXT NOT NULL, niche TEXT NOT NULL, criteria_json TEXT NOT NULL, "
            "completed BOOLEAN NOT NULL, created_at DATETIME)"
        )
        connection.execute(
            "CREATE TABLE leads (id INTEGER PRIMARY KEY, search_id INTEGER, place_id TEXT NOT NULL, name TEXT NOT NULL, "
            "notes TEXT NOT NULL, score_breakdown_json TEXT NOT NULL, search_position INTEGER, "
            "created_at DATETIME, updated_at DATETIME)"
        )
        connection.execute(
            "INSERT INTO lead_searches VALUES (1, 'Legacy search', 'Peoria', 'IL', 'roofers', '{}', 1, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO leads VALUES (1, 1, 'legacy-place', 'Legacy Roofing', 'Do not overwrite this note', "
            "'[]', 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.commit()

    factory = create_session_factory(path)
    initialize_database(factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0113")
    assert backup.exists()
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    with factory() as session:
        lead = session.get(Lead, 1)
        membership = session.scalars(select(SearchRunLead)).one()
        search = session.get(LeadSearch, 1)
        assert lead.operator_notes == "Do not overwrite this note"
        assert lead.notes == "Do not overwrite this note"
        assert lead.notes_provenance == "legacy_unknown"
        assert membership.discovery_kind == "legacy_unknown"
        assert membership.lead_id == 1 and membership.search_id == 1
        assert search.lifecycle_state == "Completed"
        assert search.succeeded_count == 1

    initialize_database(factory)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash
    with factory() as session:
        assert len(list(session.scalars(select(SearchRunLead)))) == 1
        assert list(session.scalars(select(SearchRunLease))) == []
    factory.kw["bind"].dispose()


def test_v0113a_lease_migration_creates_non_overwriting_backup(tmp_path):
    path = tmp_path / "v0113-before-lease.sqlite3"
    factory = create_session_factory(path)
    initialize_database(factory)
    with factory() as session:
        session.add(
            LeadSearch(
                name="Preserved v0.1.13 search",
                city="Peoria",
                state_region="IL",
                niche="roofers",
                criteria_json="{}",
                completed=True,
                lifecycle_state="Completed",
            )
        )
        session.commit()
    factory.kw["bind"].dispose()

    # Removing only the correction-pass lease table reproduces the immutable
    # v0.1.13 schema without manufacturing an older application fixture.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE search_run_leases")
        connection.commit()

    factory = create_session_factory(path)
    initialize_database(factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0113a")
    assert backup.exists()
    assert not path.with_suffix(path.suffix + ".backup-before-v0113").exists()
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()

    with sqlite3.connect(backup) as connection:
        backup_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "search_run_leases" not in backup_tables
        assert connection.execute("SELECT name FROM lead_searches").fetchone() == (
            "Preserved v0.1.13 search",
        )
    with factory() as session:
        assert session.get(LeadSearch, 1).name == "Preserved v0.1.13 search"
        assert list(session.scalars(select(SearchRunLease))) == []

    initialize_database(factory)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash
    factory.kw["bind"].dispose()
