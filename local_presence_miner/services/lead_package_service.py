from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan
from local_presence_miner.services.comparison_service import ComparisonService
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.mockup_service import MockupService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.report_service import ReportService, lead_artifact_slug
from local_presence_miner.services.static_site_service import StaticSiteService
from local_presence_miner.services.website_builder_prompt_service import WebsiteBuilderPromptService


class LeadPackageService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def export_package(self, session: Session, lead: Lead, ai_mode: str = "prompt") -> Path:
        report = ReportService(self.config).generate_report(session, lead, report_kind="owner_full")
        mockup = MockupService(self.config).generate_mockup(lead)
        comparison = ComparisonService(self.config).generate_comparison(session, lead, ai_mode=ai_mode)
        proposal = ProposalService(self.config).generate_proposal(session, lead)
        delivery = DeliveryPacketService().generate(session, lead, self.config)
        site_folder = StaticSiteService(self.config).export_site(lead, session=session)
        builder_prompts = WebsiteBuilderPromptService(self.config).write_bundle(session, lead)
        artifact_slug = lead_artifact_slug(lead)
        prompt = self.config.output_dir / "prompts" / f"{artifact_slug}-competitor-prompt.txt"
        prompt_file = prompt if ai_mode in {"prompt", "prompt-paste", "api"} and prompt.exists() else None
        site_files = sorted((path for path in site_folder.rglob("*") if path.is_file()), key=lambda path: str(path.relative_to(site_folder)))
        plan, _pricing = build_adaptive_sales_plan(session, lead)

        ordinary_files = [report, mockup, comparison, proposal, delivery, delivery.with_suffix(".json"), prompt_file, *builder_prompts.values()]
        manifest_files = [*ordinary_files, *site_files]
        member_records: list[dict[str, str]] = []
        for path in ordinary_files:
            if path and path.exists():
                member_records.append({"arcname": path.name, "sha256": _file_sha256(path)})
        for path in site_files:
            member_records.append({"arcname": f"site_export/{path.relative_to(site_folder)}", "sha256": _file_sha256(path)})

        # The package identity covers exact member bytes plus every manifest-only
        # lead field.  File names alone are insufficient because generators may
        # reuse a path while their rendered contents change.
        manifest_identity = self._manifest_payload(
            lead,
            manifest_files,
            smart_offer=plan.smart_offer.to_dict(),
            artifact_fingerprint="",
        )
        package_dependencies = {
            "manifest": manifest_identity,
            "members": member_records,
        }
        package_fingerprint = fingerprint(package_dependencies)[:16]
        manifest = self.write_manifest(
            lead,
            manifest_files,
            smart_offer=plan.smart_offer.to_dict(),
            artifact_fingerprint=package_fingerprint,
        )

        package_path = self.config.output_dir / "packages" / f"{artifact_slug}-lead-package--{package_fingerprint}.zip"
        package_path.parent.mkdir(parents=True, exist_ok=True)
        # An identical dependency identity represents the same immutable package.
        # Do not rewrite it just to refresh ZIP timestamps.
        if package_path.exists():
            return package_path
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in [*ordinary_files, manifest]:
                if path and path.exists():
                    archive.write(path, arcname=path.name)
            for path in site_files:
                archive.write(path, arcname=f"site_export/{path.relative_to(site_folder)}")
        return package_path

    def _manifest_payload(
        self,
        lead: Lead,
        files: list[Path | None],
        *,
        smart_offer: dict | None = None,
        artifact_fingerprint: str = "",
    ) -> dict:
        return {
            "business_name": lead.name,
            "category": lead.category,
            "phone": lead.phone,
            "website": lead.website,
            "google_maps_url": lead.google_maps_url,
            "yelp_url": lead.yelp_url,
            "lead_score": lead.lead_score,
            "priority": lead.priority,
            "sales_priority_score": lead.sales_priority_score,
            "qualification_class": lead.qualification_class,
            "qualification_confidence": lead.qualification_confidence,
            "qualification": loads(lead.qualification_json, {}),
            "smart_offer": smart_offer if smart_offer is not None else {},
            "artifact_fingerprint": artifact_fingerprint,
            "contact_discovery_status": lead.contact_discovery_status,
            "recommended_offer": lead.recommended_offer,
            "target_signals": loads(lead.target_signals_json, []),
            "warnings": [
                "Manual review is required before sending any outreach.",
                "Do not claim the Google profile is unclaimed unless ownership was manually verified.",
                "Do not create, buy, schedule, or disguise fake reviews.",
                "Do not guarantee rankings, revenue, call volume, or review counts.",
            ],
            "files": [path.name for path in files if path and path.exists()],
        }

    def write_manifest(
        self, lead: Lead, files: list[Path | None], *, smart_offer: dict | None = None, artifact_fingerprint: str = ""
    ) -> Path:
        manifest_path = self.config.output_dir / "packages" / f"{lead_artifact_slug(lead)}--{artifact_fingerprint or 'legacy'}-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = self._manifest_payload(
            lead,
            files,
            smart_offer=smart_offer,
            artifact_fingerprint=artifact_fingerprint,
        )
        if not manifest_path.exists():
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
