from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from local_presence_miner.domain.models import SearchCriteria
from local_presence_miner.services.google_places import PLACES_URL, GooglePlacesClient, GooglePlacesError


class Response:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


def postal_place(
    postal_code: str = "80903",
    state_code: str = "CO",
    state_name: str = "Colorado",
    latitude: float = 38.8339,
    longitude: float = -104.8214,
) -> dict[str, Any]:
    """Documented Places (New) response shape, with synthetic observations."""
    return {
        "id": f"postal-{postal_code}",
        "displayName": {"text": postal_code},
        "types": ["postal_code", "political"],
        "formattedAddress": f"{state_name} {postal_code}, USA",
        "addressComponents": [
            {"longText": postal_code, "shortText": postal_code, "types": ["postal_code"]},
            {"longText": state_name, "shortText": state_code, "types": ["administrative_area_level_1", "political"]},
            {"longText": "United States", "shortText": "US", "types": ["country", "political"]},
        ],
        "location": {"latitude": latitude, "longitude": longitude},
    }


def provider_transport(monkeypatch, places: Any, *, next_page_token: str = "") -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_post(url, *, json, headers, timeout, allow_redirects):
        calls.append({"url": url, "payload": json, "headers": headers, "timeout": timeout, "allow_redirects": allow_redirects})
        if len(calls) == 1:
            return Response({"places": places, "nextPageToken": next_page_token})
        return Response({"places": []})

    monkeypatch.setattr("local_presence_miner.services.google_places.requests.post", fake_post)
    return calls


@pytest.mark.parametrize(
    ("city", "postal_code", "state_code", "state_name", "latitude", "longitude"),
    [
        ("Colorado Springs", "80903", "CO", "Colorado", 38.8339, -104.8214),
        ("Alamosa", "81101", "CO", "Colorado", 37.4694, -105.8700),
        # Synthetic 81003 provider point is inside the pinned Census polygon;
        # the former generic Pueblo city point was outside this ZCTA.
        ("Pueblo", "81003", "CO", "Colorado", 38.2760, -104.6120),
        ("Flint", "48502", "MI", "Michigan", 43.0125, -83.6875),
        ("Boston", "02108", "MA", "Massachusetts", 42.3570, -71.0637),
    ],
)
def test_supported_postal_identity_reaches_public_acquisition(
    monkeypatch, city, postal_code, state_code, state_name, latitude, longitude,
) -> None:
    place = postal_place(postal_code, state_code, state_name, latitude, longitude)
    calls = provider_transport(monkeypatch, [place])
    client = GooglePlacesClient("offline-test-key")
    acquisition = client.search_with_visibility(SearchCriteria(city, state_code, "roofers", target_zip_code=postal_code), enrich=False)

    assert acquisition.collection_status == "complete"
    assert (acquisition.resolved_latitude, acquisition.resolved_longitude) == (latitude, longitude)
    assert len(calls) == 2
    assert all(call["url"] == PLACES_URL and call["allow_redirects"] is False for call in calls)
    assert calls[0]["payload"]["textQuery"] == f"{postal_code}, {state_code}, United States"
    assert calls[0]["payload"]["regionCode"] == "US"
    assert "places.addressComponents" in calls[0]["headers"]["X-Goog-FieldMask"].split(",")
    assert "includedType" not in calls[0]["payload"]
    provenance = client.center_resolution_provenance
    assert acquisition.center_resolution_provenance == provenance
    assert provenance["status"] == "verified"
    assert provenance["method"] == "google_places_text_search_postal_address_components"
    assert provenance["requested_postal_code"] == postal_code
    assert provenance["matched_postal_code"] == postal_code
    assert provenance["matched_state_region"] == state_code
    assert provenance["matched_country_code"] == "US"
    assert provenance["provider_place_id"] == place["id"]
    assert provenance["provider_response"] == place
    assert provenance["observed_at"]
    assert "postal boundary" in provenance["limitations"].lower()


