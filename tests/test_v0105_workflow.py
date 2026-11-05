from __future__ import annotations

import requests

from local_presence_miner import __version__
from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import list_contact_interactions, save_contact_interaction
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.models import BusinessProfile, SearchCriteria, WebsiteAudit
from local_presence_miner.services.pagespeed import PageSpeedClient
from local_presence_miner.services.rendered_auditor import RenderedAuditResult, rendered_audit_availability
from local_presence_miner.services.search_workflow import SearchWorkflow
from local_presence_miner.services.static_site_service import PRODUCTION_CHECKLIST, build_css, build_index_html
from local_presence_miner.services.website_auditor import USER_AGENT
from local_presence_miner.ui.widgets.pipeline_widget import follow_up_sort_key


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError()

    def json(self):
        return {"lighthouseResult": {"categories": {"performance": {"score": 0.91}}}}


def test_pagespeed_states(monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse())
    result = PageSpeedClient("test-key", resolver=lambda *_: ("93.184.216.34",)).run("https://example.com")
    assert result["pagespeed_status"] == "successful"
    assert result["performance"] == 91

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse(429))
    assert PageSpeedClient("test-key", resolver=lambda *_: ("93.184.216.34",)).run("https://example.com")["pagespeed_status"] == "failed"

    def timeout(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(requests, "get", timeout)
    assert PageSpeedClient("test-key", resolver=lambda *_: ("93.184.216.34",)).run("https://example.com")["pagespeed_status"] == "failed"
    assert "Configuration required" in PageSpeedClient().run("https://example.com")["pagespeed_error"]
    assert PageSpeedClient().run("")["pagespeed_status"] == "unavailable"


def test_search_flags_run_services_and_preserve_states(tmp_path, monkeypatch) -> None:
    config = AppConfig(tmp_path, tmp_path / "db.sqlite3", tmp_path / "app.log", tmp_path, audit_concurrency=2)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    calls = {"raw": 0, "pagespeed": 0, "rendered": 0}

    class Raw:
        def __init__(self, *args):
            pass

        def audit(self, url):
            calls["raw"] += 1
            return WebsiteAudit(url=url, reachable=True, checks={"https": True})

    class Speed:
        def __init__(self, *args):
            pass

        def run(self, url):
            calls["pagespeed"] += 1
            return {"pagespeed_status": "successful", "performance": 88}

    class Rendered:
        def __init__(self, *args):
            pass

        def audit(self, url, screenshot_dir, capture):
            calls["rendered"] += 1
            return RenderedAuditResult(
                status="successful",
                checks={"contact_form": True},
                desktop_screenshot=str(screenshot_dir / "desktop.png"),
                mobile_screenshot=str(screenshot_dir / "mobile.png"),
            )

    monkeypatch.setattr("local_presence_miner.services.search_workflow.WebsiteAuditor", Raw)
    monkeypatch.setattr("local_presence_miner.services.search_workflow.PageSpeedClient", Speed)
    monkeypatch.setattr("local_presence_miner.services.search_workflow.RenderedAuditor", Rendered)
    profiles = [BusinessProfile("one", "One", "roofers", website="https://one.example")]
    criteria = SearchCriteria(
        "Flint",
        "MI",
        "roofers",
        run_pagespeed=True,
        run_rendered_audit=True,
        generate_screenshots=True,
    )
    audits = SearchWorkflow(config, factory)._run_audits(profiles, criteria)
    assert calls == {"raw": 1, "pagespeed": 1, "rendered": 1}
    assert audits["one"].metrics["pagespeed_performance"] == 88
    assert audits["one"].rendered_checks["contact_form"] is True
    assert audits["one"].desktop_screenshot.endswith("desktop.png")


def test_demo_search_consumes_top_mockups_without_network(tmp_path) -> None:
    config = AppConfig(tmp_path, tmp_path / "demo.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    criteria = SearchCriteria("Flint", "MI", "roofers", demo_mode=True, top_mockups=1, output_name="demo-flint")
    SearchWorkflow(config, factory).run(criteria)
    assert len(list((tmp_path / "mockups").glob("*.html"))) == 1


def test_contact_history_persists_and_updates_summary(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "contacts.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = Lead(place_id="contact-1", name="Contact Test")
        session.add(lead)
        session.flush()
        save_contact_interaction(
            session,
            lead.id,
            interaction_datetime="2026-08-10T09:30",
            method="Phone",
            direction="Outbound",
            outcome="Voicemail",
            notes="Left a concise message",
            follow_up_date="2026-08-12",
        )
        lead_id = lead.id
        session.commit()
    with factory() as session:
        interactions = list_contact_interactions(session, lead_id)
        lead = session.get(Lead, lead_id)
        assert len(interactions) == 1
        assert lead.last_contacted_date == "2026-08-10"
        assert lead.next_follow_up_date == "2026-08-12"


def test_pipeline_order_prioritizes_overdue_then_due_then_future() -> None:
    leads = [
        Lead(place_id="future", name="Future", next_follow_up_date="2099-01-01", lead_score=90),
        Lead(place_id="overdue", name="Overdue", next_follow_up_date="2020-01-01", lead_score=20),
    ]
    assert [lead.name for lead in sorted(leads, key=follow_up_sort_key)] == ["Overdue", "Future"]


def test_static_export_is_truthful_and_chat_closed() -> None:
    lead = Lead(place_id="site-1", name="Concept Co", category="roofers")
    html = build_index_html(lead, ["Roof repair"], ["No quote form detected"])
    assert 'id="chat-panel"' in html and "hidden" in html
    assert 'aria-expanded="false"' in html
    assert "non-submitting form markup" in html
    assert "CONCEPT SITE" in html
    assert ".chat-panel[hidden] { display: none; }" in build_css()
    assert "Form destination" in PRODUCTION_CHECKLIST


def test_user_agent_uses_application_version() -> None:
    assert USER_AGENT.startswith(f"MarketLensLocal/{__version__}")
    assert __version__ == "0.1.16"


def test_rendered_audit_reports_unavailable_browser(monkeypatch) -> None:
    monkeypatch.setattr("local_presence_miner.services.rendered_auditor.edge_paths", lambda: [])
    available, explanation = rendered_audit_availability()
    assert available is False
    assert "browser subresources" in explanation and "DNS destinations" in explanation
