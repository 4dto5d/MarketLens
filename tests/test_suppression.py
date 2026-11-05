from __future__ import annotations

import pytest

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import update_lead_status, upsert_lead
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown
from local_presence_miner.services.suppression_service import SuppressionService


def test_suppression_blocks_approval(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "test.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = upsert_lead(
            session,
            BusinessProfile("p", "Biz", "roofers", phone="555-0101"),
            None,
            ScoreBreakdown(75, "A", [], "Offer", "Angle", []),
        )
        SuppressionService().suppress_lead(session, lead, "test")
        with pytest.raises(ValueError):
            update_lead_status(session, lead.id, LeadStatus.APPROVED_TO_CONTACT)


def test_suppression_matches_discovered_email(tmp_path) -> None:
    from local_presence_miner.database.engine import create_session_factory
    from local_presence_miner.database.migrations import initialize_database
    from local_presence_miner.database.repositories import add_suppression, replace_contact_points
    from local_presence_miner.database.schema import Lead

    factory = create_session_factory(tmp_path / "suppression-email.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = Lead(place_id="email-suppress", name="Email Suppress Test")
        session.add(lead)
        session.flush()
        replace_contact_points(
            session,
            lead.id,
            [
                {
                    "kind": "email",
                    "value": "owner@example.com",
                    "source_type": "official_website",
                    "verified_public": True,
                }
            ],
        )
        session.commit()
        lead_id = lead.id

    with factory() as session:
        add_suppression(session, "owner@example.com", "opt out")
        session.commit()
        lead = session.get(Lead, lead_id)
        assert lead is not None and lead.suppressed is True
