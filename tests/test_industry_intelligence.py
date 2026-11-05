from __future__ import annotations

from local_presence_miner.database.schema import Lead, LeadSearch, WebsiteAuditRecord
from local_presence_miner.ui.widgets.industry_intelligence_widget import build_industry_intelligence


def make_lead(index: int, has_form: bool) -> Lead:
    search = LeadSearch(name="roofers", city="Flint", state_region="MI", niche="roofers")
    lead = Lead(
        place_id=f"industry-{index}",
        name=f"Roofer {index}",
        category="roofers",
        website=f"https://{index}.example",
        lead_score=60 + index,
        review_count=10 * index,
        photo_count=index,
        search_position=index,
        target_signals_json='["No quote path"]',
    )
    lead.search = search
    lead.audit = WebsiteAuditRecord(
        lead_id=index,
        checks_json=f'{{"https": true, "contact_form": {str(has_form).lower()}}}',
        response_time_ms=500 + index,
    )
    return lead


def test_industry_intelligence_uses_denominators() -> None:
    text = build_industry_intelligence([make_lead(1, True), make_lead(2, False), make_lead(3, True)])
    assert "Collected sample: n=3" in text
    assert "Contact form detected: 2 / 3 (66.7%)" in text
    assert "collected sample and denominator" in text


def test_industry_intelligence_avoids_tiny_sample_percentages() -> None:
    text = build_industry_intelligence([make_lead(1, True)])
    assert "too small for percentages" in text
