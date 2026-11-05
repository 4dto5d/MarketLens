from __future__ import annotations

import math
import re
import time
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import requests

from local_presence_miner.domain.competitor_matching import is_likely_chain
from local_presence_miner.domain.models import (
    BusinessProfile,
    SearchCriteria,
    SearchVisibilityAcquisition,
    VisibilityObservationCapture,
)
from local_presence_miner.domain.niche_taxonomy import commercial_class, niche_relation
from local_presence_miner.services.postal_geo_reference import validate_postal_coordinates

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
DISCOVERY_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.googleMapsUri",
        "places.businessStatus",
        "places.primaryType",
        "places.types",
        "places.location",
        "places.pureServiceAreaBusiness",
        "nextPageToken",
    ]
)
DETAIL_FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "nationalPhoneNumber",
        "internationalPhoneNumber",
        "websiteUri",
        "googleMapsUri",
        "rating",
        "userRatingCount",
        "businessStatus",
        "primaryType",
        "types",
        "regularOpeningHours",
        "currentOpeningHours",
        "photos",
        "location",
        "pureServiceAreaBusiness",
    ]
)
REVIEW_DETAILS_FIELD_MASK = DETAIL_FIELD_MASK + ",reviews"
FIELD_MASK = DISCOVERY_FIELD_MASK
ENRICHMENT_LIMITS = {"Economy": 8, "Balanced": 20, "Deep Prospecting": 40}
CENTER_FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.addressComponents,nextPageToken"
US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "AS": "American Samoa", "GU": "Guam", "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "AA": "Armed Forces Americas", "AE": "Armed Forces Europe", "AP": "Armed Forces Pacific",
}
POSTAL_CENTER_LIMITATIONS = (
    "Google's identified postal place supplies a search center, not a measured postal boundary or geometric ZIP centroid. "
    "The acquisition circle may cross ZIP boundaries; its result window is not universal Maps rank. "
    "Missing, ambiguous or mismatched provider identity stops acquisition. This ZIP workflow requires US country identity. "
    "Coordinates must also be compatible with the pinned offline 2020 Census ZCTA and state reference; "
    "that generalized reference is not a USPS postal boundary or proof of ZIP-wide result coverage. "
    "Unsupported ZIPs or ambiguous reference boundary points stop acquisition."
)


class GooglePlacesError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        acquisition: SearchVisibilityAcquisition | None = None,
    ) -> None:
        super().__init__(message)
        self.acquisition = acquisition


