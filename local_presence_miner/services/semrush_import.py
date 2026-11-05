"""Offline Semrush keyword-export adapter; no API or live verification.

Semrush keyword volumes remain country/database observations. Separate local
organic/Maps observations and owner/page service references are mandatory inputs.
The CSV's domain Position is never relabeled as a local rank. Live Semrush
discovery was unavailable (no_api_units); this adapter does not bypass that limit.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from local_presence_miner.domain.seo_intelligence import MAX_QUERIES, validate_payload

MAX_CSV_BYTES = 1_000_000
_HEADERS = {
    "keyword": {"keyword", "query"},
    "volume": {"volume", "search volume", "searchvolume"},
    "difficulty": {"keyword difficulty", "keyword difficulty index", "keyword difficulty %", "kd", "kd %", "difficulty"},
}
_LOCAL_FIELDS = {"geography", "observed_at", "reference", "service", "service_state", "service_refs", "intent", "intent_basis", "organic_rank",
                 "maps_rank", "organic_window", "maps_window", "organic_complete", "maps_complete", "page_url", "competitors", "serp_features", "refs"}


def _csv_number(value: str, field: str) -> float | int | None:
    stripped = value.strip()
    if stripped.casefold() in {"", "n/a", "na", "unknown", "-", "--"}:
        return None
    # Thousands separators are accepted only in a complete grouping, never as
    # decimal-locale guessing. Malformed strings are not silently coerced to zero.
    if re.fullmatch(r"[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?", stripped):
        stripped = stripped.replace(",", "")
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", stripped):
        raise ValueError(f"CSV {field} must be a nonnegative finite number or explicit unknown")
    result = float(stripped) if "." in stripped else int(stripped)
    return result


def import_semrush_csv(csv_text: str, *, subject: dict, metadata: dict, local_ranks: dict, pages: list | None = None) -> dict:
    """Convert a bounded keyword CSV and independently supplied local observations.

    ``metadata`` contains observed_at plus the full source fields (either nested
    in source, or flat). Its geography/geo_resolution describe keyword volume;
    supported exports have country resolution. ``local_ranks`` maps each exact
    CSV keyword to one structured record with geography, observed_at, reference,
    service confirmation/intent and explicit organic/Maps rank/window fields.
    Every local timestamp must match the snapshot; old rank data cannot acquire a
    fresh timestamp merely by importing a newly downloaded keyword export.
    """
    if not isinstance(csv_text, str) or len(csv_text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("CSV must be bounded text")
    if not isinstance(metadata, dict) or not isinstance(subject, dict) or not isinstance(local_ranks, dict):
        raise ValueError("subject, metadata and local_ranks must be objects")
    if any(not isinstance(keyword, str) for keyword in local_ranks):
        raise ValueError("Local rank keys must be exact keyword strings")
    metadata_keys = {"observed_at", "source"} if "source" in metadata else {
        "observed_at", "provider", "report", "database", "geography", "geo_resolution", "status", "reference", "demo"}
    if set(metadata) - metadata_keys or "source" in metadata and not isinstance(metadata["source"], dict):
        raise ValueError("Metadata must contain only the explicit source contract and timestamp")
    observed_at = metadata.get("observed_at")
    source = dict(metadata.get("source", {key: value for key, value in metadata.items() if key != "observed_at"}))
    if source.get("provider", "semrush") != "semrush":
        raise ValueError("CSV source provider must be semrush")
    source["provider"] = "semrush"
    if source.get("geo_resolution") != "country":
        raise ValueError("Offline Semrush keyword CSV requires explicit country volume provenance")
    country = source.get("geography")
    volume_reference = source.get("reference")
    # This composite snapshot's ranks are local, while each keyword volume keeps
    # its explicit country provenance; neither observation overwrites the other.
    source["geo_resolution"] = "local"
    source["geography"] = subject.get("geography")
    probe = validate_payload({"schema_version": 1, "subject": subject, "observed_at": observed_at,
                              "source": {**source, "status": "failed"}, "queries": [], "pages": pages or []})
    if not isinstance(country, str) or not country.strip() or not isinstance(volume_reference, str) or not volume_reference.strip():
        raise ValueError("Country geography and volume reference are required")
    if not csv_text.strip():
        raise ValueError("CSV is empty")
    text = csv_text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect, strict=True)
        headers = reader.fieldnames
    except csv.Error as exc:
        raise ValueError("Malformed CSV") from exc
    if not headers or len(headers) > 50 or any(not isinstance(header, str) or len(header) > 200 for header in headers):
        raise ValueError("CSV has invalid headers")
    normalized = {header: " ".join(header.strip().casefold().split()) for header in headers}
    if len(set(normalized.values())) != len(headers):
        raise ValueError("CSV has duplicate headers")
    fields = {}
    for name, aliases in _HEADERS.items():
        candidates = [header for header, normalized_header in normalized.items() if normalized_header in aliases]
        if len(candidates) > 1 or name in {"keyword", "volume"} and not candidates:
            raise ValueError(f"CSV requires one unambiguous {name} column")
        fields[name] = candidates[0] if candidates else None
    queries: list[dict[str, Any]] = []
    used = set()
    try:
        for row in reader:
            if len(queries) >= MAX_QUERIES or None in row or any(value is None or len(value) > 5000 for value in row.values()):
                raise ValueError("CSV has oversized or malformed rows")
            keyword = " ".join(row[fields["keyword"]].split())
            if not keyword or keyword.casefold() in used:
                raise ValueError("CSV has empty, duplicate or conflicting keywords")
            local = local_ranks.get(keyword)
            if not isinstance(local, dict) or set(local) - _LOCAL_FIELDS:
                raise ValueError(f"CSV keyword {keyword!r} requires a structured local rank record")
            if local.get("geography") != probe["subject"]["geography"]:
                raise ValueError("Local rank geography must exactly match the subject")
            # ISO normalization avoids false conflicts between Z and +00:00.
            rank_probe = validate_payload({"schema_version": 1, "subject": subject, "observed_at": local.get("observed_at"),
                                           "source": {**source, "status": "failed"}, "queries": []})
            if rank_probe["observed_at"] != probe["observed_at"]:
                raise ValueError("Local rank and keyword snapshot timestamps must match")
            reference = local.get("reference")
            if not isinstance(reference, str) or not reference.strip():
                raise ValueError("Local rank reference is required")
            if local.get("organic_window") is None and local.get("maps_window") is None:
                raise ValueError("Explicit local rank observation windows are required")
            query = {key: value for key, value in local.items() if key not in {"geography", "observed_at", "reference"}}
            existing_refs = query.get("refs", [])
            if not isinstance(existing_refs, list):
                raise ValueError("Local rank refs must be a list")
            query.update({"query": keyword, "volume": _csv_number(row[fields["volume"]], "volume"),
                          "difficulty": _csv_number(row[fields["difficulty"]], "difficulty") if fields["difficulty"] else None,
                          "volume_geo_resolution": "country", "volume_geography": country, "volume_reference": volume_reference,
                          "refs": existing_refs + [reference]})
            queries.append(query)
            used.add(keyword.casefold())
    except csv.Error as exc:
        raise ValueError("Malformed CSV") from exc
    if not queries:
        raise ValueError("CSV has no keyword rows")
    if len(local_ranks) != len(queries) or any(keyword.casefold() not in used for keyword in local_ranks):
        raise ValueError("Local rank records must match the CSV keywords exactly")
    return validate_payload({"schema_version": 1, "subject": subject, "observed_at": observed_at, "source": source,
                             "queries": queries, "pages": pages or []})
