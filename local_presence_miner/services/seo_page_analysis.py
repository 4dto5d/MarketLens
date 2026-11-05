"""Observed SEO facts from already fetched HTML; this module never fetches URLs.

Indexability describes page-level HTTP and robots evidence only, not inclusion in
a search index. Service confirmation requires explicit evidence. Diagnostics are
bounded-sample hypotheses with a validation action and a falsifier.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Protocol
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup, Comment, Tag

from local_presence_miner.domain.website_evidence import classify_page_facts, classify_response, current_response_proves_content, page_identity

MAX_JSONLD_BYTES = 512 * 1024
MAX_SCHEMA_NODES = 2000
NONCONTENT_TAGS = {"script", "style", "noscript", "template", "nav", "footer", "header", "aside", "head"}
NON_SERVICE_PATH = re.compile(r"(?:^|/)(?:about(?:-us)?|contact(?:-us)?|team|reviews?|testimonials?|blog|news|articles?|resources?)(?:/|[-.]|$)", re.I)
INFORMATIONAL_HEADING = re.compile(
    r"\b(?:why|how|what|when|tips|guide|benefits|costs?|signs|contact|about|reviews?|testimonials?|areas?|"
    r"not|no|cannot|without|avoid|don't|doesn't|can't|training|courses?|education|examples?|history|news|articles?|diy)\b", re.I,
)
SERVICE_HEADING = re.compile(
    r"\b(?:services?|repair|replacement|installation|maintenance|inspection|cleaning|restoration|remodeling|remodelling|"
    r"treatment|consultation|consulting|representation|drafting|whitening|therapy|landscaping|extermination)\b", re.I,
)
GENERIC_SERVICE = re.compile(r"^(?:(?:our|all|professional|quality|local|home|available|other|the|best)\s+)*services?$", re.I)
KNOWN_ROBOTS = {"index", "noindex", "follow", "nofollow", "all", "none", "noarchive", "nosnippet", "noimageindex", "notranslate", "indexifembedded"}
ROBOT_PARAMETERS = {"max-snippet", "max-image-preview", "max-video-preview", "unavailable_after"}


class PageLike(Protocol):
    @property
    def url(self) -> str: ...

    @property
    def status_code(self) -> int: ...

    @property
    def soup(self) -> BeautifulSoup: ...

    @property
    def title(self) -> str: ...

    @property
    def meta_description(self) -> str: ...

    @property
    def x_robots_tag(self) -> str: ...


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:240]


def _service_label(value: Any) -> str:
    label = _label(value)
    if not label or GENERIC_SERVICE.fullmatch(label) or label.casefold() in {"contact", "about", "service area", "service areas"}:
        return ""
    return label


def _content_visible(node: Any) -> bool:
    for parent in [node, *node.parents]:
        if not isinstance(parent, Tag):
            continue
        style = str(parent.get("style", ""))
        if (parent.name in NONCONTENT_TAGS or parent.has_attr("hidden") or str(parent.get("aria-hidden", "")).casefold() == "true"
                or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", style, re.I)):
            return False
    return True


def _robots_directives(soup: BeautifulSoup, header: str) -> list[str]:
    directives: list[str] = []

    def append(content: str, scope: str = "", *, scoped_header: bool = False) -> None:
        for part in content.casefold().split(","):
            part = part.strip()
            prefix, colon, rest = part.partition(":")
            if scoped_header and colon and re.fullmatch(r"[\w*-]+", prefix) and prefix not in ROBOT_PARAMETERS:
                scope, part = prefix, rest.strip()
            # Parameter values are retained as one observed directive.
            tokens = [part] if part.partition(":")[0] in ROBOT_PARAMETERS else part.split()
            for token in tokens:
                if token:
                    directives.append(f"{scope}: {token}" if scope else token)

    for meta in soup.find_all("meta", attrs={"name": True}):
        name = str(meta.get("name", "")).strip().casefold()
        if name == "robots" or name in {"googlebot", "googlebot-news", "bingbot"}:
            append(str(meta.get("content", "")), "" if name == "robots" else name)
    append(header, scoped_header=True)
    return _unique(directives)


def _indexability(status: int, directives: list[str]) -> str:
    if status in {404, 410}:
        return "blocked"
    if not 200 <= status < 300 or status == 204:
        return "unknown"
    uncertain = False
    for directive in directives:
        scope = ""
        value = directive
        prefix, colon, rest = directive.partition(":")
        if colon and prefix not in ROBOT_PARAMETERS:
            scope, value = prefix.strip(), rest.strip()
        if value in {"noindex", "none"}:
            if scope in {"", "*", "googlebot"}:
                return "blocked"
            uncertain = True
        elif value.partition(":")[0] == "unavailable_after" or value.partition(":")[0] not in KNOWN_ROBOTS | ROBOT_PARAMETERS:
            uncertain = True
    return "unknown" if uncertain else "allowed"


def _schema_context(value: Any) -> bool:
    if isinstance(value, str):
        return value.rstrip("/").casefold() in {"http://schema.org", "https://schema.org"}
    if isinstance(value, list):
        # A custom remapping can change what "Service" means. Unsupported
        # context expansions remain unknown rather than confirming a service.
        return bool(value) and all(not isinstance(item, list) and _schema_context(item) for item in value)
    return (isinstance(value, dict) and set(value) <= {"@vocab", "@language", "@version"}
            and isinstance(value.get("@vocab"), str) and _schema_context(value["@vocab"]))


def _schema_type(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"^https?://schema\.org/", "", value.strip(), flags=re.I)
    return value if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", value) else ""


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Non-JSON numeric value: {value}")


def _http_reference(base: str, value: str) -> str:
    try:
        absolute = urljoin(base, value)
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.username is None and parsed.password is None:
            return absolute
    except ValueError:
        pass
    return ""


def _schema_facts(soup: BeautifulSoup, url: str) -> tuple[list[str], list[str], list[dict[str, str]]]:
    types: list[str] = []
    errors: list[str] = []
    services: list[dict[str, str]] = []
    for number, script in enumerate(soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json$", re.I)}), 1):
        raw = script.get_text()
        if len(raw.encode("utf-8")) > MAX_JSONLD_BYTES:
            errors.append(f"JSON-LD block {number} exceeds the bounded parser size; its facts are unknown.")
            continue
        try:
            parsed = json.loads(raw, parse_constant=_reject_nonfinite)
        except (ValueError, RecursionError):
            errors.append(f"JSON-LD block {number} is not valid JSON; its facts are unknown.")
            continue
        if not isinstance(parsed, (dict, list)):
            errors.append(f"JSON-LD block {number} is not an object or array; its schema facts are unknown.")
            continue
        stack: list[tuple[Any, bool]] = [(parsed, False)]
        visited = 0
        while stack:
            node, context = stack.pop()
            visited += 1
            if visited > MAX_SCHEMA_NODES:
                errors.append(f"JSON-LD block {number} exceeds the bounded node sample; remaining facts are unknown.")
                break
            if isinstance(node, list):
                stack.extend((item, context) for item in reversed(node))
                continue
            if not isinstance(node, dict):
                continue
            if "@context" in node:
                context = _schema_context(node["@context"])
            raw_types = node.get("@type", [])
            raw_types = raw_types if isinstance(raw_types, list) else [raw_types]
            node_types = [value for item in raw_types if (value := _schema_type(item))] if context else []
            types.extend(node_types)
            if "Service" in node_types:
                values = node.get("serviceType", node.get("name", []))
                values = values if isinstance(values, list) else [values]
                labels = [value for item in values if (value := _service_label(item))]
                if not labels:
                    errors.append(f"JSON-LD block {number} Service has no usable serviceType or name; service confirmation is unknown.")
                services.extend({"service": label, "source": url, "kind": "jsonld_Service"} for label in labels)
            stack.extend((value, context) for key, value in reversed(list(node.items())) if key != "@context" and isinstance(value, (dict, list)))
    return _unique(types), _unique(errors), services


def extract_page_analysis(page: PageLike) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the stable fact contract and separately retained proof details."""
    soup = page.soup
    robots = _robots_directives(soup, getattr(page, "x_robots_tag", ""))
    canonical_urls: list[str] = []
    canonical_errors: list[str] = []
    for link in soup.find_all("link", href=True):
        if "canonical" not in [str(value).casefold() for value in (link.get("rel") or [])]:
            continue
        raw = str(link.get("href", "")).strip()
        if absolute := _http_reference(page.url, raw) if raw else "":
            canonical_urls.append(absolute)
        else:
            canonical_errors.append("Canonical declaration has no usable HTTP(S) destination; intent is unknown.")
    canonical_urls = _unique(canonical_urls)
    internal_links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        absolute = urldefrag(_http_reference(page.url, str(anchor.get("href", "")))).url
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"} and parsed.netloc.casefold() == urlparse(page.url).netloc.casefold():
            internal_links.append(absolute)
    schema_types, schema_errors, service_evidence = _schema_facts(soup, page.url)
    successful_content = 200 <= page.status_code < 300 and page.status_code != 204
    if not successful_content:
        service_evidence = []
    content = soup.find("main") or soup.body or soup
    if successful_content and not NON_SERVICE_PATH.search(urlparse(page.url).path):
        for heading in content.find_all(["h1", "h2", "h3"]):
            label = _service_label(heading.get_text(" ", strip=True))
            if (label and len(label.split()) <= 10 and SERVICE_HEADING.search(label) and not INFORMATIONAL_HEADING.search(label)
                    and _content_visible(heading)):
                service_evidence.append({"service": label, "source": page.url, "kind": "main_heading"})
    visible = " ".join(
        str(item) for item in content.find_all(string=True)
        if not isinstance(item, Comment) and _content_visible(item)
    )
    # Isolated headings and link/button labels can coexist with a loading
    # shell. Keep them in raw observations/counts, but they are not body proof.
    content_text = " ".join(
        str(item) for item in content.find_all(string=True)
        if not isinstance(item, Comment) and _content_visible(item)
        and not any(parent.name in {"h1", "h2", "h3", "h4", "h5", "h6", "a", "button", "select"} for parent in item.parents)
    )
    services = _unique([item["service"] for item in service_evidence])
    facts: dict[str, Any] = {
        "url": page.url,
        "title": page.title,
        "h1": [heading.get_text(" ", strip=True) for heading in soup.find_all("h1")],
        "meta_description": page.meta_description,
        "canonical": canonical_urls[0] if canonical_urls else "",
        "robots": robots,
        "status_code": page.status_code,
        "indexability": _indexability(page.status_code, robots),
        "word_count": len(re.findall(r"\b\w+(?:['’-]\w+)*\b", visible)),
        "internal_links": _unique(internal_links),
        "schema_types": schema_types,
        "schema_errors": schema_errors,
        "services": services,
        "service_refs": [page.url] if services else [],
    }
    details: dict[str, Any] = {
        "url": page.url, "service_evidence": service_evidence,
        "canonical_candidates": canonical_urls,
        "canonical_errors": _unique(canonical_errors),
        "limitations": ["Fetched HTML only; robots.txt, rendered content, search index inclusion and ranking were not verified."],
    }
    markers = tuple(marker for marker in ("cf-challenge-running", "challenge-form") if soup.find(id=marker))
    details["response_validity"] = classify_response(
        page.url, page.status_code, page.title, headings=tuple(facts["h1"]), visible_text=visible, structural_indicators=markers,
        content_text=content_text,
    )
    # Material-content identity ignores canonical declarations themselves, but
    # does not confuse matching titles/headings with matching page content.
    material = {"visible_text": " ".join(visible.split()), "title": page.title,
                "h1": facts["h1"], "meta_description": page.meta_description,
                "robots": robots, "schema_types": schema_types, "schema_errors": schema_errors,
                "services": services, "internal_links": [page_identity(u) for u in internal_links],
                "media": [str(node) for node in soup.find_all(["img", "video", "iframe", "form"])]}
    details["content_fingerprint"] = hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()
    return facts, details


