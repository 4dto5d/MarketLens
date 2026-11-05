from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from sqlalchemy import select

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import save_contact_interaction
from local_presence_miner.database.schema import ContactInteraction, Lead, WebsiteAuditRecord
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.call_tree_identity import CALL_TREE_ID, CALL_TREE_VERSION
from local_presence_miner.ui.dialogs.contact_interaction_dialog import ContactInteractionDialog
from local_presence_miner.ui.dialogs.guided_call_dialog import GuidedCallDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _factory(tmp_path: Path):
    factory = create_session_factory(tmp_path / "b2-closure.sqlite3")
    initialize_database(factory)
    return factory


def _lead() -> Lead:
    return Lead(
        place_id="b2-closure",
        name="B2 Closure Roofing",
        category="roofers",
        phone="555-010-2015",
        website="https://example.test",
        qualification_class="Qualified",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Qualified","confidence":"Strong"}',
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        offer_resolution_state="canonical_id",
        audit=WebsiteAuditRecord(url="https://example.test", reachable=True, status_code=200,
                                checks_json='{"sitewide_contact_path":false,"tap_to_call":false,"contact_form":false}'),
    )


def _all_nodes(guide):
    pending = list(guide.branches)
    while pending:
        node = pending.pop(0)
        yield node
        pending[0:0] = list(node.followups)


