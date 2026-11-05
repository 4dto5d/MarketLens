"""H5 captured failures and bounded response/page-identity counterfactuals."""

import json
from copy import deepcopy

import pytest
from test_sales_delivery_corrections import business, payload
from test_sales_delivery_corrections import storage as storage_fixture
from test_seo_page_analysis import FixtureTransport, auditor, response, snapshot

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.repositories import audit_from_record, profile_from_lead, save_audit
from local_presence_miner.domain.scoring import score_lead, website_evidence_state
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.sales_evidence_service import USAGE_OWNER_COPIED, SalesEvidenceService
from local_presence_miner.services.seo_page_analysis import analyze_page_sample, extract_page_analysis
from local_presence_miner.services.seo_research_service import append_research, research_history

HOME = "https://fixture.example.com/"
NORMAL = "<title>Local Plumbing</title><h1>Plumbing services</h1><p>Licensed plumbing repairs for local homes and businesses.</p>"
ABNORMAL = [
    ("<title>Account Suspended</title><h1>Account Suspended</h1><p>Contact your hosting provider.</p>", "non_normal"),
    ("<title>Domain for sale</title><h1>This domain is for sale</h1>", "non_normal"),
    ("<title>Coming soon</title><h1>Website under construction</h1>", "non_normal"),
    ("<title>Just a moment...</title><div id='cf-challenge-running'>Checking your browser</div>", "non_normal"),
    ("<title>Service Unavailable</title><h1>Service Unavailable</h1>", "non_normal"),
    ("<div id='root'></div><script src='/app.js'></script>", "uncertain"),
]


@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    return storage_fixture.__wrapped__(tmp_path)


def capture(html, *, final=HOME, status=200):
    reply = response(final, html)
    reply.status_code = status
    return auditor(FixtureTransport({HOME: reply}), max_pages=1).audit(HOME)


@pytest.mark.parametrize("html,expected", ABNORMAL)
def test_abnormal_success_is_explicitly_ineligible_and_retains_source(html, expected):
    audit = capture(html)
    validity = json.loads(audit.evidence["website_response_v1"])
    assert validity["state"] == expected
    assert validity["url"] == HOME and validity["status_code"] == 200
    assert validity["indicators"]
    assert not audit.checks
    diagnostics = json.loads(audit.evidence["seo_page_diagnostics_v1"])
    assert not {"missing_metadata", "duplicate_title", "possible_target_overlap"} & {d["type"] for d in diagnostics}


@pytest.mark.parametrize("html,expected", ABNORMAL)
def test_ineligible_capture_cannot_resurrect_content_offer_or_price(storage, html, expected):
    config, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = HOME
        save_audit(session, lead.id, capture(html))
        session.flush()
        session.expire(lead, ["audit"])
        # An old compatible SEO checkpoint must not turn the invalid current
        # capture back into a normal content-based priced offer.
        append_research(session, lead, payload(session, lead), attach_current_pages=False)
        plan, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert not context.offer_id and not context.scope and not price.price_available
        assert price.recommended is None
        assert context.intervention_assessment["state"] == "validate_first"
        guide = CallGuideService().build(session, lead, [])
        assert guide.recommended_ask is None
        drafts = OutreachService(SenderInfo(name="Ben")).generate_all(lead, session=session, adaptive_plan=plan, pricing=price)
        assert "$350" not in " ".join(body for _, body in drafts.values())
        proposal = ProposalService(config).generate_proposal(session, lead).read_text(encoding="utf-8")
        assert "mobile call/quote button" not in proposal and "$350" not in proposal


def test_exact_suspension_redirect_has_no_content_repair(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = HOME
        audit = capture(ABNORMAL[0][0], final="https://fixture.example.com/cgi-sys/suspendedpage.cgi")
        save_audit(session, lead.id, audit)
        session.flush()
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.intervention_assessment["state"] == "validate_first"
        assert not price.price_available
        assert audit.final_url.endswith("suspendedpage.cgi")


def test_normal_deficient_business_still_supports_paid_contact_repair(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = HOME
        audit = capture(NORMAL)
        save_audit(session, lead.id, audit)
        session.flush()
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert json.loads(audit.evidence["website_response_v1"])["state"] == "normal"
        assert context.offer_id == "conversion_tune_up" and price.price_available
        assert "mobile call/quote button" in context.scope


def test_legitimate_maintenance_account_suspended_words_do_not_block_site():
    audit = capture(NORMAL + "<p>We offer maintenance. Your customer account remains useful even when an appointment is suspended.</p>")
    assert json.loads(audit.evidence["website_response_v1"])["state"] == "normal"
    assert audit.checks


def test_non_success_response_is_not_normal_business_content():
    audit = capture("<title>Gateway error</title><h1>Failed</h1>", status=503)
    assert not audit.reachable
    assert json.loads(audit.evidence["website_response_v1"])["state"] != "normal"


def facts(url, canonical="", title="Roof Repair", body="Roof Repair"):
    html = f"<title>{title}</title><h1>{body}</h1><p>Repair services for local customers.</p>"
    if canonical:
        html += f'<link rel="canonical" href="{canonical}">'
    return extract_page_analysis(snapshot(html, url=url))


def test_root_aliases_do_not_manufacture_duplicate_title_or_target():
    rows = [facts(HOME, HOME), facts(HOME.rstrip("/"), HOME)]
    original = deepcopy(rows)
    diagnostics = analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])
    assert not {"duplicate_title", "possible_target_overlap"} & {d["type"] for d in diagnostics}
    assert rows == original


