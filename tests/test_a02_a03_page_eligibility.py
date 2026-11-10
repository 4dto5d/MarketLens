"""Page eligibility applies to fetched and supplied facts before paid reasoning."""
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from test_h5_evidence_validity import capture
from test_owner_fit_corrections import strategy
from test_sales_delivery_corrections import business, payload
from test_sales_delivery_corrections import storage as storage_fixture
from test_seo_page_analysis import extract_page_analysis, snapshot

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.repositories import save_audit
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.owner_strategy_service import append_owner_strategy
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.seo_research_service import append_research, project_seo_research, research_history
from local_presence_miner.time_utils import utc_now

LOADING_BODIES = ["Please wait.", "Please wait while the site loads."]

ABNORMAL = [
    ("Account Suspended | Hosting Control Panel", "This account has been suspended", "Contact your hosting provider for more information."),
    ("Checking your browser before accessing the website", "Please wait while we verify your browser",
     "This security check is automatic. You will be redirected when verification completes."),
    ("Site temporarily unavailable", "We are performing scheduled maintenance", "Please try again later."),
    ("Domain for sale | Domain marketplace", "This domain is for sale", "Buy this domain."),
    ("Default web server page", "Welcome to the nginx page", "This server has not been configured."),
    ("Application error", "Something went wrong", "An unexpected error occurred. Please try again later."),
]

@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    config, factory = storage_fixture.__wrapped__(tmp_path)
    yield config, factory
    factory.kw["bind"].dispose()

def html(title, heading, body):
    return f"<title>{title}</title><main><h1>{heading}</h1><p>{body}</p></main>"

def assert_withheld(session, lead, config):
    plan, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
    assert not price.price_available and price.recommended is None and not context.scope
    assert not CallGuideService().build(session, lead, []).recommended_ask
    drafts = OutreachService(SenderInfo(name="Ben")).generate_all(lead, session=session, adaptive_plan=plan, pricing=price)
    assert "$350" not in str(drafts)
    with pytest.raises(ValueError, match="paid proposal"):
        ProposalService(config).generate_proposal(session, lead, selected_price=350)
    assert not DeliveryPacketService().build(session, lead)["ready_for_payment"]

@pytest.mark.parametrize("title,heading,body", ABNORMAL)
@pytest.mark.parametrize("path", ["fetched", "imported"])
def test_explicit_nonbusiness_capture_cannot_become_paid_scope(storage, path, title, heading, body):
    config, factory = storage
    with factory() as session:
        lead = business(session, audit=path == "imported")
        if path == "fetched":
            lead.website = "https://fixture.example.com/"
            audit = capture(html(title, heading, body))
            save_audit(session, lead.id, audit)
            session.flush()
            assert json.loads(audit.evidence["website_response_v1"])["state"] != "normal"
        else:
            data = payload(session, lead)
            data["pages"][0].update(title=title, h1=[heading], word_count=12)
            record = append_research(session, lead, data)
            original = record.payload_json
            projection = project_seo_research(session, lead)
            eligibility = projection["opportunities"][0]["page_eligibility"]
            assert eligibility[0]["state"] != "normal" and eligibility[0]["reason"]
            assert eligibility[0]["observed_at"] and eligibility[0]["version"]
            assert record.payload_json == original
        assert_withheld(session, lead, config)

@pytest.mark.parametrize("body", ["", "Loading...", "Please wait."])
def test_uncertain_fetched_shell_has_no_ordinary_diagnosis(storage, body):
    config, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        audit = capture(f"<main><p>{body}</p></main>")
        save_audit(session, lead.id, audit)
        session.flush()
        assert not audit.checks
        assert_withheld(session, lead, config)

@pytest.mark.parametrize("count", [None, 0])
def test_supplied_empty_or_unknown_content_is_not_a_normal_target_page(storage, count):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        data["pages"][0].update(title="", h1=[], meta_description="", word_count=count)
        append_research(session, lead, data)
        assert_withheld(session, lead, config)

