"""Provider overlap regressions through owner decisions and real sales surfaces."""

import json
from dataclasses import asdict, replace

import pytest
from test_owner_fit_corrections import HEALTHY, confirmed, evidence, stored_plan, strategy
from test_seo_research_integration import business, sample_payload

from local_presence_miner.config import AppConfig, SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.domain.intervention_assessment import assess_interventions
from local_presence_miner.domain.owner_strategy import owner_fit_for_scope
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.owner_strategy_service import append_owner_strategy
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.seo_research_service import append_research


def provider(*, value="emergency plumbing", scope=None, page_url=None):
    result = strategy(("provider_work", value, "The owner confirms the provider is already doing this work."))
    if scope is not None:
        result["constraints"][0]["scope"] = scope
    if page_url is not None:
        result["constraints"][0]["page_url"] = page_url
    return result


@pytest.mark.parametrize("scope", [
    ["local SEO title/meta/H1 fixes"],
    ["title tags, meta descriptions, and H1"],
    ["TITLE TAGS / META DESCRIPTIONS / H1"],
    ["title tags", "meta descriptions", "H1 headings"],
    ["meta descriptions"],
])
def test_equivalent_existing_seo_tasks_never_become_new_paid_work(scope):
    result = assess_interventions(evidence(owner_strategy=confirmed(provider(scope=scope))))
    assert result.state == "validate_first"
    assert not result.recommended_offer_id
    assert result.owner_fit_status == "conflict"
    assert "provider" in result.owner_fit_reason
    assert all(not item.offer_id and not item.scope for item in result.ranked_candidates)


def test_contact_repair_preserves_audited_page_and_holds_existing_provider_work():
    current = evidence(owner_strategy=confirmed(provider(
        value="homepage contact repair", page_url="https://owner-fit.example/",
        scope=["mobile call/quote button", "homepage CTA rewrite"],
    )))
    current = replace(current, website_checks={**HEALTHY, "sitewide_contact_path": False, "tap_to_call": False})
    result = assess_interventions(current)
    assert result.ranked_candidates[0].selected_page_url == current.website_url
    assert result.state == "validate_first"
    assert result.owner_fit_status == "conflict"
    assert all(not item.offer_id and not item.scope for item in result.ranked_candidates)


def test_unresolved_provider_scope_on_selected_service_requires_clarification():
    result = assess_interventions(evidence(owner_strategy=confirmed(provider(scope=["provider optimization bundle"]))))
    assert result.state == "validate_first"
    assert result.owner_fit_status == "unknown"
    assert result.owner_validation_question
    assert all(not item.scope for item in result.ranked_candidates)


@pytest.mark.parametrize("scope", [["update service photos"], ["photo plan"]])
def test_known_separate_photography_work_does_not_suspend_supported_seo(scope):
    result = assess_interventions(evidence(owner_strategy=confirmed(provider(scope=scope))))
    assert result.state == "recommended"
    assert result.recommended_offer_id == "conversion_tune_up"


def test_known_other_service_remains_a_paid_supported_opportunity():
    result = assess_interventions(evidence(owner_strategy=confirmed(provider(value="water heater replacement"))))
    assert result.state == "recommended"
    assert result.ranked_candidates[0].selected_service == "emergency plumbing"


@pytest.mark.parametrize("value", ["website work", "title tags, meta descriptions, and H1"])
def test_work_descriptor_is_not_misread_as_an_unrelated_business_service(value):
    result = assess_interventions(evidence(owner_strategy=confirmed(provider(value=value, scope=["meta descriptions"]))))
    assert result.state == "validate_first"
    assert result.owner_fit_status == "unknown"


@pytest.mark.parametrize("provider_page", ["https://OWNER-FIT.example/emergency/", "http://owner-fit.example/emergency",
                                           "https://owner-fit.example:443/emergency#details"])
def test_page_spelling_cannot_authorize_duplicate_work(provider_page):
    fit = owner_fit_for_scope(
        confirmed(provider(page_url=provider_page, scope=["meta descriptions"])),
        intervention_id="seo_improve_page:selected", scope=("local SEO title/meta/H1 fixes",),
        service="emergency plumbing", page_url="https://owner-fit.example/emergency",
    )
    assert fit.withhold and fit.status == "conflict"


@pytest.mark.parametrize("page_url", ["", "https://owner-fit.example/emergency?utm_source=profile"])
def test_unknown_or_ambiguous_selected_page_needs_provider_validation(page_url):
    fit = owner_fit_for_scope(
        confirmed(provider(page_url="https://owner-fit.example/emergency", scope=["meta descriptions"])),
        intervention_id="seo_improve_page:selected", scope=("local SEO title/meta/H1 fixes",),
        service="emergency plumbing", page_url=page_url,
    )
    assert fit.withhold and fit.status == "unknown"


