from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import select

from local_presence_miner.config import SenderInfo
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.database.pricing_repository import delete_seller_proof, save_seller_proof
from local_presence_miner.database.repositories import (
    add_suppression,
    edit_outreach_draft,
    outreach_approval_errors,
    revalidate_outreach_evidence,
    save_outreach_draft,
    set_outreach_approval,
    update_lead_fields,
    update_lead_status,
)
from local_presence_miner.database.schema import Lead, LeadSearch, OutreachApprovalHistory, OutreachDraft, SellerProof
from local_presence_miner.domain.enums import LeadStatus, OutreachKind
from local_presence_miner.services.credibility_service import CredibilityService
from local_presence_miner.services.outbound_validation_service import validate_outbound_draft
from local_presence_miner.services.outreach_batch_service import OutreachBatchService
from local_presence_miner.services.proof_dependency_service import (
    PERMISSION_FIELDS,
    make_proof_dependency,
    proof_allows_external_use,
)
from local_presence_miner.services.public_url_safety import (
    PinnedPublicTransport,
    UnsafePublicUrlError,
    ValidatedPublicUrl,
    safe_request,
    validate_public_url,
)
from local_presence_miner.services.rendered_auditor import RenderedAuditor, rendered_audit_availability
from local_presence_miner.services.seller_proof_service import safe_proof_sentence, summarize_seller_proof
from local_presence_miner.services.website_auditor import WebsiteAuditor


@pytest.fixture
def db(tmp_path):
    factory = create_session_factory(tmp_path / "synthetic.sqlite3")
    initialize_database(factory)
    with factory() as session:
        yield session
    factory.kw["bind"].dispose()


def prospect(session, key="pass1"):
    lead = Lead(
        place_id=key,
        name="Fixture Roofing",
        category="roofers",
        phone="555-010-1212",
        qualification_class="Qualified",
        qualification_confidence="Strong",
        qualification_json='{"classification":"Qualified","confidence":"Strong"}',
        recommended_offer="Conversion Tune-Up",
        recommended_offer_id="conversion_tune_up",
        offer_resolution_state="canonical_id",
    )
    lead.verification_json = json.dumps({key: True for key in (
        "business_identity", "website", "phone", "audit_claims", "competitors", "outreach",
    )})
    session.add(lead)
    session.flush()
    return lead


def evidence(session, **changes):
    values = dict(proof_type="Paid Project", title="Private title", status="Completed", niche="roofers",
                  client_name="Permitted Client", client_work=True, verified=True, internal_only=False,
                  share_client_name=True, safe_claims=["Recorded completed project"])
    values.update(changes)
    return save_seller_proof(session, **values)


def approved_draft(session, outbound, proof=None):
    lead = prospect(session)
    deps = [make_proof_dependency(proof, {"client_name"})] if proof is not None else []
    draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Fixture subject",
                                outbound.body("A recorded example for review."), proof_dependencies=deps)
    set_outreach_approval(session, draft.id, True, sender=outbound.sender)
    session.flush()
    return lead, draft


def test_supporting_proof_deletion_revokes_and_preserves_dependency_history(db, outbound):
    proof = evidence(db)
    proof_id = proof.id
    lead, draft = approved_draft(db, outbound, proof)
    before = draft.body
    snapshot = json.loads(draft.proof_dependencies_json)
    delete_seller_proof(db, proof_id)
    db.flush()
    assert not draft.approved and lead.status == LeadStatus.NEEDS_REVIEW.value
    assert draft.body == before
    tombstone = db.get(SellerProof, proof_id)
    assert tombstone is not None and tombstone.artifact_state == "deleted_tombstone"
    history = db.scalar(select(OutreachApprovalHistory))
    assert history.body == before and json.loads(history.proof_dependencies_json) == snapshot
    assert snapshot[0]["proof_id"] == proof_id and snapshot[0]["usages"] == ["client_name"]
    assert len(snapshot[0]["fingerprint"]) == len(snapshot[0]["claim_evidence_fingerprint"]) == 64
    assert snapshot[0]["proof_snapshot"]["status"] == "Completed"
    assert json.loads(history.approval_snapshot_json)["approved_at"]
    assert "delet" in history.revocation_reason.lower()
    with pytest.raises(ValueError, match="changed"):
        set_outreach_approval(db, draft.id, True, sender=outbound.sender)


