from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import audit_from_record, lead_google_details_retrieved
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.models import WebsiteAudit
from local_presence_miner.domain.niche_taxonomy import resolve_niche
from local_presence_miner.domain.scoring import website_evidence_state
from local_presence_miner.services.report_service import lead_artifact_slug
from local_presence_miner.services.website_builder_prompt_service import WebsiteBuilderPromptService


@dataclass(frozen=True)
class WebsiteComparison:
    name: str
    website: str
    role: str
    completeness: int | None
    ui_friendliness: int | None
    presentation_readiness: int | None
    customer_interaction: int | None
    efficiency: int | None
    overall: int | None
    strengths: list[str]
    weaknesses: list[str]
    what_makes_good: list[str]


class ComparisonService:
    def __init__(self, config: AppConfig) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.config = config

    def generate_comparison(self, session: Session, lead: Lead, ai_mode: str = "off") -> Path:
        competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
        rows = [comparison_for_lead(lead, "Target lead")]
        rows.extend(self._competitor_rows(session, competitors))
        prompt = build_ai_prompt(lead, rows)
        prompt_path = self.write_prompt(lead, prompt) if ai_mode in {"prompt", "prompt-paste", "api"} else None
        builder_prompt_paths = WebsiteBuilderPromptService(self.config).write_bundle(session, lead) if ai_mode in {"prompt", "prompt-paste", "api"} else {}

        path = self.config.output_dir / "comparisons" / f"{lead_artifact_slug(lead)}-competitor-comparison.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        html = self.env.get_template("competitor_comparison.html.j2").render(
            lead=lead,
            rows=rows,
            prompt=prompt,
            prompt_path=prompt_path,
            ai_mode=ai_mode,
            builder_prompt_paths=builder_prompt_paths,
        )
        path.write_text(html, encoding="utf-8")
        return path

    def open_comparison(self, session: Session, lead: Lead, ai_mode: str = "off") -> Path:
        path = self.generate_comparison(session, lead, ai_mode)
        webbrowser.open(path.resolve().as_uri())
        return path

    def write_prompt(self, lead: Lead, prompt: str) -> Path:
        path = self.config.output_dir / "prompts" / f"{lead_artifact_slug(lead)}-competitor-prompt.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")
        return path

    def _competitor_rows(self, session: Session, competitors: list[CompetitorRecord]) -> list[WebsiteComparison]:
        rows: list[WebsiteComparison] = []
        for competitor in competitors:
            competitor_lead = session.execute(select(Lead).where(Lead.place_id == competitor.competitor_place_id)).scalar_one_or_none()
            if competitor_lead:
                rows.append(comparison_for_lead(competitor_lead, "Competitor"))
                continue
            rows.append(
                WebsiteComparison(
                    name=competitor.competitor_name,
                    website="",
                    role="Competitor",
                    completeness=None,
                    ui_friendliness=None,
                    presentation_readiness=None,
                    customer_interaction=None,
                    efficiency=None,
                    overall=None,
                    strengths=[competitor.reason],
                    weaknesses=["No local audit record was found for this competitor."],
                    what_makes_good=["Manual review needed."],
                )
            )
        return rows


def comparison_for_lead(lead: Lead, role: str) -> WebsiteComparison:
    audit = audit_from_record(lead.audit)
    scores = comparison_scores(
        lead.website, audit,
        known_absent=lead_google_details_retrieved(lead) and not lead.google_rich_data_stale,
    )
    strengths = list(audit.strengths) or ["No clear website strengths captured yet."]
    weaknesses = list(audit.weaknesses) or [
        "Website audit evidence is unavailable." if scores["completeness"] is None
        else "No major website weaknesses captured by the quick audit."
    ]
    what_makes_good = good_website_notes(lead.category, audit)
    return WebsiteComparison(
        name=lead.name,
        website=lead.website,
        role=role,
        completeness=scores["completeness"],
        ui_friendliness=scores["ui_friendliness"],
        presentation_readiness=scores["presentation_readiness"],
        customer_interaction=scores["customer_interaction"],
        efficiency=scores["efficiency"],
        overall=round(sum(value for value in scores.values() if value is not None) / len(scores))
        if all(value is not None for value in scores.values()) else None,
        strengths=strengths,
        weaknesses=weaknesses,
        what_makes_good=what_makes_good,
    )


