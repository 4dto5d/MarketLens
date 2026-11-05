from __future__ import annotations

import re
from dataclasses import dataclass

from local_presence_miner.domain.categories import (
    CATEGORY_GROUPS,
    EXTRA_OPPORTUNITY_CATEGORIES,
    STRONG_OPPORTUNITY_CATEGORIES,
    TOP_OPPORTUNITY_CATEGORIES,
)

NICHE_TAXONOMY_VERSION = 1


@dataclass(frozen=True)
class NicheResolution:
    raw_category: str
    canonical_id: str
    display_name: str
    service_family: str
    match_rule: str
    resolved: bool


@dataclass(frozen=True)
class NicheRule:
    canonical_id: str
    display_name: str
    service_family: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SearchTopicRule:
    """Controlled search intent within an existing canonical niche."""

    topic_id: str
    display_name: str
    terms: tuple[str, ...]
    intent: str
    commercial_relevance: int  # 1 exploratory, 2 core, 3 direct service need.


def _slug(value: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", value.casefold()))


_EXPLICIT_RULES: tuple[NicheRule, ...] = (
    NicheRule(
        "roofing",
        "Roofing",
        "home_services",
        (
            "roofing",
            "roofer",
            "roofers",
            "roofing contractor",
            "roofing contractors",
            "residential roofing",
            "commercial roofing",
            "roof repair",
            "emergency roof repair",
        ),
    ),
    NicheRule(
        "dental",
        "Dental",
        "health_wellness",
        ("dentist", "dentists", "dental", "dental clinic", "dental practice", "general dentistry", "orthodontist", "orthodontists", "orthodontics"),
    ),
    NicheRule(
        "plumbing",
        "Plumbing",
        "home_services",
        ("plumber", "plumbers", "plumbing", "plumbing contractor", "emergency plumbers", "sewer repair", "sewer cleaning"),
    ),
    NicheRule(
        "hvac", "HVAC", "home_services", ("hvac", "hvac contractor", "hvac contractors", "heating and cooling", "air conditioning", "emergency hvac repair")
    ),
    NicheRule("electrical", "Electrical", "home_services", ("electrician", "electricians", "electrical contractor", "emergency electricians")),
    NicheRule(
        "residential_cleaning",
        "Residential Cleaning",
        "home_services",
        ("residential cleaning", "house cleaners", "house cleaning", "maid services", "maid service", "cleaning service"),
    ),
    NicheRule(
        "painting", "Painting", "home_services", ("residential painter", "residential painters", "painter", "painters", "painting", "painting contractor")
    ),
    NicheRule(
        "automotive_repair",
        "Automotive Repair",
        "auto_transportation",
        ("automotive repair", "auto repair", "auto repair shops", "mechanic", "mechanics", "car repair"),
    ),
    NicheRule("home_automation", "Home Automation", "professional_services", ("home automation", "smart home installer", "smart home installation")),
    NicheRule("salon", "Salon", "beauty_personal_care", ("salon", "salons", "hair salon", "hair salons", "barber", "barbers")),
    NicheRule("med_spa", "Medical Spa", "health_wellness", ("med spa", "med spas", "medical spa", "medical spas")),
    NicheRule("landscaping", "Landscaping", "home_services", ("landscaper", "landscapers", "landscaping", "lawn care")),
    NicheRule("moving", "Moving", "auto_transportation", ("mover", "movers", "moving company", "moving companies")),
    NicheRule(
        "legal",
        "Legal Services",
        "professional_services",
        (
            "law firm",
            "law firms",
            "lawyer",
            "lawyers",
            "attorney",
            "attorneys",
            "personal injury lawyers",
            "family lawyers",
            "estate planning attorneys",
            "criminal defense attorneys",
            "immigration lawyers",
        ),
    ),
)


def normalize_category(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold().replace("_", " ")))


def _catalog_rules() -> tuple[NicheRule, ...]:
    explicit_aliases = {normalize_category(alias) for rule in _EXPLICIT_RULES for alias in rule.aliases}
    rules: list[NicheRule] = []
    for group, categories in CATEGORY_GROUPS.items():
        family = _slug(group)
        for category in categories:
            normalized = normalize_category(category)
            if normalized not in explicit_aliases:
                rules.append(NicheRule(_slug(category), category.title(), family, (category,)))
    for category in EXTRA_OPPORTUNITY_CATEGORIES:
        normalized = normalize_category(category)
        if normalized not in explicit_aliases:
            rules.append(NicheRule(_slug(category), category.title(), "home_services", (category,)))
    return tuple(rules)


NICHE_RULES: tuple[NicheRule, ...] = _EXPLICIT_RULES + _catalog_rules()


