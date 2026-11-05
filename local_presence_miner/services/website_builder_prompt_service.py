from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import audit_from_record, lead_google_details_retrieved, loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.models import WebsiteAudit
from local_presence_miner.domain.scoring import website_evidence_state, website_quality_score
from local_presence_miner.services.mockup_service import infer_services
from local_presence_miner.services.report_service import lead_artifact_slug


@dataclass(frozen=True)
class BuilderPromptBundle:
    generic: str
    lovable: str
    canva: str


@dataclass(frozen=True)
class CompetitorPromptContext:
    name: str
    website: str
    reason: str
    evidence_notes: str
    quality_score: int | None
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    checks: dict[str, bool]
    rendered_checks: dict[str, bool]
    desktop_screenshot: str
    mobile_screenshot: str


SIGNALS: tuple[tuple[str, str, str | None], ...] = (
    ("clear_primary_cta", "Clear primary CTA", "primary_cta"),
    ("booking_or_quote_language", "Quote / booking path", "booking_or_quote"),
    ("tap_to_call", "Tap-to-call", "phone_link"),
    ("contact_form", "Contact form", "form"),
    ("service_pages", "Service depth", "services"),
    ("trust_signals", "Trust / review proof", "trust"),
    ("faq_content", "FAQ content", "faq"),
    ("local_schema", "LocalBusiness schema", None),
    ("viewport", "Mobile viewport", None),
    ("https", "HTTPS", None),
)


