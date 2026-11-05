from __future__ import annotations

from local_presence_miner.domain.intervention_assessment import InterventionEvidence, assess_interventions
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown, ScoreFactor, WebsiteAudit
from local_presence_miner.domain.offer_registry import offer_definition, resolve_offer

DEFAULT_SCORING_WEIGHTS: dict[str, int] = {
    "no_website": 35,
    "unreachable_website": 22,
    "weak_website": 12,
    "no_https": 8,
    "no_viewport": 8,
    "no_phone_cta": 8,
    "no_contact_form": 7,
    "no_booking_or_quote": 7,
    "missing_service_pages": 6,
    "missing_trust_signals": 6,
    "missing_local_schema": 5,
    "weak_google_info": 10,
    "low_photo_presence": 5,
    "competitor_gap": 10,
    "commercial_activity": 8,
    "low_search_position": 12,
    "review_growth_opportunity": 12,
    "verification_required": 4,
}


def score_lead(
    business: BusinessProfile,
    audit: WebsiteAudit,
    competitor_average_website_score: int = 0,
    weights: dict[str, int] | None = None,
) -> ScoreBreakdown:
    weights = weights or DEFAULT_SCORING_WEIGHTS
    factors: list[ScoreFactor] = []

    def add(key: str, label: str, evidence: str) -> None:
        points = weights.get(key, 0)
        if points:
            factors.append(ScoreFactor(key=key, label=label, points=points, evidence=evidence))

    checks = audit.checks
    details_retrieved = business.google_details_retrieved
    target_signals: list[str] = []
    if not business.website and details_retrieved:
        target_signals.append("No website listed")
        add("no_website", "No website listed", "The public Google-facing profile has no website URL.")
    elif business.website and website_evidence_state(audit) == "failed":
        target_signals.append("Website appears broken or unreachable")
        add("unreachable_website", "Website not reachable", f"Request failed or returned HTTP {audit.status_code}.")
    elif business.website and website_evidence_state(audit) == "observed":
        current_quality = website_quality_score(audit, has_website=True)
        if current_quality < 45:
            target_signals.append("Weak website")
            add("weak_website", "Weak website", f"The conservative website quality score is {current_quality}/100.")
        if not checks.get("https", False):
            add("no_https", "No HTTPS", "The final website URL does not use HTTPS.")
        if not checks.get("viewport", False):
            add("no_viewport", "Weak mobile readiness", "No viewport meta tag was detected.")
        if not checks.get("tap_to_call", False):
            add("no_phone_cta", "No tap-to-call CTA", "No tel: link was detected.")
        if not checks.get("contact_form", False):
            add("no_contact_form", "No contact form", "No obvious contact or quote form was detected.")
        if not checks.get("booking_or_quote_language", False):
            add("no_booking_or_quote", "No quote/booking language", "No clear request quote, book, schedule, or estimate wording.")
        if not checks.get("service_pages", False):
            add("missing_service_pages", "Missing service depth", "The site does not clearly expose service/menu pages.")
        if not checks.get("trust_signals", False):
            add("missing_trust_signals", "Missing trust signals", "Reviews, testimonials, gallery, or proof sections were weak or absent.")
        if not checks.get("local_schema", False):
            add("missing_local_schema", "Missing LocalBusiness schema", "No LocalBusiness or Organization schema was detected.")

    if details_retrieved and (not business.has_hours or business.photo_count < 5):
        target_signals.append("Profile appears incomplete")
        add("weak_google_info", "Profile appears incomplete", "Hours/photos/public business information appear limited.")
    if details_retrieved and business.photo_count < 5:
        add("low_photo_presence", "Few public photos", f"Detected public photo count: {business.photo_count}.")
    if business.profile_verification_required:
        target_signals.append("Google profile ownership needs manual verification")
        add(
            "verification_required",
            "Verification required",
            "The app cannot confirm whether the profile is claimed; human review is required before saying so.",
        )
    if business.search_position and business.search_position > 10:
        target_signals.append("Lower collected result position")
        add(
            "low_search_position",
            "Appears low in local search batch",
            f"This business was retained at candidate position {business.search_position} after MarketLens filters; "
            "this is not its source result or Maps rank.",
        )
    if details_retrieved and 0 <= business.review_count < 20:
        target_signals.append("Review growth opportunity")
        needed = max(0, 20 - business.review_count)
        add(
            "review_growth_opportunity",
            "Would benefit from 10-20 stronger reviews",
            f"Current public review count is {business.review_count}; about {needed} more would create stronger trust proof.",
        )

    website_score = website_quality_score(audit, has_website=bool(business.website))
    if (
        details_retrieved
        and competitor_average_website_score
        and website_evidence_state(audit) in {"observed", "failed"}
        and competitor_average_website_score - website_score >= 15
    ):
        add(
            "competitor_gap",
            "Competitors look stronger online",
            f"Competitor average website score is {competitor_average_website_score}; this lead scored {website_score}.",
        )

    if details_retrieved and business.review_count >= 8:
        add("commercial_activity", "Public review activity", f"{business.review_count} reviews are public proof, not measured current demand.")

    total = max(0, min(100, sum(f.points for f in factors)))
    priority = "A" if total >= 75 else "B" if total >= 55 else "C"
    offer_label = recommended_offer(business, audit, total)
    offer_resolution = resolve_offer(offer_label)
    return ScoreBreakdown(
        total=total,
        priority=priority,
        factors=factors,
        recommended_offer=offer_label,
        approach_angle=approach_angle(business, audit),
        target_signals=dedupe(target_signals),
        recommended_offer_id=offer_resolution.offer_id.value if offer_resolution.offer_id else "",
    )


