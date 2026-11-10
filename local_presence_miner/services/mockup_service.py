from __future__ import annotations

import webbrowser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.niche_taxonomy import resolve_niche
from local_presence_miner.services.report_service import lead_artifact_slug


class MockupService:
    def __init__(self, config: AppConfig) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "html.j2", "xml.j2"]),
        )
        self.config = config

    def generate_mockup(self, lead: Lead) -> Path:
        path = self.config.output_dir / "mockups" / f"{lead_artifact_slug(lead)}-mockup.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        html = self.env.get_template("mockup.html.j2").render(
            lead=lead,
            services=infer_services(lead.category),
            target_signals=loads(lead.target_signals_json, []),
        )
        path.write_text(html, encoding="utf-8")
        return path

    def open_mockup(self, lead: Lead) -> Path:
        path = self.generate_mockup(lead)
        webbrowser.open(path.resolve().as_uri())
        return path


def infer_services(category: str) -> list[str]:
    niche_id = resolve_niche(category).canonical_id
    if niche_id == "roofing":
        return ["Roof repair", "Roof replacement", "Storm damage", "Leak repair", "Gutters", "Free roof estimate"]
    if niche_id == "plumbing":
        return ["Leak repair", "Drain cleaning", "Water heaters", "Emergency plumbing", "Fixture installs", "Request service"]
    if niche_id == "dental":
        return ["New patient exams", "Cleanings", "Emergency dental", "Whitening", "Restorative care", "Book online"]
    if niche_id == "automotive_repair":
        return ["Diagnostics", "Brakes", "Oil changes", "Tires", "AC service", "Request appointment"]
    if niche_id == "residential_cleaning":
        return ["Recurring cleaning", "Deep cleaning", "Move-in/out cleaning", "Kitchen and bath", "Service areas", "Request a quote"]
    if niche_id == "painting":
        return ["Interior painting", "Exterior painting", "Cabinet painting", "Surface preparation", "Project gallery", "Request an estimate"]
    if niche_id == "home_automation":
        return ["Smart lighting", "Home controls", "Security integration", "Network setup", "System support", "Request a consultation"]
    return ["Services", "Pricing", "Reviews", "Gallery", "FAQ", "Contact"]