class WebsiteBuilderPromptService:
    """Generate evidence-grounded prompts for external AI website builders.

    The prompts are intentionally local files only. This service never calls Lovable,
    Canva, or any other external builder.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def build_bundle(self, session: Session, lead: Lead) -> BuilderPromptBundle:
        generic = build_generic_prompt(session, lead)
        return BuilderPromptBundle(
            generic=generic,
            lovable=build_lovable_prompt(generic),
            canva=build_canva_prompt(generic),
        )

    def write_bundle(
        self,
        session: Session,
        lead: Lead,
        destination: Path | None = None,
    ) -> dict[str, Path]:
        bundle = self.build_bundle(session, lead)
        folder = destination or (self.config.output_dir / "builder_prompts")
        folder.mkdir(parents=True, exist_ok=True)
        base = lead_artifact_slug(lead)
        paths = {
            "generic": folder / f"{base}__AI-WEBSITE-BUILDER-PROMPT.md",
            "lovable": folder / f"{base}__LOVABLE-PROMPT.md",
            "canva": folder / f"{base}__CANVA-WEBSITE-PROMPT.md",
        }
        paths["generic"].write_text(bundle.generic, encoding="utf-8")
        paths["lovable"].write_text(bundle.lovable, encoding="utf-8")
        paths["canva"].write_text(bundle.canva, encoding="utf-8")
        return paths


def build_generic_prompt(session: Session, lead: Lead) -> str:
    details_retrieved = lead_google_details_retrieved(lead)
    target_audit = audit_from_record(lead.audit)
    competitors = _competitor_contexts(session, lead)
    target_signals = [str(item) for item in loads(lead.target_signals_json, [])]
    candidate_services = infer_services(lead.category)
    gap_lines = _competitor_gap_lines(target_audit, competitors)

    target_strengths = list(target_audit.strengths) or ["No strong website strengths were captured automatically; verify manually."]
    target_weaknesses = list(target_audit.weaknesses) or ["No major website weaknesses were captured automatically; verify manually."]

    lines = [
        f"# AI Website Builder Prompt — {lead.name}",
        "",
        "## Role",
        "Create a prospect-specific website concept for the local business below using only the supplied public evidence.",
        "The purpose is to demonstrate concrete improvements after comparing the target with its selected nearby competitors.",
        "This is a concept/demo brief, not permission to publish a live site or claim affiliation with the business.",
        "",
        "## Non-negotiable truth rules",
        "- Do not invent testimonials, review quotes, licenses, certifications, warranties, guarantees, awards, "
        "pricing, service areas, years in business, financing, staff names, or credentials.",
        "- Do not copy competitor wording, branding, images, layouts, or proprietary creative work.",
        "- Do not guarantee rankings, traffic, leads, calls, revenue, or conversion gains.",
        "- Treat every item marked unknown/not captured as a placeholder requiring owner verification.",
        "- Preserve recognizable public business identity only where it is actually captured below.",
        "- Build for mobile clarity, trust, and an obvious contact path.",
        "",
        "## Target business — public facts",
        f"- Business: {lead.name}",
        f"- Category: {lead.category or 'not captured'}",
        f"- Address: {lead.address or 'not captured'}",
        f"- Phone: {lead.phone or 'not captured'}",
        f"- Current website: {lead.website or ('no website listed' if details_retrieved else 'unknown — not requested')}",
        f"- Google Maps: {lead.google_maps_url or 'not captured'}",
        f"- Google rating: {lead.rating if lead.rating is not None else 'not captured'}",
        f"- Google review count: {lead.review_count if details_retrieved else 'unknown — not requested'}",
        f"- Public photo count: {lead.photo_count if details_retrieved else 'unknown — not requested'}",
        f"- Public hours present: {('yes' if lead.has_hours else 'no') if details_retrieved else 'unknown — not requested'}",
        f"- Growth Score: {lead.lead_score}/100",
        "",
        "## Current strengths observed",
        *[f"- {item}" for item in target_strengths],
        "",
        "## Current weaknesses / revenue-leak evidence",
        *[f"- {item}" for item in target_weaknesses],
    ]
    if target_signals:
        lines.extend(["", "## Additional public opportunity signals", *[f"- {item}" for item in target_signals]])

    lines.extend(
        [
            "",
            "## Competitor comparison",
            f"Selected competitors with usable local records: {len(competitors)}",
        ]
    )
    if not competitors:
        lines.append("- No audited competitor records are available. Do not make competitor superiority claims; build only from the target evidence.")
    for index, competitor in enumerate(competitors, start=1):
        lines.extend(
            [
                "",
                f"### Competitor {index}: {competitor.name}",
                f"- Website: {competitor.website or 'not captured'}",
                f"- Why selected: {competitor.reason or 'selection reason not recorded'}",
                f"- Website readiness: {competitor.quality_score}/100" if competitor.quality_score is not None
                else "- Website readiness: unknown (not audited)",
                f"- Operator evidence notes: {competitor.evidence_notes or 'none'}",
                f"- Strengths: {'; '.join(competitor.strengths) if competitor.strengths else 'none captured'}",
                f"- Weaknesses: {'; '.join(competitor.weaknesses) if competitor.weaknesses else 'none captured'}",
                f"- Desktop screenshot: {competitor.desktop_screenshot or 'not captured'}",
                f"- Mobile screenshot: {competitor.mobile_screenshot or 'not captured'}",
            ]
        )

    lines.extend(["", "## Evidence-backed competitor gaps"])
    lines.extend(gap_lines or ["- No reliable multi-competitor gap could be calculated from the available audit evidence."])

    lines.extend(
        [
            "",
            "## Candidate services to verify with the business",
            "These are category-based ideas, NOT confirmed services. Do not present them as facts unless supported by the current site or owner input.",
            *[f"- {service}" for service in candidate_services[:6]],
            "",
            "## What the new concept should prove",
            "Prioritize the strongest evidence-backed differences rather than redesigning for decoration alone.",
            "1. Make the primary next step obvious within the first screen: call, request a quote, book, or contact — "
            "whichever is actually appropriate to this category and verified business workflow.",
            "2. Surface existing public trust proof more clearly when genuine proof exists.",
            "3. Make services easier to understand and navigate without inventing unsupported services.",
            "4. Improve mobile contact flow, including tap-to-call where a verified phone is available.",
            "5. Add FAQ structure for common customer questions, but use placeholder questions/answers until business-specific answers are verified.",
            "6. Use the competitor evidence to outperform the comparison set on clarity and conversion path without copying their design or text.",
            "",
            "## Required homepage structure",
            "- Hero: clear category/local-value headline, verified phone when available, and one dominant CTA.",
            "- Trust strip: only verified/public proof such as rating/review count; placeholders for unverified credentials.",
            "- Services: concise cards using only verified services; otherwise label suggested service content as needing confirmation.",
            "- Why choose / proof section: real public proof or clearly marked placeholders.",
            "- Process: simple customer next-step flow; do not invent operational promises.",
            "- FAQ: structured placeholders if exact answers are unknown.",
            "- Contact / estimate section: visible phone and form structure; form does not need a live backend in the concept.",
            "- Mobile sticky CTA when appropriate.",
            "",
            "## Visual direction",
            "Use a polished, trustworthy local-business design. Keep hierarchy clear, content scannable, and mobile interactions obvious.",
            "Avoid excessive animation, generic AI imagery, crowded sections, and decorative complexity that does not help trust or conversion.",
            "Use existing public brand colors/logo only if actually provided to the builder; otherwise use a neutral professional placeholder system.",
            "",
            "## Before implementation",
            "First return a short build plan containing:",
            "1. the page/section structure,",
            "2. the 3–5 most important design/conversion changes,",
            "3. which exact target/competitor evidence supports each change,",
            "4. every business fact that still needs verification,",
            "5. anything you would otherwise have to invent.",
            "",
            "Then implement only the evidence-supported concept. Do not silently fill missing facts.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_lovable_prompt(generic_prompt: str) -> str:
    return (
        generic_prompt
        + "\n\n## Lovable-specific execution\n"
        + "Use Lovable plan mode first. Show the proposed structure and evidence mapping before editing/building. "
        + "Keep this as a focused prospect demo rather than a large production build. Reuse maintainable components, "
        + "keep responsive behavior clean, and do not add backend/auth/database features unless the brief actually requires them. "
        + "After implementation, inspect the result and verify that every promised improvement is visibly present.\n"
    )


def build_canva_prompt(generic_prompt: str) -> str:
    return (
        generic_prompt
        + "\n\n## Canva Website-specific execution\n"
        + "Translate this brief into a visually strong single-page website concept suitable for Canva Website output. "
        + "Prioritize visual hierarchy, clear section order, trust proof, mobile readability, and one dominant contact action. "
        + "Keep copy concise enough for Canva sections. Do not invent business photography or credentials; "
        + "use clearly replaceable placeholders when assets are missing.\n"
    )


def _competitor_contexts(session: Session, lead: Lead) -> list[CompetitorPromptContext]:
    records = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
    contexts: list[CompetitorPromptContext] = []
    for record in records:
        competitor_lead = None
        if record.competitor_place_id:
            competitor_lead = session.execute(select(Lead).where(Lead.place_id == record.competitor_place_id)).scalar_one_or_none()
        if competitor_lead:
            audit = audit_from_record(competitor_lead.audit)
            contexts.append(
                CompetitorPromptContext(
                    name=competitor_lead.name,
                    website=competitor_lead.website,
                    reason=record.reason,
                    evidence_notes=record.evidence_notes,
                    quality_score=(
                        website_quality_score(audit, bool(competitor_lead.website))
                        if (
                            (not competitor_lead.website and lead_google_details_retrieved(competitor_lead)
                             and not competitor_lead.google_rich_data_stale)
                            or (competitor_lead.website and website_evidence_state(audit) != "unknown")
                        ) else None
                    ),
                    strengths=tuple(audit.strengths),
                    weaknesses=tuple(audit.weaknesses),
                    checks=dict(audit.checks),
                    rendered_checks=dict(audit.rendered_checks),
                    desktop_screenshot=audit.desktop_screenshot,
                    mobile_screenshot=audit.mobile_screenshot,
                )
            )
        else:
            contexts.append(
                CompetitorPromptContext(
                    name=record.competitor_name,
                    website=record.website_url,
                    reason=record.reason,
                    evidence_notes=record.evidence_notes,
                    quality_score=None,
                    strengths=(),
                    weaknesses=("No local audit record is available for this competitor.",),
                    checks={},
                    rendered_checks={},
                    desktop_screenshot="",
                    mobile_screenshot="",
                )
            )
    return contexts


def _signal_value(audit: WebsiteAudit, raw_key: str, rendered_key: str | None) -> bool | None:
    if rendered_key and audit.rendered_status in {"successful", "partial"} and rendered_key in audit.rendered_checks:
        return bool(audit.rendered_checks[rendered_key])
    if raw_key in audit.checks:
        return bool(audit.checks[raw_key])
    return None


def _competitor_signal_value(context: CompetitorPromptContext, raw_key: str, rendered_key: str | None) -> bool | None:
    if rendered_key and rendered_key in context.rendered_checks:
        return bool(context.rendered_checks[rendered_key])
    if raw_key in context.checks:
        return bool(context.checks[raw_key])
    return None


def _competitor_gap_lines(target_audit: WebsiteAudit, competitors: list[CompetitorPromptContext]) -> list[str]:
    lines: list[str] = []
    if not competitors:
        return lines
    for raw_key, label, rendered_key in SIGNALS:
        target_value = _signal_value(target_audit, raw_key, rendered_key)
        competitor_values = [value for value in (_competitor_signal_value(item, raw_key, rendered_key) for item in competitors) if value is not None]
        if target_value is False and competitor_values:
            passed = sum(1 for value in competitor_values if value)
            if passed:
                lines.append(f"- {label}: target did not show this signal; {passed} of {len(competitor_values)} audited competitors did.")
        elif target_value is True and competitor_values and not all(competitor_values):
            passed = sum(1 for value in competitor_values if value)
            lines.append(
                f"- Target advantage — {label}: target showed this signal; only {passed} of "
                f"{len(competitor_values)} audited competitors did. Preserve this strength."
            )
    return lines
