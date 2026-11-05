"""Owner constraints tested against actual assessments, storage and quoted plans.

All sources and businesses below are synthetic. Expected dispositions derive
from the owner's explicit words, never a copied ranking or price calculation.
"""

from dataclasses import replace
from uuid import uuid4

import pytest

from local_presence_miner.domain.intervention_assessment import InterventionEvidence, assess_interventions
from local_presence_miner.domain.owner_strategy import owner_fit_for_scope, validate_owner_strategy
from local_presence_miner.services.owner_strategy_service import append_owner_strategy, owner_strategy_history, project_owner_strategy

HEALTHY = {
    "https": True, "viewport": True, "tap_to_call": True, "contact_form": False,
    "sitewide_contact_path": True, "clear_primary_cta": True,
    "indexable_sample": True, "service_pages": True, "trust_signals": True,
}


def evidence(*, service="emergency plumbing", **changes):
    opportunity = {
        "cluster_id": "selected-service", "service": service,
        "queries": [f"{service} Colorado Springs CO"], "decision": "recommended",
        "action": "improve_page", "service_state": "confirmed",
        "scope": ["local SEO title/meta/H1 fixes"],
        "evidence_refs": ["seo_snapshot:1:synthetic", "source:query-observation"],
        "observations": ["The selected service page title is Home."],
    }
    return InterventionEvidence(
        website_url="https://owner-fit.example", website_state="observed", website_checks=HEALTHY,
        website_refs=("website_audit:1:synthetic",), google_current=True,
        has_hours=True, photo_count=12, rating=4.8, review_count=100,
        google_refs=("google_places:synthetic",),
        seo_research={"state": "complete", "snapshot_sha256": "synthetic", "opportunities": [opportunity]},
        **changes,
    )


@pytest.mark.parametrize("capacity", [
    "Fully booked",
    "Our schedule is full through December. We cannot take any more customers.",
    "We are fully booked until February; we do not want additional customers.",
])
def test_capacity_token_and_explicit_sentence_both_withhold_growth_scope(capacity):
    result = assess_interventions(evidence(capacity_status=capacity))
    assert result.state == "validate_first"
    assert not result.recommended_offer_id
    assert all(not candidate.scope for candidate in result.ranked_candidates)


@pytest.mark.parametrize("goal,service", [
    ("Only bathroom remodeling jobs please. Do not bring us emergency plumbing calls.", "emergency plumbing"),
    ("We do not want emergency plumbing calls. We want bathroom remodel projects only.", "emergency plumbing"),
    ("Commercial customers only. We do not want residential plumbing repair calls.", "residential plumbing repair"),
    ("Our current web company is already rebuilding the emergency plumbing page. Please do not duplicate that work.", "emergency plumbing"),
    ("Emergency plumbing barely makes us money. We want to grow bathroom remodeling instead.", "emergency plumbing"),
])
def test_explicit_goal_conflict_needs_selected_service_validation(goal, service):
    result = assess_interventions(evidence(service=service, business_goal=goal))
    assert result.state == "validate_first"
    assert not result.recommended_offer_id


def test_growth_capacity_does_not_block_independently_observed_contact_repair():
    current = evidence(capacity_status="Fully booked")
    current = replace(current, website_checks={**HEALTHY, "sitewide_contact_path": False, "tap_to_call": False})
    result = assess_interventions(current)
    assert result.state == "recommended"
    assert result.ranked_candidates[0].intervention_id == "contact_path_repair"
    assert result.ranked_candidates[0].scope == ("mobile call/quote button", "homepage CTA rewrite")


def test_ambiguous_goal_does_not_invent_owner_strategy_or_change_supported_scope():
    result = assess_interventions(evidence(business_goal="Make it easier to find us on Google"))
    assert result.state == "recommended"
    assert result.ranked_candidates[0].scope == ("local SEO title/meta/H1 fixes",)


def strategy(*facts, territories=None, mode="preferred"):
    return {"schema_version": 1, "constraints": [
        {"kind": kind, "value": value, "original_wording": text} for kind, value, text in facts
    ], "target_territories": territories or [], "territory_mode": mode}


def confirmed(value):
    return {**validate_owner_strategy(value), "state": "confirmed", "evidence_refs": ["owner_assertion:1:synthetic"]}


