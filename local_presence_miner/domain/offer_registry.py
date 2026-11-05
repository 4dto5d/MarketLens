from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique

# Increment when a change can alter resolved commercial meaning, scope, or
# price semantics. Version 4 hardens provider overlap, service territory and
# payable delivery authority. B04 snapshots retain
# the version so historical drafts are not mistaken for current advice.
OFFER_REGISTRY_VERSION = 4


@unique
class OfferID(StrEnum):
    GOOGLE_PRESENCE_CLEANUP = "google_presence_cleanup"
    CONVERSION_TUNE_UP = "conversion_tune_up"
    STARTER_LOCAL_PRESENCE_BUILD = "starter_local_presence_build"
    ONE_PAGE_CONVERSION_SITE = "one_page_conversion_site"
    FULL_LOCAL_AUTHORITY_SITE = "full_local_authority_site"
    REVIEW_TRUST_BUILDER = "review_trust_builder"
    MONITORING_REVIEW_GROWTH = "monitoring_review_growth"
    NO_TRACK_RECORD_PILOT = "no_track_record_pilot"


@dataclass(frozen=True)
class OfferDefinition:
    offer_id: OfferID
    display_name: str
    legacy_aliases: tuple[str, ...]
    price_low: int
    price_high: int
    best_for: str
    deliverables: tuple[str, ...]
    pitch_angle: str
    semantic_family: str
    active: bool = True

    @property
    def name(self) -> str:
        """Compatibility display property; identity is always ``offer_id``."""
        return self.display_name

    @property
    def price_range(self) -> str:
        suffix = "+" if self.offer_id == OfferID.FULL_LOCAL_AUTHORITY_SITE else ""
        return f"${self.price_low:,}-${self.price_high:,}{suffix}"


@dataclass(frozen=True)
class OfferResolution:
    raw_label: str
    offer_id: OfferID | None
    status: str
    matched_alias: str = ""

    @property
    def resolved(self) -> bool:
        return self.offer_id is not None

    @property
    def definition(self) -> OfferDefinition | None:
        return OFFER_BY_ID.get(self.offer_id) if self.offer_id is not None else None


OFFER_DEFINITIONS: tuple[OfferDefinition, ...] = (
    OfferDefinition(
        OfferID.GOOGLE_PRESENCE_CLEANUP,
        "Google Presence Cleanup",
        ("Google Profile Cleanup",),
        250,
        600,
        "Businesses with a decent site but weak public profile completeness.",
        (
            "service/category rewrite",
            "photo plan",
            "hours and contact cleanup checklist",
            "review reply templates",
            "tracked website/contact link plan",
        ),
        "Start with public-profile completeness and easy trust improvements.",
        "google_presence",
    ),
    OfferDefinition(
        OfferID.CONVERSION_TUNE_UP,
        "Conversion Tune-Up",
        (),
        450,
        1_000,
        "Businesses that already have a site but make calls, quotes, or trust harder than needed.",
        (
            "mobile call/quote button",
            "contact form cleanup",
            "homepage CTA rewrite",
            "review/testimonial section",
            "local SEO title/meta/H1 fixes",
        ),
        "Lead with missed calls and a clearer mobile path.",
        "website_conversion",
    ),
    OfferDefinition(
        OfferID.STARTER_LOCAL_PRESENCE_BUILD,
        "Starter Local Presence Build",
        ("Starter Site",),
        750,
        1_800,
        "Businesses with no website or a very weak website.",
        (
            "one-page mobile-first website",
            "click-to-call and quote form",
            "services section",
            "reviews/proof section",
            "Google profile alignment checklist",
            "basic LocalBusiness schema",
        ),
        "Lead with a simple concept page that makes them look established and easy to contact.",
        "website_build",
    ),
    OfferDefinition(
        OfferID.ONE_PAGE_CONVERSION_SITE,
        "One-Page Conversion Site + Google Cleanup",
        ("One Page Conversion Site", "One-Page Conversion Site"),
        900,
        2_200,
        "Businesses with a broken or substantially weak site plus public-profile gaps.",
        (
            "one-page mobile-first conversion website",
            "clear click-to-call and estimate path",
            "services and trust sections",
            "Google profile alignment and cleanup plan",
            "basic LocalBusiness schema",
        ),
        "Lead with the documented website/contact gap and a focused rebuild rather than a broad redesign.",
        "website_build",
    ),
    OfferDefinition(
        OfferID.FULL_LOCAL_AUTHORITY_SITE,
        "Full Local Authority Site",
        (),
        2_000,
        5_000,
        "Higher-value local services where service pages, proof, and FAQ content can compound.",
        (
            "homepage",
            "service pages",
            "FAQ",
            "gallery/proof section",
            "schema",
            "analytics plan",
            "Google profile improvement plan",
        ),
        "Lead with competitor gap and a phased plan to beat the local average.",
        "website_build",
    ),
    OfferDefinition(
        OfferID.REVIEW_TRUST_BUILDER,
        "Review Trust Builder",
        (),
        300,
        900,
        "Small businesses that look real but need stronger public review proof.",
        (
            "review request script",
            "QR review card copy",
            "post-job text/email wording for the owner to send",
            "review reply templates",
            "website review/proof section",
            "Google profile review-response workflow",
        ),
        "Lead with trust and a compliant owner-operated review workflow.",
        "reviews",
    ),
    OfferDefinition(
        OfferID.MONITORING_REVIEW_GROWTH,
        "Monitoring + Review Growth Plan",
        ("Review Growth Monitoring",),
        150,
        500,
        "Businesses with a sound baseline that need a light recurring improvement cadence.",
        (
            "public presence monitoring checklist",
            "review request and response workflow",
            "monthly contact-path review",
            "prioritized improvement notes",
        ),
        "Lead with a small, evidence-led maintenance plan rather than a rebuild.",
        "monitoring",
    ),
    OfferDefinition(
        OfferID.NO_TRACK_RECORD_PILOT,
        "No-Track-Record Pilot",
        ("No Track Record Pilot",),
        300,
        900,
        "Operators who are new and need honest first-client traction.",
        (
            "free public audit",
            "one-page mockup or before/after wireframe",
            "fixed-scope cleanup",
            "permission to use anonymized before/after metrics",
            "simple testimonial request after delivery",
        ),
        "Be transparent that you are building a local portfolio and make the first step low risk.",
        "pilot",
    ),
)


