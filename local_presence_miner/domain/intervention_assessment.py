"""Bounded commercial judgments from observations, never estimated buyer ROI.

The adapter owns source eligibility, freshness and subject matching. This pure
layer additionally requires source references and explicit boolean observations.
It has no contact permission, persistence, pricing or human-selection authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from math import isfinite
from typing import Any, Literal

from local_presence_miner.domain.offer_registry import OfferID
from local_presence_miner.domain.owner_strategy import capacity_constrained, owner_fit_for_scope

ASSESSMENT_VERSION = 10
AssessmentState = Literal["recommended", "validate_first", "insufficient_evidence", "no_sale"]
CandidateStatus = Literal["recommended", "validate_first"]
Fit = Literal["High", "Moderate", "Low"]
Confidence = Literal["Moderate", "Low"]

COMMERCIAL_UNKNOWNS = (
    "Search demand, organic/Maps rank and difficulty are UNKNOWN unless backed by current query/geography-specific evidence.",
    "Relevant traffic, qualified-inquiry conversion and incremental revenue/ROI are UNKNOWN.",
    "Owner priorities, implementation access, budget and willingness to pay require confirmation.",
)


@dataclass(frozen=True)
class InterventionEvidence:
    website_url: str = ""
    website_state: str = "unknown"
    website_checks: dict[str, bool] = field(default_factory=dict)
    website_refs: tuple[str, ...] = ()
    google_current: bool = False
    has_hours: bool | None = None
    photo_count: int | None = None
    rating: float | None = None
    review_count: int | None = None
    google_gaps: tuple[str, ...] = ()
    google_refs: tuple[str, ...] = ()
    search_findings: tuple[dict, ...] = ()
    seo_research: dict = field(default_factory=dict)
    capacity_status: str = ""
    commercial_disposition: str = "UNKNOWN"
    business_goal: str = ""
    owner_strategy: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class InterventionCandidate:
    intervention_id: str
    offer_id: str
    status: CandidateStatus
    fit: Fit
    confidence: Confidence
    observations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    problem_hypothesis: str
    why_now: str
    why_over_alternatives: str
    expected_effect: str
    success_metric: str
    falsifier: str
    effort: str
    scope: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = COMMERCIAL_UNKNOWNS
    selected_service: str = ""
    selected_queries: tuple[str, ...] = ()
    selected_page_url: str = ""
    selected_evidence: dict = field(default_factory=dict)
    source_coverage: dict = field(default_factory=dict)
    owner_fit_status: str = "unknown"
    owner_fit_reason: str = ""
    owner_validation_question: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class InterventionAssessment:
    version: int
    state: AssessmentState
    recommended_offer_id: str
    confidence: Confidence
    summary: str
    ranked_candidates: tuple[InterventionCandidate, ...]
    unknowns: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    owner_fit_status: str = "unknown"
    owner_fit_reason: str = ""
    owner_validation_question: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _strings(values) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in values if isinstance(value, str) and value.strip()}))


def _number(value, *, integer: bool = False) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        return None
    if integer and (not isinstance(value, int)):
        return None
    return value


def _candidate(
    intervention_id: str, observations: tuple[str, ...], refs: tuple[str, ...], *,
    problem: str, why: str, contrast: str, effect: str, metric: str, falsifier: str,
    effort: str, offer_id: str = "", scope: tuple[str, ...] = (), fit: Fit = "Moderate",
    unknowns: tuple[str, ...] = (),
    selected_service: str = "", selected_queries: tuple[str, ...] = (), selected_page_url: str = "",
    selected_evidence: dict | None = None, source_coverage: dict | None = None,
) -> InterventionCandidate:
    return InterventionCandidate(
        intervention_id=intervention_id, offer_id=offer_id,
        status="recommended" if offer_id else "validate_first", fit=fit,
        confidence="Moderate" if offer_id else "Low", observations=_strings(observations),
        evidence_refs=_strings(refs), problem_hypothesis=problem, why_now=why,
        why_over_alternatives=contrast, expected_effect=effect, success_metric=metric,
        falsifier=falsifier, effort=effort, scope=scope if offer_id else (),
        unknowns=_strings((*COMMERCIAL_UNKNOWNS, *unknowns)),
        selected_service=selected_service, selected_queries=selected_queries,
        selected_page_url=selected_page_url, selected_evidence=selected_evidence or {},
        source_coverage=source_coverage or {},
    )


def _result(
    state: AssessmentState, summary: str, candidates: tuple[InterventionCandidate, ...] = (), *,
    confidence: Confidence = "Low", refs: tuple[str, ...] = (), unknowns: tuple[str, ...] = (),
) -> InterventionAssessment:
    if state != "recommended":
        # A higher-priority diagnosis suspends commercial scopes on alternatives
        # too, so downstream rendering cannot turn validation into an upsell.
        candidates = tuple(replace(item, offer_id="", status="validate_first", scope=(), confidence="Low") for item in candidates)
    return InterventionAssessment(
        version=ASSESSMENT_VERSION, state=state,
        recommended_offer_id=candidates[0].offer_id if state == "recommended" and candidates else "",
        confidence=confidence, summary=summary, ranked_candidates=candidates,
        unknowns=_strings((*COMMERCIAL_UNKNOWNS, *unknowns, *(value for item in candidates for value in item.unknowns))),
        evidence_refs=_strings((*refs, *(value for item in candidates for value in item.evidence_refs))),
        owner_fit_status=candidates[0].owner_fit_status if candidates else "unknown",
        owner_fit_reason=candidates[0].owner_fit_reason if candidates else "",
        owner_validation_question=candidates[0].owner_validation_question if candidates else "",
    )


def _search_observations(findings: tuple[dict, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Consume only the adapter's eligible gap projection; ignore invented metrics."""
    observations: list[str] = []
    refs: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("finding_type") not in {"local_coverage_gap", "service_query_gap"}:
            continue
        run_id = _number(finding.get("run_id"), integer=True)
        eligible = _number(finding.get("eligible_queries"), integer=True)
        affected = _number(finding.get("affected_queries"), integer=True)
        query_ids = _strings(finding.get("query_ids") or ())
        probes = tuple(value for value in finding.get("probe_ids", ()) if _number(value, integer=True) is not None and value > 0)
        if not run_id or not query_ids or not probes or not eligible or not affected or affected > eligible:
            continue
        if finding.get("organic_visibility") != "UNKNOWN" or finding.get("local_visibility") not in {
            "WEAK_IN_TRACKED_PLACES_WINDOWS", "ABSENT_IN_TRACKED_SERVICE_PLACES_WINDOWS",
        }:
            continue
        observations.append(f"Prospect absent in {affected} of {eligible} eligible tracked Places windows in run {run_id}.")
        refs.extend(f"run:{run_id}/query:{query_id}" for query_id in query_ids)
        refs.extend(f"probe:{probe}" for probe in probes)
    return _strings(observations), _strings(refs)


