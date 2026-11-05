from __future__ import annotations

from local_presence_miner.database.schema import Lead
from local_presence_miner.services.owner_brief import build_owner_brief


def test_owner_brief_uses_evidence_and_does_not_invent_business_size() -> None:
    lead = Lead(
        place_id="owner-brief-1",
        name="ABC Roofing",
        category="roofers",
        phone="555-0100",
        google_maps_url="https://maps.example/abc",
        website="",
        lead_score=81,
        recommended_offer="Starter Local Presence Build",
        approach_angle="Ask permission to share the comparison.",
        target_signals_json='["No website listed", "Review growth opportunity"]',
    )

    brief = build_owner_brief(lead, [])

    assert brief.opportunity == "insufficient evidence"
    assert brief.suggested_package == "No paid recommendation"
    assert brief.recommended_ask is None
    assert brief.business_size == "Not available from public Places data"
    assert brief.likely_decision_maker.endswith("verify before outreach")
    assert brief.evidence_confidence < 100
    assert "not a revenue" in brief.confidence_note
