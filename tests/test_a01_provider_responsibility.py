"""A01 responsibility counterfactuals through public decisions and real SQLite.

Synthetic business/page evidence is held constant while only the owner's
recorded provider responsibility changes. No acquisition, message or payment
is executed.
"""

import json
from dataclasses import asdict
from datetime import date

import pytest
from test_owner_fit_corrections import confirmed, strategy
from test_sales_delivery_corrections import business, payload

from local_presence_miner.config import AppConfig, SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.pricing_repository import save_offer_history
from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.domain.owner_strategy import owner_fit_for_scope
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.delivery_packet_service import DELIVERY_FIELDS, DELIVERY_PREREQUISITES, DeliveryPacketService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.owner_strategy_service import append_owner_strategy, owner_strategy_history, project_owner_strategy
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.sales_evidence_service import SalesEvidenceService
from local_presence_miner.services.seo_research_service import append_research

SERVICE = "emergency plumbing"
SEO_SCOPE = ("local SEO title/meta/H1 fixes",)
PAGE = "https://proof.example/emergency"


def provider_strategy(value, *, scope=None, page_url=None):
    result = strategy(
        ("desired_service", SERVICE, "We want emergency plumbing jobs."),
        ("provider_work", value, f"Our existing provider handles {value}."),
    )
    fact = result["constraints"][1]
    if scope is not None:
        fact["scope"] = list(scope)
    if page_url is not None:
        fact["page_url"] = page_url
    return result


def fit(value, *, scope=None, page_url=None):
    return owner_fit_for_scope(
        confirmed(provider_strategy(value, scope=scope, page_url=page_url)),
        intervention_id="seo_improve_page:a01", scope=SEO_SCOPE,
        service=SERVICE, page_url=PAGE,
    )


@pytest.mark.parametrize("provider_scope", [
    ["local SEO title/meta/H1 fixes"],
    ["title tags, meta descriptions and headings"],
    ["Title Tags / Meta Descriptions / H1 Headings"],
    ["page titles", "meta descriptions", "headings"],
])
def test_exact_and_equivalent_tasks_are_confirmed_overlap(provider_scope):
    result = fit(SERVICE, scope=provider_scope)
    assert result.withhold
    assert result.status == "conflict"
    assert "provider" in result.reason.casefold()


@pytest.mark.parametrize("value", [
    "SEO maintenance", "website maintenance", "website content updates",
    "provider optimization bundle", "site visibility upkeep", "digital presence care",
    "search ranking repair", "growth pipeline installation", "provider restoration",
])
@pytest.mark.parametrize("provider_scope", [None, ["title tags, meta descriptions and headings"]])
def test_unknown_responsibility_is_not_a_known_other_service(value, provider_scope):
    result = fit(value, scope=provider_scope)
    assert result.withhold
    assert result.status == "unknown"
    assert "provider" in result.reason.casefold()
    assert result.question


def test_same_page_does_not_resolve_broad_maintenance_responsibility():
    result = fit("website maintenance", page_url=PAGE)
    assert result.withhold
    assert result.status == "unknown"


@pytest.mark.parametrize("value,provider_scope", [
    ("payroll/accounting support", None),
    ("payroll support", None),
    ("accounting support", None),
    ("website maintenance", ["update service photos"]),
    (SERVICE, ["photo plan"]),
    ("water heater replacement", ["title tags"]),
])
def test_known_separate_tasks_or_business_service_preserve_owner_fit(value, provider_scope):
    result = fit(value, scope=provider_scope)
    assert not result.withhold
    assert result.status == "confirmed"


def test_explicit_different_page_preserves_the_independent_task():
    result = fit("website maintenance", scope=["title tags"], page_url="https://proof.example/water-heaters")
    assert not result.withhold
    assert result.status == "confirmed"


@pytest.mark.parametrize("provider_scope", [
    ["not meta descriptions"],
    ["update service photos", "further page care"],
    ["payroll support", "website maintenance"],
])
def test_partial_or_negated_task_identity_cannot_confirm_nonoverlap(provider_scope):
    result = fit("website maintenance", scope=provider_scope)
    assert result.withhold
    assert result.status == "unknown"


@pytest.fixture
def storage(tmp_path):
    config = AppConfig(tmp_path, tmp_path / "a01.sqlite3", tmp_path / "app.log", tmp_path / "outputs")
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    yield config, factory
    factory.kw["bind"].dispose()


def owner_desired_business(session):
    """A supported normal-page SEO control with only desired-service authority."""
    lead = business(session)
    source = payload(session, lead)
    # This is real intended business content with a bounded targeting weakness.
    source["pages"][0].update(title="Plumbing services", h1=["Emergency response team"],
                              meta_description="Licensed plumbers serving Denver homes.")
    snapshot = append_research(session, lead, source)
    owner = append_owner_strategy(
        session, lead, strategy(("desired_service", SERVICE, "We want emergency plumbing jobs.")),
        owner_confirmed=True, source_text="We want emergency plumbing jobs.",
    )
    return lead, snapshot, owner


