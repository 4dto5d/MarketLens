from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import (
    LeadSearch,
    SearchMarketQuery,
    SearchMarketRun,
    SearchVisibilityObservation,
    SearchVisibilityProbe,
)
from local_presence_miner.domain.models import (
    BusinessProfile,
    SearchCriteria,
    SearchVisibilityAcquisition,
    VisibilityObservationCapture,
)
from local_presence_miner.domain.niche_taxonomy import resolve_niche
from local_presence_miner.time_utils import utc_now

ACQUISITION_STRATEGY_VERSION = "places-text-v3"
VISIBILITY_CLAIM_MAX_AGE = timedelta(days=30)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class VisibilityClaimAssessment:
    allowed: bool
    reasons: tuple[str, ...]


def demo_visibility_acquisition(
    criteria: SearchCriteria,
    profiles: list[BusinessProfile],
) -> SearchVisibilityAcquisition:
    observed_at = utc_now()
    positioned: list[BusinessProfile] = []
    observations: list[VisibilityObservationCapture] = []
    for position, original in enumerate(profiles, start=1):
        retained_position = original.search_position or position
        profile = replace(original, search_position=retained_position)
        positioned.append(profile)
        observations.append(
            VisibilityObservationCapture(
                source_position=position,
                page_number=1,
                page_position=position,
                place_id=profile.place_id,
                name=profile.name,
                address=profile.address,
                latitude=profile.latitude,
                longitude=profile.longitude,
                retained_position=retained_position,
                disposition="accepted",
            )
        )
    return SearchVisibilityAcquisition(
        source="demo_fixture",
        query_text=f"{criteria.niche} in {criteria.location_label}",
        resolved_latitude=None,
        resolved_longitude=None,
        radius_meters=criteria.radius_meters,
        requested_result_limit=criteria.max_results,
        collection_status="demo",
        truncated=False,
        page_count=1 if profiles else 0,
        raw_result_count=len(observations),
        retained_result_count=len(observations),
        selected_result_count=len(positioned),
        observed_at=observed_at,
        profiles=tuple(positioned),
        observations=tuple(observations),
    )


def failed_visibility_acquisition(
    criteria: SearchCriteria,
    error_summary: str,
) -> SearchVisibilityAcquisition:
    return SearchVisibilityAcquisition(
        source="google_places_text_search",
        query_text=f"{criteria.niche} in {criteria.location_label}",
        resolved_latitude=None,
        resolved_longitude=None,
        radius_meters=criteria.radius_meters,
        requested_result_limit=min(criteria.max_results, 60),
        collection_status="failed",
        truncated=False,
        page_count=0,
        raw_result_count=0,
        retained_result_count=0,
        selected_result_count=0,
        observed_at=utc_now(),
        profiles=(),
        observations=(),
        error_summary=error_summary[:1000],
    )


