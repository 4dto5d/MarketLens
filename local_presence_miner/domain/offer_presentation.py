"""Canonical commercial presentation for the existing offer registry.

Evidence and conversation may explain or refine a scope, but selection origin
must not change the product family that the canonical Offer ID and price name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from local_presence_miner.domain.offer_registry import OfferID


@dataclass(frozen=True)
class CanonicalOfferPresentation:
    theme: str
    problem: str
    outcome: str
    first_scope: str
    supports_google_scope: bool = False


@dataclass(frozen=True)
class OfferConversationFraming:
    theme: str
    problem: str
    outcome: str
    first_scope: str


PRESENTATIONS: dict[OfferID, CanonicalOfferPresentation] = {
    OfferID.GOOGLE_PRESENCE_CLEANUP: CanonicalOfferPresentation(
        "Google presence",
        "observable public Google profile details need owner review",
        "a more complete, evidence-aligned public Google presence",
        "Public Google presence improvement plan based on observable fields",
        True,
    ),
    OfferID.CONVERSION_TUNE_UP: CanonicalOfferPresentation(
        "Conversion path",
        "the current website has observed contact or conversion friction",
        "a clearer path from interest to a real inquiry",
        "Homepage CTA and estimate/request flow",
    ),
    OfferID.STARTER_LOCAL_PRESENCE_BUILD: CanonicalOfferPresentation(
        "Digital foundation",
        "customers need a dependable business-owned page and clear contact path",
        "a credible, mobile-friendly landing and contact path",
        "Focused three-page, owner-editable local presence with a verified contact path",
        True,
    ),
    OfferID.ONE_PAGE_CONVERSION_SITE: CanonicalOfferPresentation(
        "Website conversion",
        "the public website and contact path need a focused rebuild",
        "a clearer one-page inquiry path aligned with the public Google profile",
        "One-page mobile-first conversion website and Google profile alignment",
        True,
    ),
    OfferID.FULL_LOCAL_AUTHORITY_SITE: CanonicalOfferPresentation(
        "Service visibility support",
        "service explanations and trust proof need a fuller business-owned site",
        "a more complete service explanation and contact path",
        "Service-page and local-intent content plan subject to owner confirmation",
        True,
    ),
    OfferID.REVIEW_TRUST_BUILDER: CanonicalOfferPresentation(
        "Trust proof",
        "verified customer proof needs clearer presentation and an owner-run review workflow",
        "stronger presentation of verified trust and review evidence",
        "Verified review and trust-proof presentation",
    ),
    OfferID.MONITORING_REVIEW_GROWTH: CanonicalOfferPresentation(
        "Public presence monitoring",
        "public profile and contact paths need a light recurring review cadence",
        "a maintained public presence and owner-run review workflow",
        "Public presence monitoring and review workflow",
    ),
    OfferID.NO_TRACK_RECORD_PILOT: CanonicalOfferPresentation(
        "Paid first step",
        "a first client project needs a transparent, bounded, paid starting point",
        "a prioritized fix plan the owner keeps, with a price for each fix",
        "Paid public review with a written fix plan (credited toward a project)",
    ),
    OfferID.PAID_FIX: CanonicalOfferPresentation(
        "Specific fix",
        "one verified public defect affects the customer path",
        "the verified defect corrected and tested",
        "One root-cause fix on up to two URLs with a before/after test",
    ),
    OfferID.FIVE_PAGE_SERVICE_SITE: CanonicalOfferPresentation(
        "Service website rebuild",
        "the owner is already planning a rebuild and the current site no longer fits the services or booking route",
        "an owner-editable five-page site connected to the existing booking/inquiry tool",
        "Five-page service site with the existing booking route, subject to owner confirmation",
        True,
    ),
    OfferID.FIVE_PAGE_B2B_SITE: CanonicalOfferPresentation(
        "B2B website rebuild",
        "the business is pursuing a defined segment and its site does not qualify or route those inquiries",
        "an owner-editable B2B site with a qualified walkthrough request and capability sheet",
        "Five-page B2B site with walkthrough request and capability sheet, subject to owner confirmation",
        True,
    ),
    OfferID.MULTI_LOCATION_SITE: CanonicalOfferPresentation(
        "Multi-location website",
        "location information and routing are inconsistent across several locations",
        "consistent location pages, profiles and one routing flow under one accountable buyer",
        "Phased multi-location site, held until authority over every location is confirmed",
        True,
    ),
    OfferID.PLATFORM_MIGRATION: CanonicalOfferPresentation(
        "Platform move",
        "the owner wants to leave a locked or managed provider without losing the domain or content",
        "the site rebuilt in accounts the owner controls, with the domain in the owner's name",
        "Domain-first migration of up to five existing pages to an owner-controlled platform",
    ),
    OfferID.BOOKING_PAYMENTS_SETUP: CanonicalOfferPresentation(
        "Booking and payments",
        "customers cannot book or pay through the owner's existing platform",
        "native booking/payments configured and tested on the client's own plan",
        "Native booking/payments setup with three end-to-end tests",
    ),
    OfferID.WEBSITE_CARE_PLAN: CanonicalOfferPresentation(
        "Website care",
        "a delivered site needs routine, capped upkeep",
        "monthly checks and one routine edit with a short report",
        "Capped monthly website care (optional; never required for ownership)",
    ),
    OfferID.TECHNICAL_SEO_REPAIR: CanonicalOfferPresentation(
        "Technical search repair",
        "a demonstrable crawl, indexing or on-page defect affects important service URLs",
        "the named defects corrected on up to ten URLs with before/after verification",
        "Technical repair of named defects on up to ten URLs (no ranking promise)",
    ),
    OfferID.LOCAL_SEO_SERVICE_PROJECT: CanonicalOfferPresentation(
        "Service-specific search",
        "a service the owner wants more of is weakly or inaccurately represented",
        "two approved service pages and aligned local facts for that service",
        "Two approved service pages with bounded technical and local checks",
        True,
    ),
    OfferID.AI_FACTUAL_BASELINE: CanonicalOfferPresentation(
        "AI factual accuracy",
        "the owner wants to know whether AI assistants describe the business accurately",
        "a reproducible factual baseline with honest limits",
        "Factual baseline across two AI systems plus crawl checks on five pages",
    ),
    OfferID.ESTIMATE_READY_INQUIRY: CanonicalOfferPresentation(
        "Estimate-ready inquiries",
        "inquiries arrive without the information needed to estimate",
        "one inquiry path that collects the owner-approved details",
        "One estimate-ready inquiry path with approved questions and routing",
    ),
    OfferID.CONSULTATION_PROJECT_PROOF: CanonicalOfferPresentation(
        "Consultation and project proof",
        "customers arrive unprepared and real completed projects are hard to evaluate",
        "consultation pages and two owner-approved project stories",
        "Consultation pages plus two owner-approved project stories",
        True,
    ),
    OfferID.SIGN_QUOTE_INTAKE: CanonicalOfferPresentation(
        "Quote intake",
        "quote requests repeatedly arrive missing specifications or artwork",
        "a quote path that collects the required specifications and files",
        "Quote-ready intake with routing, file request and triage checklist",
    ),
    OfferID.SIGN_INTAKE_APPROVAL_BUNDLE: CanonicalOfferPresentation(
        "Quote intake and approvals",
        "incomplete requests and confused approvals or reorders are connected problems",
        "a tested path from complete request to the approved or reordered job",
        "Quote intake plus one connected approval or reorder path",
    ),
    OfferID.SITE_PROFILE_REVIEW_BUNDLE: CanonicalOfferPresentation(
        "Website, profile and reviews",
        "the site, the Google profile and the review process all need work",
        "an owner-editable site with an accurate profile and a neutral review process",
        "Five-page site plus profile cleanup and a neutral review-request process",
        True,
    ),
    OfferID.SOURCE_LINKED_PRODUCTION_BATCH: CanonicalOfferPresentation(
        "Recording library",
        "approved versions and sources are hard to find and hand over",
        "a verified, source-linked recording batch with an index",
        "Source-linked 120-minute batch with reviewed transcripts and an index",
    ),
    OfferID.EDUCATOR_RESOURCE_LIBRARY: CanonicalOfferPresentation(
        "Resource library",
        "existing teaching material is hard to find and reuse",
        "an organized, rights-checked resource library",
        "Thirty-asset resource library with access and rights checks",
    ),
}


# These are product-bound refinements, never a second offer-selection system.
# A goal with no allowed refinement retains the canonical presentation.
CONVERSATION_FRAMINGS: dict[OfferID, dict[str, OfferConversationFraming]] = {
    OfferID.GOOGLE_PRESENCE_CLEANUP: {
        "lead_quality": OfferConversationFraming(
            "Google service fit", "the public profile should describe the right services more clearly",
            "clearer service/category cues for relevant local searchers", "Google service/category wording review",
        ),
        "intake": OfferConversationFraming(
            "Google contact clarity", "public phone, hours, or contact links may complicate inquiries",
            "a clearer public path to contact the business", "Public phone, hours, and contact-link cleanup",
        ),
        "trust": OfferConversationFraming(
            "Google trust presentation", "the public profile needs clearer verified trust cues",
            "better presentation of public photos and owner-run review responses",
            "Google photo and review-reply presentation",
        ),
    },
    OfferID.CONVERSION_TUNE_UP: {
        "lead_quality": OfferConversationFraming(
            "Lead quality", "the business wants better-fit inquiries rather than simply more inquiries",
            "clearer service-fit messaging and intake qualification on the existing website",
            "Service-fit messaging and inquiry qualification on the existing website",
        ),
        "intake": OfferConversationFraming(
            "Intake efficiency", "the current website intake path may create avoidable friction",
            "an easier, more structured inquiry path on the existing website",
            "Contact and estimate-flow simplification on the existing website",
        ),
        "trust": OfferConversationFraming(
            "Website trust proof", "the existing website needs clearer verified trust cues near its contact path",
            "stronger website proof that supports a credible inquiry",
            "Website review/testimonial section and contact-path trust cues",
        ),
    },
    OfferID.STARTER_LOCAL_PRESENCE_BUILD: {
        "lead_quality": OfferConversationFraming(
            "Starter-site service fit", "the new site should clarify which jobs the business wants",
            "a starter-site service explanation that supports better-fit inquiries",
            "Starter-site service-fit messaging and clear inquiry path",
        ),
        "intake": OfferConversationFraming(
            "Starter-site intake", "the new site needs a simple first-contact route",
            "an easier click-to-call and quote path on the new site",
            "Starter-site click-to-call and quote-flow setup",
        ),
        "trust": OfferConversationFraming(
            "Starter-site trust proof", "the new site should present verified customer proof clearly",
            "a credible starter-site proof and contact path", "Starter-site verified reviews/proof section",
        ),
    },
    OfferID.ONE_PAGE_CONVERSION_SITE: {
        "lead_quality": OfferConversationFraming(
            "One-page lead quality", "the replacement page should make service fit clear before inquiry",
            "a one-page path to better-fit inquiries", "One-page service-fit messaging and inquiry flow",
        ),
        "intake": OfferConversationFraming(
            "One-page intake", "the replacement page should simplify contact and estimate requests",
            "a clearer one-page estimate path", "One-page contact and estimate-flow design",
        ),
        "trust": OfferConversationFraming(
            "One-page trust proof", "the replacement page needs verified proof near the contact path",
            "a credible one-page proof and inquiry path", "One-page verified trust section",
        ),
    },
    OfferID.FULL_LOCAL_AUTHORITY_SITE: {
        "lead_quality": OfferConversationFraming(
            "Service-page lead quality", "service pages should clarify the jobs the business wants",
            "clearer service-fit paths to relevant inquiries", "Service-page messaging for better-fit inquiries",
        ),
        "intake": OfferConversationFraming(
            "Site intake clarity", "site contact and FAQ paths may leave buyer questions unresolved",
            "a clearer site-wide inquiry and FAQ path", "Site contact-path and FAQ intake clarification",
        ),
        "trust": OfferConversationFraming(
            "Site trust proof", "service pages need stronger verified examples and proof",
            "clearer service-specific proof on the business-owned site",
            "Site gallery/proof and service trust presentation",
        ),
    },
    OfferID.REVIEW_TRUST_BUILDER: {
        "trust": OfferConversationFraming(
            "Review trust", "verified customer proof needs clearer owner-run presentation",
            "stronger verified review and website proof presentation",
            "Verified review request and website proof presentation",
        ),
    },
    OfferID.MONITORING_REVIEW_GROWTH: {
        "intake": OfferConversationFraming(
            "Contact-path monitoring", "recurring contact-path friction needs a light review cadence",
            "a maintained public contact path with prioritized notes",
            "Monthly contact-path review with intake-friction notes",
        ),
        "trust": OfferConversationFraming(
            "Review workflow monitoring", "verified review proof needs a steady owner-run cadence",
            "a maintained review request and response workflow",
            "Owner-run review request and response cadence",
        ),
    },
    OfferID.NO_TRACK_RECORD_PILOT: {
        "lead_quality": OfferConversationFraming(
            "Service-fit first step", "a first project needs a bounded, paid review of service-fit messaging",
            "a written service-fit fix plan without performance promises",
            "Paid service-fit review with a written fix plan",
        ),
        "intake": OfferConversationFraming(
            "Intake first step", "a first project needs a bounded, paid review of the contact path",
            "a written intake fix plan without performance promises",
            "Paid intake review with a written fix plan",
        ),
        "trust": OfferConversationFraming(
            "Trust-proof first step", "a first project needs a bounded, paid review of verified proof",
            "a written trust-proof fix plan without performance promises",
            "Paid trust-proof review with a written fix plan",
        ),
    },
}


def presentation_for_offer(offer_id: str) -> CanonicalOfferPresentation | None:
    try:
        canonical_id = OfferID(offer_id)
    except ValueError:
        return None
    return PRESENTATIONS.get(canonical_id)


def conversation_focus(business_goal: str) -> str:
    goal = business_goal.casefold()
    matches = {
        "lead_quality": bool(re.search(
            r"\b(?:better[- ]fit|service[- ]fit)\b|"
            r"\b(?:high(?:er)?[- ]quality|quality|qualified)\s+(?:leads?|inquiries|jobs|prospects)\b",
            goal,
        )),
        "intake": bool(re.search(
            r"\bintake\b|\b(?:contact|quote|estimate|booking|inquiry|lead)[- ]"
            r"(?:form|flow|path|process|friction)\b",
            goal,
        )),
        "trust": bool(re.search(
            r"\b(?:trust|credibility|reputation)\b|"
            r"\b(?:verified\s+)?(?:reviews?|testimonials?|customer)\s+"
            r"(?:proof|presentation|showcase)\b",
            goal,
        )),
    }
    # Free text can describe several goals; never guess which one should lead.
    focused = [name for name, matched in matches.items() if matched]
    return focused[0] if len(focused) == 1 else ""


def conversation_framing_for_offer(offer_id: str, business_goal: str) -> OfferConversationFraming | None:
    focus = conversation_focus(business_goal)
    if not focus:
        return None
    try:
        canonical_id = OfferID(offer_id)
    except ValueError:
        return None
    return CONVERSATION_FRAMINGS.get(canonical_id, {}).get(focus)
