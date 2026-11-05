from __future__ import annotations

import hashlib
from dataclasses import dataclass

from local_presence_miner.domain.niche_taxonomy import normalize_category, resolve_niche, search_topics_for

QUERY_UNIVERSE_VERSION = "taxonomy-query-v1"
MAX_TRACKED_QUERIES = 24


@dataclass(frozen=True)
class TrackedQuery:
    query_id: str
    query_text: str
    normalized_query: str
    canonical_niche_id: str
    service_topic_id: str
    cluster_id: str
    cluster_name: str
    geography: str
    intent: str
    provenance_rule: str
    commercial_relevance: int
    generation_version: str = QUERY_UNIVERSE_VERSION


def generate_query_universe(niche: str, city: str, state_region: str, *, limit: int = 12) -> tuple[TrackedQuery, ...]:
    """Render a bounded, explainable set of local-intent queries; no cross product."""
    if limit < 1:
        raise ValueError("Query limit must be positive.")
    resolution = resolve_niche(niche)
    if not resolution.resolved:
        raise ValueError("A controlled niche is required before Search Market queries can be generated.")
    geography = " ".join(part.strip() for part in (city, state_region) if part.strip())
    if not geography:
        raise ValueError("Search Market queries require explicit geography.")
    output: list[TrackedQuery] = []
    seen: set[str] = set()
    for topic in search_topics_for(resolution.canonical_id):
        for index, term in enumerate(topic.terms, start=1):
            query_text = f"{term} {geography}"
            normalized = normalize_category(query_text)
            if normalized in seen:
                continue
            seen.add(normalized)
            cluster_id = f"{resolution.canonical_id}:{topic.topic_id}"
            identity = "|".join((QUERY_UNIVERSE_VERSION, resolution.canonical_id, cluster_id, normalized))
            output.append(
                TrackedQuery(
                    query_id=hashlib.sha256(identity.encode()).hexdigest(),
                    query_text=query_text,
                    normalized_query=normalized,
                    canonical_niche_id=resolution.canonical_id,
                    service_topic_id=topic.topic_id,
                    cluster_id=cluster_id,
                    cluster_name=topic.display_name,
                    geography=geography,
                    intent=topic.intent,
                    provenance_rule=f"taxonomy:{resolution.canonical_id}:{topic.topic_id}:term:{index}",
                    commercial_relevance=topic.commercial_relevance,
                )
            )
            if len(output) >= min(limit, MAX_TRACKED_QUERIES):
                return tuple(output)
    return tuple(output)
