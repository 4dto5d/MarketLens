from __future__ import annotations

import json
import sys
from pathlib import Path

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.pricing_repository import save_seller_proof
from local_presence_miner.database.repositories import save_outreach_draft
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.enums import LeadStatus, OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import refresh_adaptive_sales_assets


def main() -> int:
    path = Path(sys.argv[1]).resolve()
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite fixture: {path}")
    factory = create_session_factory(path)
    initialize_database(factory)
    sender = SenderInfo(
        name="Fixture Operator",
        business_name="Fixture Studio",
        reply_email="operator@example.com",
        phone="555-010-0100",
        postal_address="123 Fixture Street",
        opt_out_line="Reply opt out.",
    )
    with factory() as session:
        lead = Lead(
            place_id="v0111-immutable-fixture",
            name="Preserved Roofing Fixture",
            category="roofers",
            phone="555-010-1212",
            website="https://fixture.example.com",
            status=LeadStatus.APPROVED_TO_CONTACT.value,
            lead_score=75,
            sales_priority_score=78,
            qualification_class="High Priority",
            qualification_confidence="Moderate",
            qualification_json='{"classification":"High Priority"}',
            verification_json=json.dumps(
                {
                    key: True
                    for key in (
                        "business_identity",
                        "website",
                        "phone",
                        "audit_claims",
                        "competitors",
                        "outreach",
                    )
                }
            ),
        )
        session.add(lead)
        session.flush()
        save_seller_proof(
            session, proof_type="Paid Project", title="Preserved Seller Proof", niche="roofers", verified=True, safe_claims=["A historical claim existed"]
        )
        refresh_adaptive_sales_assets(session, lead, sender)
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Historical subject", "EXACT HISTORICAL APPROVED BODY")
        draft.approved = True  # v0.1.11 had no structured dependency metadata.
        session.commit()
    factory.kw["bind"].dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