@pytest.mark.parametrize("change", [
    {"status": "In Progress"}, {"status": "Unclassified"}, {"verified": False}, {"client_work": False},
    {"safe_claims": []}, {"safe_claims": ["Different evidence"]}, {"internal_only": True},
    {"share_client_name": False},
])
def test_supporting_proof_material_change_revokes_exact_approval(db, outbound, change):
    proof = evidence(db)
    _, draft = approved_draft(db, outbound, proof)
    body = draft.body
    evidence(db, proof_id=proof.id, **change)
    db.flush()
    assert not draft.approved and draft.body == body
    history = db.scalar(select(OutreachApprovalHistory))
    assert history.body == body and "changed" in history.revocation_reason
    with pytest.raises(ValueError, match="changed"):
        set_outreach_approval(db, draft.id, True, sender=outbound.sender)


def test_non_claim_proof_change_that_affects_pricing_requires_commercial_review(db, outbound):
    """B04 adds commercial dependencies beyond a draft's direct proof claim.

    A second completed same-niche paid-project artifact contributes to the seller
    evidence used by pricing. Changing its verification state is therefore not
    commercially unrelated even though the draft's direct proof dependency points
    at another artifact. The exact approved body must be preserved before review.
    """
    supporting = evidence(db)
    pricing_evidence = evidence(db, title="Other proof")
    _, draft = approved_draft(db, outbound, supporting)
    exact_body = draft.body
    evidence(db, proof_id=pricing_evidence.id, title="Other proof changed", verified=False)
    db.flush()
    assert not draft.approved
    assert draft.body == exact_body
    assert outreach_approval_errors(db, draft, outbound.sender)
    history = db.scalar(select(OutreachApprovalHistory))
    assert history is not None and history.body == exact_body


def test_manual_edit_requires_fresh_explicit_dependency_review_and_reapproval(db, outbound):
    proof = evidence(db)
    _, draft = approved_draft(db, outbound, proof)
    before = draft.body
    edit_outreach_draft(db, draft.id, "Edited", outbound.body("Edited reviewable example."))
    assert not draft.approved and draft.proof_dependencies_json == "[]"
    assert draft.dependency_state == "manual_review_required" and not draft.dependency_body_fingerprint
    with pytest.raises(ValueError, match="revalidate"):
        set_outreach_approval(db, draft.id, True, sender=outbound.sender)
    with pytest.raises(ValueError, match="Explicit operator"):
        revalidate_outreach_evidence(db, draft.id, [proof.id], operator_confirmed=False)
    revalidate_outreach_evidence(db, draft.id, [proof.id], operator_confirmed=True)
    assert not draft.approved and draft.dependency_state == "manually_revalidated"
    set_outreach_approval(db, draft.id, True, sender=outbound.sender)
    assert draft.approved
    assert db.scalar(select(OutreachApprovalHistory)).body == before
    draft.body += " Untracked edit"
    with pytest.raises(ValueError, match="exact body"):
        set_outreach_approval(db, draft.id, True, sender=outbound.sender)


def test_deleted_proof_is_not_silently_replaced(db, outbound):
    proof = evidence(db)
    _, draft = approved_draft(db, outbound, proof)
    delete_seller_proof(db, proof.id)
    evidence(db, title="Similar replacement")
    with pytest.raises(ValueError, match="no verified, permitted external use"):
        revalidate_outreach_evidence(db, draft.id, [proof.id], operator_confirmed=True)
    assert not draft.approved