def assess_interventions(evidence: InterventionEvidence) -> InterventionAssessment:
    """Rank documented bottlenecks, using conservative categorical precedence.

    Diagnosis of a possible operational blocker precedes marketing spend. A
    directly observed contact defect precedes listing presentation; both precede
    unmeasured growth hypotheses. These are inspectable decision rules, not
    predictions of lift, value, demand, or a probability of success.
    """
    disposition = (evidence.commercial_disposition or "UNKNOWN").strip().upper()
    if disposition in {"NO_SELL", "CLOSED_WON", "CLOSED_LOST"}:
        return _result("no_sale", f"Recorded commercial disposition {disposition} does not support a new paid recommendation.",
                       refs=(f"owner_context:commercial_disposition:{disposition}",), confidence="Moderate")
    if disposition == "DEFERRED":
        return _result("validate_first", "Confirm the owner's timing and capacity goal before proposing paid work.",
                       refs=("owner_context:commercial_disposition",),
                       unknowns=("Whether an existing operational need warrants work despite the recorded timing or capacity constraint is UNKNOWN.",))

    website_refs = _strings(evidence.website_refs)
    google_refs = _strings(evidence.google_refs)
    website_observed = evidence.website_state == "observed" and bool(evidence.website_url.strip()) and bool(website_refs)
    checks = {
        key: value for key, value in evidence.website_checks.items() if type(value) is bool
    } if website_observed else {}
    google_current = evidence.google_current is True and bool(google_refs)
    hours = evidence.has_hours if google_current and type(evidence.has_hours) is bool else None
    photos = _number(evidence.photo_count, integer=True) if google_current else None
    reviews = _number(evidence.review_count, integer=True) if google_current else None
    rating = _number(evidence.rating) if google_current else None
    if rating is not None and not 1 <= rating <= 5:
        rating = None
    candidates: list[InterventionCandidate] = []

    if rating is not None and reviews is not None and reviews >= 10 and rating < 3.5:
        candidates.append(_candidate(
            "reputation_diagnosis", (f"Public rating is {rating:.1f} across {reviews} reviews.",), google_refs,
            problem="Customer service or fulfillment problems may be the bottleneck; acquiring more reviews may not solve them.",
            why="The current substantial low-rating sample warrants examining causes before promoting the business.",
            contrast="Understanding recurring customer problems precedes cosmetic site work or a review-generation campaign.",
            effect="Identify actionable service and response problems before deciding whether a paid intervention fits.",
            metric="Track recurring complaint themes, resolution rate and subsequent genuine customer feedback against a baseline.",
            falsifier="Current reviews describe resolved historical issues or incorrect attribution, with independently verified recent service recovery.",
            effort="Diagnosis first; remediation effort is UNKNOWN.", fit="High",
        ))

    if evidence.website_state in {"failed", "absent"} and (
        evidence.website_state == "failed" and website_refs or evidence.website_state == "absent" and google_current
    ):
        absent = evidence.website_state == "absent"
        candidates.append(_candidate(
            "website_need_validation" if absent else "website_access_diagnosis",
            ("No business website was listed in the current public source." if absent else
             "The recorded website request failed; customer reachability is unconfirmed.",),
            google_refs if absent else website_refs,
            problem="The business may lack a useful owned contact page, or the collection method may have missed an existing working route.",
            why="Verify the current customer journey and owner preference before deciding whether a new site or repair is useful.",
            contrast="A missing listing or failed request cannot justify buying a replacement website.",
            effect="Establish whether customers actually lack a dependable route and whether the owner wants one.",
            metric="Verify owner-approved contact routes on real devices and record existing qualified inquiry sources.",
            falsifier="An existing website, phone, booking platform or referral route already serves the owner's needs.",
            effort="Small verification step; any subsequent implementation scope is UNKNOWN.",
        ))

    technical = [key for key in ("https", "indexable_sample") if checks.get(key) is False]
    if technical:
        candidates.append(_candidate(
            "technical_validation", tuple(f"Website audit explicitly recorded {key}=False." for key in technical), website_refs,
            problem="Transport or indexability configuration may block the intended customer or discovery path.",
            why="Confirm the audit observation and configuration intent before spending on content or promotion.",
            contrast="A bounded configuration diagnosis is more defensible than a rebuild or an assumed SEO growth program.",
            effect="Confirm and, if unintended, remove a specific configuration barrier.",
            metric="Recheck the intended HTTPS/indexability behavior and then monitor relevant indexed pages and qualified referrals.",
            falsifier="The setting is intentional, the audit sampled an excluded page, or a fresh customer-visible check disproves the defect.",
            effort="Diagnosis first; access and implementation difficulty are UNKNOWN.",
        ))

    no_route = all(checks.get(key) is False for key in ("sitewide_contact_path", "tap_to_call", "contact_form"))
    mobile_friction = checks.get("viewport") is False and (
        checks.get("tap_to_call") is False or checks.get("clear_primary_cta") is False
    )
    if no_route or mobile_friction:
        observed_keys = ("sitewide_contact_path", "tap_to_call", "contact_form", "viewport", "clear_primary_cta")
        candidates.append(_candidate(
            "contact_path_repair", tuple(f"Website audit explicitly recorded {key}=False." for key in observed_keys if checks.get(key) is False),
            website_refs, offer_id=OfferID.CONVERSION_TUNE_UP.value,
            scope=("mobile call/quote button", "homepage CTA rewrite"), fit="High",
            problem="The sampled contact or mobile path may make intended inquiries unnecessarily difficult.",
            why="A specific current customer-path defect can be checked and repaired in a small scope.",
            contrast="A contact-path repair addresses the observed route directly; a rebuild or more visibility has no established incremental advantage.",
            effect="Make the owner's preferred contact action easier; any increase in qualified inquiries remains a hypothesis.",
            metric="Verify the intended action works, then compare qualified inquiries per relevant visit with an owner-approved baseline.",
            falsifier="The owner-preferred route already works, relevant traffic is negligible, or the apparent defect does not affect customer tasks.",
            effort="Small bounded repair, subject to platform access and owner confirmation.",
            unknowns=("The preferred contact route and whether this is the actual conversion bottleneck are UNKNOWN.",),
            selected_page_url=evidence.website_url,
        ))

    # Rich search evidence is an input to the established intervention policy,
    # not a second offer system. Actual contact/operational blockers stay first.
    seo_candidates = _seo_candidates(evidence.seo_research, website_observed)
    candidates.extend(item for item in seo_candidates if item.intervention_id.startswith("seo_technical_repair:"))

    listing_observations: list[str] = []
    listing_scope: list[str] = []
    if hours is False:
        listing_observations.append("Public hours were not returned in the current Google observation.")
        listing_scope.append("hours and contact cleanup checklist")
    if photos == 0:
        listing_observations.append("The current Google observation returned zero public photo references.")
        listing_scope.append("photo plan")
    if listing_observations:
        candidates.append(_candidate(
            "listing_correction", tuple(listing_observations), google_refs,
            offer_id=OfferID.GOOGLE_PRESENCE_CLEANUP.value, scope=tuple(listing_scope),
            problem="Public listing details may leave customers without practical hours or visual context.",
            why="A specific current public-field gap supports a narrow owner-authorized verification and correction checklist.",
            contrast="A listing checklist addresses the observed fields with less work than replacing a functioning website or commissioning speculative SEO.",
            effect="Confirm and improve accurate public presentation; no ranking or demand improvement is established.",
            metric="Confirm correct intended public fields and track qualified listing-referred inquiries if the owner can measure them.",
            falsifier="The public fields are already correct, the provider omitted them, or the business intentionally does not publish them.",
            effort="Small checklist/photo-planning scope; owner access and actual corrections require confirmation.",
        ))

    # Independent listing observations may still support their narrow scope;
    # this capture alone never supports ordinary website content repair.
    if evidence.website_state in {"non_normal", "uncertain"} and website_refs:
        candidates.append(_candidate(
            "website_response_validation", (f"Captured website response eligibility is {evidence.website_state}.",), website_refs,
            problem="The captured response may be an interstitial, placeholder, platform failure or insufficient HTML, not the intended business page.",
            why="Verify site availability, ownership, hosting and retrieval before diagnosing normal content.",
            contrast="Missing controls on an ineligible capture are not evidence that the intended business site needs CTA or SEO repairs.",
            effect="Establish the intended customer-visible website and obtain eligible observations before considering website work.",
            metric="Record an owner-confirmed working route and a fresh normal business-page capture.",
            falsifier="A fresh eligible response demonstrates the functioning intended website.",
            effort="Validation first; recovery or content scope and price remain UNKNOWN.",
        ))

    # An unpriced Maps hypothesis must not suppress a directly observed narrow
    # listing correction. Attach the query evidence only when that same local
    # channel diagnosis explains the current checklist, without claiming cause.
    local_refs = _strings(ref for item in seo_candidates if item.intervention_id.startswith("seo_local_profile:")
                          for ref in item.evidence_refs)
    if local_refs and listing_observations:
        candidates = [replace(item, evidence_refs=_strings((*item.evidence_refs, *local_refs)))
                      if item.intervention_id == "listing_correction" else item for item in candidates]
    candidates.extend(item for item in seo_candidates if not item.intervention_id.startswith("seo_technical_repair:"))

    if reviews is not None and reviews < 20 and not (rating is not None and rating < 3.5):
        goal = " ".join((evidence.business_goal or "").casefold().split())
        trust_goal = goal in {"build trust", "more reviews", "improve reputation", "review growth", "trust proof", "stronger public proof"}
        supported = trust_goal and rating is not None and rating >= 4.0
        candidates.append(_candidate(
            "review_workflow", (f"The current public profile has {reviews} reviews; volume alone does not establish a commercial problem.",),
            (*google_refs, *(("owner_context:business_goal",) if trust_goal else ())),
            offer_id=OfferID.REVIEW_TRUST_BUILDER.value if supported else "",
            scope=("review request script", "post-job text/email wording for the owner to send", "Google profile review-response workflow"),
            problem="An inconsistent owner-run request process may underrepresent customer proof; business age and completed-job volume are unmeasured.",
            why="Confirm the owner wants stronger public proof and can request genuine feedback from completed customers.",
            contrast="A review workflow fits an explicit trust goal and positive feedback; low volume alone does not justify a new website or a campaign.",
            effect="Make lawful, nonselective feedback requests and responses consistent without promising a review count or rating.",
            metric="Track eligible completed jobs offered a feedback request, genuine response rate and owner response coverage.",
            falsifier="The business has few completed jobs, already requests feedback consistently, or poor service explains the evidence.",
            effort="Small owner-operated workflow after process and customer-consent validation.",
            unknowns=("Business age, completed-job volume and the current review-request workflow are UNKNOWN.",),
        ))

    seo_dominant = (
        evidence.seo_research.get("state") == "complete"
        and bool(evidence.seo_research.get("opportunities"))
        and all(item.get("decision") == "no_sale" for item in evidence.seo_research["opportunities"])
    )
    if not seo_candidates and not seo_dominant and (
        checks.get("service_pages") is False or checks.get("sitewide_service_depth") is False
    ):
        candidates.append(_candidate(
            "service_content_validation", ("The website audit did not detect sufficient service-page content in its bounded sample.",), website_refs,
            problem="Customers may lack an explanation of a commercially useful service, but service demand and profitability are unknown.",
            why="Verify the missing service explanation and owner-prioritized service before commissioning pages.",
            contrast="Validate one service need before paying for a full site or assuming Places absence proves an organic-content problem.",
            effect="Identify whether a specific useful page can answer a real customer question or support a viable service.",
            metric="Measure qualified service inquiries and relevant landing-page engagement after establishing a baseline.",
            falsifier="Existing pages already answer the question, demand is negligible, or the business cannot profitably deliver the service.",
            effort="Small service/demand validation step; page scope is not established.",
        ))

    search_observations, search_refs = _search_observations(evidence.search_findings)
    if search_observations:
        # Attach the bounded observation, not a rank/demand/value bonus. When
        # an explanation uses this sample its identity must expire with it.
        candidates = [replace(item, observations=_strings((*item.observations, *search_observations)),
                              evidence_refs=_strings((*item.evidence_refs, *search_refs)))
                      if item.intervention_id == "listing_correction" else item for item in candidates]
        candidates.append(_candidate(
            "search_opportunity_validation", search_observations, search_refs,
            problem="The business did not appear in selected Places windows; the economic significance is unmeasured.",
            why="Use the recorded queries to check service relevance, owner priorities and actual inquiry demand before proposing growth spend.",
            contrast="Tracked absence and recurring competitors do not establish organic rank, customer demand, ranking difficulty or a need to rebuild.",
            effect="Determine whether a measurable and commercially useful visibility opportunity exists.",
            metric="Validate relevant service demand and qualified search-referred inquiries; monitor comparable Places windows separately.",
            falsifier="Queries have little relevant demand, target unprofitable services, or a comparable fresh observation contradicts the gap.",
            effort="Validation first; competitive cost and time to impact are UNKNOWN.",
        ))

    if google_current and evidence.google_gaps and not listing_observations and not any(
        item.intervention_id in {"reputation_diagnosis", "review_workflow"} for item in candidates
    ):
        candidates.append(_candidate(
            "public_observation_validation", _strings(evidence.google_gaps), google_refs,
            problem="The assessment contains public-gap descriptions without enough structured facts to select a paid intervention.",
            why="Verify the specific source observation and its practical consequence.",
            contrast="Recorded prose does not establish a service scope or justify substituting a generic package.",
            effect="Resolve whether a meaningful, correctable public issue exists.",
            metric="Record a source-backed before/after check for the claimed field and establish its customer consequence.",
            falsifier="A direct current check disproves the description or the condition is intentional and harmless.",
            effort="Small verification step; paid scope is UNKNOWN.",
        ))

    if candidates:
        candidates = [_apply_owner_fit(item, evidence) for item in candidates]
        # Within the same SEO tier, a supported wanted service precedes a scope
        # the owner has excluded. Operational/reputation precedence stays intact.
        seo_positions = [index for index, item in enumerate(candidates)
                         if item.intervention_id.startswith("seo_") and not item.intervention_id.startswith("seo_technical_repair:")]
        seo_ranked = sorted((candidates[index] for index in seo_positions), key=lambda item: item.status != "recommended")
        for index, item in zip(seo_positions, seo_ranked, strict=True):
            candidates[index] = item
        # Preserve explicit bottleneck precedence; no incumbent package or sales
        # score participates. Lower-ranked entries remain inspectable alternatives.
        first = candidates[0]
        return _result(first.status, (first.owner_fit_reason if first.owner_fit_status == "conflict" else (
            f"Recommend a bounded {first.intervention_id.replace('_', ' ')}; validate the business effect with the owner."
            if first.status == "recommended" else
            f"Validate {first.intervention_id.replace('_', ' ')} before selecting a paid intervention."
        )), tuple(candidates), confidence=first.confidence)

    route_present = checks.get("sitewide_contact_path") is True and (
        checks.get("tap_to_call") is True or checks.get("contact_form") is True
    )
    healthy_site = route_present and all(checks.get(key) is True for key in (
        "https", "viewport", "clear_primary_cta", "indexable_sample", "service_pages", "trust_signals",
    ))
    healthy_google = hours is True and photos is not None and photos > 0 and reviews is not None and reviews >= 20 and rating is not None and rating >= 4.0
    current_refs = (*(website_refs if website_observed else ()), *(google_refs if google_current else ()))
    constrained = capacity_constrained(evidence.capacity_status) or capacity_constrained(evidence.business_goal)
    structured_capacity = isinstance(evidence.owner_strategy, dict) and evidence.owner_strategy.get("state") == "confirmed" and any(
        fact.get("kind") == "capacity" and fact.get("value") in {"growth_constrained", "deferred"}
        for fact in evidence.owner_strategy.get("constraints", []) if isinstance(fact, dict)
    )
    if constrained or structured_capacity:
        fit = owner_fit_for_scope(evidence.owner_strategy, intervention_id="search_opportunity_validation", scope=(),
                                  capacity_text=evidence.capacity_status, goal_text=evidence.business_goal)
        return replace(_result("validate_first", "Confirm the owner's timing and capacity goal before proposing paid work.",
                               refs=(*current_refs, *fit.evidence_refs)), owner_fit_status=fit.status,
                       owner_fit_reason=fit.reason, owner_validation_question=fit.question)
    if healthy_site and healthy_google:
        return _result("no_sale", "Current observed contact, site and public-profile evidence does not justify a meaningful paid intervention.",
                       confidence="Moderate", refs=current_refs)
    return _result("insufficient_evidence", "Current evidence does not establish a meaningful paid intervention or a comprehensively healthy baseline.",
                   refs=current_refs, unknowns=("Complete current website-route and public-profile observations before making a commercial recommendation.",))


