from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from soupsieve import SelectorSyntaxError

from local_presence_miner import __version__
from local_presence_miner.database.schema import Lead
from local_presence_miner.services.public_url_safety import (
    STYLESHEET_MAX_RESPONSE_BYTES,
    PublicTransport,
    Resolver,
    resolve_public_addresses,
    safe_request,
)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
CONTACT_HINTS = ("contact", "about", "team", "staff", "owner", "management")
SOCIAL_HOSTS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "x.com": "x",
    "twitter.com": "x",
}
GENERIC_EMAIL_LOCALPARTS = {
    "info",
    "hello",
    "contact",
    "office",
    "sales",
    "support",
    "admin",
    "service",
    "appointments",
    "booking",
}
HIDDEN_DECLARATION_RE = re.compile(
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?(?:\s*!important)?\s*(?:;|$))",
    re.IGNORECASE,
)
CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
CSS_IMPORT_RE = re.compile(r"@import\b", re.IGNORECASE)
COMMON_HIDDEN_CLASSES = {"hidden", "d-none", "display-none", "visually-hidden", "sr-only", "screen-reader-only"}
MAX_STYLESHEETS_PER_DISCOVERY = 4
MAX_STYLESHEET_CHARACTERS = 500_000


@dataclass(frozen=True)
class DiscoveredContact:
    kind: str
    value: str
    label: str
    source_type: str
    source_url: str
    confidence: str
    verified_public: bool = True
    selected: bool = False
    notes: str = ""

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ContactDiscoveryResult:
    website: str
    pages_checked: tuple[str, ...]
    contacts: tuple[DiscoveredContact, ...]
    warnings: tuple[str, ...]