@pytest.mark.parametrize("field,value", [
    ("proof_dependencies_json", "not json"), ("proof_dependencies_json", "[null]"),
    ("proof_dependency_fingerprint", "bad hash"), ("dependency_state", "unknown"),
    ("dependency_body_fingerprint", ""),
])
def test_malformed_or_unknown_dependency_metadata_blocks_approval(db, outbound, field, value):
    _, draft = approved_draft(db, outbound)
    set_outreach_approval(db, draft.id, False)
    setattr(draft, field, value)
    with pytest.raises(ValueError, match="Approval blocked"):
        set_outreach_approval(db, draft.id, True, sender=outbound.sender)
    assert not draft.approved


def test_new_proof_defaults_do_not_create_client_experience(db):
    from local_presence_miner.ui.dialogs.seller_proof_dialog import proof_values

    values = proof_values(None)
    assert values["status"] == "Unclassified" and not values["verified"] and not values["client_work"]
    assert values["internal_only"] and not any(values[field] for field in PERMISSION_FIELDS.values())
    for proof_type in ("Paid Project", "Testimonial", "Portfolio Example", "Other"):
        proof = save_seller_proof(db, proof_type=proof_type, title="New record")
        assert proof.status == "Unclassified" and not proof.verified and not proof.client_work
        assert proof.internal_only and not any(getattr(proof, field) for field in PERMISSION_FIELDS.values())
    profile = CredibilityService().build(db, "roofers")
    assert profile.completed_client_projects == 0
    assert not profile.attachments.send
    with pytest.raises(ValueError, match="no longer exists"):
        save_seller_proof(db, proof_id=987654, proof_type="Paid Project", title="Missing edit")


def test_verified_public_url_alone_remains_internal_and_never_emitted(db):
    proof = evidence(db, internal_only=True, title="SECRET TITLE", client_name="SECRET CLIENT",
                     public_url="https://portfolio.example.com/secret", testimonial_available=True,
                     before_after_available=True, safe_claims=["SECRET CLAIM"])
    profile = CredibilityService().build(db, "roofers")
    assert profile.completed_client_projects == 1  # internal evidence is not disabled
    external = " ".join((profile.experience_quick, profile.experience_normal, profile.experience_detailed,
                         profile.ai_response, profile.email_context, *profile.proposal_points,
                         *profile.reference_options, *profile.attachments.send, *profile.attachments.optional))
    assert "SECRET" not in external and "portfolio.example.com" not in external
    assert all(not proof_allows_external_use(proof, usage) for usage in PERMISSION_FIELDS)
    assert safe_proof_sentence(summarize_seller_proof(db, "roofers"), "roofers") == ""


@pytest.mark.parametrize("usage", list(PERMISSION_FIELDS))
def test_disclosure_permissions_are_independent_and_internal_only_overrides(db, usage):
    flags = {field: False for field in PERMISSION_FIELDS.values()}
    flags[PERMISSION_FIELDS[usage]] = True
    proof = evidence(db, proof_type="Case Study", testimonial_available=True, before_after_available=True,
                     public_url="https://portfolio.example.com/example", **flags)
    assert {key for key in PERMISSION_FIELDS if proof_allows_external_use(proof, key)} == {usage}
    proof.internal_only = True
    assert not any(proof_allows_external_use(proof, key) for key in PERMISSION_FIELDS)


def test_client_name_permission_does_not_quote_unpermitted_claim_or_url(db):
    evidence(db, title="SECRET TITLE", safe_claims=["SECRET RESULT"], public_url="https://example.com/private")
    profile = CredibilityService().build(db, "roofers")
    assert "Permitted Client" in profile.email_context
    assert "SECRET" not in profile.email_context and "example.com/private" not in profile.email_context
    assert not profile.attachments.send and not profile.reference_options
    assert profile.email_proof_dependencies[0]["usages"] == ["client_name"]


