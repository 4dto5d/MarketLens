from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    baseline = Path(sys.argv[1]).resolve()
    database = Path(sys.argv[2]).resolve()
    if database.exists():
        raise RuntimeError(f"Refusing to overwrite fixture: {database}")
    sys.path.insert(0, str(baseline))

    from local_presence_miner.database.engine import create_session_factory
    from local_presence_miner.database.migrations import initialize_database
    from local_presence_miner.database.schema import Lead, LeadSearch, OutreachDraft

    factory = create_session_factory(database)
    initialize_database(factory)
    with factory() as session:
        search = LeadSearch(
            name="Immutable v0.1.12 fixture search",
            city="Peoria",
            state_region="IL",
            niche="roofers",
            criteria_json='{"demo_mode": true}',
            completed=True,
        )
        session.add(search)
        session.flush()
        lead = Lead(
            search_id=search.id,
            place_id="immutable-v0112-place",
            name="Immutable Fixture Roofing",
            category="roofers",
            phone="555-010-1212",
            website="https://fixture.example.com",
            status="Contacted",
            notes="Operator note created in immutable v0.1.12",
            tags="preserve-me",
            owner="Fixture Owner",
            qualification_class="Qualified",
            qualification_json='{"classification": "Qualified"}',
        )
        session.add(lead)
        session.flush()
        session.add(OutreachDraft(
            lead_id=lead.id,
            kind="Cold Email",
            subject="Approved v0.1.12 subject",
            body="EXACT APPROVED V0.1.12 BODY",
            approved=True,
            dependency_state="generated",
            proof_dependencies_json="[]",
        ))
        session.commit()
    factory.kw["bind"].dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