def test_distinct_service_pages_with_same_title_remain_distinct():
    rows = [facts(HOME + "repair", HOME + "repair"), facts(HOME + "replacement", HOME + "replacement")]
    kinds = {d["type"] for d in analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])}
    assert {"duplicate_title", "possible_target_overlap"} <= kinds


def test_same_trustworthy_canonical_and_content_is_one_identity():
    rows = [facts(HOME + "alias", HOME + "repair"), facts(HOME + "repair", HOME + "repair")]
    assert "duplicate_title" not in {d["type"] for d in analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])}


@pytest.mark.parametrize("left,right", [("repair", "repair/"), ("repair?area=one", "repair?area=two")])
def test_ambiguous_paths_and_queries_are_not_collapsed_without_proof(left, right):
    rows = [facts(HOME + left), facts(HOME + right)]
    assert "duplicate_title" in {d["type"] for d in analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])}


def test_same_canonical_different_content_does_not_erase_separate_pages():
    rows = [facts(HOME + "repair", HOME, body="Roof Repair"), facts(HOME + "replace", HOME, body="Roof Replacement")]
    assert "duplicate_title" in {d["type"] for d in analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])}


def test_root_alias_does_not_consume_content_sample_slot():
    html = NORMAL + f'<a href="{HOME.rstrip("/")}">Plumbing home</a><a href="/contact">Contact</a><a href="/repair">Repair</a>'
    network = FixtureTransport(
        {
            HOME: response(HOME, html),
            HOME.rstrip("/"): response(HOME.rstrip("/"), html),
            HOME + "contact": response(HOME + "contact", NORMAL),
            HOME + "repair": response(HOME + "repair", NORMAL),
        }
    )
    audit = auditor(network, max_pages=3).audit(HOME)
    pages = json.loads(audit.evidence["seo_pages_v1"])
    assert len(pages) == 3 and audit.metrics["pages_sampled"] == 3
    assert {p["url"] for p in pages} == {HOME, HOME + "contact", HOME + "repair"}


def test_cross_defect_non_normal_aliases_are_not_content_diagnostics():
    rows = [extract_page_analysis(snapshot(ABNORMAL[0][0], url=u)) for u in (HOME, HOME.rstrip("/"))]
    kinds = {d["type"] for d in analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])}
    assert not {"duplicate_title", "possible_target_overlap", "missing_metadata"} & kinds


