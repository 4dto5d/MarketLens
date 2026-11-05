"""Pure, conservative SEO evidence normalization and intervention reasoning.

This module does not fetch data, estimate local demand from country volumes,
infer Google ranks from Places, price work, or promise ranking/lead effects.
Inputs are independent timestamped research snapshots, not model-generated facts.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from local_presence_miner.domain.evidence_geography import coverage_footprint, coverage_identity, coverage_label, legacy_city_coverage, validate_coverage
from local_presence_miner.domain.website_evidence import classify_page_facts

SEO_INTELLIGENCE_VERSION = 3
MAX_AGE_DAYS = 30
MAX_FUTURE_SKEW_SECONDS = 0
MAX_QUERIES = 500
MAX_PAGES = 100

SERVICE_STATES = {"confirmed", "likely", "possible_expansion", "unsupported", "unknown"}
INTENTS = {"transactional", "local_commercial", "service_discovery", "comparison", "informational", "navigational", "curiosity", "unknown"}
COMMERCIAL_INTENTS = {"transactional", "local_commercial", "service_discovery"}
QUERY_FIELDS = {"query", "service", "service_state", "service_refs", "intent", "intent_basis", "volume", "difficulty", "organic_rank", "maps_rank",
                "organic_window", "maps_window", "organic_complete", "maps_complete", "page_url", "competitors", "serp_features", "refs",
                "volume_geo_resolution", "volume_geography", "volume_reference"}
PAGE_FIELDS = {"url", "title", "h1", "meta_description", "canonical", "robots", "status_code", "indexability", "word_count", "internal_links",
               "schema_types", "schema_errors", "services", "service_refs", "observed_at", "source_ref"}
_LOW_INTENT = re.compile(r"\b(how to|diy|do it yourself|salary|salaries|jobs|careers|definition|what is|why does|history of|meme|joke|tutorial)\b")


def _object(value: object, name: str, allowed: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    if allowed is not None and set(value) - allowed:
        raise ValueError(f"{name} has unsupported fields: {', '.join(sorted(set(value) - allowed))}")
    return value


def _text(value: object, name: str, *, required: bool = False, limit: int = 2000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if len(value) > limit or any(ord(char) < 32 and char not in "\t\r\n" for char in value):
        raise ValueError(f"{name} contains invalid or oversized text")
    result = " ".join(value.split())
    if required and not result:
        raise ValueError(f"{name} is required")
    return result


def _enum(value: object, name: str, options: set[str]) -> str:
    result = _text(value, name, required=True)
    if result not in options:
        raise ValueError(f"{name} has an unsupported value")
    return result


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _number(value: object, name: str, *, integer: bool = False, minimum: float = 0, maximum: float = 1_000_000_000) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a finite number or null")
    if value < minimum or value > maximum or (integer and (type(value) is not int)):
        raise ValueError(f"{name} is outside its valid range")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number or null")
    return value


def _list(value: object, name: str, limit: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{name} must be a bounded list")
    return value


def _texts(value: object, name: str, *, limit: int = 100, item_limit: int = 2000) -> list[str]:
    return list(dict.fromkeys(_text(item, name, required=True, limit=item_limit) for item in _list(value, name, limit)))


def _reference(value: object, name: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    _text(value, name, required=required)
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} cannot contain control characters")
    return value


def _refs(value: object, name: str) -> list[str]:
    return list(dict.fromkeys(_reference(item, name) for item in _list(value, name, 100)))


def _url(value: object, name: str, *, required: bool = False) -> str:
    result = _text(value, name, required=required, limit=4096)
    if not result:
        return ""
    try:
        parts = urlsplit(result)
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid URL") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password or " " in result:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL without credentials")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{port}" if port and not (parts.scheme.lower() == "https" and port == 443 or parts.scheme.lower() == "http" and port == 80) else "")
    return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), parts.query, ""))


def _site(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _same_site(url: str, website: str, name: str) -> None:
    if url and _site(url) != _site(website):
        raise ValueError(f"{name} does not match the subject website")


def _instant(value: object, name: str) -> datetime:
    text = _text(value, name, required=True, limit=100)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return result.astimezone(UTC)


def _query(value: object, website: str, source: dict, schema_version: int = 1) -> dict:
    q = _object(value, "query", QUERY_FIELDS | ({"coverage", "volume_coverage"} if schema_version == 2 else set()))
    result: dict[str, Any] = {
        "query": _text(q.get("query"), "query.query", required=True, limit=500),
        "service": _text(q.get("service", ""), "query.service", limit=200),
        "service_state": _enum(q.get("service_state", "unknown"), "query.service_state", SERVICE_STATES),
        "service_refs": _refs(q.get("service_refs", []), "query.service_refs"),
        "intent": _enum(q.get("intent", "unknown"), "query.intent", INTENTS),
        "intent_basis": _text(q.get("intent_basis", ""), "query.intent_basis"),
        "volume": _number(q.get("volume"), "query.volume"),
        "volume_geo_resolution": _enum(q.get("volume_geo_resolution", source["geo_resolution"]), "query.volume_geo_resolution", {"local", "country"}),
        "volume_geography": _text(q.get("volume_geography", source["geography"]), "query.volume_geography", required=True, limit=500),
        "volume_reference": _reference(q.get("volume_reference", source["reference"]), "query.volume_reference"),
        "difficulty": _number(q.get("difficulty"), "query.difficulty", maximum=100),
        "page_url": _url(q.get("page_url", ""), "query.page_url"),
        "serp_features": _texts(q.get("serp_features", []), "query.serp_features", item_limit=100),
        "refs": _refs(q.get("refs", []), "query.refs"),
        "competitors": [],
    }
    _same_site(result["page_url"], website, "query.page_url")
    if schema_version == 2:
        result["coverage"] = validate_coverage(q.get("coverage", source["coverage"]))
        # Volume has its own provenance. A city estimate cannot silently become
        # ZIP demand even when a SERP was sampled in the selected postal area.
        result["volume_coverage"] = validate_coverage(q.get("volume_coverage", source["coverage"]))
        if any(result["coverage"][key] != source["coverage"][key] for key in ("country", "state")):
            raise ValueError("Query observation country/state does not match the source")
    if result["volume_geo_resolution"] == "local" and result["volume_geography"].casefold() != source["geography"].casefold():
        raise ValueError("query local volume geography does not match the source geography")
    if source["geo_resolution"] == "country" and result["volume_geo_resolution"] == "local":
        raise ValueError("country source cannot independently establish local query volume")
    for channel in ("organic", "maps"):
        rank = _number(q.get(f"{channel}_rank"), f"query.{channel}_rank", integer=True, minimum=1, maximum=1000)
        window = _number(q.get(f"{channel}_window"), f"query.{channel}_window", integer=True, minimum=1, maximum=1000)
        complete = _bool(q.get(f"{channel}_complete", False), f"query.{channel}_complete")
        if complete and window is None:
            raise ValueError(f"query.{channel}_complete requires an observed window")
        if rank is not None and window is not None and rank > window:
            raise ValueError(f"query.{channel}_rank exceeds its observed window")
        result.update({f"{channel}_rank": rank, f"{channel}_window": window, f"{channel}_complete": complete})
    seen = set()
    positions = set()
    for value in _list(q.get("competitors", []), "query.competitors", 100):
        competitor = _object(value, "competitor", {"url", "channel", "position", "kind", "authority", "referring_domains"})
        row: dict[str, Any] = {"url": _url(competitor.get("url"), "competitor.url", required=True),
               "channel": _enum(competitor.get("channel"), "competitor.channel", {"organic", "maps"}),
               "position": _number(competitor.get("position"), "competitor.position", integer=True, minimum=1, maximum=1000),
               "kind": _enum(competitor.get("kind"), "competitor.kind", {"local_business", "directory", "aggregator", "national_brand"}),
               "authority": _number(competitor.get("authority"), "competitor.authority", maximum=100),
               "referring_domains": _number(competitor.get("referring_domains"), "competitor.referring_domains", integer=True)}
        if row["position"] is None:
            raise ValueError("competitor.position is required")
        key, position = (row["url"], row["channel"]), (row["position"], row["channel"])
        if key in seen or position in positions:
            raise ValueError("duplicate or conflicting competitors in a query/channel")
        if _site(row["url"]) == _site(website):
            raise ValueError("subject website cannot also be recorded as a competitor")
        window = result[f"{row['channel']}_window"]
        if window is not None and row["position"] > window:
            raise ValueError("competitor position exceeds the observed channel window")
        seen.add(key)
        positions.add(position)
        result["competitors"].append(row)
    return result


def _page(value: object, website: str, observed_at: str) -> dict:
    p = _object(value, "page", PAGE_FIELDS)
    result: dict[str, Any] = {"url": _url(p.get("url"), "page.url", required=True), "title": _text(p.get("title", ""), "page.title"),
              "meta_description": _text(p.get("meta_description", ""), "page.meta_description"), "canonical": _url(p.get("canonical", ""), "page.canonical"),
              "status_code": _number(p.get("status_code"), "page.status_code", integer=True, minimum=100, maximum=599),
              "indexability": _enum(p.get("indexability", "unknown"), "page.indexability", {"allowed", "blocked", "unknown"}),
              "word_count": _number(p.get("word_count"), "page.word_count", integer=True, maximum=1_000_000),
              "observed_at": _instant(p.get("observed_at", observed_at), "page.observed_at").isoformat(),
              "source_ref": _reference(p.get("source_ref", ""), "page.source_ref", required=False)}
    _same_site(result["url"], website, "page.url")
    for name in ("h1", "robots", "schema_types", "schema_errors", "services"):
        result[name] = _texts(p.get(name, []), f"page.{name}")
    result["service_refs"] = _refs(p.get("service_refs", []), "page.service_refs")
    result["internal_links"] = [_url(url, "page.internal_links", required=True) for url in _list(p.get("internal_links", []), "page.internal_links", 500)]
    for url in result["internal_links"]:
        _same_site(url, website, "page.internal_links")
    return result


def _economics(value: object) -> dict:
    e = _object(value, "economics", {"service", "observed_at", "refs", "currency", "average_job_value", "gross_margin", "conversion_rate",
                                      "customer_value", "repeat_customer_value", "average_job_margin"})
    result: dict[str, Any] = {"service": _text(e.get("service", ""), "economics.service", limit=200),
              "observed_at": _instant(e["observed_at"], "economics.observed_at").isoformat() if e.get("observed_at") is not None else None,
              "refs": _refs(e.get("refs", []), "economics.refs"), "currency": _text(e.get("currency", ""), "economics.currency", limit=20)}
    for key in ("average_job_value", "customer_value", "repeat_customer_value"):
        result[key] = _number(e.get(key), f"economics.{key}")
    result["average_job_margin"] = _number(e.get("average_job_margin"), "economics.average_job_margin", minimum=-1_000_000_000)
    result["gross_margin"] = _number(e.get("gross_margin"), "economics.gross_margin", minimum=-1, maximum=1)
    result["conversion_rate"] = _number(e.get("conversion_rate"), "economics.conversion_rate", maximum=1)
    return result


def validate_payload(payload: dict) -> dict:
    """Return a fresh JSON-safe canonical snapshot, or reject corruption.

    Time eligibility is assessed separately so stale/future/failed snapshots can
    remain in immutable history. Missing numbers remain null, never zero.
    """
    p = _object(payload, "payload", {"schema_version", "subject", "observed_at", "source", "queries", "pages",
                                    "prospect_authority", "referring_domains", "economics"})
    if type(p.get("schema_version")) is not int or p["schema_version"] not in {1, 2}:
        raise ValueError("schema_version must be integer 1 or 2")
    schema_version = p["schema_version"]
    s = _object(p.get("subject"), "subject", {"place_id", "website", "geography", "canonical_niche_id"})
    subject = {key: _text(s.get(key), f"subject.{key}", required=True, limit=500) for key in ("place_id", "geography", "canonical_niche_id")}
    subject["website"] = _url(s.get("website"), "subject.website", required=True)
    source = _object(p.get("source"), "source", {"provider", "report", "database", "geography", "geo_resolution", "status", "reference", "demo"}
                     | ({"coverage"} if schema_version == 2 else set()))
    normalized_source: dict[str, Any] = {"provider": _enum(source.get("provider"), "source.provider", {"semrush", "manual_serp"}),
                         "geo_resolution": _enum(source.get("geo_resolution"), "source.geo_resolution", {"local", "country"}),
                         "status": _enum(source.get("status"), "source.status", {"complete", "failed", "partial"}),
                         "demo": _bool(source.get("demo", False), "source.demo")}
    for key in ("report", "database", "geography", "reference"):
        normalized_source[key] = _text(source.get(key, ""), f"source.{key}", required=key != "database", limit=1000)
    normalized_source["reference"] = _reference(source.get("reference", ""), "source.reference")
    if normalized_source["geo_resolution"] == "local" and normalized_source["geography"].casefold() != subject["geography"].casefold():
        raise ValueError("local source geography does not match the subject geography")
    if schema_version == 2:
        normalized_source["coverage"] = validate_coverage(source.get("coverage"))
        if normalized_source["geo_resolution"] != "local":
            raise ValueError("Version-2 precise observations require a local source; country estimates retain separate query volume provenance")
    queries = [_query(q, subject["website"], normalized_source, schema_version) for q in _list(p.get("queries", []), "queries", MAX_QUERIES)]
    query_names = [(q["query"].casefold(), json_coverage_key(q.get("coverage", {}))) for q in queries]
    if len(query_names) != len(set(query_names)):
        raise ValueError("duplicate or conflicting query observations")
    if normalized_source["status"] == "complete" and not queries:
        raise ValueError("complete source requires query observations")
    observed_at = _instant(p.get("observed_at"), "observed_at").isoformat()
    pages = [_page(page, subject["website"], observed_at) for page in _list(p.get("pages", []), "pages", MAX_PAGES)]
    if len(pages) != len({page["url"] for page in pages}):
        raise ValueError("duplicate or conflicting page observations")
    economics = _economics(p.get("economics", {}))
    return {"schema_version": schema_version, "subject": subject, "observed_at": observed_at,
            "source": normalized_source, "queries": queries, "pages": pages,
            "prospect_authority": _number(p.get("prospect_authority"), "prospect_authority", maximum=100),
            "referring_domains": _number(p.get("referring_domains"), "referring_domains", integer=True), "economics": economics}


def json_coverage_key(coverage: dict) -> str:
    from local_presence_miner.domain.commercial import canonical_json

    return canonical_json(coverage_identity(coverage))


def _service_key(query: dict) -> str:
    service = query["service"].casefold()
    service = re.sub(r"[^a-z0-9]+", " ", service).strip()
    text = query["query"].casefold()
    # Distinct repair types precede the broad emergency bucket; generic plumber
    # variants may overlap, but drain/sewer/heater work is not interchangeable.
    for needles, key in ((r"\b(drain|clog|unblock)\b", "drain"), (r"\b(sewer|septic)\b", "sewer"),
                         (r"\b(water heater|hot water)\b", "water heater")):
        if re.search(needles, text):
            if key in service and not any(other in service for other in ("drain", "sewer", "water heater") if other != key):
                return service
            return f"{service or 'reported service'} / {key}"
    if re.search(r"\b(plumb\w*|burst pipe)\b", service) and re.search(r"\b(emergency|24h|24 hour|24/7|burst pipe)\b", text):
        return "emergency plumbing"
    return service or "unknown service"


_SERVICE_DECORATIONS = {"service", "services", "in", "for", "the", "a", "an", "and", "near", "me", "local", "find", "hire", "book", "quote", "quotes",
                        "best", "company", "companies"}
_SERVICE_OPERATIONS = {"repair", "replacement", "installation", "maintenance", "inspection", "cleaning", "removal", "restoration", "sales", "rental",
                       "residential", "commercial"}


def _service_tokens(text: str, geography: str = "") -> set[str]:
    """Preserve service actions/urgency; remove only explicit cosmetic/location words.

    This is deliberately not broad stemming or a cross-industry synonym taxonomy.
    The sole overlap family is emergency plumbing/24h plumbing/burst-pipe repair.
    Unknown differences continue to require validation of the actual service.
    """
    normalized = re.sub(r"\b(?:24h|24\s*(?:hours?|h)|24/7)\b", "emergency", text.casefold())
    words = set(re.findall(r"[a-z0-9]+", normalized))
    replacements = {"plumbing": "plumb", "plumber": "plumb", "plumbers": "plumb", "repairs": "repair", "rentals": "rental"}
    words = {replacements.get(word, word) for word in words}
    words -= _SERVICE_DECORATIONS | set(re.findall(r"[a-z0-9]+", geography.casefold()))
    # Only the explicitly agreed emergency family can erase the repair modifier.
    # Replacement/installation and other subservices remain distinct.
    if {"burst", "pipe"} <= words and not (words & _SERVICE_OPERATIONS) - {"repair"}:
        words -= {"burst", "pipe", "repair"}
        words |= {"emergency", "plumb"}
    elif {"emergency", "plumb"} <= words and not (words & _SERVICE_OPERATIONS) - {"repair"}:
        words.discard("repair")
    return words


def _service_relevant(query: dict, geography: str) -> bool:
    service = _service_tokens(query["service"], geography)
    words = _service_tokens(query["query"], geography)
    coverage = query.get("coverage", {})
    words -= set(coverage.get("postal_codes", [])) | ({coverage["center_postal_code"]} if coverage.get("center_postal_code") else set())
    return bool(service) and service == words


def _page_service_matches(page: dict, service: str, geography: str) -> bool:
    expected = _service_tokens(service, geography)
    return bool(page["service_refs"] and expected) and any(_service_tokens(text, geography) == expected for text in page["services"])


def _intent(query: dict) -> str:
    return "informational" if _LOW_INTENT.search(query["query"].casefold()) else query["intent"]


def _visibility(queries: list[dict], channel: str) -> str:
    if any(not q[f"{channel}_complete"] or not q["refs"] for q in queries):
        return "unknown"
    ranks = [q[f"{channel}_rank"] for q in queries]
    if all(rank is not None and rank <= 3 for rank in ranks):
        return "dominant"
    if any(rank is None for rank in ranks):
        return "absent_in_window"
    if any(rank >= 8 for rank in ranks):
        return "weak"
    return "visible"


def _targeted(page: dict, service: str, geography: str) -> bool:
    tokens = _service_tokens(service, geography)

    def matches(text: str) -> bool:
        observed = _service_tokens(text, geography)
        return bool(tokens) and tokens <= observed and (observed & _SERVICE_OPERATIONS) <= tokens

    return matches(page["title"]) and any(matches(heading) for heading in page["h1"]) and bool(page["meta_description"])


def _page_blocked(page: dict) -> bool:
    noindex = False
    for entry in page["robots"]:
        directive = entry.casefold()
        if ":" in directive:
            agent, directive = directive.split(":", 1)
            if agent.strip() not in {"googlebot", "googlebot-smartphone", "*"}:
                continue
        noindex |= bool({"noindex", "none"} & {token.strip() for token in directive.split(",")})
    return page["indexability"] == "blocked" or noindex or (page["status_code"] is not None and page["status_code"] >= 400)


def _capturability(queries: list[dict], payload: dict) -> tuple[str, list[str]]:
    barriers = []
    competitors = [c for q in queries for c in q["competitors"] if c["channel"] == "organic" and c["position"] <= 5]
    entrenched_urls = {c["url"] for c in competitors if c["kind"] in {"directory", "aggregator", "national_brand"}}
    if len(entrenched_urls) >= 2:
        barriers.append("Directories, aggregators or national brands occupy multiple leading organic positions.")
    authority = payload["prospect_authority"]
    if authority is not None and any(c["authority"] is not None and c["authority"] >= authority + 30 for c in competitors):
        barriers.append("Observed competitor authority materially exceeds the prospect's reported authority.")
    domains = payload["referring_domains"]
    if domains is not None and any(c["referring_domains"] is not None and c["referring_domains"] > max(domains * 5, domains + 50) for c in competitors):
        barriers.append("Observed competitor referring-domain counts materially exceed the prospect's reported count.")
    features = {feature.casefold().replace(" ", "_") for q in queries for feature in q["serp_features"]}
    if features & {"ads", "paid_ads", "lsa", "local_service_ads", "local_services_ads"}:
        barriers.append("Ads or Local Services Ads may absorb attention before organic results.")
    if any(q["difficulty"] is not None and q["difficulty"] >= 70 for q in queries):
        barriers.append("High reported keyword difficulty is a provider estimate and a cautious competitive barrier; "
                        "it is not a calibrated local success probability.")
    if barriers:
        return "low", barriers
    if not competitors:
        return "unknown", ["Competitor barriers have not been independently characterized for this query and geography."]
    if any(c["authority"] is None and c["referring_domains"] is None for c in competitors):
        return "unmeasured", ["Recorded competitor coverage/strength is incomplete; feasibility and ranking lift remain UNKNOWN."]
    return "moderate", []


def _opportunity(queries: list[dict], payload: dict, state: str, current: datetime) -> dict:
    service = _service_key(queries[0])
    intent = _intent(queries[0])
    states = {q["service_state"] for q in queries}
    service_state = ("confirmed" if states == {"confirmed"} else
                     "unsupported" if "unsupported" in states else "unknown" if len(states) > 1 else next(iter(states)))
    volumes = [q["volume"] for q in queries if q["volume"] is not None]
    volume = min(volumes) if volumes else None
    organic, maps = _visibility(queries, "organic"), _visibility(queries, "maps")
    source = payload["source"]
    coverage = queries[0].get("coverage", legacy_city_coverage(payload))
    geography = payload["subject"]["geography"]
    if payload["schema_version"] == 2 and coverage.get("city"):
        geography = f"{coverage['city']} {coverage.get('state', '')}".strip()
    refs = list(dict.fromkeys([source["reference"]] + [ref for q in queries for ref in q["refs"] + q["service_refs"] + [q["volume_reference"]]]))
    ranked_urls = {q["page_url"] for q in queries if q["page_url"]}
    ranked_pages = [page for page in payload["pages"] if page["url"] in ranked_urls]
    pages = [page for page in payload["pages"] if page["url"] in ranked_urls or _page_service_matches(page, service, geography)]
    page_eligibility = [classify_page_facts(page) for page in pages]
    ineligible_pages = [item for item in page_eligibility if item["state"] != "normal"]
    refs = list(dict.fromkeys(refs + [ref for page in pages for ref in page["service_refs"] + ([page["source_ref"]] if page["source_ref"] else [])]))
    unknowns = []
    if ineligible_pages:
        unknowns.append("One or more matching page observations are non-business or uncertain; "
                        "availability/retrieval must be validated before ordinary page optimization.")
    observations = [f"Organic visibility: {organic}; Maps visibility: {maps}. Channels are assessed separately."]
    if volumes:
        observations.append(f"Cluster volume {volume:g} is a conservative lower bound from the smallest reported member volume; aliases are not summed.")
    if any(q["volume"] is None for q in queries):
        unknowns.append("One or more query volumes are unknown; null is not zero demand.")
    if any(q.get("volume_coverage") and coverage_footprint(q["volume_coverage"]) != coverage_footprint(coverage) for q in queries):
        unknowns.append("Query volume coverage differs from observed SERP coverage; local demand in this footprint is UNKNOWN.")
    if organic == "unknown":
        unknowns.append("A complete, referenced organic result window is unavailable for one or more queries.")
    if maps == "unknown":
        unknowns.append("A complete, referenced Maps result window is unavailable for one or more queries.")
    if not pages:
        unknowns.append("No matching page snapshot was supplied; bounded sampling does not prove that a service page is absent.")
    ranked_pages_confirmed = (all(q["page_url"] in {page["url"] for page in ranked_pages} for q in queries)
                              and all(_page_service_matches(page, service, geography) for page in ranked_pages))
    if not ranked_pages_confirmed:
        unknowns.append("The observed query-to-page mapping and relevant service coverage of the ranked page require validation.")
    if any(page["indexability"] == "unknown" for page in pages):
        unknowns.append("Matching page indexability is unknown.")
    page_time_valid = all(current - timedelta(days=MAX_AGE_DAYS) <= _instant(page["observed_at"], "page.observed_at") <= current for page in pages)
    if not page_time_valid:
        unknowns.append("A matching page snapshot is stale or future-dated; page targeting cannot justify paid work.")
    capturability, barriers = _capturability(queries, payload)
    observations += barriers
    if capturability == "unmeasured":
        unknowns.extend(barriers)
    demand = "unknown"
    if intent not in COMMERCIAL_INTENTS:
        demand = "low_intent"
    elif service_state == "unsupported":
        demand = "unsupported_service"
    elif source["geo_resolution"] == "country" or any(q["volume_geo_resolution"] == "country" for q in queries):
        demand = "country_only"
        unknowns.append("Country keyword volume cannot establish demand in the subject's local geography.")
    elif volumes and any(value > 0 for value in volumes):
        demand = "validated_local_commercial"
    elif volumes and len(volumes) == len(queries):
        demand = "zero_reported_volume"
    if demand == "validated_local_commercial" and any(
        q.get("volume_coverage") and coverage_footprint(q["volume_coverage"]) != coverage_footprint(coverage) for q in queries
    ):
        demand = "coverage_unvalidated"
    confirmed = service_state == "confirmed" and all(q["service"] and q["service_refs"] for q in queries)
    supported_intent = all(q["intent_basis"] and q["refs"] for q in queries)
    if not confirmed:
        unknowns.append("Actual service availability requires confirmation with exact service evidence references.")
    relevant_service = all(_service_relevant(q, geography) for q in queries)
    if not relevant_service:
        unknowns.append("The query's requested subservice does not match the reported service closely enough; confirm exact relevance before paid work.")
        if demand == "validated_local_commercial":
            demand = "service_relevance_unvalidated"
    if not supported_intent:
        unknowns.append("Query intent needs an explicit evidence basis and references.")
    action, decision, confidence = "validate", "insufficient_evidence", "low"
    scope = [f"validate local search demand and service coverage for {service}"]
    reason = "The available evidence does not yet justify paid SEO work."
    blocked = [page for page in pages if _page_blocked(page)]
    foreign_canonical = [page for page in pages if page["canonical"] and _site(page["canonical"]) != _site(payload["subject"]["website"])]
    preferred_canonical = [page for page in pages if page["canonical"] and page["canonical"] != page["url"] and page not in foreign_canonical]
    redirects = [page for page in pages if page["status_code"] is not None and 300 <= page["status_code"] < 400]
    page_indexability_known = all(page["indexability"] != "unknown" for page in pages)
    eligible = (state == "complete" and demand == "validated_local_commercial" and confirmed and supported_intent
                and organic != "unknown" and page_time_valid and page_indexability_known)
    coverage_current = all(current - timedelta(days=MAX_AGE_DAYS) <= _instant(c["observed_at"], "coverage.observed_at") <= current
                           for q in queries for c in (q.get("coverage", coverage), q.get("volume_coverage", coverage)))
    if not coverage_current:
        eligible = False
        unknowns.append("Original coverage observations are stale or future-dated; reimporting cannot refresh them.")
    features = {feature.casefold().replace(" ", "_") for q in queries for feature in q["serp_features"]}
    local_pack = bool(features & {"local_pack", "maps", "map_pack"})
    if local_pack:
        observations.append("A local pack/Maps feature is reported; channel visibility does not measure click share or establish a website ranking cause.")
    if any(page["schema_errors"] for page in pages):
        unknowns.append("Reported structured-data errors require markup/eligibility validation; they do not establish a cause of the ranking gap.")
    economics = payload["economics"]
    economic_time = _instant(economics["observed_at"], "economics.observed_at") if economics["observed_at"] else None
    economic_service = economics["service"].casefold()
    economics_current = (bool(economics["refs"]) and economic_time is not None and current - timedelta(days=MAX_AGE_DAYS) <= economic_time <= current
                         and economic_service in {service} | {q["service"].casefold() for q in queries})
    if economics_current:
        refs = list(dict.fromkeys(refs + economics["refs"]))
    else:
        unknowns.append("Current referenced service-specific customer economics and conversion value are unknown; no ROI or revenue estimate is justified.")
    if economics_current and (economics["conversion_rate"] is None or economics["customer_value"] is None):
        unknowns.append("Incremental conversion rate or customer value is unknown; local search demand is not a revenue forecast.")
    nonpositive_margin = economics_current and any(economics[key] is not None and economics[key] <= 0 for key in ("gross_margin", "average_job_margin"))
    if state != "complete" or not coverage_current:
        reason = (f"The research snapshot is {state}; current independent evidence is required." if state != "complete" else
                  "Original query/coverage observations are stale or future-dated; reimporting does not renew evidence.")
        unknowns.append(reason)
        scope = ["collect current complete local SEO evidence"]
    elif demand in {"low_intent", "unsupported_service"}:
        action, decision = "no_seo_sale", "no_sale"
        reason = "This query does not establish a relevant local purchase opportunity for an actual offered service."
        scope = []
    elif ineligible_pages:
        # Preserve the existing unpriced transport-repair category for explicit
        # HTTP failure; it never diagnoses ordinary page targeting/content.
        http_failure = any(indicator["kind"] == "http_non_content" for item in ineligible_pages for indicator in item["indicators"])
        action, decision, confidence = "technical_repair" if http_failure else "response_validation", "validate_first", "low"
        reason = ("Matching page evidence is non-business or uncertain; validate availability, retrieval and provider status "
                  "before any ordinary SEO/content intervention.")
        scope = []
    elif source["geo_resolution"] == "local" and organic == "dominant" and maps == "dominant" and not blocked and not foreign_canonical and not redirects:
        action, decision, confidence, scope = "no_seo_sale", "no_sale", "high", []
        reason = "The prospect already dominates the complete measured organic and Maps windows; no ranking-gap sale is supported."
    elif nonpositive_margin:
        action, decision, confidence = "validate", "validate_first", "medium"
        scope = [f"validate service unit economics before SEO spend for {service}"]
        reason = "Current referenced owner/source-reported service margin is nonpositive; "
        reason += "observed demand does not justify SEO spend without economic validation."
    elif eligible and (blocked or foreign_canonical or redirects):
        action, decision, confidence = "technical_repair", "validate_first", "medium"
        scope = [f"validate intended indexability/canonical/redirect configuration for {page['url']}" for page in blocked + foreign_canonical + redirects]
        scope = list(dict.fromkeys(scope))
        reason = "Observed indexability or canonical defects take precedence over keyword/page targeting edits."
    elif eligible and preferred_canonical:
        action, decision, confidence = "preferred_page_validation", "validate_first", "low"
        scope = [f"confirm preferred canonical page and intended query target for {page['url']}" for page in preferred_canonical]
        reason = "A same-site canonical points to another page; confirm preferred-page intent before editing targeting."
        unknowns.append("The same-site canonical may be intentional; no automatic canonical repair is authorized.")
    elif eligible and len(pages) > 1:
        action, decision, confidence = "consolidate_validation", "validate_first", "medium"
        scope = [f"validate targeting overlap and preferred page for {service}"]
        reason = "Multiple sampled pages target the same service; query-to-page validation is needed before consolidation."
        unknowns.append("Overlapping sampled targeting is a hypothesis, not proof of cannibalization or whole-site duplication.")
    elif eligible and organic == "dominant" and (maps in {"weak", "absent_in_window"} or local_pack and maps == "unknown"):
        action, decision, confidence = "local_profile", "validate_first", "medium"
        scope = [f"validate local profile visibility and eligibility for {service}"]
        reason = "The measured gap is in Maps while organic results are strong; a website rebuild is not supported by this channel gap."
    elif eligible and not pages:
        action, decision, confidence = "create_page", "validate_first", "medium"
        scope = [f"validate existing coverage; if absent, create a focused {service} service page"]
        reason = "Relevant local demand is observed, but page absence and the creation scope must be confirmed; this is a specific unpriced scope."
    elif (eligible and ranked_pages_confirmed and any(8 <= q["organic_rank"] <= 18 for q in queries if q["organic_rank"] is not None)
          and any(not _targeted(page, service, geography) for page in ranked_pages)):
        action, decision, confidence = "improve_page", "recommended", "medium"
        scope = ["local SEO title/meta/H1 fixes"]
        reason = "A measured organic position 8–18 coincides with weak sampled title/H1/meta targeting on an existing relevant page."
    elif eligible and organic == "dominant":
        action, decision, confidence, scope = "leave_alone", "no_sale", "medium", []
        reason = "Existing organic visibility is strong; the evidence does not justify page-targeting work."
    elif eligible:
        action, decision, confidence = "validate", "validate_first", "medium"
        scope = [f"validate the cause of the measured organic gap for {service}"]
        reason = "A visibility gap is observed, but the evidence does not identify a supported page intervention."
    if (capturability in {"low", "unknown"} or local_pack and maps == "dominant") and decision == "recommended":
        decision, confidence = "validate_first", "low"
        reason += " Competitive/SERP composition is limiting or insufficiently characterized; validate incremental organic capturability before a paid scope."
    if capturability == "unmeasured" and decision == "recommended":
        confidence = "low"
    key = service + "|" + intent
    if payload["schema_version"] == 2:
        key += "|" + json_coverage_key(coverage)
    cluster_id = "seo-" + hashlib.sha256(key.encode()).hexdigest()[:16]
    # A deterministic representative is not an arbitrary first observation.
    # Preserve every exact query/channel window beside the selected proof card.
    proof_channel = "maps" if action == "local_profile" else "organic"
    supporting = [q for q in queries if q["organic_rank"] is not None and 8 <= q["organic_rank"] <= 18] if action == "improve_page" else queries
    chosen = min(supporting or queries, key=lambda q: (q[f"{proof_channel}_rank"] is None,
                                                       q[f"{proof_channel}_rank"] or 1001, q["query"].casefold()))
    chosen_coverage = chosen.get("coverage", coverage)
    evidence_packet = {"service": service, "query": chosen["query"], "channel": proof_channel, "page_url": chosen["page_url"],
                       "observed_position": chosen[f"{proof_channel}_rank"], "result_window": chosen[f"{proof_channel}_window"],
                       "complete": chosen[f"{proof_channel}_complete"], "observed_at": chosen_coverage["observed_at"],
                       "source_coverage": chosen_coverage, "coverage_label": coverage_label(chosen_coverage),
                       "competitors": chosen["competitors"], "reason": reason, "hypothesis": reason, "confidence": confidence,
                       "falsifier": "Comparable current observations or owner-confirmed service intent contradict this proposed intervention.",
                       "unknowns": list(dict.fromkeys(unknowns)), "source_refs": refs,
                       "page_eligibility": page_eligibility,
                       "observations": [{"query": q["query"], "channel": channel, "observed_position": q[f"{channel}_rank"],
                                         "result_window": q[f"{channel}_window"], "complete": q[f"{channel}_complete"],
                                         "source_coverage": q.get("coverage", coverage), "observed_at": q.get("coverage", coverage)["observed_at"],
                                         "competitors": [c for c in q["competitors"] if c["channel"] == channel], "source_refs": q["refs"]}
                                        for q in queries for channel in ("organic", "maps")]}
    return {"cluster_id": cluster_id, "queries": [q["query"] for q in queries], "service": service, "intent": intent,
            "service_state": service_state, "organic_visibility": organic, "maps_visibility": maps, "volume": volume,
            "volume_basis": "minimum reported member volume; conservative cluster lower bound; no addition or local allocation",
            "demand_quality": demand, "capturability": capturability, "action": action, "decision": decision,
            "confidence": confidence, "reason": reason, "observations": observations, "evidence_refs": refs,
            "coverage": coverage, "selected_evidence": evidence_packet,
            "page_eligibility": page_eligibility,
            "economics_state": "reported_current" if economics_current else "unknown",
            "expected_effect": "May improve query-to-page relevance or remove an observed eligibility defect; rankings, clicks and leads are not guaranteed.",
            "success_metric": "Compare the same query/geography organic and Maps windows and page impressions/clicks after the agreed change.",
            "falsifier": "Complete independent local remeasurement shows no relevant gap, no offered service, no local purchase demand, "
                         "or a different cause of the observed gap.",
            "scope": scope, "unknowns": list(dict.fromkeys(unknowns))}


def analyze_seo(payload: dict, *, now: datetime | None = None) -> dict:
    """Analyze one immutable snapshot; malformed evidence always fails closed."""
    try:
        normalized = validate_payload(payload)
    except (ValueError, TypeError, OverflowError) as exc:
        return {"version": SEO_INTELLIGENCE_VERSION, "state": "invalid", "summary": "SEO evidence is invalid; no recommendation is eligible.",
                "opportunities": [], "unknowns": [str(exc)], "limitations": ["Invalid evidence cannot justify paid work."],
                "competitors": [], "schema_notes": [], "source_metadata": {}}
    current = now or datetime.now(UTC)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    current = current.astimezone(UTC)
    observed = _instant(normalized["observed_at"], "observed_at")
    state = normalized["source"]["status"]
    if observed > current + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        state = "future"
    elif current - observed > timedelta(days=MAX_AGE_DAYS):
        state = "stale"
    elif normalized["source"]["demo"]:
        state = "demo"
    clusters: dict[tuple[str, str, str], list[dict]] = {}
    for query in normalized["queries"]:
        clusters.setdefault((_service_key(query), _intent(query), json_coverage_key(query.get("coverage", {}))), []).append(query)
    opportunities = [_opportunity(queries, normalized, state, current) for _, queries in sorted(clusters.items())]
    competitors = [{"query": q["query"], "geography": normalized["source"]["geography"], "geo_resolution": normalized["source"]["geo_resolution"],
                    "coverage": q.get("coverage", legacy_city_coverage(normalized)),
                    "observed_at": q.get("coverage", legacy_city_coverage(normalized))["observed_at"],
                    "evidence_refs": q["refs"], **competitor}
                   for q in normalized["queries"] for competitor in q["competitors"]]
    schema_notes = [f"{p['url']}: observed schema types {', '.join(p['schema_types']) or 'unknown'}; "
                    f"errors {', '.join(p['schema_errors']) or 'none reported'}. "
                    "Schema presence alone does not establish a ranking cause or guarantee rich results." for p in normalized["pages"]]
    unknowns = list(dict.fromkeys([unknown for op in opportunities for unknown in op["unknowns"]]))
    if state != "complete" and not opportunities:
        unknowns.append(f"Source state {state}; no usable query observations are available.")
    recommended = sum(op["decision"] == "recommended" for op in opportunities)
    return {"version": SEO_INTELLIGENCE_VERSION, "state": state,
            "summary": f"{len(opportunities)} distinct service/intent clusters; {recommended} supported scoped recommendations; snapshot state {state}.",
            "opportunities": opportunities, "unknowns": unknowns, "competitors": competitors, "schema_notes": schema_notes,
            "limitations": ["Observed association does not establish why a page ranks or guarantee rankings, traffic, leads or ROI.",
                            "Volumes are source estimates; overlapping queries are not additive and country volume is not local demand.",
                            "Bounded page samples do not prove whole-site absence, duplication, orphaning or cannibalization.",
                            "Offline imports are recorded evidence, not live Semrush verification; live discovery returned no_api_units.",
                            "Service alias clusters, intent overrides, targeting checks and capturability thresholds are "
                            "conservative heuristics requiring human validation.",
                            "Demand and keyword difficulty never determine a price or authorize a quote."],
            "source_metadata": {**normalized["source"], "observed_at": normalized["observed_at"], "subject": normalized["subject"],
                                "freshness_limit_days": MAX_AGE_DAYS},
            "economics": normalized["economics"]}