class WebsiteContactDiscovery:
    """Conservative public-contact discovery from the official website only.

    This intentionally does not decode obfuscated/hidden addresses, bypass login walls,
    crawl arbitrary third-party data brokers, or guess email addresses. It only records
    contact details visibly published by the business or exposed through ordinary mailto/tel links.
    """

    def __init__(
        self,
        timeout_seconds: int = 12,
        max_pages: int = 4,
        *,
        resolver: Resolver = resolve_public_addresses,
        transport: PublicTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, min(max_pages, 6))
        self.resolver = resolver
        self.transport = transport
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"MarketLensLocal/{__version__} public-contact-discovery"})

    def discover(self, lead: Lead) -> ContactDiscoveryResult:
        website = _normalize_url(lead.website)
        if not website:
            contacts = []
            if lead.phone:
                contacts.append(
                    DiscoveredContact(
                        kind="phone",
                        value=lead.phone.strip(),
                        label="Public business phone",
                        source_type="google_places",
                        source_url=lead.google_maps_url,
                        confidence="Strong",
                        selected=True,
                    )
                )
            return ContactDiscoveryResult("", tuple(), tuple(contacts), ("No official website is listed.",))

        root_host = _registrable_host(website)
        queue = [website]
        checked: list[str] = []
        contacts: list[DiscoveredContact] = []
        warnings: list[str] = []
        seen_urls: set[str] = set()
        stylesheet_cache: dict[str, str] = {}

        while queue and len(checked) < self.max_pages:
            url = queue.pop(0)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                response = safe_request(
                    self.session,
                    "GET",
                    url,
                    timeout=self.timeout_seconds,
                    resolver=self.resolver,
                    transport=self.transport,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                warnings.append(f"Could not read {url}: {exc.__class__.__name__}")
                continue
            final_url = response.url
            if _registrable_host(final_url) != root_host:
                warnings.append(f"Skipped redirected page outside the official website: {final_url}")
                continue
            checked.append(final_url)
            soup = BeautifulSoup(response.text, "html.parser")
            stylesheet_texts, visibility_verified, stylesheet_warnings = _load_same_origin_stylesheets(
                self.session,
                soup,
                final_url,
                root_host,
                timeout_seconds=self.timeout_seconds,
                stylesheet_cache=stylesheet_cache,
                resolver=self.resolver,
                transport=self.transport,
            )
            warnings.extend(stylesheet_warnings)
            contacts.extend(
                _extract_contacts(
                    soup,
                    final_url,
                    root_host,
                    stylesheet_texts=stylesheet_texts,
                    visibility_verified=visibility_verified,
                )
            )
            if len(checked) == 1 and visibility_verified:
                queue.extend(_contact_pages(soup, final_url, root_host, limit=self.max_pages - 1))

        if lead.phone:
            contacts.append(
                DiscoveredContact(
                    kind="phone",
                    value=lead.phone.strip(),
                    label="Public business phone",
                    source_type="google_places",
                    source_url=lead.google_maps_url,
                    confidence="Strong",
                )
            )

        deduped = _dedupe(contacts)
        selected_key = _preferred_contact_key(deduped, root_host)
        selected = tuple(DiscoveredContact(**{**asdict(contact), "selected": (contact.kind, contact.value.casefold()) == selected_key}) for contact in deduped)
        if not selected:
            warnings.append("No public email, phone link, contact page, or supported social profile was found.")
        return ContactDiscoveryResult(website, tuple(checked), selected, tuple(dict.fromkeys(warnings)))


def _extract_contacts(
    soup: BeautifulSoup,
    source_url: str,
    root_host: str,
    *,
    stylesheet_texts: tuple[str, ...] = (),
    visibility_verified: bool = True,
) -> list[DiscoveredContact]:
    found: list[DiscoveredContact] = []
    visibility_verified = visibility_verified and _remove_hidden_content(soup, stylesheet_texts)
    for bad in soup(["script", "style", "noscript", "template"]):
        bad.decompose()

    if visibility_verified:
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            label = " ".join(anchor.stripped_strings).strip()
            lowered = href.lower()
            if lowered.startswith("mailto:"):
                value = href.split(":", 1)[1].split("?", 1)[0].strip()
                if _valid_email(value):
                    found.append(_email_contact(value, label or "Published email", source_url, root_host, "mailto link"))
            elif lowered.startswith("tel:"):
                value = href.split(":", 1)[1].split("?", 1)[0].strip()
                if value:
                    found.append(
                        DiscoveredContact(
                            kind="phone",
                            value=value,
                            label=label or "Published phone",
                            source_type="official_website",
                            source_url=source_url,
                            confidence="Strong",
                            notes="Visible tel link on official website",
                        )
                    )
            else:
                absolute = urljoin(source_url, href)
                host = _registrable_host(absolute)
                social = next((name for domain, name in SOCIAL_HOSTS.items() if host.endswith(domain)), None)
                if social:
                    found.append(
                        DiscoveredContact(
                            kind="social",
                            value=absolute,
                            label=label or social.title(),
                            source_type="official_website",
                            source_url=source_url,
                            confidence="Strong",
                            notes=f"Official website links to {social}",
                        )
                    )

        text = soup.get_text(" ", strip=True)
        for email in EMAIL_RE.findall(text):
            if _valid_email(email):
                found.append(_email_contact(email, "Published email", source_url, root_host, "visible page text"))

    contact_page = _page_contact_candidate(source_url)
    if contact_page:
        found.append(
            DiscoveredContact(
                kind="contact_page",
                value=source_url,
                label="Contact page",
                source_type="official_website",
                source_url=source_url,
                confidence="Strong",
                notes="Official website contact-related page",
            )
        )
    return found


def _load_same_origin_stylesheets(
    session: requests.Session,
    soup: BeautifulSoup,
    page_url: str,
    root_host: str,
    *,
    timeout_seconds: int,
    stylesheet_cache: dict[str, str],
    resolver: Resolver = resolve_public_addresses,
    transport: PublicTransport | None = None,
) -> tuple[tuple[str, ...], bool, tuple[str, ...]]:
    """Load a discovery-bounded set of same-origin stylesheets or fail closed for DOM contact extraction."""
    inline_styles = tuple(tag.get_text(" ", strip=True) for tag in soup.find_all("style"))
    if any(CSS_IMPORT_RE.search(text) for text in inline_styles):
        return (), False, (f"Skipped DOM contact extraction on {page_url}: an inline stylesheet imports additional CSS.",)

    stylesheet_urls: list[str] = []
    for link in soup.find_all("link", href=True):
        rel = link.get("rel", [])
        rel_values = rel if isinstance(rel, list) else [rel]
        if "stylesheet" not in {str(value).casefold() for value in rel_values} or link.has_attr("disabled"):
            continue
        stylesheet_url = urljoin(page_url, str(link.get("href", "")).strip()).split("#", 1)[0]
        parsed = urlparse(stylesheet_url)
        if parsed.scheme not in {"http", "https"} or _registrable_host(stylesheet_url) != root_host:
            return (), False, (f"Skipped DOM contact extraction on {page_url}: a stylesheet is not same-origin.",)
        if stylesheet_url not in stylesheet_urls:
            stylesheet_urls.append(stylesheet_url)

    uncached_urls = [url for url in stylesheet_urls if url not in stylesheet_cache]
    if len(stylesheet_cache) + len(uncached_urls) > MAX_STYLESHEETS_PER_DISCOVERY:
        return (
            (),
            False,
            (f"Skipped DOM contact extraction on {page_url}: more than {MAX_STYLESHEETS_PER_DISCOVERY} stylesheets require review.",),
        )

    for stylesheet_url in uncached_urls:
        try:
            response = safe_request(
                session,
                "GET",
                stylesheet_url,
                timeout=timeout_seconds,
                resolver=resolver,
                transport=transport,
                max_response_bytes=STYLESHEET_MAX_RESPONSE_BYTES,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return (
                (),
                False,
                (f"Skipped DOM contact extraction on {page_url}: stylesheet could not be read ({exc.__class__.__name__}).",),
            )
        if _registrable_host(response.url) != root_host:
            return (), False, (f"Skipped DOM contact extraction on {page_url}: a stylesheet redirected off-site.",)
        text = response.text
        if len(text) > MAX_STYLESHEET_CHARACTERS:
            return (), False, (f"Skipped DOM contact extraction on {page_url}: a stylesheet exceeded the review limit.",)
        if CSS_IMPORT_RE.search(text):
            return (), False, (f"Skipped DOM contact extraction on {page_url}: a stylesheet imports additional CSS.",)
        stylesheet_cache[stylesheet_url] = text

    return tuple(stylesheet_cache[url] for url in stylesheet_urls), True, tuple()


def _remove_hidden_content(soup: BeautifulSoup, stylesheet_texts: tuple[str, ...] = ()) -> bool:
    """Remove DOM content that is explicitly non-visible before contact extraction."""
    hidden_nodes = []
    visibility_verified = True
    css_sources = [tag.get_text(" ", strip=True) for tag in soup.find_all("style")]
    css_sources.extend(stylesheet_texts)
    for css_text in css_sources:
        hidden_rule_found = False
        for selector_group, declarations in CSS_RULE_RE.findall(css_text):
            if not HIDDEN_DECLARATION_RE.search(declarations):
                continue
            hidden_rule_found = True
            for selector in selector_group.split(","):
                selector = selector.strip()
                if not selector or selector.startswith("@"):
                    visibility_verified = False
                    continue
                try:
                    hidden_nodes.extend(soup.select(selector))
                except SelectorSyntaxError:
                    visibility_verified = False
                    continue
        if HIDDEN_DECLARATION_RE.search(css_text) and not hidden_rule_found:
            visibility_verified = False

    for tag in soup.find_all(True):
        classes = {str(value).casefold() for value in tag.get("class", [])}
        explicitly_hidden = (
            tag.has_attr("hidden")
            or str(tag.get("aria-hidden", "")).strip().casefold() == "true"
            or (tag.name == "input" and str(tag.get("type", "")).strip().casefold() == "hidden")
            or bool(HIDDEN_DECLARATION_RE.search(str(tag.get("style", ""))))
            or bool(classes & COMMON_HIDDEN_CLASSES)
        )
        if explicitly_hidden:
            hidden_nodes.append(tag)

    for tag in hidden_nodes:
        if tag.parent is not None:
            tag.decompose()
    return visibility_verified


def _email_contact(value: str, label: str, source_url: str, root_host: str, evidence: str) -> DiscoveredContact:
    domain = value.rsplit("@", 1)[1].lower()
    local = value.split("@", 1)[0].lower()
    same_domain = root_host.endswith(domain) or domain.endswith(root_host)
    confidence = "Strong" if same_domain else "Moderate"
    if local in GENERIC_EMAIL_LOCALPARTS:
        label = label or "General business email"
    return DiscoveredContact(
        kind="email",
        value=value,
        label=label,
        source_type="official_website",
        source_url=source_url,
        confidence=confidence,
        notes=f"Published in {evidence}; {'same-domain' if same_domain else 'external-domain'} address",
    )


def _contact_pages(soup: BeautifulSoup, base_url: str, root_host: str, limit: int) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0]
        if _registrable_host(absolute) != root_host:
            continue
        text = (" ".join(anchor.stripped_strings) + " " + urlparse(absolute).path).lower()
        score = sum(1 for hint in CONTACT_HINTS if hint in text)
        if score:
            candidates.append((score, absolute))
    ordered: list[str] = []
    for _score, url in sorted(candidates, key=lambda item: (-item[0], len(item[1]))):
        if url not in ordered and url != base_url:
            ordered.append(url)
        if len(ordered) >= limit:
            break
    return ordered


def _page_contact_candidate(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(hint in path for hint in CONTACT_HINTS)


def _dedupe(contacts: list[DiscoveredContact]) -> list[DiscoveredContact]:
    result: list[DiscoveredContact] = []
    seen: set[tuple[str, str]] = set()
    for contact in contacts:
        value = contact.value.strip()
        normalized = value.casefold()
        if contact.kind == "phone":
            normalized = re.sub(r"\D", "", value)
        key = (contact.kind, normalized)
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(contact)
    return result


def _preferred_contact_key(contacts: list[DiscoveredContact], root_host: str) -> tuple[str, str] | None:
    emails = [contact for contact in contacts if contact.kind == "email"]
    if emails:
        ranked = sorted(
            emails,
            key=lambda c: (
                c.confidence != "Strong",
                c.value.split("@", 1)[0].lower() in GENERIC_EMAIL_LOCALPARTS,
                c.value,
            ),
        )
        return ranked[0].kind, ranked[0].value.casefold()
    phones = [contact for contact in contacts if contact.kind == "phone"]
    if phones:
        return phones[0].kind, phones[0].value.casefold()
    pages = [contact for contact in contacts if contact.kind == "contact_page"]
    if pages:
        return pages[0].kind, pages[0].value.casefold()
    return None


def _valid_email(value: str) -> bool:
    value = value.strip().strip(".,;:()[]<>")
    if not EMAIL_RE.fullmatch(value):
        return False
    lowered = value.lower()
    return not any(lowered.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"))


def _normalize_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _registrable_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host