def visibility_context_fingerprint(
    criteria: SearchCriteria,
    acquisition: SearchVisibilityAcquisition | SearchVisibilityProbe,
) -> str:
    context = {
        "schema": 2,
        "acquisition_strategy_version": ACQUISITION_STRATEGY_VERSION,
        "source": acquisition.source,
        "query_text": acquisition.query_text.strip().casefold(),
        "niche": criteria.niche.strip().casefold(),
        "location_label": criteria.location_label.strip().casefold(),
        "target_zip_code": criteria.target_zip_code.strip().casefold(),
        "resolved_latitude": acquisition.resolved_latitude,
        "resolved_longitude": acquisition.resolved_longitude,
        "radius_meters": acquisition.radius_meters,
        "requested_result_limit": acquisition.requested_result_limit,
    }
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def frozen_search_market_binding(
    session: Session, search_id: int, market_query_id: int
) -> tuple[SearchMarketRun, SearchMarketQuery, SearchCriteria]:
    """Resolve a tracked query back to its frozen run and persisted acquisition criteria."""
    query = session.get(SearchMarketQuery, market_query_id)
    run = session.get(SearchMarketRun, query.run_id) if query is not None else None
    parent = session.get(LeadSearch, search_id)
    if query is None or run is None or parent is None or run.search_id != search_id:
        raise ValueError("Search Market query and search run linkage do not match.")
    try:
        stored = json.loads(parent.criteria_json)
        required = {
            "city", "state_region", "niche", "target_zip_code", "target_radius_miles",
            "radius_meters", "max_results", "demo_mode",
        }
        if not isinstance(stored, dict) or not required.issubset(stored):
            raise ValueError("incomplete criteria")
        frozen = SearchCriteria(**stored)
        niche = resolve_niche(frozen.niche)
        geography = " ".join(part.strip() for part in (frozen.city, frozen.state_region) if part.strip())
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Search Market frozen parent criteria are missing or invalid.") from exc
    if (
        not niche.resolved
        or parent.city != frozen.city
        or parent.state_region != frozen.state_region
        or parent.niche != frozen.niche
        or run.demo_mode != frozen.demo_mode
        or run.canonical_niche_id != niche.canonical_id
        or run.geography != geography
        or query.canonical_niche_id != run.canonical_niche_id
        or query.geography != run.geography
        or query.generation_version != run.query_universe_version
    ):
        raise ValueError("Search Market frozen query, run, and parent context disagree.")
    return run, query, frozen


def search_market_criteria_match(incoming: SearchCriteria, frozen: SearchCriteria) -> bool:
    """Fields that define the Places query and its collected geographic window."""
    fields = (
        "city", "state_region", "niche", "target_zip_code", "target_radius_miles",
        "radius_meters", "max_results", "demo_mode",
    )
    return all(getattr(incoming, field) == getattr(frozen, field) for field in fields)


def search_market_acquisition_context_error(
    frozen: SearchCriteria,
    query: SearchMarketQuery,
    acquisition: SearchVisibilityAcquisition | SearchVisibilityProbe,
) -> str:
    if acquisition.query_text != query.query_text:
        return "Search Market provider query differs from the frozen tracked query."
    if acquisition.radius_meters != frozen.radius_meters:
        return "Search Market acquisition radius differs from the frozen context."
    expected_limit = frozen.max_results if acquisition.collection_status == "demo" else min(frozen.max_results, 60)
    if acquisition.requested_result_limit != expected_limit:
        return "Search Market acquisition result limit differs from the frozen context."
    return ""


def search_market_center_anchor(
    session: Session, search_id: int, query: SearchMarketQuery, frozen: SearchCriteria
) -> tuple[float | None, float | None] | None:
    """Use the first valid complete attempt as a query's resolved-center anchor."""
    source = "demo_fixture" if frozen.demo_mode else "google_places_text_search"
    status = "demo" if frozen.demo_mode else "complete"
    attempts = session.scalars(
        select(SearchVisibilityProbe).where(
            SearchVisibilityProbe.search_id == search_id,
            SearchVisibilityProbe.market_query_id == query.id,
        ).order_by(SearchVisibilityProbe.observed_at, SearchVisibilityProbe.id)
    )
    for prior in attempts:
        if prior.source != source or prior.collection_status != status or prior.truncated:
            continue
        if (
            prior.normalized_niche != frozen.niche.strip().casefold()
            or prior.location_label != frozen.location_label
            or prior.target_zip_code != frozen.target_zip_code.strip()
            or search_market_acquisition_context_error(frozen, query, prior)
            or prior.acquisition_strategy_version != ACQUISITION_STRATEGY_VERSION
            or prior.comparability_fingerprint != visibility_context_fingerprint(frozen, prior)
        ):
            continue
        return prior.resolved_latitude, prior.resolved_longitude
    return None


