from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from local_presence_miner.domain.models import SearchCriteria
from local_presence_miner.services import postal_geo_reference
from local_presence_miner.services.google_places import GooglePlacesClient, GooglePlacesError
from local_presence_miner.services.postal_geo_reference import polygon_relation, validate_postal_coordinates


class Response:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def json(self) -> dict[str, Any]:
        return self.data


def postal_place(postal_code: str, state: str, latitude: float, longitude: float) -> dict[str, Any]:
    state_names = {"CO": "Colorado", "MI": "Michigan", "MA": "Massachusetts", "NY": "New York", "CA": "California", "AK": "Alaska", "HI": "Hawaii"}
    return {
        "id": f"postal-{postal_code}", "types": ["postal_code", "political"],
        "addressComponents": [
            {"longText": postal_code, "shortText": postal_code, "types": ["postal_code"]},
            {"longText": state_names[state], "shortText": state, "types": ["administrative_area_level_1"]},
            {"longText": "United States", "shortText": "US", "types": ["country"]},
        ],
        "location": {"latitude": latitude, "longitude": longitude},
    }


def acquire(monkeypatch, place: dict[str, Any], *, postal_code: str = "80903", state: str = "CO"):
    client = GooglePlacesClient("synthetic-offline-key")
    calls: list[dict[str, Any]] = []

    def transport(payload, headers):
        calls.append(deepcopy(payload))
        return Response({"places": [place] if len(calls) == 1 else []})

    monkeypatch.setattr(client, "_post_with_retry", transport)
    criteria = SearchCriteria("Synthetic locality", state, "roofers", target_zip_code=postal_code)
    return client, calls, criteria


@pytest.mark.parametrize(
    ("name", "latitude", "longitude"),
    [
        ("Denver", 39.7392, -104.9903),
        ("Pueblo", 38.2544, -104.6091),
        ("Paris", 48.8566, 2.3522),
        ("ocean", 0.0, 0.0),
        ("adjacent 80906", 38.7941, -104.8100),
    ],
)
def test_correct_zip_state_country_labels_with_wrong_coordinates_stop_public_acquisition(monkeypatch, name, latitude, longitude) -> None:
    client, calls, criteria = acquire(monkeypatch, postal_place("80903", "CO", latitude, longitude))
    with pytest.raises(GooglePlacesError, match="search center.*radius cannot be enforced safely"):
        client.search_with_visibility(criteria, enrich=False)
    assert len(calls) == 1, name
    assert client.center_resolution_provenance["status"] == "unresolved"
    check = client.center_resolution_provenance["coordinate_reference"]
    assert check["status"] == "unresolved"
    assert check["reason"] == "coordinates_incompatible_with_reference"
    assert check["zcta_relation"] == "outside"
    assert "provider_place_id" not in client.center_resolution_provenance


@pytest.mark.parametrize(
    ("postal_code", "state", "latitude", "longitude"),
    [
        ("80903", "CO", 38.8339, -104.8214),
        ("80906", "CO", 38.7941, -104.8100),
        ("81101", "CO", 37.4694, -105.8700),
        ("81003", "CO", 38.2760, -104.6120),
        ("80817", "CO", 38.6850, -104.7050),
        ("81007", "CO", 38.3500, -104.7500),
        ("81144", "CO", 37.5792, -106.1480),
        ("48502", "MI", 43.0125, -83.6875),
        ("02108", "MA", 42.3570, -71.0637),
        ("10001", "NY", 40.7506, -73.9972),
        ("90001", "CA", 33.9731, -118.2479),
        ("99501", "AK", 61.2160, -149.8940),
        ("96701", "HI", 21.3820, -157.9330),
    ],
)
def test_national_reference_and_colorado_extra_coverage_allow_compatible_center(monkeypatch, postal_code, state, latitude, longitude) -> None:
    client, calls, criteria = acquire(monkeypatch, postal_place(postal_code, state, latitude, longitude), postal_code=postal_code, state=state)
    acquisition = client.search_with_visibility(criteria, enrich=False)
    assert len(calls) == 2
    assert acquisition.collection_status == "complete"
    assert (acquisition.resolved_latitude, acquisition.resolved_longitude) == (latitude, longitude)
    check = acquisition.center_resolution_provenance["coordinate_reference"]
    assert check["status"] == "compatible"
    assert check["zcta_relation"] == check["state_relation"] == "inside"
    assert check["reference"]["vintage"] == "2020"
    assert check["reference"]["publisher"] == "U.S. Census Bureau"
    assert check["reference"]["sources"]["zcta"]["url"].startswith("https://www2.census.gov/")
    assert check["reference"]["sources"]["zcta"]["retrieved_at_utc"]
    assert len(check["reference"]["sources"]["zcta"]["sha256"]) == 64
    assert check["reference_resource_sha256"] == postal_geo_reference.REFERENCE_SHA256
    limitations = acquisition.center_resolution_provenance["limitations"].lower()
    assert "circle may cross zip boundaries" in limitations
    assert "not a usps postal boundary" in limitations
    assert "result window is not universal maps rank" in limitations


