from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections.abc import Iterable
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.schema import Base


def initialize_database(session_factory: sessionmaker[Session]) -> None:
    engine = session_factory.kw["bind"]
    backup_database_before_v0105(engine)
    backup_database_before_v0106(engine)
    backup_database_before_v0107(engine)
    backup_database_before_v0109(engine)
    backup_database_before_v0110(engine)
    backup_database_before_v0111(engine)
    backup_database_before_v0111_credibility(engine)
    backup_database_before_v0112(engine)
    backup_database_before_v0113(engine)
    backup_database_before_v0113a(engine)
    backup_database_before_v0114(engine)
    backup_database_before_v0114_a1(engine)
    backup_database_before_v0114_b03(engine)
    backup_database_before_v0114_b04(engine)
    backup_database_before_v0115_b1(engine)
    backup_database_before_v0115_b2(engine)
    backup_database_before_v0116(engine)
    backup_database_before_search_market(engine)
    backup_database_before_seo_research(engine)
    backup_database_before_center_provenance(engine)
    Base.metadata.create_all(engine)
    install_seo_ledger_guards(engine)
    with engine.begin() as connection:
        for table_name, columns in SQLITE_COLUMNS.items():
            existing = {
                row[1]
                for row in connection.execute(text(f"PRAGMA table_info({table_name})"))  # noqa: S608 - internal table names only
            }
            for column_name, ddl in columns:
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))  # noqa: S608
    migrate_v0114_semantics(session_factory)
    migrate_v0114_b03_project_proof(session_factory)
    migrate_v0114_b04_commercial_state(session_factory)
    migrate_v0115_b1_state(session_factory)
    migrate_v0115_b2_guided_call_identity(session_factory)
    migrate_v0116_search_visibility(session_factory)
    migrate_v0116_search_market(session_factory)
    normalize_contact_interaction_dates(engine)
    migrate_historical_outreach_approvals(session_factory)
    migrate_v0113_state(session_factory)
    from local_presence_miner.database.search_run_control import reconcile_interrupted_search_runs

    reconcile_interrupted_search_runs(session_factory)
    from local_presence_miner.services.search_market_service import reconcile_interrupted_search_market_runs

    reconcile_interrupted_search_market_runs(session_factory)


def migrate_historical_outreach_approvals(session_factory: sessionmaker[Session]) -> int:
    """Unknown historical dependencies are not evidence of no dependencies."""
    from sqlalchemy import select

    from local_presence_miner.database.repositories import revoke_outreach_approval
    from local_presence_miner.database.schema import OutreachDraft

    with session_factory() as session:
        drafts = list(session.scalars(select(OutreachDraft).where(OutreachDraft.approved.is_(True), OutreachDraft.dependency_state == "unknown")))
        for draft in drafts:
            revoke_outreach_approval(
                session,
                draft,
                "v0.1.12 migration: historical approval has no deterministically established proof dependencies; exact text retained for review",
            )
        session.commit()
        return len(drafts)