class GooglePlacesClient:
    def __init__(self, api_key: str, timeout_seconds: int = 12) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.center_resolution_provenance: dict[str, Any] = {}

    def search(self, criteria: SearchCriteria) -> list[BusinessProfile]:
        """Compatibility API returning the same enriched processing set as v0.1.15."""
        return list(self.search_with_visibility(criteria).profiles)

    def search_with_visibility(
        self,
        criteria: SearchCriteria,
        *,
        query_text_override: str | None = None,
        enrich: bool = True,
    ) -> SearchVisibilityAcquisition:
        self.center_resolution_provenance = {}
        if not self.api_key:
            raise GooglePlacesError("GOOGLE_MAPS_API_KEY is required unless demo mode is enabled.")
        if criteria.radius_meters > 50_000:
            raise GooglePlacesError("Google Places radius enforcement supports up to 30 miles per search. Use multiple nearby searches for a wider market.")

        query = query_text_override or f"{criteria.niche} in {criteria.location_label}"
        center = self.resolve_search_center(criteria)
        results: list[BusinessProfile] = []
        observations: list[VisibilityObservationCapture] = []
        seen: set[str] = set()
        discovery_cap = min(criteria.max_results, 60)
        page_token = ""
        attempts = 0
        page_number = 0
        source_position = 0
        observed_at = datetime.now(UTC)
        while len(results) < discovery_cap:
            payload: dict[str, Any] = {
                "textQuery": query,
                "pageSize": min(20, discovery_cap - len(results)),
                "includePureServiceAreaBusinesses": True,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": center[0], "longitude": center[1]},
                        "radius": float(criteria.radius_meters),
                    }
                },
            }
            if page_token:
                payload["pageToken"] = page_token
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": DISCOVERY_FIELD_MASK,
            }
            try:
                response = self._post_with_retry(payload, headers)
            except GooglePlacesError as exc:
                incomplete = SearchVisibilityAcquisition(
                    source="google_places_text_search",
                    query_text=query,
                    resolved_latitude=center[0],
                    resolved_longitude=center[1],
                    radius_meters=criteria.radius_meters,
                    requested_result_limit=discovery_cap,
                    collection_status="partial" if observations else "failed",
                    truncated=False,
                    page_count=page_number,
                    raw_result_count=len(observations),
                    retained_result_count=len(results),
                    selected_result_count=0,
                    observed_at=observed_at,
                    profiles=(),
                    observations=tuple(observations),
                    error_summary=str(exc)[:1000],
                    center_resolution_provenance=dict(self.center_resolution_provenance),
                )
                raise GooglePlacesError(str(exc), acquisition=incomplete) from exc
            data = response.json()
            page_number += 1
            for page_position, place in enumerate(data.get("places", []), start=1):
                source_position += 1
                profile = parse_place(place, criteria.niche)
                if profile.place_id in seen:
                    observations.append(
                        visibility_observation(
                            profile,
                            source_position,
                            page_number,
                            page_position,
                            disposition="duplicate",
                            exclusion_reason="Duplicate Place ID in this provider response window.",
                        )
                    )
                    continue
                if profile.latitude is None or profile.longitude is None:
                    observations.append(
                        visibility_observation(
                            profile,
                            source_position,
                            page_number,
                            page_position,
                            disposition="missing_coordinates",
                            exclusion_reason="Coordinates were unavailable, so radius eligibility is unknown.",
                        )
                    )
                    continue
                distance_miles = haversine_miles(center[0], center[1], profile.latitude, profile.longitude)
                if distance_miles > float(criteria.target_radius_miles):
                    observations.append(
                        visibility_observation(
                            profile,
                            source_position,
                            page_number,
                            page_position,
                            disposition="outside_radius",
                            exclusion_reason="Result was outside the requested target radius.",
                            distance_miles=distance_miles,
                        )
                    )
                    continue
                retained_position = len(results) + 1
                profile = replace(
                    profile,
                    search_position=retained_position,
                    raw={
                        **profile.raw,
                        "_distance_miles": round(distance_miles, 2),
                        "_radius_enforced": True,
                        "_source_result_position": source_position,
                    },
                )
                seen.add(profile.place_id)
                results.append(profile)
                observations.append(
                    visibility_observation(
                        profile,
                        source_position,
                        page_number,
                        page_position,
                        retained_position=retained_position,
                        distance_miles=distance_miles,
                    )
                )
            page_token = data.get("nextPageToken", "")
            if not page_token:
                break
            attempts += 1
            time.sleep(min(2 + attempts, 5))
        discovery_results = [
            replace(
                profile,
                raw={
                    **profile.raw,
                    "_details_retrieved": False,
                    "_detail_fields_requested": False,
                    "_google_data_depth": criteria.google_data_depth,
                },
            )
            for profile in results
        ]
        if not enrich:
            return SearchVisibilityAcquisition(
                source="google_places_text_search",
                query_text=query,
                resolved_latitude=center[0],
                resolved_longitude=center[1],
                radius_meters=criteria.radius_meters,
                requested_result_limit=discovery_cap,
                collection_status="complete",
                truncated=bool(page_token and len(results) >= discovery_cap),
                page_count=page_number,
                raw_result_count=len(observations),
                retained_result_count=len(discovery_results),
                selected_result_count=0,
                observed_at=observed_at,
                profiles=(),
                observations=tuple(observations),
                center_resolution_provenance=dict(self.center_resolution_provenance),
            )
        enrich_limit = rich_detail_limit(criteria, len(discovery_results))
        selected_ids = (
            {profile.place_id for profile in discovery_results}
            if criteria.safe_live_test
            else select_preliminary_candidates(discovery_results, criteria.niche, enrich_limit)
        )
        enriched: list[BusinessProfile] = []
        preliminary_ranking = preliminary_candidate_ranking(discovery_results, criteria.niche)
        for profile in discovery_results:
            profile = replace(
                profile,
                raw={
                    **profile.raw,
                    "_preliminary_candidate_score": preliminary_candidate_score(profile, criteria.niche),
                    "_preliminary_rank": preliminary_ranking[profile.place_id],
                    "_selected_for_details": profile.place_id in selected_ids,
                },
            )
            if profile.place_id not in selected_ids:
                continue
            if profile.place_id in selected_ids:
                try:
                    profile = self.details(profile)
                except GooglePlacesError as exc:
                    profile = replace(profile, raw={**profile.raw, "details_error": str(exc), "_detail_fields_requested": True})
            if profile.google_details_retrieved:
                if profile.review_count < criteria.min_review_count:
                    continue
                if profile.rating is not None and profile.rating < criteria.min_rating:
                    continue
            enriched.append(profile)
        return SearchVisibilityAcquisition(
            source="google_places_text_search",
            query_text=query,
            resolved_latitude=center[0],
            resolved_longitude=center[1],
            radius_meters=criteria.radius_meters,
            requested_result_limit=discovery_cap,
            collection_status="complete",
            truncated=bool(page_token and len(results) >= discovery_cap),
            page_count=page_number,
            raw_result_count=len(observations),
            retained_result_count=len(discovery_results),
            selected_result_count=len(enriched),
            center_resolution_provenance=dict(self.center_resolution_provenance),
            observed_at=observed_at,
            profiles=tuple(enriched),
            observations=tuple(observations),
        )

    def resolve_search_center(self, criteria: SearchCriteria) -> tuple[float, float]:
        postal_code = criteria.target_zip_code.strip()
        text_query = f"{postal_code}, {criteria.state_region.strip()}, United States" if postal_code else criteria.location_label
        self.center_resolution_provenance = {
            "status": "unresolved",
            "method": "google_places_text_search_postal_address_components" if postal_code else "google_places_text_search_locality",
            "requested_postal_code": postal_code,
            "requested_state_region": criteria.state_region.strip(),
            "requested_country_code": "US" if postal_code else "",
            "query_text": text_query,
            "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "limitations": POSTAL_CENTER_LIMITATIONS if postal_code else "City search center; no verified ZIP coverage or postal boundary is established.",
        }
        error_message = (
            f"Could not resolve a search center for {text_query!r}; radius cannot be enforced safely. "
            "A unique geographic result with valid coordinates and supported location identity is required."
        )
        if postal_code and (not re.fullmatch(r"[0-9]{5}", postal_code) or not us_state_code(criteria.state_region)):
            raise GooglePlacesError(error_message)
        payload: dict[str, Any] = {
            "textQuery": text_query,
            "pageSize": 5,
        }
        if postal_code:
            # regionCode affects formatting, not country enforcement. Identity is
            # checked from the response components below, never from this hint.
            payload.update(regionCode="US", languageCode="en")
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": CENTER_FIELD_MASK,
        }
        try:
            response = self._post_with_retry(payload, headers)
        except GooglePlacesError as exc:
            self.center_resolution_provenance.update(status="provider_error", error_summary=str(exc)[:1000])
            raise
        try:
            data = response.json()
        except ValueError as exc:
            raise GooglePlacesError(error_message) from exc
        places = data.get("places", []) if isinstance(data, dict) else None
        if not isinstance(places, list) or any(not isinstance(place, dict) for place in places):
            raise GooglePlacesError(error_message)
        self.center_resolution_provenance["candidate_count"] = len(places)
        if postal_code:
            # Documented Text Search response fields and address/coordinate types:
            # https://developers.google.com/maps/documentation/places/web-service/text-search
            # https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places
            # postal_code is a response/address type, not an includedType filter.
            # https://developers.google.com/maps/documentation/places/web-service/place-types
            if data.get("nextPageToken"):
                raise GooglePlacesError(error_message)
            matching = [place for place in places if verified_postal_center(place, criteria)]
            if len(matching) != 1:
                raise GooglePlacesError(error_message)
            place = matching[0]
            center = valid_place_coordinates(place)
            if center is None:
                raise GooglePlacesError(error_message)
            coordinate_reference = validate_postal_coordinates(postal_code, us_state_code(criteria.state_region), center[0], center[1])
            self.center_resolution_provenance["coordinate_reference"] = coordinate_reference
            if coordinate_reference["status"] != "compatible":
                raise GooglePlacesError(error_message)
            self.center_resolution_provenance.update(
                status="verified",
                matched_postal_code=postal_code,
                matched_state_region=us_state_code(criteria.state_region),
                matched_country_code="US",
                provider_place_id=place["id"],
                provider_response=deepcopy(place),
                resolved_latitude=center[0],
                resolved_longitude=center[1],
            )
            return center
        preferred_types = {"locality", "postal_town", "administrative_area_level_3"}
        geographic_places = [
            place for place in places
            if preferred_types.intersection(provider_types(place.get("types")))
            and provider_types(place.get("types")).issubset(preferred_types | {"political", "geocode"})
        ]
        ranked = sorted(
            geographic_places,
            key=lambda place: (
                0 if criteria.state_region.casefold() in str(place.get("formattedAddress", "")).casefold() else 1,
            ),
        )
        for place in ranked:
            center = valid_place_coordinates(place)
            if center is not None:
                self.center_resolution_provenance.update(
                    status="locality_coordinates",
                    provider_place_id=place.get("id", ""),
                    provider_response=deepcopy(place),
                    resolved_latitude=center[0],
                    resolved_longitude=center[1],
                )
                return center
        raise GooglePlacesError(error_message)

    def details(self, profile: BusinessProfile, *, include_review_samples: bool = False) -> BusinessProfile:
        if not profile.place_id:
            return profile
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": REVIEW_DETAILS_FIELD_MASK if include_review_samples else DETAIL_FIELD_MASK,
        }
        response = self._get_with_retry(PLACE_DETAILS_URL.format(place_id=profile.place_id), headers)
        rich = parse_place(response.json(), profile.category)
        values = {
            key: value
            for key, value in rich.__dict__.items()
            if value not in ("", None, [], {})
        }
        values["search_position"] = profile.search_position
        values["raw"] = {
            **profile.raw,
            **rich.raw,
            "_details_retrieved": True,
            "_detail_fields_requested": True,
        }
        return replace(profile, **values)

    def _post_with_retry(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.post(PLACES_URL, json=payload, headers=headers, timeout=self.timeout_seconds, allow_redirects=False)
                if response.status_code < 500:
                    if not response.ok or 300 <= response.status_code < 400:
                        raise GooglePlacesError(f"Google Places API error {response.status_code}: {response.text[:300]}")
                    return response
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(2**attempt)
        if last_error:
            raise GooglePlacesError(f"Google Places request failed: {last_error}") from last_error
        raise GooglePlacesError("Google Places request failed after retries.")

    def _get_with_retry(self, url: str, headers: dict[str, str]) -> requests.Response:
        from urllib.parse import urlsplit

        target = urlsplit(url)
        if target.scheme != "https" or target.netloc != "places.googleapis.com" or not target.path.startswith("/v1/places/"):
            raise GooglePlacesError("Only the fixed Google Places details endpoint is allowed.")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=self.timeout_seconds, allow_redirects=False)
                if response.status_code < 500:
                    if not response.ok or 300 <= response.status_code < 400:
                        raise GooglePlacesError(f"Google Places details error {response.status_code}: {response.text[:300]}")
                    return response
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(2**attempt)
        if last_error:
            raise GooglePlacesError(f"Google Places details request failed: {last_error}") from last_error
        raise GooglePlacesError("Google Places details request failed after retries.")


