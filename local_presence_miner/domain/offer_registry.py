from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique

# Increment when a change can alter resolved commercial meaning, scope, or
# price semantics. Version 4 hardens provider overlap, service territory and
# payable delivery authority. Version 5 reprices every offer to the November
# 2026 service catalog (stage quotes, realistic hours and acquisition route)
# and adds the catalog offers that v4 could not represent. B04 snapshots retain
# the version so historical drafts are not mistaken for current advice.
OFFER_REGISTRY_VERSION = 5


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
    # v5 catalog additions (service catalog section 3).
    PAID_FIX = "paid_fix"
    FIVE_PAGE_SERVICE_SITE = "five_page_service_site"
    FIVE_PAGE_B2B_SITE = "five_page_b2b_site"
    MULTI_LOCATION_SITE = "multi_location_site"
    PLATFORM_MIGRATION = "platform_migration"
    BOOKING_PAYMENTS_SETUP = "booking_payments_setup"
    WEBSITE_CARE_PLAN = "website_care_plan"
    TECHNICAL_SEO_REPAIR = "technical_seo_repair"
    LOCAL_SEO_SERVICE_PROJECT = "local_seo_service_project"
    AI_FACTUAL_BASELINE = "ai_factual_baseline"
    ESTIMATE_READY_INQUIRY = "estimate_ready_inquiry"
    CONSULTATION_PROJECT_PROOF = "consultation_project_proof"
    SIGN_QUOTE_INTAKE = "sign_quote_intake"
    SIGN_INTAKE_APPROVAL_BUNDLE = "sign_intake_approval_bundle"
    SITE_PROFILE_REVIEW_BUNDLE = "site_profile_review_bundle"
    SOURCE_LINKED_PRODUCTION_BATCH = "source_linked_production_batch"
    EDUCATOR_RESOURCE_LIBRARY = "educator_resource_library"