def test_identity_analysis_leaves_separate_historical_snapshots_immutable(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        data = payload(session, lead)
        first = append_research(session, lead, data)
        saved = first.payload_json
        data["queries"][0]["organic_rank"] = 2
        second = append_research(session, lead, data)
        assert first.id != second.id and first.payload_json == saved
        assert len(research_history(session, lead.id)) == 2


def test_normal_healthy_route_still_allows_bounded_seo_offer(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = HOME
        html = NORMAL + '<meta name="viewport" content="width=device-width"><a href="tel:5550100">Call now</a>'
        save_audit(session, lead.id, capture(html))
        session.flush()
        append_research(session, lead, payload(session, lead), attach_current_pages=False)
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == "conversion_tune_up" and price.price_available
        assert "local SEO title/meta/H1 fixes" in context.scope


def test_independent_hours_correction_survives_invalid_website(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = HOME
        lead.has_hours = False
        save_audit(session, lead.id, capture(ABNORMAL[0][0]))
        session.flush()
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert context.offer_id == "google_presence_cleanup" and price.price_available
        assert context.scope == ("hours and contact cleanup checklist",)
        assert "website_response_validation" in {c["intervention_id"] for c in context.intervention_assessment["ranked_candidates"]}


def test_legacy_suspended_capture_is_sanitized_not_rewritten(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        record = lead.audit
        record.title = "Account Suspended"
        record.final_url = lead.website + "/cgi-sys/suspendedpage.cgi"
        record.weaknesses_json = '["Contact/quote path is weak across sampled pages."]'
        record.evidence_json = '{"tap_to_call":"legacy capture"}'
        lead.verification_json = '{"audit_claims":true}'
        session.flush()
        original = (record.checks_json, record.weaknesses_json, record.evidence_json)
        audit = audit_from_record(record)
        assert website_evidence_state(audit) == "non_normal" and not audit.checks
        score = score_lead(profile_from_lead(lead), audit, competitor_average_website_score=100)
        assert not {"weak_website", "competitor_gap", "no_phone_cta"} & {f.key for f in score.factors}
        proof = SalesEvidenceService().build(session, lead)
        assert not proof.for_usage(USAGE_OWNER_COPIED)
        report = ReportService(config).generate_report(session, lead, "owner_short").read_text(encoding="utf-8")
        assert "Contact/quote path is weak" not in report
        assert original == (record.checks_json, record.weaknesses_json, record.evidence_json)


@pytest.mark.parametrize(
    "bad",
    [
        "{corrupt",
        '{"version":99,"state":"normal"}',
        json.dumps({"version": 1, "state": "normal", "url": "https://other.example/", "status_code": 200, "indicators": [], "reason": "foreign"}),
    ],
)
def test_corrupt_or_foreign_response_metadata_fails_closed(storage, bad):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        lead.audit.evidence_json = json.dumps({"website_response_v1": bad})
        session.flush()
        _, price, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        assert not price.price_available and not context.scope
        assert context.intervention_assessment["state"] == "validate_first"


def test_canonical_conflicting_fingerprints_do_not_merge_any_group():
    rows = [facts(HOME + "a", HOME), facts(HOME + "b", HOME), facts(HOME + "c", HOME, body="Roof Replacement")]
    diagnostics = analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])
    duplicate = next(d for d in diagnostics if d["type"] == "duplicate_title")
    assert len(duplicate["urls"]) == 3


def test_redirect_observations_are_retained_but_not_counted_twice():
    html = NORMAL + '<a href="/old-repair">Repair service</a><a href="/new-repair">Repair service</a>'
    network = FixtureTransport(
        {HOME: response(HOME, html), HOME + "old-repair": response(HOME + "repair", NORMAL), HOME + "new-repair": response(HOME + "repair", NORMAL)}
    )
    audit = auditor(network, max_pages=3).audit(HOME)
    assert audit.metrics["pages_sampled"] == 2
    sample = json.loads(audit.evidence["seo_sample_v1"])
    assert sample["observations_sampled"] == 3 and sample["pages_sampled"] == 2
    observations = json.loads(audit.evidence["website_observations_v1"])
    assert {o["requested_url"] for o in observations} == {HOME, HOME + "old-repair", HOME + "new-repair"}
    assert len(json.loads(audit.evidence["seo_pages_v1"])) == 3


def test_auto_attached_seo_pages_use_unique_identity_not_redirect_count(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        lead.website = HOME
        html = NORMAL + '<a href="/old-repair">Repair service</a><a href="/new-repair">Repair service</a>'
        network = FixtureTransport(
            {HOME: response(HOME, html), HOME + "old-repair": response(HOME + "repair", NORMAL), HOME + "new-repair": response(HOME + "repair", NORMAL)}
        )
        save_audit(session, lead.id, auditor(network, max_pages=3).audit(HOME))
        data = payload(session, lead)
        data["pages"] = []
        row = append_research(session, lead, data)
        imported = json.loads(row.payload_json)["pages"]
        assert len(imported) == 2


def test_legacy_invalid_page_facts_never_generate_ordinary_metadata_diagnosis():
    row, _ = facts(HOME, title="Account Suspended")
    kinds = {d["type"] for d in analyze_page_sample([row])}
    assert kinds == {"response_validation"}


def test_abnormal_internal_page_is_retained_but_excluded_from_content_checks():
    html = NORMAL + '<a href="/repair">Roof Repair</a>'
    network = FixtureTransport({HOME: response(HOME, html), HOME + "repair": response(HOME + "repair", ABNORMAL[0][0])})
    audit = auditor(network, max_pages=2).audit(HOME)
    assert audit.metrics["pages_sampled"] == 2 and audit.metrics["ordinary_pages_sampled"] == 1
    assert audit.metrics["service_pages_sampled"] == 0
    raw = json.loads(audit.evidence["seo_pages_v1"])
    assert len(raw) == 2 and raw[1]["title"] == "Account Suspended"
    assert any(d["type"] == "response_validation" for d in json.loads(audit.evidence["seo_page_diagnostics_v1"]))


def test_shared_canonical_aliases_do_not_overwrite_distinct_observed_destination():
    rows = [facts(HOME + "a", HOME), facts(HOME + "b", HOME), facts(HOME, body="Roof Replacement")]
    diagnostics = analyze_page_sample([r[0] for r in rows], [r[1] for r in rows])
    duplicate = next(d for d in diagnostics if d["type"] == "duplicate_title")
    assert len(duplicate["urls"]) == 3


@pytest.mark.parametrize("raw", ['"not a list"', "null", "12", '{"bad":"shape"}'])
def test_legacy_malformed_claim_json_cannot_become_owner_facing_characters(storage, raw):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        lead.audit.weaknesses_json = raw
        lead.verification_json = '{"audit_claims":true}'
        session.flush()
        proof = SalesEvidenceService().build(session, lead)
        assert not proof.findings and not proof.for_usage(USAGE_OWNER_COPIED)
