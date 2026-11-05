from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database


def query(path: Path, sql: str):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def main() -> int:
    database = Path(sys.argv[1]).resolve()
    report = Path(sys.argv[2]).resolve()
    if report.exists():
        raise RuntimeError(f"Refusing to overwrite report: {report}")
    before = {
        "lead": query(database, "SELECT place_id,name,phone,website,status FROM leads"),
        "proof": query(database, "SELECT title,status,verified,safe_claims_json FROM seller_proof"),
        "draft": query(database, "SELECT subject,body,approved FROM outreach_drafts WHERE subject='Historical subject'"),
    }
    factory = create_session_factory(database)
    initialize_database(factory)
    backup = database.with_suffix(database.suffix + ".backup-before-v0112")
    first = {
        "lead": query(database, "SELECT place_id,name,phone,website,status FROM leads"),
        "proof": query(
            database,
            "SELECT title,status,verified,safe_claims_json,internal_only,share_client_name,share_public_url,"
            "share_testimonial,share_case_study,share_reference FROM seller_proof",
        ),
        "draft": query(
            database, "SELECT subject,body,approved,dependency_state,approval_revoked_reason FROM outreach_drafts WHERE subject='Historical subject'"
        ),
        "history": query(database, "SELECT subject,body,proof_dependencies_json,revocation_reason FROM outreach_approval_history"),
    }
    first_db_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    initialize_database(factory)
    second = {
        "history": query(database, "SELECT subject,body,proof_dependencies_json,revocation_reason FROM outreach_approval_history"),
        "draft": query(
            database, "SELECT subject,body,approved,dependency_state,approval_revoked_reason FROM outreach_drafts WHERE subject='Historical subject'"
        ),
    }
    assertions = {
        "backup_exists_and_integrity_ok": backup.exists() and query(backup, "PRAGMA integrity_check") == [("ok",)],
        "baseline_lead_fields_preserved": [row[:4] for row in before["lead"]] == [row[:4] for row in first["lead"]],
        "proof_claim_fields_preserved": before["proof"] == [row[:4] for row in first["proof"]],
        "permissions_default_deny": all(row[4:] == (1, 0, 0, 0, 0, 0) for row in first["proof"]),
        "approved_body_preserved_exactly": before["draft"][0][1] == first["draft"][0][1] == "EXACT HISTORICAL APPROVED BODY",
        "unknown_historical_approval_revoked": first["draft"][0][2] == 0 and first["draft"][0][3] == "unknown",
        "lead_moved_to_needs_review": first["lead"][0][4] == "Needs Review",
        "history_preserves_exact_body": first["history"][0][1] == before["draft"][0][1],
        "second_start_is_idempotent": second["history"] == first["history"] and second["draft"] == first["draft"],
        "backup_not_overwritten": hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash,
        "no_second_start_database_mutation": hashlib.sha256(database.read_bytes()).hexdigest() == first_db_hash,
    }
    payload = {
        "fixture_origin": "Created by immutable authoritative v0.1.11 source tree",
        "database": database.name,
        "backup": backup.name,
        "backup_sha256": backup_hash,
        "historical_approvals_affected": len(first["history"]),
        "assertions": assertions,
        "status": "PASS" if all(assertions.values()) else "FAIL",
    }
    report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    factory.kw["bind"].dispose()
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