# Acquisition routes used by seller economics. "cold" = researched stranger,
# "warm" = introduction or existing relationship, "reached" = an owner already
# in conversation, where acquisition effort is already spent.
ACQUISITION_ROUTES = ("cold", "warm", "reached")
# Evidence behind the quote: "published" sits inside published competitor
# asks for similar scope; "adjacent" is a related service priced in another
# unit; "cost_modeled" has no comparable buyer price and is built from hours.
EVIDENCE_CLASSES = ("published", "adjacent", "cost_modeled")


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
    # Stage 1 (first clients) / Stage 2 (proven) / Stage 3 (established) quote
    # for the same scope. price_low/price_high mirror stages 1 and 3.
    stage_quotes: tuple[int, ...] = ()
    # Planning inputs for the seller walk-away floor. These are modeled
    # assumptions, not measured delivery times; replace with logged actuals.
    delivery_hours: float = 0.0
    project_cash: int = 0
    sample_hours: float = 0.0
    acquisition_route: str = "cold"
    billing: str = "project"
    evidence_class: str = "cost_modeled"

    @property
    def name(self) -> str:
        """Compatibility display property; identity is always ``offer_id``."""
        return self.display_name

    @property
    def price_range(self) -> str:
        suffix = "/mo" if self.billing == "monthly" else ""
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
        750,
        950,
        "Businesses with a decent site but an incomplete or inaccurate owner-authorized Google profile.",
        (
            "service/category rewrite",
            "photo plan",
            "hours and contact cleanup checklist",
            "review reply templates",
            "tracked website/contact link plan",
        ),
        "Start with public-profile completeness and easy trust improvements.",
        "google_presence",
        stage_quotes=(750, 850, 950),
        delivery_hours=5.0,
        project_cash=20,
        acquisition_route="reached",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.CONVERSION_TUNE_UP,
        "Conversion Tune-Up",
        (),
        950,
        1_300,
        "Businesses that already have a site but make calls, quotes, or trust harder than needed.",
        (
            "mobile call/quote button",
            "contact form cleanup",
            "homepage CTA rewrite",
            "review/testimonial section",
            "local SEO title/meta/H1 fixes",
        ),
        "Lead with one verified contact-path observation and a clearer mobile path.",
        "website_conversion",
        stage_quotes=(950, 1_100, 1_300),
        delivery_hours=7.0,
        project_cash=20,
        acquisition_route="reached",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.STARTER_LOCAL_PRESENCE_BUILD,
        "Starter Local Presence Build",
        ("Starter Site",),
        1_900,
        2_600,
        "Businesses with no website or a very weak website that want an owner-editable starting site.",
        (
            "three-page owner-editable website (home, services, contact)",
            "click-to-call and quote form",
            "services section",
            "reviews/proof section",
            "Google profile alignment checklist",
            "basic LocalBusiness schema",
            "client-owned accounts and a short editing handoff",
        ),
        "Lead with a verified contact-path gap and a site the owner can edit without a monthly provider.",
        "website_build",
        stage_quotes=(1_900, 2_200, 2_600),
        delivery_hours=18.0,
        project_cash=60,
        sample_hours=10.0,
        acquisition_route="warm",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.ONE_PAGE_CONVERSION_SITE,
        "One-Page Conversion Site + Google Cleanup",
        ("One Page Conversion Site", "One-Page Conversion Site"),
        1_950,
        2_650,
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
        stage_quotes=(1_950, 2_250, 2_650),
        delivery_hours=14.0,
        project_cash=30,
        sample_hours=10.0,
        acquisition_route="warm",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.FULL_LOCAL_AUTHORITY_SITE,
        "Full Local Authority Site",
        ("Ten-Page Site",),
        5_500,
        7_200,
        "Higher-value local services where up to ten pages of service, proof, and FAQ content are justified.",
        (
            "homepage",
            "service pages (up to ten pages in total)",
            "FAQ",
            "gallery/proof section",
            "schema",
            "analytics plan",
            "Google profile improvement plan",
        ),
        "Lead with competitor gap and a phased plan; quote only with one accountable decision-maker.",
        "website_build",
        stage_quotes=(5_500, 6_200, 7_200),
        delivery_hours=56.0,
        project_cash=200,
        sample_hours=10.0,
        acquisition_route="cold",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.REVIEW_TRUST_BUILDER,
        "Review Trust Builder",
        (),
        850,
        1_100,
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
        stage_quotes=(850, 950, 1_100),
        delivery_hours=6.0,
        project_cash=30,
        acquisition_route="reached",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.MONITORING_REVIEW_GROWTH,
        "Monitoring + Review Growth Plan",
        ("Review Growth Monitoring",),
        325,
        425,
        "Businesses with a sound baseline that need a light recurring improvement cadence (monthly).",
        (
            "public presence monitoring checklist",
            "review request and response workflow",
            "monthly contact-path review",
            "prioritized improvement notes",
        ),
        "Lead with a small, evidence-led maintenance plan rather than a rebuild.",
        "monitoring",
        stage_quotes=(325, 375, 425),
        delivery_hours=3.5,
        project_cash=25,
        acquisition_route="reached",
        billing="monthly",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.NO_TRACK_RECORD_PILOT,
        "No-Track-Record Pilot",
        ("No Track Record Pilot", "Paid First Step"),
        400,
        500,
        "Operators who are new and need honest first-client traction without giving work away.",
        (
            "paid public review with a written, prioritized fix plan",
            "a price for each recommended fix",
            "fee credited if a recommended project starts within 30 days",
            "permission to show the finished work requested (never traded for a review)",
        ),
        "Be transparent that you are early on paid client work; offer a small paid first step, not free work.",
        "pilot",
        stage_quotes=(400, 450, 500),
        delivery_hours=2.5,
        project_cash=0,
        acquisition_route="reached",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.PAID_FIX,
        "Paid Fix",
        ("Small Repair",),
        500,
        700,
        "An owner already reached who wants one specific, verified defect fixed.",
        (
            "one root cause on up to two URLs",
            "before/after test",
            "short written summary",
        ),
        "Offer a small paid fix for the verified observation instead of a free fix or a rebuild.",
        "website_conversion",
        stage_quotes=(500, 600, 700),
        delivery_hours=3.5,
        project_cash=10,
        acquisition_route="reached",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.FIVE_PAGE_SERVICE_SITE,
        "Five-Page Service Site + Booking Route",
        ("Five-Page Service Site",),
        3_400,
        4_500,
        "An established service business already planning a rebuild, with one decision-maker and an existing booking/inquiry tool.",
        (
            "five owner-editable pages (home, services, team, visit, contact/book)",
            "up to twelve services, six bios, fifteen approved photos, 2,000 edited words",
            "one existing booking link/embed and two owner-approved templates",
            "mobile/desktop and booking-route tests",
            "client-owned accounts, export and rollback, editing handoff",
        ),
        "Ask whether a rebuild is already planned; recommend this only when the owner has a rebuild trigger.",
        "website_build",
        stage_quotes=(3_400, 3_900, 4_500),
        delivery_hours=30.0,
        project_cash=90,
        sample_hours=10.0,
        acquisition_route="cold",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.FIVE_PAGE_B2B_SITE,
        "Five-Page B2B Site + Walkthrough Request",
        ("Five-Page B2B Site",),
        3_600,
        4_800,
        "An established B2B service company pursuing a defined facility or customer segment, with capacity to take it on.",
        (
            "five owner-editable B2B pages (home, two segments, proof/about, walkthrough/contact)",
            "facility-fit walkthrough request",
            "one-page capability sheet from supplied facts",
            "two follow-up templates and inquiry-scenario tests",
            "client-owned accounts and editing handoff",
        ),
        "Scope it around qualification, approved facts and tested handoff, never as just a website.",
        "website_build",
        stage_quotes=(3_600, 4_100, 4_800),
        delivery_hours=32.0,
        project_cash=110,
        sample_hours=10.0,
        acquisition_route="cold",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.MULTI_LOCATION_SITE,
        "Multi-Location Site",
        (),
        6_900,
        9_200,
        "One accountable buyer controlling several locations, profiles and one existing booking/inquiry route.",
        (
            "up to ten pages including three location pages",
            "three already-authorized profiles kept consistent",
            "one routing flow with up to three location branches",
            "up to twenty mapped redirects",
            "phased acceptance with written review gates",
        ),
        "Hold the quote until authority over every included location is confirmed.",
        "website_build",
        stage_quotes=(6_900, 7_900, 9_200),
        delivery_hours=70.0,
        project_cash=300,
        sample_hours=10.0,
        acquisition_route="cold",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.PLATFORM_MIGRATION,
        "Platform Migration",
        ("Site Migration",),
        1_800,
        2_500,
        "An owner leaving a managed or locked provider (e.g. UENI) for an owner-controlled platform; up to five pages of existing content.",
        (
            "rebuild up to five existing pages in the owner's account",
            "domain moved to an account in the owner's name before the old provider is cancelled",
            "redirect and email-dependency check",
            "one editing lesson and a 14-day defect window",
        ),
        "Confirm who controls the domain and the old provider's terms before quoting.",
        "website_build",
        stage_quotes=(1_800, 2_100, 2_500),
        delivery_hours=14.0,
        project_cash=60,
        acquisition_route="warm",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.BOOKING_PAYMENTS_SETUP,
        "Booking/Payments Setup",
        (),
        750,
        1_000,
        "An existing site that needs native booking or payments on the client's own plan.",
        (
            "native booking/payment configuration on the client's plan",
            "three end-to-end tests",
            "staff how-to",
        ),
        "Use the platform's built-in booking/payments; the client pays the plan directly.",
        "website_conversion",
        stage_quotes=(750, 850, 1_000),
        delivery_hours=6.0,
        project_cash=20,
        acquisition_route="reached",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.WEBSITE_CARE_PLAN,
        "Website Care Plan",
        (),
        249,
        349,
        "A delivered client who wants routine, capped upkeep instead of editing the site themselves (monthly).",
        (
            "monthly backup/export check",
            "form and link test",
            "one routine edit up to 45 minutes",
            "short change report",
        ),
        "Offer only after a delivered project; it is never required to keep ownership.",
        "monitoring",
        stage_quotes=(249, 299, 349),
        delivery_hours=2.5,
        project_cash=20,
        acquisition_route="reached",
        billing="monthly",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.TECHNICAL_SEO_REPAIR,
        "Technical SEO Repair",
        (),
        2_050,
        2_600,
        "A site with a specific, demonstrable crawl, indexing or on-page defect on important service URLs.",
        (
            "up to ten URLs and three agreed defect classes",
            "before/after verification",
            "rollback notes",
        ),
        "Show the exact defect first; never promise rankings or indexing timelines.",
        "search",
        stage_quotes=(2_050, 2_300, 2_600),
        delivery_hours=12.0,
        project_cash=30,
        sample_hours=4.0,
        acquisition_route="cold",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.LOCAL_SEO_SERVICE_PROJECT,
        "Local SEO Service Project",
        (),
        3_000,
        3_900,
        "A business that wants more of one specific service, with weak or inaccurate representation of it.",
        (
            "two approved service pages",
            "bounded technical and local checks",
            "profile factual alignment for that service",
        ),
        "Offer after a controlled practice sample; describe work completed, not ranking outcomes.",
        "search",
        stage_quotes=(3_000, 3_400, 3_900),
        delivery_hours=24.0,
        project_cash=90,
        sample_hours=8.0,
        acquisition_route="cold",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.AI_FACTUAL_BASELINE,
        "AI Factual Baseline Check",
        (),
        700,
        1_000,
        "A warm owner who wants to know whether AI assistants describe the business accurately.",
        (
            "ten questions across two AI systems, two runs each",
            "factual and crawl checks on five pages",
            "written findings with honest limits",
        ),
        "Never promise AI mentions or recommendations; sell the factual check and named corrections only.",
        "search",
        stage_quotes=(700, 850, 1_000),
        delivery_hours=5.0,
        project_cash=40,
        acquisition_route="warm",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.ESTIMATE_READY_INQUIRY,
        "Estimate-Ready Inquiry Setup",
        (),
        1_450,
        1_900,
        "A showroom or trade business whose inquiries arrive without the information needed to estimate.",
        (
            "one inquiry path with owner-approved questions",
            "optional photo upload and routing",
            "staff notes and test submissions",
        ),
        "Check the existing form and field-service tool before proposing a new path.",
        "website_conversion",
        stage_quotes=(1_450, 1_650, 1_900),
        delivery_hours=10.0,
        project_cash=30,
        acquisition_route="warm",
        evidence_class="cost_modeled",
    ),
    OfferDefinition(
        OfferID.CONSULTATION_PROJECT_PROOF,
        "Consultation Pages + Project Proof",
        (),
        3_200,
        4_100,
        "A flooring, cabinet or trade showroom with real completed projects and customers who arrive unprepared.",
        (
            "up to three consultation/service pages",
            "two genuine owner-approved project stories",
            "one existing consultation request path and a preparation message",
        ),
        "Use only owner-supplied projects and approved claims; no invented results.",
        "website_build",
        stage_quotes=(3_200, 3_600, 4_100),
        delivery_hours=26.0,
        project_cash=110,
        sample_hours=10.0,
        acquisition_route="cold",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.SIGN_QUOTE_INTAKE,
        "Sign/Print Quote Intake",
        (),
        2_550,
        3_200,
        "A sign or print shop whose requests repeatedly arrive missing specifications or artwork.",
        (
            "quote-ready page/form with up to twelve fields and three routing branches",
            "existing secure file-request destination",
            "acknowledgement template and staff triage checklist",
        ),
        "Check Printavo or the shop's own system first; a working native tool is a legitimate no-sale.",
        "workflow",
        stage_quotes=(2_550, 2_850, 3_200),
        delivery_hours=18.0,
        project_cash=70,
        sample_hours=6.0,
        acquisition_route="cold",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.SIGN_INTAKE_APPROVAL_BUNDLE,
        "Sign Intake + Approval/Reorder Bundle",
        (),
        3_400,
        4_300,
        "A sign or print shop with both incomplete requests and confused approvals or reorders.",
        (
            "quote intake (as Sign/Print Quote Intake)",
            "one connected approval or reorder path",
            "joint acceptance tests across both",
        ),
        "Bundle only when the owner confirms both connected problems.",
        "workflow",
        stage_quotes=(3_400, 3_800, 4_300),
        delivery_hours=30.0,
        project_cash=120,
        sample_hours=6.0,
        acquisition_route="cold",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.SITE_PROFILE_REVIEW_BUNDLE,
        "Site + Profile + Review Bundle",
        (),
        4_500,
        5_900,
        "A five-page site client whose Google profile and review process also need work.",
        (
            "five-page service site with existing booking route",
            "one-location profile accuracy cleanup",
            "one neutral review-request process",
        ),
        "Remove a component the business already manages well; never stack duplicate SEO work.",
        "website_build",
        stage_quotes=(4_500, 5_100, 5_900),
        delivery_hours=40.0,
        project_cash=160,
        sample_hours=10.0,
        acquisition_route="cold",
        evidence_class="published",
    ),
    OfferDefinition(
        OfferID.SOURCE_LINKED_PRODUCTION_BATCH,
        "Source-Linked Production Batch",
        (),
        1_450,
        1_900,
        "An established producer who wants verified, findable recordings (warm introduction only).",
        (
            "120 minutes across up to twelve files",
            "reviewed transcripts and a source manifest",
            "up to thirty index entries",
        ),
        "Compare against the strongest adequate transcription/review option; decline a full scope at a subcontract ceiling below the floor.",
        "content_handoff",
        stage_quotes=(1_450, 1_650, 1_900),
        delivery_hours=12.0,
        project_cash=35,
        sample_hours=4.0,
        acquisition_route="warm",
        evidence_class="adjacent",
    ),
    OfferDefinition(
        OfferID.EDUCATOR_RESOURCE_LIBRARY,
        "Educator Resource Library",
        (),
        1_950,
        2_500,
        "An established educator with reusable material and the right to reuse it (warm introduction only).",
        (
            "thirty assets organized and indexed",
            "access and rights checks",
            "handoff with a findability test",
        ),
        "Confirm rights and access rules before scoping.",
        "content_handoff",
        stage_quotes=(1_950, 2_200, 2_500),
        delivery_hours=20.0,
        project_cash=40,
        sample_hours=4.0,
        acquisition_route="warm",
        evidence_class="adjacent",
    ),
)