def backup_database_before_v0105(engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "leads" not in tables:
            return None
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(leads)"))}
    if "verification_json" in columns:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0105")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def backup_database_before_v0106(engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    if "contact_interactions" not in tables:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0106")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def backup_database_before_v0107(engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    if "contact_interactions" not in tables or "seller_profiles" in tables:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0107")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def backup_database_before_v0109(engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "leads" not in tables:
            return None
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(leads)"))}
    if "sales_priority_score" in columns:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0109")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def backup_database_before_v0110(engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "contact_interactions" not in tables:
            return None
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(contact_interactions)"))}
    if "branch_path_json" in columns:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0110")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def backup_database_before_v0111(engine) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "leads" not in tables:
            return None
        lead_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(leads)"))}
    google_ready = "google_presence_assessments" in tables
    rich_refresh_ready = {
        "last_rich_google_retrieved_at",
        "last_google_refresh_attempt_at",
        "last_google_refresh_error",
        "google_rich_data_stale",
    }.issubset(lead_columns)
    if google_ready and rich_refresh_ready:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0111")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def backup_database_before_v0111_credibility(engine) -> Path | None:
    """Preserve an integrity-hardened v0.1.11 DB before adding credibility fields."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if not {"seller_profiles", "seller_proof", "contact_interactions"}.issubset(tables):
            return None
        proof_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(seller_proof)"))}
        interaction_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(contact_interactions)"))}
    credibility_ready = {"status", "client_work", "provenance", "safe_claims_json", "prohibited_claims_json"}.issubset(proof_columns)
    memory_ready = {"credibility_concern", "concerned_about_ai", "wants_proof"}.issubset(interaction_columns)
    if credibility_ready and memory_ready:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0111-credibility")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def backup_database_before_v0112(engine) -> Path | None:
    """Preserve a v0.1.11 database before proof-permission and approval-history changes."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if not {"seller_proof", "outreach_drafts"}.issubset(tables):
            return None
        proof_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(seller_proof)"))}
        draft_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(outreach_drafts)"))}
    proof_ready = {
        "internal_only",
        "share_client_name",
        "share_public_url",
        "share_testimonial",
        "share_case_study",
        "share_reference",
    }.issubset(proof_columns)
    draft_ready = {
        "proof_dependencies_json",
        "proof_dependency_fingerprint",
        "approval_revoked_reason",
        "dependency_state",
        "dependency_body_fingerprint",
        "approval_snapshot_json",
    }.issubset(draft_columns)
    if proof_ready and draft_ready and "outreach_approval_history" in tables:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0112")
    if not backup.exists():
        # SQLite backup includes committed WAL data; a raw copy of just the DB does not.
        with tempfile.NamedTemporaryFile(prefix="v0112-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            temporary.rename(backup)  # Windows refuses to replace a prior backup.
        finally:
            temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0113(engine) -> Path | None:
    """Preserve the committed pre-v0.1.13 state before workflow migration.

    SQLite's backup API is required here so committed WAL content is included.
    A prior backup is never replaced.
    """
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if not {"lead_searches", "leads"}.issubset(tables):
            return None
        search_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(lead_searches)"))}
        lead_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(leads)"))}
    search_ready = {
        "lifecycle_state",
        "total_candidates",
        "processed_count",
        "succeeded_count",
        "failed_count",
        "skipped_count",
        "new_count",
        "rediscovered_count",
        "last_candidate",
        "error_summary",
        "started_at",
        "completed_at",
    }.issubset(search_columns)
    notes_ready = {"operator_notes", "system_notes", "notes_provenance"}.issubset(lead_columns)
    if search_ready and notes_ready and "search_run_leads" in tables:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0113")
    if not backup.exists():
        with tempfile.NamedTemporaryFile(prefix="v0113-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            temporary.rename(backup)
        finally:
            temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0113a(engine) -> Path | None:
    """Preserve an existing v0.1.13 database before adding the lease table."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if not {"lead_searches", "leads", "search_run_leads"}.issubset(tables) or "search_run_leases" in tables:
            return None
        search_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(lead_searches)"))}
        lead_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(leads)"))}
    if not {
        "lifecycle_state",
        "processed_count",
        "succeeded_count",
        "failed_count",
        "started_at",
        "completed_at",
    }.issubset(search_columns) or not {
        "operator_notes",
        "system_notes",
        "notes_provenance",
    }.issubset(lead_columns):
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0113a")
    if not backup.exists():
        with tempfile.NamedTemporaryFile(prefix="v0113a-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            temporary.rename(backup)
        finally:
            temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0114(engine) -> Path | None:
    """Preserve committed v0.1.13a data before canonical semantic columns are added."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if not {"leads", "seller_proof", "offer_history"}.issubset(tables):
            return None
        lead_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(leads)"))}
    if "recommended_offer_id" in lead_columns and "seller_projects" in tables:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0114")
    if not backup.exists():
        with tempfile.NamedTemporaryFile(prefix="v0114-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            temporary.rename(backup)
        finally:
            temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0114_a1(engine) -> Path | None:
    """Preserve v0.1.14 rows before removing the legacy research pseudo-offer ID."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if not {"app_settings", "leads", "offer_history"}.issubset(tables):
            return None
        migrated = connection.execute(text("SELECT value FROM app_settings WHERE key='v0114_a1_offer_taxonomy_delta_migrated'"))
        if migrated.scalar_one_or_none() == "1":
            return None
        has_legacy_research = connection.execute(
            text(
                "SELECT 1 FROM leads WHERE recommended_offer_id='research_first' OR starting_offer_json LIKE '%research_first%' "
                "UNION ALL SELECT 1 FROM offer_history WHERE canonical_offer_id='research_first' LIMIT 1"
            )
        ).scalar_one_or_none()
    if has_legacy_research is None:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0114-a1")
    if not backup.exists():
        with tempfile.NamedTemporaryFile(prefix="v0114-a1-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            temporary.rename(backup)
        finally:
            temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0114_b03(engine) -> Path | None:
    """Create one readable B03 recovery point before project/proof semantics change."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "seller_proof" not in tables:
            return None
        if "app_settings" in tables:
            marker = connection.execute(text("SELECT value FROM app_settings WHERE key='v0114_b03_project_proof_migrated'"))
            if marker.scalar_one_or_none() == "1":
                return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0114-b03")
    if backup.exists():
        with closing(sqlite3.connect(backup)) as existing:
            if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Existing v0.1.14 B03 backup is unreadable; migration requires review.")
        return backup
    with tempfile.NamedTemporaryFile(prefix="v0114-b03-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(temporary)) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(temporary)) as copied:
            if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("B03 backup integrity check failed.")
        temporary.rename(backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0114_b04(engine) -> Path | None:
    """Create one atomic B04 backup before adding freshness state."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "leads" not in tables:
            return None
        if "app_settings" in tables:
            marker = connection.execute(text("SELECT value FROM app_settings WHERE key='v0114_b04_commercial_state_migrated'"))
            if marker.scalar_one_or_none() is not None:
                return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0114-b04")
    if backup.exists():
        try:
            with closing(sqlite3.connect(str(backup))) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Existing v0.1.14 B04 backup is unreadable; migration requires review.")
                existing.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Existing v0.1.14 B04 backup is unreadable; migration requires review.") from exc
        return backup
    with tempfile.NamedTemporaryFile(prefix="v0114-b04-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(str(temporary))) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("B04 backup integrity check failed.")
            verification.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database_before_v0115_b1(engine) -> Path | None:
    """Create a readable, non-overwriting recovery point before B1 state storage."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "leads" not in tables:
            return None
        if "app_settings" in tables:
            marker = connection.execute(text("SELECT value FROM app_settings WHERE key='v0115_b1_state_migrated'")).scalar_one_or_none()
            if marker is not None:
                return None
    base = path.with_suffix(path.suffix + ".backup-before-v0115-b1")
    backup = base
    index = 1
    # Never overwrite a prior recovery point. If a previous attempted migration
    # left one behind without a marker, preserve it and create another copy.
    while backup.exists():
        try:
            with closing(sqlite3.connect(str(backup))) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Existing v0.1.15 B1 backup is unreadable; migration requires review.")
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Existing v0.1.15 B1 backup is unreadable; migration requires review.") from exc
        backup = Path(str(base) + f".{index}")
        index += 1
    with tempfile.NamedTemporaryFile(prefix="v0115-b1-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(str(temporary))) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("B1 backup integrity check failed.")
            verification.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0115_b2(engine) -> Path | None:
    """Preserve an already-B1 database before adding B2 Guided Call identity."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if not {"app_settings", "contact_interactions"}.issubset(tables):
            return None
        b1_marker = connection.execute(
            text("SELECT value FROM app_settings WHERE key='v0115_b1_state_migrated'")
        ).scalar_one_or_none()
        if b1_marker is None:
            return None
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(contact_interactions)"))}
        if {"guided_call_identity_json", "guided_call_sequence_json"}.issubset(columns):
            return None
    base = path.with_suffix(path.suffix + ".backup-before-v0115-b2")
    backup = base
    index = 1
    while backup.exists():
        try:
            with closing(sqlite3.connect(str(backup))) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Existing v0.1.15 B2 backup is unreadable; migration requires review.")
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Existing v0.1.15 B2 backup is unreadable; migration requires review.") from exc
        backup = Path(str(base) + f".{index}")
        index += 1
    with tempfile.NamedTemporaryFile(prefix="v0115-b2-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(str(temporary))) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("B2 backup integrity check failed.")
            verification.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_v0116(engine) -> Path | None:
    """Preserve the pre-v0.1.16 database before adding visibility evidence tables."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "lead_searches" not in tables:
            return None
        if {"search_visibility_probes", "search_visibility_observations"}.intersection(tables):
            return None
        if "app_settings" in tables:
            marker = connection.execute(
                text("SELECT value FROM app_settings WHERE key='v0116_search_visibility_migrated'")
            ).scalar_one_or_none()
            if marker is not None:
                return None
    base = path.with_suffix(path.suffix + ".backup-before-v0116")
    backup = base
    index = 1
    while backup.exists():
        try:
            with closing(sqlite3.connect(str(backup))) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Existing v0.1.16 backup is unreadable; migration requires review.")
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Existing v0.1.16 backup is unreadable; migration requires review.") from exc
        backup = Path(str(base) + f".{index}")
        index += 1
    with tempfile.NamedTemporaryFile(prefix="v0116-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(str(temporary))) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("v0.1.16 backup integrity check failed.")
            verification.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_search_market(engine) -> Path | None:
    """Take one checked snapshot before additive Search Market storage appears."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "lead_searches" not in tables or "search_market_runs" in tables:
            return None
    backup = path.with_suffix(path.suffix + ".backup-before-v0116-search-market")
    if backup.exists():
        try:
            with closing(sqlite3.connect(str(backup))) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Existing Search Market backup is unreadable; migration requires review.")
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("Existing Search Market backup is unreadable; migration requires review.") from exc
        return backup
    with tempfile.NamedTemporaryFile(prefix="search-market-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(str(temporary))) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Search Market backup integrity check failed.")
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_seo_research(engine) -> Path | None:
    """Checked, non-overwriting backup before additive SEO ledger creation."""
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.exists():
        return None
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "leads" not in tables or "seo_research_snapshots" in tables:
            return None
    backup = path.with_suffix(path.suffix + ".backup-before-seo-intelligence")
    if backup.exists():
        with closing(sqlite3.connect(str(backup))) as existing:
            if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Existing SEO backup integrity check failed; migration requires review.")
        return backup
    with tempfile.NamedTemporaryFile(prefix="seo-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(str(temporary))) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SEO backup integrity check failed.")
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def backup_database_before_center_provenance(engine) -> Path | None:
    """Checked, exclusively-created backup before the additive provenance column.

    No historical center is inferred as verified. An existing backup is checked,
    never overwritten; interrupted/invalid backups require explicit review.
    """
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).exists():
        return None
    path = Path(database)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(search_visibility_probes)"))}
    if not columns or "center_resolution_provenance_json" in columns:
        return None
    backup = path.with_suffix(path.suffix + ".backup-before-center-provenance")
    if backup.exists():
        try:
            with closing(sqlite3.connect(str(backup))) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Center provenance backup integrity failed")
                columns = {row[1] for row in existing.execute("PRAGMA table_info(search_visibility_probes)")}
                if not columns or "center_resolution_provenance_json" in columns:
                    raise RuntimeError("Existing center provenance backup is invalid or not a pre-migration checkpoint")
        except sqlite3.Error as exc:
            raise RuntimeError("Existing center provenance backup is invalid; review required") from exc
        return backup
    with tempfile.NamedTemporaryFile(prefix="center-backup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(temporary))) as destination:
            source.backup(destination)
        with closing(sqlite3.connect(str(temporary))) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Center provenance backup integrity failed")
        # Exclusive creation prevents a concurrent initialization overwriting a
        # previously checked backup. Failed copies remain visible for review.
        with backup.open("xb") as destination, temporary.open("rb") as source:
            shutil.copyfileobj(source, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def install_seo_ledger_guards(engine) -> None:
    """Enforce this ledger's FK/immutability even in legacy FK-off SQLite.

    Do not enable global foreign keys retroactively on unrelated legacy tables.
    No updates/deletes/backfill are required by this additive migration.
    """
    if engine.dialect.name != "sqlite":
        return
    statements = (
        "CREATE TRIGGER IF NOT EXISTS seo_snapshot_lead_fk BEFORE INSERT ON seo_research_snapshots "
        "WHEN NOT EXISTS(SELECT 1 FROM leads WHERE id=NEW.lead_id) "
        "BEGIN SELECT RAISE(ABORT, 'SEO snapshot requires an existing lead'); END",
        "CREATE TRIGGER IF NOT EXISTS seo_snapshot_no_replace BEFORE INSERT ON seo_research_snapshots "
        "WHEN EXISTS(SELECT 1 FROM seo_research_snapshots WHERE id=NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'SEO evidence cannot be replaced'); END",
        "CREATE TRIGGER IF NOT EXISTS seo_snapshot_no_update BEFORE UPDATE ON seo_research_snapshots "
        "BEGIN SELECT RAISE(ABORT, 'SEO evidence is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS seo_snapshot_no_delete BEFORE DELETE ON seo_research_snapshots "
        "BEGIN SELECT RAISE(ABORT, 'SEO evidence is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS seo_snapshot_restrict_lead_delete BEFORE DELETE ON leads "
        "WHEN EXISTS(SELECT 1 FROM seo_research_snapshots WHERE lead_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT, 'Preserve the lead referenced by historical SEO evidence'); END",
        "CREATE TRIGGER IF NOT EXISTS seo_snapshot_restrict_lead_rekey BEFORE UPDATE OF id ON leads "
        "WHEN NEW.id != OLD.id AND EXISTS(SELECT 1 FROM seo_research_snapshots WHERE lead_id=OLD.id) "
        "BEGIN SELECT RAISE(ABORT, 'Preserve the lead identity referenced by historical SEO evidence'); END",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def migrate_v0115_b1_state(session_factory: sessionmaker[Session]) -> None:
    """Install B1 canonical state without inventing semantics from legacy rows."""
    engine = session_factory.kw["bind"]
    with engine.begin() as connection:
        marker = connection.execute(
            text("SELECT value FROM app_settings WHERE key='v0115_b1_state_migrated'")
        ).scalar_one_or_none()
        if marker is not None:
            return

        # Base.metadata/create_all and SQLITE_COLUMNS have already added storage.
        # Existing CRM/outcome/free-text values are intentionally NOT converted
        # into current disposition, consent, concern, or assertion truth.
        lead_count = connection.execute(text("SELECT COUNT(*) FROM leads")).scalar_one()
        interaction_count = connection.execute(text("SELECT COUNT(*) FROM contact_interactions")).scalar_one()
        assertion_count = connection.execute(text("SELECT COUNT(*) FROM conversation_assertions")).scalar_one()
        disposition_count = connection.execute(text("SELECT COUNT(*) FROM commercial_disposition_records")).scalar_one()
        if assertion_count != 0 or disposition_count != 0:
            raise RuntimeError("B1 migration found unexpected pre-marker canonical state; manual reconciliation is required.")

        integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError("B1 migration integrity validation failed.")

        database = engine.url.database
        backup_meta: dict[str, object] = {}
        if database and database != ":memory:":
            path = Path(database)
            base = path.with_suffix(path.suffix + ".backup-before-v0115-b1")
            candidates = [base, *sorted(path.parent.glob(base.name + ".*"))]
            existing = [candidate for candidate in candidates if candidate.exists()]
            if existing:
                chosen = max(existing, key=lambda item: item.stat().st_mtime_ns)
                backup_meta = {
                    "backup": chosen.name,
                    "backup_sha256": _sha256_file(chosen),
                    "backup_size": chosen.stat().st_size,
                }

        marker_value = json.dumps(
            {
                "version": "v0.1.15-b1",
                "lead_rows_preserved": lead_count,
                "interaction_rows_preserved": interaction_count,
                "legacy_assertions_activated": 0,
                "legacy_dispositions_inferred": 0,
                **backup_meta,
            },
            sort_keys=True,
        )
        connection.execute(
            text("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('v0115_b1_state_migrated', :value)"),
            {"value": marker_value},
        )


def migrate_v0115_b2_guided_call_identity(session_factory: sessionmaker[Session]) -> None:
    """Mark additive B2 storage without inventing identity for old interactions."""
    engine = session_factory.kw["bind"]
    with engine.begin() as connection:
        marker = connection.execute(
            text("SELECT value FROM app_settings WHERE key='v0115_b2_guided_call_identity_migrated'")
        ).scalar_one_or_none()
        if marker is not None:
            return
        rows = connection.execute(
            text(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN guided_call_identity_json != '{}' OR guided_call_sequence_json != '[]' THEN 1 ELSE 0 END) "
                "FROM contact_interactions"
            )
        ).one()
        interaction_count = int(rows[0] or 0)
        activated_count = int(rows[1] or 0)
        if activated_count:
            raise RuntimeError("B2 migration found unmarked Guided Call identity; manual reconciliation is required.")
        if connection.execute(text("PRAGMA integrity_check")).scalar_one() != "ok":
            raise RuntimeError("B2 migration integrity validation failed.")
        connection.execute(
            text(
                "INSERT OR REPLACE INTO app_settings (key, value) "
                "VALUES ('v0115_b2_guided_call_identity_migrated', :value)"
            ),
            {
                "value": json.dumps(
                    {
                        "version": "v0.1.15-b2",
                        "interaction_rows_preserved": interaction_count,
                        "historical_guided_call_identities_inferred": 0,
                    },
                    sort_keys=True,
                )
            },
        )


def migrate_v0116_search_visibility(session_factory: sessionmaker[Session]) -> None:
    """Mark additive visibility storage without inventing history from legacy positions."""
    engine = session_factory.kw["bind"]
    with engine.begin() as connection:
        marker = connection.execute(
            text("SELECT value FROM app_settings WHERE key='v0116_search_visibility_migrated'")
        ).scalar_one_or_none()
        if marker is not None:
            return
        probe_count = connection.execute(text("SELECT COUNT(*) FROM search_visibility_probes")).scalar_one()
        observation_count = connection.execute(text("SELECT COUNT(*) FROM search_visibility_observations")).scalar_one()
        if probe_count or observation_count:
            raise RuntimeError("v0.1.16 migration found unmarked visibility evidence; manual reconciliation is required.")
        membership_count = connection.execute(text("SELECT COUNT(*) FROM search_run_leads")).scalar_one()
        integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError("v0.1.16 visibility migration integrity validation failed.")

        database = engine.url.database
        backup_meta: dict[str, object] = {}
        if database and database != ":memory:":
            path = Path(database)
            base = path.with_suffix(path.suffix + ".backup-before-v0116")
            candidates = [base, *sorted(path.parent.glob(base.name + ".*"))]
            existing = [candidate for candidate in candidates if candidate.exists()]
            if existing:
                chosen = max(existing, key=lambda item: item.stat().st_mtime_ns)
                backup_meta = {
                    "backup": chosen.name,
                    "backup_sha256": _sha256_file(chosen),
                    "backup_size": chosen.stat().st_size,
                }
        value = json.dumps(
            {
                "version": "v0.1.16",
                "search_run_memberships_preserved": membership_count,
                "legacy_visibility_observations_inferred": 0,
                **backup_meta,
            },
            sort_keys=True,
        )
        connection.execute(
            text(
                "INSERT OR REPLACE INTO app_settings (key, value) "
                "VALUES ('v0116_search_visibility_migrated', :value)"
            ),
            {"value": value},
        )


def migrate_v0116_search_market(session_factory: sessionmaker[Session]) -> None:
    """Mark new storage without converting legacy visibility into multi-query claims."""
    engine = session_factory.kw["bind"]
    with engine.begin() as connection:
        marker = connection.execute(
            text("SELECT value FROM app_settings WHERE key='v0116_search_market_migrated'")
        ).scalar_one_or_none()
        if marker is not None:
            return
        run_count = connection.execute(text("SELECT COUNT(*) FROM search_market_runs")).scalar_one()
        query_count = connection.execute(text("SELECT COUNT(*) FROM search_market_queries")).scalar_one()
        if run_count or query_count:
            raise RuntimeError("Unmarked Search Market evidence requires manual reconciliation.")
        if connection.execute(text("PRAGMA integrity_check")).scalar_one() != "ok" or connection.execute(
            text("PRAGMA foreign_key_check")
        ).fetchall():
            raise RuntimeError("Search Market migration integrity validation failed.")
        probe_count = connection.execute(text("SELECT COUNT(*) FROM search_visibility_probes")).scalar_one()
        backup = None
        if engine.url.database and engine.url.database != ":memory:":
            path = Path(engine.url.database)
            candidate = path.with_suffix(path.suffix + ".backup-before-v0116-search-market")
            if candidate.exists():
                backup = {"name": candidate.name, "sha256": _sha256_file(candidate)}
        value = json.dumps({
            "version": "v0.1.16-search-market-1",
            "existing_visibility_probes_preserved": probe_count,
            "legacy_market_queries_inferred": 0,
            "backup": backup,
        }, sort_keys=True)
        connection.execute(
            text("INSERT INTO app_settings (key, value) VALUES ('v0116_search_market_migrated', :value)"),
            {"value": value},
        )


def migrate_v0114_b03_project_proof(session_factory: sessionmaker[Session]) -> None:
    """Backfill explicit project containers without merging ambiguous legacy evidence."""
    engine = session_factory.kw["bind"]
    completed = {"Completed", "Completed + Verified", "Completed + Testimonial", "Completed + Measurable Result"}
    project_types = {
        "Paid Project",
        "Unpaid Project",
        "Local-Business Website Project",
        "Audit Project",
        "Google Presence Project",
        "Niche-Specific Project",
        "AI / Software System",
        "Automation Workflow",
        "Data-Processing Pipeline",
    }
    unresolved_types = {"Testimonial", "Case Study", "Before / After"}
    with engine.begin() as connection:
        marker = connection.execute(text("SELECT value FROM app_settings WHERE key='v0114_b03_project_proof_migrated'"))
        if marker.scalar_one_or_none() == "1":
            return
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_seller_projects_legacy_source_proof_id ON seller_projects(legacy_source_proof_id)"))
        proof_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(seller_proof)"))}
        def column(name: str, default_sql: str) -> str:
            return name if name in proof_columns else f"{default_sql} AS {name}"

        select_fields = ", ".join(
            [
                "id",
                "seller_profile_id",
                column("project_id", "NULL"),
                column("grouping_state", "'unresolved'"),
                "proof_type",
                "title",
                column("status", "'Unclassified'"),
                column("niche", "''"),
                column("canonical_niche_id", "''"),
                column("niche_match_rule", "''"),
                column("client_name", "NULL"),
                column("project_value", "NULL"),
                column("completion_date", "NULL"),
                column("client_work", "0"),
                column("software_ai_project", "0"),
                column("provenance", "''"),
            ]
        )
        rows = list(connection.execute(text(f"SELECT {select_fields} FROM seller_proof ORDER BY id")).mappings())  # noqa: S608 - fixed column names
        before_count = len(rows)
        for row in rows:
            existing_project_id = row["project_id"]
            if existing_project_id is not None:
                connection.execute(
                    text(
                        "UPDATE seller_projects SET counting_state='legacy_unresolved', grouping_state=CASE "
                        "WHEN grouping_state='' THEN 'explicit' ELSE grouping_state END "
                        "WHERE id=:id AND COALESCE(counting_state, '')=''"
                    ),
                    {"id": existing_project_id},
                )
                continue
            proof_type = str(row["proof_type"] or "")
            completed_client_project = (
                proof_type in project_types
                and str(row["status"] or "") in completed
                and bool(row["client_work"])
            )
            unresolved_client_artifact = proof_type in unresolved_types
            if not completed_client_project and not unresolved_client_artifact:
                connection.execute(
                    text("UPDATE seller_proof SET grouping_state='non_project' WHERE id=:id"), {"id": row["id"]}
                )
                continue
            counting_state = "confirmed" if completed_client_project else "legacy_unresolved"
            grouping_state = "legacy_confirmed_singleton" if completed_client_project else "legacy_unresolved_singleton"
            connection.execute(
                text(
                    "INSERT OR IGNORE INTO seller_projects "
                    "(seller_profile_id, project_type, title, status, niche, canonical_niche_id, niche_match_rule, client_name, "
                    "project_value, completion_date, client_work, software_ai_project, provenance, grouping_state, counting_state, "
                    "verified, legacy_source_proof_id, active, notes, project_revision, created_at, updated_at) "
                    "VALUES (:seller_profile_id, :project_type, :title, :status, :niche, :canonical_niche_id, :niche_match_rule, "
                    ":client_name, :project_value, :completion_date, :client_work, :software_ai_project, :provenance, :grouping_state, "
                    ":counting_state, 0, :legacy_source_proof_id, 1, '', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "seller_profile_id": row["seller_profile_id"],
                    "project_type": proof_type,
                    "title": row["title"],
                    "status": row["status"],
                    "niche": row["niche"],
                    "canonical_niche_id": row["canonical_niche_id"],
                    "niche_match_rule": row["niche_match_rule"],
                    "client_name": row["client_name"],
                    "project_value": row["project_value"],
                    "completion_date": row["completion_date"],
                    "client_work": row["client_work"],
                    "software_ai_project": row["software_ai_project"],
                    "provenance": row["provenance"],
                    "grouping_state": grouping_state,
                    "counting_state": counting_state,
                    "legacy_source_proof_id": row["id"],
                },
            )
            project_id = connection.execute(
                text("SELECT id FROM seller_projects WHERE legacy_source_proof_id=:proof_id"), {"proof_id": row["id"]}
            ).scalar_one()
            connection.execute(
                text("UPDATE seller_proof SET project_id=:project_id, grouping_state=:grouping_state WHERE id=:id"),
                {"project_id": project_id, "grouping_state": grouping_state, "id": row["id"]},
            )
        after_count = connection.execute(text("SELECT COUNT(*) FROM seller_proof")).scalar_one()
        if after_count != before_count:
            raise RuntimeError("B03 migration changed Seller Proof row count.")
        integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError("B03 migration integrity validation failed.")
        connection.execute(text("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('v0114_b03_project_proof_migrated', '1')"))


def migrate_v0114_b04_commercial_state(session_factory: sessionmaker[Session]) -> None:
    """Preserve legacy cached offers, but require review before treating them as current."""
    with session_factory.begin() as session:
        connection = session.connection()
        marker = connection.execute(
            text("SELECT value FROM app_settings WHERE key='v0114_b04_commercial_state_migrated'")
        ).scalar_one_or_none()
        if marker is not None:
            return
        # Copy byte-for-byte once.  B04 never reads this column as current plan truth.
        connection.execute(
            text(
                "UPDATE leads SET legacy_starting_offer_json=starting_offer_json "
                "WHERE legacy_starting_offer_json='{}' AND starting_offer_json<>'{}'"
            )
        )
        connection.execute(
            text(
                "UPDATE leads SET commercial_plan_state='legacy_unknown_review_required', "
                "commercial_plan_snapshot_json='{}', commercial_dependency_fingerprint='', "
                "commercial_output_fingerprint='', commercial_plan_revision=0"
            )
        )
        # Preserve every previously approved body exactly once before revoking
        # it. Unknown legacy dependencies are never treated as current.
        connection.execute(
            text(
                "INSERT INTO outreach_approval_history "
                "(outreach_draft_id, lead_id, kind, subject, body, proof_dependencies_json, proof_dependency_fingerprint, approval_snapshot_json, "
                "commercial_snapshot_json, commercial_dependency_fingerprint, commercial_output_fingerprint, revocation_reason, revoked_at) "
                "SELECT d.id, d.lead_id, d.kind, d.subject, d.body, d.proof_dependencies_json, d.proof_dependency_fingerprint, d.approval_snapshot_json, "
                "d.commercial_snapshot_json, d.commercial_dependency_fingerprint, d.commercial_output_fingerprint, "
                "'migration: legacy B04 commercial dependencies require review', CURRENT_TIMESTAMP "
                "FROM outreach_drafts d WHERE d.approved=1 AND NOT EXISTS ("
                "SELECT 1 FROM outreach_approval_history h WHERE h.outreach_draft_id=d.id "
                "AND h.revocation_reason='migration: legacy B04 commercial dependencies require review')"
            )
        )
        connection.execute(
            text(
                "UPDATE outreach_drafts SET commercial_dependency_state="
                "CASE WHEN approved=1 THEN 'legacy_unknown_review_required' ELSE 'stale' END, "
                "commercial_snapshot_json='{}', commercial_dependency_fingerprint='', "
                "commercial_output_fingerprint='', commercial_plan_revision=0, "
                "approved=0, approval_revoked_reason=CASE WHEN approved=1 THEN "
                "'migration: legacy B04 commercial dependencies require review' ELSE approval_revoked_reason END, "
                "approval_revoked_at=CASE WHEN approved=1 THEN CURRENT_TIMESTAMP ELSE approval_revoked_at END"
            )
        )
        connection.execute(
            text("UPDATE leads SET status='Needs Review' WHERE status='Approved to Contact'")
        )
        integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError("B04 migration integrity validation failed.")
        connection.execute(
            text("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('v0114_b04_commercial_state_migrated', '1')")
        )


def migrate_v0114_semantics(session_factory: sessionmaker[Session]) -> None:
    """Attach canonical identities without rewriting raw historical labels or guessing project grouping."""
    from local_presence_miner.domain.niche_taxonomy import resolve_niche
    from local_presence_miner.domain.offer_registry import resolve_offer

    engine = session_factory.kw["bind"]
    with engine.begin() as connection:
        migrated = connection.execute(text("SELECT value FROM app_settings WHERE key='v0114_semantics_migrated'")).scalar_one_or_none()
        if migrated != "1":
            for row in connection.execute(text("SELECT id, category, recommended_offer, recommended_offer_id, starting_offer_json FROM leads")).mappings():
                offer = resolve_offer(str(row["recommended_offer"] or ""), str(row["recommended_offer_id"] or "") or None)
                niche = resolve_niche(str(row["category"] or ""))
                raw_json = str(row["starting_offer_json"] or "{}")
                try:
                    plan = json.loads(raw_json)
                except (TypeError, json.JSONDecodeError):
                    plan = None
                migrated_json = raw_json
                if isinstance(plan, dict):
                    plan_label = str(plan.get("offer_name", row["recommended_offer"] or ""))
                    plan_offer = resolve_offer(plan_label, str(plan.get("offer_id", "")) or None)
                    plan.setdefault("legacy_offer_label", plan_label)
                    plan["offer_id"] = plan_offer.offer_id.value if plan_offer.offer_id else ""
                    plan["resolution_status"] = plan_offer.status
                    migrated_json = json.dumps(plan, ensure_ascii=False, sort_keys=True)
                connection.execute(
                    text(
                        "UPDATE leads SET recommended_offer_id=:offer_id, offer_resolution_state=:offer_state, "
                        "canonical_niche_id=:niche_id, niche_match_rule=:niche_rule, starting_offer_json=:plan WHERE id=:id"
                    ),
                    {
                        "offer_id": offer.offer_id.value if offer.offer_id else "",
                        "offer_state": offer.status,
                        "niche_id": niche.canonical_id if niche.resolved else "",
                        "niche_rule": niche.match_rule,
                        "plan": migrated_json,
                        "id": row["id"],
                    },
                )
            for row in connection.execute(text("SELECT id, niche, package_name, canonical_offer_id FROM offer_history")).mappings():
                offer = resolve_offer(str(row["package_name"] or ""), str(row["canonical_offer_id"] or "") or None)
                niche = resolve_niche(str(row["niche"] or ""))
                connection.execute(
                    text(
                        "UPDATE offer_history SET canonical_offer_id=:offer_id, offer_resolution_state=:offer_state, "
                        "canonical_niche_id=:niche_id, niche_match_rule=:niche_rule WHERE id=:id"
                    ),
                    {
                        "offer_id": offer.offer_id.value if offer.offer_id else "",
                        "offer_state": offer.status,
                        "niche_id": niche.canonical_id if niche.resolved else "",
                        "niche_rule": niche.match_rule,
                        "id": row["id"],
                    },
                )
            proof_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(seller_proof)"))}
            # v0.1.11-era databases may have a minimally shaped seller_proof
            # table.  Those rows have no raw niche to canonicalize, but must still
            # receive safe v0.1.14 grouping/provenance defaults instead of aborting
            # initialization.
            proof_query = "SELECT id, niche FROM seller_proof" if "niche" in proof_columns else "SELECT id, '' AS niche FROM seller_proof"
            for row in connection.execute(text(proof_query)).mappings():
                niche = resolve_niche(str(row["niche"] or ""))
                connection.execute(
                    text(
                        "UPDATE seller_proof SET grouping_state=CASE WHEN project_id IS NULL THEN 'legacy_unresolved' ELSE grouping_state END, "
                        "canonical_niche_id=:niche_id, niche_match_rule=:niche_rule WHERE id=:id"
                    ),
                    {
                        "niche_id": niche.canonical_id if niche.resolved else "",
                        "niche_rule": niche.match_rule,
                        "id": row["id"],
                    },
                )
            connection.execute(text("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('v0114_semantics_migrated', '1')"))

        delta_migrated = connection.execute(
            text("SELECT value FROM app_settings WHERE key='v0114_a1_offer_taxonomy_delta_migrated'")
        ).scalar_one_or_none()
        if delta_migrated != "1":
            for row in connection.execute(text("SELECT id, recommended_offer, recommended_offer_id, starting_offer_json FROM leads")).mappings():
                offer = resolve_offer(str(row["recommended_offer"] or ""), str(row["recommended_offer_id"] or "") or None)
                raw_json = str(row["starting_offer_json"] or "{}")
                try:
                    plan = json.loads(raw_json)
                except (TypeError, json.JSONDecodeError):
                    plan = None
                migrated_json = raw_json
                if isinstance(plan, dict):
                    plan_label = str(plan.get("legacy_offer_label") or plan.get("offer_name") or row["recommended_offer"] or "")
                    plan_offer = resolve_offer(plan_label, str(plan.get("offer_id", "")) or None)
                    plan.setdefault("legacy_offer_label", plan_label)
                    plan["offer_id"] = plan_offer.offer_id.value if plan_offer.offer_id else ""
                    plan["resolution_status"] = plan_offer.status
                    migrated_json = json.dumps(plan, ensure_ascii=False, sort_keys=True)
                connection.execute(
                    text(
                        "UPDATE leads SET recommended_offer_id=:offer_id, offer_resolution_state=:offer_state, "
                        "starting_offer_json=:plan WHERE id=:id"
                    ),
                    {
                        "offer_id": offer.offer_id.value if offer.offer_id else "",
                        "offer_state": offer.status,
                        "plan": migrated_json,
                        "id": row["id"],
                    },
                )
            for row in connection.execute(text("SELECT id, package_name, canonical_offer_id FROM offer_history")).mappings():
                offer = resolve_offer(str(row["package_name"] or ""), str(row["canonical_offer_id"] or "") or None)
                connection.execute(
                    text(
                        "UPDATE offer_history SET canonical_offer_id=:offer_id, offer_resolution_state=:offer_state WHERE id=:id"
                    ),
                    {
                        "offer_id": offer.offer_id.value if offer.offer_id else "",
                        "offer_state": offer.status,
                        "id": row["id"],
                    },
                )
            connection.execute(
                text("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('v0114_a1_offer_taxonomy_delta_migrated', '1')")
            )


def migrate_v0113_state(session_factory: sessionmaker[Session]) -> None:
    """Conservatively separate notes and reconstruct legacy search membership.

    Legacy ``notes`` has unknown provenance, so it is copied only into an empty
    operator field and explicitly labelled ``legacy_unknown``.  The source
    column is retained.  Legacy ``Lead.search_id`` values become membership
    records without guessing whether the lead was new or rediscovered.
    """
    engine = session_factory.kw["bind"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE leads SET operator_notes = notes, notes_provenance = 'legacy_unknown' "
                "WHERE COALESCE(operator_notes, '') = '' AND COALESCE(notes, '') != ''"
            )
        )
        connection.execute(
            text(
                "INSERT OR IGNORE INTO search_run_leads "
                "(search_id, lead_id, candidate_place_id, candidate_name, discovery_order, search_position, "
                "score_context_json, discovery_kind, processing_status, error_summary, discovered_at, processed_at) "
                "SELECT l.search_id, l.id, l.place_id, l.name, COALESCE(l.search_position, 0), l.search_position, "
                "COALESCE(l.score_breakdown_json, '{}'), 'legacy_unknown', 'Succeeded', '', "
                "COALESCE(l.created_at, CURRENT_TIMESTAMP), COALESCE(l.updated_at, CURRENT_TIMESTAMP) "
                "FROM leads l JOIN lead_searches s ON s.id = l.search_id "
                "WHERE l.search_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE lead_searches SET "
                "lifecycle_state = CASE WHEN completed = 1 THEN 'Completed' ELSE 'Legacy / Unknown' END, "
                "total_candidates = (SELECT COUNT(*) FROM search_run_leads m WHERE m.search_id = lead_searches.id), "
                "processed_count = (SELECT COUNT(*) FROM search_run_leads m WHERE m.search_id = lead_searches.id "
                "AND m.processing_status IN ('Succeeded', 'Failed', 'Skipped')), "
                "succeeded_count = (SELECT COUNT(*) FROM search_run_leads m WHERE m.search_id = lead_searches.id "
                "AND m.processing_status = 'Succeeded'), "
                "failed_count = (SELECT COUNT(*) FROM search_run_leads m WHERE m.search_id = lead_searches.id "
                "AND m.processing_status = 'Failed'), "
                "skipped_count = (SELECT COUNT(*) FROM search_run_leads m WHERE m.search_id = lead_searches.id "
                "AND m.processing_status = 'Skipped') "
                "WHERE lifecycle_state IN ('Pending', 'Legacy / Unknown')"
            )
        )


def normalize_contact_interaction_dates(engine) -> None:
    with engine.begin() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "contact_interactions" not in tables:
            return
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(contact_interactions)"))}
        if not {"id", "interaction_datetime", "follow_up_date"}.issubset(columns):
            return
        rows = connection.execute(text("SELECT id, interaction_datetime, follow_up_date FROM contact_interactions")).fetchall()
        for interaction_id, interaction_datetime, follow_up_date in rows:
            try:
                canonical_datetime = datetime.fromisoformat(interaction_datetime).isoformat(timespec="minutes")
                canonical_follow_up = date.fromisoformat(follow_up_date).isoformat() if follow_up_date else ""
            except (TypeError, ValueError):
                continue
            connection.execute(
                text("UPDATE contact_interactions SET interaction_datetime = :interaction_datetime, follow_up_date = :follow_up_date WHERE id = :id"),
                {
                    "id": interaction_id,
                    "interaction_datetime": canonical_datetime,
                    "follow_up_date": canonical_follow_up,
                },
            )


ColumnSpec = tuple[str, str]


SQLITE_COLUMNS: dict[str, Iterable[ColumnSpec]] = {
    "search_visibility_probes": [
        ("center_resolution_provenance_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("market_query_id", "INTEGER REFERENCES search_market_queries(id)"),
        ("comparability_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("attempt_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("acquisition_strategy_version", "VARCHAR(40) NOT NULL DEFAULT 'legacy-v1'"),
    ],
    "lead_searches": [
        ("state_region", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("criteria_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("completed", "BOOLEAN NOT NULL DEFAULT 0"),
        ("lifecycle_state", "VARCHAR(40) NOT NULL DEFAULT 'Pending'"),
        ("total_candidates", "INTEGER NOT NULL DEFAULT 0"),
        ("processed_count", "INTEGER NOT NULL DEFAULT 0"),
        ("succeeded_count", "INTEGER NOT NULL DEFAULT 0"),
        ("failed_count", "INTEGER NOT NULL DEFAULT 0"),
        ("skipped_count", "INTEGER NOT NULL DEFAULT 0"),
        ("new_count", "INTEGER NOT NULL DEFAULT 0"),
        ("rediscovered_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_candidate", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("error_summary", "TEXT NOT NULL DEFAULT ''"),
        ("started_at", "DATETIME"),
        ("completed_at", "DATETIME"),
        ("created_at", "DATETIME"),
    ],
    "leads": [
        ("search_id", "INTEGER"),
        ("category", "VARCHAR(160) NOT NULL DEFAULT ''"),
        ("address", "VARCHAR(300) NOT NULL DEFAULT ''"),
        ("phone", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("website", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("google_maps_url", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("yelp_url", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("rating", "FLOAT"),
        ("review_count", "INTEGER NOT NULL DEFAULT 0"),
        ("business_types_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("has_hours", "BOOLEAN NOT NULL DEFAULT 0"),
        ("photo_count", "INTEGER NOT NULL DEFAULT 0"),
        ("latitude", "FLOAT"),
        ("longitude", "FLOAT"),
        ("search_position", "INTEGER"),
        ("profile_verification_required", "BOOLEAN NOT NULL DEFAULT 1"),
        ("status", "VARCHAR(80) NOT NULL DEFAULT 'New'"),
        ("priority", "VARCHAR(4) NOT NULL DEFAULT 'C'"),
        ("lead_score", "INTEGER NOT NULL DEFAULT 0"),
        ("sales_priority_score", "INTEGER NOT NULL DEFAULT 0"),
        ("qualification_class", "VARCHAR(40) NOT NULL DEFAULT 'Hold'"),
        ("qualification_confidence", "VARCHAR(20) NOT NULL DEFAULT 'Low'"),
        ("qualification_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("recommended_offer", "VARCHAR(160) NOT NULL DEFAULT ''"),
        ("recommended_offer_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("offer_resolution_state", "VARCHAR(40) NOT NULL DEFAULT 'unmapped'"),
        ("canonical_niche_id", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("niche_match_rule", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("approach_angle", "TEXT NOT NULL DEFAULT ''"),
        ("target_signals_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("score_breakdown_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("operator_notes", "TEXT NOT NULL DEFAULT ''"),
        ("system_notes", "TEXT NOT NULL DEFAULT ''"),
        ("notes_provenance", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("notes", "TEXT NOT NULL DEFAULT ''"),
        ("tags", "VARCHAR(300) NOT NULL DEFAULT ''"),
        ("owner", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("next_follow_up_date", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("last_contacted_date", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("contact_method", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("contact_outcome", "VARCHAR(160) NOT NULL DEFAULT ''"),
        ("target_zip_code", "VARCHAR(20) NOT NULL DEFAULT ''"),
        ("target_radius_miles", "INTEGER NOT NULL DEFAULT 10"),
        ("past_sales_notes", "TEXT NOT NULL DEFAULT ''"),
        ("starting_offer_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("legacy_starting_offer_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("commercial_plan_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("commercial_dependency_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("commercial_output_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("commercial_plan_state", "VARCHAR(48) NOT NULL DEFAULT 'legacy_unknown_review_required'"),
        ("commercial_plan_revision", "INTEGER NOT NULL DEFAULT 0"),
        ("commercial_plan_generated_at", "DATETIME"),
        ("commercial_disposition", "VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN'"),
        ("commercial_disposition_revision", "INTEGER NOT NULL DEFAULT 0"),
        ("disposition_not_before", "VARCHAR(10) NOT NULL DEFAULT ''"),
        ("follow_up_permission", "VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'"),
        ("adaptive_assets_revision", "INTEGER NOT NULL DEFAULT 0"),
        ("suppressed", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("contact_discovery_status", "VARCHAR(40) NOT NULL DEFAULT 'not_started'"),
        ("contact_discovery_error", "TEXT NOT NULL DEFAULT ''"),
        ("contact_discovery_updated_at", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("business_status", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("primary_type", "VARCHAR(160) NOT NULL DEFAULT ''"),
        ("pure_service_area_business", "BOOLEAN NOT NULL DEFAULT 0"),
        ("google_public_data_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("google_retrieved_at", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("last_rich_google_retrieved_at", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("last_google_refresh_attempt_at", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("last_google_refresh_error", "TEXT NOT NULL DEFAULT ''"),
        ("google_rich_data_stale", "BOOLEAN NOT NULL DEFAULT 0"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
    "website_audits": [
        ("url", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("reachable", "BOOLEAN NOT NULL DEFAULT 0"),
        ("status_code", "INTEGER"),
        ("final_url", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("response_time_ms", "INTEGER"),
        ("title", "VARCHAR(300) NOT NULL DEFAULT ''"),
        ("meta_description", "TEXT NOT NULL DEFAULT ''"),
        ("checks_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("metrics_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("strengths_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("weaknesses_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("rendered_checks_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("pagespeed_status", "VARCHAR(40) NOT NULL DEFAULT 'not_run'"),
        ("rendered_status", "VARCHAR(40) NOT NULL DEFAULT 'not_run'"),
        ("desktop_screenshot", "VARCHAR(600) NOT NULL DEFAULT ''"),
        ("mobile_screenshot", "VARCHAR(600) NOT NULL DEFAULT ''"),
        ("created_at", "DATETIME"),
    ],
    "competitors": [
        ("competitor_place_id", "VARCHAR(180) NOT NULL DEFAULT ''"),
        ("competitor_name", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("website_url", "VARCHAR(500) NOT NULL DEFAULT ''"),
        ("evidence_notes", "TEXT NOT NULL DEFAULT ''"),
        ("checklist_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("match_score", "INTEGER NOT NULL DEFAULT 0"),
        ("reason", "TEXT NOT NULL DEFAULT ''"),
        ("google_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
    ],
    "outreach_drafts": [
        ("kind", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("subject", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("body", "TEXT NOT NULL DEFAULT ''"),
        ("approved", "BOOLEAN NOT NULL DEFAULT 0"),
        ("proof_dependencies_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("proof_dependency_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("dependency_state", "VARCHAR(40) NOT NULL DEFAULT 'unknown'"),
        ("dependency_body_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("approval_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("commercial_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("commercial_dependency_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("commercial_output_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("commercial_dependency_state", "VARCHAR(48) NOT NULL DEFAULT 'legacy_unknown_review_required'"),
        ("commercial_plan_revision", "INTEGER NOT NULL DEFAULT 0"),
        ("approval_revoked_reason", "TEXT NOT NULL DEFAULT ''"),
        ("approval_revoked_at", "DATETIME"),
        ("approved_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
    "outreach_approval_history": [
        ("commercial_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("commercial_dependency_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("commercial_output_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "suppression_entries": [
        ("reason", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("created_at", "DATETIME"),
    ],
    "activity_log": [
        ("lead_id", "INTEGER"),
        ("action", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("message", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "DATETIME"),
    ],
    "contact_interactions": [
        ("semantic_capture_version", "VARCHAR(32) NOT NULL DEFAULT ''"),
        ("response_signals_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("objection", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("contact_name", "VARCHAR(160) NOT NULL DEFAULT ''"),
        ("contact_role", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("decision_maker_status", "VARCHAR(40) NOT NULL DEFAULT 'Unknown'"),
        ("business_goal", "TEXT NOT NULL DEFAULT ''"),
        ("capacity_status", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("buyer_questions_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("commitments_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("branch_path_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("guided_call_identity_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("guided_call_sequence_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("next_action", "TEXT NOT NULL DEFAULT ''"),
        ("credibility_concern", "BOOLEAN NOT NULL DEFAULT 0"),
        ("wants_examples", "BOOLEAN NOT NULL DEFAULT 0"),
        ("wants_references", "BOOLEAN NOT NULL DEFAULT 0"),
        ("concerned_about_ai", "BOOLEAN NOT NULL DEFAULT 0"),
        ("wants_proof", "BOOLEAN NOT NULL DEFAULT 0"),
        ("seller_experience_question", "BOOLEAN NOT NULL DEFAULT 0"),
        ("local_presence_question", "BOOLEAN NOT NULL DEFAULT 0"),
        ("decision_maker_skeptical", "BOOLEAN NOT NULL DEFAULT 0"),
        ("legitimacy_concern", "BOOLEAN NOT NULL DEFAULT 0"),
        ("commercial_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("commercial_dependency_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("linked_outreach_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
    ],
    "seller_profiles": [
        ("identity_type", "VARCHAR(60) NOT NULL DEFAULT 'Individual / Freelancer'"),
        ("location_mode", "VARCHAR(40) NOT NULL DEFAULT 'Not configured'"),
        ("location_label", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("service_area", "VARCHAR(240) NOT NULL DEFAULT ''"),
    ],
    "seller_proof": [
        ("project_id", "INTEGER"),
        ("grouping_state", "VARCHAR(40) NOT NULL DEFAULT 'unresolved'"),
        ("status", "VARCHAR(60) NOT NULL DEFAULT 'Unclassified'"),
        ("niche", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("canonical_niche_id", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("niche_match_rule", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("description", "TEXT NOT NULL DEFAULT ''"),
        ("client_name", "VARCHAR(200)"),
        ("project_value", "INTEGER"),
        ("completion_date", "VARCHAR(10)"),
        ("public_url", "VARCHAR(500)"),
        ("verified", "BOOLEAN NOT NULL DEFAULT 0"),
        ("client_work", "BOOLEAN NOT NULL DEFAULT 0"),
        ("software_ai_project", "BOOLEAN NOT NULL DEFAULT 0"),
        ("testimonial_available", "BOOLEAN NOT NULL DEFAULT 0"),
        ("measurable_result_available", "BOOLEAN NOT NULL DEFAULT 0"),
        ("before_after_available", "BOOLEAN NOT NULL DEFAULT 0"),
        ("provenance", "TEXT NOT NULL DEFAULT ''"),
        ("safe_claims_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("prohibited_claims_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("internal_only", "BOOLEAN NOT NULL DEFAULT 1"),
        ("share_client_name", "BOOLEAN NOT NULL DEFAULT 0"),
        ("share_public_url", "BOOLEAN NOT NULL DEFAULT 0"),
        ("share_testimonial", "BOOLEAN NOT NULL DEFAULT 0"),
        ("share_case_study", "BOOLEAN NOT NULL DEFAULT 0"),
        ("share_reference", "BOOLEAN NOT NULL DEFAULT 0"),
        ("artifact_state", "VARCHAR(32) NOT NULL DEFAULT 'active'"),
        ("artifact_revision", "INTEGER NOT NULL DEFAULT 1"),
        ("withdrawn_or_deleted_at", "DATETIME"),
        ("withdrawal_or_deletion_reason", "TEXT NOT NULL DEFAULT ''"),
        ("notes", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
    "seller_projects": [
        ("grouping_state", "VARCHAR(48) NOT NULL DEFAULT 'explicit'"),
        ("counting_state", "VARCHAR(32) NOT NULL DEFAULT 'legacy_unresolved'"),
        ("verified", "BOOLEAN NOT NULL DEFAULT 0"),
        ("legacy_source_proof_id", "INTEGER"),
        ("invalidated_at", "DATETIME"),
        ("invalidation_reason", "TEXT NOT NULL DEFAULT ''"),
        ("superseded_by_project_id", "INTEGER"),
        ("project_revision", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "offer_history": [
        ("canonical_niche_id", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("niche_match_rule", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("canonical_offer_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("offer_resolution_state", "VARCHAR(40) NOT NULL DEFAULT 'unmapped'"),
        ("commercial_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("commercial_dependency_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "app_settings": [
        ("value", "TEXT NOT NULL DEFAULT ''"),
    ],
}
