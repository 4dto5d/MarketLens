import pytest
from test_seo_research_integration import business, sample_payload
from test_seo_research_integration import storage as storage_fixture

from local_presence_miner.services.commercial_triage_service import commercial_triage_overlay
from local_presence_miner.services.seo_research_service import append_research


@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    return storage_fixture.__wrapped__(tmp_path)


def test_legacy_high_priority_does_not_turn_no_sale_into_opportunity(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        lead.sales_priority_score = lead.lead_score = 100
        before = lead.qualification_class
        overlay = commercial_triage_overlay(session, lead)
        assert overlay["state"] == "no_sale"
        assert overlay["label"] == "No paid recommendation"
        assert lead.qualification_class == before
        assert overlay["contact_authorization"] is False


def test_low_legacy_priority_can_show_supported_scoped_review(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        lead.sales_priority_score = 0
        append_research(session, lead, sample_payload(session, lead))
        overlay = commercial_triage_overlay(session, lead)
        assert overlay["state"] == "recommended"
        assert overlay["contact_authorization"] is False
        assert lead.sales_priority_score == 0
