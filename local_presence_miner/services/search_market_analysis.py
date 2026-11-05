from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from local_presence_miner.database.schema import (
    SearchMarketQuery,
    SearchMarketRun,
    SearchVisibilityObservation,
    SearchVisibilityProbe,
)
from local_presence_miner.services.search_visibility_service import (
    ACQUISITION_STRATEGY_VERSION,
    frozen_search_market_binding,
    search_market_acquisition_context_error,
    search_market_center_anchor,
    visibility_context_fingerprint,
)
from local_presence_miner.time_utils import utc_now

MARKET_EVIDENCE_MAX_AGE = timedelta(days=30)


@dataclass(frozen=True)
class QueryCoverage:
    query_id: str
    query_text: str
    cluster_id: str
    cluster_name: str
    commercial_relevance: int
    state: str  # present | absent | excluded | unknown
    reason: str
    probe_id: int | None
    attempt_count: int
    collection_status: str
    source_position: int | None
    retained_position: int | None
    observed_at: str
    competitor_place_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClusterCoverage:
    cluster_id: str
    cluster_name: str
    tracked: int
    observed: int
    present: int
    absent: int
    excluded: int
    unknown: int
    denominator: int
    coverage_percent: float | None


@dataclass(frozen=True)
class CompetitorCapture:
    query_id: str
    query_text: str
    cluster_id: str
    source_position: int
    prospect_state: str


@dataclass(frozen=True)
class SearchCompetitor:
    place_id: str
    name: str
    appearance_queries: int
    gap_capture_queries: int
    top10_gap_queries: int
    weighted_gap_relevance: int
    cluster_count: int
    evidence: tuple[CompetitorCapture, ...]
    why: str


@dataclass(frozen=True)
class SearchMarketGap:
    kind: str
    scope: str
    fact: str
    interpretation: str


@dataclass(frozen=True)
class SearchMarketProjection:
    run_id: int
    prospect_place_id: str
    evidence_mode: str  # live | demo
    tracked_queries: int
    observed_queries: int
    unknown_queries: int
    excluded_queries: int
    present_queries: int
    absent_queries: int
    coverage_denominator: int
    coverage_percent: float | None
    strongest_cluster: str | None
    weakest_cluster: str | None
    queries: tuple[QueryCoverage, ...]
    clusters: tuple[ClusterCoverage, ...]
    top_search_competitors: tuple[SearchCompetitor, ...]
    gaps: tuple[SearchMarketGap, ...]
    limitations: tuple[str, ...]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _probe_eligibility(
    session: Session,
    run: SearchMarketRun,
    query: SearchMarketQuery,
    probe: SearchVisibilityProbe | None,
    *,
    now: datetime,
) -> str:
    if probe is None:
        return "unexecuted query"
    if query.run_id != run.id or probe.search_id != run.search_id or probe.market_query_id != query.id:
        return "Search Market probe, query, and run linkage do not match."
    try:
        _, _, frozen = frozen_search_market_binding(session, run.search_id, query.id)
    except ValueError as exc:
        return str(exc)
    if (
        probe.normalized_niche != frozen.niche.strip().casefold()
        or probe.location_label != frozen.location_label
        or probe.target_zip_code != frozen.target_zip_code.strip()
    ):
        return "Search Market probe niche, geography, or ZIP context differs from the frozen parent."
    context_error = search_market_acquisition_context_error(frozen, query, probe)
    if context_error:
        return context_error
    expected_fingerprint = visibility_context_fingerprint(frozen, probe)
    if (
        probe.comparability_fingerprint != expected_fingerprint
        or probe.context_fingerprint != hashlib.sha256(
            f"{expected_fingerprint}:{probe.attempt_id}".encode()
        ).hexdigest()
    ):
        return "Search Market probe comparability or attempt context fingerprint differs from the frozen parent."
    anchor = search_market_center_anchor(session, run.search_id, query, frozen)
    if anchor is not None and (probe.resolved_latitude, probe.resolved_longitude) != anchor:
        return "Search Market probe resolved-center context differs from the prior comparable attempt."
    source = "demo_fixture" if run.demo_mode else "google_places_text_search"
    status = "demo" if run.demo_mode else "complete"
    if probe.source != source or probe.collection_status != status:
        return "failed, partial, or different-source acquisition"
    if probe.truncated:
        return "truncated collected window"
    if probe.acquisition_strategy_version != ACQUISITION_STRATEGY_VERSION:
        return "legacy or different acquisition strategy"
    age = now - _utc(probe.observed_at)
    if not timedelta(0) <= age <= MARKET_EVIDENCE_MAX_AGE:
        return "stale or future-dated capture"
    if probe.raw_result_count != len(probe.observations):
        return "observation count mismatch"
    return ""