def extract_page_facts(page: PageLike) -> dict[str, Any]:
    """Extract the stable fact contract without changing the snapshot or checks."""
    return extract_page_analysis(page)[0]


def analytical_page_sample(pages: list[dict[str, Any]], details: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Unique content-comparison sample; observations remain unmodified.

    A shared canonical requires one unambiguous same-origin declaration plus
    matching material content in both observations. Without this proof, keep
    the original path/query identity. A canonical is not proof by itself.
    """
    by_url = {item["url"]: item for item in details or []}
    rows = [{**by_url.get(row["url"], {}), **row} for row in pages]
    canonical_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row["analysis_identity"] = page_identity(row["url"])
        derived = classify_page_facts(row)
        if "response_validity" not in row:
            # Old observations are not retroactively certified normal. Their
            # stored title/path/status can still prove a non-normal response.
            row["response_validity"] = derived if derived["state"] != "normal" else {**derived, "state": "legacy_unclassified"}
        elif (row["response_validity"].get("state") == "normal" and derived["state"] != "normal"
              and not current_response_proves_content(row["response_validity"], derived)):
            # A saved normal classification must not override current shell
            # counterevidence. This is a consumer view; stored facts/details
            # and their original interpretation remain unchanged.
            row["response_validity"] = derived
        canonical = row.get("canonical", "")
        candidates = row.get("canonical_candidates", [])
        if (canonical and candidates == [canonical] and not row.get("canonical_errors")
                and urlparse(page_identity(canonical)).netloc == urlparse(page_identity(row["url"])).netloc
                and urlparse(canonical).scheme == urlparse(row["url"]).scheme
                and 200 <= row.get("status_code", 0) < 300
                and row.get("response_validity", {}).get("state") == "normal" and row.get("content_fingerprint")):
            canonical_groups[(page_identity(canonical), row["content_fingerprint"])].append(row)
    for (canonical, _content), group in canonical_groups.items():
        fingerprints = {content for target, content in canonical_groups if target == canonical}
        # A separately observed canonical destination can contradict the alias
        # declaration. Never merge it merely because its URL is the group key.
        destinations = [row for row in rows if page_identity(row["url"]) == canonical]
        compatible_destination = all(row.get("content_fingerprint") == _content
                                     and row.get("response_validity", {}).get("state") == "normal" for row in destinations)
        if len(group) > 1 and len(fingerprints) == 1 and compatible_destination:
            for row in group:
                row["analysis_identity"] = canonical
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row["analysis_identity"]
        if identity not in unique:
            unique[identity] = {**row, "observed_urls": []}
        unique[identity]["observed_urls"].append(row["url"])
        # A conflicting alias must not promote abnormal content into normal.
        validity = row.get("response_validity", {})
        if validity and validity.get("state") in {"non_normal", "uncertain"}:
            unique[identity]["response_validity"] = validity
    return list(unique.values())


def analyze_page_sample(pages: list[dict[str, Any]], details: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return hypotheses to validate, without asserting whole-site SEO causality."""
    diagnostics: list[dict[str, Any]] = []

    def add(kind: str, urls: list[str], evidence: str, confidence: str, action: str, falsifier: str) -> None:
        diagnostics.append({"type": kind, "urls": urls, "evidence": evidence, "confidence": confidence, "action": action, "falsifier": falsifier})

    title_urls: dict[str, list[str]] = defaultdict(list)
    target_urls: dict[str, list[str]] = defaultdict(list)
    for page in analytical_page_sample(pages, details):
        url = page["url"]
        validity = page.get("response_validity")
        if validity and validity.get("state") in {"non_normal", "uncertain"}:
            add("response_validation", page["observed_urls"], validity.get("reason", "Response eligibility is UNKNOWN."),
                "observed", "validate", "A fresh owner-confirmed capture supplies normal business-page content.")
            continue
        title = " ".join(page.get("title", "").split()).casefold()
        if title:
            title_urls[title].append(url)
        for service in page.get("services", []):
            target_urls[" ".join(service.split()).casefold()].append(url)
        missing = [name for name in ("title", "h1", "meta_description") if not page.get(name)]
        if missing:
            add("missing_metadata", [url], f"Not detected in fetched HTML: {', '.join(missing)}. Missing metadata alone does not prove weak targeting.",
                "observed", "validate", "Rendered HTML contains these fields, or the page is intentionally excluded and needs no search targeting.")
        if page.get("indexability") == "blocked":
            add("indexing_restriction", [url], f"Observed HTTP status {page.get('status_code')} and robots directives {page.get('robots', [])}.",
                "observed", "validate", "The exclusion is intentional, or a fresh response no longer contains the restriction.")
        canonical = page.get("canonical", "")
        if canonical and urlparse(canonical).netloc.casefold() != urlparse(url).netloc.casefold():
            add("offsite_canonical", [url], f"Fetched HTML declares canonical {canonical}; intent and search-engine selection are unknown.",
                "observed", "validate", "The destination is an intentional equivalent publication or consolidation target.")
        if len(page.get("canonical_candidates", [])) > 1:
            add("multiple_canonicals", [url], f"Multiple canonical declarations: {page['canonical_candidates']}.", "observed", "validate",
                "A fresh rendered response has one intended canonical declaration.")
        if page.get("canonical_errors"):
            add("invalid_canonical", [url], "; ".join(page["canonical_errors"]), "observed", "validate",
                "A fresh response contains a usable and intended HTTP(S) canonical destination.")
        if page.get("schema_errors"):
            add("schema_parse_error", [url], "; ".join(page["schema_errors"]), "observed", "validate",
                "Fresh HTML parses within the bounded limits and matches the intended entities; separate valid blocks may already supply useful schema.")
    for title, urls in title_urls.items():
        unique_urls = _unique(urls)
        if len(unique_urls) > 1:
            add("duplicate_title", unique_urls, f"The sampled pages share title {title!r}; this is only a possible targeting issue.", "observed", "validate",
                "The pages intentionally represent equivalent content, or distinct search intents are supported by query and content evidence.")
    for target, urls in target_urls.items():
        unique_urls = _unique(urls)
        if len(unique_urls) > 1:
            add("possible_target_overlap", unique_urls,
                f"The sampled pages explicitly reference the same service {target!r}; ranking competition is unverified.",
                "possible", "validate", "The pages address different geography, audiences or intents, or query/page performance shows useful distinct roles.")
    return diagnostics
