"""Two narrow adapters on an immutable, provider-neutral finding ledger."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.prospect_finding_repository import append_finding_revision, finding_head, finding_rows, finding_write_transaction
from local_presence_miner.database.repositories import audit_from_record
from local_presence_miner.database.schema import Lead, ProspectFindingRevision, WebsiteAuditRecord
from local_presence_miner.domain.ai_discoverability import AI_DISCLOSURE_VERSION, AI_SOURCE_KIND, ai_claim, ai_disclosure, ai_snapshot
from local_presence_miner.domain.commercial import canonical_json, fingerprint
from local_presence_miner.domain.models import WebsiteAudit
from local_presence_miner.domain.prospect_findings import (
    CONTACT_FACTS,
    MANUAL_ATTRIBUTIONS,
    REVIEW_STATES,
    SOURCE_ENVELOPE_VERSION,
    bounded_text,
    contact_claim,
    decode_snapshot,
    utc_text,
)
from local_presence_miner.domain.scoring import website_evidence_state
from local_presence_miner.time_utils import utc_now


def _lead(session: Session, lead_id: int) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise ValueError("Business no longer exists.")
    return lead


def contact_source_snapshot(session: Session, lead_id: int, fact_id: str, *, audit_id: int | None = None) -> dict[str, Any]:
    if fact_id not in CONTACT_FACTS:
        raise ValueError("Choose a supported website contact-path fact.")
    _lead(session, lead_id)
    audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead_id))
    if audit is None or (audit_id is not None and audit.id != audit_id):
        raise ValueError("The website source is missing or belongs to another business.")
    try:
        checks = json.loads(audit.checks_json)
    except (ValueError, TypeError):
        checks = {}
    key, _ = CONTACT_FACTS[fact_id]
    value = checks.get(key) if isinstance(checks, dict) else None
    return {"schema_version": SOURCE_ENVELOPE_VERSION, "source_kind": "website_capture.v1",
            "subject": {"lead_id": lead_id}, "observed_at": utc_text(audit.created_at),
            "payload": {"audit_id": audit.id, "url": audit.url, "final_url": audit.final_url,
                        "reachable": audit.reachable, "status_code": audit.status_code, "title": audit.title,
                        "fact_id": fact_id, "value": value if type(value) is bool else None,
                        "checks_json": audit.checks_json, "rendered_checks_json": audit.rendered_checks_json,
                        "evidence_json": audit.evidence_json, "weaknesses_json": audit.weaknesses_json,
                        "strengths_json": audit.strengths_json, "metrics_json": audit.metrics_json}}


def _review_fields(actor: str, review_state: str, review_note: str, source_checked: bool) -> dict[str, Any]:
    actor = bounded_text(actor, "Reviewer/operator", maximum=160)
    if review_state not in REVIEW_STATES or type(source_checked) is not bool:
        raise ValueError("Choose a supported review state and explicit source-check acknowledgement.")
    note = bounded_text(review_note, "Review notes", required=review_state != "UNREVIEWED")
    if review_state == "VERIFIED" and not source_checked:
        raise ValueError("Verified requires checking the recorded source and claim, with review notes.")
    return {"actor_id": actor, "review_state": review_state, "review_note": note, "source_checked": source_checked}


def _append(
    session: Session, lead_id: int, *, finding_key: str, finding_type: str, fact_id: str,
    assertion_kind: str, snapshot: dict, claim_text: str, expected_revision: int,
    actor: str, review_state: str, review_note: str, source_checked: bool,
    inference_text: str = "", owner_question: str = "",
    approve_customer_claim: bool = False,
) -> ProspectFindingRevision:
    review = _review_fields(actor, review_state, review_note, source_checked)
    row = ProspectFindingRevision(
        lead_id=lead_id, finding_key=finding_key, finding_type=finding_type, fact_id=fact_id,
        assertion_kind=assertion_kind, source_audit_id=snapshot['payload'].get('audit_id'),
        source_snapshot_json=canonical_json(snapshot), source_sha256=fingerprint(snapshot), claim_text=claim_text,
        inference_text=bounded_text(inference_text, "Possible consequence", required=False),
        owner_question=bounded_text(owner_question, "Owner question", required=False),
        customer_copy_approved=approve_customer_claim,
        customer_copy_contract_version=AI_DISCLOSURE_VERSION if approve_customer_claim else 0, **review,
    )
    _validate_row(row)
    with finding_write_transaction(session):
        append_finding_revision(session, row, expected_revision=expected_revision)
        if finding_type == "website_contact_path":
            from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

            recompute_lead_commercial_candidate(session, _lead(session, lead_id), "Website contact fact review changed")
    return row


def capture_contact_finding(
    session: Session, lead_id: int, fact_id: str, *, actor: str, audit_id: int | None = None,
    inference_text: str = "", owner_question: str = "",
) -> ProspectFindingRevision:
    snapshot = contact_source_snapshot(session, lead_id, fact_id, audit_id=audit_id)
    return _append(session, lead_id, finding_key=fact_id, finding_type="website_contact_path", fact_id=fact_id,
                   assertion_kind="OBSERVATION", snapshot=snapshot, claim_text=contact_claim(fact_id, snapshot['payload']['value']),
                   expected_revision=0, actor=actor, review_state="UNREVIEWED", review_note="", source_checked=False,
                   inference_text=inference_text, owner_question=owner_question)


def record_owner_need(
    session: Session, lead_id: int, *, actor: str, owner_label: str, source_text: str, source_ref: str,
    source_text_mode: str, attribution: str, observed_at: str | None = None,
    inference_text: str = "", owner_question: str = "",
) -> ProspectFindingRevision:
    _lead(session, lead_id)
    snapshot = _manual_snapshot(lead_id, owner_label, source_text, source_ref, source_text_mode, attribution, observed_at)
    return _append(session, lead_id, finding_key="owner_need:" + uuid4().hex, finding_type="manual_owner_need", fact_id="",
                   assertion_kind="ATTRIBUTED_STATEMENT" if attribution == "OPERATOR_REPORTED_OWNER" else "INFERENCE",
                   snapshot=snapshot, claim_text=snapshot['payload']['source_text'], expected_revision=0,
                   actor=actor, review_state="UNREVIEWED", review_note="", source_checked=False,
                   inference_text=inference_text, owner_question=owner_question)


def _legacy_manual_snapshot(lead_id, owner_label, source_text, source_ref, source_text_mode, attribution, observed_at=None):
    if attribution not in MANUAL_ATTRIBUTIONS or source_text_mode not in {"VERBATIM", "PARAPHRASED"}:
        raise ValueError("Choose explicit attribution and verbatim/paraphrased wording.")
    stamp = utc_text(datetime.fromisoformat(observed_at)) if observed_at else None
    bounded_text(source_text, "Original wording")
    return {"schema_version": SOURCE_ENVELOPE_VERSION, "source_kind": "operator_attribution.v1",
            "subject": {"lead_id": lead_id}, "observed_at": stamp,
            "payload": {"owner_label": bounded_text(owner_label, "Attributed person or context", maximum=240),
                        "source_text": source_text,
                        "source_ref": bounded_text(source_ref, "Source/reference", maximum=2000),
                        "source_text_mode": source_text_mode, "attribution": attribution}}


def _manual_snapshot(lead_id, owner_label, source_text, source_ref, source_text_mode, attribution, observed_at=None):
    if observed_at:
        parsed = datetime.fromisoformat(observed_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('Original time requires an explicit timezone offset; leave it blank when the timezone is unknown.')
    snapshot = _legacy_manual_snapshot(lead_id, owner_label, source_text, source_ref, source_text_mode, attribution, observed_at)
    snapshot['source_kind'] = 'operator_attribution.v2'
    snapshot['payload'].update(observed_at_original=observed_at, timezone_provenance='EXPLICIT_OFFSET' if observed_at else 'NOT_RECORDED')
    return snapshot


def record_ai_observation(session: Session, lead_id: int, *, actor: str, inference_text: str = "",
                          owner_question: str = "", **source_fields) -> ProspectFindingRevision:
    lead = _lead(session, lead_id)
    snapshot = ai_snapshot(lead_id, business={'name': lead.name, 'place_id': lead.place_id or '', 'website': lead.website or ''}, **source_fields)
    return _append(session, lead_id, finding_key='ai_observation:' + uuid4().hex, finding_type='ai_discoverability', fact_id='',
                   assertion_kind='MODEL_RESPONSE_OBSERVATION', snapshot=snapshot, claim_text=ai_claim(snapshot),
                   expected_revision=0, actor=actor, review_state='UNREVIEWED', review_note='', source_checked=False,
                   inference_text=inference_text, owner_question=owner_question)


def revise_finding(
    session: Session, lead_id: int, finding_key: str, *, expected_revision: int, review_state: str,
    actor: str, review_note: str, source_checked: bool = False, inference_text: str | None = None,
    owner_question: str | None = None, capture_current: bool = False, expected_source_sha256: str | None = None,
    corrected_manual_source: dict | None = None,
    corrected_ai_source: dict | None = None, approve_customer_claim: bool = False,
) -> ProspectFindingRevision:
    _lead(session, lead_id)
    head = finding_head(session, lead_id, finding_key)
    if head is None or head.revision != expected_revision:
        raise ValueError("Finding is missing or changed; reload before saving.")
    if not review_note.strip():
        raise ValueError("Every correction/review revision requires a reason.")
    snapshot = None
    claim, assertion = head.claim_text, head.assertion_kind
    if capture_current:
        if head.finding_type != "website_contact_path" or not expected_source_sha256:
            raise ValueError("Explicit source preview is required before rebasing a website review.")
        snapshot = contact_source_snapshot(session, lead_id, head.fact_id)
        if fingerprint(snapshot) != expected_source_sha256:
            raise ValueError("Website source changed since preview; reload and check the new capture.")
        claim = contact_claim(head.fact_id, snapshot['payload']['value'])
    if corrected_manual_source is not None:
        if head.finding_type != "manual_owner_need" or capture_current:
            raise ValueError("Manual wording corrections belong only to the manual owner-need adapter.")
        snapshot = _manual_snapshot(lead_id, **corrected_manual_source)
        claim = snapshot['payload']['source_text']
        assertion = "ATTRIBUTED_STATEMENT" if snapshot['payload']['attribution'] == "OPERATOR_REPORTED_OWNER" else "INFERENCE"
    if corrected_ai_source is not None:
        if head.finding_type != 'ai_discoverability' or capture_current or corrected_manual_source is not None:
            raise ValueError('AI response corrections belong only to the manual AI adapter.')
        lead = _lead(session, lead_id)
        snapshot = ai_snapshot(lead_id, business={'name': lead.name, 'place_id': lead.place_id or '', 'website': lead.website or ''}, **corrected_ai_source)
        claim, assertion = ai_claim(snapshot), 'MODEL_RESPONSE_OBSERVATION'
    if snapshot is None:
        snapshot = _validate_row(head)
    return _append(session, lead_id, finding_key=finding_key, finding_type=head.finding_type, fact_id=head.fact_id,
                   assertion_kind=assertion, snapshot=snapshot, claim_text=claim, expected_revision=expected_revision,
                   actor=actor, review_state=review_state, review_note=review_note, source_checked=source_checked,
                   inference_text=head.inference_text if inference_text is None else inference_text,
                   owner_question=head.owner_question if owner_question is None else owner_question,
                   approve_customer_claim=approve_customer_claim)


def _validate_row(row: ProspectFindingRevision) -> dict[str, Any]:
    _review_fields(row.actor_id, row.review_state, row.review_note, row.source_checked)
    if type(row.customer_copy_approved) is not bool or (row.customer_copy_approved and (
            row.finding_type != 'ai_discoverability' or row.review_state != 'VERIFIED' or not row.source_checked)):
        raise ValueError('Customer-copy approval requires a separately approved VERIFIED AI response review.')
    snapshot = decode_snapshot(row.source_snapshot_json, row.source_sha256, row.lead_id)
    payload = snapshot['payload']
    if row.finding_type == "website_contact_path":
        if (row.fact_id not in CONTACT_FACTS or row.finding_key != row.fact_id or row.assertion_kind != "OBSERVATION"
                or snapshot.get('source_kind') != 'website_capture.v1' or payload.get('fact_id') != row.fact_id
                or payload.get('audit_id') != row.source_audit_id
                or row.claim_text != contact_claim(row.fact_id, payload.get('value'))):
            raise ValueError("Website finding identity or claim does not match its source.")
        try:
            checks = json.loads(payload['checks_json'])
        except (ValueError, TypeError):
            checks = {}
        key, _ = CONTACT_FACTS[row.fact_id]
        raw = checks.get(key) if isinstance(checks, dict) else None
        expected_value = raw if type(raw) is bool else None
        if payload.get('value') != expected_value or type(payload.get('value')) is not type(expected_value):
            raise ValueError("Website finding value disagrees with its preserved source.")
    elif row.finding_type == "manual_owner_need":
        if snapshot.get('source_kind') not in {'operator_attribution.v1','operator_attribution.v2'} or row.source_audit_id is not None or row.fact_id:
            raise ValueError("Manual attribution has an invalid source kind.")
        if snapshot['source_kind'] == 'operator_attribution.v1':
            normalized = _legacy_manual_snapshot(row.lead_id, **payload, observed_at=snapshot.get('observed_at'))
        else:
            fields = {key:payload[key] for key in ('owner_label','source_text','source_ref','source_text_mode','attribution')}
            normalized = _manual_snapshot(row.lead_id, **fields, observed_at=payload['observed_at_original'])
        expected = "ATTRIBUTED_STATEMENT" if payload['attribution'] == 'OPERATOR_REPORTED_OWNER' else "INFERENCE"
        if normalized != snapshot or row.claim_text != payload['source_text'] or row.assertion_kind != expected:
            raise ValueError("Manual finding wording/attribution does not match its source.")
    elif row.finding_type == 'ai_discoverability':
        if (snapshot.get('source_kind') != AI_SOURCE_KIND or row.source_audit_id is not None or row.fact_id
                or row.assertion_kind != 'MODEL_RESPONSE_OBSERVATION'):
            raise ValueError('AI response has an invalid source identity or assertion kind.')
        normalized = ai_snapshot(row.lead_id, **payload)
        if normalized != snapshot or row.claim_text != ai_claim(snapshot):
            raise ValueError('AI observation does not match its exact recorded response envelope.')
    else:
        raise ValueError("Finding adapter is unsupported; preserve it for review.")
    return snapshot


def _freshness(stamp: object, now: datetime) -> str:
    try:
        parsed = datetime.fromisoformat(str(stamp))
        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        age = now - parsed
        if age < timedelta(0):
            return "UNKNOWN"
        return "CURRENT" if age <= timedelta(days=30) else "STALE"
    except (ValueError, TypeError, OverflowError):
        return "UNKNOWN"


def _project(session: Session, row: ProspectFindingRevision, *, now: datetime) -> dict[str, Any]:
    result = {"id": row.id, "finding_key": row.finding_key, "revision": row.revision, "finding_type": row.finding_type,
              "fact_id": row.fact_id, "assertion_kind": row.assertion_kind, "claim": row.claim_text,
              "inference": row.inference_text, "owner_question": row.owner_question,
              "review_state": row.review_state, "recorded_review_state": row.review_state, "actor": row.actor_id, "review_note": row.review_note,
              "recorded_at": utc_text(row.created_at), "source_snapshot_json": row.source_snapshot_json,
              "source_sha256": row.source_sha256, "reference": f"finding_revision:{row.id}:{row.source_sha256}",
              "valid": False, "freshness": "UNKNOWN", "source_matches_current": False, "commercial_fact_eligible": False,
              "customer_copy_approved": row.customer_copy_approved, "customer_claim_eligible": False}
    result['customer_copy_contract_version'] = row.customer_copy_contract_version
    try:
        snapshot = _validate_row(row)
        result.update(valid=True, source=snapshot, freshness=_freshness(snapshot.get('observed_at'), now))
        if row.finding_type == 'manual_owner_need':
            legacy = snapshot['source_kind'] == 'operator_attribution.v1'
            result['timestamp_qualification'] = ('Original timezone unrecorded in legacy capture; historical UTC rendering is not verified UTC.'
                if legacy else 'Explicit operator-entered offset' if snapshot['payload']['timezone_provenance'] == 'EXPLICIT_OFFSET'
                else 'Original time/timezone not recorded')
            if legacy:
                result['freshness'] = 'UNKNOWN'
        if row.finding_type == 'website_contact_path':
            current = contact_source_snapshot(session, row.lead_id, row.fact_id)
            result['source_matches_current'] = fingerprint(current) == row.source_sha256
            lead = _lead(session, row.lead_id)
            audit = session.get(WebsiteAuditRecord, row.source_audit_id)
            eligible = bool(audit and lead.website and audit.url.rstrip('/') == lead.website.rstrip('/')
                            and website_evidence_state(audit_from_record(audit)) == 'observed')
            result['commercial_fact_eligible'] = (row.review_state == 'VERIFIED' and result['source_matches_current']
                                                  and result['freshness'] == 'CURRENT' and eligible
                                                  and type(snapshot['payload'].get('value')) is bool)
        elif row.finding_type == 'ai_discoverability':
            lead = _lead(session, row.lead_id)
            identity_matches = snapshot['payload']['business'] == {'name': lead.name, 'place_id': lead.place_id or '', 'website': lead.website or ''}
            result['source_matches_current'] = identity_matches
            result['customer_claim_eligible'] = bool(identity_matches and row.review_state == 'VERIFIED'
                and row.customer_copy_approved and result['freshness'] == 'CURRENT'
                and type(row.customer_copy_contract_version) is int and row.customer_copy_contract_version == AI_DISCLOSURE_VERSION
                and _freshness(utc_text(row.created_at), now) == 'CURRENT'
                and snapshot['payload']['prospect_mention'] != 'UNCLEAR')
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        result.update(valid=False, review_state="UNKNOWN", validation_error=str(exc))
    return result


def project_findings(session: Session, lead_id: int, *, now: datetime | None = None) -> list[dict[str, Any]]:
    heads = {row.finding_key: row for row in finding_rows(session, lead_id)}
    clock = now or utc_now()
    clock = clock.replace(tzinfo=UTC) if clock.tzinfo is None else clock.astimezone(UTC)
    return [_project(session, row, now=clock) for row in heads.values()]


def finding_history(session: Session, lead_id: int, finding_key: str) -> list[dict[str, Any]]:
    return [_project(session, row, now=utc_now()) for row in finding_rows(session, lead_id) if row.finding_key == finding_key]


def validate_finding_references(session: Session, lead_id: int, references: object) -> list[str]:
    if not isinstance(references, list) or len(references) > 50 or any(not isinstance(ref, str) for ref in references):
        raise ValueError("Use at most 50 stable finding revision references.")
    for ref in references:
        _resolve_reference(session, lead_id, ref)
    return list(dict.fromkeys(references))


def _resolve_reference(session: Session, lead_id: int, reference: str) -> ProspectFindingRevision:
    match = re.fullmatch(r'finding_revision:(\d+):([a-f0-9]{64})', reference)
    if match is None:
        raise ValueError("Linked finding reference is malformed.")
    row = session.get(ProspectFindingRevision, int(match[1]))
    if row is None or row.lead_id != lead_id or row.source_sha256 != match[2]:
        raise ValueError("Linked finding is missing, corrupt or belongs to another business.")
    _validate_row(row)
    return row


def project_linked_findings(session: Session, lead_id: int, references: list[str]) -> list[dict[str, Any]]:
    results = []
    for reference in references:
        try:
            results.append(_project(session, _resolve_reference(session, lead_id, reference), now=utc_now()))
        except (ValueError, TypeError) as exc:
            results.append({"reference": reference, "valid": False, "claim": "Linked source needs review", "validation_error": str(exc)})
    return results


def held_contact_checks(session: Session, lead_id: int, *, now: datetime | None = None) -> frozenset[str]:
    """Only registered exact facts can be held; raw observations stay intact."""
    return frozenset(CONTACT_FACTS[item['finding_key']][0] for item in project_findings(session, lead_id, now=now)
                     if item['finding_key'] in CONTACT_FACTS and not item['commercial_fact_eligible'])


def approved_ai_observations(session: Session, lead_id: int, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Exact current revisions only; never a Smart Offer/ranking/pricing input."""
    return [item for item in project_findings(session, lead_id, now=now) if item['customer_claim_eligible']]


