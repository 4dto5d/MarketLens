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
        "Focused one-page local presence with a verified contact path",
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
        "Pilot",
        "a first client project needs a transparent, bounded demonstration",
        "a small verified improvement with an honest proof plan",
        "Fixed-scope public audit and one-page concept",
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
            "One-page service fit", "the new page should clarify which jobs the business wants",
            "a one-page service explanation that supports better-fit inquiries",
            "One-page service-fit messaging and clear inquiry path",
        ),
        "intake": OfferConversationFraming(
            "One-page intake", "the new page needs a simple first-contact route",
            "an easier click-to-call and quote path on the new page",
            "One-page click-to-call and quote-flow setup",
        ),
        "trust": OfferConversationFraming(
            "One-page trust proof", "the new page should present verified customer proof clearly",
            "a credible one-page proof and contact path", "One-page verified reviews/proof section",
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
            "Service-fit pilot", "a first project needs a bounded test of service-fit messaging",
            "a transparent one-page service-fit concept without performance promises",
            "Fixed-scope service-fit audit and one-page concept",
        ),
        "intake": OfferConversationFraming(
            "Intake pilot", "a first project needs a bounded contact-path demonstration",
            "a transparent one-page intake concept without performance promises",
            "Fixed-scope intake audit and one-page concept",
        ),
        "trust": OfferConversationFraming(
            "Trust-proof pilot", "a first project needs a bounded demonstration of verified proof",
            "a transparent one-page trust-proof concept without performance promises",
            "Fixed-scope trust-proof audit and one-page concept",
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
