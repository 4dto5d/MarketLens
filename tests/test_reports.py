from __future__ import annotations

import zipfile

from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import upsert_lead
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown
from local_presence_miner.services.comparison_service import ComparisonService
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.mockup_service import MockupService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.static_site_service import StaticSiteService


def test_report_and_mockup_generation(tmp_path) -> None:
    config = AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        log_path=tmp_path / "app.log",
        output_dir=tmp_path,
        google_maps_api_key="google-secret-must-not-export",
        pagespeed_api_key="pagespeed-secret-must-not-export",
    )
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(
            session,
            BusinessProfile("p", "Biz", "roofers", phone="555-0101"),
            None,
            ScoreBreakdown(75, "A", [], "Starter Local Presence Build", "Angle", ["No website listed"]),
        )
        session.commit()
        report = ReportService(config).generate_report(session, lead)
        mockup = MockupService(config).generate_mockup(lead)
        comparison = ComparisonService(config).generate_comparison(session, lead, ai_mode="prompt")
        proposal = ProposalService(config).generate_proposal(session, lead)
        internal_proposal = ProposalService(config).generate_proposal(session, lead, internal=True)
        site_folder = StaticSiteService(config).export_site(lead)
        package = LeadPackageService(config).export_package(session, lead, ai_mode="prompt")
    assert report.exists()
    assert mockup.exists()
    assert comparison.exists()
    assert proposal.exists()
    assert (site_folder / "index.html").exists()
    assert (site_folder / "styles.css").exists()
    assert package.exists()
    assert "Biz" in report.read_text(encoding="utf-8")
    assert "Business Opportunity Analysis" in report.read_text(encoding="utf-8")
    assert "No paid recommendation" in report.read_text(encoding="utf-8")
    assert "Observed Revenue Leaks" not in report.read_text(encoding="utf-8")
    assert "Paste-Ready AI Prompt" in comparison.read_text(encoding="utf-8")
    customer_text = proposal.read_text(encoding="utf-8")
    internal_text = internal_proposal.read_text(encoding="utf-8")
    assert "Private Seller Pricing Intelligence" not in customer_text
    assert "Optional Add-Ons And Pricing Menu" not in customer_text
    assert "Private Seller Pricing Intelligence" in internal_text
    assert "Optional Add-Ons And Pricing Menu" in internal_text
    assert "Ask a question" in (site_folder / "index.html").read_text(encoding="utf-8")
    with zipfile.ZipFile(package) as archive:
        exported_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore") for name in archive.namelist() if name.endswith((".html", ".txt", ".md", ".json", ".css"))
        )
    assert "google-secret-must-not-export" not in exported_text
    assert "pagespeed-secret-must-not-export" not in exported_text