@pytest.mark.parametrize("path", ["setter", "save", "status", "fields"])
def test_unresolved_sender_is_blocked_at_all_approval_entry_points(db, outbound, path):
    lead = prospect(db)
    draft = save_outreach_draft(db, lead.id, OutreachKind.INITIAL_EMAIL, "Hi",
                                outbound.body("Hello [Your name]"), proof_dependencies=[])
    with pytest.raises(ValueError, match="placeholder|cannot bypass|cannot grant"):
        if path == "setter":
            set_outreach_approval(db, draft.id, True, sender=outbound.sender)
        elif path == "save":
            save_outreach_draft(db, lead.id, OutreachKind.INITIAL_EMAIL, draft.subject, draft.body,
                                approved=True, proof_dependencies=[], sender=outbound.sender)
        elif path == "status":
            update_lead_status(db, lead.id, LeadStatus.APPROVED_TO_CONTACT)
        else:
            update_lead_fields(db, lead.id, status=LeadStatus.APPROVED_TO_CONTACT.value)
    assert not draft.approved and lead.status != LeadStatus.APPROVED_TO_CONTACT.value


@pytest.mark.parametrize("field", ["name", "reply_email", "postal_address", "opt_out_line"])
def test_missing_sender_compliance_blocks_valid_body(db, outbound, field):
    _, draft = approved_draft(db, outbound)
    set_outreach_approval(db, draft.id, False)
    with pytest.raises(ValueError, match="Approval blocked"):
        set_outreach_approval(db, draft.id, True, sender=replace(outbound.sender, **{field: ""}))
    assert not draft.approved


def test_valid_sender_approves_and_exact_suppression_still_blocks(db, outbound):
    lead, draft = approved_draft(db, outbound)
    assert draft.approved and not outreach_approval_errors(db, draft, outbound.sender)
    add_suppression(db, "Fixture Roof")
    assert draft.approved
    add_suppression(db, lead.name)
    assert not draft.approved
    with pytest.raises(ValueError, match="Suppressed"):
        set_outreach_approval(db, draft.id, True, sender=outbound.sender)


def test_batch_export_rechecks_current_sender_and_explains_skip(db, outbound, tmp_path):
    lead = prospect(db)
    call = save_outreach_draft(db, lead.id, OutreachKind.CALL_OPENING, "", "Reviewable call opening", proof_dependencies=[])
    set_outreach_approval(db, call.id, True, sender=outbound.sender)
    ready = OutreachBatchService(outbound.sender).export_ready_csv(db, tmp_path / "ready")
    assert ready.exported == 1 and "Reviewable call opening" in ready.path.read_text()
    skipped = OutreachBatchService(SenderInfo()).export_ready_csv(db, tmp_path / "review")
    assert skipped.exported == 0 and skipped.skipped == 1
    assert "sender" in skipped.review_path.read_text().lower()


def test_voicemail_uses_neutral_fallback_and_requires_configured_identity(db):
    from local_presence_miner.services.outreach_service import OutreachService

    lead = prospect(db)
    drafts = OutreachService(SenderInfo()).generate_all(lead, session=db)
    subject, body = drafts[OutreachKind.VOICEMAIL]
    assert "a website analyst" in body and "a local website auditor" not in body
    assert not validate_outbound_draft(SenderInfo(), OutreachKind.VOICEMAIL.value, subject, body).valid


