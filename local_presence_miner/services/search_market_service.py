from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, replace

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import dumps
from local_presence_miner.database.schema import Lead, LeadSearch, SearchMarketQuery, SearchMarketRun, SearchVisibilityProbe
from local_presence_miner.domain.models import SearchCriteria, SearchVisibilityAcquisition
from local_presence_miner.services.demo_data import load_demo_businesses
from local_presence_miner.services.google_places import GooglePlacesClient, GooglePlacesError
from local_presence_miner.services.preflight_service import PreflightService
from local_presence_miner.services.query_universe_service import QUERY_UNIVERSE_VERSION, TrackedQuery, generate_query_universe
from local_presence_miner.services.search_visibility_service import (
    demo_visibility_acquisition,
    failed_visibility_acquisition,
    persist_visibility_acquisition,
)
from local_presence_miner.services.search_workflow import _single_flight
from local_presence_miner.time_utils import utc_now

Capture = Callable[[TrackedQuery, SearchCriteria], SearchVisibilityAcquisition]
log = logging.getLogger(__name__)
COMMERCIAL_REFRESH_WARNING = "Commercial refresh requires review after this Search Market run."


def _refresh_commercial_after_run(
    session_factory: sessionmaker[Session], run_id: int, prospect_place_id: str, reason: str,
) -> bool:
    """Refresh one lead after acquisition commits; report planner failure separately."""
    from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

    try:
        with session_factory() as session:
            lead = session.scalar(select(Lead).where(Lead.place_id == prospect_place_id))
            if lead is None:
                return False
            recompute_lead_commercial_candidate(session, lead, reason)
            session.commit()
        return False
    except Exception as exc:  # noqa: BLE001 - completed acquisition must retain its own outcome
        log.exception("Commercial refresh failed after Search Market run %s completed", run_id)
        try:
            with session_factory() as session:
                from local_presence_miner.database.repositories import log_activity
                from local_presence_miner.services.commercial_state_service import mark_lead_commercial_stale

                lead = session.scalar(select(Lead).where(Lead.place_id == prospect_place_id))
                run = session.get(SearchMarketRun, run_id)
                if lead is not None:
                    mark_lead_commercial_stale(session, lead, COMMERCIAL_REFRESH_WARNING)
                    log_activity(
                        session, "commercial_refresh_failed",
                        f"Search Market run {run_id}: {exc.__class__.__name__}; commercial review required.", lead.id,
                    )
                if run is not None and COMMERCIAL_REFRESH_WARNING not in run.error_summary:
                    run.error_summary = "\n".join(
                        part for part in (run.error_summary, COMMERCIAL_REFRESH_WARNING) if part
                    )
                session.commit()
        except Exception:  # noqa: BLE001 - retain acquisition identity through a second persistence fault
            log.exception("Could not persist commercial review warning for Search Market run %s", run_id)
        return True


