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
    from local_presence_miner.database.schema import Lead, LeadSearch, SearchRunLead

    factory = create_session_factory(database)
    initialize_database(factory)
    with factory() as session:
        search = LeadSearch(
            name="Immutable v0.1.13 fixture search",
            city="Peoria",
            state_region="IL",
            niche="roofers",
            criteria_json='{"demo_mode": true}',
            completed=True,
            lifecycle_state="Completed",
            total_candidates=1,
            processed_count=1,
            succeeded_count=1,
            new_count=1,
        )
        session.add(search)
        session.flush()
        lead = Lead(
            search_id=search.id,
            place_id="immutable-v0113-place",
            name="Immutable v0.1.13 Roofing",
            category="roofers",
            phone="555-010-1313",
            website="https://v0113-fixture.example.com",
            status="Contacted",
            operator_notes="Operator note from immutable v0.1.13",
            system_notes="System note from immutable v0.1.13",
            notes_provenance="separated",
            notes="Legacy compatibility note",
            tags="preserve-v0113",
            owner="Fixture Owner",
        )
        session.add(lead)
        session.flush()
        session.add(
            SearchRunLead(
                search_id=search.id,
                lead_id=lead.id,
                candidate_place_id=lead.place_id,
                candidate_name=lead.name,
                discovery_order=1,
                search_position=1,
                discovery_kind="new",
                processing_status="Succeeded",
            )
        )
        session.commit()
    factory.kw["bind"].dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