def test_legacy_approved_unknown_dependencies_migrate_once_without_body_loss(tmp_path):
    path = tmp_path / "synthetic-legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL)")
        connection.execute("INSERT INTO leads VALUES (1, 'legacy', 'Legacy fixture', 'Approved to Contact')")
        connection.execute("CREATE TABLE seller_proof (id INTEGER PRIMARY KEY, seller_profile_id INTEGER NOT NULL, "
                           "proof_type TEXT NOT NULL, title TEXT NOT NULL)")
        connection.execute("INSERT INTO seller_proof VALUES (1, 1, 'Paid Project', 'Preserved legacy proof')")
        connection.execute("CREATE TABLE outreach_drafts (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, "
                           "kind TEXT, subject TEXT, body TEXT, approved BOOLEAN)")
        connection.execute("INSERT INTO outreach_drafts VALUES (1, 1, ?, 'Legacy subject', 'EXACT historical body', 1)", (OutreachKind.INITIAL_EMAIL.value,))
    with sqlite3.connect(path) as original:
        original_dump = list(original.iterdump())
    factory = create_session_factory(path)
    initialize_database(factory)
    backup = path.with_suffix(path.suffix + ".backup-before-v0112")
    with sqlite3.connect(backup) as copied:
        assert list(copied.iterdump()) == original_dump
        assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    before = hashlib.sha256(backup.read_bytes()).hexdigest()
    for _ in range(2):
        initialize_database(factory)
        with factory() as session:
            draft = session.get(OutreachDraft, 1)
            assert draft.body == "EXACT historical body" and not draft.approved
            assert draft.dependency_state == "unknown"
            assert session.get(Lead, 1).status == LeadStatus.NEEDS_REVIEW.value
            histories = list(session.scalars(select(OutreachApprovalHistory)))
            assert len(histories) == 1 and histories[0].body == draft.body
            assert "migration" in histories[0].revocation_reason
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT title, internal_only, share_public_url FROM seller_proof").fetchone() == (
                "Preserved legacy proof", 1, 0,
            )
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == before
    factory.kw["bind"].dispose()


def public_dns(_host, _port):
    return ("93.184.216.34",)


def response(url, body="<html><title>Fixture</title><body>Public page</body></html>", status=200, **headers):
    result = requests.Response()
    result.url, result.status_code, result._content = url, status, body.encode()
    result.headers.update({"Content-Type": "text/html", **headers})
    result._content_consumed = True
    return result


class PublicFixtureTransport:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def request(self, method, target, **kwargs):
        self.calls.append((method, target.url, target.addresses))
        return self.pages[target.url]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1", "http://10.1.2.3", "http://172.16.0.2", "http://192.168.1.1", "http://169.254.169.254",
    "http://0.0.0.0", "http://224.0.0.1", "http://[::1]", "http://[fc00::1]", "http://[fe80::1]",
    "http://[::ffff:127.0.0.1]", "http://[64:ff9b::a00:1]", "file:///secret", "ftp://example.com", "http://localhost",
    "http://router.internal", "https://user:password@example.com", "http://example.com\\@127.0.0.1",
])
def test_private_special_and_unsupported_destinations_rejected_before_transport(url):
    network = PublicFixtureTransport({})
    with pytest.raises(UnsafePublicUrlError):
        safe_request(None, "GET", url, resolver=public_dns, transport=network)
    assert network.calls == []


@pytest.mark.parametrize("addresses", [("10.0.0.1",), ("93.184.216.34", "192.168.1.1"), ()])
def test_hostname_private_mixed_or_empty_dns_rejected_before_contact(addresses):
    network = PublicFixtureTransport({})
    with pytest.raises(UnsafePublicUrlError):
        safe_request(None, "GET", "https://fixture.example.com", resolver=lambda *_: addresses, transport=network)
    assert not network.calls


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_public_redirect_to_private_blocked_before_next_hop(method):
    start = "https://fixture.example.com"
    network = PublicFixtureTransport({start: response(start, status=302, Location="http://10.0.0.1/private")})
    with pytest.raises(UnsafePublicUrlError):
        safe_request(None, method, start, resolver=public_dns, transport=network)
    assert network.calls == [(method, start, ("93.184.216.34",))]


def test_ordinary_public_redirect_and_website_audit_remain_enabled():
    start, end = "https://fixture.example.com", "https://fixture.example.com/home"
    network = PublicFixtureTransport({start: response(start, status=302, Location="/home"), end: response(end)})
    audit = WebsiteAuditor(request_delay_seconds=0, max_pages=1, resolver=public_dns, transport=network).audit(start)
    assert audit.reachable and audit.title == "Fixture" and audit.final_url == end
    assert [url for _, url, _ in network.calls] == [start, end]


