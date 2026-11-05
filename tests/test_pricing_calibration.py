from __future__ import annotations

from local_presence_miner.database.schema import Lead
from local_presence_miner.services.pricing_calibration import recommend_pricing


def test_project_value_does_not_change_based_on_missing_seller_notes() -> None:
    lead = Lead(
        place_id="p1",
        name="Test Biz",
        category="roofers",
        recommended_offer="Review Trust Builder",
        review_count=4,
        lead_score=80,
    )
    guidance = recommend_pricing(lead)
    assert guidance.offer_name == "Review Trust Builder"
    without_notes = guidance.suggested_range
    lead.past_sales_notes = "Several completed projects"
    assert recommend_pricing(lead).suggested_range == without_notes
    assert any("per posted review" in warning.lower() for warning in guidance.warnings)
    assert all("per posted review" not in item.lower() for item in guidance.rationale)
