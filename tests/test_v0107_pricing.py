from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.pricing_repository import (
    get_or_create_seller_profile,
    list_offer_history,
    list_seller_proof,
    save_offer_history,
    save_seller_profile,
    save_seller_proof,
)
from local_presence_miner.database.repositories import log_activity
from local_presence_miner.database.schema import Lead, OfferHistory, SellerProfile, SellerProof
from local_presence_miner.domain.offer_registry import resolve_offer
from local_presence_miner.services.comparable_offer_service import ComparableOfferService
from local_presence_miner.services.export_service import ExportService
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.pricing_calibration import estimate_project_value
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.seller_pricing_service import SellerPricingService
from local_presence_miner.services.seller_proof_service import safe_proof_sentence, summarize_seller_proof


def make_lead(
    session,
    *,
    place_id: str = "pricing-lead",
    niche: str = "roofing",
    score: int = 80,
    package: str = "One-Page Conversion Site + Google Cleanup",
) -> Lead:
    lead = Lead(
        place_id=place_id,
        name="Strong Roofing Prospect",
        category=niche,
        lead_score=score,
        recommended_offer=package,
        starting_offer_json=json.dumps({"scope": ["Homepage conversion refresh", "Quote flow", "Review proof"]}),
    )
    session.add(lead)
    session.flush()
    # This suite prices a seller-selected catalog package, not an automatic
    # recommendation inferred from a prospect score or cached JSON.
    selected = resolve_offer(package)
    if selected.offer_id:
        log_activity(session, "offer_selected", json.dumps({"offer_id": selected.offer_id.value}), lead.id)
        session.flush()
    return lead


def save_offer(
    session,
    *,
    business: str,
    niche: str,
    ask: int,
    status: str,
    closed: int | None = None,
    lost_reason: str = "",
    days_ago: int = 30,
    package: str = "One-Page Conversion Site + Google Cleanup",
    growth_score: int = 70,
    project_low: int = 1000,
    project_high: int = 2400,
):
    return save_offer_history(
        session,
        historical_record=True,
        offer_date=(date.today() - timedelta(days=days_ago)).isoformat(),
        business_name=business,
        niche=niche,
        package_name=package,
        scope_summary="Homepage conversion refresh; quote flow; review proof",
        initial_ask=ask,
        status=status,
        closed_amount=closed,
        lost_reason=lost_reason,
        growth_score_at_offer=growth_score,
        project_value_low_at_offer=project_low,
        project_value_high_at_offer=project_high,
        seller_confidence_at_offer="Low",
        proof_snapshot={"recorded_at_offer": business},
    )


def test_seller_profile_proof_and_offer_persist(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "pricing.sqlite3")
    initialize_database(factory)
    with factory() as session:
        profile = save_seller_profile(
            session,
            display_name="Sammi",
            business_name="Sammi Sites",
            experience_start_date="2025-01-02",
            notes="Private seller notes",
        )
        proof = save_seller_proof(
            session,
            proof_type="Paid Project",
            title="Roofing conversion site",
            niche="roofing",
            project_value=1200,
            completion_date="2026-07-01",
            verified=True,
        )
        offer = save_offer(session, business="ABC Roofing", niche="roofing", ask=1250, status="Won", closed=1150)
        ids = profile.id, proof.id, offer.id
        session.commit()
    with factory() as session:
        assert session.get(SellerProfile, ids[0]).display_name == "Sammi"
        assert session.get(SellerProof, ids[1]).verified is True
        assert session.get(OfferHistory, ids[2]).closed_amount == 1150
        assert len(list_seller_proof(session)) == 1
        assert len(list_offer_history(session)) == 1


