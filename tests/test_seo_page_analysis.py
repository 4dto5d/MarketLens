from __future__ import annotations

import json

import pytest
import requests
from bs4 import BeautifulSoup

from local_presence_miner.services.seo_page_analysis import analyze_page_sample, extract_page_analysis, extract_page_facts
from local_presence_miner.services.website_auditor import PageSnapshot, WebsiteAuditor, page_checks


def snapshot(html: str, url: str = "https://fixture.example.com/", status: int = 200, robots: str = "") -> PageSnapshot:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": "description"})
    description = str(meta.get("content", "")) if meta else ""
    return PageSnapshot(url, status, 0, soup, soup.get_text(" ", strip=True), html, title, description, robots)


def test_facts_retain_page_targets_and_same_site_links_without_fetching() -> None:
    page = snapshot('''<html><title>Roof Repair in Denver</title>
        <meta name="description" content="Repair options">
        <link rel="canonical" href="/roof-repair">
        <body><nav>Navigation words</nav><main><h1>Roof Repair</h1><h1>Emergency Repair</h1>
        <p>Fast careful work.</p><a href="/contact#form">Contact</a>
        <a href="/contact#other">Contact again</a><a href="https://elsewhere.example.com/">Elsewhere</a>
        <a href="mailto:office@example.com">Email</a></main>
        <script>Organization Roof Repair</script><footer>Footer words</footer></body></html>''')
    facts = extract_page_facts(page)
    assert facts["url"] == page.url
    assert facts["title"] == "Roof Repair in Denver"
    assert facts["h1"] == ["Roof Repair", "Emergency Repair"]
    assert facts["meta_description"] == "Repair options"
    assert facts["canonical"] == "https://fixture.example.com/roof-repair"
    assert facts["internal_links"] == ["https://fixture.example.com/contact"]
    assert facts["services"] == ["Roof Repair", "Emergency Repair"]
    assert facts["service_refs"] == [page.url]
    assert facts["word_count"] == 12
    assert facts["schema_types"] == []
    assert facts["indexability"] == "allowed"


@pytest.mark.parametrize(("status", "meta", "header", "expected"), [
    (200, "", "", "allowed"),
    (200, "noindex, follow", "", "blocked"),
    (200, "index", "noindex, nofollow", "blocked"),
    (200, "", "googlebot: noindex, nofollow", "blocked"),
    (200, "none", "", "blocked"),
    (200, "nofollow", "", "allowed"),
    (200, "notnoindex", "", "unknown"),
    (200, "", "bingbot: noindex", "unknown"),
    (302, "", "", "unknown"),
    (404, "index", "", "blocked"),
    (503, "", "", "unknown"),
])
def test_indexability_is_page_level_and_accounts_for_headers(status, meta, header, expected) -> None:
    facts = extract_page_facts(snapshot(f'<meta name="robots" content="{meta}"><h1>Page</h1>', status=status, robots=header))
    assert facts["indexability"] == expected
    assert facts["status_code"] == status


def test_all_robots_meta_and_scoped_header_directives_are_retained() -> None:
    facts = extract_page_facts(snapshot('''<meta name="robots" content="index,follow">
        <meta name="ROBOTS" content="noindex"><meta name="googlebot" content="nosnippet">''', robots="googlebot: nofollow"))
    assert set(facts["robots"]) == {"index", "follow", "noindex", "googlebot: nosnippet", "googlebot: nofollow"}


def test_jsonld_must_parse_and_have_schema_context_to_confirm_services() -> None:
    page = snapshot('''<h1>Welcome</h1><p>Organization is a plain text word.</p>
        <script type="application/ld+json">{"@type":"Organization",</script>
        <script type="application/ld+json">{"@context":"https://example.com/custom", "@type":"Service", "serviceType":"Roof Repair"}</script>
        <script type="application/ld+json">{"@context":"https://schema.org", "@graph":[
          {"@type":"RoofingContractor", "category":"Plumbing", "hasOfferCatalog":{
            "itemListElement":[{"itemOffered":{"@type":"Service", "serviceType":"Roof Repair"}}]}},
          {"@type":"Service", "name":"Gutter Installation"}]}</script>''')
    facts = extract_page_facts(page)
    assert facts["schema_types"] == ["RoofingContractor", "Service"]
    assert facts["services"] == ["Roof Repair", "Gutter Installation"]
    assert len(facts["schema_errors"]) == 1
    assert "JSON" in facts["schema_errors"][0]
    # The existing heuristic boolean deliberately retains its historical semantics.
    assert page_checks(page)["local_schema"]