def provider_types(value: Any) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return set()
    return set(value)


def us_state_code(value: str) -> str:
    normalized = value.strip().casefold()
    return next((code for code, name in US_STATE_NAMES.items() if normalized in {code.casefold(), name.casefold()}), "")


def address_component_values(place: dict[str, Any], component_type: str) -> set[str]:
    components = place.get("addressComponents")
    if not isinstance(components, list) or any(not isinstance(component, dict) for component in components):
        return set()
    matching = [component for component in components if component_type in provider_types(component.get("types"))]
    if len(matching) != 1:
        return set()
    values = [matching[0].get(key, "") for key in ("longText", "shortText")]
    if any(not isinstance(value, str) for value in values):
        return set()
    return {value.strip().casefold() for value in values if value.strip()}


def verified_postal_center(place: dict[str, Any], criteria: SearchCriteria) -> bool:
    types = provider_types(place.get("types"))
    if "postal_code" not in types or not types.issubset({"postal_code", "political", "geocode"}):
        return False
    if not isinstance(place.get("id"), str) or not place["id"].strip():
        return False
    postal = address_component_values(place, "postal_code")
    state = address_component_values(place, "administrative_area_level_1")
    country = address_component_values(place, "country")
    state_code = us_state_code(criteria.state_region)
    state_names = {state_code.casefold(), US_STATE_NAMES.get(state_code, "").casefold()}
    return bool(
        postal == {criteria.target_zip_code.strip().casefold()}
        and state and state.issubset(state_names)
        and country and country.issubset({"us", "usa", "united states", "united states of america"})
    )


