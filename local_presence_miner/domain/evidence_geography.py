"""Recorded observation coverage, distinct from business/owner/acquisition targets.

These validate supplier claims and provenance, not authenticate a live provider.
A radius is a search-location circle, not a postal polygon or universal rank.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any


def _text(value: object, field: str, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 1000 or any(ord(c) < 32 for c in value):
        raise ValueError(f"coverage.{field} must be bounded text")
    result = " ".join(value.split())
    if required and not result:
        raise ValueError(f"coverage.{field} is required")
    return result


def validate_coverage(value: object) -> dict[str, Any]:
    allowed = {"kind", "country", "state", "city", "postal_codes", "center", "radius_miles", "center_postal_code",
               "center_reference", "method", "reference", "observed_at"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Observation coverage must be a supported structured object")
    kind = _text(value.get("kind"), "kind")
    if kind not in {"city", "zip", "radius"}:
        raise ValueError("Observation coverage kind must be city, zip or radius")
    result: dict[str, Any] = {key: _text(value.get(key, ""), key, required=key != "city")
              for key in ("country", "state", "city", "method", "reference", "observed_at")}
    if result["country"] != "US" or not re.fullmatch(r"[A-Z]{2}", result["state"]):
        raise ValueError("Precise coverage currently requires an explicit US country and state abbreviation")
    try:
        stamp = datetime.fromisoformat(result["observed_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Coverage time requires a timezone")
        result["observed_at"] = stamp.astimezone(UTC).isoformat()
    except (ValueError, TypeError) as exc:
        raise ValueError("Coverage observed_at must be an original ISO timestamp with timezone") from exc
    result["kind"] = kind
    if kind == "city":
        if not result["city"] or any(key in value for key in ("postal_codes", "center", "radius_miles", "center_postal_code", "center_reference")):
            raise ValueError("City observations must not carry invented ZIP/radius precision")
    elif kind == "zip":
        zips = value.get("postal_codes")
        if (not isinstance(zips, list) or not 1 <= len(zips) <= 20
                or any(not isinstance(z, str) or re.fullmatch(r"\d{5}", z) is None for z in zips)
                or any(key in value for key in ("center", "radius_miles", "center_postal_code", "center_reference"))):
            raise ValueError("ZIP observations require explicit postal codes, not a city or circle relabel")
        result["postal_codes"] = sorted(set(zips))
    else:
        if "postal_codes" in value:
            raise ValueError("A radius cannot claim ZIP-polygon coverage")
        center = value.get("center")
        if not isinstance(center, dict) or set(center) != {"latitude", "longitude"}:
            raise ValueError("Radius coverage requires a recorded center")
        for key, limit in (("latitude", 90), ("longitude", 180)):
            number = center[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or abs(number) > limit:
                raise ValueError("Radius center coordinates are invalid")
        radius = value.get("radius_miles")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or not 0 < radius <= 100:
            raise ValueError("Radius coverage requires a finite positive radius up to 100 miles")
        postal = _text(value.get("center_postal_code"), "center_postal_code")
        if not re.fullmatch(r"\d{5}", postal):
            raise ValueError("Radius center postal identity is required")
        result.update(center=dict(center), radius_miles=radius, center_postal_code=postal,
                      center_reference=_text(value.get("center_reference"), "center_reference"))
    return result


def coverage_identity(coverage: dict) -> dict:
    """Comparable footprint/method, deliberately excluding capture date/reference."""
    return {key: value for key, value in coverage.items() if key not in {"observed_at", "reference", "center_reference"}}


def coverage_footprint(coverage: dict) -> dict:
    return {key: value for key, value in coverage_identity(coverage).items() if key not in {"method", "precision"}}


def fits_target(coverage: dict, target: dict, *, partial_zip: bool = False) -> bool:
    """Exact supported footprint only; no invented city/adjacency containment."""
    if coverage.get("kind") != target.get("kind"):
        return False
    if any(target.get(key) and coverage.get(key) != target[key] for key in ("country", "state")):
        return False
    if target["kind"] == "zip":
        wanted, observed = set(target.get("postal_codes", [])), set(coverage.get("postal_codes", []))
        return bool(wanted and observed) and (observed <= wanted if partial_zip else wanted <= observed)
    if target["kind"] == "radius":
        return ((not target.get("center_postal_code") or coverage.get("center_postal_code") == target["center_postal_code"])
                and coverage.get("radius_miles") == target.get("radius_miles")
                and (not target.get("center") or coverage.get("center") == target["center"]))
    return bool(target.get("city")) and str(coverage.get("city", "")).casefold() == str(target["city"]).casefold()


def coverage_label(coverage: dict) -> str:
    if coverage.get("kind") == "country":
        return f"Country-level source: {coverage.get('geography', 'UNKNOWN')}; no local ZIP demand established"
    if coverage.get("kind") == "zip":
        return f"Recorded search-location/postal sample for ZIP {', '.join(coverage.get('postal_codes', []))}; not universal Maps rank"
    if coverage.get("kind") == "radius":
        return (f"Recorded {coverage['radius_miles']:g}-mile circle around ZIP {coverage['center_postal_code']}; "
                "may cross ZIP boundaries; not a ZIP polygon or universal Maps rank")
    return f"City-level observation: {coverage.get('city') or coverage.get('geography', 'UNKNOWN')}; ZIP/radius fit UNKNOWN"


def legacy_city_coverage(payload: dict) -> dict:
    """Describe historical bytes honestly without changing or redating them."""
    return {"kind": "city" if payload["source"]["geo_resolution"] == "local" else "country",
            "geography": payload["source"]["geography"], "city": payload["subject"]["geography"],
            "method": payload["source"]["report"], "reference": payload["source"]["reference"],
            "observed_at": payload["observed_at"], "precision": "historical source geography only"}