def persist_visibility_acquisition(
    session: Session,
    search_id: int,
    criteria: SearchCriteria,
    acquisition: SearchVisibilityAcquisition,
    *,
    market_query_id: int | None = None,
) -> SearchVisibilityProbe:
    if acquisition.raw_result_count != len(acquisition.observations):
        raise ValueError("Visibility acquisition count does not match its observation ledger.")
    if acquisition.retained_result_count != sum(
        item.disposition == "accepted" for item in acquisition.observations
    ):
        raise ValueError("Visibility acquisition retained count does not match accepted observations.")
    if market_query_id is not None:
        _, query, frozen = frozen_search_market_binding(session, search_id, market_query_id)
        if not search_market_criteria_match(criteria, frozen):
            raise ValueError("Search Market incoming criteria differ from the frozen parent context.")
        context_error = search_market_acquisition_context_error(frozen, query, acquisition)
        if context_error:
            raise ValueError(context_error)
        anchor = search_market_center_anchor(session, search_id, query, frozen)
        if (
            acquisition.collection_status in {"complete", "demo"}
            and anchor is not None
            and (acquisition.resolved_latitude, acquisition.resolved_longitude) != anchor
        ):
            raise ValueError("Search Market retry resolved center differs from the prior comparable attempt.")

    comparability_fingerprint = visibility_context_fingerprint(criteria, acquisition)
    fingerprint = hashlib.sha256(
        f"{comparability_fingerprint}:{acquisition.attempt_id}".encode()
    ).hexdigest()
    if market_query_id is not None and session.scalars(
        select(SearchVisibilityProbe.id).where(
            SearchVisibilityProbe.search_id == search_id,
            SearchVisibilityProbe.attempt_id == acquisition.attempt_id,
            SearchVisibilityProbe.context_fingerprint != fingerprint,
        )
    ).first() is not None:
        raise ValueError("An acquisition attempt ID cannot be reused for different evidence.")
    existing = session.scalars(
        select(SearchVisibilityProbe).where(
            SearchVisibilityProbe.search_id == search_id,
            SearchVisibilityProbe.context_fingerprint == fingerprint,
        )
    ).one_or_none()
    if existing is not None:
        existing_time = _as_utc(existing.observed_at)
        incoming_time = _as_utc(acquisition.observed_at)
        if (
            existing.collection_status != acquisition.collection_status
            or existing_time != incoming_time
            or existing.raw_result_count != acquisition.raw_result_count
            or existing.retained_result_count != acquisition.retained_result_count
            or existing.selected_result_count != acquisition.selected_result_count
            or existing.page_count != acquisition.page_count
            or existing.truncated != acquisition.truncated
            or existing.error_summary != acquisition.error_summary
            or json.loads(existing.center_resolution_provenance_json or "{}") != acquisition.center_resolution_provenance
            or existing.market_query_id != market_query_id
            or (market_query_id is not None and not _same_market_observations(existing, acquisition))
        ):
            raise ValueError("An acquisition attempt ID cannot be reused for different evidence.")
        return existing

    probe = SearchVisibilityProbe(
        search_id=search_id,
        market_query_id=market_query_id,
        source=acquisition.source,
        query_text=acquisition.query_text,
        normalized_niche=criteria.niche.strip().casefold(),
        location_label=criteria.location_label,
        target_zip_code=criteria.target_zip_code.strip(),
        resolved_latitude=acquisition.resolved_latitude,
        resolved_longitude=acquisition.resolved_longitude,
        radius_meters=acquisition.radius_meters,
        requested_result_limit=acquisition.requested_result_limit,
        collection_status=acquisition.collection_status,
        error_summary=acquisition.error_summary,
        truncated=acquisition.truncated,
        page_count=acquisition.page_count,
        raw_result_count=acquisition.raw_result_count,
        retained_result_count=acquisition.retained_result_count,
        selected_result_count=acquisition.selected_result_count,
        context_fingerprint=fingerprint,
        comparability_fingerprint=comparability_fingerprint,
        attempt_id=acquisition.attempt_id,
        acquisition_strategy_version=ACQUISITION_STRATEGY_VERSION,
        center_resolution_provenance_json=json.dumps(acquisition.center_resolution_provenance, sort_keys=True),
        observed_at=acquisition.observed_at,
        completed_at=utc_now(),
    )
    session.add(probe)
    session.flush()
    for item in acquisition.observations:
        session.add(
            SearchVisibilityObservation(
                probe_id=probe.id,
                source_position=item.source_position,
                page_number=item.page_number,
                page_position=item.page_position,
                place_id=item.place_id,
                place_name=item.name,
                address=item.address,
                latitude=item.latitude,
                longitude=item.longitude,
                retained_position=item.retained_position,
                disposition=item.disposition,
                exclusion_reason=item.exclusion_reason,
                distance_miles=item.distance_miles,
                observed_at=acquisition.observed_at,
            )
        )
    session.flush()
    return probe


