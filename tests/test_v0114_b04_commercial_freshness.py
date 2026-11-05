from __future__ import annotations

from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.repositories import save_outreach_draft, update_lead_fields
from local_presence_miner.database.schema import Lead, OutreachApprovalHistory, WebsiteAuditRecord
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan, build_adaptive_sales_plan_with_context
from local_presence_miner.services.commercial_plan_service import build_current_offer_context
from local_presence_miner.services.commercial_state_service import draft_commercial_errors, persist_current_plan


def _lead() -> Lead:
    return Lead(
        place_id="b04-roofing",
        name="B04 Roofing",
        category="roofing",
        website="https://example.test",
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        qualification_class="Qualified",
        qualification_confidence="Moderate",
        qualification_json='{"classification":"Qualified","confidence":"Moderate"}',
        target_signals_json='["No obvious quote request path"]',
        audit=WebsiteAuditRecord(url="https://example.test", reachable=True, status_code=200,
                                checks_json='{"sitewide_contact_path":false,"tap_to_call":false,"contact_form":false}'),
    )


def test_current_offer_context_applies_scope_before_pricing(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "b04-context.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        context, offer = build_current_offer_context(session, lead, competitors=[])
        assert context.offer_id == "conversion_tune_up"
        assert tuple(offer.scope) == context.scope
        assert context.scope[0] == "mobile call/quote button"
        plan, pricing = build_adaptive_sales_plan(session, lead)
        assert tuple(plan.smart_offer.scope) == context.scope
        assert pricing.project.offer_id == context.offer_id


def test_commercial_change_revokes_approval_but_preserves_exact_history(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "b04-stale.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Subject", "Exact historical body", commercial_snapshot=snapshot.to_dict()
        )
        draft.approved = True  # Approval mechanics are covered separately; this exercises propagation preservation.
        session.flush()
        update_lead_fields(session, lead.id, recommended_offer="Review Trust Builder", recommended_offer_id="review_trust_builder")
        assert draft.approved is False
        assert draft.commercial_dependency_state == "stale"
        history = session.query(OutreachApprovalHistory).one()
        assert history.body == "Exact historical body"
        assert history.commercial_dependency_fingerprint == snapshot.dependency_fingerprint


def test_draft_requires_current_matching_commercial_snapshot(tmp_path) -> None:
    factory = create_session_factory(tmp_path / "b04-draft.sqlite3")
    initialize_database(factory)
    with factory() as session:
        lead = _lead()
        session.add(lead)
        session.flush()
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        draft = save_outreach_draft(
            session, lead.id, OutreachKind.INITIAL_EMAIL, "Subject", "Body", commercial_snapshot=snapshot.to_dict()
        )
        assert not draft_commercial_errors(session, draft)
        lead.commercial_dependency_fingerprint = "changed"
        assert draft_commercial_errors(session, draft) == ("Commercial inputs changed; regenerate and review this draft.",)