@pytest.mark.parametrize("fault", ["wrong_zip", "wrong_state", "wrong_country", "business", "mixed_business_type", "missing_identity", "missing_id"])
def test_mismatched_or_unrelated_postal_response_stops_before_discovery(monkeypatch, fault) -> None:
    place = postal_place()
    if fault == "wrong_zip":
        place["addressComponents"][0].update(longText="81003", shortText="81003")
    elif fault == "wrong_state":
        place["addressComponents"][1].update(longText="Florida", shortText="FL")
    elif fault == "wrong_country":
        place["addressComponents"][2].update(longText="Germany", shortText="DE")
    elif fault == "business":
        place["types"] = ["restaurant", "establishment"]
    elif fault == "mixed_business_type":
        place["types"].append("restaurant")
    elif fault == "missing_identity":
        del place["addressComponents"]
    else:
        del place["id"]
    calls = provider_transport(monkeypatch, [place])
    client = GooglePlacesClient("offline-test-key")

    with pytest.raises(GooglePlacesError, match="search center.*radius cannot be enforced safely"):
        client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)

    assert len(calls) == 1
    assert client.center_resolution_provenance["status"] == "unresolved"
    assert "provider_place_id" not in client.center_resolution_provenance


@pytest.mark.parametrize("component_index", [0, 1, 2])
def test_each_missing_or_conflicting_identity_component_fails_closed(monkeypatch, component_index) -> None:
    place = postal_place()
    del place["addressComponents"][component_index]
    calls = provider_transport(monkeypatch, [place])
    client = GooglePlacesClient("offline-test-key")
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(90.01, 0), (-90.01, 0), (0, 180.01), (0, -180.01), (float("nan"), 0), (0, float("inf")), (float("-inf"), 0),
     ("38.8339", -104.8214), (True, -104.8214), (None, -104.8214), (38.8339, None), ([], -104.8214)],
)
def test_invalid_coordinates_never_reach_discovery(monkeypatch, latitude, longitude) -> None:
    place = postal_place()
    place["location"] = {"latitude": latitude, "longitude": longitude}
    calls = provider_transport(monkeypatch, [place])
    client = GooglePlacesClient("offline-test-key")
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "fault", ["multiple_centers", "duplicate_postal_component", "conflicting_state_names", "conflicting_country_names", "truncated", "corrupt_places"],
)
def test_ambiguous_or_corrupt_resolution_has_no_centroid_fallback(monkeypatch, fault) -> None:
    place = postal_place()
    places: Any = [place]
    next_page_token = ""
    if fault == "multiple_centers":
        other = deepcopy(place)
        other["id"] = "another-center"
        other["location"]["latitude"] = 38.9
        places.append(other)
    elif fault == "duplicate_postal_component":
        place["addressComponents"].append({"longText": "81003", "shortText": "81003", "types": ["postal_code"]})
    elif fault == "conflicting_state_names":
        place["addressComponents"][1]["longText"] = "Florida"
    elif fault == "conflicting_country_names":
        place["addressComponents"][2]["longText"] = "Germany"
    elif fault == "truncated":
        next_page_token = "uninspected-centers"
    else:
        places = {"location": place["location"]}
    calls = provider_transport(monkeypatch, places, next_page_token=next_page_token)
    client = GooglePlacesClient("offline-test-key")
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)
    assert len(calls) == 1


def test_invalid_candidate_does_not_displace_one_verified_postal_center(monkeypatch) -> None:
    wrong = postal_place("81003")
    matching = postal_place()
    calls = provider_transport(monkeypatch, [wrong, matching])
    acquisition = GooglePlacesClient("offline-test-key").search_with_visibility(
        SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False,
    )
    assert (acquisition.resolved_latitude, acquisition.resolved_longitude) == (38.8339, -104.8214)
    assert len(calls) == 2