def test_b2_call_tree_has_stable_authored_unique_identity(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        guide = CallGuideService().build(session, lead, [])

    nodes = list(_all_nodes(guide))
    node_ids = [node.node_id for node in nodes]
    assert guide.tree_id == CALL_TREE_ID
    assert guide.tree_version == CALL_TREE_VERSION
    assert len(node_ids) == len(set(node_ids))
    assert all(node_ids)
    assert all(node.strategy_id for node in nodes)
    assert next(node for node in nodes if node.label == "Who are you?").node_id == "gc.who_are_you"
    assert (
        next(node for node in nodes if node.label == "What company are you with?").node_id
        == "gc.who_are_you.what_company_are_you_with"
    )


def test_b2_display_copy_and_actual_use_are_distinct_and_persisted(tmp_path) -> None:
    qt_app = _app()
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.commit()
        lead_id = lead.id

    dialog = GuidedCallDialog(factory, lead_id)
    dialog.mode.setCurrentText("Live Call")
    dialog.show_branch("price")

    displayed = dict(dialog._current_reply_identity)
    assert displayed["usage_state"] == "displayed"
    assert dialog._guide_events[-1]["event"] == "reply_displayed"
    assert dialog._guide_events[-1]["usage_state"] == "displayed"

    dialog.copy_reply()
    assert dialog._current_reply_identity["usage_state"] == "copied"
    assert dialog._guide_events[-1]["event"] == "reply_copied"
    assert all(event["usage_state"] != "used" for event in dialog._guide_events)

    dialog.mark_reply_used()
    assert dialog._current_reply_identity["usage_state"] == "used"
    assert dialog._guide_events[-1]["event"] == "reply_used"
    assert [event["sequence"] for event in dialog._guide_events] == list(
        range(1, len(dialog._guide_events) + 1)
    )

    outcome = ContactInteractionDialog(
        factory,
        lead_id,
        default_method="Phone",
        defaults={
            "outcome": "Interested",
            "branch_path": list(dialog.path),
            "guided_call_identity": dict(dialog._current_reply_identity),
            "guided_call_sequence": list(dialog._guide_events),
        },
    )
    outcome.save()

    with factory() as session:
        interaction = session.scalar(
            select(ContactInteraction).where(ContactInteraction.lead_id == lead_id)
        )
        assert interaction is not None
        identity = json.loads(interaction.guided_call_identity_json)
        events = json.loads(interaction.guided_call_sequence_json)
        assert identity["tree_id"] == CALL_TREE_ID
        assert identity["selected_node_id"] == "gc.price"
        assert identity["usage_state"] == "used"
        assert events[-1]["usage_state"] == "used"
        assert events[-1]["response_fingerprint"] == identity["response_fingerprint"]

    outcome.close()
    dialog.close()
    qt_app.processEvents()


def test_b2_guided_call_capture_rejects_tampering_and_noncontiguous_sequence(tmp_path) -> None:
    qt_app = _app()
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.commit()
        lead_id = lead.id

    dialog = GuidedCallDialog(factory, lead_id)
    dialog.mode.setCurrentText("Live Call")
    dialog.show_branch("price")
    identity = dict(dialog._current_reply_identity)
    events = list(dialog._guide_events)

    with factory() as session:
        forged = {**identity, "response_snapshot": "Different text"}
        with pytest.raises(ValueError, match="fingerprint does not match"):
            save_contact_interaction(
                session,
                lead_id,
                interaction_datetime="2026-09-12T00:30:00Z",
                method="Phone",
                direction="Outbound",
                outcome="Interested",
                notes="Forged identity",
                guided_call_identity=forged,
                guided_call_sequence=events,
            )

        broken_order = [{**events[0], "sequence": 2}]
        with pytest.raises(ValueError, match="contiguous and ordered"):
            save_contact_interaction(
                session,
                lead_id,
                interaction_datetime="2026-09-12T00:31:00Z",
                method="Phone",
                direction="Outbound",
                outcome="Interested",
                notes="Broken order",
                guided_call_identity=identity,
                guided_call_sequence=broken_order,
            )

    dialog.close()
    qt_app.processEvents()


def test_b2_blank_outcome_cannot_persist_from_repository_or_dialog(tmp_path) -> None:
    qt_app = _app()
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.commit()
        lead_id = lead.id

    with factory() as session, pytest.raises(ValueError, match="truthful contact outcome"):
        save_contact_interaction(
            session,
            lead_id,
            interaction_datetime="2026-09-12T00:35:00Z",
            method="Phone",
            direction="Outbound",
            outcome="",
            notes="Must not save",
        )

    dialog = ContactInteractionDialog(factory, lead_id, default_method="Phone")
    assert dialog.outcome.currentText() == ""
    dialog.save()
    with factory() as session:
        assert session.scalar(
            select(ContactInteraction.id).where(ContactInteraction.lead_id == lead_id)
        ) is None

    dialog.close()
    qt_app.processEvents()


def test_b2_migration_backs_up_b1_rows_without_inventing_guided_call_identity(tmp_path) -> None:
    path = tmp_path / "b1-before-b2.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE app_settings (
                key VARCHAR(120) PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE contact_interactions (
                id INTEGER PRIMARY KEY,
                lead_id INTEGER NOT NULL,
                interaction_datetime VARCHAR(40) NOT NULL,
                method VARCHAR(40) NOT NULL DEFAULT 'Phone',
                direction VARCHAR(20) NOT NULL DEFAULT 'Outbound',
                outcome VARCHAR(160) NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO app_settings (key, value)
            VALUES ('v0115_b1_state_migrated', '{"version":"v0.1.15-b1"}');
            INSERT INTO contact_interactions
                (id, lead_id, interaction_datetime, method, direction, outcome, notes)
            VALUES
                (1, 1, '2026-09-11T20:00', 'Phone', 'Outbound', 'Interested', 'Historical B1 row');
            """
        )

    factory = create_session_factory(path)
    initialize_database(factory)

    backup = path.with_suffix(path.suffix + ".backup-before-v0115-b2")
    assert backup.exists()
    with sqlite3.connect(backup) as copied:
        columns = {
            row[1] for row in copied.execute("PRAGMA table_info(contact_interactions)")
        }
        assert "guided_call_identity_json" not in columns
        assert copied.execute(
            "SELECT outcome, notes FROM contact_interactions WHERE id=1"
        ).fetchone() == ("Interested", "Historical B1 row")

    with sqlite3.connect(path) as migrated:
        identity, sequence = migrated.execute(
            "SELECT guided_call_identity_json, guided_call_sequence_json "
            "FROM contact_interactions WHERE id=1"
        ).fetchone()
        assert identity == "{}"
        assert sequence == "[]"
        marker = migrated.execute(
            "SELECT value FROM app_settings "
            "WHERE key='v0115_b2_guided_call_identity_migrated'"
        ).fetchone()
        assert marker is not None
        metadata = json.loads(marker[0])
        assert metadata["interaction_rows_preserved"] == 1
        assert metadata["historical_guided_call_identities_inferred"] == 0

    initialize_database(factory)
    assert not Path(str(backup) + ".1").exists()