def _seo_candidates(report: dict, website_observed: bool) -> list[InterventionCandidate]:
    """Only current validated source projections may influence paid selection.

    Specific uncovered catalog work remains unpriced. A missing service page is
    not permission to sell the Full Local Authority Site or invent an Offer ID.
    """
    if report.get("state") != "complete" or not report.get("snapshot_sha256"):
        return []
    result: list[InterventionCandidate] = []
    for item in report.get("opportunities", []):
        if not isinstance(item, dict) or item.get("decision") in {"no_sale", "insufficient_evidence"}:
            continue
        refs = _strings(item.get("evidence_refs", []))
        if not refs or not any(ref.startswith("seo_snapshot:") for ref in refs):
            continue
        paid = (website_observed and item.get("decision") == "recommended" and item.get("action") == "improve_page"
                and item.get("service_state") == "confirmed"
                and tuple(item.get("scope", [])) == ("local SEO title/meta/H1 fixes",))
        action = str(item.get("action") or "validate")
        result.append(_candidate(
            f"seo_{action}:{item.get('cluster_id', '')}", tuple(str(value) for value in item.get("observations", [])), refs,
            offer_id=OfferID.CONVERSION_TUNE_UP.value if paid else "",
            scope=("local SEO title/meta/H1 fixes",) if paid else (),
            problem=str(item.get("reason") or "Validate the recorded query-specific search hypothesis."),
            why="Current query, service and geography evidence identifies this bounded search hypothesis.",
            contrast="Select the specific observed bottleneck instead of assuming more pages or a whole-site rebuild is necessary.",
            effect=str(item.get("expected_effect") or "Resolve the observation before commissioning work; ranking lift is unproven."),
            metric=str(item.get("success_metric") or "Reobserve the same query, geography and source window; track qualified inquiries separately."),
            falsifier=str(item.get("falsifier") or "A comparable current source contradicts the gap or the service is not commercially useful."),
            effort=("Bounded targeting repair, subject to access and owner approval." if paid else
                    "Validate the specific diagnosis and a suitable bounded scope before quoting."),
            unknowns=tuple(str(value) for value in item.get("unknowns", [])),
            selected_service=str(item.get("service") or ""),
            selected_queries=tuple(str(value) for value in item.get("queries", [])),
            selected_page_url=str((item.get("selected_evidence") or {}).get("page_url") or ""),
            selected_evidence=item.get("selected_evidence") if isinstance(item.get("selected_evidence"), dict) else {},
            source_coverage=item.get("coverage") if isinstance(item.get("coverage"), dict) else {},
        ))
    # Do not suspend a supported repair merely because a lower-priority cluster
    # requires research. Preserve all alternatives for explicit operator review.
    return sorted(result, key=lambda item: (item.status != "recommended", item.intervention_id))


