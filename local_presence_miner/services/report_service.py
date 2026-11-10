from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import webbrowser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import audit_from_record, lead_google_details_retrieved, loads
from local_presence_miner.database.schema import CompetitorRecord, Lead, OutreachDraft
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.credibility_service import CredibilityService
from local_presence_miner.services.google_presence_service import assessment_to_dict
from local_presence_miner.services.offer_service import options_for_lead
from local_presence_miner.services.sales_evidence_service import SalesEvidenceService


class ReportService:
    def __init__(self, config: AppConfig) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "html.j2", "xml.j2"]),
        )
        self.config = config

    def generate_report(self, session: Session, lead: Lead, report_kind: str = "owner_full") -> Path:
        competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
        drafts = list(session.execute(select(OutreachDraft).where(OutreachDraft.lead_id == lead.id)).scalars())
        audit = audit_from_record(lead.audit)
        adaptive_plan, _pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=competitors)
        sales_evidence = SalesEvidenceService().build(session, lead, assessment=context.intervention_assessment,
                                                    offer_id=context.offer_id, scope=context.scope)
        credibility = CredibilityService().build(session, lead.category)
        competitors_verified = bool(loads(lead.verification_json, {}).get("competitors"))
        is_internal = report_kind == "internal"
        draft_warnings: dict[int, tuple[str, ...]] = {}
        if is_internal:
            from local_presence_miner.services.commercial_state_service import draft_commercial_errors

            draft_warnings = {draft.id: draft_commercial_errors(session, draft) for draft in drafts}
        offer = adaptive_plan.smart_offer
        from local_presence_miner.services.seo_research_service import project_seo_research

        seo_research = project_seo_research(session, lead)
        suffix = "" if report_kind == "owner_full" else f"-{safe_filename(report_kind)}"
        artifact_dependencies = {
            "smart_offer": adaptive_plan.smart_offer.to_dict(),
            "competitors": [
                {
                    "id": item.competitor_place_id,
                    "name": item.competitor_name,
                    "website": item.website_url,
                    "match_score": item.match_score,
                    "snapshot": loads(item.google_snapshot_json, {}),
                }
                for item in competitors
            ],
            "audit": {"url": audit.url, "checks": audit.checks, "weaknesses": audit.weaknesses, "evidence": audit.evidence},
            "google_presence": assessment_to_dict(lead.google_presence),
            "credibility": list(credibility.proposal_points),
            "report_kind": report_kind,
            "sales_evidence": list(sales_evidence.identity()),
            **({"seo_research": seo_research} if is_internal else {}),
        }
        html = self.env.get_template("report.html.j2").render(
            lead=lead,
            google_details_retrieved=lead_google_details_retrieved(lead),
            audit=audit,
            competitors=competitors if is_internal or competitors_verified else [],
            drafts=drafts,
            draft_warnings=draft_warnings,
            offer=offer,
            offer_options=options_for_lead(lead),
            report_kind=report_kind,
            is_owner_short=report_kind == "owner_short",
            is_internal=is_internal,
            score_factors=loads(lead.score_breakdown_json, []),
            target_signals=loads(lead.target_signals_json, []),
            starting_offer=adaptive_plan.smart_offer.to_dict(),
            smart_offer=adaptive_plan.smart_offer.to_dict(),
            google_presence=assessment_to_dict(lead.google_presence),
            seo_research=seo_research,
            desktop_screenshot_uri=image_data_uri(audit.desktop_screenshot) if report_kind == "internal" else "",
            mobile_screenshot_uri=image_data_uri(audit.mobile_screenshot) if report_kind == "internal" else "",
            credibility_points=credibility.proposal_points,
            competitors_verified=competitors_verified,
            sales_evidence=sales_evidence,
            raw_html_status=raw_acquisition_status(lead.audit),
            raw_html_observed_at=lead.audit.created_at.isoformat() if lead.audit is not None and lead.audit.created_at else "UNKNOWN",
            final_review_state=sales_evidence.review_state,
        )
        rendered_sha256 = hashlib.sha256(html.encode("utf-8")).hexdigest()
        commercial_fingerprint = fingerprint(
            {"dependencies": artifact_dependencies, "rendered_sha256": rendered_sha256}
        )[:16]
        path = self.config.output_dir / "reports" / f"{lead_artifact_slug(lead)}{suffix}--{commercial_fingerprint}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(html, encoding="utf-8")
        metadata_path = path.with_suffix(".commercial.json")
        if not metadata_path.exists():
            metadata_path.write_text(
                json.dumps(
                    {
                        "commercial_fingerprint": commercial_fingerprint,
                        "rendered_sha256": rendered_sha256,
                        "dependencies": artifact_dependencies,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return path

    def open_report(self, session: Session, lead: Lead, report_kind: str = "owner_full") -> Path:
        path = self.generate_report(session, lead, report_kind)
        webbrowser.open(path.resolve().as_uri())
        return path


def safe_filename(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return clean[:80] or "lead"


def raw_acquisition_status(record) -> str:
    if record is None:
        return "missing"
    if not record.reachable or record.status_code is not None and record.status_code >= 400:
        return "failed"
    checks, evidence = loads(record.checks_json, {}), loads(record.evidence_json, {})
    complete = (record.status_code is not None and 200 <= record.status_code < 300
                and isinstance(checks, dict) and bool(checks) and isinstance(evidence, dict) and bool(evidence))
    return "complete" if complete else "partial"


def lead_artifact_slug(lead: Lead) -> str:
    """Readable, collision-resistant, stable identity for every lead artifact."""
    readable = safe_filename(lead.name)[:56]
    if lead.place_id:
        identity = hashlib.sha256(lead.place_id.encode("utf-8")).hexdigest()[:12]
    elif lead.id is not None:
        identity = f"lead-{lead.id}"
    else:
        raise ValueError("A persisted lead ID or place ID is required for artifact generation.")
    return f"{readable}--{identity}"


def image_data_uri(value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    if not path.is_file():
        return ""
    mime_type, _encoding = mimetypes.guess_type(path.name)
    if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        return ""
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