def test_provider_can_neither_relabel_requested_state_nor_use_a_business_centroid(monkeypatch) -> None:
    # All provider labels agree with the request, but the actual ZIP/point is MI.
    client, calls, criteria = acquire(monkeypatch, postal_place("48502", "CO", 43.0125, -83.6875), postal_code="48502", state="CO")
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(criteria, enrich=False)
    assert len(calls) == 1
    check = client.center_resolution_provenance["coordinate_reference"]
    assert check["zcta_relation"] == "inside"
    assert check["state_relation"] == "outside"


def test_zip_without_reference_coverage_fails_closed(monkeypatch) -> None:
    # Requested 80961 is absent from this pinned 2020 ZCTA layer; no inferred
    # polygon, neighboring ZIP or business centroid fallback is allowed.
    client, calls, criteria = acquire(monkeypatch, postal_place("80961", "CO", 38.8339, -104.8214), postal_code="80961")
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(criteria, enrich=False)
    assert len(calls) == 1
    assert client.center_resolution_provenance["coordinate_reference"]["reason"] == "unsupported_zip_or_state"


def test_exact_reference_boundary_is_ambiguous_not_invented_zip_precision(monkeypatch) -> None:
    with ZipFile(postal_geo_reference.REFERENCE_FILE) as archive:
        geometry = json.loads(archive.read("zcta/80903.json"))
    longitude, latitude = geometry["rings"][0][0]
    client, calls, criteria = acquire(monkeypatch, postal_place("80903", "CO", latitude, longitude))
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(criteria, enrich=False)
    assert len(calls) == 1
    assert client.center_resolution_provenance["coordinate_reference"]["reason"] == "reference_boundary_ambiguous"


@pytest.mark.parametrize("fault", ["missing", "corrupt", "same_process_corruption"])
def test_missing_or_corrupt_reference_stops_discovery_and_cannot_reuse_compatible_provenance(monkeypatch, tmp_path: Path, fault) -> None:
    client, _, criteria = acquire(monkeypatch, postal_place("80903", "CO", 38.8339, -104.8214))
    if fault == "same_process_corruption":
        client.search_with_visibility(criteria, enrich=False)
        assert client.center_resolution_provenance["status"] == "verified"
    path = tmp_path / "reference.zip"
    if fault != "missing":
        path.write_bytes(b"broken geographic reference")
    monkeypatch.setattr(postal_geo_reference, "REFERENCE_FILE", path)
    calls: list[dict[str, Any]] = []

    def transport(payload, headers):
        calls.append(payload)
        return Response({"places": [postal_place("80903", "CO", 38.8339, -104.8214)]})

    monkeypatch.setattr(client, "_post_with_retry", transport)
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(criteria, enrich=False)
    assert len(calls) == 1
    assert client.center_resolution_provenance["status"] == "unresolved"
    assert "provider_place_id" not in client.center_resolution_provenance
    assert client.center_resolution_provenance["coordinate_reference"]["reason"] in {"reference_integrity_failure", "reference_unavailable_or_corrupt"}


