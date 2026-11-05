from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import func, select

from local_presence_miner.config import AppConfig, SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.pricing_repository import (
    delete_seller_proof,
    save_seller_profile,
    save_seller_proof,
)
from local_presence_miner.database.repositories import save_contact_interaction, save_outreach_draft, set_outreach_approval
from local_presence_miner.database.schema import ContactInteraction, Lead, OutreachDraft, WebsiteAuditRecord
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import refresh_after_seller_proof_change
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.conversation_state_service import ConversationStateService
from local_presence_miner.services.credibility_service import CredibilityService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.proposal_service import ProposalService


def lead() -> Lead:
    return Lead(
        place_id="credibility-roofer",
        name="ABC Roofing",
        category="roofers",
        website="https://abc.example",
        phone="555-0100",
        rating=4.8,
        review_count=34,
        lead_score=82,
        sales_priority_score=86,
        qualification_class="Demo Priority",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Demo Priority","confidence":"Strong"}',
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        offer_resolution_state="canonical_id",
        target_signals_json='["No obvious CTA"]',
        audit=WebsiteAuditRecord(url="https://abc.example", reachable=True, status_code=200,
                                checks_json='{"sitewide_contact_path":false,"tap_to_call":false,"contact_form":false}'),
    )


def factory(tmp_path):
    result = create_session_factory(tmp_path / "credibility.sqlite3")
    initialize_database(result)
    return result


