from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.repositories import (
    lead_contact_readiness_errors,
    list_contact_points,
    outreach_approval_errors,
)
from local_presence_miner.database.schema import Lead, OutreachDraft
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.outreach_planner import build_outreach_channel_plan


@dataclass(frozen=True)
class OutreachBatchSummary:
    path: Path
    review_path: Path
    exported: int
    skipped: int


class OutreachBatchService:
    """Exports operator-reviewed outreach work; it never sends messages or places calls."""

    def __init__(self, sender: SenderInfo | None = None) -> None:
        self.sender = sender or SenderInfo()

    def export_ready_csv(self, session: Session, output_dir: Path) -> OutreachBatchSummary:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "outreach-ready.csv"
        review_path = output_dir / "outreach-needs-review.csv"
        leads = list(session.execute(select(Lead).order_by(Lead.sales_priority_score.desc(), Lead.lead_score.desc())).scalars())
        rows: list[dict[str, str]] = []
        review_rows: list[dict[str, str]] = []
        for lead in leads:
            reasons = list(lead_contact_readiness_errors(session, lead))
            contacts = list_contact_points(session, lead.id)
            plan = build_outreach_channel_plan(lead, contacts)
            email_draft = session.execute(
                select(OutreachDraft).where(
                    OutreachDraft.lead_id == lead.id,
                    OutreachDraft.kind == OutreachKind.INITIAL_EMAIL.value,
                    OutreachDraft.approved.is_(True),
                )
            ).scalar_one_or_none()
            call_draft = session.execute(
                select(OutreachDraft).where(
                    OutreachDraft.lead_id == lead.id,
                    OutreachDraft.kind == OutreachKind.CALL_OPENING.value,
                    OutreachDraft.approved.is_(True),
                )
            ).scalar_one_or_none()
            relevant_draft = email_draft if plan.primary_channel in {"Email", "Contact form"} else call_draft
            if plan.state not in {"Contactable", "Limited"}:
                reasons.append(plan.reason)
            if relevant_draft is None:
                reasons.append(f"No approved {plan.primary_channel.lower()} outreach draft")
            else:
                reasons.extend(outreach_approval_errors(session, relevant_draft, self.sender))
            base = {
                "lead_id": str(lead.id),
                "business": lead.name,
                "category": lead.category,
                "priority": lead.priority,
                "sales_priority": str(lead.sales_priority_score),
                "qualification": lead.qualification_class,
                "qualification_confidence": lead.qualification_confidence,
                "growth_score": str(lead.lead_score),
                "primary_channel": plan.primary_channel,
                "secondary_channel": plan.secondary_channel,
                "email": plan.recipient,
                "phone": plan.phone,
                "contact_page": plan.contact_page,
                "status": lead.status,
                "next_follow_up": lead.next_follow_up_date,
            }
            if reasons:
                review_rows.append({**base, "reason_not_ready": "; ".join(dict.fromkeys(reasons))})
                continue
            rows.append(
                {
                    **base,
                    "subject": relevant_draft.subject if relevant_draft else "",
                    "approved_message": relevant_draft.body if relevant_draft else "",
                }
            )
        ready_fields = [
            "lead_id",
            "business",
            "category",
            "priority",
            "sales_priority",
            "qualification",
            "qualification_confidence",
            "growth_score",
            "primary_channel",
            "secondary_channel",
            "email",
            "phone",
            "contact_page",
            "subject",
            "approved_message",
            "status",
            "next_follow_up",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=ready_fields)
            writer.writeheader()
            writer.writerows(rows)
        review_fields = [
            "lead_id",
            "business",
            "category",
            "priority",
            "sales_priority",
            "qualification",
            "qualification_confidence",
            "growth_score",
            "primary_channel",
            "secondary_channel",
            "email",
            "phone",
            "contact_page",
            "status",
            "next_follow_up",
            "reason_not_ready",
        ]
        with review_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=review_fields)
            writer.writeheader()
            writer.writerows(review_rows)
        return OutreachBatchSummary(path, review_path, len(rows), len(review_rows))
