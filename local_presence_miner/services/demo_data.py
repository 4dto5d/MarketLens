from __future__ import annotations

import json
from pathlib import Path

from local_presence_miner.domain.models import BusinessProfile, SearchCriteria, WebsiteAudit
from local_presence_miner.time_utils import utc_now


def sample_data_path() -> Path:
    return Path(__file__).resolve().parents[2] / "sample_data" / "demo_businesses.json"


def load_demo_businesses(criteria: SearchCriteria) -> list[BusinessProfile]:
    data = json.loads(sample_data_path().read_text(encoding="utf-8"))
    profiles = []
    for item in data:
        profiles.append(
            BusinessProfile(
                place_id=item["place_id"],
                name=item["name"],
                category=criteria.niche,
                address=item["address"],
                phone=item["phone"],
                website=item["website"],
                google_maps_url=item["google_maps_url"],
                rating=item["rating"],
                review_count=item["review_count"],
                business_types=[criteria.niche, *item.get("business_types", [])],
                has_hours=item["has_hours"],
                photo_count=item["photo_count"],
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
                search_position=item.get("search_position"),
                profile_verification_required=True,
                business_status=item.get("business_status", "OPERATIONAL"),
                primary_type=item.get("primary_type", criteria.niche),
                pure_service_area_business=bool(item.get("pure_service_area_business", False)),
                international_phone=item.get("international_phone", ""),
                current_hours_available=bool(item.get("current_hours_available", item["has_hours"])),
                public_reviews=list(item.get("public_reviews", [])),
                price_level=item.get("price_level", ""),
                price_range=dict(item.get("price_range", {})),
                # Demo observations belong to this synthetic run; a fixed
                # calendar date made the demonstration silently expire.
                retrieved_at=utc_now().isoformat(),
                raw=item,
            )
        )
    return profiles[: criteria.max_results]


def demo_audit(profile: BusinessProfile) -> WebsiteAudit:
    if not profile.website:
        return WebsiteAudit(
            url="",
            reachable=False,
            checks={},
            weaknesses=["No website listed on the public profile."],
        )
    if "oldtown" in profile.website:
        return WebsiteAudit(
            url=profile.website,
            reachable=True,
            status_code=200,
            final_url=profile.website.replace("http://", "http://"),
            response_time_ms=1400,
            title="Old Town Roofing",
            meta_description="",
            checks={
                "https": False,
                "viewport": False,
                "has_title": True,
                "has_meta_description": False,
                "has_h1": True,
                "tap_to_call": False,
                "contact_form": False,
                "booking_or_quote_language": False,
                "service_pages": False,
                "trust_signals": False,
                "map_embed": False,
                "local_schema": False,
                "social_links": False,
                "clear_primary_cta": False,
                "local_wording": True,
            },
            weaknesses=[
                "No HTTPS on final URL.",
                "No mobile viewport tag found.",
                "No tap-to-call link detected.",
                "No contact or quote form detected.",
                "No visible reviews, gallery, or proof section.",
            ],
            strengths=["City wording is present."],
        )
    if "modern" in profile.website:
        return WebsiteAudit(
            url=profile.website,
            reachable=True,
            status_code=200,
            final_url=profile.website,
            response_time_ms=620,
            title="Modern Pro Roofers",
            meta_description="Roof repair and replacement in Flint.",
            checks={
                key: True
                for key in [
                    "https",
                    "viewport",
                    "has_title",
                    "has_meta_description",
                    "has_h1",
                    "tap_to_call",
                    "contact_form",
                    "booking_or_quote_language",
                    "service_pages",
                    "trust_signals",
                    "map_embed",
                    "local_schema",
                    "social_links",
                    "clear_primary_cta",
                    "local_wording",
                ]
            },
            strengths=["Strong CTA path.", "Trust proof appears above the fold.", "Local schema detected."],
        )
    strong_fast_site = "fast" in profile.name.lower() or "fast" in profile.website.lower()
    return WebsiteAudit(
        url=profile.website,
        reachable=True,
        status_code=200,
        final_url=profile.website,
        response_time_ms=980,
        title=profile.name,
        checks={
            "https": profile.website.startswith("https://"),
            "viewport": True,
            "has_title": True,
            "has_meta_description": False,
            "has_h1": True,
            "tap_to_call": strong_fast_site,
            "contact_form": strong_fast_site,
            "booking_or_quote_language": strong_fast_site,
            "service_pages": True,
            "trust_signals": strong_fast_site,
            "map_embed": strong_fast_site,
            "local_schema": strong_fast_site,
            "social_links": strong_fast_site,
            "clear_primary_cta": strong_fast_site,
            "local_wording": True,
        },
        weaknesses=[] if strong_fast_site else ["No contact form found.", "No LocalBusiness schema detected.", "Google map embed not detected."],
        strengths=["Strong public contact path.", "Trust and local proof are present."]
        if strong_fast_site
        else ["Service language appears on the page.", "Basic mobile viewport found."],
    )
