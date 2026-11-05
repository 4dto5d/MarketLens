from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from local_presence_miner import __version__
from local_presence_miner.domain.models import WebsiteAudit
from local_presence_miner.domain.website_evidence import page_identity
from local_presence_miner.services.public_url_safety import PublicTransport, Resolver, resolve_public_addresses, safe_request
from local_presence_miner.services.seo_page_analysis import analytical_page_sample, analyze_page_sample, extract_page_analysis

USER_AGENT = f"MarketLensLocal/{__version__} (+public website audit; contact operator for details)"
IMPORTANT_LINK_RE = re.compile(
    r"service|repair|roof|plumb|hvac|contact|quote|estimate|book|appointment|about|team|review|testimonial|faq|gallery|portfolio|financ|warrant|service-area|location",
    re.I,
)


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    status_code: int
    elapsed_ms: int
    soup: BeautifulSoup
    text: str
    html: str
    title: str
    meta_description: str
    x_robots_tag: str = ""
    requested_url: str = ""


class WebsiteAuditor:
    """Bounded, evidence-first local-business website audit.

    The homepage remains the anchor, but up to ``max_pages`` high-value internal
    pages are sampled so service depth, trust, and contact flow are not inferred
    from homepage links alone.
    """

    def __init__(
        self,
        timeout_seconds: int = 12,
        request_delay_seconds: float = 0.5,
        max_pages: int = 5,
        *,
        resolver: Resolver = resolve_public_addresses,
        transport: PublicTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.request_delay_seconds = request_delay_seconds
        self.max_pages = max(1, min(max_pages, 8))
        self.resolver = resolver
        self.transport = transport

    def audit(self, url: str) -> WebsiteAudit:
        if not url:
            return WebsiteAudit(
                weaknesses=["No website listed on the public profile."],
                evidence=self._seo_evidence([], [], [{"url": "", "reason": "no_website"}]),
            )
        normalized = normalize_url(url)
        try:
            home = self._fetch(normalized)
        except requests.RequestException as exc:
            return WebsiteAudit(
                url=normalized, reachable=False, weaknesses=[f"Website request failed: {exc.__class__.__name__}."],
                evidence=self._seo_evidence([], [normalized], [{"url": normalized, "reason": exc.__class__.__name__}]),
            )
        if home is None:
            return WebsiteAudit(
                url=normalized, reachable=False, weaknesses=["The response was not HTML, so page content could not be audited."],
                evidence=self._seo_evidence([], [normalized], [{"url": normalized, "reason": "non_html"}]),
            )

        response_validity = extract_page_analysis(home)[1]["response_validity"]
        if response_validity["state"] != "normal":
            evidence = self._seo_evidence([home], [normalized], [])
            evidence["website_response_v1"] = json.dumps(response_validity, ensure_ascii=False)
            return WebsiteAudit(
                url=normalized, final_url=home.url, reachable=200 <= home.status_code < 400,
                status_code=home.status_code, response_time_ms=home.elapsed_ms, title=home.title,
                meta_description=home.meta_description, weaknesses=[response_validity["reason"]],
                metrics={"pages_sampled": 1, "ordinary_pages_sampled": 0}, evidence=evidence,
            )
        pages = [home]
        requested_urls = [normalized]
        failed_pages: list[dict[str, str]] = []
        for candidate in important_internal_links(home.url, home.soup, self.max_pages - 1):
            requested_urls.append(candidate)
            try:
                page = self._fetch(candidate)
            except requests.RequestException as exc:
                failed_pages.append({"url": candidate, "reason": exc.__class__.__name__})
                continue
            if page is None:
                failed_pages.append({"url": candidate, "reason": "non_html"})
            if page is not None:
                pages.append(page)
            if len(pages) >= self.max_pages:
                break

        observed_pages = pages
        analyses = [extract_page_analysis(page) for page in pages]
        identities = analytical_page_sample([row[0] for row in analyses], [row[1] for row in analyses])
        ordinary_urls = {row["url"] for row in identities if row["response_validity"]["state"] == "normal"}
        pages = [page for index, page in enumerate(pages) if page.url in ordinary_urls
                 and page.url not in {p.url for p in pages[:index]}]
        home_checks = page_checks(home)
        all_links = [anchor for page in pages for anchor in page.soup.find_all("a", href=True)]
        contact_pages = [page.url for page in pages if re.search(r"contact|quote|estimate|book|appointment", page.url, re.I)]
        service_pages = [page.url for page in pages if re.search(r"service|repair|roof|plumb|hvac|remodel|dent|legal|med", page.url, re.I)]
        trust_pages = [page.url for page in pages if re.search(r"review|testimonial|gallery|portfolio|about|team", page.url, re.I)]
        forms = [page.url for page in pages if page.soup.find("form")]
        quote_language_pages = [page.url for page in pages if re.search(r"quote|estimate|book|schedule|appointment|request", page.text, re.I)]
        trust_text_pages = [
            page.url for page in pages if re.search(r"review|testimonial|licensed|insured|gallery|portfolio|before|warrant|guarantee", page.text, re.I)
        ]

        titles = [page.title.strip().casefold() for page in pages if page.title.strip()]
        duplicate_titles = len(titles) - len(set(titles))
        noindex_pages = [page.url for page in pages if has_noindex(page.soup)]
        canonical_pages = [page.url for page in pages if page.soup.find("link", rel=lambda value: value and "canonical" in str(value).lower())]
        image_total = sum(len(page.soup.find_all("img")) for page in pages)
        image_alt_missing = sum(1 for page in pages for img in page.soup.find_all("img") if not str(img.get("alt", "")).strip())

        checks = dict(home_checks)
        checks.update(
            {
                "contact_form": bool(forms) and bool(quote_language_pages or contact_pages),
                "booking_or_quote_language": bool(quote_language_pages),
                "service_pages": bool(service_pages) or sum(1 for a in all_links if IMPORTANT_LINK_RE.search(str(a.get("href", "")))) >= 2,
                "about_page": any(re.search(r"about|team", page.url, re.I) for page in pages),
                "trust_signals": bool(trust_text_pages),
                "faq_content": any(re.search(r"faq|frequently asked", page.text, re.I) for page in pages),
                "clear_primary_cta": any(
                    re.search(r"call now|get a quote|request estimate|book now|schedule|request service", page.text, re.I) for page in pages
                ),
                "sitewide_contact_path": bool(forms or contact_pages or any(page_checks(page).get("tap_to_call") for page in pages)),
                "sitewide_service_depth": len(service_pages) >= 2 or len(pages) >= 3 and bool(service_pages),
                "sitewide_trust_depth": len(set(trust_text_pages + trust_pages)) >= 1,
                "unique_titles_sample": duplicate_titles == 0,
                "indexable_sample": not noindex_pages,
                "canonical_coverage_sample": len(canonical_pages) >= max(1, len(pages) // 2),
                "image_alt_coverage_sample": image_total == 0 or image_alt_missing / max(1, image_total) <= 0.35,
            }
        )

        broken_count = sample_broken_internal_links(home.url, home.soup, timeout=self.timeout_seconds, resolver=self.resolver, transport=self.transport)
        metrics: dict[str, int | float | str | None] = {
            "broken_internal_links_sample": broken_count,
            "pages_sampled": len(identities),
            "ordinary_pages_sampled": len(pages),
            "service_pages_sampled": len(service_pages),
            "contact_pages_sampled": len(contact_pages),
            "trust_pages_sampled": len(set(trust_text_pages + trust_pages)),
            "duplicate_titles_sample": duplicate_titles,
            "noindex_pages_sample": len(noindex_pages),
            "canonical_pages_sample": len(canonical_pages),
            "images_sampled": image_total,
            "images_missing_alt_sample": image_alt_missing,
        }
        strengths = [label for key, label in CHECK_LABELS.items() if checks.get(key)]
        weaknesses = [f"{label} not detected." for key, label in CHECK_LABELS.items() if key in checks and not checks.get(key)]
        if not checks["sitewide_contact_path"]:
            weaknesses.append("Contact/quote path is weak across sampled pages.")
        if not checks["sitewide_service_depth"]:
            weaknesses.append("Service depth is thin across sampled pages.")
        if not checks["sitewide_trust_depth"]:
            weaknesses.append("Trust proof is thin across sampled pages.")
        if duplicate_titles:
            weaknesses.append(f"{duplicate_titles} duplicate page title(s) found in the sampled pages.")
        if noindex_pages:
            weaknesses.append(f"{len(noindex_pages)} sampled page(s) include noindex directives.")
        if image_total and image_alt_missing / max(1, image_total) > 0.35:
            weaknesses.append("More than 35% of sampled images are missing alt text.")
        if broken_count:
            weaknesses.append(f"{broken_count} broken internal links found in a capped sample.")
        if checks.get("outdated_copyright"):
            weaknesses.append("Likely outdated copyright year detected.")

        evidence = {key: home.url for key in home_checks}
        evidence.update(
            {
                "pages_sampled": " | ".join(page.url for page in pages),
                "service_pages": " | ".join(service_pages),
                "contact_pages": " | ".join(contact_pages + forms),
                "trust_pages": " | ".join(dict.fromkeys(trust_text_pages + trust_pages)),
                "sitewide_contact_path": " | ".join(dict.fromkeys(contact_pages + forms + quote_language_pages)),
            }
        )
        evidence.update(self._seo_evidence(observed_pages, requested_urls, failed_pages))
        evidence["website_response_v1"] = json.dumps(response_validity, ensure_ascii=False)
        return WebsiteAudit(
            url=normalized,
            reachable=200 <= home.status_code < 400,
            status_code=home.status_code,
            final_url=home.url,
            response_time_ms=home.elapsed_ms,
            title=home.title,
            meta_description=home.meta_description,
            checks=checks,
            metrics=metrics,
            strengths=strengths[:16],
            weaknesses=weaknesses[:20],
            evidence=evidence,
        )

    def _seo_evidence(self, pages: list[PageSnapshot], requested_urls: list[str], failed_pages: list[dict[str, str]]) -> dict[str, str]:
        analyses = [extract_page_analysis(page) for page in pages]
        facts = [analysis[0] for analysis in analyses]
        details = [analysis[1] for analysis in analyses]
        identities = analytical_page_sample(facts, details)
        failed_pages = failed_pages + [
            {"url": page.url, "reason": f"http_status_{page.status_code}"} for page in pages if not 200 <= page.status_code < 300
        ]
        limitations = [
            "Only a bounded homepage-selected HTML sample was inspected; this is not a complete crawl.",
            "Unsampled pages and missing observations remain unknown.",
            "No whole-site absence, orphaning or cannibalization conclusions follow from this sample.",
            "Robots.txt, rendered content, search index inclusion, query performance and ranking were not verified.",
        ]
        if failed_pages:
            limitations.append("Some requested pages failed or were not HTML; missing page facts are unknown.")
        sample = {
            "scope": "bounded_same_site_sample", "bounded": True, "complete": False,
            "max_pages": self.max_pages, "pages_sampled": len(identities), "observations_sampled": len(pages), "requested_urls": requested_urls,
            "ordinary_pages_sampled": sum(row["response_validity"]["state"] == "normal" for row in identities),
            "failed_pages": failed_pages, "fetch_complete": not failed_pages,
            "sample_limit_reached": len(requested_urls) >= self.max_pages, "limitations": limitations,
        }
        return {
            "seo_pages_v1": json.dumps(facts, ensure_ascii=False),
            "seo_page_details_v1": json.dumps(details, ensure_ascii=False),
            "seo_sample_v1": json.dumps(sample, ensure_ascii=False),
            "seo_page_diagnostics_v1": json.dumps(analyze_page_sample(facts, details), ensure_ascii=False),
            "seo_page_identities_v1": json.dumps([
                {"analysis_identity": row["analysis_identity"], "observed_urls": row["observed_urls"]} for row in identities
            ], ensure_ascii=False),
            "website_observations_v1": json.dumps([
                {"requested_url": page.requested_url or page.url, "url": page.url, "status_code": page.status_code,
                 "response_validity": details[index]["response_validity"]} for index, page in enumerate(pages)
            ], ensure_ascii=False),
        }

    def _fetch(self, url: str) -> PageSnapshot | None:
        time.sleep(max(0, self.request_delay_seconds))
        started = time.perf_counter()
        response = safe_request(
            requests,
            "GET",
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            resolver=self.resolver,
            transport=self.transport,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if "html" not in response.headers.get("content-type", "").lower():
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        meta_description = str(meta.get("content", "")).strip() if meta else ""
        return PageSnapshot(
            response.url, response.status_code, elapsed_ms, soup, text, response.text, title, meta_description,
            str(response.headers.get("X-Robots-Tag", "")),
            url,
        )


CHECK_LABELS = {
    "https": "HTTPS",
    "viewport": "mobile viewport",
    "has_title": "page title",
    "has_meta_description": "meta description",
    "has_h1": "H1 heading",
    "tap_to_call": "tap-to-call link",
    "contact_form": "contact or quote form",
    "booking_or_quote_language": "booking or quote language",
    "visible_phone": "visible phone number",
    "visible_address": "visible address",
    "service_pages": "service depth",
    "trust_signals": "trust signals",
    "faq_content": "FAQ content",
    "map_embed": "embedded map",
    "social_links": "social links",
    "local_schema": "LocalBusiness or Organization schema",
    "clear_primary_cta": "clear primary CTA",
    "local_wording": "local city/service wording",
    "sitewide_contact_path": "site-wide contact path",
    "sitewide_service_depth": "site-wide service depth",
    "sitewide_trust_depth": "site-wide trust depth",
    "unique_titles_sample": "unique titles in sampled pages",
    "indexable_sample": "indexable sampled pages",
    "canonical_coverage_sample": "canonical coverage in sampled pages",
    "image_alt_coverage_sample": "image alt-text coverage",
}


def page_checks(page: PageSnapshot) -> dict[str, bool]:
    soup, text = page.soup, page.text
    return {
        "https": page.url.startswith("https://"),
        "viewport": soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) is not None,
        "has_title": bool(page.title),
        "has_meta_description": bool(page.meta_description),
        "has_h1": soup.find("h1") is not None,
        "tap_to_call": soup.find("a", href=re.compile(r"^tel:", re.I)) is not None,
        "visible_phone": bool(re.search(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", text)),
        "visible_address": bool(re.search(r"\b(st|street|ave|avenue|rd|road|blvd|drive|dr)\b", text, re.I)),
        "map_embed": soup.find("iframe", src=re.compile(r"google.*maps|maps\.google", re.I)) is not None,
        "social_links": soup.find("a", href=re.compile(r"facebook|instagram|linkedin|youtube|x.com|twitter", re.I)) is not None,
        "local_schema": bool(re.search(r"LocalBusiness|Organization", page.html)),
        "local_wording": bool(re.search(r"\bnear me\b|serving|local|service area|city", text, re.I)),
        "outdated_copyright": has_outdated_copyright(text),
        "oversized_images_hint": has_oversized_image_hint(soup),
    }


def important_internal_links(base_url: str, soup: BeautifulSoup, limit: int) -> list[str]:
    base = urlparse(base_url)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", ""))
        absolute = urldefrag(urljoin(base_url, href)).url
        parsed = urlparse(absolute)
        identity = page_identity(absolute)
        if (parsed.netloc.casefold() != base.netloc.casefold() or parsed.scheme not in {"http", "https"}
                or identity in seen or identity == page_identity(base_url)):
            continue
        seen.add(identity)
        haystack = f"{href} {anchor.get_text(' ', strip=True)}"
        score = 3 if IMPORTANT_LINK_RE.search(haystack) else 0
        if re.search(r"contact|quote|estimate|book", haystack, re.I):
            score += 4
        if re.search(r"service|repair", haystack, re.I):
            score += 3
        if re.search(r"about|team|review|testimonial|faq|gallery|financ|warrant", haystack, re.I):
            score += 2
        scored.append((score, absolute))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return [url for _score, url in scored[: max(0, limit)]]


def normalize_url(url: str) -> str:
    cleaned = url.strip()
    return cleaned if cleaned.startswith(("http://", "https://")) else f"https://{cleaned}"


def has_noindex(soup: BeautifulSoup) -> bool:
    robots = soup.find("meta", attrs={"name": re.compile("robots", re.I)})
    return bool(robots and "noindex" in str(robots.get("content", "")).casefold())


def has_outdated_copyright(text: str) -> bool:
    years = [int(year) for year in re.findall(r"(?:copyright|©)\s*(20\d{2})", text, flags=re.I)]
    return bool(years and max(years) < 2024)


def has_oversized_image_hint(soup: BeautifulSoup) -> bool:
    images = soup.find_all("img")[:20]
    return any(not img.get("width") or not img.get("height") for img in images)


def sample_broken_internal_links(
    base_url: str,
    soup: BeautifulSoup,
    timeout: int,
    *,
    resolver: Resolver = resolve_public_addresses,
    transport: PublicTransport | None = None,
) -> int:
    parsed = urlparse(base_url)
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        absolute = urldefrag(urljoin(base_url, str(anchor["href"]))).url
        if urlparse(absolute).netloc == parsed.netloc and absolute not in links:
            links.append(absolute)
        if len(links) >= 8:
            break
    broken = 0
    for link in links:
        try:
            response = safe_request(
                requests,
                "HEAD",
                link,
                timeout=min(timeout, 5),
                headers={"User-Agent": USER_AGENT},
                resolver=resolver,
                transport=transport,
            )
            if response.status_code >= 400:
                broken += 1
        except requests.RequestException:
            broken += 1
    return broken
