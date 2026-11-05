from __future__ import annotations

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import (
    lead_contact_readiness_errors,
    save_contact_interaction,
    update_lead_status,
)
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.enums import LeadStatus
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_state_service import persist_current_plan
from local_presence_miner.services.suppression_service import SuppressionService


def _lead() -> Lead:
    return Lead(
        place_id="a6-dnc",
        name="A6 Roofing",
        category="roofing",
        phone="5550101000",
        website="https://example.test",
        lead_score=99,
        qualification_class="Qualified",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Qualified","confidence":"Strong"}',
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        target_signals_json='["No quote path"]',
    )


def _factory(tmp_path):
    factory = create_session_factory(tmp_path / "a6.sqlite3")
    initialize_database(factory)
    return factory


def test_toolbar_and_explicit_outcome_converge_on_persisted_suppression(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        toolbar = _lead()
        toolbar.place_id = "a6-toolbar"
        outcome = _lead()
        outcome.place_id = "a6-outcome"
        session.add_all([toolbar, outcome])
        session.flush()
        SuppressionService().suppress_lead(session, toolbar, "Toolbar request")
        save_contact_interaction(
            session, outcome.id, interaction_datetime="2026-09-08T10:00", method="Phone", direction="Outbound",
            outcome="Do not contact me again", notes="Exact prospect request",
        )
        session.commit()
    with factory() as session:
        toolbar = session.query(Lead).filter_by(place_id="a6-toolbar").one()
        outcome = session.query(Lead).filter_by(place_id="a6-outcome").one()
        assert (toolbar.suppressed, toolbar.status) == (True, LeadStatus.DO_NOT_CONTACT.value)
        assert (outcome.suppressed, outcome.status) == (True, LeadStatus.DO_NOT_CONTACT.value)
        assert lead_contact_readiness_errors(session, outcome)


def test_guided_call_exact_next_action_and_current_plan_cannot_bypass_dnc(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        _plan, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        save_contact_interaction(
            session, lead.id, interaction_datetime="2026-09-08T10:00", method="Phone", direction="Outbound",
            outcome="No answer", notes="Guided Call branch was explicit", next_action="Do Not Contact",
        )
        assert lead.suppressed
        assert "Suppressed lead" in " ".join(lead_contact_readiness_errors(session, lead))
        # Score, qualification, offer state, and ordinary status edits cannot clear DNC.
        update_lead_status(session, lead.id, LeadStatus.QUALIFIED)
        assert (lead.suppressed, lead.status) == (True, LeadStatus.DO_NOT_CONTACT.value)


def test_non_dnc_outcomes_and_edits_never_infer_unsuppression_or_dnc(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        for index, outcome in enumerate(("Not interested", "Follow up later", "Price objection")):
            save_contact_interaction(
                session, lead.id, interaction_datetime=f"2026-09-08T10:0{index}", method="Phone", direction="Outbound",
                outcome=outcome, notes="Normal outcome",
            )
        assert lead.suppressed is False
        SuppressionService().suppress_lead(session, lead, "Explicit request")
        save_contact_interaction(
            session, lead.id, interaction_datetime="2026-09-08T10:10", method="Phone", direction="Outbound",
            outcome="Follow up later", notes="Later edit cannot clear DNC",
        )
        assert (lead.suppressed, lead.status) == (True, LeadStatus.DO_NOT_CONTACT.value)