def test_pinned_national_resource_is_complete_and_hash_bound() -> None:
    with postal_geo_reference.REFERENCE_FILE.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == postal_geo_reference.REFERENCE_SHA256
        stream.seek(0)
        with ZipFile(stream) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names))
            metadata = json.loads(archive.read("metadata.json"))
            assert metadata["counts"]["zcta"] >= 33000
            assert metadata["counts"]["state"] >= 50
            assert sum(name.startswith("zcta/") for name in names) == metadata["counts"]["zcta"]
            assert sum(name.startswith("state/") for name in names) == metadata["counts"]["state"]
            assert "not USPS" in metadata["limitations"]


@pytest.mark.parametrize("fault", ["schema", "unclosed_ring", "nan_point", "wrong_geography"])
def test_reference_schema_and_geometry_errors_fail_closed(monkeypatch, tmp_path: Path, fault) -> None:
    path = tmp_path / "malformed-reference.zip"
    metadata = {"schema_version": 1, "reference_id": postal_geo_reference.REFERENCE_ID}
    geometry: dict[str, Any] = {"code": "80903", "rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    if fault == "schema":
        metadata["schema_version"] = 99
    elif fault == "unclosed_ring":
        geometry["rings"][0][-1] = [0, 1]
    elif fault == "nan_point":
        geometry["rings"][0][1][0] = float("nan")
    else:
        geometry["code"] = "80906"
    with ZipFile(path, "w") as archive:
        archive.writestr("metadata.json", json.dumps(metadata))
        archive.writestr("zcta/80903.json", json.dumps(geometry))
        archive.writestr("state/CO.json", json.dumps({**geometry, "code": "CO"}))
    # A matching pin cannot make malformed schema/geometry geographically valid.
    monkeypatch.setattr(postal_geo_reference, "REFERENCE_FILE", path)
    monkeypatch.setattr(postal_geo_reference, "REFERENCE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    result = validate_postal_coordinates("80903", "CO", 38.8339, -104.8214)
    assert result["status"] == "unresolved"
    assert result["reason"] in {"reference_schema_failure", "reference_unavailable_or_corrupt"}


@pytest.mark.parametrize(
    ("longitude", "latitude", "expected"),
    [(1, 1, "inside"), (5, 5, "outside"), (3, 5, "boundary"), (10, 2, "boundary"), (21, 1, "inside"), (15, 1, "outside")],
)
def test_polygon_holes_disjoint_parts_and_boundaries_fail_closed(longitude, latitude, expected) -> None:
    outer = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0))
    hole = ((3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 3.0))
    island = ((20.0, 0.0), (22.0, 0.0), (22.0, 2.0), (20.0, 2.0), (20.0, 0.0))
    assert polygon_relation(longitude, latitude, (outer, hole, island)) == expected
    assert polygon_relation(longitude, latitude, tuple(tuple(reversed(ring)) for ring in (outer, hole, island))) == expected


@pytest.mark.parametrize(("longitude", "expected"), [(179.5, "inside"), (-179.5, "inside"), (0.0, "outside"), (179.0, "boundary")])
def test_dateline_geometry_does_not_wrap_wrong_side_of_world_inside(longitude, expected) -> None:
    ring = ((179.0, 0.0), (-179.0, 0.0), (-179.0, 2.0), (179.0, 2.0), (179.0, 0.0))
    assert polygon_relation(longitude, 1.0, (ring,)) == expected


@pytest.mark.parametrize(("latitude", "longitude"), [(float("nan"), 0.0), (0.0, float("inf")), (91.0, 0.0), (0.0, 181.0), (True, 0.0)])
def test_reference_api_rejects_invalid_coordinates(latitude, longitude) -> None:
    assert validate_postal_coordinates("80903", "CO", latitude, longitude)["status"] == "unresolved"
