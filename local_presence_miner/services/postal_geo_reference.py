"""Offline geographic compatibility of a provider ZIP search center.

Census ZCTAs are generalized geographic proxies, not USPS ZIP boundaries.
This check permits an acquisition center only when it lies strictly within
both the requested ZCTA and state in the pinned public reference. It never
supplies a replacement center or establishes ZIP-wide acquisition coverage.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

REFERENCE_FILE = Path(__file__).resolve().parents[1] / "assets" / "postal_geo_census2020_v1.zip"
REFERENCE_SHA256 = "d6fd6afbecabdd7bc1a33c52bae714e59613ccc79888ff364f15b050b5fe4748"
REFERENCE_ID = "us_census_2020_cartographic_zcta_state_500k_v1"
REFERENCE_LIMITATIONS = (
    "2020 generalized Census ZCTA/state compatibility proxy, not USPS ZIP boundaries or current ZIP coverage. "
    "Unsupported ZIPs, holes and reference boundary points fail closed. A compatible center does not establish "
    "business ZIP membership, owner service coverage or acquisition-circle ZIP coverage."
)
Point = tuple[float, float]
Ring = tuple[Point, ...]


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Non-finite or non-numeric reference coordinate")
    return float(value)


def _geometry(value: object, code: str) -> tuple[Ring, ...]:
    if not isinstance(value, dict) or value.get("code") != code or not isinstance(value.get("rings"), list):
        raise ValueError("Malformed reference geometry")
    rings: list[Ring] = []
    for raw in value["rings"]:
        if not isinstance(raw, list) or len(raw) < 4:
            raise ValueError("Malformed reference ring")
        points: list[Point] = []
        for pair in raw:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Malformed reference point")
            x, y = _number(pair[0]), _number(pair[1])
            if not -180 <= x <= 180 or not -90 <= y <= 90:
                raise ValueError("Out-of-range reference point")
            points.append((x, y))
        if points[0] != points[-1]:
            raise ValueError("Unclosed reference ring")
        rings.append(tuple(points))
    if not rings:
        raise ValueError("Empty reference geometry")
    return tuple(rings)


def _ring_relation(longitude: float, latitude: float, ring: Ring) -> str:
    # Unwrap each ring at the dateline; then place the candidate in the same
    # longitude interval. Polygon parts and holes are handled with even/odd
    # crossings rather than relying on source ring orientation.
    unwrapped: list[Point] = [ring[0]]
    for longitude_value, latitude_value in ring[1:]:
        previous = unwrapped[-1][0]
        while longitude_value - previous > 180:
            longitude_value -= 360
        while longitude_value - previous < -180:
            longitude_value += 360
        unwrapped.append((longitude_value, latitude_value))
    reference_longitude = sum(point[0] for point in unwrapped) / len(unwrapped)
    longitude += 360 * round((reference_longitude - longitude) / 360)
    inside = False
    for (x1, y1), (x2, y2) in zip(unwrapped, unwrapped[1:], strict=False):
        dx, dy = x2 - x1, y2 - y1
        # The tiny tolerance addresses floating-point arithmetic only; it does
        # not enlarge polygons or invent a geographic acceptance buffer.
        cross = (longitude - x1) * dy - (latitude - y1) * dx
        scale = max(abs(dx), abs(dy), 1.0)
        if abs(cross) <= 1e-10 * scale and min(x1, x2) - 1e-10 <= longitude <= max(x1, x2) + 1e-10 and min(y1, y2) - 1e-10 <= latitude <= max(y1, y2) + 1e-10:
            return "boundary"
        if (y1 > latitude) != (y2 > latitude) and longitude < x1 + (latitude - y1) * dx / dy:
            inside = not inside
    return "inside" if inside else "outside"


def polygon_relation(longitude: float, latitude: float, rings: tuple[Ring, ...]) -> str:
    """Strict interior relation for disjoint polygon parts and nested holes."""
    inside = False
    for ring in rings:
        relation = _ring_relation(longitude, latitude, ring)
        if relation == "boundary":
            return "boundary"
        if relation == "inside":
            inside = not inside
    return "inside" if inside else "outside"


def validate_postal_coordinates(postal_code: str, state_code: str, latitude: float, longitude: float) -> dict[str, Any]:
    """Return inspectable, fail-closed compatibility evidence without network IO.

    Verify the current resource bytes on every call, including after a file
    changes during a process. Only the requested polygons are decoded.
    """
    result: dict[str, Any] = {
        "status": "unresolved",
        "method": "strict_point_in_census_zcta_and_state",
        "reference_id": REFERENCE_ID,
        "reference_resource_sha256": REFERENCE_SHA256,
        "requested_postal_code": postal_code,
        "requested_state_region": state_code,
        "limitations": REFERENCE_LIMITATIONS,
    }
    if not re.fullmatch(r"[0-9]{5}", postal_code) or not re.fullmatch(r"[A-Z]{2}", state_code):
        return {**result, "reason": "unsupported_identity"}
    try:
        latitude, longitude = _number(latitude), _number(longitude)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return {**result, "reason": "invalid_coordinates"}
        with REFERENCE_FILE.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != REFERENCE_SHA256:
                return {**result, "reason": "reference_integrity_failure", "observed_resource_sha256": digest}
            stream.seek(0)
            with ZipFile(stream) as archive:
                metadata = json.loads(archive.read("metadata.json"))
                if not isinstance(metadata, dict) or metadata.get("schema_version") != 1 or metadata.get("reference_id") != REFERENCE_ID:
                    return {**result, "reason": "reference_schema_failure"}
                result["reference"] = metadata
                try:
                    zcta = _geometry(json.loads(archive.read(f"zcta/{postal_code}.json")), postal_code)
                    state = _geometry(json.loads(archive.read(f"state/{state_code}.json")), state_code)
                except KeyError:
                    return {**result, "reason": "unsupported_zip_or_state"}
        zcta_relation = polygon_relation(longitude, latitude, zcta)
        state_relation = polygon_relation(longitude, latitude, state)
        result.update(zcta_relation=zcta_relation, state_relation=state_relation)
        if "boundary" in {zcta_relation, state_relation}:
            return {**result, "reason": "reference_boundary_ambiguous"}
        if zcta_relation != "inside" or state_relation != "inside":
            return {**result, "reason": "coordinates_incompatible_with_reference"}
        return {**result, "status": "compatible", "reason": "strict_reference_interior"}
    except (OSError, BadZipFile, ValueError, RuntimeError, OverflowError, UnicodeError, KeyError):
        return {**result, "reason": "reference_unavailable_or_corrupt"}