def plan(session, lead):
    return build_adaptive_sales_plan_with_context(session, lead, competitors=[])


def delivery_facts():
    fields = {key: f"Owner and reviewer confirm the exact SEO text work: {label}." for key, label in DELIVERY_FIELDS.items()}
    prerequisites = {key: {"state": "satisfied", "notes": "Owner and provider confirm this exact SEO page assignment is feasible."}
                     for key in DELIVERY_PREREQUISITES}
    return fields, prerequisites


def agreement(lead, amount):
    return dict(lead_id=lead.id, offer_date=date.today().isoformat(), business_name=lead.name,
                niche="plumber", package_name="Conversion Tune-Up", canonical_offer_id="conversion_tune_up",
                scope_summary="; ".join(SEO_SCOPE), initial_ask=amount)


def test_desired_service_only_positive_reaches_price_proof_and_ready_agreement(storage):
    config, factory = storage
    with factory() as session:
        lead, snapshot, owner = owner_desired_business(session)
        source_bytes, owner_bytes = snapshot.payload_json, owner.value_json
        sales, pricing, context = plan(session, lead)
        assert context.intervention_assessment["state"] == "recommended"
        assert context.intervention_assessment["owner_fit_status"] == "confirmed"
        assert context.scope == SEO_SCOPE
        assert sales.smart_offer.offer_id == context.offer_id == "conversion_tune_up"
        assert pricing.price_available and pricing.recommended == 350
        proof = SalesEvidenceService().build(session, lead)
        assert proof.selected_evidence["page_url"] == PAGE
        SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi", source_text="Source and selected page checked.")
        fields, prerequisites = delivery_facts()
        DeliveryPacketService().record(session, lead, context=context, fields=fields, selected_price=350,
                                       reviewer="Sammi", source_text="Owner agrees to the independent page-text work.",
                                       reviewed=True, owner_approved=True, prerequisites=prerequisites)
        assert DeliveryPacketService().build(session, lead)["ready_for_payment"]
        saved = save_offer_history(session, status="Accepted", **agreement(lead, 350))
        assert saved.status == "Accepted" and saved.canonical_offer_id == "conversion_tune_up"
        proposal = ProposalService(config).generate_proposal(session, lead, selected_price=350).read_text(encoding="utf-8")
        assert "$350" in proposal
        assert snapshot.payload_json == source_bytes and owner.value_json == owner_bytes


@pytest.mark.parametrize("value,provider_scope,expected_status", [
    (SERVICE, ["local SEO title/meta/H1 fixes"], "conflict"),
    (SERVICE, ["title tags, meta descriptions and headings"], "conflict"),
    ("SEO maintenance", None, "unknown"),
    ("website maintenance", ["title tags, meta descriptions and headings"], "unknown"),
    ("website content updates", ["local SEO title/meta/H1 fixes"], "unknown"),
    ("digital presence care", None, "unknown"),
    ("search ranking repair", None, "unknown"),
])
def test_overlap_holds_every_sales_surface_and_new_payable_progression(storage, value, provider_scope, expected_status):
    config, factory = storage
    with factory() as session:
        lead, snapshot, prior_owner = owner_desired_business(session)
        source_bytes, prior_owner_bytes = snapshot.payload_json, prior_owner.value_json
        _, pricing, _ = plan(session, lead)
        assert pricing.price_available and pricing.recommended == 350
        owner = append_owner_strategy(
            session, lead, provider_strategy(value, scope=provider_scope), owner_confirmed=True,
            source_text=f"Our existing provider handles {value}.", supersedes_assertion_id=prior_owner.id,
            correction_reason="Owner records current provider responsibility.",
        )
        owner_bytes = owner.value_json
        sales, pricing, context = plan(session, lead)
        assert context.intervention_assessment["state"] == "validate_first"
        assert context.intervention_assessment["owner_fit_status"] == expected_status
        assert not pricing.price_available and not context.price_available
        assert not context.scope and not sales.smart_offer.offer_id
        assert all(not item["scope"] and not item["offer_id"] for item in context.intervention_assessment["ranked_candidates"])
        guide = json.dumps(asdict(CallGuideService().build(session, lead, [])))
        drafts = OutreachService(SenderInfo(name="Ben")).generate_all(lead, session=session, competitors=[])
        assert set(drafts) == set(OutreachKind)
        for kind, draft in drafts.items():
            assert "$350" not in json.dumps(draft), kind
        assert "$350" not in guide
        proof = SalesEvidenceService().build(session, lead)
        assert not proof.selected_evidence
        assert "provider" in proof.owner_question.casefold()
        with pytest.raises(ValueError):
            ProposalService(config).generate_proposal(session, lead, selected_price=350)
        proposal = ProposalService(config).generate_proposal(session, lead).read_text(encoding="utf-8")
        assert "$350" not in proposal and "provider" in proposal.casefold()
        fields, prerequisites = delivery_facts()
        with pytest.raises(ValueError, match="supported scope"):
            DeliveryPacketService().record(session, lead, fields=fields, selected_price=350, reviewer="Sammi",
                                           source_text="Attempt to agree the duplicate SEO work.", reviewed=True,
                                           owner_approved=True, prerequisites=prerequisites)
        packet = DeliveryPacketService().build(session, lead)
        assert not packet["ready_for_payment"] and not packet["scope"]
        for status in ("Accepted", "Won"):
            with pytest.raises(ValueError, match="delivery packet"):
                save_offer_history(session, status=status, closed_amount=350 if status == "Won" else None,
                                   **agreement(lead, 350))
        assert snapshot.payload_json == source_bytes
        assert prior_owner.value_json == prior_owner_bytes and owner.value_json == owner_bytes


