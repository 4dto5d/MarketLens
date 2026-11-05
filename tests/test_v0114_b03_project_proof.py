from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import select

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.pricing_repository import (
    deactivate_seller_project,
    save_seller_project,
    save_seller_proof,
)
from local_presence_miner.database.repositories import save_outreach_draft, set_outreach_approval
from local_presence_miner.database.schema import Lead, OutreachApprovalHistory, SellerProject, SellerProof
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_state_service import persist_current_plan
from local_presence_miner.services.proof_dependency_service import (
    USAGE_CLIENT_NAME,
    USAGE_REFERENCE,
    make_proof_dependency,
    proof_allows_external_use,
)
from local_presence_miner.services.seller_proof_service import project_is_completed, summarize_seller_proof


def factory(tmp_path):
    result = create_session_factory(tmp_path / "b03.sqlite3")
    initialize_database(result)
    return result


def confirmed_project(session, *, niche: str = "roofing") -> SellerProject:
    return save_seller_project(
        session,
        project_type="Paid Project",
        title="Confirmed client engagement",
        status="Completed + Verified",
        niche=niche,
        client_name="Recorded client",
        client_work=True,
        verified=True,
        counting_state="confirmed",
    )


def test_one_project_with_five_artifacts_counts_once(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        project = confirmed_project(session)
        internal_summary = summarize_seller_proof(session, "roofing")
        assert internal_summary.completed_projects == 1
        assert internal_summary.proof_artifacts == 0
        for index, proof_type in enumerate(("Paid Project", "Case Study", "Before / After", "Testimonial", "Portfolio Example")):
            save_seller_proof(
                session,
                project_id=project.id,
                proof_type=proof_type,
                title=f"Artifact {index}",
                status="Completed + Verified",
                niche="roofing",
                client_work=True,
                verified=True,
                internal_only=False,
                share_client_name=True,
            )
        summary = summarize_seller_proof(session, "roofing")
    assert summary.completed_projects == 1
    assert summary.completed_paid_projects == 1
    assert summary.relevant_niche_projects == 1
    assert summary.proof_artifacts == 5


def test_project_counting_requires_confirmed_completed_client_work(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        incomplete = save_seller_project(
            session,
            project_type="Paid Project",
            title="In progress",
            status="In Progress",
            client_work=True,
            counting_state="incomplete",
        )
        unresolved = save_seller_project(
            session,
            project_type="Paid Project",
            title="Legacy unresolved",
            status="Completed",
            client_work=True,
            counting_state="legacy_unresolved",
        )
        assert not project_is_completed(incomplete)
        assert not project_is_completed(unresolved)
        assert summarize_seller_proof(session).completed_projects == 0


def test_artifact_permission_is_independent_of_project_count(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        project = confirmed_project(session)
        testimonial = save_seller_proof(
            session,
            project_id=project.id,
            proof_type="Testimonial",
            title="Permitted testimonial",
            status="Completed + Verified",
            client_work=True,
            verified=True,
            testimonial_available=True,
            internal_only=False,
            share_testimonial=True,
            share_reference=False,
        )
        assert proof_allows_external_use(testimonial, USAGE_CLIENT_NAME) is False
        assert proof_allows_external_use(testimonial, USAGE_REFERENCE) is False
        assert summarize_seller_proof(session).completed_projects == 1
        save_seller_proof(
            session,
            proof_id=testimonial.id,
            project_id=project.id,
            proof_type="Testimonial",
            title=testimonial.title,
            status=testimonial.status,
            client_work=True,
            verified=True,
            testimonial_available=True,
            internal_only=True,
        )
        assert summarize_seller_proof(session).completed_projects == 1


def test_project_invalidation_revokes_current_dependency_but_preserves_history(tmp_path) -> None:
    session_factory = factory(tmp_path)
    sender = SenderInfo(
        name="Operator",
        reply_email="operator@example.test",
        postal_address="123 Test Street",
        opt_out_line="Reply opt out.",
    )
    with session_factory() as session:
        project = confirmed_project(session)
        proof = save_seller_proof(
            session,
            project_id=project.id,
            proof_type="Paid Project",
            title="Shareable project artifact",
            status="Completed + Verified",
            niche="roofing",
            client_work=True,
            verified=True,
            internal_only=False,
            client_name="Recorded client",
            share_client_name=True,
        )
        lead = Lead(
            place_id="b03-project",
            name="B03 Project",
            category="roofing",
            phone="5550101010",
            qualification_class="Qualified",
            qualification_confidence="Strong",
            qualification_json='{"classification":"Qualified","confidence":"Strong"}',
            recommended_offer="Conversion Tune-Up",
            recommended_offer_id="conversion_tune_up",
            offer_resolution_state="canonical_id",
        )
        lead.verification_json = json.dumps({key: True for key in ("business_identity", "website", "phone", "audit_claims", "competitors", "outreach")})
        session.add(lead)
        session.flush()
        _plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        commercial_snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        dependency = make_proof_dependency(proof, {USAGE_CLIENT_NAME}, project=project)
        draft = save_outreach_draft(
            session,
            lead.id,
            OutreachKind.INITIAL_EMAIL,
            "Subject",
            sender.name + " recorded example\n\noperator@example.test\n123 Test Street\nReply opt out.",
                proof_dependencies=[dependency],
                commercial_snapshot=commercial_snapshot.to_dict(),
        )
        set_outreach_approval(session, draft.id, True, sender=sender)
        before = draft.body
        deactivate_seller_project(session, project.id)
        session.flush()
        history = session.scalar(select(OutreachApprovalHistory))
        assert not draft.approved
        assert history is not None and history.body == before
        assert session.get(SellerProject, project.id).counting_state == "invalidated"
        assert summarize_seller_proof(session, "roofing").completed_projects == 0


def test_legacy_migration_preserves_ids_permissions_and_never_merges_similar_rows(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE seller_profiles (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, business_name TEXT NOT NULL)")
        connection.execute("INSERT INTO seller_profiles VALUES (1, 'Sam', 'Sam Digital')")
        connection.execute(
            "CREATE TABLE seller_proof (id INTEGER PRIMARY KEY, seller_profile_id INTEGER NOT NULL, proof_type TEXT NOT NULL, title TEXT NOT NULL, "
            "status TEXT NOT NULL, niche TEXT NOT NULL, client_name TEXT, client_work BOOLEAN NOT NULL, internal_only BOOLEAN NOT NULL, "
            "share_client_name BOOLEAN NOT NULL, share_reference BOOLEAN NOT NULL)"
        )
        connection.execute("INSERT INTO seller_proof VALUES (11, 1, 'Testimonial', 'Same Client', 'Completed', 'roofing', 'Same Client', 1, 0, 1, 0)")
        connection.execute("INSERT INTO seller_proof VALUES (12, 1, 'Testimonial', 'Same Client', 'Completed', 'roofing', 'Same Client', 1, 0, 1, 0)")
        connection.commit()
    session_factory = create_session_factory(path)
    initialize_database(session_factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0114-b03")
    assert backup.exists()
    with session_factory() as session:
        proofs = list(session.scalars(select(SellerProof).order_by(SellerProof.id)))
        projects = list(session.scalars(select(SellerProject).order_by(SellerProject.id)))
        assert [proof.id for proof in proofs] == [11, 12]
        assert [proof.grouping_state for proof in proofs] == ["legacy_unresolved_singleton", "legacy_unresolved_singleton"]
        assert [project.legacy_source_proof_id for project in projects] == [11, 12]
        assert all(project.counting_state == "legacy_unresolved" for project in projects)
        assert all(project.id == proof.project_id for project, proof in zip(projects, proofs, strict=True))
        assert all(proof.share_client_name and not proof.share_reference for proof in proofs)
    initialize_database(session_factory)
    with session_factory() as session:
        assert len(list(session.scalars(select(SellerProject)))) == 2
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_legacy_migration_leaves_recoverable_backup_and_no_marker(tmp_path) -> None:
    path = tmp_path / "broken-legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE seller_profiles (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, business_name TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE seller_proof (id INTEGER PRIMARY KEY, seller_profile_id INTEGER NOT NULL, proof_type TEXT NOT NULL, title TEXT NOT NULL, "
            "status TEXT NOT NULL, niche TEXT NOT NULL, client_work BOOLEAN NOT NULL)"
        )
        # This is deliberately malformed: there is no owning seller profile.
        connection.execute("INSERT INTO seller_proof VALUES (7, 404, 'Testimonial', 'Orphaned proof', 'Completed', 'roofing', 1)")
        connection.commit()
    session_factory = create_session_factory(path)
    with pytest.raises(RuntimeError, match="integrity validation failed"):
        initialize_database(session_factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0114-b03")
    assert backup.exists()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT id FROM seller_proof").fetchall() == [(7,)]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(path) as connection:
        marker = connection.execute(
            "SELECT value FROM app_settings WHERE key='v0114_b03_project_proof_migrated'"
        ).fetchone()
        assert marker is None
