from __future__ import annotations

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import upsert_lead
from local_presence_miner.domain.models import BusinessProfile, ScoreBreakdown
from local_presence_miner.services.export_service import ExportService


def test_csv_export(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "test.sqlite3")
    initialize_database(factory)
    with factory() as session:
        upsert_lead(session, BusinessProfile("p", "Biz", "roofers"), None, ScoreBreakdown(75, "A", [], "Offer", "Angle", []))
        session.commit()
        path = ExportService().export_leads_csv(session, tmp_path / "exports" / "leads.csv")
    assert path.exists()
    assert "Biz" in path.read_text(encoding="utf-8")
