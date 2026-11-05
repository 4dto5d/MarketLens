from __future__ import annotations

from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import apply_do_not_contact
from local_presence_miner.database.schema import Lead


class SuppressionService:
    def suppress_lead(self, session: Session, lead: Lead, reason: str) -> None:
        apply_do_not_contact(session, lead, reason)