@pytest.mark.parametrize("fact,service", [
    (("excluded_service", "emergency plumbing", "We do not want emergency calls."), "emergency plumbing"),
    (("desired_service", "bathroom remodeling", "Bathroom projects only."), "emergency plumbing"),
    (("desired_customer_type", "commercial", "Commercial customers only."), "residential plumbing repair"),
    (("excluded_customer_type", "residential", "No residential customers."), "residential plumbing repair"),
    (("provider_work", "emergency plumbing", "Our provider is already changing this page."), "emergency plumbing"),
    (("low_economic_priority", "emergency plumbing", "Emergency plumbing barely makes money."), "emergency plumbing"),
])
def test_structured_confirmed_constraints_suspend_the_exact_service(fact, service):
    result = assess_interventions(evidence(service=service, owner_strategy=confirmed(strategy(fact))))
    assert result.state == "validate_first"
    assert result.owner_fit_status == "conflict"
    assert result.owner_fit_reason
    assert result.owner_validation_question
    assert service in result.owner_validation_question or "residential" in result.owner_validation_question
    assert not result.recommended_offer_id
    assert "owner_assertion:1:synthetic" in result.evidence_refs
    assert all(not item.scope and not item.offer_id for item in result.ranked_candidates)


def test_qualitative_economics_does_not_become_an_invented_margin():
    current = evidence(owner_strategy=confirmed(strategy(("low_economic_priority", "emergency plumbing", "Barely makes money."))))
    result = assess_interventions(current)
    assert result.state == "validate_first"
    assert "numeric" in result.owner_fit_reason
    assert "gross_margin" not in current.seo_research
    assert "0%" not in str(result.to_dict())


def test_matching_desired_service_preserves_supported_scope_and_inspectable_proof():
    current = evidence(owner_strategy=confirmed(strategy(("desired_service", "emergency plumbing", "We want emergency jobs."))))
    packet = {"query": "emergency plumber Colorado Springs CO", "channel": "organic", "position": 12,
              "page_url": "https://owner-fit.example/emergency", "source_coverage": {"kind": "city", "city": "Colorado Springs",
                                                                                      "country": "US", "state": "CO"}}
    current.seo_research["opportunities"][0]["selected_evidence"] = packet
    result = assess_interventions(current)
    assert result.state == "recommended"
    assert result.owner_fit_status == "confirmed"
    assert result.ranked_candidates[0].selected_service == "emergency plumbing"
    assert result.ranked_candidates[0].selected_evidence == packet
    assert result.ranked_candidates[0].selected_page_url == packet["page_url"]
    assert "title/meta/H1" in result.owner_validation_question


def test_both_customer_types_is_not_a_false_exclusion():
    current = evidence(service="residential plumbing repair", owner_strategy=confirmed(strategy(
        ("desired_customer_type", "commercial", "We serve both."), ("desired_customer_type", "residential", "We serve both."),
    )))
    assert assess_interventions(current).state == "recommended"


@pytest.mark.parametrize("coverage,expected", [
    ({"kind": "zip", "postal_codes": ["80918"], "country": "US", "state": "CO"}, "confirmed"),
    ({"kind": "zip", "postal_codes": ["80906", "80918"], "country": "US", "state": "CO"}, "confirmed"),
    ({"kind": "zip", "postal_codes": ["80903"], "country": "US", "state": "CO"}, "conflict"),
    ({"kind": "zip", "postal_codes": ["80918"], "country": "US", "state": "TX"}, "unknown"),
    ({"kind": "city", "city": "Colorado Springs", "country": "US", "state": "CO"}, "unknown"),
    ({"kind": "radius", "center": {"latitude": 38.8, "longitude": -104.8}, "radius_miles": 10,
      "country": "US", "state": "CO"}, "unknown"),
    ({}, "unknown"),
])
def test_multiple_desired_zips_need_actual_matching_coverage_not_the_office_zip(coverage, expected):
    desired = confirmed(strategy(territories=[{"kind": "zip", "country": "US", "state": "CO",
                                             "postal_codes": ["80906", "80918"], "original_wording": "Only these two ZIPs."}], mode="only"))
    fit = owner_fit_for_scope(desired, intervention_id="seo_improve_page:selected", scope=("local SEO title/meta/H1 fixes",),
                              service="emergency plumbing", coverage=coverage)
    assert fit.status == expected
    assert fit.withhold is (expected != "confirmed")