@pytest.mark.parametrize("payload", [
    '{"@context":"https://schema.org", "@type":"Service", "serviceType":NaN}',
    '"Organization"',
    '{"@context":"https://schema.org", "@type":"Service", "serviceType":42}',
])
def test_invalid_or_noncredible_jsonld_never_confirms_service(payload) -> None:
    facts = extract_page_facts(snapshot(f'<script type="application/ld+json">{payload}</script>'))
    assert facts["services"] == []
    assert facts["schema_errors"]


def test_custom_schema_context_remapping_cannot_confirm_an_offered_service() -> None:
    payload = json.dumps({"@context": ["https://schema.org", {"Service": "https://example.com/Other"}],
                          "@type": "Service", "serviceType": "Roof Repair"})
    facts = extract_page_facts(snapshot(f'<script type="application/ld+json">{payload}</script>'))
    assert facts["services"] == [] and facts["schema_types"] == []


def test_error_pages_do_not_confirm_services_and_malformed_canonical_does_not_crash() -> None:
    facts, details = extract_page_analysis(snapshot('''<main><h1>Roof Repair</h1></main>
        <link rel="canonical" href="http://["><a href="http://[">Broken markup</a>''', status=404))
    assert facts["services"] == []
    assert facts["canonical"] == "" and details["canonical_errors"]
    assert facts["internal_links"] == []


def test_schema_parser_size_limit_is_explicit_unknown() -> None:
    oversized = json.dumps({"@context": "https://schema.org", "@type": "Service", "serviceType": "Roof Repair", "description": "x" * (513 * 1024)})
    facts = extract_page_facts(snapshot(f'<script type="application/ld+json">{oversized}</script>'))
    assert facts["schema_types"] == [] and facts["services"] == []
    assert "bounded parser" in facts["schema_errors"][0]


@pytest.mark.parametrize(("url", "html"), [
    ("https://fixture.example.com/about", "<main><h1>Roof Repair</h1><p>Contact us for plumbing or HVAC.</p></main>"),
    ("https://fixture.example.com/contact", "<main><h1>Roof Repair Services</h1></main>"),
    ("https://fixture.example.com/blog/roof-repair", "<main><h1>Roof Repair</h1></main>"),
    ("https://fixture.example.com/", "<nav><h2>Roof Repair</h2></nav><main><h1>Welcome</h1><p>Plumbing Roofing HVAC</p></main>"),
    ("https://fixture.example.com/", "<main><h1>Why Roof Repair Matters</h1><h2>Our Services</h2></main>"),
    ("https://fixture.example.com/", "<main><h1>We Do Not Offer Roof Repair</h1><h2>Roof Repair Training</h2></main>"),
    ("https://fixture.example.com/", '<main><h1 hidden>Roof Repair</h1><div style="display: none"><h2>Plumbing Services</h2></div></main>'),
])
def test_mentions_categories_navigation_and_information_pages_are_not_service_proof(url, html) -> None:
    facts = extract_page_facts(snapshot(html, url=url))
    assert facts["services"] == []
    assert facts["service_refs"] == []


class FixtureTransport:
    def __init__(self, pages: dict[str, requests.Response | Exception]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str]] = []

    def request(self, method, target, **kwargs):
        self.calls.append((method, target.url))
        value = self.pages[target.url]
        if isinstance(value, Exception):
            raise value
        return value


def response(url: str, html: str, **headers: str) -> requests.Response:
    value = requests.Response()
    value.url, value.status_code, value._content = url, 200, html.encode()
    value.headers.update({"Content-Type": "text/html", **headers})
    value._content_consumed = True
    return value


def auditor(network: FixtureTransport, max_pages: int = 5) -> WebsiteAuditor:
    return WebsiteAuditor(request_delay_seconds=0, max_pages=max_pages, resolver=lambda *_: ("93.184.216.34",), transport=network)


