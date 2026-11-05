from __future__ import annotations

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.outreach_service import OutreachService


def test_outreach_avoids_unclaimed_claims() -> None:
    lead = Lead(place_id="x", name="Small Roofer", category="roofers")
    lead.target_signals_json = '["No website listed", "Google profile ownership needs manual verification"]'
    lead.recommended_offer = "Starter Local Presence Build"
    drafts = OutreachService(SenderInfo(name="Sam")).generate_all(lead, city="Flint", state_region="MI")
    body = drafts[OutreachKind.INITIAL_EMAIL][1]
    assert "unclaimed" not in body.lower()
    assert "manual verification" in body.lower()