def test_provider_exact_scope_does_not_block_a_different_supported_task():
    desired = strategy(("provider_work", "emergency plumbing", "Provider is changing photos only."))
    desired["constraints"][0]["scope"] = ["update service photos"]
    result = assess_interventions(evidence(owner_strategy=confirmed(desired)))
    assert result.state == "recommended"
    desired["constraints"][0]["scope"] = ["local SEO title/meta/H1 fixes"]
    assert assess_interventions(evidence(owner_strategy=confirmed(desired))).state == "validate_first"


def test_wanted_supported_service_precedes_excluded_service_in_same_seo_tier():
    current = evidence(owner_strategy=confirmed(strategy(
        ("desired_service", "bathroom remodeling", "Bathroom projects only."),
        ("excluded_service", "emergency plumbing", "No emergency calls."),
    )))
    alternative = evidence(service="bathroom remodeling").seo_research["opportunities"][0]
    alternative["cluster_id"] = "wanted-service"
    current.seo_research["opportunities"].append(alternative)
    result = assess_interventions(current)
    assert result.state == "recommended"
    assert result.ranked_candidates[0].selected_service == "bathroom remodeling"
    assert result.ranked_candidates[0].owner_fit_status == "confirmed"
    excluded = next(item for item in result.ranked_candidates if item.selected_service == "emergency plumbing")
    assert excluded.status == "validate_first"
    assert not excluded.offer_id and not excluded.scope


def test_unconfirmed_interpretation_and_corrupt_current_preferences_require_validation():
    for state in ("unconfirmed", "invalid", "ambiguous"):
        result = assess_interventions(evidence(owner_strategy={"state": state}))
        assert result.state == "validate_first"
        assert result.owner_fit_status == "unknown"
        assert result.owner_validation_question


def test_negated_capacity_and_hypothetical_sentence_do_not_create_growth_constraints():
    for text in ("Not at capacity", "We are not fully booked", "If fully booked, ask us later", "We are no longer fully booked"):
        assert assess_interventions(evidence(capacity_status=text)).state == "recommended"


@pytest.fixture
def storage(tmp_path):
    from local_presence_miner.database.engine import create_session_factory
    from local_presence_miner.database.migrations import initialize_database

    factory = create_session_factory(tmp_path / "owner-fit.sqlite3")
    initialize_database(factory)
    return factory


def stored_business(session):
    """Use the existing source-backed synthetic boundary fixture, not its oracles."""
    from test_seo_research_integration import business, sample_payload

    from local_presence_miner.database.schema import LeadSearch
    from local_presence_miner.services.seo_research_service import append_research

    lead, audit = business(session)
    search = LeadSearch(name="Owner fit", city="Austin", state_region="TX", niche="plumber")
    session.add(search)
    session.flush()
    lead.search_id = search.id
    append_research(session, lead, sample_payload(session, lead))
    return lead, audit


def stored_plan(session, lead):
    from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context

    return build_adaptive_sales_plan_with_context(session, lead, competitors=[])


def test_owner_record_restart_correction_retains_wording_history_and_controls_price(storage):
    with storage() as session:
        lead, _ = stored_business(session)
        _, price, context = stored_plan(session, lead)
        assert price.price_available
        assert context.scope == ("local SEO title/meta/H1 fixes",)
        initial = strategy(("excluded_service", "emergency plumbing", "No emergency work."))
        first = append_owner_strategy(session, lead, initial, source_text="No emergency work.", owner_confirmed=True)
        original = first.value_json
        _, price, context = stored_plan(session, lead)
        assert not price.price_available
        assert not context.scope
        assert context.intervention_assessment["owner_fit_status"] == "conflict"
        corrected = strategy(("desired_service", "emergency plumbing", "We now want emergency jobs."))
        second = append_owner_strategy(session, lead, corrected, source_text="We now want emergency jobs.",
                                       supersedes_assertion_id=first.id, correction_reason="Owner explicitly reconsidered service", owner_confirmed=True)
        assert stored_plan(session, lead)[1].price_available
        assert first.value_json == original
        assert first.source_text == "No emergency work."
        assert second.supersedes_assertion_id == first.id
        history = owner_strategy_history(session, lead.id)
        assert len(history) == 2
        assert history[0]["source_text"] == "No emergency work."
        assert history[1]["source_text"] == "We now want emergency jobs."
        lead_id = lead.id
        session.commit()
    from local_presence_miner.database.schema import Lead

    with storage() as session:
        lead = session.get(Lead, lead_id)
        projected = project_owner_strategy(session, lead)
        assert projected["state"] == "confirmed"
        assert projected["constraints"][0]["kind"] == "desired_service"
        assert projected["provenance"][0]["correction_reason"] == "Owner explicitly reconsidered service"