def test_audit_evidence_preserves_boolean_contract_and_transport_bound() -> None:
    home = "https://fixture.example.com/"
    links = "".join(f'<a href="/service-{number}">Repair {number}</a>' for number in range(12))
    html = f"<title>Same Title</title><h1>Roof Repair</h1><p>We repair roofs for local homeowners.</p>{links}"
    network = FixtureTransport({home: response(home, html, **{"X-Robots-Tag": "noindex"})})
    for number in range(12):
        url = f"https://fixture.example.com/service-{number}"
        network.pages[url] = response(url, "<title>Same Title</title><h1>Roof Repair</h1><p>We repair roofs for local homeowners.</p>")
    audit = auditor(network, max_pages=100).audit(home)
    pages = json.loads(audit.evidence["seo_pages_v1"])
    contract_keys = {"url", "title", "h1", "meta_description", "canonical", "robots", "status_code", "indexability", "word_count",
                     "internal_links", "schema_types", "schema_errors", "services", "service_refs"}
    assert all(set(page) == contract_keys for page in pages)
    assert len(pages) == audit.metrics["pages_sampled"] == 8
    assert len([method for method, _ in network.calls if method == "GET"]) == 8
    assert len([method for method, _ in network.calls if method == "HEAD"]) == 8
    assert pages[0]["indexability"] == "blocked"
    assert pages[0]["robots"] == ["noindex"]
    assert audit.checks["indexable_sample"] is True  # Legacy meta-only boolean, unchanged.
    sample = json.loads(audit.evidence["seo_sample_v1"])
    assert sample["max_pages"] == 8 and sample["bounded"] and not sample["complete"]
    assert sample["sample_limit_reached"]
    assert "orphan" in " ".join(sample["limitations"]).lower()


def test_failed_sample_fetch_is_retained_as_incomplete_evidence() -> None:
    home, failed = "https://fixture.example.com/", "https://fixture.example.com/service"
    network = FixtureTransport({home: response(home, '<h1>Welcome</h1><p>We repair roofs.</p><a href="/service">Services</a>'),
                                failed: requests.Timeout()})
    audit = auditor(network).audit(home)
    sample = json.loads(audit.evidence["seo_sample_v1"])
    assert sample["failed_pages"] == [{"url": failed, "reason": "Timeout"}]
    assert not sample["fetch_complete"] and not sample["complete"]
    assert [item["url"] for item in json.loads(audit.evidence["seo_pages_v1"])] == [home]


@pytest.mark.parametrize("failure", [requests.Timeout(), None])
def test_unavailable_home_has_empty_facts_and_explicit_limitations(failure) -> None:
    home = "https://fixture.example.com/"
    value = failure if failure else response(home, "not html", **{"Content-Type": "application/pdf"})
    audit = auditor(FixtureTransport({home: value})).audit(home)
    assert not audit.reachable
    assert json.loads(audit.evidence["seo_pages_v1"]) == []
    sample = json.loads(audit.evidence["seo_sample_v1"])
    assert sample["failed_pages"] and not sample["fetch_complete"]


def test_duplicate_targets_and_offsite_canonical_diagnoses_are_validation_only() -> None:
    first, first_proof = extract_page_analysis(snapshot('<title>Roof Repair</title><main><h1>Roof Repair</h1><p>We repair roofs.</p></main>',
                                                       url="https://fixture.example.com/repair"))
    second, second_proof = extract_page_analysis(snapshot('''<title>Roof Repair</title><main><h1>Roof Repair</h1><p>We repair roofs.</p></main>
        <link rel="canonical" href="https://other.example.com/repair">''', url="https://fixture.example.com/repair-two"))
    diagnostics = analyze_page_sample([first, second], [first_proof, second_proof])
    types = {item["type"] for item in diagnostics}
    assert {"duplicate_title", "possible_target_overlap", "offsite_canonical"} <= types
    assert all({"type", "urls", "evidence", "confidence", "action", "falsifier"} <= set(item) for item in diagnostics)
    assert all(item["action"] == "validate" for item in diagnostics if item["type"] in {"duplicate_title", "possible_target_overlap", "offsite_canonical"})
    assert all(item["falsifier"] for item in diagnostics)
    assert not {"orphan", "cannibalization"} & types
