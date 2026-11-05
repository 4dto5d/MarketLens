from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.repositories import lead_google_details_retrieved
from local_presence_miner.database.schema import GooglePresenceAssessment, Lead
from local_presence_miner.services.adaptive_sales_asset_service import refresh_adaptive_sales_assets
from local_presence_miner.services.google_presence_service import GooglePresenceService
from local_presence_miner.services.qualification_service import QualificationService


class V0111BackfillService:
    """Recompute Google-aware intelligence for pre-v0.1.11 leads without fabricating missing evidence."""

    def run(self, session: Session, sender: SenderInfo | None = None) -> int:
        changed = 0
        for lead in session.execute(select(Lead)).scalars():
            existing = session.execute(
                select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead.id)
            ).scalar_one_or_none()
            if existing is not None:
                continue
            GooglePresenceService().evaluate_and_store(session, lead)
            QualificationService().evaluate_and_store(session, lead)
            if sender is not None and lead_google_details_retrieved(lead):
                refresh_adaptive_sales_assets(session, lead, sender)
            changed += 1
        return changed
