from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class SearchCriteria:
    city: str
    state_region: str
    niche: str
    target_zip_code: str = ""
    target_radius_miles: int = 10
    radius_meters: int = 12000
    max_results: int = 20
    min_review_count: int = 0
    min_rating: float = 0.0
    include_no_website: bool = False
    include_weak_websites: bool = False
    include_low_search_position: bool = False
    include_review_growth_opportunities: bool = False
    run_pagespeed: bool = False
    run_rendered_audit: bool = False
    generate_screenshots: bool = False
    top_mockups: int = 3
    output_name: str = "demo-search"
    demo_mode: bool = False
    safe_live_test: bool = False
    google_data_depth: str = "Economy"

    @property
    def location_label(self) -> str:
        return f"{self.city}, {self.state_region}".strip(", ")


@dataclass(frozen=True)
class BusinessProfile:
    place_id: str
    name: str
    category: str
    address: str = ""
    phone: str = ""
    website: str = ""
    google_maps_url: str = ""
    yelp_url: str = ""
    rating: float | None = None
    review_count: int = 0
    business_types: list[str] = field(default_factory=list)
    has_hours: bool = False
    photo_count: int = 0
    latitude: float | None = None
    longitude: float | None = None
    search_position: int | None = None
    profile_verification_required: bool = True
    business_status: str = ""
    primary_type: str = ""
    pure_service_area_business: bool = False
    international_phone: str = ""
    current_hours_available: bool = False
    public_reviews: list[dict[str, Any]] = field(default_factory=list)
    price_level: str = ""
    price_range: dict[str, Any] = field(default_factory=dict)
    retrieved_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def google_details_retrieved(self) -> bool:
        """Whether costed rich Google fields were actually observed.

        An explicit marker wins. The fallback preserves compatibility with demo
        fixtures and profiles created before staged acquisition was introduced.
        """
        if "_details_retrieved" in self.raw:
            return bool(self.raw["_details_retrieved"])
        return bool(
            self.place_id.startswith("demo_")
            or self.phone
            or self.website
            or self.has_hours
            or self.photo_count
            or self.rating is not None
        )


@dataclass(frozen=True)
class VisibilityObservationCapture:
    """One ordered provider result, including results excluded from lead processing."""

    source_position: int
    page_number: int
    page_position: int
    place_id: str
    name: str
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    retained_position: int | None = None
    disposition: str = "accepted"
    exclusion_reason: str = ""
    distance_miles: float | None = None


@dataclass(frozen=True)
class SearchVisibilityAcquisition:
    """The immutable discovery evidence and the existing enriched processing set."""

    source: str
    query_text: str
    resolved_latitude: float | None
    resolved_longitude: float | None
    radius_meters: int
    requested_result_limit: int
    collection_status: str
    truncated: bool
    page_count: int
    raw_result_count: int
    retained_result_count: int
    selected_result_count: int
    observed_at: datetime
    profiles: tuple[BusinessProfile, ...]
    observations: tuple[VisibilityObservationCapture, ...]
    error_summary: str = ""
    attempt_id: str = field(default_factory=lambda: uuid4().hex)
    center_resolution_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebsiteAudit:
    url: str = ""
    reachable: bool = False
    status_code: int | None = None
    final_url: str = ""
    response_time_ms: int | None = None
    title: str = ""
    meta_description: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, int | float | str | None] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    rendered_checks: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    pagespeed_status: str = "not_run"
    rendered_status: str = "not_run"
    desktop_screenshot: str = ""
    mobile_screenshot: str = ""


@dataclass(frozen=True)
class ScoreFactor:
    key: str
    label: str
    points: int
    evidence: str


@dataclass(frozen=True)
class ScoreBreakdown:
    total: int
    priority: str
    factors: list[ScoreFactor]
    recommended_offer: str
    approach_angle: str
    target_signals: list[str] = field(default_factory=list)
    recommended_offer_id: str = ""


@dataclass(frozen=True)
class CompetitorMatch:
    place_id: str
    name: str
    score: int
    reason: str


@dataclass(frozen=True)
class StartingOfferInput:
    business_name: str
    niche: str
    city: str
    state_region: str = ""
    target_zip_code: str = ""
    target_radius_miles: int = 10
    phone: str = ""
    website: str = ""
    google_maps_url: str = ""
    yelp_url: str = ""
    current_rank_position: int | None = None
    review_count: int = 0
    rating: float | None = None
    competitor_names: list[str] = field(default_factory=list)
    competitor_review_average: int = 0
    competitor_website_average_score: int = 0
    target_signals: list[str] = field(default_factory=list)
    recommended_offer: str = ""
    past_sales_notes: str = ""
    recommended_offer_id: str = ""


@dataclass(frozen=True)
class StartingOffer:
    headline: str
    opening_angle: str
    offer_name: str
    price_range: str
    scope: list[str]
    proof_plan: list[str]
    first_ask: str
    risk_reversal: str
    talk_track: str
    offer_id: str = ""
    resolution_status: str = "resolved"