def test_provider_correction_revokes_a_previously_ready_packet_and_survives_restart(storage):
    _, factory = storage
    with factory() as session:
        lead, snapshot, prior_owner = owner_desired_business(session)
        _, pricing, context = plan(session, lead)
        SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi", source_text="Selected source checked.")
        fields, prerequisites = delivery_facts()
        old_packet = DeliveryPacketService().record(
            session, lead, context=context, fields=fields, selected_price=pricing.recommended, reviewer="Sammi",
            source_text="Owner approved the then-current separate scope.", reviewed=True, owner_approved=True, prerequisites=prerequisites,
        )
        assert DeliveryPacketService().build(session, lead)["ready_for_payment"]
        draft = save_offer_history(session, status="Draft", **agreement(lead, 350))
        old_packet_bytes, source_bytes = old_packet.value_json, snapshot.payload_json
        owner = append_owner_strategy(
            session, lead, provider_strategy("website maintenance"), owner_confirmed=True,
            source_text="Our existing provider handles website maintenance.", supersedes_assertion_id=prior_owner.id,
            correction_reason="Owner adds unresolved provider responsibility.",
        )
        assert not DeliveryPacketService().build(session, lead)["ready_for_payment"]
        for status in ("Accepted", "Won"):
            with pytest.raises(ValueError, match="delivery packet"):
                save_offer_history(session, offer_id=draft.id, status=status,
                                   closed_amount=350 if status == "Won" else None, **agreement(lead, 350))
        assert draft.status == "Draft"
        assert old_packet.value_json == old_packet_bytes and snapshot.payload_json == source_bytes
        identity = lead.id
        owner_bytes = owner.value_json
        session.commit()
    with factory() as session:
        lead = session.get(Lead, identity)
        assert project_owner_strategy(session, lead)["constraints"][1]["value"] == "website maintenance"
        assert not plan(session, lead)[1].price_available
        assert not DeliveryPacketService().build(session, lead)["ready_for_payment"]
        history = owner_strategy_history(session, identity)
        assert len(history) == 2
        assert history[-1]["source_text"] == "Our existing provider handles website maintenance."
        assert history[-1]["value_json"] == owner_bytes


@pytest.mark.parametrize("value,provider_scope,provider_page", [
    ("payroll/accounting support", None, None),
    ("water heater replacement", ["title tags"], None),
    ("website maintenance", ["photo plan"], None),
    ("website maintenance", ["title tags"], "https://proof.example/water-heaters"),
])
def test_confirmed_nonoverlap_preserves_real_paid_plan_and_proof(storage, value, provider_scope, provider_page):
    _, factory = storage
    with factory() as session:
        lead, _, prior_owner = owner_desired_business(session)
        append_owner_strategy(
            session, lead, provider_strategy(value, scope=provider_scope, page_url=provider_page), owner_confirmed=True,
            source_text=f"The owner confirms a separate assignment: {value}.", supersedes_assertion_id=prior_owner.id,
            correction_reason="Owner confirms independent responsibility.",
        )
        sales, pricing, context = plan(session, lead)
        assert context.intervention_assessment["state"] == "recommended"
        assert context.intervention_assessment["owner_fit_status"] == "confirmed"
        assert context.scope == SEO_SCOPE
        assert sales.smart_offer.offer_id == "conversion_tune_up"
        assert pricing.price_available and pricing.recommended == 350
        assert SalesEvidenceService().build(session, lead).selected_evidence["page_url"] == PAGE