class SearchMarketService:
    """Acquire independent query ledgers, then refresh affected commercial state."""

    def __init__(self, config: AppConfig, session_factory: sessionmaker[Session]) -> None:
        self.config = config
        self.session_factory = session_factory

    def run_for_lead(self, lead_id: int, *, demo_mode: bool = False, query_limit: int = 12) -> int:
        with self.session_factory() as session:
            lead = session.get(Lead, lead_id)
            if lead is None or not lead.place_id:
                raise ValueError("A lead with a canonical Place ID is required for Search Market.")
            parent = session.get(LeadSearch, lead.search_id) if lead.search_id is not None else None
            if parent is None or not parent.city or not parent.state_region:
                raise ValueError("This lead needs a recorded search city/state before Search Market can run.")
            criteria = SearchCriteria(
                city=parent.city,
                state_region=parent.state_region,
                niche=lead.category,
                target_zip_code=lead.target_zip_code,
                target_radius_miles=lead.target_radius_miles,
                radius_meters=round(lead.target_radius_miles * 1609.344),
                max_results=20,
                top_mockups=0,
                demo_mode=demo_mode,
            )
            place_id = lead.place_id
        return self.run(criteria, place_id, query_limit=query_limit)

    def run(
        self,
        criteria: SearchCriteria,
        prospect_place_id: str,
        *,
        query_limit: int = 12,
        capture: Capture | None = None,
    ) -> int:
        prospect_place_id = prospect_place_id.strip()
        if not prospect_place_id:
            raise ValueError("A canonical prospect Place ID is required; unknown identity cannot prove absence.")
        queries = generate_query_universe(
            criteria.niche, criteria.city, criteria.state_region, limit=query_limit
        )
        if not queries:
            raise ValueError("No controlled Search Market queries are available for this niche.")
        if not criteria.demo_mode and capture is None:
            preflight = PreflightService().run(self.config, live_search=True)
            if not preflight.ready:
                detail = "; ".join(f"{item.label}: {item.detail}" for item in preflight.blocking)
                raise RuntimeError("Search Market preflight failed: " + detail)

        with _single_flight(self.session_factory, 60.0) as lease:
            with self.session_factory() as session:
                search = LeadSearch(
                    name=f"Search Market: {criteria.niche} in {criteria.location_label}",
                    city=criteria.city,
                    state_region=criteria.state_region,
                    niche=criteria.niche,
                    criteria_json=dumps(asdict(criteria)),
                    lifecycle_state="Running",
                    started_at=utc_now(),
                )
                session.add(search)
                session.flush()
                lease.bind_search(session, search.id)
                run = SearchMarketRun(
                    search_id=search.id,
                    prospect_place_id=prospect_place_id,
                    canonical_niche_id=queries[0].canonical_niche_id,
                    geography=queries[0].geography,
                    query_universe_version=QUERY_UNIVERSE_VERSION,
                    demo_mode=criteria.demo_mode,
                )
                session.add(run)
                session.flush()
                for ordinal, query in enumerate(queries, start=1):
                    session.add(SearchMarketQuery(run_id=run.id, ordinal=ordinal, **asdict(query)))
                session.commit()
                run_id = run.id
                search_id = search.id

            client = None if criteria.demo_mode or capture is not None else GooglePlacesClient(
                self.config.google_maps_api_key, self.config.request_timeout_seconds
            )
            for query in queries:
                lease.heartbeat()
                try:
                    if capture is not None:
                        acquisition = capture(query, criteria)
                    elif criteria.demo_mode:
                        acquisition = self._demo_capture(criteria, query)
                    else:
                        assert client is not None
                        acquisition = client.search_with_visibility(
                            criteria, query_text_override=query.query_text, enrich=False
                        )
                except GooglePlacesError as exc:
                    acquisition = exc.acquisition or failed_visibility_acquisition(criteria, str(exc))
                    acquisition = replace(acquisition, query_text=query.query_text)
                except SQLAlchemyError:
                    raise
                except Exception as exc:  # noqa: BLE001 - one provider query must not erase other evidence
                    acquisition = replace(
                        failed_visibility_acquisition(criteria, f"{exc.__class__.__name__}: {exc}"),
                        query_text=query.query_text,
                    )
                if acquisition.query_text.strip().casefold() != query.query_text.casefold():
                    acquisition = replace(
                        failed_visibility_acquisition(criteria, "Provider query did not match the tracked query."),
                        query_text=query.query_text,
                    )
                with self.session_factory() as session:
                    query_row = session.scalars(
                        select(SearchMarketQuery).where(
                            SearchMarketQuery.run_id == run_id,
                            SearchMarketQuery.query_id == query.query_id,
                        )
                    ).one()
                    persist_visibility_acquisition(
                        session, search_id, criteria, acquisition, market_query_id=query_row.id
                    )
                    session.commit()

            with self.session_factory() as session:
                stored_run = session.get(SearchMarketRun, run_id)
                stored_search = session.get(LeadSearch, search_id)
                assert stored_run is not None and stored_search is not None
                probes = list(session.scalars(
                    select(SearchVisibilityProbe).where(SearchVisibilityProbe.search_id == search_id)
                ))
                successful = sum(
                    probe.collection_status in {"complete", "demo"} and not probe.truncated
                    for probe in probes
                )
                state = "Completed" if successful == len(queries) else "Partial" if successful else "Failed"
                stored_run.lifecycle_state = state
                stored_run.completed_at = utc_now()
                stored_search.lifecycle_state = state
                stored_search.completed = True
                stored_search.completed_at = stored_run.completed_at
                session.commit()
            if not criteria.demo_mode:
                # A newer partial/failed run can remove earlier current advice.
                _refresh_commercial_after_run(
                    self.session_factory, run_id, prospect_place_id,
                    "Search Market evidence changed commercial planning inputs",
                )
            return run_id

    @staticmethod
    def _demo_capture(criteria: SearchCriteria, query: TrackedQuery) -> SearchVisibilityAcquisition:
        fixtures = load_demo_businesses(criteria)
        # Rotate one omission per query; this is tagged demo evidence, never a live claim.
        omitted = int(query.query_id[:8], 16) % len(fixtures) if fixtures else -1
        selected = [profile for index, profile in enumerate(fixtures) if index != omitted]
        return replace(demo_visibility_acquisition(criteria, selected), query_text=query.query_text)


def reconcile_interrupted_search_market_runs(session_factory: sessionmaker[Session]) -> None:
    """Keep a crashed multi-query run auditable after the shared lease recovers."""
    affected: list[tuple[int, str]] = []
    with session_factory() as session:
        runs = list(session.scalars(
            select(SearchMarketRun).where(SearchMarketRun.lifecycle_state == "Running")
        ))
        for run in runs:
            parent = session.get(LeadSearch, run.search_id)
            if parent is None or parent.lifecycle_state == "Running":
                continue
            observed = session.scalars(
                select(SearchVisibilityProbe).where(SearchVisibilityProbe.search_id == run.search_id)
            ).first() is not None
            run.lifecycle_state = "Partial" if observed else "Failed"
            run.error_summary = "Interrupted before every tracked query completed."
            run.completed_at = utc_now()
            if not run.demo_mode:
                affected.append((run.id, run.prospect_place_id))
        session.commit()
    for run_id, prospect_place_id in affected:
        _refresh_commercial_after_run(
            session_factory, run_id, prospect_place_id,
            "Interrupted Search Market evidence changed commercial planning inputs",
        )