def comparison_scores(website: str, audit: WebsiteAudit, *, known_absent: bool = True) -> dict[str, int | None]:
    if not website:
        return {key: 0 if known_absent else None for key in ["completeness", "ui_friendliness", "presentation_readiness", "customer_interaction", "efficiency"]}
    if website_evidence_state(audit) == "unknown":
        return {key: None for key in ["completeness", "ui_friendliness", "presentation_readiness", "customer_interaction", "efficiency"]}
    if not audit.reachable:
        return {
            "completeness": 10,
            "ui_friendliness": 5,
            "presentation_readiness": 5,
            "customer_interaction": 5,
            "efficiency": 10,
        }
    checks = audit.checks
    response_time = int(audit.response_time_ms or 3000)
    return {
        "completeness": pct(
            [
                checks.get("has_title", False),
                checks.get("has_meta_description", False),
                checks.get("has_h1", False),
                checks.get("service_pages", False),
                checks.get("trust_signals", False),
                checks.get("local_schema", False),
            ]
        ),
        "ui_friendliness": pct(
            [
                checks.get("viewport", False),
                checks.get("clear_primary_cta", False),
                checks.get("tap_to_call", False),
                checks.get("booking_or_quote_language", False),
            ]
        ),
        "presentation_readiness": pct(
            [
                checks.get("trust_signals", False),
                checks.get("service_pages", False),
                checks.get("social_links", False),
                bool(audit.title),
                bool(audit.meta_description),
            ]
        ),
        "customer_interaction": pct(
            [
                checks.get("tap_to_call", False),
                checks.get("contact_form", False),
                checks.get("booking_or_quote_language", False),
                checks.get("map_embed", False),
            ]
        ),
        "efficiency": pct(
            [
                checks.get("https", False),
                response_time <= 1200,
                response_time <= 2500,
                audit.status_code in {200, 301, 302},
            ]
        ),
    }


def pct(values: list[bool]) -> int:
    if not values:
        return 0
    return round((sum(1 for value in values if value) / len(values)) * 100)


def good_website_notes(category: str, audit: WebsiteAudit) -> list[str]:
    niche = resolve_niche(category)
    notes = [
        "Clear service area, phone CTA, quote/contact path, proof, and recent work examples.",
        "Trust proof should be visible before a visitor has to scroll far.",
        "The page should make the next action obvious: call, request quote, book, or send photos.",
    ]
    if niche.canonical_id in {"roofing", "plumbing", "hvac", "electrical"}:
        notes.append("Emergency/service businesses need tap-to-call, urgency language, service area, and job-photo proof.")
    if niche.canonical_id in {"dental", "med_spa"}:
        notes.append("Health businesses need reassurance, staff/provider proof, appointment flow, and clear insurance/payment notes.")
    if niche.service_family == "beauty_personal_care" or niche.canonical_id == "med_spa":
        notes.append("Beauty businesses need gallery proof, booking flow, prices/services, and review/social proof.")
    if audit.checks.get("local_schema", False):
        notes.append("Local schema is present, which helps machines understand the business details.")
    return notes


def build_ai_prompt(lead: Lead, rows: list[WebsiteComparison]) -> str:
    details_retrieved = lead_google_details_retrieved(lead) and not lead.google_rich_data_stale
    lines = [
        "You are helping improve a local business website and Google presence.",
        "Use only the observations below. Do not invent private facts, copy competitor text, or guarantee rankings/revenue.",
        f"Target business: {lead.name}",
        f"Category: {lead.category}",
        f"Phone: {lead.phone or 'not captured'}",
        f"Website: {lead.website or ('no website listed' if details_retrieved else 'unknown — rich details not retrieved')}",
        f"Google Maps URL: {lead.google_maps_url or 'not captured'}",
        "",
        "Compare the target against the top competitors. Return:",
        "1. Target weaknesses in extensive detail.",
        "2. What each competitor does well.",
        "3. What each competitor still does poorly.",
        "4. A website plan that could match or beat the competitor average without copying them.",
        "5. Google profile cleanup recommendations.",
        "6. A truthful first-contact pitch for someone with no established track record.",
        "",
        "Observed website comparison:",
    ]
    for row in rows:
        lines.extend(
            [
                f"- {row.role}: {row.name}",
                f"  Website: {row.website or 'none listed'}",
                (
                    "  Scores: "
                    f"completeness {score_text(row.completeness)}, UI {score_text(row.ui_friendliness)}, "
                    f"presentation {score_text(row.presentation_readiness)}, "
                    f"interaction {score_text(row.customer_interaction)}, efficiency {score_text(row.efficiency)}, overall {score_text(row.overall)}"
                ),
                f"  Strengths: {'; '.join(row.strengths)}",
                f"  Weaknesses: {'; '.join(row.weaknesses)}",
                f"  Good-site notes: {'; '.join(row.what_makes_good)}",
            ]
        )
    return "\n".join(lines)


def score_text(score: int | None) -> str:
    return str(score) if score is not None else "unknown (not audited)"