def test_won_accepted_lost_and_negotiation_amounts_remain_distinct(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "outcomes.sqlite3")
    initialize_database(factory)
    with factory() as session:
        accepted = save_offer_history(
            session,
            historical_record=True,
            offer_date=date.today().isoformat(),
            business_name="Accepted Co",
            niche="roofing",
            package_name="Core",
            scope_summary="Core scope",
            initial_ask=1500,
            final_ask=1350,
            status="Accepted",
        )
        won = save_offer_history(
            session,
            historical_record=True,
            offer_date=date.today().isoformat(),
            business_name="Won Co",
            niche="roofing",
            package_name="Core",
            scope_summary="Core scope",
            initial_ask=1500,
            final_ask=1300,
            closed_amount=1250,
            status="Won",
        )
        lost = save_offer_history(
            session,
            offer_date=date.today().isoformat(),
            business_name="Lost Co",
            niche="roofing",
            package_name="Core",
            scope_summary="Core scope",
            initial_ask=1500,
            status="Lost",
            lost_reason="Too expensive",
        )
        assert accepted.status == "Accepted" and accepted.closed_amount is None
        assert (won.initial_ask, won.final_ask, won.closed_amount) == (1500, 1300, 1250)
        assert lost.lost_reason == "Too expensive"
        with pytest.raises(ValueError, match="closed amount"):
            save_offer_history(
                session,
                offer_date=date.today().isoformat(),
                business_name="Invalid Win",
                niche="roofing",
                package_name="Core",
                scope_summary="",
                initial_ask=1000,
                status="Won",
            )