SEARCH_TOPICS: dict[str, tuple[SearchTopicRule, ...]] = {
    "pest_control": (
        SearchTopicRule("core", "Pest Control", ("pest control", "exterminator"), "local_service", 2),
        SearchTopicRule("rodent_control", "Rodent Control", ("rodent control", "mice exterminator", "rat removal"), "service_need", 3),
        SearchTopicRule("termite", "Termite Control", ("termite control", "termite inspection"), "service_need", 3),
        SearchTopicRule("emergency", "Emergency Pest Control", ("emergency pest control",), "urgent_service", 3),
    ),
    "roofing": (
        SearchTopicRule("core", "Roofing", ("roofing contractor", "roofer"), "local_service", 2),
        SearchTopicRule("repair", "Roof Repair", ("roof repair", "emergency roof repair"), "service_need", 3),
        SearchTopicRule("replacement", "Roof Replacement", ("roof replacement",), "service_need", 3),
        SearchTopicRule("inspection", "Roof Inspection", ("roof inspection",), "service_need", 2),
    ),
    "plumbing": (
        SearchTopicRule("core", "Plumbing", ("plumber", "plumbing contractor"), "local_service", 2),
        SearchTopicRule("drain", "Drain and Sewer", ("drain cleaning", "sewer repair"), "service_need", 3),
        SearchTopicRule("emergency", "Emergency Plumbing", ("emergency plumber",), "urgent_service", 3),
    ),
}


def search_topics_for(canonical_id: str) -> tuple[SearchTopicRule, ...]:
    """Use the existing niche taxonomy as authority; uncurated niches get one core query."""
    if canonical_id in SEARCH_TOPICS:
        return SEARCH_TOPICS[canonical_id]
    rule = next((item for item in NICHE_RULES if item.canonical_id == canonical_id), None)
    if rule is None:
        return ()
    return (SearchTopicRule("core", rule.display_name, (normalize_category(rule.display_name),), "local_service", 2),)


def resolve_niche(raw_category: str) -> NicheResolution:
    raw = (raw_category or "").strip()
    normalized = normalize_category(raw)
    if not normalized:
        return NicheResolution(raw, "unresolved", "Unresolved", "unresolved", "empty", False)

    # Exact explicit/catalog aliases are preferred. Controlled phrase rules use
    # complete normalized words, never arbitrary substrings such as dent in residential.
    for rule in NICHE_RULES:
        for alias in rule.aliases:
            if normalized == normalize_category(alias):
                return NicheResolution(raw, rule.canonical_id, rule.display_name, rule.service_family, f"exact_alias:{alias}", True)
    tokens = normalized.split()
    phrase_matches: list[tuple[int, NicheRule, str]] = []
    for rule in _EXPLICIT_RULES:
        for alias in rule.aliases:
            alias_tokens = normalize_category(alias).split()
            if alias_tokens and _contains_phrase(tokens, alias_tokens):
                phrase_matches.append((len(alias_tokens), rule, alias))
    if phrase_matches:
        _, rule, alias = max(phrase_matches, key=lambda item: (item[0], len(item[2])))
        return NicheResolution(raw, rule.canonical_id, rule.display_name, rule.service_family, f"controlled_phrase:{alias}", True)
    return NicheResolution(raw, "unresolved", raw or "Unresolved", "unresolved", "no_rule", False)


def _contains_phrase(tokens: list[str], phrase: list[str]) -> bool:
    width = len(phrase)
    return any(tokens[index : index + width] == phrase for index in range(0, len(tokens) - width + 1))


def niche_relation(left: str, right: str) -> str:
    a = resolve_niche(left)
    b = resolve_niche(right)
    if not a.resolved or not b.resolved:
        return "unknown"
    if a.canonical_id == b.canonical_id:
        return "same"
    if a.service_family == b.service_family and a.service_family != "unresolved":
        return "related"
    return "different"


def commercial_class(raw_category: str) -> str:
    resolution = resolve_niche(raw_category)
    top_ids = {_canonical_for_known(value) for value in (*TOP_OPPORTUNITY_CATEGORIES, *EXTRA_OPPORTUNITY_CATEGORIES)}
    strong_ids = {_canonical_for_known(value) for value in STRONG_OPPORTUNITY_CATEGORIES}
    if resolution.canonical_id in top_ids:
        return "high"
    if resolution.canonical_id in strong_ids:
        return "moderate"
    return "general"


def _canonical_for_known(value: str) -> str:
    normalized = normalize_category(value)
    for rule in NICHE_RULES:
        if any(normalized == normalize_category(alias) for alias in rule.aliases):
            return rule.canonical_id
    return _slug(value)


def taxonomy_inventory() -> list[dict[str, object]]:
    return [
        {
            "canonical_id": rule.canonical_id,
            "display_name": rule.display_name,
            "service_family": rule.service_family,
            "aliases": list(rule.aliases),
        }
        for rule in NICHE_RULES
    ]