def test_supplied_loading_shell_is_uncertain_even_with_positive_word_count(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        data["pages"][0].update(title="Loading...", h1=["Please wait."], meta_description="", word_count=4)
        append_research(session, lead, data)
        assert_withheld(session, lead, config)

@pytest.mark.parametrize("wording", [
    "Customer account support and plumbing maintenance are available.",
    "We repair suspended ceilings and provide plumbing services.",
    "Verify our license and contact us about your home maintenance.",
    "Website maintenance is one subject we discuss with our local business customers.",
])
def test_legitimate_business_words_do_not_invalidate_content(storage, wording):
    _, factory = storage
    audit = capture(html("Local Plumbing", "Plumbing services", "Licensed repairs for local homeowners. " + wording))
    assert json.loads(audit.evidence["website_response_v1"])["state"] == "normal"
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        save_audit(session, lead.id, audit)
        session.flush()
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert price.price_available and context.scope == ("mobile call/quote button", "homepage CTA rewrite")

def test_normal_supplied_targeting_weakness_remains_sellable_and_auditable(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert price.price_available and context.scope == ("local SEO title/meta/H1 fixes",)
        observation = project_seo_research(session, lead)["opportunities"][0]["page_eligibility"][0]
        assert observation["state"] == "normal" and observation["basis"] == "structured_page_facts"
        assert "ownership" in observation["reason"]

def test_equivalent_live_and_imported_abnormal_facts_have_same_state():
    for title, heading, body in ABNORMAL:
        from local_presence_miner.domain.website_evidence import classify_page_facts

        facts, details = extract_page_analysis(snapshot(html(title, heading, body)))
        assert classify_page_facts(facts)["state"] == details["response_validity"]["state"] == "non_normal"

@pytest.mark.parametrize("headings", [None, "Welcome", [None], {"h1": "Welcome"}])
def test_malformed_historical_page_headings_do_not_certify_normal_or_crash(headings):
    from local_presence_miner.domain.website_evidence import classify_page_facts

    assert classify_page_facts({"url": "https://proof.example/", "status_code": 200, "title": "Home",
                                "h1": headings, "word_count": 300})["state"] == "uncertain"

@pytest.mark.parametrize("status,count", [("200", 300), (True, 300), (None, 300), (200, float("inf")), (200, float("nan"))])
def test_malformed_transport_or_content_count_cannot_certify_normal(status, count):
    from local_presence_miner.domain.website_evidence import classify_page_facts

    assert classify_page_facts({"url": "https://proof.example/", "status_code": status, "title": "Home",
                                "h1": ["Plumbing services"], "word_count": count})["state"] == "uncertain"

def test_body_only_provider_status_is_not_a_content_repair(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        audit = capture(html("Local business", "We'll be back soon", "This website has been suspended. Contact your hosting provider for restoration."))
        save_audit(session, lead.id, audit)
        session.flush()
        assert_withheld(session, lead, config)

def test_new_abnormal_observation_does_not_rewrite_older_normal_history(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        old = append_research(session, lead, data)
        before = old.payload_json
        data = deepcopy(data)
        data["observed_at"] = (utc_now() + timedelta(microseconds=1)).isoformat()
        data["pages"][0].update(title="Account Suspended", h1=["Account Suspended"])
        new = append_research(session, lead, data)
        assert new.id != old.id and old.payload_json == before and len(research_history(session, lead.id)) == 2
        assert_withheld(session, lead, config)

def test_provider_and_abnormal_page_both_prevent_sale(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        owner = strategy(("provider_work", "website/SEO maintenance", "Our current provider handles the website and SEO maintenance."))
        append_owner_strategy(session, lead, owner, owner_confirmed=True, source_text=owner["constraints"][0]["original_wording"])
        data = payload(session, lead)
        data["pages"][0].update(title="Account Suspended | Hosting Control Panel", h1=["This account has been suspended"])
        append_research(session, lead, data)
        assert_withheld(session, lead, config)


def loading_html(body):
    return ('<html><head><title>Local Plumbing</title><script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"Service","serviceType":"emergency plumbing"}'
            f'</script></head><body><main><h1>Loading...</h1><p>{body}</p></main></body></html>')


@pytest.mark.parametrize("body", LOADING_BODIES)
def test_same_url_loading_facts_cannot_upgrade_fetched_uncertainty(body):
    from local_presence_miner.domain.website_evidence import classify_page_facts

    facts, detail = extract_page_analysis(snapshot(loading_html(body), "https://proof.example/emergency"))
    before = deepcopy(facts)
    assert detail["response_validity"]["state"] == "uncertain"
    derived = classify_page_facts(facts)
    assert derived["state"] == "uncertain" and derived["indicators"]
    assert facts == before and facts["services"] == ["emergency plumbing"]


@pytest.mark.parametrize("body", LOADING_BODIES)
@pytest.mark.parametrize("path", ["fetched", "imported"])
def test_branded_loading_page_never_supports_ordinary_paid_scope(storage, path, body):
    config, factory = storage
    with factory() as session:
        lead = business(session, audit=path == "imported")
        if path == "fetched":
            lead.website = "https://fixture.example.com/"
            audit = capture(loading_html(body))
            save_audit(session, lead.id, audit)
            session.flush()
            assert not audit.checks
        else:
            data = payload(session, lead)
            facts, _ = extract_page_analysis(snapshot(loading_html(body), data["pages"][0]["url"]))
            data["pages"] = [{**facts, "source_ref": "captured:loading", "observed_at": data["observed_at"]}]
            append_research(session, lead, data)
        assert_withheld(session, lead, config)


@pytest.mark.parametrize("body", LOADING_BODIES)
def test_imported_loading_page_retains_provenance_and_hold_after_restart(storage, body):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        facts, _ = extract_page_analysis(snapshot(loading_html(body), data["pages"][0]["url"]))
        data["pages"] = [{**facts, "source_ref": "captured:loading", "observed_at": data["observed_at"]}]
        record = append_research(session, lead, data)
        original = (record.id, record.observed_at, record.payload_json)
        identity = lead.id
        session.commit()
    with factory() as session:
        from local_presence_miner.database.schema import Lead, SEOResearchSnapshot

        lead = session.get(Lead, identity)
        persisted = session.get(SEOResearchSnapshot, original[0])
        assert (persisted.id, persisted.observed_at, persisted.payload_json) == original
        observation = project_seo_research(session, lead)["opportunities"][0]["page_eligibility"][0]
        assert observation["state"] == "uncertain" and observation["source_ref"] == "captured:loading"
        assert observation["observed_at"] and observation["reason"] and observation["version"]
        assert_withheld(session, lead, config)


@pytest.mark.parametrize("text", [
    "Loading... Please wait while the site loads.",
    "LOADING… PLEASE WAIT WHILE THE WEBSITE IS LOADING!",
    "Loading our page. Please wait while we load the content.",
    "Please wait while this page loads.",
    "Loading\nPlease\t wait. Redirecting...",
])
def test_complete_loading_status_compositions_are_uncertain(text):
    from local_presence_miner.domain.website_evidence import classify_response

    assert classify_response("https://proof.example/", 200, "Plumbing", visible_text=text)["state"] == "uncertain"


@pytest.mark.parametrize("title,heading,body", [
    ("Local Plumbing", "Loading dock plumbing repairs", "Licensed repairs for local businesses. Contact us about your loading dock."),
    ("Local Plumbing", "Plumbing services", "Please wait for our technician to inspect your pipes before booking repairs."),
    ("Local Plumbing", "Plumbing services", "Our website explains the repairs we offer while a booking widget is loading."),
])
def test_real_business_prose_and_loading_related_services_remain_eligible(storage, title, heading, body):
    from local_presence_miner.domain.website_evidence import classify_page_facts

    _, factory = storage
    content = html(title, heading, body)
    facts, details = extract_page_analysis(snapshot(content))
    assert details["response_validity"]["state"] == classify_page_facts(facts)["state"] == "normal"
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        save_audit(session, lead.id, capture(content))
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert price.price_available and "mobile call/quote button" in context.scope


@pytest.mark.parametrize("count", [3, 400])
def test_branded_loading_heading_cannot_be_certified_by_count_or_schema(count):
    from local_presence_miner.domain.website_evidence import classify_page_facts

    facts = {"url": "https://proof.example/", "status_code": 200, "title": "Local Plumbing",
             "h1": ["Loading..."], "word_count": count, "services": ["emergency plumbing"], "schema_types": ["Service"]}
    assert classify_page_facts(facts)["state"] == "uncertain"


@pytest.mark.parametrize("version", [1, 2])
def test_old_normal_loading_capture_is_sanitized_without_rewriting(storage, version):
    from local_presence_miner.database.repositories import audit_from_record
    from local_presence_miner.domain.scoring import website_evidence_state

    config, factory = storage
    with factory() as session:
        lead = business(session)
        record = lead.audit
        facts, _ = extract_page_analysis(snapshot(loading_html(LOADING_BODIES[1]), lead.website))
        evidence = {"website_response_v1": json.dumps({"version": version, "state": "normal", "url": lead.website,
                    "status_code": 200, "indicators": [], "reason": "Old capture"}), "seo_pages_v1": json.dumps([facts])}
        record.evidence_json = json.dumps(evidence)
        session.flush()
        original = (record.evidence_json, record.checks_json, record.created_at)
        projected = audit_from_record(record)
        assert website_evidence_state(projected) == "uncertain" and not projected.checks
        assert_withheld(session, lead, config)
        assert (record.evidence_json, record.checks_json, record.created_at) == original


def test_old_normal_loading_page_details_cannot_bypass_shared_projection():
    from local_presence_miner.services.seo_page_analysis import analyze_page_sample

    facts, detail = extract_page_analysis(snapshot(loading_html(LOADING_BODIES[1])))
    detail["response_validity"].update(version=2, state="normal", indicators=[], reason="Old interpretation")
    original = deepcopy((facts, detail))
    assert {row["type"] for row in analyze_page_sample([facts], [detail])} == {"response_validation"}
    assert (facts, detail) == original


@pytest.mark.parametrize("body", LOADING_BODIES)
def test_loading_capture_does_not_disable_independent_hours_correction(storage, body):
    _, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        lead.has_hours = False
        save_audit(session, lead.id, capture(loading_html(body)))
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert price.price_available and context.offer_id == "google_presence_cleanup"
        assert context.scope == ("hours and contact cleanup checklist",)


@pytest.mark.parametrize("headings", [[], ["Local Plumbing"], ["Local Plumbing", "Loading..."]])
@pytest.mark.parametrize("count", [3, 400])
def test_l01_ambiguous_brand_facts_do_not_sell_even_with_large_count(storage, headings, count):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        data["pages"][0].update(title="Local Plumbing", h1=headings, word_count=count)
        row = append_research(session, lead, data)
        before = row.payload_json
        assert_withheld(session, lead, config)
        assert row.payload_json == before


@pytest.mark.parametrize("heading", ["", "<h1>Local Plumbing</h1>"])
def test_l01_short_real_capture_with_missing_or_brand_heading_is_still_useful(storage, heading):
    from local_presence_miner.database.repositories import audit_from_record
    from local_presence_miner.domain.scoring import website_evidence_state

    _, factory = storage
    content = f"<title>Local Plumbing</title><main>{heading}<p>We repair burst pipes.</p></main>"
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        row = save_audit(session, lead.id, capture(content))
        original = row.evidence_json
        assert website_evidence_state(audit_from_record(row)) == "observed"
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert price.price_available and "mobile call/quote button" in context.scope
        assert row.evidence_json == original


@pytest.mark.parametrize("headings", [[], ["Local Plumbing"]])
def test_l01_static_description_cannot_rescue_missing_or_brand_heading_import(storage, headings):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        data["pages"][0].update(title="Local Plumbing", h1=headings, word_count=3,
                                meta_description="Licensed plumbers repair pipes for local homeowners.")
        append_research(session, lead, data)
        assert_withheld(session, lead, config)


def test_l01_short_descriptive_heading_is_not_blocked_by_a_count_threshold(storage):
    from local_presence_miner.domain.website_evidence import classify_page_facts

    _, factory = storage
    content = ('<title>Local Plumbing</title><main><h1>Repair services</h1><p>Plumbing.</p></main>'
               '<script type="application/ld+json">{"@context":"https://schema.org",'
               '"@type":"Service","serviceType":"emergency plumbing"}</script>')
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        facts, detail = extract_page_analysis(snapshot(content, data["pages"][0]["url"]))
        assert facts["word_count"] == 3
        assert detail["response_validity"]["state"] == classify_page_facts(facts)["state"] == "normal"
        data["pages"] = [{**facts, "observed_at": data["observed_at"], "source_ref": "captured:short-real-page"}]
        append_research(session, lead, data)
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert price.price_available and context.scope == ("local SEO title/meta/H1 fixes",)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
def test_l01_old_brand_only_normal_capture_is_not_recertified(storage, version):
    from local_presence_miner.database.repositories import audit_from_record
    from local_presence_miner.domain.scoring import website_evidence_state

    config, factory = storage
    with factory() as session:
        lead = business(session)
        row = lead.audit
        facts, _ = extract_page_analysis(snapshot(html("Local Plumbing", "Local Plumbing", LOADING_BODIES[1]), lead.website))
        row.evidence_json = json.dumps({"seo_pages_v1": json.dumps([facts]),
            "website_response_v1": json.dumps({"version": version, "state": "normal", "url": lead.website,
                "status_code": 200, "indicators": [], "reason": "Stored prior interpretation"})})
        session.flush()
        before = (row.evidence_json, row.checks_json, row.created_at)
        assert website_evidence_state(audit_from_record(row)) == "uncertain"
        assert_withheld(session, lead, config)
        assert (row.evidence_json, row.checks_json, row.created_at) == before


@pytest.mark.parametrize("change", ["old_version", "different_url", "shell_counterevidence", "empty_count"])
def test_l01_normal_detail_cannot_override_explicit_shell_or_invalid_proof(change):
    from local_presence_miner.services.seo_page_analysis import analytical_page_sample

    facts, detail = extract_page_analysis(snapshot(html("Local Plumbing", "Local Plumbing", "We repair pipes.")))
    if change == "old_version":
        detail["response_validity"]["version"] = 3
    elif change == "different_url":
        detail["response_validity"]["url"] += "other"
    elif change == "empty_count":
        facts["word_count"] = 0
    else:
        facts["h1"] = ["Loading..."]
    before = deepcopy((facts, detail))
    assert analytical_page_sample([facts], [detail])[0]["response_validity"]["state"] == "uncertain"
    assert (facts, detail) == before


def test_l01_schema_label_equal_to_brand_does_not_certify_import(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        data["pages"][0].update(title="Emergency Plumbing", h1=["Emergency Plumbing"], word_count=9)
        append_research(session, lead, data)
        assert_withheld(session, lead, config)


@pytest.mark.parametrize("heading", ["Local Plumbing", "Welcome", "Welcome to our website", "Emergency plumbing services"])
@pytest.mark.parametrize("body", ["", "Loading... Please wait while the site loads."])
def test_l01_headings_and_metadata_are_not_current_body_proof(heading, body):
    content = ('<title>Local Plumbing</title><meta name="description" content="Licensed plumbers repair pipes.">'
               '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Service",'
               '"serviceType":"emergency plumbing"}</script>' + html("Local Plumbing", heading, body))
    _, details = extract_page_analysis(snapshot(content))
    assert details["response_validity"]["state"] == "uncertain"


@pytest.mark.parametrize("headings", [[], ["Local Plumbing"], ["Welcome"], ["Welcome to our website"]])
@pytest.mark.parametrize("count", [8, 500])
def test_l01_incidental_import_cannot_be_rescued_by_static_description(storage, headings, count):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        data["pages"][0].update(title="Local Plumbing", h1=headings, word_count=count,
                                meta_description="Licensed plumbers repair pipes for local homeowners.")
        row = append_research(session, lead, data)
        original = (row.payload_json, row.observed_at)
        assert_withheld(session, lead, config)
        assert (row.payload_json, row.observed_at) == original


@pytest.mark.parametrize("heading", ["Repair services", "Loading dock repairs"])
def test_l01_heading_only_count_does_not_establish_additional_content(heading):
    from local_presence_miner.domain.website_evidence import classify_page_facts

    facts, details = extract_page_analysis(snapshot(html("Local Plumbing", heading, "")))
    assert details["response_validity"]["state"] == classify_page_facts(facts)["state"] == "uncertain"


def test_l01_version_four_generic_capture_cannot_certify_current_content(storage):
    from local_presence_miner.database.repositories import audit_from_record
    from local_presence_miner.domain.scoring import website_evidence_state

    config, factory = storage
    with factory() as session:
        lead = business(session)
        row = lead.audit
        facts, _ = extract_page_analysis(snapshot(html("Local Plumbing", "Welcome", "Loading..."), lead.website))
        row.evidence_json = json.dumps({"seo_pages_v1": json.dumps([facts]),
            "website_response_v1": json.dumps({"version": 4, "state": "normal", "url": lead.website,
                "status_code": 200, "indicators": [], "reason": "Stored original version-four interpretation"})})
        session.flush()
        original = (row.evidence_json, row.created_at, row.checks_json)
        assert website_evidence_state(audit_from_record(row)) == "uncertain"
        assert_withheld(session, lead, config)
        assert (row.evidence_json, row.created_at, row.checks_json) == original


@pytest.mark.parametrize("decoration", ['<a href="tel:5550100">Call for repairs</a>', '<h2>Emergency plumbing repairs</h2>',
                                        '<button>Book our repair service</button>'])
def test_l01_isolated_controls_or_subheadings_cannot_rescue_loading(decoration):
    _, details = extract_page_analysis(snapshot('<title>Local Plumbing</title><main>'
        '<h1>Welcome</h1><p>Loading... Please wait while the site loads.</p>' + decoration + '</main>'))
    assert details["response_validity"]["state"] == "uncertain"


@pytest.mark.parametrize("body", [
    "Loading (75%)",
    "Loading [3/10]",
    "Loading — 75% complete",
    "Loading : [3 of 10 resources loaded]",
    "Please wait while we prepare your page",
    "Please wait while we assemble your content",
    "Loading... 0% complete. Please wait while the site loads.",
    "Loading... 99.5% complete. Please wait while the site loads.",
    "Loading... 3 of 10 resources loaded. Please wait.",
    "Loading... Almost ready. Please wait.",
    "Loading... A few moments remaining. Please wait.",
    "Loading... Call us for help.",
    "Loading... We will help shortly.",
    "Loading... We will provide information soon.",
])
def test_l01_loading_progress_variants_withhold_actual_consumers(storage, body):
    from local_presence_miner.database.schema import Lead

    config, factory = storage
    content = html("Local Plumbing", "Local Plumbing", body) + '<button>Book our repair service</button>'
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        captured = capture(content)
        assert json.loads(captured.evidence["website_response_v1"])["state"] == "uncertain"
        row = save_audit(session, lead.id, captured)
        session.flush()
        assert_withheld(session, lead, config)
        raw = (row.evidence_json, row.created_at.replace(tzinfo=None), row.checks_json)
        identity = lead.id
        session.commit()
    with factory() as session:
        lead = session.get(Lead, identity)
        assert_withheld(session, lead, config)
        assert (lead.audit.evidence_json, lead.audit.created_at.replace(tzinfo=None), lead.audit.checks_json) == raw


@pytest.mark.parametrize("body", [
    "Loading... 75% complete. We repair burst pipes for local homeowners.",
    "Loading... Pool maintenance plans available. Call for weekly service.",
])
def test_l01_status_does_not_poison_independent_descriptive_body(storage, body):
    from local_presence_miner.database.repositories import audit_from_record
    from local_presence_miner.domain.scoring import website_evidence_state

    _, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        row = save_audit(session, lead.id, capture(html("Local Plumbing", "Local Plumbing", body)))
        assert website_evidence_state(audit_from_record(row)) == "observed"
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert price.price_available and "mobile call/quote button" in context.scope


@pytest.mark.parametrize("proof", [None, {"kind": "visible_body", "text": "Loading... 75% complete."},
                                   {"kind": "static_metadata", "text": "We repair burst pipes."}])
def test_l01_current_normal_label_requires_body_proof_not_its_reason(storage, proof):
    from local_presence_miner.database.repositories import audit_from_record
    from local_presence_miner.domain.scoring import website_evidence_state

    config, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = "https://fixture.example.com/"
        captured = capture(html("Local Plumbing", "Local Plumbing", "We repair burst pipes."))
        value = json.loads(captured.evidence["website_response_v1"])
        assert value["content_proof"]["text"] == "we repair burst pipes"
        value["content_proof"] = proof
        captured.evidence["website_response_v1"] = json.dumps(value)
        row = save_audit(session, lead.id, captured)
        original = row.evidence_json
        assert website_evidence_state(audit_from_record(row)) == "uncertain"
        assert_withheld(session, lead, config)
        assert row.evidence_json == original


@pytest.mark.parametrize("heading", ["Loading (75%)", "Loading [3/10]", "Loading — 75% complete",
                                     "Please wait while we prepare your page"])
def test_l01_imported_status_heading_preserves_uncertainty(storage, heading):
    from local_presence_miner.database.schema import Lead

    config, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        content = html("Local Plumbing", heading, "") + '<button>Book our repair service</button>'
        facts, _ = extract_page_analysis(snapshot(content, data["pages"][0]["url"]))
        data["pages"] = [{**facts, "observed_at": data["observed_at"], "source_ref": "fixture:status-heading"}]
        row = append_research(session, lead, data)
        original = (row.payload_json, row.observed_at)
        assert_withheld(session, lead, config)
        identity, record_id = lead.id, row.id
        session.commit()
    with factory() as session:
        lead = session.get(Lead, identity)
        assert_withheld(session, lead, config)
        from local_presence_miner.database.schema import SEOResearchSnapshot

        row = session.get(SEOResearchSnapshot, record_id)
        assert (row.payload_json, row.observed_at) == original


@pytest.mark.parametrize("body", ["Loading dock repairs for local businesses.",
                                  "We repair loading docks and offer maintenance services.",
                                  "Loading (75%). We repair leaks."])
def test_l01_loading_language_with_business_content_stays_eligible(body):
    _, details = extract_page_analysis(snapshot(html("Local Plumbing", "Local Plumbing", body)))
    assert details["response_validity"]["state"] == "normal"