_RESEARCH_REQUIRED_LABELS = frozenset({"research first", "research required"})
_AMBIGUOUS_LEGACY_LABELS = frozenset({"website google presence improvement"})

OFFER_BY_ID: dict[OfferID, OfferDefinition] = {offer.offer_id: offer for offer in OFFER_DEFINITIONS}
if len(OFFER_BY_ID) != len(OFFER_DEFINITIONS):  # pragma: no cover - import-time invariant
    raise RuntimeError("Canonical offer IDs must be unique.")
for _offer in OFFER_DEFINITIONS:  # pragma: no cover - import-time invariant
    if len(_offer.stage_quotes) != 3 or (_offer.price_low, _offer.price_high) != (_offer.stage_quotes[0], _offer.stage_quotes[2]):
        raise RuntimeError(f"{_offer.offer_id}: price band must mirror stage quotes 1 and 3.")
    if _offer.acquisition_route not in ACQUISITION_ROUTES or _offer.evidence_class not in EVIDENCE_CLASSES:
        raise RuntimeError(f"{_offer.offer_id}: unknown acquisition route or evidence class.")
    if _offer.billing not in {"project", "monthly"} or _offer.delivery_hours <= 0:
        raise RuntimeError(f"{_offer.offer_id}: billing must be project/monthly with positive delivery hours.")


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
            "stage_quotes": list(offer.stage_quotes),
            "acquisition_route": offer.acquisition_route,
            "billing": offer.billing,
            "evidence_class": offer.evidence_class,
        }
        for offer in OFFER_DEFINITIONS
    ]
