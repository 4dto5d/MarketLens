"""Additive ledger guards, including legacy SQLite connections with FK checks off."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from sqlalchemy import text


def backup_before_findings(engine, *, disclosure_upgrade: bool = False) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).exists():
        return None
    path = Path(database)
    with engine.connect() as connection:
        tables = set(connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'" )).scalars())
        columns = {row[1] for row in connection.execute(text('PRAGMA table_info(prospect_finding_revisions)'))}
    if "leads" not in tables:
        return None
    if disclosure_upgrade:
        if 'prospect_finding_revisions' not in tables or 'customer_copy_contract_version' in columns:
            return None
    elif 'prospect_finding_revisions' in tables:
        return None
    suffix = '.backup-before-finding-disclosure-v2' if disclosure_upgrade else '.backup-before-prospect-findings'
    backup = path.with_suffix(path.suffix + suffix)

    def validate(target: Path) -> None:
        with closing(sqlite3.connect(str(target))) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Finding migration backup failed integrity validation.")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns = {row[1] for row in connection.execute('PRAGMA table_info(prospect_finding_revisions)')}
            valid_ledger = ('prospect_finding_revisions' in tables and 'customer_copy_contract_version' not in columns
                            if disclosure_upgrade else 'prospect_finding_revisions' not in tables)
            if "leads" not in tables or not valid_ledger:
                raise RuntimeError("Finding backup is not a pre-migration source checkpoint.")

    if backup.exists():
        validate(backup)
        return backup
    with tempfile.NamedTemporaryFile(prefix="findings-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        validate(temporary)
        with backup.open("xb") as destination_stream, temporary.open("rb") as source_stream:
            shutil.copyfileobj(source_stream, destination_stream)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def install_finding_guards(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    statements = (
        "CREATE TRIGGER IF NOT EXISTS finding_lead_fk BEFORE INSERT ON prospect_finding_revisions "
        "WHEN NOT EXISTS(SELECT 1 FROM leads WHERE id=NEW.lead_id) "
        "BEGIN SELECT RAISE(ABORT,'Finding requires existing business'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_audit_owner BEFORE INSERT ON prospect_finding_revisions "
        "WHEN NEW.source_audit_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM website_audits "
        "WHERE id=NEW.source_audit_id AND lead_id=NEW.lead_id) "
        "BEGIN SELECT RAISE(ABORT,'Finding source belongs to another business or is missing'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_previous_owner BEFORE INSERT ON prospect_finding_revisions "
        "WHEN NEW.previous_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM prospect_finding_revisions "
        "WHERE id=NEW.previous_id AND lead_id=NEW.lead_id AND finding_key=NEW.finding_key "
        "AND finding_type=NEW.finding_type AND fact_id=NEW.fact_id AND revision=NEW.revision-1) "
        "BEGIN SELECT RAISE(ABORT,'Finding correction must extend its own history'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_no_replace BEFORE INSERT ON prospect_finding_revisions "
        "WHEN EXISTS(SELECT 1 FROM prospect_finding_revisions WHERE id=NEW.id "
        "OR (lead_id=NEW.lead_id AND finding_key=NEW.finding_key AND revision=NEW.revision)) "
        "BEGIN SELECT RAISE(ABORT,'Finding history cannot be replaced'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_no_update BEFORE UPDATE ON prospect_finding_revisions "
        "BEGIN SELECT RAISE(ABORT,'Finding history is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_no_delete BEFORE DELETE ON prospect_finding_revisions "
        "BEGIN SELECT RAISE(ABORT,'Finding history is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_restrict_lead_delete BEFORE DELETE ON leads "
        "WHEN EXISTS(SELECT 1 FROM prospect_finding_revisions WHERE lead_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve business referenced by finding history'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_restrict_lead_rekey BEFORE UPDATE OF id ON leads "
        "WHEN NEW.id!=OLD.id AND EXISTS(SELECT 1 FROM prospect_finding_revisions WHERE lead_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve finding business identity'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_restrict_audit_delete BEFORE DELETE ON website_audits "
        "WHEN EXISTS(SELECT 1 FROM prospect_finding_revisions WHERE source_audit_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve finding source identity'); END",
        "CREATE TRIGGER IF NOT EXISTS finding_restrict_audit_rekey BEFORE UPDATE OF id,lead_id ON website_audits "
        "WHEN (NEW.id!=OLD.id OR NEW.lead_id!=OLD.lead_id) "
        "AND EXISTS(SELECT 1 FROM prospect_finding_revisions WHERE source_audit_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT,'Preserve finding source ownership'); END",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