def valid_place_coordinates(place: dict[str, Any]) -> tuple[float, float] | None:
    location = place.get("location")
    if not isinstance(location, dict):
        return None
    latitude_value, longitude_value = location.get("latitude"), location.get("longitude")
    if isinstance(latitude_value, bool) or isinstance(longitude_value, bool):
        return None
    if not isinstance(latitude_value, (int, float)) or not isinstance(longitude_value, (int, float)):
        return None
    try:
        latitude, longitude = float(latitude_value), float(longitude_value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def parse_place(place: dict[str, Any], fallback_category: str) -> BusinessProfile:
    location = place.get("location") or {}
    return BusinessProfile(
        place_id=place.get("id", ""),
        name=(place.get("displayName") or {}).get("text", ""),
        category=(place.get("primaryTypeDisplayName") or {}).get("text", "") or fallback_category,
        address=place.get("formattedAddress", ""),
        phone=place.get("nationalPhoneNumber", ""),
        website=place.get("websiteUri", ""),
        google_maps_url=place.get("googleMapsUri", ""),
        rating=place.get("rating"),
        review_count=int(place.get("userRatingCount") or 0),
        business_types=list(place.get("types") or []),
        has_hours=bool(place.get("regularOpeningHours")),
        photo_count=len(place.get("photos") or []),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        business_status=place.get("businessStatus", ""),
        primary_type=place.get("primaryType", ""),
        pure_service_area_business=bool(place.get("pureServiceAreaBusiness")),
        international_phone=place.get("internationalPhoneNumber", ""),
        current_hours_available=bool(place.get("currentOpeningHours")),
        public_reviews=list(place.get("reviews") or []),
        price_level=place.get("priceLevel", ""),
        price_range=dict(place.get("priceRange") or {}),
        retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
        raw=place,
    )


def visibility_observation(
    profile: BusinessProfile,
    source_position: int,
    page_number: int,
    page_position: int,
    *,
    retained_position: int | None = None,
    disposition: str = "accepted",
    exclusion_reason: str = "",
    distance_miles: float | None = None,
) -> VisibilityObservationCapture:
    return VisibilityObservationCapture(
        source_position=source_position,
        page_number=page_number,
        page_position=page_position,
        place_id=profile.place_id,
        name=profile.name,
        address=profile.address,
        latitude=profile.latitude,
        longitude=profile.longitude,
        retained_position=retained_position,
        disposition=disposition,
        exclusion_reason=exclusion_reason,
        distance_miles=round(distance_miles, 2) if distance_miles is not None else None,
    )


def rich_detail_limit(criteria: SearchCriteria, result_count: int) -> int:
    if criteria.safe_live_test:
        return min(result_count, 5)
    return min(result_count, ENRICHMENT_LIMITS.get(criteria.google_data_depth, ENRICHMENT_LIMITS["Economy"]))


def estimate_places_api_calls(criteria: SearchCriteria) -> tuple[int, int, int]:
    """Return upper-bound Text Search, Place Details, and total request counts."""
    effective_results = min(criteria.max_results, 5) if criteria.safe_live_test else criteria.max_results
    discovery_calls = 1 + max(1, (min(effective_results, 60) + 19) // 20)  # center resolution + discovery pages
    detail_calls = rich_detail_limit(criteria, effective_results)
    return discovery_calls, detail_calls, discovery_calls + detail_calls


def select_preliminary_candidates(profiles: list[BusinessProfile], niche: str, limit: int) -> set[str]:
    ranked = sorted(
        profiles,
        key=lambda profile: (
            -preliminary_candidate_score(profile, niche),
            profile.search_position if profile.search_position is not None else 10_000,
            profile.place_id,
        ),
    )
    return {profile.place_id for profile in ranked[: max(0, limit)]}


def preliminary_candidate_ranking(profiles: list[BusinessProfile], niche: str) -> dict[str, int]:
    ranked = sorted(
        profiles,
        key=lambda profile: (
            -preliminary_candidate_score(profile, niche),
            profile.search_position if profile.search_position is not None else 10_000,
            profile.place_id,
        ),
    )
    return {profile.place_id: index for index, profile in enumerate(ranked, start=1)}


def preliminary_candidate_score(profile: BusinessProfile, niche: str) -> int:
    """Rank discovery candidates using only fields in the cheap field mask."""
    status = profile.business_status.upper()
    if status == "CLOSED_PERMANENTLY":
        return -100

    score = 0
    if status == "OPERATIONAL":
        score += 35
    elif status == "CLOSED_TEMPORARILY":
        score -= 25
    else:
        score += 5

    type_values = [profile.category, profile.primary_type, *profile.business_types]
    if any(niche_relation(niche, value) == "same" for value in type_values if value):
        score += 25
    elif profile.primary_type or profile.business_types:
        score += 8

    if profile.pure_service_area_business:
        score += 12
    elif profile.address:
        score += 10
    elif profile.latitude is not None and profile.longitude is not None:
        score += 6

    position = profile.search_position or 100
    score += max(0, 21 - position)

    classification = commercial_class(niche)
    if classification == "high":
        score += 15
    elif classification == "moderate":
        score += 10
    else:
        score += 4

    if is_likely_chain(profile.name):
        score -= 30
    return score


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