def test_dns_pinning_preserves_tls_identity_and_disables_automatic_redirects(monkeypatch):
    import local_presence_miner.services.public_url_safety as policy

    calls = []

    class Pool:
        def __init__(self, host, port, **kwargs):
            calls.append((host, port, kwargs))

        def urlopen(self, method, path, **kwargs):
            assert method == "GET" and path == "/path"
            assert kwargs["redirect"] is False and kwargs["retries"] is False
            assert kwargs["headers"]["Host"] == "fixture.example.com"
            return SimpleNamespace(status=200, headers={}, data=b"fixture")

        def close(self):
            pass

    monkeypatch.setattr(policy.urllib3, "HTTPSConnectionPool", Pool)
    target = validate_public_url("https://fixture.example.com/path", resolver=public_dns)
    result = PinnedPublicTransport().request("GET", target, timeout=1, headers={})
    assert result.content == b"fixture"
    host, port, tls = calls[0]
    assert (host, port) == ("93.184.216.34", 443)
    assert tls["assert_hostname"] == tls["server_hostname"] == "fixture.example.com"
    assert tls["cert_reqs"] == "CERT_REQUIRED" and tls["ca_certs"]
    with pytest.raises(UnsafePublicUrlError):
        PinnedPublicTransport().request("GET", ValidatedPublicUrl("http://10.0.0.1", "10.0.0.1", 80, ("10.0.0.1",)), timeout=1, headers={})
    assert len(calls) == 1


def test_rendered_browser_operation_is_explicitly_skipped_without_network(tmp_path, monkeypatch):
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("Unsafe rendered operation contacted a network or launched a browser")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = RenderedAuditor().audit("http://127.0.0.1/private", tmp_path, True)
    assert result.status == "security_unavailable"
    assert "subresources" in result.error and not result.desktop_screenshot and not result.mobile_screenshot
    assert rendered_audit_availability() == (False, result.error)


def test_pagespeed_blocks_private_input_and_api_redirects_before_contact(monkeypatch):
    from local_presence_miner.services.pagespeed import PageSpeedClient

    calls = []

    def get(url, **kwargs):
        calls.append(url)
        assert url == "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        assert kwargs["allow_redirects"] is False
        return response(url, status=302, Location="http://127.0.0.1/private")

    monkeypatch.setattr(requests, "get", get)
    client = PageSpeedClient("fixture-not-a-real-key", resolver=public_dns)
    result = client.run("http://10.0.0.1")
    assert result["pagespeed_status"] == "security_unavailable" and not calls
    result = client.run("https://fixture.example.com")
    assert result["pagespeed_status"] == "failed" and "redirect" in result["pagespeed_error"]
    assert len(calls) == 1


