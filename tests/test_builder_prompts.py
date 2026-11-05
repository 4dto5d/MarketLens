from __future__ import annotations

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import save_audit, upsert_lead
from local_presence_miner.database.schema import CompetitorRecord
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown, WebsiteAudit
from local_presence_miner.services.static_site_service import StaticSiteService
from local_presence_miner.services.website_builder_prompt_service import WebsiteBuilderPromptService


def make_config(tmp_path) -> AppConfig:
    return AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        log_path=tmp_path / "app.log",
        output_dir=tmp_path / "out",
    )


def test_builder_prompt_uses_target_and_competitor_evidence(tmp_path) -> None:
    config = make_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        target = upsert_lead(
            session,
            BusinessProfile(
                place_id="target",
                name="ABC Roofing",
                category="roofers",
                phone="555-0100",
                website="https://abc.example",
                google_maps_url="https://maps.example/abc",
                rating=4.8,
                review_count=126,
                photo_count=12,
                has_hours=True,
            ),
            None,
            ScoreBreakdown(
                82,
                "A",
                [],
                "One-Page Conversion Site + Google Cleanup",
                "Lead with quote flow",
                ["Weak website"],
            ),
        )
        competitor = upsert_lead(
            session,
            BusinessProfile(
                place_id="competitor",
                name="Smith Roofing",
                category="roofers",
                website="https://smith.example",
                rating=4.9,
                review_count=184,
            ),
            None,
            ScoreBreakdown(30, "C", [], "Conversion Tune-Up", "", []),
        )
        session.flush()
        save_audit(
            session,
            target.id,
            WebsiteAudit(
                url=target.website,
                reachable=True,
                checks={
                    "https": True,
                    "viewport": True,
                    "clear_primary_cta": False,
                    "booking_or_quote_language": False,
                    "tap_to_call": True,
                    "contact_form": True,
                    "service_pages": False,
                    "trust_signals": False,
                    "faq_content": False,
                    "local_schema": False,
                },
                strengths=["Tap-to-call is present."],
                weaknesses=["No clear quote CTA was detected.", "Trust proof is weak."],
            ),
        )
        save_audit(
            session,
            competitor.id,
            WebsiteAudit(
                url=competitor.website,
                reachable=True,
                checks={
                    "https": True,
                    "viewport": True,
                    "clear_primary_cta": True,
                    "booking_or_quote_language": True,
                    "tap_to_call": True,
                    "contact_form": True,
                    "service_pages": True,
                    "trust_signals": True,
                    "faq_content": True,
                    "local_schema": True,
                },
                strengths=["Clear request-estimate path.", "Reviews are prominent."],
                weaknesses=["No major weakness captured."],
            ),
        )
        session.add(
            CompetitorRecord(
                lead_id=target.id,
                competitor_place_id=competitor.place_id,
                competitor_name=competitor.name,
                website_url=competitor.website,
                match_score=88,
                reason="Same roofing category and nearby market.",
            )
        )
        session.commit()

        bundle = WebsiteBuilderPromptService(config).build_bundle(session, target)
        paths = WebsiteBuilderPromptService(config).write_bundle(session, target)
        site_folder = StaticSiteService(config).export_site(target, session=session)

    assert "ABC Roofing" in bundle.generic
    assert "Smith Roofing" in bundle.generic
    assert "1 of 1 audited competitors" in bundle.generic
    assert "Do not invent testimonials" in bundle.generic
    assert "Candidate services to verify" in bundle.generic
    assert "Lovable plan mode first" in bundle.lovable
    assert "Canva Website-specific execution" in bundle.canva
    assert all(path.exists() for path in paths.values())
    assert (site_folder / "AI_WEBSITE_BUILDER_PROMPT.md").exists()
    assert (site_folder / "LOVABLE_PROMPT.md").exists()
    assert (site_folder / "CANVA_WEBSITE_PROMPT.md").exists()
    readme = (site_folder / "README_FOR_BUILDER.md").read_text(encoding="utf-8")
    assert "competitor-grounded prompt" in readme
    assert "Smith Roofing" in readme


def test_builder_prompt_does_not_fake_competitors(tmp_path) -> None:
    config = make_config(tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(
            session,
            BusinessProfile(place_id="solo", name="Solo Plumbing", category="plumbers"),
            None,
            ScoreBreakdown(70, "B", [], "Starter Local Presence Build", "", ["No website listed"]),
        )
        session.commit()
        prompt = WebsiteBuilderPromptService(config).build_bundle(session, lead).generic

    assert "Selected competitors with usable local records: 0" in prompt
    assert "do not make competitor superiority claims" in prompt.lower()
    assert "no website listed" in prompt.lower()
