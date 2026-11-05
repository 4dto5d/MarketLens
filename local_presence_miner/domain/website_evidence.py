"""Bounded capture eligibility and URL identity, not proof of business ownership.

HTTP success is transport evidence only. These rules retain their triggers and
do not attempt universal parked-page detection or infer the unseen site's state.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from local_presence_miner.domain.models import WebsiteAudit

RESPONSE_VERSION = 6
_RESPONSE_HEADINGS = (
    ("suspension", r"(?:(?:this|the|your) )?(?:account|hosting(?: account)?|website|site) (?:(?:is|has been|was) )?(?:(?:temporarily|currently) )?suspended"),
    ("parked_domain", r"(?:this )?domain (?:is )?(?:for sale|parked)|buy this domain"),
    ("placeholder", r"(?:website |site )?(?:coming soon|under construction)|(?:default|welcome to the) (?:web server|nginx|apache) page"),
    ("access_challenge", r"just a moment|checking your browser(?: before (?:accessing|continuing to) .{1,160})?|"
     r"(?:please wait while we )?verify (?:that )?you are human(?: to continue)?|please wait while we verify your browser|access denied|attention required"),
    (
        "platform_failure",
        r"(?:service|temporarily|website) unavailable|(?:site|website|service) temporarily unavailable|"
        r"(?:internal server|bad gateway|gateway timeout|application) error|error (?:403|404|500|502|503)",
    ),
    ("maintenance", r"(?:website|site) (?:is )?(?:under|down for) maintenance|maintenance (?:mode|in progress)|we are performing scheduled maintenance"),
)
_SHELL_CONTENT = r"(?:(?:the|our|your|this)\s+)?(?:website|site|page|content)"
_PROGRESS_CLAUSE = (
    r"(?:(?:progress\s*:?\s*)?\d+(?:[.,]\d+)?\s*%(?:\s+(?:complete|completed|loaded|done))?|"
    r"\d+\s*(?:/|of)\s*\d+(?:\s+(?:resources|files|items|steps))?(?:\s+(?:loaded|complete|completed))?|"
    r"(?:almost|nearly)\s+(?:ready|there|done)|(?:initializing|preparing|connecting)(?:\s+(?:the\s+)?(?:site|page|content|resources))?)"
)
_SHELL_CLAUSE = (
    rf"(?:loading(?:\s+{_SHELL_CONTENT})?|please\s+wait(?:\s+while\s+(?:"
    rf"{_SHELL_CONTENT}\s+(?:loads|is\s+loading)|we\s+load\s+{_SHELL_CONTENT}))?|"
    rf"redirecting|something\s+went\s+wrong|an\s+unexpected\s+error\s+occurred|{_PROGRESS_CLAUSE})"
)
# Full compositions of response-status clauses, never an isolated keyword in
# business prose. Static branding/Service JSON-LD is not rendered content.
_UNCERTAIN_SHELL = re.compile(rf"{_SHELL_CLAUSE}(?:[\s,.!…:;\-]+{_SHELL_CLAUSE})*[\s,.!…:;\-]*", re.I)
# Structural greetings/navigation are not descriptions of a business. This
# vocabulary never filters words inside substantive service prose.
_INCIDENTAL_LABEL = re.compile(
    r"(?:(?:welcome|home|homepage|menu|navigation|about|us|contact|login|sign|in|up|to|our|the|page|site|website)[\s,.!…:;\-]*)+", re.I,
)
# An active status clause followed by unrecognized status text is not positive
# business evidence either. Require an independently descriptive clause rather
# than letting a changed progress message defeat the finite shell grammar.
_STATUS_PREFIX = re.compile(
    rf"(?:^|[.!…;])\s*{_SHELL_CLAUSE}(?=$|[.!…:;,\-]|\s+(?:\d|please\b))", re.I,
)
_BUSINESS_PROSE = re.compile(
    r"\b(?:we|our\s+(?:team|staff|business|company|technicians))\s+"
    r"(?:\w+\s+){0,2}(?:repair|fix|install|build|design|manage|maintain|sell)\s+\w+|"
    r"\b(?:we|our\s+team)\s+(?:\w+\s+){0,2}(?:offer|provide|deliver)\s+"
    r"(?:\w+\s+){0,3}(?:services?|repairs?|maintenance|management|plans?)\b|"
    r"\b(?:services?|repairs?|maintenance|management|plans?)\s+(?:\w+\s+){0,2}(?:for|available|include)\b", re.I,
)


def _label(value: str) -> str:
    return " ".join(value.casefold().split()).strip(" ,.!…:;-")


def _without_labels(text: str, labels: tuple[str, ...]) -> str:
    """Remove observed whole labels, not arbitrary substrings or service words."""
    text = _label(text)
    for label in sorted({_label(value) for value in labels if _label(value)}, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(label)}(?!\w)", " ", text)
    return _label(text)


def _descriptive_text(text: str) -> bool:
    if not re.search(r"[^\W\d_]", text) or _UNCERTAIN_SHELL.fullmatch(text) or _INCIDENTAL_LABEL.fullmatch(text):
        return False
    return not _STATUS_PREFIX.search(text) or bool(_BUSINESS_PROSE.search(text))


def current_response_proves_content(recorded: Any, derived: dict[str, Any]) -> bool:
    """A current actual capture can resolve lossy facts, never shell counterproof.

    Imported facts cannot invoke this exception: the stable page contract has
    no response-validity field. Older normal captures are not newly certified.
    """
    proof = recorded.get("content_proof") if isinstance(recorded, dict) else None
    return bool(
        derived.get("state") == "uncertain"
        and derived.get("indicators")
        and all(item.get("kind") == "insufficient_content" for item in derived["indicators"])
        and isinstance(recorded, dict)
        and type(recorded.get("version")) is int and recorded["version"] == RESPONSE_VERSION
        and recorded.get("state") == "normal"
        and page_identity(str(recorded.get("url", ""))) == page_identity(str(derived.get("url", "")))
        and type(recorded.get("status_code")) is int and recorded["status_code"] == derived.get("status_code")
        and recorded.get("indicators") == []
        and isinstance(recorded.get("reason"), str) and recorded["reason"].strip()
        and isinstance(proof, dict) and proof.get("kind") == "visible_body"
        and isinstance(proof.get("text"), str) and _descriptive_text(proof["text"])
    )


def _heading_indicator(value: str) -> str:
    # A provider brand suffix does not turn an explicit suspension into content.
    # Whole phrase matching still protects normal isolated suspicious words.
    for part in re.split(r"\s*[|—–]\s*|\s+-\s+", value):
        label = " ".join(part.casefold().split()).strip(" .!…:-")
        for kind, pattern in _RESPONSE_HEADINGS:
            if re.fullmatch(pattern, label):
                return kind
    return ""


def page_identity(url: str) -> str:
    """Only structural equivalences; path/query distinctions remain intact."""
    try:
        parts = urlsplit(url)
        if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return url
        host = parts.hostname.casefold()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port and (parts.scheme.casefold(), port) not in {("http", 80), ("https", 443)}:
            host += f":{port}"
        return urlunsplit((parts.scheme.casefold(), host, parts.path or "/", parts.query, ""))
    except ValueError:
        return url


def classify_response(
    url: str,
    status_code: int | None,
    title: str,
    *,
    headings: tuple[str, ...] = (),
    visible_text: str = "",
    structural_indicators: tuple[str, ...] = (),
    content_text: str | None = None,
) -> dict[str, Any]:
    body_proof = _without_labels(
        visible_text if content_text is None else content_text,
        (title, *headings) if content_text is None else (title,),
    )
    indicators: list[dict[str, str]] = []
    if status_code is not None and (not 200 <= status_code < 300 or status_code == 204):
        indicators.append({"kind": "http_non_content", "source": "status_code", "value": str(status_code)})
    try:
        path = urlsplit(url).path.casefold()
    except ValueError:
        path = ""
    if path.endswith("/cgi-sys/suspendedpage.cgi"):
        indicators.append({"kind": "suspension_route", "source": "final_url", "value": url})
    for source, value in [("title", title), *(("h1", h) for h in headings)]:
        if kind := _heading_indicator(value):
            indicators.append({"kind": kind, "source": source, "value": value[:240]})
    # Body-only failure wording requires an explicit status statement paired
    # with a provider/retry instruction in a short shell. Never reject a page
    # merely because it discusses maintenance or suspended accounts.
    if len(visible_text.split()) <= 200:
        body = " ".join(visible_text.casefold().split())
        if (re.search(r"\b(?:this|the|your) (?:website|site|account) (?:is |has been )?(?:temporarily )?suspended\b", body)
                and re.search(r"\b(?:contact (?:your|the) hosting provider|restore (?:this|the) (?:website|site))\b", body)):
            indicators.append({"kind": "suspension", "source": "visible_html", "value": visible_text[:240]})
        if ("we are performing scheduled maintenance" in body
                and re.search(r"\b(?:please try again later|we will be back|check back later)\b", body)):
            indicators.append({"kind": "maintenance", "source": "visible_html", "value": visible_text[:240]})
    indicators.extend({"kind": "access_challenge", "source": "html_structure", "value": marker} for marker in structural_indicators)
    if indicators:
        state = "non_normal"
        reason = "Captured response has a non-business/availability indicator; validate retrieval, ownership and hosting before content diagnosis."
    elif status_code is None or not _descriptive_text(body_proof):
        state = "uncertain"
        reason = "Captured content/transport supplies no descriptive proof beyond branding/headings/status; representative business content remains UNKNOWN."
        indicators.append({"kind": "response_shell" if visible_text.strip() else "no_visible_content",
                           "source": "visible_html", "value": visible_text.strip()[:240] or "empty"})
    else:
        state = "normal"
        reason = ("Descriptive visible HTML beyond branding and headings supports bounded ordinary analysis; "
                  "ownership, rendered behavior and unseen platform failures are not verified.")
    return {"version": RESPONSE_VERSION, "state": state, "url": url, "status_code": status_code, "indicators": indicators, "reason": reason,
            "content_proof": {"kind": "visible_body", "text": body_proof} if state == "normal" else None}


def classify_page_facts(page: dict[str, Any]) -> dict[str, Any]:
    """Derive eligibility without modifying an imported/historical observation.

    Structured snapshots do not carry HTML. Explicit title/H1/route/status
    counterevidence uses the same rules as acquisition. Count and static
    branding/schema alone do not establish representative content. Missing
    content support or unknown transport stays uncertain.
    """
    headings, title = page.get("h1", []), page.get("title", "")
    status, count = page.get("status_code"), page.get("word_count")
    malformed = not isinstance(headings, (list, tuple)) or any(not isinstance(item, str) for item in headings)
    malformed = malformed or not isinstance(title, str)
    result = classify_response(str(page.get("url", "")), status if type(status) is int else None, title if isinstance(title, str) else "",
                               headings=tuple(headings) if not malformed else ())
    result["basis"] = "structured_page_facts"
    result["observed_at"] = page.get("observed_at", "UNKNOWN")
    result["source_ref"] = page.get("source_ref", "")
    if result["state"] == "non_normal":
        return result
    if malformed:
        result.update(reason="Stored page title/headings are malformed; content eligibility remains UNKNOWN.")
        return result
    # A title can be static branding while every content heading still says
    # Loading. Count/schema alone cannot resolve that ambiguity without HTML.
    # Prefer the actual H1 evidence; retain title-only shell detection when no
    # headings are supplied. Genuine service headings are not keyword-filtered.
    populated = [label.strip() for label in headings if label.strip()]
    if not populated and title.strip():
        populated = [title.strip()]
    brand = _label(title)
    meaningful = [label for label in populated if _label(label) != brand]
    if (populated and all(_UNCERTAIN_SHELL.fullmatch(label) for label in populated)) or (
            meaningful and all(_UNCERTAIN_SHELL.fullmatch(label) for label in meaningful)):
        result.update(reason="Supplied headings describe only a loading/response shell; intended business-page content remains UNKNOWN.")
        result["indicators"] = [{"kind": "response_shell", "source": "h1" if any(headings) else "title", "value": label[:240]}
                                for label in populated]
        return result
    if not (type(status) is int and 200 <= status < 300 and status != 204
            and isinstance(count, (int, float)) and not isinstance(count, bool) and math.isfinite(count) and count > 0):
        result.update(reason="Supplied page content or transport eligibility is UNKNOWN; validate the actual page before ordinary content or SEO diagnosis.")
        return result
    # Meta descriptions, schemas and counts cannot supply omitted visible
    # content. Only descriptive *reported visible headings* support bounded
    # structured analysis; a greeting/brand is insufficient even with metadata.
    # Count is a consistency veto, never affirmative proof of unseen prose.
    heading_support = any(_descriptive_text(_without_labels(label, (title,))) for label in headings)
    heading_words = sum(len(re.findall(r"\b\w+(?:['’-]\w+)*\b", label)) for label in headings)
    if not heading_support or count <= heading_words:
        result.update(reason="Stored facts supply only count/branding/static metadata; representative content remains UNKNOWN without a current capture.")
        result["indicators"] = [{"kind": "insufficient_content", "source": "structured_page_facts", "value": title[:240]}]
        return result
    result.update(state="normal", indicators=[],
                  reason="Supplied page facts report descriptive visible headings eligible for bounded analysis; "
                         "ownership, rendered behavior and omitted content are not verified.")
    return result


def _capture_page_facts(evidence: dict, url: str) -> dict[str, Any] | None:
    """Find the observed final root, not a different service page or new fetch."""
    try:
        pages = json.loads(evidence.get("seo_pages_v1", "[]"))
        if not isinstance(pages, list):
            return None
        for page in pages:
            if isinstance(page, dict) and page_identity(str(page.get("url", ""))) == page_identity(url):
                return page
    except (TypeError, ValueError):
        pass
    return None


def capture_state(*, evidence: dict, url: str, final_url: str, title: str, status_code: int | None) -> str:
    """Read recorded classification; old captures are not newly certified normal.

    Legacy captures retain existing observation eligibility only when there is
    no explicit counter-evidence. Strong stored suspension evidence is blocked.
    Malformed, mismatched or unknown-version new classifications fail closed.
    """
    if not isinstance(evidence, dict):
        return "uncertain"
    legacy = classify_response(final_url or url, status_code, title)
    if legacy["state"] == "non_normal":
        return "non_normal"
    facts = _capture_page_facts(evidence, final_url or url)
    derived = classify_page_facts(facts) if facts else None
    if derived and derived["state"] == "non_normal":
        return str(derived["state"])
    if "website_response_v1" not in evidence:
        return "uncertain" if derived and derived["state"] == "uncertain" else "legacy_unclassified"
    try:
        value = evidence["website_response_v1"]
        value = json.loads(value) if isinstance(value, str) else value
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int or value["version"] not in {1, 2, 3, 4, 5, RESPONSE_VERSION}
            or page_identity(str(value.get("url", ""))) != page_identity(final_url or url)
            or value.get("status_code") != status_code
            or value.get("state") not in {"normal", "non_normal", "uncertain"}
            or not isinstance(value.get("indicators"), list)
            or not isinstance(value.get("reason"), str)
        ):
            return "uncertain"
        if derived and derived["state"] == "uncertain" and not current_response_proves_content(value, derived):
            return "uncertain"
        if value["version"] < RESPONSE_VERSION and value["state"] == "normal":
            # Earlier versions could certify shells now rejected. Use
            # original facts, never silently upgrade missing historical proof.
            return "legacy_unclassified" if derived else "uncertain"
        return str(value["state"])
    except (ValueError, TypeError):
        return "uncertain"


def ordinary_content_projection(audit: WebsiteAudit) -> WebsiteAudit:
    """Sanitize the current consumer view, never the stored historical bytes."""
    state = capture_state(evidence=audit.evidence, url=audit.url, final_url=audit.final_url, title=audit.title, status_code=audit.status_code)
    if state not in {"non_normal", "uncertain"}:
        return audit
    return replace(
        audit,
        checks={},
        rendered_checks={},
        strengths=[],
        weaknesses=[f"Captured response eligibility is {state}; verify site availability, ownership, hosting and retrieval before ordinary website diagnosis."],
    )