def test_operator_interpretation_is_not_laundered_into_owner_confirmation(storage):
    with storage() as session:
        lead, _ = stored_business(session)
        append_owner_strategy(session, lead, strategy(("desired_service", "emergency plumbing", "Salesperson assumes emergency jobs.")),
                              source_text="Salesperson assumes emergency jobs.", owner_confirmed=False)
        projected = project_owner_strategy(session, lead)
        assert projected["state"] == "unconfirmed"
        assert projected["provenance"][0]["source_kind"] == "OPERATOR_INTERPRETATION"
        assert not stored_plan(session, lead)[1].price_available


def test_legacy_operator_goal_keeps_its_source_and_requires_owner_validation(storage):
    from local_presence_miner.database.repositories import save_contact_interaction
    from local_presence_miner.time_utils import utc_now

    with storage() as session:
        lead, _ = stored_business(session)
        interaction = save_contact_interaction(session, lead.id, interaction_datetime=utc_now().isoformat(),
                                                method="Phone", direction="Inbound", outcome="Conversation recorded", notes="Operator note",
                                                business_goal="We do not want emergency plumbing calls.")
        projection = project_owner_strategy(session, lead)
        legacy = projection["legacy_context"]["goal"]
        assert legacy["interaction_id"] == interaction.id
        assert legacy["source_kind"] == "OPERATOR_OBSERVATION"
        assert not legacy["confirmed_owner"]
        _, pricing, context = stored_plan(session, lead)
        assert not pricing.price_available
        assessment = context.intervention_assessment
        assert assessment["owner_fit_status"] == "unknown"
        assert "emergency plumbing" in assessment["owner_validation_question"]
        assert any(ref in assessment["evidence_refs"] for ref in legacy["evidence_refs"])


def test_new_strategy_default_does_not_imply_owner_confirmation(storage):
    with storage() as session:
        lead, _ = stored_business(session)
        append_owner_strategy(session, lead, strategy(("desired_service", "emergency plumbing", "Unconfirmed input.")),
                              source_text="Unconfirmed input.")
        assert project_owner_strategy(session, lead)["state"] == "unconfirmed"
        assert not stored_plan(session, lead)[1].price_available


@pytest.mark.parametrize("bad", ["invalid JSON", '{"schema_version":1,"schema_version":1}', '{"schema_version":999}'])
def test_corrupt_newer_owner_assertion_cannot_reuse_old_approval(storage, bad):
    from local_presence_miner.database.schema import ConversationAssertion

    with storage() as session:
        lead, _ = stored_business(session)
        first = append_owner_strategy(session, lead, strategy(("desired_service", "emergency plumbing", "We want emergency jobs.")),
                                      source_text="We want emergency jobs.", owner_confirmed=True)
        session.add(ConversationAssertion(assertion_uid=str(uuid4()), lead_id=lead.id, subject_key="owner.strategy",
                                          value_json=bad, assertion_state="ACTIVE", source_kind="OWNER_LITERAL",
                                          source_text="New statement", source_text_mode="VERBATIM", confidence="CONFIRMED",
                                          supersedes_assertion_id=first.id, correction_reason="Manual correction"))
        session.flush()
        assert project_owner_strategy(session, lead)["state"] == "invalid"
        assert not stored_plan(session, lead)[1].price_available
        assert len(owner_strategy_history(session, lead.id)) == 2


def test_contradictory_current_preferences_do_not_choose_the_newest_without_correction(storage):
    with storage() as session:
        lead, _ = stored_business(session)
        append_owner_strategy(session, lead, strategy(("desired_service", "emergency plumbing", "Want emergency work.")),
                              source_text="Want emergency work.", owner_confirmed=True)
        append_owner_strategy(session, lead, strategy(("excluded_service", "emergency plumbing", "No emergency work.")),
                              source_text="No emergency work.", owner_confirmed=True)
        assert project_owner_strategy(session, lead)["state"] == "ambiguous"
        assert not stored_plan(session, lead)[1].price_available