def project_search_market(
    session: Session,
    run_id: int,
    *,
    now: datetime | None = None,
) -> SearchMarketProjection:
    """Pure read model over frozen query definitions and append-only probe evidence.

    Denominator = present + absent on fresh complete nontruncated query windows.
    Failed, partial, truncated, stale, unexecuted, and provider-excluded target
    observations are not treated as absence and do not enter that denominator.
    """
    run = session.get(SearchMarketRun, run_id)
    if run is None:
        raise ValueError(f"Search Market run {run_id} was not found.")
    current = _utc(now or utc_now())
    query_rows = list(session.scalars(
        select(SearchMarketQuery)
        .where(SearchMarketQuery.run_id == run_id)
        .options(selectinload(SearchMarketQuery.probes).selectinload(SearchVisibilityProbe.observations))
        .order_by(SearchMarketQuery.ordinal)
    ))
    evidence: list[QueryCoverage] = []
    competitor_captures: dict[str, list[CompetitorCapture]] = {}
    competitor_names: dict[str, str] = {}
    relevance_by_query = {query.query_id: query.commercial_relevance for query in query_rows}
    for query in query_rows:
        attempts = sorted(query.probes, key=lambda item: (_utc(item.observed_at), item.id))
        probe = attempts[-1] if attempts else None
        ineligible = _probe_eligibility(session, run, query, probe, now=current)
        if probe is None or ineligible:
            evidence.append(QueryCoverage(
                query.query_id, query.query_text, query.cluster_id, query.cluster_name,
                query.commercial_relevance, "unknown", ineligible, probe.id if probe else None,
                len(attempts), probe.collection_status if probe else "unexecuted", None, None,
                probe.observed_at.isoformat() if probe else "", (),
            ))
            continue
        matching = [item for item in probe.observations if item.place_id == run.prospect_place_id]
        accepted = next((item for item in matching if item.disposition == "accepted"), None)
        if accepted:
            state, reason = "present", "Prospect returned within this complete collected in-radius window."
        elif matching:
            state, reason = "excluded", "Provider returned the prospect, but it was excluded from the retained local window."
        else:
            state, reason = "absent", "Prospect was not returned within this complete collected query window."
        query_competitors: dict[str, SearchVisibilityObservation] = {}
        for item in probe.observations:
            if item.disposition != "accepted" or not item.place_id or item.place_id == run.prospect_place_id:
                continue
            prior = query_competitors.get(item.place_id)
            if prior is None or item.source_position < prior.source_position:
                query_competitors[item.place_id] = item
        for place_id, item in query_competitors.items():
            competitor_names.setdefault(place_id, item.place_name or place_id)
            competitor_captures.setdefault(place_id, []).append(CompetitorCapture(
                query.query_id, query.query_text, query.cluster_id, item.source_position, state
            ))
        evidence.append(QueryCoverage(
            query.query_id, query.query_text, query.cluster_id, query.cluster_name,
            query.commercial_relevance, state, reason, probe.id, len(attempts),
            probe.collection_status, accepted.source_position if accepted else None,
            accepted.retained_position if accepted else None, probe.observed_at.isoformat(),
            tuple(sorted(query_competitors)),
        ))

    cluster_ids = dict.fromkeys(item.cluster_id for item in evidence)
    clusters: list[ClusterCoverage] = []
    for cluster_id in cluster_ids:
        members = [item for item in evidence if item.cluster_id == cluster_id]
        present = sum(item.state == "present" for item in members)
        absent = sum(item.state == "absent" for item in members)
        denominator = present + absent
        clusters.append(ClusterCoverage(
            cluster_id, members[0].cluster_name, len(members),
            sum(item.state != "unknown" for item in members), present, absent,
            sum(item.state == "excluded" for item in members),
            sum(item.state == "unknown" for item in members), denominator,
            round(100 * present / denominator, 1) if denominator else None,
        ))
    comparable_clusters = [item for item in clusters if item.coverage_percent is not None]
    strongest = max(comparable_clusters, key=lambda item: (item.coverage_percent or 0, item.denominator, item.cluster_id)) if comparable_clusters else None
    weakest = min(comparable_clusters, key=lambda item: (item.coverage_percent or 0, -item.denominator, item.cluster_id)) if comparable_clusters else None

    search_competitors: list[SearchCompetitor] = []
    for place_id, captures in competitor_captures.items():
        gaps = [item for item in captures if item.prospect_state == "absent"]
        if len(gaps) < 2:
            continue  # One appearance is not repeated search capture.
        weighted = sum(relevance_by_query[item.query_id] for item in gaps)
        top10 = sum(item.source_position <= 10 for item in gaps)
        clusters_captured = len({item.cluster_id for item in gaps})
        search_competitors.append(SearchCompetitor(
            place_id, competitor_names[place_id], len(captures), len(gaps), top10,
            weighted, clusters_captured, tuple(captures),
            f"Returned in {len(gaps)} complete tracked queries where the prospect was not returned; "
            f"source position 1–10 in {top10}; across {clusters_captured} cluster(s).",
        ))
    search_competitors.sort(key=lambda item: (
        -item.gap_capture_queries, -item.weighted_gap_relevance,
        -item.top10_gap_queries, -item.appearance_queries, -item.cluster_count, item.place_id,
    ))
    gap_insights: list[SearchMarketGap] = []
    for coverage_item in evidence:
        if coverage_item.state == "absent" and len(coverage_item.competitor_place_ids) >= 2:
            gap_insights.append(SearchMarketGap(
                "multi_competitor_query", coverage_item.query_text,
                f"Prospect was not returned in this complete collected window; "
                f"{len(coverage_item.competitor_place_ids)} other Place IDs were retained.",
                "This tracked query has an observed search-capture gap; it does not establish exact Maps rank.",
            ))
    for cluster in clusters:
        if cluster.denominator >= 2 and cluster.absent >= 2 and cluster.coverage_percent is not None and cluster.coverage_percent < 50:
            gap_insights.append(SearchMarketGap(
                "weak_cluster", cluster.cluster_name,
                f"Prospect returned in {cluster.present} of {cluster.denominator} eligible "
                f"{cluster.cluster_name} queries; {cluster.unknown} were UNKNOWN and {cluster.excluded} excluded.",
                "Observed coverage is weak within this tracked service cluster, not across all Google searches.",
            ))
        cluster_absent = {item.query_id for item in evidence if item.cluster_id == cluster.cluster_id and item.state == "absent"}
        if len(cluster_absent) < 2:
            continue
        for competitor in search_competitors:
            captured = sum(item.query_id in cluster_absent for item in competitor.evidence)
            if captured >= 2 and captured == len(cluster_absent):
                gap_insights.append(SearchMarketGap(
                    "recurring_cluster_competitor", cluster.cluster_name,
                    f"{competitor.name} ({competitor.place_id}) was retained in {captured} of "
                    f"{len(cluster_absent)} eligible {cluster.cluster_name} queries where the prospect was absent.",
                    "This business repeatedly captured the sampled cluster gaps; provider cause is unknown.",
                ))
    present_total = sum(item.state == "present" for item in evidence)
    absent_total = sum(item.state == "absent" for item in evidence)
    denominator_total = present_total + absent_total
    return SearchMarketProjection(
        run.id, run.prospect_place_id, "demo" if run.demo_mode else "live", len(evidence),
        sum(item.state != "unknown" for item in evidence),
        sum(item.state == "unknown" for item in evidence),
        sum(item.state == "excluded" for item in evidence),
        present_total, absent_total, denominator_total,
        round(100 * present_total / denominator_total, 1) if denominator_total else None,
        strongest.cluster_name if strongest else None,
        weakest.cluster_name if weakest else None,
        tuple(evidence), tuple(clusters), tuple(search_competitors[:3]), tuple(gap_insights),
        (
            "Demo fixtures are not live public evidence." if run.demo_mode else
            "Google Places Text Search order is a collected-window proxy, not exact Maps or Local Pack rank.",
            "Coverage describes only the controlled tracked queries, not search demand or market share.",
            "UNKNOWN and provider-excluded target rows are omitted from the coverage denominator.",
        ),
    )
