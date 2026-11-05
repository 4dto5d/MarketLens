from __future__ import annotations

from local_presence_miner.domain.competitor_matching import select_competitors
from local_presence_miner.domain.models import BusinessProfile, WebsiteAudit


def test_selects_three_relevant_competitors_and_avoids_chain() -> None:
    target = BusinessProfile("t", "Local Roof", "roofers", review_count=5, latitude=1, longitude=1)
    candidates = [
        target,
        BusinessProfile("a", "A Roof", "roofers", review_count=40, rating=4.8, latitude=1.01, longitude=1.01),
        BusinessProfile("b", "B Roof", "roofers", review_count=30, rating=4.7, latitude=1.02, longitude=1.02),
        BusinessProfile("c", "C Roof", "roofers", review_count=20, rating=4.6, latitude=1.03, longitude=1.03),
        BusinessProfile("d", "Home Depot", "roofers", review_count=999, rating=4.5, latitude=1, longitude=1),
    ]
    audits = {item.place_id: WebsiteAudit(reachable=True, checks={"https": True}) for item in candidates}
    matches = select_competitors(target, candidates, audits)
    assert [match.place_id for match in matches] == ["a", "b", "c"]