def test_confirmed_fact_needs_original_wording_and_source_provenance():
    with pytest.raises(ValueError, match="original wording"):
        validate_owner_strategy({"schema_version": 1, "constraints": [{"kind": "desired_service", "value": "emergency plumbing"}]})
    current = confirmed(strategy(("desired_service", "emergency plumbing", "We want emergency jobs.")))
    current["evidence_refs"] = []
    result = assess_interventions(evidence(owner_strategy=current))
    assert result.state == "validate_first"
    assert "provenance" in result.owner_fit_reason


def test_owner_constraints_revoke_current_approval_but_keep_human_and_historical_text(storage):
    from sqlalchemy import select

    from local_presence_miner.database.repositories import save_outreach_draft
    from local_presence_miner.database.schema import OutreachApprovalHistory
    from local_presence_miner.domain.enums import OutreachKind
    from local_presence_miner.services.commercial_state_service import persist_current_plan

    with storage() as session:
        lead, _ = stored_business(session)
        _, pricing, context = stored_plan(session, lead)
        snapshot = persist_current_plan(session, lead, competitors=[], pricing=pricing, context=context)
        body = "Exact already approved human wording. Prior offer $350; preserve this!"
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Historical quote", body,
                                   commercial_snapshot=snapshot.to_dict())
        draft.approved = True
        session.flush()
        original_offer_id = lead.recommended_offer_id
        append_owner_strategy(session, lead, strategy(("excluded_service", "emergency plumbing", "No emergency inquiries.")),
                              source_text="No emergency inquiries.", owner_confirmed=True)
        assert not draft.approved
        assert draft.body == body
        assert lead.recommended_offer_id == original_offer_id
        assert lead.commercial_plan_state == "stale"
        assert not stored_plan(session, lead)[1].price_available
        history = list(session.scalars(select(OutreachApprovalHistory).where(OutreachApprovalHistory.lead_id == lead.id)))
        assert history[-1].body == body


def test_cleared_owner_strategy_does_not_fall_back_to_old_confirmed_preferences(storage):
    from local_presence_miner.domain.enums import AssertionState
    from local_presence_miner.services.conversation_state_service import ConversationStateService

    with storage() as session:
        lead, _ = stored_business(session)
        first = append_owner_strategy(session, lead, strategy(("excluded_service", "emergency plumbing", "No emergency work.")),
                                      source_text="No emergency work.", owner_confirmed=True)
        ConversationStateService().correct_assertion(session, first.id, assertion_state=AssertionState.UNKNOWN,
                                                     correction_reason="Owner has not confirmed current preferences")
        projection = project_owner_strategy(session, lead)
        assert projection["state"] == "unknown"
        assert projection["constraints"] == []
        assert len(owner_strategy_history(session, lead.id)) == 2
        assert assess_interventions(evidence(owner_strategy=projection)).owner_fit_status == "unknown"


def test_dialog_records_confirmed_multi_zip_preferences_without_relabeling_observations(storage, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from local_presence_miner.database.schema import Lead
    from local_presence_miner.ui.dialogs.contact_interaction_dialog import ContactInteractionDialog

    app = QApplication.instance() or QApplication([])
    with storage() as session:
        lead, _ = stored_business(session)
        lead_id = lead.id
        session.commit()
    dialog = ContactInteractionDialog(storage, lead_id)
    dialog.outcome.setCurrentText("Conversation recorded")
    dialog.owner_wording.setPlainText("Emergency jobs in 80906 and 80918 only, please.")
    dialog.owner_confirmation.setCurrentText("Owner explicitly confirmed")
    dialog.desired_services.setText("emergency plumbing")
    dialog.owner_target_zips.setText("80906, 80918")
    dialog.owner_target_state.setText("CO")
    dialog.owner_territory_mode.setCurrentText("Only these areas")
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    with storage() as session:
        lead = session.get(Lead, lead_id)
        projection = project_owner_strategy(session, lead)
        assert projection["state"] == "confirmed"
        assert projection["target_territories"][0]["postal_codes"] == ["80906", "80918"]
        assert projection["target_territories"][0]["state"] == "CO"
        assert lead.target_zip_code == ""
        assert not stored_plan(session, lead)[1].price_available
    dialog.deleteLater()
    app.processEvents()