def test_google_api_requests_cannot_follow_redirect_or_use_arbitrary_endpoint(monkeypatch):
    from local_presence_miner.services.google_places import GooglePlacesClient, GooglePlacesError

    calls = []

    def request(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return response(url, status=302, Location="http://10.0.0.1")

    monkeypatch.setattr(requests, "get", request)
    monkeypatch.setattr(requests, "post", request)
    client = GooglePlacesClient("fixture-not-a-real-key")
    with pytest.raises(GooglePlacesError, match="endpoint"):
        client._get_with_retry("http://10.0.0.1", {})
    assert not calls
    with pytest.raises(GooglePlacesError, match="302"):
        client._get_with_retry("https://places.googleapis.com/v1/places/fixture", {})
    with pytest.raises(GooglePlacesError, match="302"):
        client._post_with_retry({}, {})
    assert len(calls) == 2


def test_stylesheet_redirect_private_is_blocked_before_fetch_and_email_is_withheld():
    from local_presence_miner.services.contact_discovery import WebsiteContactDiscovery

    site, css = "https://fixture.example.com", "https://fixture.example.com/style.css"
    network = PublicFixtureTransport({
        site: response(site, '<html><head><link rel="stylesheet" href="/style.css"></head><body>public@example.com</body></html>'),
        css: response(css, status=302, Location="http://192.168.1.1/secret"),
    })
    lead = Lead(place_id="css-redirect", name="Fixture", website=site)
    result = WebsiteContactDiscovery(max_pages=1, resolver=public_dns, transport=network).discover(lead)
    assert not [point for point in result.contacts if point.kind == "email"]
    assert [url for _, url, _ in network.calls] == [site, css]
    assert any("stylesheet could not be read" in warning for warning in result.warnings)


def test_gui_approval_buttons_share_validator_and_url_copy_does_not_navigate(tmp_path, outbound, monkeypatch):
    import webbrowser

    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    from local_presence_miner.config import AppConfig
    from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
    from local_presence_miner.ui.widgets.outreach_widget import OutreachWidget

    app = QApplication.instance() or QApplication([])
    config = AppConfig(tmp_path, tmp_path / "ui.sqlite3", tmp_path / "ui.log", tmp_path, sender=outbound.sender)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    with factory() as session:
        lead = prospect(session)
        lead.website = "http://127.0.0.1/do-not-fetch"
        draft = save_outreach_draft(session, lead.id, OutreachKind.INITIAL_EMAIL, "Fixture", outbound.body("[Your name]"), proof_dependencies=[])
        session.commit()
        lead_id, draft_id = lead.id, draft.id
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(str(args[2])))
    monkeypatch.setattr(QMessageBox, "information", lambda *_: None)
    monkeypatch.setattr(webbrowser, "open", lambda *_: pytest.fail("Prospect URL opened outside policy"))
    dialog = LeadDetailDialog(config, factory, lead_id)
    dialog.set_draft_approval(draft_id, True)
    widget = OutreachWidget(factory, config)
    with factory() as session:
        chosen = session.get(OutreachDraft, draft_id)
    monkeypatch.setattr(widget, "selected", lambda: chosen)
    widget.toggle_approval()
    assert len(warnings) == 2 and all("placeholder" in warning for warning in warnings)
    with factory() as session:
        assert not session.get(OutreachDraft, draft_id).approved
    dialog.open_website()
    assert QGuiApplication.clipboard().text() == "http://127.0.0.1/do-not-fetch"
    dialog.close()
    widget.close()
    app.processEvents()
    factory.kw["bind"].dispose()


def test_migration_backup_captures_committed_wal_and_is_not_overwritten(tmp_path):
    from local_presence_miner.database.migrations import backup_database_before_v0112

    path = tmp_path / "wal-fixture.sqlite3"
    keeper = sqlite3.connect(path)
    try:
        keeper.execute("PRAGMA journal_mode=WAL")
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        keeper.execute("CREATE TABLE seller_proof (id INTEGER PRIMARY KEY, title TEXT)")
        keeper.execute("CREATE TABLE outreach_drafts (id INTEGER PRIMARY KEY, body TEXT)")
        keeper.execute("INSERT INTO seller_proof VALUES (1, 'Committed WAL row')")
        keeper.commit()
        factory = create_session_factory(path)
        backup = backup_database_before_v0112(factory.kw["bind"])
        with sqlite3.connect(backup) as copied:
            assert copied.execute("SELECT title FROM seller_proof").fetchone() == ("Committed WAL row",)
            assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        before = hashlib.sha256(backup.read_bytes()).hexdigest()
        keeper.execute("INSERT INTO seller_proof VALUES (2, 'Newer WAL row')")
        keeper.commit()
        backup_database_before_v0112(factory.kw["bind"])
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == before
        factory.kw["bind"].dispose()
    finally:
        keeper.close()