def proposal_ai_choices(session: Session, lead_id: int) -> list[dict[str, Any]]:
    """Public disclosure whitelist; never serialize a private source into exports."""
    return [{'reference':item['reference'], 'contract_version':AI_DISCLOSURE_VERSION, 'disclosure':ai_disclosure(item['source'])}
            for item in approved_ai_observations(session, lead_id)]


def selected_proposal_ai_evidence(session: Session, lead_id: int, references: list[str] | None) -> list[dict[str, Any]]:
    if references is None:
        return []
    if not isinstance(references,list) or len(references)>50 or any(not isinstance(ref,str) for ref in references):
        raise ValueError('Select at most 50 eligible AI finding revisions for this proposal.')
    if not references:
        return []
    choices = {item['reference']:item for item in proposal_ai_choices(session,lead_id)}
    if any(ref not in choices for ref in references):
        raise ValueError('Selected AI evidence is no longer eligible or belongs to another business; reselect current evidence.')
    return [choices[ref] for ref in dict.fromkeys(references)]


def reviewed_contact_audit(
    session: Session, lead: Lead, record: WebsiteAuditRecord | None, *, now: datetime | None = None,
) -> WebsiteAudit:
    """Current consumer view, separate from the immutable/historical source.

    Canonical detector strings are bound to their producing check. Free-text
    human notes are never rewritten. This adapter adjudicates passive checks;
    independent rendered observations and other providers retain their identity.
    """
    audit = audit_from_record(record)
    if not isinstance(audit.checks, dict):
        audit = replace(audit, checks={})
    if record is None:
        return audit
    if record.lead_id != lead.id:
        raise ValueError("Website source belongs to another business.")
    held = held_contact_checks(session, lead.id, now=now)
    if not held:
        return audit
    labels = {label for key, label in CONTACT_FACTS.values() if key in held}
    statements = {f'{label} not detected.' for label in labels}
    if 'sitewide_contact_path' in held:
        statements.add('Contact/quote path is weak across sampled pages.')
    return replace(audit, checks={key: value for key, value in audit.checks.items() if key not in held},
                   weaknesses=[value for value in audit.weaknesses if value not in statements],
                   strengths=[value for value in audit.strengths if value not in labels])