def website_quality_score(audit: WebsiteAudit, has_website: bool = True) -> int:
    """Legacy numeric heuristic; callers must gate unknown audits first."""
    if not has_website:
        return 0
    if not audit.reachable:
        return 12
    checks = audit.checks
    positive = [
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
    passed = sum(1 for key in positive if checks.get(key, False))
    return round((passed / len(positive)) * 100)


def website_evidence_state(audit: WebsiteAudit) -> str:
    """Distinguish an unattempted audit from an observed HTTP/site failure."""
    from local_presence_miner.domain.website_evidence import capture_state

    state = capture_state(evidence=audit.evidence, url=audit.url, final_url=audit.final_url,
                          title=audit.title, status_code=audit.status_code)
    if audit.reachable and state in {"non_normal", "uncertain"}:
        return state
    if audit.reachable and audit.checks:
        return "observed"
    if audit.status_code is not None or (audit.url and any(audit.weaknesses)):
        return "failed"
    return "unknown"


def recommended_offer(business: BusinessProfile, audit: WebsiteAudit, total: int) -> str:
    # The legacy triage score is retained for Qualification compatibility, not
    # used as a buyer-value estimate or a scope/price switch. Collection-time
    # hints are assessed again against dated stored sources at planning time.
    details = business.google_details_retrieved and bool(business.retrieved_at)
    state = website_evidence_state(audit) if business.website else "absent" if details else "unknown"
    assessment = assess_interventions(InterventionEvidence(
        website_url=business.website, website_state=state, website_checks=audit.checks,
        website_refs=(f"collection_website:{audit.url}",) if audit.url else (),
        google_current=details, has_hours=business.has_hours if details else None,
        photo_count=business.photo_count if details else None, rating=business.rating if details else None,
        review_count=business.review_count if details else None,
        google_refs=(f"collection_google:{business.place_id}",) if details else (),
    ))
    return offer_definition(assessment.recommended_offer_id).display_name if assessment.recommended_offer_id else "Research-first"


def approach_angle(business: BusinessProfile, audit: WebsiteAudit) -> str:
    if not business.google_details_retrieved and not business.website:
        return "Retrieve rich public details before making a website, review, phone, hours, or photo claim."
    if not business.website:
        return "Lead with a free public-profile gap check and a simple one-page concept."
    if website_evidence_state(audit) == "unknown":
        return "Audit the linked website before claiming a website defect or offering a site-specific fix."
    if website_evidence_state(audit) == "failed":
        return "Lead with the broken/reachable-site issue and offer a low-risk repair audit."
    if website_evidence_state(audit) in {"non_normal", "uncertain"}:
        return "Validate the intended website, ownership, hosting and retrieval before proposing ordinary content or conversion work."
    if audit.checks.get("tap_to_call") is False:
        return "Verify the owner's preferred contact route before suggesting a bounded mobile/contact repair."
    if business.photo_count < 5:
        return "Lead with Google profile proof: photos, services, hours, and review replies."
    if business.review_count < 20:
        return "Ask whether the current genuine-feedback process supports the owner's trust goal; review volume alone is not a sales case."
    return "Review current evidence and the owner's goals; do not infer a paid opportunity from candidate order or a triage score."


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
