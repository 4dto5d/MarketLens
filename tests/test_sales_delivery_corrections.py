"""Synthetic public sales/delivery checks; no live acquisitions or sends."""

import json
import zipfile
from datetime import timedelta

import pytest

from local_presence_miner.config import AppConfig, SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.schema import Lead, LeadSearch, SEOResearchSnapshot, WebsiteAuditRecord
from local_presence_miner.domain.enums import OutreachKind
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.call_guide_service import CallGuideService
from local_presence_miner.services.delivery_packet_service import DELIVERY_FIELDS, DELIVERY_PREREQUISITES, DeliveryPacketService
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.outreach_service import OutreachService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.sales_evidence_service import USAGE_OWNER_COPIED, USAGE_OWNER_SPOKEN, SalesEvidenceService
from local_presence_miner.services.seo_research_service import append_research, research_binding
from local_presence_miner.time_utils import utc_now


@pytest.fixture
def storage(tmp_path):
    config = AppConfig(tmp_path, tmp_path / "sales.sqlite3", tmp_path / "app.log", tmp_path / "outputs")
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    return config, factory


def business(session, *, audit=True):
    search = LeadSearch(name="Synthetic buyer proof", city="Denver", state_region="CO", niche="plumber")
    session.add(search)
    session.flush()
    now = utc_now()
    lead = Lead(search_id=search.id, place_id="sales-proof", name="Synthetic Plumbing", category="plumber",
                website="https://proof.example", phone="555-0100", rating=4.8, review_count=100,
                has_hours=True, photo_count=12, google_public_data_json='{"details_retrieved":true}',
                google_retrieved_at=now.isoformat(), last_rich_google_retrieved_at=now.isoformat(),
                qualification_class="Qualified", qualification_confidence="Moderate")
    session.add(lead)
    session.flush()
    if audit:
        checks = {key: True for key in ("https", "viewport", "tap_to_call", "contact_form", "sitewide_contact_path",
                                       "clear_primary_cta", "indexable_sample", "service_pages", "trust_signals")}
        session.add(WebsiteAuditRecord(lead_id=lead.id, url=lead.website, final_url=lead.website, reachable=True,
                                      status_code=200, checks_json=json.dumps(checks), created_at=now))
        session.flush()
    return lead


def payload(session, lead):
    page = lead.website + "/emergency"
    return {
        "schema_version": 1, "subject": research_binding(session, lead)["subject"], "observed_at": utc_now().isoformat(),
        "source": {"provider": "manual_serp", "report": "synthetic buyer proof", "database": "manual",
                   "geography": "Denver CO", "geo_resolution": "local", "status": "complete",
                   "reference": "synthetic:buyer-proof", "demo": False},
        "queries": [{"query": "emergency plumber Denver CO", "service": "emergency plumbing", "service_state": "confirmed",
                     "service_refs": [page + "#service"], "intent": "local_commercial", "intent_basis": "Synthetic intent observation",
                     "volume": 7, "difficulty": 18, "organic_rank": 11, "maps_rank": None, "organic_window": 30,
                     "maps_window": None, "organic_complete": True, "maps_complete": False, "page_url": page,
                     "competitors": [{"url": "https://other.example/emergency", "channel": "organic", "position": 3,
                                      "kind": "local_business", "authority": 15, "referring_domains": 7}],
                     "serp_features": [], "refs": ["synthetic:rank11"]}],
        "pages": [{"url": page, "title": "Home", "h1": ["Local service team"], "meta_description": "", "canonical": page,
                   "robots": [], "status_code": 200, "indexability": "allowed", "word_count": 500, "internal_links": [],
                   "schema_types": ["Service"], "schema_errors": [], "services": ["emergency plumbing"],
                   "service_refs": [page + "#service"]}],
    }


