from __future__ import annotations

from local_presence_miner.domain.models import BusinessProfile, WebsiteAudit
from local_presence_miner.domain.scoring import score_lead, website_quality_score


def test_no_website_low_reviews_and_low_position_scores_high() -> None:
    business = BusinessProfile(
        place_id="x",
        name="Small Roofer",
        category="roofers",
        review_count=6,
        photo_count=1,
        has_hours=False,
        search_position=21,
    )
    score = score_lead(business, WebsiteAudit(), competitor_average_website_score=80)
    assert 0 <= score.total <= 100
    assert score.priority == "A"
    assert "No website listed" in score.target_signals
    assert "Review growth opportunity" in score.target_signals


def test_strong_site_does_not_get_high_score_for_low_rating_alone() -> None:
    checks = {
        key: True
        for key in [
            "https",
            "viewport",
            "has_title",
            "has_meta_description",
            "has_h1",
            "tap_to_call",
            "contact_form",
            "booking_or_quote_language",
            "service_pages",
            "trust_signals",
            "map_embed",
            "local_schema",
            "social_links",
            "clear_primary_cta",
            "local_wording",
        ]
    }
    business = BusinessProfile(
        place_id="x",
        name="Strong But Low Rating",
        category="roofers",
        website="https://example.com",
        rating=2.4,
        review_count=80,
        photo_count=20,
        has_hours=True,
        profile_verification_required=False,
    )
    audit = WebsiteAudit(url=business.website, reachable=True, checks=checks)
    assert website_quality_score(audit, True) == 100
    assert score_lead(business, audit).total < 25