def _same_market_observations(
    existing: SearchVisibilityProbe, acquisition: SearchVisibilityAcquisition
) -> bool:
    """An idempotent market retry must replay the exact ordered observation ledger."""
    stored = sorted(existing.observations, key=lambda item: item.source_position)
    incoming = sorted(acquisition.observations, key=lambda item: item.source_position)
    return len(stored) == len(incoming) and all(
        (
            old.source_position, old.page_number, old.page_position, old.place_id,
            old.place_name, old.address, old.latitude, old.longitude,
            old.retained_position, old.disposition, old.exclusion_reason, old.distance_miles,
        ) == (
            new.source_position, new.page_number, new.page_position, new.place_id,
            new.name, new.address, new.latitude, new.longitude,
            new.retained_position, new.disposition, new.exclusion_reason, new.distance_miles,
        )
        for old, new in zip(stored, incoming, strict=True)
    )


def assess_absence_claim(
    earlier: SearchVisibilityProbe,
    later: SearchVisibilityProbe,
    place_id: str,
    *,
    now: datetime | None = None,
) -> VisibilityClaimAssessment:
    """Permit an absence statement only across fresh, complete comparable live captures."""
    reasons: list[str] = []
    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if not place_id:
        reasons.append("missing_place_id")
    if earlier.id == later.id:
        reasons.append("same_attempt")
    if _as_utc(later.observed_at) <= _as_utc(earlier.observed_at):
        reasons.append("not_later_capture")
    for probe in (earlier, later):
        if probe.source != "google_places_text_search" or probe.collection_status != "complete":
            reasons.append("not_complete_live_evidence")
        if probe.truncated:
            reasons.append("truncated_collection")
        if probe.acquisition_strategy_version != ACQUISITION_STRATEGY_VERSION:
            reasons.append("legacy_or_different_strategy")
        age = current - _as_utc(probe.observed_at)
        if not timedelta(0) <= age <= VISIBILITY_CLAIM_MAX_AGE:
            reasons.append("stale_or_future_evidence")
    if not earlier.comparability_fingerprint or earlier.comparability_fingerprint != later.comparability_fingerprint:
        reasons.append("incomparable_context")
    if not any(item.place_id == place_id for item in earlier.observations):
        reasons.append("not_observed_in_prior_capture")
    if any(item.place_id == place_id for item in later.observations):
        reasons.append("still_observed")
    return VisibilityClaimAssessment(not reasons, tuple(dict.fromkeys(reasons)))


def link_visibility_observation(
    session: Session,
    probe_id: int,
    place_id: str,
    *,
    lead_id: int,
    search_run_lead_id: int,
) -> None:
    observation = session.scalars(
        select(SearchVisibilityObservation).where(
            SearchVisibilityObservation.probe_id == probe_id,
            SearchVisibilityObservation.place_id == place_id,
            SearchVisibilityObservation.disposition == "accepted",
        )
    ).first()
    if observation is None:
        return
    observation.lead_id = lead_id
    observation.search_run_lead_id = search_run_lead_id