def test_selected_query_proof_reaches_guide_and_rendered_owner_report(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        source = payload(session, lead)
        append_research(session, lead, source)
        guide = CallGuideService().build(session, lead, [])
        owner = ReportService(config).generate_report(session, lead, "owner_short").read_text(encoding="utf-8")
        assert "emergency plumber Denver CO" in guide.opening_15s
        assert "position 11" in owner and "window 30" in owner
        assert source["observed_at"] in owner
        assert "https://proof.example/emergency" in owner


def test_no_artifact_drafts_use_future_preparation_and_honest_identical_scope(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        plan, pricing, _ = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        drafts = OutreachService(SenderInfo(name="Ben")).generate_all(lead, session=session, adaptive_plan=plan, pricing=pricing)
        text = " ".join(body for _, body in drafts.values()).casefold()
        assert "put together" not in text and "saved the comparison" not in text and "also made" not in text
        assert "expanded scope" not in drafts[OutreachKind.PRICE_REPLY][1]


def test_no_audit_report_never_claims_acquisition_or_final_review_completed(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session, audit=False)
        text = ReportService(config).generate_report(session, lead, "owner_short").read_text(encoding="utf-8")
        assert "Raw HTML: completed" not in text
        assert "tied to stored public observations and final human review" not in text
        assert "Raw HTML: missing" in text


def test_priced_discovery_proposal_contains_customer_delivery_unknowns(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        _, pricing, _ = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        text = ProposalService(config).generate_proposal(session, lead, selected_price=pricing.recommended).read_text(encoding="utf-8")
        assert "local SEO title/meta/H1 fixes" in text
        assert "Payment arrangement" in text and "UNKNOWN" in text
        assert "Rollback" in text and "Email" in text and "Definition of done" in text
        assert "Not ready for a payable commitment" in text


def test_review_is_bound_to_current_selected_proof_and_not_artifact_existence(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        proof = SalesEvidenceService().build(session, lead)
        assert proof.selected_evidence["query"] == "emergency plumber Denver CO"
        assert proof.for_usage(USAGE_OWNER_COPIED) == ()
        ProposalService(config).generate_proposal(session, lead, selected_price=pricing.recommended)
        assert SalesEvidenceService().build(session, lead).for_usage(USAGE_OWNER_SPOKEN) == ()
        review = SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi",
                                                     source_text="Checked exact synthetic query/page/source.")
        reviewed = SalesEvidenceService().build(session, lead)
        assert reviewed.review_state == "REVIEWED"
        assert "position 11" in reviewed.for_usage(USAGE_OWNER_COPIED)[0].claim
        review.value_json = "{corrupt"
        session.flush()
        assert SalesEvidenceService().build(session, lead).for_usage(USAGE_OWNER_COPIED) == ()


@pytest.mark.parametrize("state", ["failed", "partial", "corrupt", "stale", "future"])
def test_new_unusable_checkpoint_never_reuses_reviewed_sales_proof(storage, state):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        source = payload(session, lead)
        row = append_research(session, lead, source)
        _, _, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi", source_text="Reviewed synthetic evidence.")
        if state == "corrupt":
            session.add(SEOResearchSnapshot(lead_id=lead.id, schema_version=1, binding_json=row.binding_json,
                                          payload_json="{broken", payload_sha256="0" * 64, source_status="complete",
                                          observed_at=source["observed_at"]))
            session.flush()
        else:
            if state in {"failed", "partial"}:
                source["source"]["status"] = state
            else:
                source["observed_at"] = (utc_now() + timedelta(days=1 if state == "future" else -31)).isoformat()
            append_research(session, lead, source)
        proof = SalesEvidenceService().build(session, lead)
        assert not proof.selected_evidence
        assert proof.for_usage(USAGE_OWNER_COPIED) == ()
        guide = CallGuideService().build(session, lead, [])
        assert "position 11" not in guide.opening_15s


def test_delivery_manual_review_owner_agreement_and_unknowns_fail_closed(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        service = DeliveryPacketService()
        SalesEvidenceService().record_review(session, lead, context=context, reviewer="Sammi", source_text="Reviewed synthetic source and page.")
        facts = {key: f"Manual synthetic agreement: {label}; assigned Sammi and owner for this title/meta/H1 scope." for key, label in DELIVERY_FIELDS.items()}
        facts["payment_arrangement"] = "Actual synthetic agreement: $350 after owner-approved checks, no deposit."
        first = service.record(session, lead, context=context, fields=facts, selected_price=pricing.recommended,
                               reviewer="Sammi", source_text="Synthetic manual discovery, owner has not agreed.", reviewed=True)
        assert not service.build(session, lead, context=context, selected_price=pricing.recommended)["ready_for_payment"]
        final = service.record(session, lead, context=context, fields=facts, selected_price=pricing.recommended,
                               reviewer="Sammi", source_text="Synthetic owner approves exactly these facts.", reviewed=True, owner_approved=True,
                               prerequisites={key: {"state": "satisfied", "notes": "Synthetic owner/provider has confirmed the exact page access and plan."}
                                              for key in DELIVERY_PREREQUISITES})
        assert final.id != first.id and final.supersedes_assertion_id == first.id
        ready = service.build(session, lead, context=context, selected_price=pricing.recommended)
        assert ready["ready_for_payment"] and ready["state"] == "reviewed"
        rendered = ProposalService(config).generate_proposal(session, lead, selected_price=pricing.recommended).read_text(encoding="utf-8")
        assert facts["payment_arrangement"] in rendered
        assert "Not ready for a payable commitment" not in rendered
        assert not service.build(session, lead, context=context, selected_price=pricing.recommended + 100)["ready_for_payment"]
        facts["email_inventory"] = "UNKNOWN — owner must verify email dependencies"
        service.record(session, lead, context=context, fields=facts, selected_price=pricing.recommended,
                       reviewer="Sammi", source_text="Discovery incomplete.", reviewed=True, owner_approved=True)
        assert not service.build(session, lead, context=context, selected_price=pricing.recommended)["ready_for_payment"]


def test_delivery_cannot_turn_manual_text_or_corrupt_record_into_review(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        service = DeliveryPacketService()
        with pytest.raises(ValueError, match="named delivery fields"):
            service.record(session, lead, context=context, fields={"imaginary_guarantee": "No risk"},
                           selected_price=pricing.recommended, reviewer="Sammi", source_text="Manual record.")
        row = service.record(session, lead, context=context, fields={}, selected_price=pricing.recommended,
                             reviewer="Sammi", source_text="Unreviewed manual discovery.")
        assert not service.build(session, lead, context=context, selected_price=pricing.recommended)["ready_for_payment"]
        row.value_json = "null"
        session.flush()
        assert not service.build(session, lead, context=context, selected_price=pricing.recommended)["ready_for_payment"]
        corrupt = {"binding": service.build(session, lead, context=context, selected_price=pricing.recommended)["binding"],
                   "fields": {"email_inventory": 123}}
        row.value_json = json.dumps(corrupt)
        session.flush()
        assert not service.build(session, lead, context=context, selected_price=pricing.recommended)["ready_for_payment"]


def test_owner_reports_and_proposals_do_not_leak_internal_send_or_private_prices(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        for path in (ReportService(config).generate_report(session, lead), ProposalService(config).generate_proposal(session, lead)):
            text = path.read_text(encoding="utf-8")
            assert "SEND:" not in text and "DO NOT SEND" not in text
            assert "Private Seller Pricing" not in text and "seo_snapshot:" not in text
            assert "emergency plumber Denver CO" in text


def test_supplied_selected_packet_cannot_override_current_source_position(storage):
    _, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        _, _, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
        forged = json.loads(json.dumps(context.intervention_assessment))
        forged["ranked_candidates"][0]["selected_evidence"]["observed_position"] = 1
        evidence = SalesEvidenceService().build(session, lead, assessment=forged, offer_id=context.offer_id, scope=context.scope)
        assert evidence.selected_evidence == {}
        assert evidence.for_usage(USAGE_OWNER_COPIED) == ()


@pytest.mark.parametrize("reachable,status,checks,evidence,expected", [
    (False, 503, {}, {}, "failed"), (True, 200, {}, {}, "partial"),
    (True, 200, {"https": True}, {"title": "Recorded page"}, "complete"),
    (True, 200, ["invalid record"], {"title": "Record"}, "partial"),
])
def test_rendered_raw_acquisition_uses_actual_record(storage, reachable, status, checks, evidence, expected):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        audit = lead.audit
        audit.reachable, audit.status_code = reachable, status
        audit.checks_json, audit.evidence_json = json.dumps(checks), json.dumps(evidence)
        session.flush()
        text = ReportService(config).generate_report(session, lead, "owner_short").read_text(encoding="utf-8")
        assert f"Raw HTML: {expected}" in text
        assert "Completion records acquisition, not fact review or owner approval" in text


def test_customer_package_contains_exact_delivery_packet_separate_from_optional_concept(storage):
    config, factory = storage
    with factory() as session:
        lead = business(session)
        append_research(session, lead, payload(session, lead))
        path = LeadPackageService(config).export_package(session, lead, ai_mode="off")
        with zipfile.ZipFile(path) as archive:
            delivery_files = [name for name in archive.namelist() if "-delivery--" in name]
            assert len(delivery_files) == 2
            html = archive.read(next(name for name in delivery_files if name.endswith(".html"))).decode("utf-8")
            assert "local SEO title/meta/H1 fixes" in html and "https://proof.example/emergency" in html
            assert "Generic concepts are optional demonstrations" in html
            assert "Not ready for a payable commitment" in html