def test_explicit_separate_page_preserves_supported_paid_task():
    fit = owner_fit_for_scope(
        confirmed(provider(page_url="https://owner-fit.example/water-heaters", scope=["meta descriptions"])),
        intervention_id="seo_improve_page:selected", scope=("local SEO title/meta/H1 fixes",),
        service="emergency plumbing", page_url="https://owner-fit.example/emergency",
    )
    assert not fit.withhold and fit.status == "confirmed"


def test_negated_or_unrecognized_scope_does_not_authorize_optimistic_nonoverlap():
    for scope in (["not meta descriptions"], ["update service photos", "additional optimization"]):
        result = assess_interventions(evidence(owner_strategy=confirmed(provider(scope=scope))))
        assert result.state == "validate_first"
        assert result.owner_fit_status == "unknown"


@pytest.fixture
def storage(tmp_path):
    config = AppConfig(tmp_path, tmp_path / "provider.sqlite3", tmp_path / "app.log", tmp_path)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    return config, factory


@pytest.mark.parametrize("kind", ["contact", "contact-alias", "seo"])
def test_duplicate_scope_withholds_price_and_all_downstream_sales_surfaces(storage, kind):
    config, factory = storage
    with factory() as session:
        lead, audit = business(session)
        if kind.startswith("contact"):
            audit.checks_json = json.dumps({**HEALTHY, "sitewide_contact_path": False, "tap_to_call": False})
            owner = provider(value="homepage contact repair", page_url=lead.website,
                             scope=["click-to-call button", "homepage CTA"] if kind == "contact-alias" else
                                   ["mobile call/quote button", "homepage CTA rewrite"])
        else:
            append_research(session, lead, sample_payload(session, lead))
            owner = provider(scope=["title tags, meta descriptions, and H1"])
        assert stored_plan(session, lead)[1].price_available
        row = append_owner_strategy(session, lead, owner, owner_confirmed=True,
                                    source_text="The owner confirms the provider is already doing this work.")
        original = row.value_json
        _, price, context = stored_plan(session, lead)
        assert not price.price_available
        assert context.intervention_assessment["state"] == "validate_first"
        assert not context.scope
        assert context.intervention_assessment["owner_fit_status"] == "conflict"
        guide = json.dumps(asdict(CallGuideService().build(session, lead, [])))
        drafts = OutreachService(SenderInfo(name="Ben", business_name="Synthetic Agency")).generate_all(
            lead, session=session, competitors=[])
        outbound = json.dumps({str(key): value for key, value in drafts.items()})
        assert "$350" not in guide and "$350" not in outbound
        assert "provider" in (guide + outbound).casefold()
        with pytest.raises(ValueError):
            ProposalService(config).generate_proposal(session, lead, selected_price=350)
        proposal = ProposalService(config).generate_proposal(session, lead)
        body = proposal.read_text(encoding="utf-8")
        assert "$350" not in body
        assert "provider" in body.casefold()
        assert row.value_json == original


def test_equivalent_wording_counterfactual_cannot_reopen_paid_scope(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        append_research(session, lead, sample_payload(session, lead))
        previous = None
        recorded = []
        for scope in (["local SEO title/meta/H1 fixes"], ["title tags, meta descriptions, and H1"],
                      ["local SEO title/meta/H1 fixes"]):
            previous = append_owner_strategy(
                session, lead, provider(scope=scope), owner_confirmed=True,
                source_text="The provider owns these same title, description and heading edits.",
                supersedes_assertion_id=previous.id if previous else None,
                correction_reason="Equivalent wording, no change to the agreed work." if previous else "",
            )
            _, pricing, context = stored_plan(session, lead)
            assert not pricing.price_available
            assert context.intervention_assessment["state"] == "validate_first"
            recorded.append((previous, previous.value_json))
        assert previous is not None
        append_owner_strategy(
            session, lead, provider(scope=["update service photos"]), owner_confirmed=True,
            source_text="The owner clarifies that the provider will update photos only, leaving SEO edits separate.",
            supersedes_assertion_id=previous.id, correction_reason="Owner confirms a materially separate provider assignment.",
        )
        _, pricing, context = stored_plan(session, lead)
        assert pricing.price_available
        assert context.scope == ("local SEO title/meta/H1 fixes",)
        assert all(row.value_json == original for row, original in recorded)
