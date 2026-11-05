"""Explicit owner preferences and bounded selected-scope checks.

Preferences are owner evidence, never measured market coverage or numeric
economics. The existing SEO service matcher supplies service identity; no niche
taxonomy or general goal classifier is introduced here.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

from local_presence_miner.domain.seo_intelligence import _service_tokens

OWNER_STRATEGY_VERSION = 1
CONSTRAINT_KINDS = frozenset({
    "desired_service", "excluded_service", "desired_customer_type", "excluded_customer_type",
    "capacity", "low_economic_priority", "provider_work", "intentional_condition",
})
INTENTIONAL_CONDITIONS = frozenset({
    "https", "indexable_sample", "sitewide_contact_path", "tap_to_call", "contact_form",
    "viewport", "clear_primary_cta", "hours", "photos",
})


def _text(value: object, label: str, *, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 4000 or required and not value.strip():
        raise ValueError(f"Owner strategy {label} requires bounded recorded text.")
    return value.strip()


def _list(value: object, label: str) -> list:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(f"Owner strategy {label} requires a bounded list.")
    return value


def validate_owner_strategy(value: object) -> dict:
    """Validate a complete preference snapshot, without inferred geometry."""
    if not isinstance(value, dict) or set(value) - {"schema_version", "constraints", "target_territories", "territory_mode"}:
        raise ValueError("Owner strategy has unsupported fields.")
    if type(value.get("schema_version")) is not int or value["schema_version"] != OWNER_STRATEGY_VERSION:
        raise ValueError("Owner strategy schema version is unsupported.")
    constraints = []
    for fact in _list(value.get("constraints", []), "constraints"):
        if not isinstance(fact, dict) or set(fact) - {"kind", "value", "original_wording", "page_url", "scope"}:
            raise ValueError("Owner constraint has unsupported fields.")
        kind = _text(fact.get("kind"), "constraint kind")
        if kind not in CONSTRAINT_KINDS:
            raise ValueError("Owner constraint kind is unsupported.")
        item: dict[str, Any] = {"kind": kind, "value": _text(fact.get("value"), "constraint value"),
                "original_wording": _text(fact.get("original_wording"), "original wording")}
        if kind.endswith("customer_type") and item["value"] not in {"commercial", "residential"}:
            raise ValueError("Customer type must be explicitly commercial or residential.")
        if kind == "capacity" and item["value"] not in {"growth_constrained", "available", "deferred", "unknown"}:
            raise ValueError("Owner capacity status is unsupported.")
        if kind == "intentional_condition" and item["value"] not in INTENTIONAL_CONDITIONS:
            raise ValueError("Intentional condition must use an existing observed-check key.")
        if "page_url" in fact:
            page = _text(fact["page_url"], "provider page", required=False)
            if page and not re.match(r"https?://[^\s/]+", page):
                raise ValueError("Provider page requires an absolute HTTP(S) URL.")
            item["page_url"] = page
        if "scope" in fact:
            item["scope"] = [_text(part, "provider scope") for part in _list(fact["scope"], "provider scope")]
        if ("page_url" in fact or "scope" in fact) and kind != "provider_work":
            raise ValueError("Only provider work may declare page and scope.")
        constraints.append(item)
    territories = []
    for area in _list(value.get("target_territories", []), "target territories"):
        allowed = {"kind", "country", "state", "city", "postal_codes", "center", "radius_miles", "original_wording"}
        if not isinstance(area, dict) or set(area) - allowed:
            raise ValueError("Owner territory has unsupported fields.")
        kind = _text(area.get("kind"), "territory kind")
        country = _text(area.get("country"), "territory country").upper()
        state = _text(area.get("state"), "territory state").upper()
        item = {"kind": kind, "country": country, "state": state,
                "original_wording": _text(area.get("original_wording"), "territory original wording")}
        if kind not in {"zip", "city", "radius"} or not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[A-Z]{2}", state):
            raise ValueError("Owner territory requires explicit kind, country and state.")
        if kind == "zip":
            codes = [_text(code, "desired postal code") for code in _list(area.get("postal_codes"), "postal codes")]
            if not codes or country != "US" or any(not re.fullmatch(r"\d{5}", code) for code in codes):
                raise ValueError("Desired US ZIP territory requires five-digit postal codes.")
            if set(area) & {"center", "radius_miles", "city"}:
                raise ValueError("ZIP preferences do not carry inferred city or radius geometry.")
            item["postal_codes"] = sorted(set(codes))
        elif kind == "city":
            item["city"] = _text(area.get("city"), "desired city")
            if set(area) & {"postal_codes", "center", "radius_miles"}:
                raise ValueError("City preferences do not establish ZIP or circle geometry.")
        else:
            center, radius = area.get("center"), area.get("radius_miles")
            if not isinstance(center, dict) or set(center) != {"latitude", "longitude"}:
                raise ValueError("Desired radius requires an explicitly recorded center.")
            lat, lon = center["latitude"], center["longitude"]
            if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not isfinite(n) for n in (lat, lon, radius)):
                raise ValueError("Desired radius requires finite numbers.")
            assert isinstance(radius, (int, float))
            if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 < radius <= 500:
                raise ValueError("Desired radius bounds are invalid.")
            if set(area) & {"postal_codes", "city"}:
                raise ValueError("A desired circle is distinct from ZIP and city preferences.")
            item.update(center={"latitude": lat, "longitude": lon}, radius_miles=radius)
        territories.append(item)
    mode = value.get("territory_mode", "preferred")
    if mode not in {"only", "preferred"}:
        raise ValueError("Owner territory mode must be only or preferred.")
    return {"schema_version": OWNER_STRATEGY_VERSION, "constraints": constraints,
            "target_territories": territories, "territory_mode": mode}


def conflicting_owner_constraints(value: dict) -> bool:
    facts = value["constraints"]
    desired = [fact["value"] for fact in facts if fact["kind"] == "desired_service"]
    excluded = [fact["value"] for fact in facts if fact["kind"] == "excluded_service"]
    if any(_matches(left, right) for left in desired for right in excluded):
        return True
    wanted_types = {fact["value"] for fact in facts if fact["kind"] == "desired_customer_type"}
    excluded_types = {fact["value"] for fact in facts if fact["kind"] == "excluded_customer_type"}
    capacity = {fact["value"] for fact in facts if fact["kind"] == "capacity"}
    return bool(wanted_types & excluded_types) or len(capacity) > 1


@dataclass(frozen=True)
class OwnerFit:
    status: str = "unknown"
    withhold: bool = False
    reason: str = "The owner's preference for this exact scope has not been confirmed."
    question: str = "Does this specific work address a problem you want to resolve now?"
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def capacity_constrained(text: str) -> bool:
    """Exact prior tokens plus explicit first-person sentences, not token search."""
    if not isinstance(text, str):
        return False
    clean = " ".join(text.casefold().split())
    if clean in {"booked/busy", "booked", "fully booked", "at capacity", "no capacity", "not accepting new customers"}:
        return True
    if re.search(r"\b(?:not|never|if|unless)\s+(?:fully booked|at capacity)\b", clean):
        return False
    return bool(re.search(
        r"\b(?:we are|we're|our business is)\s+(?:fully booked|at capacity)\b|"
        r"\bour schedule is full\b|"
        r"\bwe\s+(?:cannot|can't|can not|do not|don't)\s+(?:take|accept|want)\s+"
        r"(?:any\s+)?(?:more|additional|new)\s+(?:customers|jobs|work|calls)\b", clean,
    ))


def _matches(left: str, right: str) -> bool:
    return bool(_service_tokens(left)) and _service_tokens(left) == _service_tokens(right)


_SCOPE_TASKS = {
    "local seo title/meta/h1 fixes": frozenset({"title", "meta", "h1"}),
    "title": frozenset({"title"}), "titles": frozenset({"title"}),
    "title tag": frozenset({"title"}), "title tags": frozenset({"title"}),
    "page title": frozenset({"title"}), "page titles": frozenset({"title"}),
    "meta": frozenset({"meta"}), "meta description": frozenset({"meta"}),
    "meta descriptions": frozenset({"meta"}),
    "h1": frozenset({"h1"}), "h1 heading": frozenset({"h1"}), "h1 headings": frozenset({"h1"}),
    "heading": frozenset({"h1"}), "headings": frozenset({"h1"}),
    "mobile call/quote button": frozenset({"contact_button"}),
    "mobile call button": frozenset({"contact_button"}), "call button": frozenset({"contact_button"}),
    "quote button": frozenset({"contact_button"}), "click to call button": frozenset({"contact_button"}),
    "homepage cta rewrite": frozenset({"homepage_cta"}), "homepage cta": frozenset({"homepage_cta"}),
    "homepage call to action": frozenset({"homepage_cta"}),
    "contact form cleanup": frozenset({"contact_form"}),
    "photo plan": frozenset({"photos"}), "update service photos": frozenset({"photos"}),
    "hours and contact cleanup checklist": frozenset({"listing_contact"}),
    "review request script": frozenset({"review_request"}),
    "post job text/email wording for the owner to send": frozenset({"review_request"}),
    "google profile review response workflow": frozenset({"review_response"}),
    "review reply templates": frozenset({"review_response"}),
    "payroll": frozenset({"administration"}), "payroll support": frozenset({"administration"}),
    "accounting": frozenset({"administration"}), "accounting support": frozenset({"administration"}),
}
# Retain the already-supported independent business-service identity. Other
# unequal labels need a recorded page or bounded task identity; they do not
# become separate services through an open-ended noun/action heuristic.
_PROVIDER_SERVICE_IDENTITIES = {"water heater replacement": frozenset({"water", "heater"})}


def _scope_label(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split()).strip(" .")


def _scope_tasks(scope: tuple[str, ...] | list[str]) -> tuple[set[str], bool]:
    """Resolve only the existing task vocabulary and explicit task lists.

    Unrecognized wording remains unresolved, including negations and broad
    optimization promises. A partial match never establishes non-overlap.
    """
    tasks: set[str] = set()
    unresolved = not scope
    for value in scope:
        label = _scope_label(value)
        known = _SCOPE_TASKS.get(label)
        if known is not None:
            tasks.update(known)
            continue
        parts = [part.strip() for part in re.split(r"[,;/&]|\band\b", label) if part.strip()]
        if parts and all(part in _SCOPE_TASKS for part in parts):
            for part in parts:
                tasks.update(_SCOPE_TASKS[part])
        else:
            unresolved = True
    return tasks, unresolved


def _page_identity(value: str) -> tuple[str, str, str, str] | None:
    try:
        page = urlsplit(value)
        if page.scheme not in {"http", "https"} or not page.hostname or page.username or page.password:
            return None
        # Protocol/default-port spelling cannot prove two assignments separate.
        port = page.port
        authority = page.hostname.casefold()
        if port is not None and (page.scheme, port) not in {("http", 80), ("https", 443)}:
            authority += f":{port}"
        return "web", authority, page.path.rstrip("/") or "/", page.query
    except ValueError:
        return None


def _provider_service_subject(value: str, service: str) -> bool | None:
    """Compare a service assignment only when its subject is established.

    An exact existing service identity applies to that service. The previously
    supported water-heater assignment remains distinct from unrelated services.
    Everything else needs an explicit page or task comparison; an unrecognized
    responsibility is never presumed to name a separate business service.
    """
    if _matches(value, service):
        return True
    selected_words = _service_tokens(service)
    for known, subject in _PROVIDER_SERVICE_IDENTITIES.items():
        if _matches(value, known) and selected_words and not subject & selected_words:
            return False
    return None


def _provider_overlap(fact: dict, scope: tuple[str, ...], service: str, page_url: str) -> bool | None:
    """True means duplicate work, False means a known separate task/subject.

    A missing page or service identity and unknown scope are not permission to
    quote. Explicit page identity narrows a provider's recorded assignment;
    a service-only assignment continues to apply to that service's pages.
    """
    subject: bool | None = None
    if fact.get("page_url"):
        provider_page, selected_page = _page_identity(fact["page_url"]), _page_identity(page_url)
        if provider_page is not None and selected_page is not None:
            # Different query strings on the same path may be trackers or true
            # separate resources; neither interpretation is established here.
            subject = None if provider_page[:3] == selected_page[:3] and provider_page[3] != selected_page[3] else provider_page == selected_page
    elif service:
        subject = _provider_service_subject(fact["value"], service)
    if subject is False:
        return False
    provider_scope = fact.get("scope", [])
    if not provider_scope:
        # A service-wide assignment retains its existing overlap semantics.
        # A page URL alone does not resolve broad maintenance responsibility;
        # otherwise use the recorded value as a possible bounded task identity.
        if subject is True and service and _matches(fact["value"], service):
            return True
        provider_scope = [fact["value"]]
    provider_tasks, provider_unknown = _scope_tasks(provider_scope)
    selected_tasks, selected_unknown = _scope_tasks(scope)
    exact_overlap = {_scope_label(part) for part in provider_scope} & {_scope_label(part) for part in scope}
    if exact_overlap or provider_tasks & selected_tasks:
        return True if subject is True else None
    if not provider_unknown and not selected_unknown:
        return False
    return None


def _legacy_reason(goal: str, service: str) -> tuple[str, str]:
    """Recognize a few explicit refusal forms solely to request confirmation."""
    if not isinstance(goal, str):
        return "", ""
    clean = " ".join(goal.casefold().split())
    words = _service_tokens(service)
    for fragment in re.split(r"[.;!?]", clean):
        refusal = re.search(r"\b(?:do not|don't)\s+(?:want|bring us|accept)\s+(.+)", fragment)
        if refusal:
            excluded = re.sub(r"\b(?:calls?|jobs?|customers?|projects?|please|any|more)\b", " ", refusal.group(1)).strip()
            if _matches(excluded, service):
                return "The recorded owner statement excludes the selected service.", f"Do you want to reconsider {service}, or keep it excluded?"
        for wanted, excluded in (("commercial", "residential"), ("residential", "commercial")):
            if re.search(rf"\b{wanted}(?: customers)? only\b", fragment) and excluded in words:
                return ("The selected service targets a customer type the recorded owner statement excludes.",
                        f"Should {service} remain excluded from this scope?")
    if words and words <= _service_tokens(clean):
        if re.search(r"\balready\s+(?:rebuilding|working on|repairing|updating)\b", clean) and re.search(r"\b(?:do not|don't) duplicate\b", clean):
            return ("The current provider may already be doing the selected work.",
                    f"What is your provider already changing for {service}, and is any separate work needed?")
        if re.search(r"\b(?:barely makes us money|low profit(?:ability)?|not profitable)\b", clean):
            return ("The owner described low economic priority; no numeric margin is established.",
                    f"Is {service} worth prioritizing now, and what would make this specific work useful?")
    return "", ""


def _territory_fit(territories: list[dict], coverage: dict, mode: str) -> bool | None:
    """Require actual source coverage; selected lead ZIP is never evidence."""
    if not coverage or coverage.get("kind") not in {"zip", "city", "radius"}:
        return None
    if coverage.get("kind") == "zip":
        observed = set(coverage.get("postal_codes", []))
        desired = {code for area in territories if area["kind"] == "zip" for code in area["postal_codes"]
                   if area["country"] == coverage.get("country") and area["state"] == coverage.get("state")}
        if not observed or not desired:
            return None
        return observed <= desired if mode == "only" else bool(observed & desired)
    for area in territories:
        if area["kind"] != coverage["kind"] or any(area[key] != coverage.get(key) for key in ("country", "state")):
            continue
        if area["kind"] == "city" and area["city"].casefold() == str(coverage.get("city", "")).casefold():
            return True
        if area["kind"] == "radius" and area["center"] == coverage.get("center") and area["radius_miles"] == coverage.get("radius_miles"):
            return True
    return None


def owner_fit_for_scope(
    strategy: dict, *, intervention_id: str, scope: tuple[str, ...], service: str = "",
    queries: tuple[str, ...] = (), page_url: str = "", coverage: dict | None = None,
    capacity_text: str = "", goal_text: str = "", observed_conditions: tuple[str, ...] = (),
) -> OwnerFit:
    if not isinstance(strategy, dict):
        return OwnerFit("unknown", True, "Current owner strategy is malformed.", "Can you confirm the instructions for this exact work?")
    growth = intervention_id.startswith("seo_") and not intervention_id.startswith("seo_technical_repair:") or intervention_id in {
        "service_content_validation", "search_opportunity_validation", "review_workflow", "listing_correction",
    }
    refs = tuple(strategy.get("evidence_refs", ()))

    def hold(reason: str, question: str, *, conflict: bool = True) -> OwnerFit:
        return OwnerFit("conflict" if conflict else "unknown", True, reason, question, refs)

    if strategy.get("state") in {"invalid", "ambiguous"}:
        return hold("Current owner strategy is invalid or contradictory; its history requires clarification.",
                    f"Which owner instruction applies to {service or 'this specific scope'} now?", conflict=False)
    facts: list[dict] = []
    territories: list[dict] = []
    if strategy.get("state") == "confirmed":
        if not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            return hold("Owner confirmation lacks recorded source provenance.", "Can you confirm the instructions for this exact work?", conflict=False)
        try:
            valid = validate_owner_strategy({key: strategy[key] for key in ("schema_version", "constraints", "target_territories", "territory_mode")})
        except (ValueError, KeyError, TypeError):
            return hold("Current owner strategy failed validation.", "Can you confirm the current instructions for this exact work?", conflict=False)
        if conflicting_owner_constraints(valid):
            return hold("Confirmed owner constraints contradict one another.", "Which owner instruction applies to this exact work now?", conflict=False)
        facts, territories = valid["constraints"], valid["target_territories"]
    elif strategy.get("state") == "unconfirmed":
        return hold("Recorded strategy is an operator interpretation or lacks explicit owner confirmation.",
                    f"Do you confirm these instructions for {service or 'this specific work'}?", conflict=False)
    structured_constraint = any(fact["kind"] == "capacity" and fact["value"] in {
        "growth_constrained", "deferred", "unknown",
    } for fact in facts)
    if growth and (capacity_constrained(capacity_text) or capacity_constrained(goal_text) or structured_constraint):
        legacy = strategy.get("legacy_context", {}).get("capacity" if capacity_constrained(capacity_text) else "goal", {})
        refs = tuple(dict.fromkeys((*refs, *legacy.get("evidence_refs", ()))))
        return hold("Recorded timing or capacity does not support this growth scope now.",
                    f"When would work aimed at more {service or 'customer'} inquiries fit your capacity, or should we defer it?",
                    conflict=structured_constraint or legacy.get("confirmed_owner") is True)
    legacy_reason, legacy_question = _legacy_reason(goal_text, service)
    if growth and legacy_reason:
        legacy = strategy.get("legacy_context", {}).get("goal", {})
        refs = tuple(dict.fromkeys((*refs, *legacy.get("evidence_refs", ()))))
        return hold(legacy_reason + " Confirm its structured meaning before quoting.", legacy_question,
                    conflict=legacy.get("confirmed_owner") is True)
    if service and growth:
        excluded = [fact for fact in facts if fact["kind"] == "excluded_service" and _matches(fact["value"], service)]
        desired = [fact["value"] for fact in facts if fact["kind"] == "desired_service"]
        if excluded or desired and not any(_matches(item, service) for item in desired):
            return hold("The selected service conflicts with the confirmed desired or excluded services.",
                        f"Should {service} remain outside the paid scope, or do you explicitly want to reconsider it?")
        customer_words = _service_tokens(" ".join((service, *queries)))
        desired_types = {fact["value"] for fact in facts if fact["kind"] == "desired_customer_type"}
        for fact in facts:
            if fact["kind"] == "excluded_customer_type" and fact["value"] in customer_words:
                return hold("The selected query targets an excluded customer type.", f"Should {fact['value']} inquiries remain excluded from {service}?")
            if fact["kind"] == "desired_customer_type" and len(desired_types) == 1:
                opposite = "residential" if fact["value"] == "commercial" else "commercial"
                if opposite in customer_words:
                    return hold("The selected query conflicts with the desired customer type.", f"Should {opposite} inquiries remain excluded from {service}?")
                if fact["value"] not in customer_words:
                    return hold("The query's customer type is unknown relative to the owner's confirmed preference.",
                                f"Will this {service} scope serve only the {fact['value']} customers you want?", conflict=False)
            if fact["kind"] == "low_economic_priority" and _matches(fact["value"], service):
                return hold("The owner reports low economic priority for the selected service; its numeric economics are unknown.",
                            f"Is {service} worth prioritizing now, and what would make this specific work useful?")
    elif growth and any(fact["kind"] in {"desired_service", "excluded_service", "desired_customer_type", "excluded_customer_type"}
                        for fact in facts):
        return hold("The selected scope does not establish its service or customer fit against the confirmed preferences.",
                    "Which desired services and customers should this specific work support?", conflict=False)
    for fact in facts:
        if fact["kind"] == "provider_work":
            overlap = _provider_overlap(fact, scope, service, page_url)
            if overlap is not False:
                return hold(
                    "The selected work may duplicate the owner's current provider scope." if overlap is True else
                    "The provider's recorded page, service or task scope does not establish that this work is separate.",
                    f"What is your provider already changing for {service or page_url or 'this work'}, and is any separate work needed?",
                    conflict=overlap is True,
                )
        if fact["kind"] == "intentional_condition" and fact["value"] in observed_conditions:
            return hold("An observed condition is recorded as intentional, so repair approval requires reconsideration.",
                        f"Do you want to change the intentionally configured {fact['value']} behavior?")
    if growth and territories:
        match = _territory_fit(territories, coverage or {}, strategy.get("territory_mode", "preferred"))
        if match is not True:
            return hold("Actual observation coverage does not establish fit with the owner's confirmed target territory.",
                        f"Should we collect matching evidence for your desired areas before quoting {service or 'this scope'}?", conflict=match is False)
    if (growth and isinstance(goal_text, str) and re.search(r"\b\d{5}\b", goal_text)
            and re.search(r"\b(?:only|prefer|want)\b", goal_text.casefold()) and not territories):
        refs = tuple(dict.fromkeys((*refs, *strategy.get("legacy_context", {}).get("goal", {}).get("evidence_refs", ()))))
        return hold("The recorded desired ZIPs need structured owner confirmation and matching observation coverage.",
                    "Which ZIPs do you want to serve, and are they exclusive or preferred areas?", conflict=False)
    confirmed = bool(facts or territories) and strategy.get("state") == "confirmed"
    # Capacity alone confirms timing, never the exact paid scope or service.
    if confirmed and all(fact["kind"] == "capacity" for fact in facts) and not territories:
        confirmed = False
    question = (f"Does {'; '.join(scope) or 'this specific work'} for {service or 'your existing customer path'} "
                "address a problem you want to resolve now?")
    return OwnerFit("confirmed" if confirmed else "unknown", False,
                    "The selected scope satisfies the applicable confirmed owner constraints." if confirmed else
                    "No confirmed conflict is recorded; owner approval of the exact scope is still required.",
                    question, refs)
