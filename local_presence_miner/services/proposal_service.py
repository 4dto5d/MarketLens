from __future__ import annotations

import hashlib
import json
import webbrowser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import audit_from_record, loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.credibility_service import CredibilityService
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.google_presence_service import assessment_to_dict
from local_presence_miner.services.pricing_menu import SERVICE_TIERS
from local_presence_miner.services.report_service import lead_artifact_slug
from local_presence_miner.services.sales_evidence_service import SalesEvidenceService


class ProposalService:
    def __init__(self, config: AppConfig) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.config = config

    def generate_proposal(
        self,
        session: Session,
        lead: Lead,
        *,
        selected_price: int | None = None,
        internal: bool = False,
    ) -> Path:
        competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
        audit = audit_from_record(lead.audit)
        adaptive_plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=competitors)
        sales_evidence = SalesEvidenceService().build(session, lead, assessment=context.intervention_assessment,
                                                    offer_id=context.offer_id, scope=context.scope)
        delivery_packet = DeliveryPacketService().build(session, lead, context=context, selected_price=selected_price)
        offer = adaptive_plan.smart_offer
        if selected_price is not None and not pricing.price_available:
            raise ValueError("Current evidence does not support a paid proposal; validate the intervention first.")
        credibility = CredibilityService().build(session, lead.category)
        competitors_verified = bool(loads(lead.verification_json, {}).get("competitors"))
        if internal:
            suffix = "-internal-pricing"
        elif selected_price is None:
            suffix = "-proposal-draft"
        else:
            suffix = "-proposal"
        artifact_dependencies = {
            "smart_offer": adaptive_plan.smart_offer.to_dict(),
            "pricing": {
                "easy": pricing.easy_close,
                "recommended": pricing.recommended,
                "stretch": pricing.stretch,
                "reasoning": pricing.reasoning,
                "proof": pricing.proof.snapshot(),
            },
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
            "selected_price": selected_price,
            "internal": internal,
            "sales_evidence": list(sales_evidence.identity()),
            "delivery_packet": delivery_packet,
        }
        html = self.env.get_template("proposal.html.j2").render(
            lead=lead,
            audit=audit,
            competitors=competitors if internal or competitors_verified else [],
            offer=offer,
            smart_offer=adaptive_plan.smart_offer.to_dict(),
            google_presence=assessment_to_dict(lead.google_presence),
            pricing=pricing,
            selected_price=selected_price,
            is_internal=internal,
            service_tiers=SERVICE_TIERS,
            target_signals=loads(lead.target_signals_json, []) if internal else [],
            score_factors=loads(lead.score_breakdown_json, []),
            credibility_points=credibility.proposal_points,
            competitors_verified=competitors_verified,
            sales_evidence=sales_evidence,
            delivery_packet=delivery_packet,
        )
        rendered_sha256 = hashlib.sha256(html.encode("utf-8")).hexdigest()
        commercial_fingerprint = fingerprint(
            {"dependencies": artifact_dependencies, "rendered_sha256": rendered_sha256}
        )[:16]
        path = self.config.output_dir / "proposals" / f"{lead_artifact_slug(lead)}{suffix}--{commercial_fingerprint}.html"
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

    def open_proposal(
        self,
        session: Session,
        lead: Lead,
        *,
        selected_price: int | None = None,
        internal: bool = False,
    ) -> Path:
        path = self.generate_proposal(session, lead, selected_price=selected_price, internal=internal)
        webbrowser.open(path.resolve().as_uri())
        return path