def test_full_state_name_matches_supported_state_identity(monkeypatch) -> None:
    provider_transport(monkeypatch, [postal_place()])
    acquisition = GooglePlacesClient("offline-test-key").search_with_visibility(
        SearchCriteria("Colorado Springs", "Colorado", "roofers", target_zip_code="80903"), enrich=False,
    )
    assert (acquisition.resolved_latitude, acquisition.resolved_longitude) == (38.8339, -104.8214)


def test_failed_attempt_clears_prior_verified_provenance(monkeypatch) -> None:
    client = GooglePlacesClient("offline-test-key")
    provider_transport(monkeypatch, [postal_place()])
    client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)
    calls = provider_transport(monkeypatch, [postal_place("81003")])
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)
    assert len(calls) == 1
    assert client.center_resolution_provenance["status"] == "unresolved"
    assert "matched_postal_code" not in client.center_resolution_provenance
    assert "provider_place_id" not in client.center_resolution_provenance


def test_provider_failure_remains_provider_failure_and_clears_prior_provenance(monkeypatch) -> None:
    client = GooglePlacesClient("offline-test-key")
    provider_transport(monkeypatch, [postal_place()])
    client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)

    def fail(_payload, _headers):
        raise GooglePlacesError("provider unavailable")

    monkeypatch.setattr(client, "_post_with_retry", fail)
    with pytest.raises(GooglePlacesError, match="provider unavailable") as stopped:
        client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)
    assert stopped.value.acquisition is None
    assert client.center_resolution_provenance["status"] == "provider_error"
    assert "provider_place_id" not in client.center_resolution_provenance


@pytest.mark.parametrize("fault", ["missing_api_key", "unsupported_radius"])
def test_public_failure_cannot_reuse_last_center_provenance(monkeypatch, fault) -> None:
    client = GooglePlacesClient("offline-test-key")
    provider_transport(monkeypatch, [postal_place()])
    client.search_with_visibility(SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903"), enrich=False)
    if fault == "missing_api_key":
        client.api_key = ""
    criteria = SearchCriteria("Colorado Springs", "CO", "roofers", target_zip_code="80903", radius_meters=60_000 if fault == "unsupported_radius" else 12000)
    with pytest.raises(GooglePlacesError):
        client.search_with_visibility(criteria, enrich=False)
    assert client.center_resolution_provenance == {}


def test_city_search_keeps_existing_query_and_locality_center(monkeypatch) -> None:
    place = {
        "id": "flint-city",
        "displayName": {"text": "Flint"},
        "types": ["locality", "political"],
        "formattedAddress": "Flint, MI, USA",
        "location": {"latitude": 43.0125, "longitude": -83.6875},
    }
    calls = provider_transport(monkeypatch, [place])
    acquisition = GooglePlacesClient("offline-test-key").search_with_visibility(SearchCriteria("Flint", "MI", "roofers"), enrich=False)
    assert (acquisition.resolved_latitude, acquisition.resolved_longitude) == (43.0125, -83.6875)
    assert calls[0]["payload"]["textQuery"] == "Flint, MI"
    assert len(calls) == 2


@pytest.mark.parametrize("fault", ["business", "invalid_coordinates"])
def test_city_search_rejects_business_centroid_or_invalid_coordinates(monkeypatch, fault) -> None:
    place = {
        "id": "flint-city",
        "types": ["locality"],
        "formattedAddress": "Flint, MI, USA",
        "location": {"latitude": 43.0125, "longitude": -83.6875},
    }
    if fault == "business":
        place["types"] = ["restaurant"]
    else:
        place["location"]["latitude"] = float("nan")
    calls = provider_transport(monkeypatch, [place])
    with pytest.raises(GooglePlacesError):
        GooglePlacesClient("offline-test-key").search_with_visibility(SearchCriteria("Flint", "MI", "roofers"), enrich=False)
    assert len(calls) == 1
