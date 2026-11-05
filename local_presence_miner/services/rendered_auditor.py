from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RenderedAuditResult:
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    desktop_screenshot: str = ""
    mobile_screenshot: str = ""
    error: str = ""


RENDERED_SECURITY_LIMITATION = (
    "Rendered-browser network auditing remains temporarily skipped (since v0.1.12): all browser subresources, redirects, "
    "and DNS destinations cannot yet be pinned to the public-network policy. Ordinary Website Audit and "
    "Contact Discovery remain enabled through the validated DNS-pinned transport."
)


def rendered_audit_availability() -> tuple[bool, str]:
    return False, RENDERED_SECURITY_LIMITATION


def edge_paths() -> list[Path]:
    import os

    roots = [os.getenv("PROGRAMFILES(X86)", ""), os.getenv("PROGRAMFILES", ""), os.getenv("LOCALAPPDATA", "")]
    return [Path(root) / "Microsoft/Edge/Application/msedge.exe" for root in roots if root]


class RenderedAuditor:
    def __init__(self, timeout_seconds: int = 20) -> None:
        self.timeout_ms = max(5, timeout_seconds) * 1000

    def audit(self, url: str, screenshot_dir: Path | None = None, capture_screenshots: bool = False) -> RenderedAuditResult:
        # Deliberately no browser launch, DNS lookup, navigation, or screenshot fetch.
        # A single unguarded browser request would bypass the Pass 1 policy.
        if not url:
            return RenderedAuditResult(status="unavailable", error="No website URL was captured.")
        return RenderedAuditResult(status="security_unavailable", error=RENDERED_SECURITY_LIMITATION)


def inspect_rendered_page(page) -> tuple[dict[str, bool], dict[str, str]]:
    body_text = page.locator("body").inner_text(timeout=5000)
    visible_links = page.locator("a:visible")
    visible_forms = page.locator("form:visible")
    link_text = " ".join(visible_links.all_inner_texts())
    combined = f"{body_text} {link_text}"

    checks = {
        "visible_primary_cta": bool(re.search(r"call now|get a quote|request (an )?estimate|book now|schedule", combined, re.I)),
        "phone_cta": page.locator('a[href^="tel:"]:visible').count() > 0,
        "contact_form": visible_forms.count() > 0,
        "booking_control": bool(re.search(r"book|schedule|appointment|request estimate|get a quote", combined, re.I)),
        "visible_navigation": page.locator("nav:visible").count() > 0,
        "service_content": bool(re.search(r"services?|repairs?|installation|what we do", body_text, re.I)),
        "trust_proof": bool(re.search(r"reviews?|testimonials?|licensed|insured|years? of experience", body_text, re.I)),
        "faq": bool(re.search(r"frequently asked|\bfaq\b", body_text, re.I)),
        "contact_information": bool(re.search(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", body_text)),
        "visible_overlay": page.locator('[role="dialog"]:visible, .modal:visible, [class*="popup"]:visible').count() > 0,
        "major_rendering_failure": len(body_text.strip()) < 80,
    }

    def snippet(pattern: str, text: str) -> str:
        match = re.search(pattern, text, re.I)
        if not match:
            return "Not detected in visible rendered content."
        start = max(0, match.start() - 45)
        end = min(len(text), match.end() + 75)
        return "Visible text: " + re.sub(r"\s+", " ", text[start:end]).strip()[:180]

    evidence = {
        "visible_primary_cta": snippet(r"call now|get a quote|request (an )?estimate|book now|schedule", combined),
        "phone_cta": "Visible tel: link detected." if checks["phone_cta"] else "No visible tel: link detected.",
        "contact_form": "Visible form element detected." if checks["contact_form"] else "No visible form element detected.",
        "booking_control": snippet(r"book|schedule|appointment|request estimate|get a quote", combined),
        "visible_navigation": "Visible nav element detected." if checks["visible_navigation"] else "No visible nav element detected.",
        "service_content": snippet(r"services?|repairs?|installation|what we do", body_text),
        "trust_proof": snippet(r"reviews?|testimonials?|licensed|insured|years? of experience", body_text),
        "faq": snippet(r"frequently asked|\bfaq\b", body_text),
        "contact_information": snippet(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", body_text),
        "visible_overlay": ("Visible dialog/modal-like element detected." if checks["visible_overlay"] else "No visible dialog/modal-like element detected."),
        "major_rendering_failure": f"Visible body text length: {len(body_text.strip())} characters.",
    }
    return checks, evidence
