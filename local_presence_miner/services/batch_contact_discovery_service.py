from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import replace_contact_points
from local_presence_miner.database.schema import Lead
from local_presence_miner.services.adaptive_sales_asset_service import refresh_adaptive_sales_assets
from local_presence_miner.services.contact_discovery import WebsiteContactDiscovery
from local_presence_miner.services.qualification_service import QualificationService
from local_presence_miner.time_utils import utc_now_iso


@dataclass(frozen=True)
class BatchContactDiscoverySummary:
    attempted: int
    leads_with_contacts: int
    contacts_saved: int
    warnings: tuple[str, ...]
    skipped_completed: int = 0
    failed: int = 0


class BatchContactDiscoveryService:
    """Sequential, resumable public contact discovery ordered by Sales Priority."""

    def __init__(self, config: AppConfig, session_factory: sessionmaker[Session]) -> None:
        self.config = config
        self.session_factory = session_factory

    def run(self, limit: int = 25, *, retry_failed: bool = True) -> BatchContactDiscoverySummary:
        limit = max(1, min(limit, 100))
        with self.session_factory() as session:
            query = select(Lead.id).where(Lead.suppressed.is_(False))
            status_filter = Lead.contact_discovery_status != "complete" if retry_failed else Lead.contact_discovery_status == "not_started"
            query = query.where(status_filter)
            lead_ids = list(session.execute(query.order_by(Lead.sales_priority_score.desc(), Lead.lead_score.desc(), Lead.id).limit(limit)).scalars())
        attempted = with_contacts = contacts_saved = skipped_completed = failed = 0
        warnings: list[str] = []
        for lead_id in lead_ids:
            time.sleep(max(0, self.config.request_delay_seconds))
            with self.session_factory() as session:
                lead = session.get(Lead, lead_id)
                if not lead:
                    continue
                if lead.contact_discovery_status == "complete":
                    skipped_completed += 1
                    continue
                attempted += 1
                lead.contact_discovery_status = "running"
                lead.contact_discovery_error = ""
                lead.contact_discovery_updated_at = utc_now_iso()
                session.commit()
            try:
                with self.session_factory() as session:
                    lead = session.get(Lead, lead_id)
                    if not lead:
                        continue
                    result = WebsiteContactDiscovery(self.config.request_timeout_seconds, max_pages=3).discover(lead)
                    saved = replace_contact_points(session, lead.id, [contact.to_record() for contact in result.contacts])
                    QualificationService().evaluate_and_store(session, lead)
                    refresh_adaptive_sales_assets(session, lead, self.config.sender)
                    lead.contact_discovery_status = "complete"
                    lead.contact_discovery_error = ""
                    lead.contact_discovery_updated_at = utc_now_iso()
                    session.commit()
                    if saved:
                        with_contacts += 1
                        contacts_saved += len(saved)
                    for warning in result.warnings[:2]:
                        warnings.append(f"{lead.name}: {warning}")
            except Exception as exc:  # isolate a bad business from the rest of the batch
                failed += 1
                with self.session_factory() as session:
                    lead = session.get(Lead, lead_id)
                    if lead:
                        lead.contact_discovery_status = "failed"
                        lead.contact_discovery_error = f"{exc.__class__.__name__}: {exc}"[:1000]
                        lead.contact_discovery_updated_at = utc_now_iso()
                        session.commit()
                        warnings.append(f"{lead.name}: contact discovery failed ({exc.__class__.__name__})")
        return BatchContactDiscoverySummary(attempted, with_contacts, contacts_saved, tuple(warnings), skipped_completed, failed)