def _apply_owner_fit(candidate: InterventionCandidate, evidence: InterventionEvidence) -> InterventionCandidate:
    packet = candidate.selected_evidence
    condition_keys: tuple[str, ...] = ()
    if candidate.intervention_id == "contact_path_repair":
        condition_keys = ("sitewide_contact_path", "tap_to_call", "contact_form", "viewport", "clear_primary_cta")
    elif candidate.intervention_id == "technical_validation" or candidate.intervention_id.startswith("seo_technical_repair:"):
        condition_keys = ("https", "indexable_sample")
    conditions = tuple(key for key in condition_keys if evidence.website_checks.get(key) is False)
    if candidate.intervention_id == "listing_correction":
        conditions = (*conditions, *(("hours",) if evidence.has_hours is False else ()),
                      *(("photos",) if evidence.photo_count == 0 else ()))
    fit = owner_fit_for_scope(
        evidence.owner_strategy, intervention_id=candidate.intervention_id, scope=candidate.scope,
        service=candidate.selected_service, queries=candidate.selected_queries, page_url=candidate.selected_page_url,
        coverage=candidate.source_coverage or packet.get("source_coverage") or packet.get("coverage") or
                 evidence.seo_research.get("source_metadata", {}).get("coverage"),
        capacity_text=evidence.capacity_status, goal_text=evidence.business_goal, observed_conditions=conditions,
    )
    values: dict[str, Any] = {"owner_fit_status": fit.status, "owner_fit_reason": fit.reason,
              "owner_validation_question": fit.question,
              "evidence_refs": _strings((*candidate.evidence_refs, *fit.evidence_refs))}
    if fit.withhold:
        return replace(candidate, **values, offer_id="", scope=(), status="validate_first", confidence="Low",
                       unknowns=_strings((*candidate.unknowns, fit.reason)))
    return replace(candidate, **values)