_RESEARCH_REQUIRED_LABELS = frozenset({"research first", "research required"})
_AMBIGUOUS_LEGACY_LABELS = frozenset({"website google presence improvement"})

OFFER_BY_ID: dict[OfferID, OfferDefinition] = {offer.offer_id: offer for offer in OFFER_DEFINITIONS}
if len(OFFER_BY_ID) != len(OFFER_DEFINITIONS):  # pragma: no cover - import-time invariant
    raise RuntimeError("Canonical offer IDs must be unique.")


def normalize_offer_label(value: str) -> str:
    return " ".join((value or "").casefold().replace("_", " ").replace("-", " ").split())


def resolve_offer(raw_label: str = "", canonical_id: str | OfferID | None = None) -> OfferResolution:
    """Resolve only explicit IDs/display labels/declared aliases; never guess."""
    raw = (raw_label or "").strip()
    if canonical_id:
        canonical_text = str(canonical_id)
        if canonical_text == "research_first":
            return OfferResolution(raw, None, "research_required", canonical_text)
        try:
            offer_id = canonical_id if isinstance(canonical_id, OfferID) else OfferID(canonical_text)
        except ValueError:
            return OfferResolution(raw, None, "unmapped", canonical_text)
        return OfferResolution(raw, offer_id, "canonical_id", str(canonical_id))

    normalized = normalize_offer_label(raw)
    if not normalized:
        return OfferResolution(raw, None, "missing")
    if normalized in _RESEARCH_REQUIRED_LABELS:
        return OfferResolution(raw, None, "research_required", raw)
    if normalized in _AMBIGUOUS_LEGACY_LABELS:
        return OfferResolution(raw, None, "ambiguous", raw)
    for offer in OFFER_DEFINITIONS:
        if normalized == normalize_offer_label(offer.display_name):
            return OfferResolution(raw, offer.offer_id, "display_label", offer.display_name)
        for alias in offer.legacy_aliases:
            if normalized == normalize_offer_label(alias):
                return OfferResolution(raw, offer.offer_id, "legacy_alias", alias)
    return OfferResolution(raw, None, "unmapped")


def offer_definition(offer_id: str | OfferID) -> OfferDefinition:
    try:
        key = offer_id if isinstance(offer_id, OfferID) else OfferID(offer_id)
    except ValueError as exc:
        raise ValueError(f"Unknown canonical Offer ID: {offer_id!r}") from exc
    return OFFER_BY_ID[key]


def offer_registry_inventory() -> list[dict[str, object]]:
    return [
        {
            "offer_id": offer.offer_id.value,
            "display_name": offer.display_name,
            "legacy_aliases": list(offer.legacy_aliases),
            "semantic_family": offer.semantic_family,
            "price_low": offer.price_low,
            "price_high": offer.price_high,
            "active": offer.active,
        }
        for offer in OFFER_DEFINITIONS
    ]