def test_completed_search_continues_after_candidate_local_failure(tmp_path, outbound, monkeypatch):
    from local_presence_miner.config import AppConfig
    from local_presence_miner.domain.models import SearchCriteria
    from local_presence_miner.services.qualification_service import QualificationService
    from local_presence_miner.services.search_workflow import SearchWorkflow

    config = AppConfig(tmp_path, tmp_path / "durable.sqlite3", tmp_path / "fixture.log", tmp_path, sender=outbound.sender)
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    original = QualificationService.evaluate_and_store
    count = 0

    def fail_second(self, session, lead):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("Controlled second-lead failure")
        return original(self, session, lead)

    monkeypatch.setattr(QualificationService, "evaluate_and_store", fail_second)
    search_id = SearchWorkflow(config, factory).run(
        SearchCriteria("Peoria", "IL", "roofers", demo_mode=True, top_mockups=0)
    )
    with factory() as session:
        leads = list(session.scalars(select(Lead)))
        search = session.get(LeadSearch, search_id)
        assert len(leads) > 1 and all(lead.qualification_json != "{}" for lead in leads)
        assert search.lifecycle_state == "Completed With Errors"
        assert search.failed_count == 1 and search.succeeded_count == len(leads)
        assert list(session.scalars(select(OutreachDraft)))
    factory.kw["bind"].dispose()


def test_stale_rich_review_values_do_not_change_current_scores(db):
    from local_presence_miner.services.google_presence_service import GooglePresenceService
    from local_presence_miner.services.qualification_service import QualificationService

    lead = prospect(db)
    lead.google_public_data_json = '{"details_retrieved": true}'
    lead.google_rich_data_stale = True
    lead.rating, lead.review_count = 5.0, 10000
    google_before = GooglePresenceService().evaluate_and_store(db, lead)
    qualification_before = QualificationService().evaluate(db, lead)
    lead.rating, lead.review_count = 1.0, 0
    google_after = GooglePresenceService().evaluate_and_store(db, lead)
    qualification_after = QualificationService().evaluate(db, lead)
    assert google_before.strength_score == google_after.strength_score
    assert google_before.opportunity_score == google_after.opportunity_score
    assert qualification_before.score == qualification_after.score
    assert any("stale" in item for item in google_after.unknowns)


def test_competitor_relevance_is_not_used_as_website_strength():
    from local_presence_miner.domain.models import BusinessProfile, CompetitorMatch, WebsiteAudit
    from local_presence_miner.services.competitor_service import CompetitorService

    match = CompetitorMatch("nearby", "Nearby Roofing", 100, "Same niche and location")
    profile = BusinessProfile("nearby", "Nearby Roofing", "roofers", phone="555-0100", website="")
    value = CompetitorService().average_website_score([match], {"nearby": profile}, {"nearby": WebsiteAudit()})
    assert match.score == 100 and value == 0


def test_interaction_correction_regenerates_adaptive_draft_from_current_memory(db, outbound):
    from local_presence_miner.database.repositories import save_contact_interaction
    from local_presence_miner.services.adaptive_sales_asset_service import refresh_after_interaction_change

    lead = prospect(db)
    lead.qualification_class = "High Priority"
    values = dict(interaction_datetime="2026-09-01T10:00", method="Phone", direction="Outbound", outcome="Interested", notes="Fixture")
    interaction = save_contact_interaction(db, lead.id, business_goal="Better-fit jobs", **values)
    refresh_after_interaction_change(db, lead.id, outbound.sender)
    draft = db.scalar(select(OutreachDraft).where(OutreachDraft.kind == OutreachKind.INTERESTED_REPLY.value))
    assert "better-fit jobs" in draft.body.lower()
    save_contact_interaction(db, lead.id, interaction_id=interaction.id, business_goal="Clearer service information", **values)
    refresh_after_interaction_change(db, lead.id, outbound.sender)
    assert "clearer service information" in draft.body.lower() and "better-fit jobs" not in draft.body.lower()
    assert not draft.approved
