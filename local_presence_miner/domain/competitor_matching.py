from __future__ import annotations

import math
import re

from local_presence_miner.domain.models import BusinessProfile, CompetitorMatch, WebsiteAudit
from local_presence_miner.domain.niche_taxonomy import niche_relation
from local_presence_miner.domain.scoring import website_evidence_state, website_quality_score

CHAIN_HINTS = {
    "walmart",
    "home depot",
    "lowe",
    "mcdonald",
    "starbucks",
    "subway",
    "taco bell",
    "wendy",
    "burger king",
    "costco",
}

MIN_CREDIBLE_RELEVANCE = 45


def select_competitors(
    target: BusinessProfile,
    candidates: list[BusinessProfile],
    audits: dict[str, WebsiteAudit],
    max_competitors: int = 3,
) -> list[CompetitorMatch]:
    """Select only credible local competitors.

    Relevance answers "is this actually a comparable business?" and is kept
    separate from aspirational strength such as website quality/review volume.
    A strong-but-irrelevant business should never outrank a real competitor.
    """
    target_chain = is_likely_chain(target.name)
    ranked: list[tuple[int, int, int, CompetitorMatch]] = []
    for candidate in candidates:
        if candidate.place_id == target.place_id:
            continue
        candidate_chain = is_likely_chain(candidate.name)
        if candidate_chain != target_chain:
            continue

        relevance, reasons, disqualifiers = competitor_relevance(target, candidate)
        if disqualifiers or relevance < MIN_CREDIBLE_RELEVANCE:
            continue
        strength = competitor_strength(candidate, audits.get(candidate.place_id, WebsiteAudit()))
        quality = match_quality(relevance)
        distance = competitor_distance_miles(target, candidate)
        reason = (
            f"Match Quality: {quality}; relevance {relevance}/100. "
            + "; ".join(reasons)
            + f". Competitor strength {strength}/100 is reported separately and does not raise relevance."
        )
        match = CompetitorMatch(candidate.place_id, candidate.name, relevance, reason)
        quality_rank = {"Strong": 3, "Moderate": 2, "Weak": 1}[quality]
        distance_sort = int(round((distance if distance is not None else 999) * 100))
        ranked.append((quality_rank, relevance, strength, match if distance_sort >= 0 else match))

    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3].name.casefold()))
    return [item[3] for item in ranked[:max_competitors]]


def competitor_relevance(target: BusinessProfile, candidate: BusinessProfile) -> tuple[int, list[str], list[str]]:
    reasons: list[str] = []
    disqualifiers: list[str] = []
    score = 0

    target_types = normalized_types(target)
    candidate_types = normalized_types(candidate)
    exact_primary = bool(target.primary_type and candidate.primary_type and target.primary_type == candidate.primary_type)
    type_overlap = target_types & candidate_types
    if exact_primary:
        score += 45
        reasons.append(f"same primary Google type ({target.primary_type})")
    elif type_overlap:
        score += 38
        reasons.append("overlapping public Google business types")
    elif not target_types or not candidate_types:
        if category_token_overlap(target.category, candidate.category):
            score += 24
            reasons.append("category fallback overlap because richer Google type data is unavailable")
        else:
            score += 6
            reasons.append("limited category evidence")
    else:
        disqualifiers.append("public Google types do not overlap")

    service_overlap = service_token_overlap(target, candidate)
    score += min(15, service_overlap * 5)
    if service_overlap:
        reasons.append(f"{service_overlap} service/category token overlap(s)")

    miles = competitor_distance_miles(target, candidate)
    if miles is None:
        score += 5
        reasons.append("distance unknown")
    elif miles <= 5:
        score += 20
        reasons.append(f"{miles:.1f} miles away")
    elif miles <= 10:
        score += 16
        reasons.append(f"{miles:.1f} miles away")
    elif miles <= 20:
        score += 10
        reasons.append(f"{miles:.1f} miles away")
    elif miles <= 35:
        score += 4
        reasons.append(f"{miles:.1f} miles away")
    else:
        disqualifiers.append(f"too far away for a local comparison ({miles:.1f} miles)")

    if target.google_details_retrieved and candidate.google_details_retrieved:
        scale = scale_similarity_points(target.review_count, candidate.review_count)
        score += scale
        reasons.append(f"local-scale similarity {scale}/15 from public review-volume band")
    else:
        score += 6
        reasons.append("business-scale comparison unavailable at current Google data depth")

    if is_likely_chain(target.name) == is_likely_chain(candidate.name):
        score += 5
    return max(0, min(100, score)), reasons, disqualifiers


def competitor_strength(candidate: BusinessProfile, audit: WebsiteAudit) -> int:
    """Aspirational strength is intentionally separate from relevance."""
    score = 0
    if candidate.google_details_retrieved:
        if candidate.rating is not None:
            score += max(0, min(25, round((candidate.rating - 3.0) / 2.0 * 25)))
        if candidate.review_count >= 100:
            score += 25
        elif candidate.review_count >= 40:
            score += 20
        elif candidate.review_count >= 15:
            score += 14
        elif candidate.review_count > 0:
            score += 7
    if not candidate.website or website_evidence_state(audit) != "unknown":
        score += min(50, website_quality_score(audit, bool(candidate.website)) // 2)
    return max(0, min(100, score))


def match_quality(relevance: int) -> str:
    if relevance >= 75:
        return "Strong"
    if relevance >= 55:
        return "Moderate"
    return "Weak"


def normalized_types(profile: BusinessProfile) -> set[str]:
    values = {profile.primary_type, *profile.business_types}
    return {normalize_token(value) for value in values if normalize_token(value)}


def category_token_overlap(a: str, b: str) -> bool:
    return niche_relation(a, b) in {"same", "related"}


def service_token_overlap(a: BusinessProfile, b: BusinessProfile) -> int:
    a_tokens = tokenize(" ".join([a.category, a.primary_type, *a.business_types]))
    b_tokens = tokenize(" ".join([b.category, b.primary_type, *b.business_types]))
    return len(a_tokens & b_tokens)


def tokenize(value: str) -> set[str]:
    stop = {"service", "services", "company", "contractor", "business", "local", "the", "and"}
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold().replace("_", " ")) if len(token) >= 4 and token not in stop}


def normalize_token(value: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", (value or "").casefold().replace("-", "_")))


def scale_similarity_points(target_reviews: int, candidate_reviews: int) -> int:
    if target_reviews <= 0 or candidate_reviews <= 0:
        return 6
    ratio = max(target_reviews, candidate_reviews) / max(1, min(target_reviews, candidate_reviews))
    if ratio <= 2:
        return 15
    if ratio <= 4:
        return 11
    if ratio <= 8:
        return 7
    if ratio <= 15:
        return 3
    return 0


def is_likely_chain(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in CHAIN_HINTS)


def competitor_distance_miles(a: BusinessProfile, b: BusinessProfile) -> float | None:
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return None
    return haversine_miles(float(a.latitude), float(a.longitude), float(b.latitude), float(b.longitude))


def distance_bonus(a: BusinessProfile, b: BusinessProfile) -> int:
    """Backward-compatible helper retained for callers/tests; relevance uses richer distance bands."""
    miles = competitor_distance_miles(a, b)
    if miles is None:
        return 5
    if miles <= 5:
        return 10
    if miles <= 15:
        return 5
    return 0


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h))
