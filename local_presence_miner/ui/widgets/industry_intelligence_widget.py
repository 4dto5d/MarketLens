from __future__ import annotations

import html
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from local_presence_miner.database.repositories import audit_from_record, lead_google_details_retrieved, loads
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.services.comparison_service import comparison_scores

MIN_SAMPLE_SIZE = 3


class IndustryIntelligenceWidget(QWidget):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.session_factory = session_factory
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Industry Intelligence</h2>"))
        layout.addWidget(QLabel("Observed patterns in the collected sample—not estimates for the entire market."))
        refresh = QPushButton("Refresh Industry Intelligence")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        export = QPushButton("Export Current Summary to HTML")
        export.clicked.connect(self.export_html)
        layout.addWidget(export)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.refresh()

    def refresh(self) -> None:
        with self.session_factory() as session:
            leads = list(
                session.execute(select(Lead).options(selectinload(Lead.search), selectinload(Lead.audit)).order_by(Lead.category, Lead.name)).scalars()
            )
            competitors = list(session.execute(select(CompetitorRecord)).scalars())
        lead_by_place = {lead.place_id: lead for lead in leads}
        competitor_scores: dict[int, list[float]] = defaultdict(list)
        for competitor in competitors:
            competitor_lead = lead_by_place.get(competitor.competitor_place_id)
            if competitor_lead:
                scores = comparison_scores(
                    competitor_lead.website,
                    audit_from_record(competitor_lead.audit),
                    known_absent=lead_google_details_retrieved(competitor_lead)
                    and not competitor_lead.google_rich_data_stale,
                )
                observed_scores: list[int | float] = [value for value in scores.values() if value is not None]
                if observed_scores:
                    competitor_scores[competitor.lead_id].append(mean(observed_scores))
        self.output.setPlainText(build_industry_intelligence(leads, competitor_scores))

    def export_html(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Industry Intelligence",
            "industry-intelligence.html",
            "HTML files (*.html)",
        )
        if not selected:
            return
        path = Path(selected)
        path.write_text(industry_summary_html(self.output.toPlainText()), encoding="utf-8")
        QMessageBox.information(self, "Industry Intelligence exported", f"Created:\n{path}")


def build_industry_intelligence(leads: list[Lead], competitor_scores: dict[int, list[float]] | None = None) -> str:
    competitor_scores = competitor_scores or {}
    groups: dict[tuple[str, str], list[Lead]] = defaultdict(list)
    for lead in leads:
        location = f"{lead.search.city}, {lead.search.state_region}".strip(", ") if lead.search else "Unknown market"
        groups[(lead.category or "Uncategorized", location)].append(lead)

    sections: list[str] = []
    for (category, location), group in sorted(groups.items()):
        count = len(group)
        sections.extend(
            [
                f"{category.title()} — {location}",
                f"Collected sample: n={count}",
                f"Average Growth Score: {mean([lead.lead_score for lead in group]):.1f}/100",
            ]
        )
        if count < MIN_SAMPLE_SIZE:
            sections.extend([f"Sample is too small for percentages (minimum n={MIN_SAMPLE_SIZE}).", ""])
            continue

        add_rate(sections, "Website listed", sum(bool(lead.website) for lead in group), count)
        audited = [lead for lead in group if lead.audit]
        sections.append(f"Website audits available: {len(audited)} / {count}")
        for label, key in [
            ("HTTPS detected", "https"),
            ("Mobile viewport detected", "viewport"),
            ("Tap-to-call detected", "tap_to_call"),
            ("Contact form detected", "contact_form"),
            ("Quote or booking CTA detected", "booking_or_quote_language"),
            ("Service depth detected", "service_pages"),
            ("Trust signals detected", "trust_signals"),
            ("Local schema detected", "local_schema"),
        ]:
            eligible = [lead for lead in audited if key in loads(lead.audit.checks_json, {})]
            if eligible:
                detected = sum(bool(loads(lead.audit.checks_json, {}).get(key)) for lead in eligible)
                add_rate(sections, label, detected, len(eligible))

        rich_group = [lead for lead in group if lead_google_details_retrieved(lead)]
        if rich_group:
            sections.extend(
                [
                    f"Average reviews: {mean([lead.review_count for lead in rich_group]):.1f}",
                    f"Median reviews: {median([lead.review_count for lead in rich_group]):.1f}",
                    f"Average public photo count: {mean([lead.photo_count for lead in rich_group]):.1f}",
                    f"Rich Google detail coverage: {len(rich_group)} / {count}",
                ]
            )
        else:
            sections.append("Reviews/photos: Unknown — no rich Google detail observations in this sample.")
        positions = [lead.search_position for lead in group if lead.search_position is not None]
        response_times = [lead.audit.response_time_ms for lead in audited if lead.audit.response_time_ms is not None]
        if positions:
            sections.append(f"Average retained candidate position after MarketLens filters: {mean(positions):.1f} (not provider order or Maps rank)")
        if response_times:
            sections.append(f"Average website response time: {mean(response_times):.0f} ms")
        group_competitor_scores = [score for lead in group for score in competitor_scores.get(lead.id, [])]
        if group_competitor_scores:
            sections.append(f"Average competitor website readiness: {mean(group_competitor_scores):.1f}/100")

        signals: Counter[str] = Counter()
        for lead in group:
            signals.update(set(loads(lead.target_signals_json, [])))
        sections.append("Most common observed Revenue Leaks:")
        for signal, detected in signals.most_common(8):
            sections.append(f"- {signal}: {detected} / {count} ({detected / count * 100:.1f}%)")
        sections.append("")

    if not sections:
        return "No collected leads yet. Run Demo Mode or a live search first."
    sections.append("Evidence note: every rate above describes only the displayed collected sample and denominator. It is not a market-wide estimate.")
    return "\n".join(sections)


def add_rate(lines: list[str], label: str, detected: int, denominator: int) -> None:
    lines.append(f"{label}: {detected} / {denominator} ({detected / denominator * 100:.1f}%)")


def mean(values: list[int | float]) -> float:
    return sum(values) / len(values) if values else 0.0


def industry_summary_html(summary: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Industry Intelligence</title><style>body{font:16px Arial,sans-serif;max-width:960px;"
        "margin:32px auto;padding:0 20px;color:#172033}pre{white-space:pre-wrap;line-height:1.5}</style></head>"
        f"<body><h1>Industry Intelligence</h1><pre>{html.escape(summary)}</pre></body></html>"
    )
