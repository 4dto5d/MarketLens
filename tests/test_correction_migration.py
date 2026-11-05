"""Real SQLite additive provenance migration, preserving historical uncertainty."""
import sqlite3

import pytest
from sqlalchemy import text

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import backup_database_before_center_provenance, initialize_database


def legacy_database(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    factory = create_session_factory(path)
    initialize_database(factory)
    with factory.kw["bind"].begin() as connection:
        connection.execute(text("ALTER TABLE search_visibility_probes DROP COLUMN center_resolution_provenance_json"))
    return path, factory


@pytest.mark.parametrize("foreign_keys", [0, 1])
def test_additive_provenance_backup_idempotence_and_unknown_history(tmp_path, foreign_keys):
    path, factory = legacy_database(tmp_path)
    with factory.kw["bind"].begin() as connection:
        connection.execute(text(f"PRAGMA foreign_keys={foreign_keys}"))
    backup = backup_database_before_center_provenance(factory.kw["bind"])
    original = backup.read_bytes()
    initialize_database(factory)
    initialize_database(factory)
    assert backup.read_bytes() == original
    with sqlite3.connect(path) as connection:
        columns = connection.execute("PRAGMA table_info(search_visibility_probes)").fetchall()
        provenance = next(row for row in columns if row[1] == "center_resolution_provenance_json")
        assert provenance[4] == "'{}'"  # no historical verified-center inference
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(backup) as connection:
        assert "center_resolution_provenance_json" not in {r[1] for r in connection.execute("PRAGMA table_info(search_visibility_probes)")}


def test_corrupt_preexisting_backup_stops_before_schema_mutation(tmp_path):
    path, factory = legacy_database(tmp_path)
    backup = path.with_suffix(path.suffix + ".backup-before-center-provenance")
    backup.write_bytes(b"corrupt pre-existing backup")
    with pytest.raises(RuntimeError, match="invalid"):
        initialize_database(factory)
    assert backup.read_bytes() == b"corrupt pre-existing backup"
    with sqlite3.connect(path) as connection:
        assert "center_resolution_provenance_json" not in {r[1] for r in connection.execute("PRAGMA table_info(search_visibility_probes)")}


def test_backup_failure_does_not_add_column(tmp_path, monkeypatch):
    path, factory = legacy_database(tmp_path)
    def fail(_source, _destination):
        raise OSError("injected backup write failure")
    monkeypatch.setattr("local_presence_miner.database.migrations.shutil.copyfileobj", fail)
    with pytest.raises(OSError, match="injected"):
        initialize_database(factory)
    with sqlite3.connect(path) as connection:
        assert "center_resolution_provenance_json" not in {r[1] for r in connection.execute("PRAGMA table_info(search_visibility_probes)")}
    # SQLite reports an empty file as integrity-ok; an interrupted backup still
    # must not be accepted as a recoverable pre-migration checkpoint on retry.
    with pytest.raises(RuntimeError, match="invalid"):
        initialize_database(factory)
    with sqlite3.connect(path) as connection:
        assert "center_resolution_provenance_json" not in {r[1] for r in connection.execute("PRAGMA table_info(search_visibility_probes)")}