def test_comparable_selection_is_niche_aware_and_no_response_is_not_price_evidence(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "comparables.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        save_offer(session, business="Roof Win", niche="roofing", ask=1000, status="Won", closed=900)
        save_offer(
            session,
            business="Roof Silence",
            niche="roofing",
            ask=1200,
            status="Lost",
            lost_reason="No response",
        )
        save_offer(
            session,
            business="Roof Price Loss",
            niche="roofing",
            ask=1500,
            status="Lost",
            lost_reason="Too expensive",
        )
        save_offer(
            session,
            business="Unrelated Dental",
            niche="dental",
            ask=3000,
            status="Won",
            closed=2800,
            package="Unrelated package",
            growth_score=20,
            project_low=3000,
            project_high=5000,
        )
        analysis = ComparableOfferService().analyze(session, lead, lead.recommended_offer, "Homepage quote flow", 1000, 2400)
        names = [item.offer.business_name for item in analysis.offers]
        assert "Roof Win" in names
        assert "Unrelated Dental" not in names
        assert analysis.won_count == 1
        assert analysis.resolved_price_sample == 2
        assert "1 / 2" in analysis.success_text
        assert "reliable close-rate" in analysis.success_text


def test_recent_wins_prevent_old_beginner_prices_from_permanently_anchoring(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "recency.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        for index, amount in enumerate([300, 500, 600]):
            save_offer(
                session,
                business=f"Old {index}",
                niche="roofing",
                ask=amount,
                status="Won",
                closed=amount,
                days_ago=1200 + index,
            )
        for index, amount in enumerate([1100, 1300, 1500]):
            save_offer(
                session,
                business=f"Recent {index}",
                niche="roofing",
                ask=amount,
                status="Won",
                closed=amount,
                days_ago=90 - index * 20,
            )
        recommendation = SellerPricingService().recommend_for_lead(session, lead)
        assert recommendation.recommended >= 1500
        assert recommendation.proof.recent_pricing_trend == "Increasing"


def test_insufficient_history_is_explicit_and_uses_smaller_scope(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "empty.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        recommendation = SellerPricingService().recommend_for_lead(session, lead)
        assert recommendation.confidence == "Low"
        assert recommendation.comparable.sample_count == 0
        assert any("Limited seller history" in line for line in recommendation.reasoning)
        assert recommendation.phases[0].scope != recommendation.phases[1].scope
        assert recommendation.project.low <= recommendation.stretch <= recommendation.project.high


def test_seller_evidence_changes_ask_but_not_project_value(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "separation.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        before = SellerPricingService().recommend_for_lead(session, lead)
        project_before = estimate_project_value(lead)
        # v5: three completed paid projects move the seller to pricing stage 2.
        for index in range(3):
            save_seller_proof(
                session,
                proof_type="Paid Project",
                title=f"Roof project {index}",
                niche="roofing",
                status="Completed",
                client_work=True,
                verified=True,
            )
        save_offer(session, business="Prior Roof Win", niche="roofing", ask=1200, status="Won", closed=1100)
        after = SellerPricingService().recommend_for_lead(session, lead)
        project_after = estimate_project_value(lead)
        assert (project_before.low, project_before.high) == (project_after.low, project_after.high)
        assert (before.pricing_stage, after.pricing_stage) == (1, 2)
        assert after.recommended > before.recommended


def test_manual_override_and_historical_snapshot_are_immutable(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "snapshot.sqlite3")
    initialize_database(factory)
    with factory() as session:
        proof = save_seller_proof(
            session,
            proof_type="Paid Project",
            title="Original proof",
            niche="roofing",
            verified=True,
        )
        offer = save_offer_history(
            session,
            offer_date=date.today().isoformat(),
            business_name="Override Co",
            niche="roofing",
            package_name="Core",
            scope_summary="Core",
            initial_ask=1500,
            recommended_ask_at_offer=1250,
            status="Presented",
            proof_snapshot={"proof_title": proof.title, "paid_projects": 1},
        )
        original_snapshot = offer.proof_snapshot_json
        proof.title = "Changed later"
        save_offer_history(
            session,
            offer_id=offer.id,
            offer_date=offer.offer_date,
            business_name=offer.business_name,
            niche=offer.niche,
            package_name=offer.package_name,
            scope_summary=offer.scope_summary,
            initial_ask=offer.initial_ask,
            recommended_ask_at_offer=offer.recommended_ask_at_offer,
            status="Negotiating",
            proof_snapshot={"proof_title": "Should not replace history"},
        )
        assert offer.initial_ask == 1500
        assert offer.recommended_ask_at_offer == 1250
        assert offer.proof_snapshot_json == original_snapshot


def test_proof_matching_never_generates_claim_from_unverified_record(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "proof-claims.sqlite3")
    initialize_database(factory)
    with factory() as session:
        save_seller_proof(
            session,
            proof_type="Paid Project",
            title="Unverified Roofing Story",
            niche="roofing",
            description="Self-authored claim",
            verified=False,
        )
        summary = summarize_seller_proof(session, "roofing")
        assert safe_proof_sentence(summary, "roofing") == ""
        save_seller_proof(
            session,
            proof_type="Portfolio Example",
            title="Verified Roofing Example",
            niche="roofing",
            status="Completed",
            verified=True,
            internal_only=False,
            public_url="https://portfolio.example.com/roofing",
            share_public_url=True,
        )
        sentence = safe_proof_sentence(summarize_seller_proof(session, "roofing"), "roofing")
        assert "verified relevant roofing example" in sentence.lower()
        assert "permission to share" in sentence
        assert "revenue" not in sentence.lower()


def test_negotiation_metrics_and_small_sample_suppression(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "negotiation.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        for index, (ask, closed) in enumerate([(1500, 1300), (1600, 1400), (1700, 1500)]):
            offer = save_offer(
                session,
                business=f"Negotiated {index}",
                niche="roofing",
                ask=ask,
                status="Won",
                closed=closed,
            )
            offer.final_ask = closed + 50
        analysis = ComparableOfferService().analyze(session, lead, lead.recommended_offer, "Homepage quote flow", 1000, 2400)
        assert analysis.average_negotiation_discount == 200
        assert "reliable close-rate" in analysis.success_text
        for index in range(2):
            save_offer(
                session,
                business=f"Price loss {index}",
                niche="roofing",
                ask=1700,
                status="Lost",
                lost_reason="Too expensive",
            )
        reliable = ComparableOfferService().analyze(session, lead, lead.recommended_offer, "Homepage quote flow", 1000, 2400)
        assert "60.0%" in reliable.success_text


def test_customer_proposal_and_lead_package_exclude_private_seller_history(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "privacy.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        save_seller_proof(
            session,
            proof_type="Testimonial",
            title="PRIVATE SELLER TESTIMONIAL",
            niche="roofing",
            verified=True,
            notes="PRIVATE NEGOTIATION NOTE",
        )
        save_offer(session, business="PRIVATE PAST CLIENT", niche="roofing", ask=1000, status="Won", closed=900)
        customer = ProposalService(config).generate_proposal(session, lead, selected_price=1250)
        internal = ProposalService(config).generate_proposal(session, lead, internal=True)
        package = LeadPackageService(config).export_package(session, lead)
    customer_text = customer.read_text(encoding="utf-8")
    internal_text = internal.read_text(encoding="utf-8")
    assert "$1,250" in customer_text
    assert "Private Seller Pricing Intelligence" not in customer_text
    assert "PRIVATE SELLER TESTIMONIAL" not in customer_text
    assert "Private Seller Pricing Intelligence" in internal_text
    with zipfile.ZipFile(package) as archive:
        exported = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore") for name in archive.namelist() if name.endswith((".html", ".json", ".txt", ".md"))
        )
    assert "PRIVATE SELLER TESTIMONIAL" not in exported
    assert "PRIVATE NEGOTIATION NOTE" not in exported
    assert "PRIVATE PAST CLIENT" not in exported


def test_private_csv_exports_and_no_config_secrets(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "exports.sqlite3")
    initialize_database(factory)
    with factory() as session:
        save_seller_proof(
            session,
            proof_type="Certification",
            title="Accessibility certificate",
            verified=True,
        )
        save_offer(session, business="CSV Roofing", niche="roofing", ask=1200, status="Won", closed=1100)
        offers = ExportService().export_offer_history_csv(session, tmp_path / "offers.csv")
        proof = ExportService().export_seller_proof_csv(session, tmp_path / "seller_proof.csv")
    assert "CSV Roofing" in offers.read_text(encoding="utf-8")
    assert "Accessibility certificate" in proof.read_text(encoding="utf-8")
    assert "api_key" not in (offers.read_text(encoding="utf-8") + proof.read_text(encoding="utf-8")).lower()


def test_v0106_database_is_backed_up_before_v0107_tables(tmp_path) -> None:
    path = tmp_path / "v0106.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id TEXT NOT NULL, name TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE contact_interactions (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, "
        "interaction_datetime TEXT NOT NULL, method TEXT NOT NULL, direction TEXT NOT NULL, outcome TEXT NOT NULL, "
        "notes TEXT NOT NULL, follow_up_date TEXT NOT NULL, created_at DATETIME)"
    )
    connection.commit()
    connection.close()
    factory = create_session_factory(path)
    initialize_database(factory)
    assert path.with_suffix(path.suffix + ".backup-before-v0107").exists()
    with factory() as session:
        assert session.scalar(select(SellerProfile)) is None
        get_or_create_seller_profile(session)
        session.commit()
        assert session.scalar(select(SellerProfile)) is not None


def test_final_roofing_acceptance_scenario(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "acceptance.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = make_lead(session)
        save_offer(session, business="Roof Offer 1", niche="roofing", ask=750, status="Won", closed=750, days_ago=240)
        save_offer(session, business="Roof Offer 2", niche="roofing", ask=1000, status="Won", closed=900, days_ago=180)
        save_offer(
            session,
            business="Roof Offer 3",
            niche="roofing",
            ask=1200,
            status="Lost",
            lost_reason="No response",
            days_ago=120,
        )
        save_offer(
            session,
            business="HVAC Offer",
            niche="hvac",
            ask=1250,
            status="Won",
            closed=1150,
            package="HVAC maintenance package",
            growth_score=40,
            project_low=400,
            project_high=900,
            days_ago=60,
        )
        for title, niche in [("Roof Project A", "roofing"), ("Roof Project B", "roofing"), ("HVAC Project", "hvac")]:
            save_seller_proof(
                session,
                proof_type="Paid Project",
                title=title,
                niche=niche,
                status="Completed",
                client_work=True,
                verified=True,
            )
        for title in ["Roof Testimonial A", "Roof Testimonial B"]:
            save_seller_proof(
                session,
                proof_type="Testimonial",
                title=title,
                niche="roofing",
                status="Completed",
                testimonial_available=True,
                verified=True,
            )
        recommendation = SellerPricingService().recommend_for_lead(session, lead)
        assert recommendation.project.low == 1950
        # v0.1.14 records HVAC as a transparent same-family comparison rather
        # than silently treating it as a roofing result.  The historical offer
        # is therefore eligible as related home-service evidence.
        # Registry v5: the catalog band is 1,950-2,650 (stage quotes 1,950 /
        # 2,250 / 2,650). Three completed paid projects put the seller at
        # stage 2, so the ask is the 2,250 stage quote. The 1,150 related-family
        # win (+ one 250 proof step) is below that quote and does not lower it.
        # Easy is one step down but never below the internal walk-away
        # (35/h x 24.9 realistic warm hours + $80 cash, card fees = 1,000).
        assert recommendation.pricing_stage == 2
        assert recommendation.walk_away == 1000
        assert recommendation.easy_close == 2000
        assert recommendation.recommended == 2250
        assert recommendation.stretch == 2650
        assert recommendation.confidence == "Moderate"
        assert recommendation.proof.completed_paid_projects == 3
        assert recommendation.proof.relevant_niche_projects == 2
        assert recommendation.proof.testimonials == 2
        assert recommendation.comparable.sample_count == 4
        assert recommendation.comparable.resolved_price_sample == 3
        assert any("related service family" in comparable.reasons for comparable in recommendation.comparable.offers)
        assert "Not enough history" in recommendation.comparable.success_text
