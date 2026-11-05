from __future__ import annotations

from dataclasses import dataclass, field

import requests

from local_presence_miner.database.schema import Lead
from local_presence_miner.services.contact_discovery import WebsiteContactDiscovery


@dataclass
class FakeResponse:
    url: str
    text: str
    status_code: int = 200

    headers: dict = field(default_factory=dict)

    def close(self) -> None:
        pass

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")


class FixtureTransport:
    def __init__(self, get):
        self.get = get

    def request(self, method, target, **kwargs):
        assert target.addresses == ("93.184.216.34",)
        return self.get(target.url, **kwargs)


def public_dns(_host, _port):
    return ("93.184.216.34",)


def test_contact_discovery_finds_public_email_phone_and_contact_page() -> None:
    lead = Lead(
        place_id="contact-1",
        name="ABC Roofing",
        website="https://abcroofing.example.com",
        phone="(555) 010-2000",
        google_maps_url="https://maps.example.com/abc",
    )
    pages = {
        "https://abcroofing.example.com": FakeResponse(
            "https://abcroofing.example.com",
            '<html><body><a href="/contact">Contact</a><a href="mailto:hello@abcroofing.example.com">Email us</a>'
            '<a href="tel:+15550102000">Call</a></body></html>',
        ),
        "https://abcroofing.example.com/contact": FakeResponse(
            "https://abcroofing.example.com/contact",
            "<html><body>Owner questions: jane@abcroofing.example.com</body></html>",
        ),
    }
    discovery = WebsiteContactDiscovery(timeout_seconds=1, resolver=public_dns)
    discovery.transport = FixtureTransport(lambda url, **_kwargs: pages[url])
    result = discovery.discover(lead)
    values = {(item.kind, item.value) for item in result.contacts}
    assert ("email", "hello@abcroofing.example.com") in values
    assert ("email", "jane@abcroofing.example.com") in values
    assert any(kind == "phone" for kind, _value in values)
    assert ("contact_page", "https://abcroofing.example.com/contact") in values
    assert any(item.selected and item.kind == "email" for item in result.contacts)


def test_contact_discovery_does_not_guess_when_no_website() -> None:
    lead = Lead(place_id="contact-2", name="No Site", website="", phone="555-0100")
    result = WebsiteContactDiscovery().discover(lead)
    assert [(item.kind, item.value) for item in result.contacts] == [("phone", "555-0100")]
    assert "No official website" in result.warnings[0]


def test_contact_discovery_ignores_hidden_aria_and_css_hidden_emails() -> None:
    lead = Lead(place_id="contact-hidden", name="Hidden Contact Test", website="https://hidden.example.com")
    pages = {
        "https://hidden.example.com": FakeResponse(
            "https://hidden.example.com",
            """
            <html><head><style>.concealed { display: none; }</style></head><body>
              <div hidden>hidden-attr@hidden.example.com</div>
              <div aria-hidden="true">aria-hidden@hidden.example.com</div>
              <div style="visibility: hidden">inline-hidden@hidden.example.com</div>
              <div class="concealed"><a href="mailto:css-hidden@hidden.example.com">Hidden mail</a></div>
              <p>visible@hidden.example.com</p>
            </body></html>
            """,
        )
    }
    discovery = WebsiteContactDiscovery(timeout_seconds=1, resolver=public_dns)
    discovery.transport = FixtureTransport(lambda url, **_kwargs: pages[url])
    result = discovery.discover(lead)
    emails = {item.value for item in result.contacts if item.kind == "email"}
    assert emails == {"visible@hidden.example.com"}


def test_contact_discovery_applies_bounded_same_origin_external_css_before_extracting_email() -> None:
    lead = Lead(place_id="contact-linked-css", name="Linked CSS Test", website="https://linked.example.com")
    pages = {
        "https://linked.example.com": FakeResponse(
            "https://linked.example.com",
            """
            <html><head><link rel="stylesheet" href="/site.css"></head><body>
              <div class="concealed-contact">hidden@linked.example.com</div>
              <p>visible@linked.example.com</p>
            </body></html>
            """,
        ),
        "https://linked.example.com/site.css": FakeResponse(
            "https://linked.example.com/site.css",
            ".concealed-contact { display: none; }",
        ),
    }
    calls: list[str] = []
    discovery = WebsiteContactDiscovery(timeout_seconds=1, max_pages=1, resolver=public_dns)

    def get(url: str, **_kwargs) -> FakeResponse:
        calls.append(url)
        return pages[url]

    discovery.transport = FixtureTransport(get)
    result = discovery.discover(lead)

    assert {item.value for item in result.contacts if item.kind == "email"} == {"visible@linked.example.com"}
    assert result.pages_checked == ("https://linked.example.com",)
    assert calls == ["https://linked.example.com", "https://linked.example.com/site.css"]


def test_contact_discovery_fails_closed_when_same_origin_stylesheet_cannot_be_read() -> None:
    lead = Lead(place_id="contact-css-failure", name="CSS Failure Test", website="https://failure.example.com")
    page = FakeResponse(
        "https://failure.example.com",
        '<html><head><link rel="stylesheet" href="/site.css"></head><body>uncertain@failure.example.com</body></html>',
    )
    discovery = WebsiteContactDiscovery(timeout_seconds=1, max_pages=1, resolver=public_dns)

    def get(url: str, **_kwargs) -> FakeResponse:
        if url.endswith("site.css"):
            raise requests.ConnectionError("offline")
        return page

    discovery.transport = FixtureTransport(get)
    result = discovery.discover(lead)

    assert not [item for item in result.contacts if item.kind == "email"]
    assert any("stylesheet could not be read" in warning for warning in result.warnings)


def test_contact_discovery_does_not_fetch_cross_origin_stylesheet_and_fails_closed() -> None:
    lead = Lead(place_id="contact-cross-origin-css", name="Cross-Origin CSS Test", website="https://origin.example.com")
    page = FakeResponse(
        "https://origin.example.com",
        """
        <html><head><link rel="stylesheet" href="https://cdn.example.com/site.css"></head><body>
          uncertain@origin.example.com
        </body></html>
        """,
    )
    calls: list[str] = []
    discovery = WebsiteContactDiscovery(timeout_seconds=1, max_pages=1, resolver=public_dns)

    def get(url: str, **_kwargs) -> FakeResponse:
        calls.append(url)
        assert url == "https://origin.example.com"
        return page

    discovery.transport = FixtureTransport(get)
    result = discovery.discover(lead)

    assert not [item for item in result.contacts if item.kind == "email"]
    assert calls == ["https://origin.example.com"]
    assert any("stylesheet is not same-origin" in warning for warning in result.warnings)