def test_no_client_work_uses_truthful_new_seller_response(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        session.add(lead())
        session.flush()
        profile = CredibilityService().build(session, "roofers")
        guide = CallGuideService().build(session, session.scalar(select(Lead)), [])
    assert profile.completed_client_projects == 0
    assert "newer on the client-service side" in profile.experience_normal
    assert "large niche portfolio" in profile.experience_normal
    assert any("no completed proof" in line.lower() for line in guide.why_you)
    assert "years of experience" in " ".join(guide.do_not_claim).lower()


def test_in_progress_and_prototype_are_never_promoted_to_completed_client_work(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        in_progress = save_seller_proof(
            session,
            proof_type="Local-Business Website Project",
            title="Roofing build",
            status="In Progress",
            niche="roofers",
            client_work=True,
            verified=True,
            client_name="Developmental Roofing",
            internal_only=False,
            share_client_name=True,
        )
        prototype = save_seller_proof(
            session,
            proof_type="Portfolio Concept",
            title="Roofing concept",
            status="Prototype",
            niche="roofers",
        )
        summary = CredibilityService().build(session, "roofers")
        assert "in progress" in summary.experience_normal.lower()
        assert summary.completed_client_projects == 0
        assert "not completed client work" in summary.experience_normal.lower()
        assert in_progress.status == "In Progress"
        assert prototype.client_work is False
        with pytest.raises(ValueError, match="cannot be recorded"):
            save_seller_proof(
                session,
                proof_type="Portfolio Concept",
                title="Invalid prototype",
                status="Prototype",
                client_work=True,
            )


def test_same_niche_completed_verified_proof_testimonial_and_result_are_ranked(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        save_seller_proof(
            session,
            proof_type="Paid Project",
            title="Summit Roofing Website",
            client_name="Summit Roofing",
            client_work=True,
            internal_only=False,
            share_client_name=True,
            share_public_url=True,
            share_testimonial=True,
            before_after_available=True,
            share_case_study=True,
            status="Completed + Measurable Result",
            niche="roofers",
            verified=True,
            testimonial_available=True,
            measurable_result_available=True,
            public_url="https://portfolio.example/summit",
            safe_claims=["Completed Summit Roofing website project"],
            prohibited_claims=["Guaranteed Summit Roofing more revenue"],
        )
        summary = CredibilityService().build(session, "roofers")
    assert summary.same_niche_completed_client_projects == 1
    assert "1 completed relevant client project" in summary.experience_normal
    assert "verified testimonial" in summary.experience_normal
    assert "verified measurable result" in summary.experience_normal
    assert summary.attachments.send[0].startswith("recorded work for Summit Roofing")
    assert "Guaranteed Summit Roofing more revenue" in summary.do_not_claim


def test_identity_company_location_and_ai_responses_use_configured_evidence(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        save_seller_profile(
            session,
            display_name="Sam",
            business_name="Sam Digital",
            identity_type="Brand Name",
            location_mode="Remote-first service",
            location_label="Denver, CO",
            service_area="Colorado",
        )
        save_seller_proof(
            session,
            proof_type="AI / Software System",
            title="Local Presence Miner",
            status="Completed + Verified",
            verified=True,
            software_ai_project=True,
        )
        profile = CredibilityService().build(session, "roofers")
    assert profile.identity_response.startswith("I'm Sam")
    assert "Sam Digital" in profile.company_response
    assert "remotely" in profile.location_response
    assert "Denver" in profile.location_response
    assert "Local Presence Miner" not in profile.ai_response
    assert any(item.proof.title == "Local Presence Miner" for item in profile.ranked_proof)
    assert "move faster, not to invent" in profile.ai_response


def test_call_tree_prioritizes_early_skepticism_and_contains_deep_ai_paths(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        prospect = lead()
        session.add(prospect)
        session.flush()
        guide = CallGuideService().build(session, prospect, [])
    keys = {branch.key for branch in guide.branches}
    assert guide.initial_branch_keys == (
        "who_are_you",
        "what_about",
        "provider",
        "too_expensive",
        "think",
        "overwhelmed",
        "evidence_dispute",
        "stop_disengage",
    )
    assert {"who_are_you", "experience", "credibility", "ai_skepticism", "why_you", "other"} <= keys
    who = next(branch for branch in guide.branches if branch.key == "who_are_you")
    assert {"What company are you with?", "Are you local?", "Why did you pick us?", "Is this a sales call?"} <= {
        item.label for item in who.followups
    }
    ai = next(branch for branch in guide.branches if branch.key == "ai_skepticism")
    labels = {item.label for item in ai.followups}
    assert {"Why would I pay if AI can make a website?", "Can't I use ChatGPT, Lovable, or Canva myself?", "Will AI make things up?"} <= labels
    pay = next(item for item in ai.followups if item.label == "Why would I pay if AI can make a website?")
    assert {item.label for item in pay.followups} == {"I can do it myself", "I don't have time to do it"}


def test_competitor_language_requires_manual_verification(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        prospect = lead()
        session.add(prospect)
        session.flush()
        from local_presence_miner.database.schema import CompetitorRecord

        record = CompetitorRecord(
            lead_id=prospect.id,
            competitor_place_id="nearby",
            competitor_name="Nearby Roofing",
            match_score=90,
            reason="Same niche",
        )
        session.add(record)
        session.flush()
        unverified = CallGuideService().build(session, prospect, [record])
        prospect.verification_json = '{"competitors":true}'
        verified = CallGuideService().build(session, prospect, [record])
    # A reviewed competitor record alone is not a bounded owner-facing finding.
    # B2 therefore keeps named competitor language out of both openings.
    assert "nearby" not in unverified.opening_30s.lower()
    assert "nearby" not in verified.opening_30s.lower()


def test_credibility_conversation_state_persists_and_changes_follow_up_email(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        prospect = lead()
        session.add(prospect)
        session.flush()
        save_contact_interaction(
            session,
            prospect.id,
            interaction_datetime="2026-08-28T10:00",
            method="Phone",
            direction="Outbound",
            outcome="Requested information",
            notes="Asked for proof",
            credibility_concern=True,
            wants_examples=True,
            wants_proof=True,
            seller_experience_question=True,
            decision_maker_skeptical=True,
            branch_path=["Have you actually done this before?", "Can I see examples?"],
        )
        state = ConversationStateService().build(session, prospect)
        drafts = OutreachService(SenderInfo(name="Sam", opt_out_line="Reply opt out.")).generate_all(prospect, session=session)
    assert state.credibility_concern is True
    assert state.wants_examples is True
    assert state.seller_experience_question is True
    body = drafts[OutreachKind.SHORT_FOLLOW_UP][1]
    assert "asked about my experience" in body.lower()
    assert "instead of overstating" in body.lower()


def test_new_unrelated_proof_regenerates_unapproved_but_preserves_approved_draft(tmp_path, outbound) -> None:
    session_factory = factory(tmp_path)
    sender = outbound.sender
    with session_factory() as session:
        first = lead()
        second = lead()
        second.place_id = "approved-lead"
        second.name = "Approved Roofing"
        second.verification_json = '{"business_identity":true,"website":true,"audit_claims":true,"outreach":true}'
        session.add_all([first, second])
        session.flush()
        for prospect in (first, second):
            save_contact_interaction(
                session,
                prospect.id,
                interaction_datetime="2026-08-28T10:00",
                method="Phone",
                direction="Outbound",
                outcome="Requested information",
                notes="Experience question",
                seller_experience_question=True,
                credibility_concern=True,
            )
        refresh_after_seller_proof_change(session, sender)
        approved = session.scalar(
            select(OutreachDraft).where(OutreachDraft.lead_id == second.id, OutreachDraft.kind == OutreachKind.SHORT_FOLLOW_UP.value)
        )
        approved_body = approved.body
        set_outreach_approval(session, approved.id, True, sender=sender)
        before = session.scalar(
            select(OutreachDraft).where(OutreachDraft.lead_id == first.id, OutreachDraft.kind == OutreachKind.SHORT_FOLLOW_UP.value)
        ).body
        save_seller_proof(
            session,
            proof_type="Paid Project",
            title="Roofing Client",
            client_name="Roofing Client",
            client_work=True,
            internal_only=False,
            share_client_name=True,
            status="Completed + Verified",
            niche="roofers",
            verified=True,
            safe_claims=["Completed roofing client project"],
        )
        assert refresh_after_seller_proof_change(session, sender) == 2
        session.flush()
        after = session.scalar(
            select(OutreachDraft).where(OutreachDraft.lead_id == first.id, OutreachDraft.kind == OutreachKind.SHORT_FOLLOW_UP.value)
        ).body
        session.refresh(approved)
    assert before != after
    assert "recorded work for Roofing Client" in after
    # B04 makes a material proof/pricing change revoke approval rather than
    # silently keeping an apparently-current message. The exact old text is
    # retained in approval history by the repository contract.
    assert approved.approved is False
    assert approved.body != approved_body


def test_deleted_proof_stops_being_used(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        proof = save_seller_proof(
            session,
            proof_type="Paid Project",
            title="Deleted Roofing Example",
            client_name="Deleted Roofing Example",
            client_work=True,
            internal_only=False,
            share_client_name=True,
            status="Completed + Verified",
            niche="roofers",
            verified=True,
        )
        session.flush()
        assert "Deleted Roofing Example" in CredibilityService().build(session, "roofers").experience_normal
        delete_seller_proof(session, proof.id)
        session.flush()
        profile = CredibilityService().build(session, "roofers")
    assert "Deleted Roofing Example" not in profile.experience_normal
    # Removing an artifact does not erase the confirmed engagement it documented.
    assert profile.completed_client_projects == 1


def test_credibility_migration_creates_dedicated_backup_and_preserves_rows(tmp_path) -> None:
    path = tmp_path / "integrity-v0111.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id TEXT NOT NULL, name TEXT NOT NULL)")
    connection.execute("INSERT INTO leads VALUES (1, 'old', 'Old Lead')")
    connection.execute("CREATE TABLE seller_profiles (id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, business_name TEXT NOT NULL)")
    connection.execute("INSERT INTO seller_profiles VALUES (1, 'Sam', 'Sam Digital')")
    connection.execute(
        "CREATE TABLE seller_proof (id INTEGER PRIMARY KEY, seller_profile_id INTEGER NOT NULL, proof_type TEXT NOT NULL, title TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO seller_proof VALUES (1, 1, 'Portfolio Example', 'Legacy Example')")
    connection.execute(
        "CREATE TABLE contact_interactions (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, interaction_datetime TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()
    session_factory = create_session_factory(path)
    initialize_database(session_factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0111-credibility")
    assert backup.exists()
    with sqlite3.connect(path) as migrated:
        proof_columns = {row[1] for row in migrated.execute("PRAGMA table_info(seller_proof)")}
        memory_columns = {row[1] for row in migrated.execute("PRAGMA table_info(contact_interactions)")}
        assert {"status", "client_work", "safe_claims_json", "prohibited_claims_json"} <= proof_columns
        assert {"credibility_concern", "concerned_about_ai", "wants_proof"} <= memory_columns
        assert migrated.execute("SELECT title, status FROM seller_proof WHERE id=1").fetchone() == ("Legacy Example", "Unclassified")


def test_proposal_uses_concise_verified_proof_and_hides_unverified_competitors(tmp_path) -> None:
    session_factory = factory(tmp_path)
    config = AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "credibility.sqlite3",
        log_path=tmp_path / "app.log",
        output_dir=tmp_path,
    )
    with session_factory() as session:
        prospect = lead()
        session.add(prospect)
        session.flush()
        save_seller_proof(
            session,
            proof_type="Paid Project",
            title="Verified Roofing Work",
            client_name="Verified Roofing Work",
            client_work=True,
            internal_only=False,
            share_client_name=True,
            status="Completed + Verified",
            niche="roofers",
            verified=True,
            safe_claims=["Completed verified roofing website project"],
        )
        from local_presence_miner.database.schema import CompetitorRecord

        session.add(
            CompetitorRecord(
                lead_id=prospect.id,
                competitor_place_id="unverified-neighbor",
                competitor_name="Unverified Neighbor",
                match_score=90,
                reason="Not manually reviewed",
            )
        )
        session.flush()
        output = ProposalService(config).generate_proposal(session, prospect, selected_price=1200)
    html = output.read_text(encoding="utf-8")
    assert "Why This Recommendation Is Grounded" in html
    assert "recorded work for Verified Roofing Work" in html
    assert "Unverified Neighbor" not in html


def test_practice_call_credibility_state_and_back_do_not_persist(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from local_presence_miner.ui.dialogs.guided_call_dialog import GuidedCallDialog

    app = QApplication.instance() or QApplication([])
    session_factory = factory(tmp_path)
    with session_factory() as session:
        prospect = lead()
        session.add(prospect)
        session.commit()
        lead_id = prospect.id
    dialog = GuidedCallDialog(session_factory, lead_id)
    dialog.show_branch("experience")
    assert dialog.state["seller_experience_question"] is True
    dialog.go_back()
    assert "seller_experience_question" not in dialog.state
    dialog.show_branch("credibility")
    dialog.record_outcome()
    with session_factory() as session:
        assert session.scalar(select(func.count(ContactInteraction.id))) == 0
    dialog.close()
    app.processEvents()


def test_dnc_remains_absolute_after_credibility_expansion(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        prospect = lead()
        prospect.suppressed = True
        session.add(prospect)
        session.flush()
        draft = save_outreach_draft(session, prospect.id, OutreachKind.INITIAL_EMAIL, "Hi", "Body")
        with pytest.raises(ValueError, match="Suppressed"):
            set_outreach_approval(session, draft.id, True)


def test_windows_fixed_and_string_versions_are_current_v0115() -> None:
    version_text = (Path(__file__).parents[1] / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")
    assert "filevers=(0, 1, 16, 0)" in version_text
    assert "prodvers=(0, 1, 16, 0)" in version_text
    assert "StringStruct('FileVersion', '0.1.16.0')" in version_text
    assert "StringStruct('ProductVersion', '0.1.16.0')" in version_text


def test_legacy_save_calls_preserve_new_profile_and_proof_state(tmp_path) -> None:
    session_factory = factory(tmp_path)
    with session_factory() as session:
        profile = save_seller_profile(
            session,
            display_name="Sam",
            business_name="Sam Digital",
            identity_type="Brand Name",
            location_mode="Remote-first service",
            location_label="Denver, CO",
            service_area="Colorado",
        )
        proof = save_seller_proof(
            session,
            proof_type="Portfolio Example",
            title="Legacy evidence",
            status="Unclassified",
            verified=True,
            provenance="Imported legacy record",
            safe_claims=["Legacy artifact exists"],
        )
        session.flush()
        save_seller_profile(session, display_name="Sam Updated", business_name="Sam Digital")
        save_seller_proof(
            session,
            proof_id=proof.id,
            proof_type="Portfolio Example",
            title="Legacy evidence renamed",
        )
        session.flush()
        session.refresh(profile)
        session.refresh(proof)
    assert profile.location_mode == "Remote-first service"
    assert profile.location_label == "Denver, CO"
    assert proof.status == "Unclassified"
    assert proof.verified is True
    assert proof.provenance == "Imported legacy record"
    assert "Legacy artifact exists" in proof.safe_claims_json
