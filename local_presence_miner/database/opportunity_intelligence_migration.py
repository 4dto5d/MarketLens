"""Additive advice ledger and SQLite history/ownership guards."""
from __future__ import annotations

from sqlalchemy import text


def install_intelligence_guards(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    tables = ("opportunity_intelligence_runs", "opportunity_intelligence_results", "opportunity_intelligence_reviews")
    statements = []
    for table in tables:
        for operation in ("UPDATE", "DELETE"):
            statements.append(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                              "BEGIN SELECT RAISE(ABORT,'Intelligence history is append-only'); END")
        statements.append(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} "
                          f"WHEN EXISTS(SELECT 1 FROM {table} WHERE id=NEW.id) "
                          "BEGIN SELECT RAISE(ABORT,'Preserve intelligence history'); END")
    statements.extend([
        "CREATE TRIGGER IF NOT EXISTS intelligence_run_owner BEFORE INSERT ON opportunity_intelligence_runs "
        "WHEN NOT EXISTS(SELECT 1 FROM leads WHERE id=NEW.lead_id) BEGIN SELECT RAISE(ABORT,'Missing business'); END",
        "CREATE TRIGGER IF NOT EXISTS intelligence_result_owner BEFORE INSERT ON opportunity_intelligence_results "
        "WHEN NOT EXISTS(SELECT 1 FROM opportunity_intelligence_runs WHERE id=NEW.run_id) "
        "OR EXISTS(SELECT 1 FROM opportunity_intelligence_results WHERE run_id=NEW.run_id) "
        "BEGIN SELECT RAISE(ABORT,'Missing or finalized run'); END",
        "CREATE TRIGGER IF NOT EXISTS intelligence_review_owner BEFORE INSERT ON opportunity_intelligence_reviews "
        "WHEN NOT EXISTS(SELECT 1 FROM opportunity_intelligence_runs WHERE id=NEW.run_id AND lead_id=NEW.lead_id) "
        "OR (NEW.worksheet_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM activity_log WHERE id=NEW.worksheet_id AND lead_id=NEW.lead_id "
        "AND action='opportunity_worksheet_v1')) "
        "BEGIN SELECT RAISE(ABORT,'Review must retain its own worksheet/business'); END",
        "CREATE TRIGGER IF NOT EXISTS intelligence_preserve_lead BEFORE DELETE ON leads "
        "WHEN EXISTS(SELECT 1 FROM opportunity_intelligence_runs WHERE lead_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve intelligence business'); END",
        "CREATE TRIGGER IF NOT EXISTS intelligence_preserve_lead_id BEFORE UPDATE OF id ON leads "
        "WHEN NEW.id!=OLD.id AND EXISTS(SELECT 1 FROM opportunity_intelligence_runs WHERE lead_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve intelligence business'); END",
        "CREATE TRIGGER IF NOT EXISTS intelligence_preserve_worksheet BEFORE DELETE ON activity_log "
        "WHEN EXISTS(SELECT 1 FROM opportunity_intelligence_reviews WHERE worksheet_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve adopted worksheet'); END",
        "CREATE TRIGGER IF NOT EXISTS intelligence_preserve_worksheet_update BEFORE UPDATE ON activity_log "
        "WHEN EXISTS(SELECT 1 FROM opportunity_intelligence_reviews WHERE worksheet_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve adopted worksheet'); END",
    ])
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
