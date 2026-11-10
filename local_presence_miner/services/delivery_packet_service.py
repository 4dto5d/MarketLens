"""Reviewed manual delivery facts for one exact customer scope; no payment execution."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import ConversationAssertion, Lead
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.services.sales_evidence_service import SalesEvidenceService, current_review

DELIVERY_SUBJECT = "delivery.packet"
DELIVERY_FIELDS = {
    "payment_arrangement": "Payment arrangement / deposit / timing actually agreed",
    "account_ownership": "Owner account, domain and billing control",
    "platform_inventory": "Platform and editable selected page inventory",
    "domain_inventory": "Domain, DNS and hosting inventory",
    "email_inventory": "Email and integrations inventory / change boundaries",
    "collaborator_access": "Minimal collaborator / delegate access and removal",
    "provider_cooperation": "Existing provider cooperation / responsibilities",
    "backup_staging": "Backup, duplicate or staging method and explicit limits",
    "definition_of_done": "Definition of done for every indivisible deliverable",
    "tests": "Customer-path and technical acceptance tests",
    "owner_approval": "Owner approval checkpoints and recorded scope agreement",
    "launch_boundaries": "Authorized launch / live-change boundaries",
    "rollback": "Rollback / recovery method, limits and responsible person",
    "measurement_baseline": "Comparable measurement baseline and source coverage",
    "measurement_follow_up": "Follow-up measurement time and responsible person",
    "handoff_support": "Handoff, support responsibility and access removal",
}
DELIVERY_PREREQUISITES = {
    "ownership_authority": "Owner authority for the agreed work and assets",
    "change_access": "Ability to deliver the exact changes with appropriate access",
    "provider_dependencies": "Existing-provider and platform dependencies resolved",
    "backup_recovery": "Preservation and recovery appropriate to the scope",
    "acceptance_verification": "Feasible preview, approval and acceptance checks",
    "measurement_handoff": "Feasible measurement and customer handoff",
}
PREREQUISITE_STATES = {"unknown", "blocked", "satisfied", "not_applicable"}


def validate_prerequisites(value: dict) -> dict:
    """Explicit human decisions; narrative text never implies technical readiness."""
    if not isinstance(value, dict) or set(value) - DELIVERY_PREREQUISITES.keys():
        raise ValueError("Use only the named delivery prerequisites.")
    result = {}
    for key, item in value.items():
        if (not isinstance(item, dict) or set(item) != {"state", "notes"}
                or not isinstance(item["state"], str) or item["state"] not in PREREQUISITE_STATES
                or not isinstance(item["notes"], str) or len(item["notes"]) > 10000):
            raise ValueError("Each prerequisite requires a valid state and bounded notes.")
        if item["state"] in {"satisfied", "not_applicable"} and not _known(item["notes"]):
            raise ValueError("Satisfied or not-applicable prerequisites require a scope-specific explanation.")
        result[key] = dict(item)
    return result


def delivery_binding(lead: Lead, context, selected_price: int | None) -> str:
    # Assertion revision is deliberately excluded: recording this packet must
    # not invalidate itself. Actual selected evidence, scope and price are bound.
    decision = context.planning_inputs.get("intervention_decision", {})
    return fingerprint({"lead_id": lead.id, "place_id": lead.place_id, "offer_id": context.offer_id,
                        "scope": list(context.scope), "selected_price": selected_price,
                        "selected_decision": decision})


class DeliveryPacketService:
    def build(self, session: Session, lead: Lead, *, context=None, selected_price: int | None = None) -> dict:
        if context is None:
            from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context

            _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
            if selected_price is None:
                selected_price = pricing.recommended
        binding = delivery_binding(lead, context, selected_price)
        rows = list(session.scalars(select(ConversationAssertion).where(
            ConversationAssertion.lead_id == lead.id, ConversationAssertion.subject_key == DELIVERY_SUBJECT,
        ).order_by(ConversationAssertion.id)))
        superseded = {row.supersedes_assertion_id for row in rows}
        current = [row for row in rows if row.id not in superseded]
        row = current[0] if len(current) == 1 else None
        value = loads(row.value_json, {}) if row else {}
        bound = isinstance(value, dict) and value.get("binding") == binding
        facts = value.get("fields", {}) if bound else {}
        if (not isinstance(facts, dict) or set(facts) - DELIVERY_FIELDS.keys()
                or any(not isinstance(item, str) or len(item) > 10000 for item in facts.values())):
            facts = {}
        fields = [{"key": key, "label": label, "value": facts.get(key) or "UNKNOWN — Sammi / owner discovery required"}
                  for key, label in DELIVERY_FIELDS.items()]
        missing = [field["label"] for field in fields if not _known(field["value"])]
        try:
            decisions = validate_prerequisites(value.get("prerequisites", {}) if bound else {})
        except (ValueError, TypeError):
            decisions = {}
        prerequisites = [{"key": key, "label": label, **decisions.get(key, {"state": "unknown", "notes": ""})}
                         for key, label in DELIVERY_PREREQUISITES.items()]
        unresolved = [item["label"] for item in prerequisites if item["state"] in {"unknown", "blocked"}]
        reviewed = current_review(session, lead.id, DELIVERY_SUBJECT, binding, datetime.now(UTC))
        proof = SalesEvidenceService().build(session, lead, assessment=context.intervention_assessment,
                                             offer_id=context.offer_id, scope=context.scope)
        evidence_reviewed = not proof.selected_evidence or proof.review_state == "REVIEWED"
        ready = bool(context.price_available and context.scope and type(selected_price) is int and selected_price > 0
                     and reviewed and not missing and not unresolved and value.get("owner_approved") is True and evidence_reviewed)
        state = "reviewed" if ready else "stale" if row and not bound else "review_required"
        return {"version": 2, "lead_id": lead.id, "business_name": lead.name, "offer_id": context.offer_id,
                "scope": list(context.scope), "selected_price": selected_price, "binding": binding,
                "state": state, "ready_for_payment": ready, "fields": fields, "missing": missing,
                "prerequisites": prerequisites, "unresolved_prerequisites": unresolved,
                "reviewer": value.get("reviewer", "") if bound else "", "reviewed_at": value.get("reviewed_at", "") if bound else "",
                "source_text": row.source_text if row and bound else "",
                "review_ref": f"conversation_assertion:{row.id}" if row else "",
                "owner_approved": value.get("owner_approved") is True if bound else False,
                "evidence_reviewed": evidence_reviewed,
                "selected_evidence": proof.selected_evidence,
                "warning": "Ready only for the recorded agreement; this packet does not send payment, publish or grant account access." if ready else
                           "Not ready for a payable commitment. Resolve technical blockers/unknowns and record human and owner review first.",
                "implementation_brief": _implementation_brief(context.scope, proof.selected_evidence)}

    def record(self, session: Session, lead: Lead, *, fields: dict, selected_price: int,
               reviewer: str, source_text: str, reviewed: bool = False, owner_approved: bool = False, context=None,
               prerequisites: dict | None = None):
        from local_presence_miner.services.conversation_state_service import ConversationStateService

        if context is None:
            from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context

            _, _, context = build_adaptive_sales_plan_with_context(session, lead)
        if (not isinstance(fields, dict) or set(fields) - DELIVERY_FIELDS.keys()
                or any(not isinstance(value, str) or len(value) > 10000 for value in fields.values())):
            raise ValueError("Use only the named delivery fields with bounded manual text.")
        decisions = validate_prerequisites({} if prerequisites is None else prerequisites)
        if (type(selected_price) is not int or selected_price <= 0 or not context.price_available or not context.scope
                or not reviewer.strip() or not source_text.strip() or type(reviewed) is not bool or type(owner_approved) is not bool):
            raise ValueError("Record the actual price, supported scope, named reviewer and traceable review notes.")
        value = {"version": 1, "binding": delivery_binding(lead, context, selected_price), "fields": dict(fields),
                 "selected_price": selected_price, "reviewer": reviewer.strip(), "reviewed": reviewed,
                 "reviewed_at": datetime.now(UTC).isoformat(), "owner_approved": owner_approved,
                 "offer_id": context.offer_id, "scope": list(context.scope)}
        # Version-1 assertions remain readable and immutable. Missing structured
        # decisions in old packets are unknown; recording a correction appends.
        value["prerequisites"] = decisions
        return ConversationStateService().append_assertion(
            session, lead, subject_key=DELIVERY_SUBJECT, value=value, actor_id=reviewer,
            source_text=source_text, source_text_mode="PARAPHRASED", supersede_current=True,
        )

    def generate(self, session: Session, lead: Lead, config: AppConfig, *, context=None, selected_price: int | None = None) -> Path:
        from local_presence_miner.services.report_service import lead_artifact_slug

        packet = self.build(session, lead, context=context, selected_price=selected_price)
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "templates"),
                          autoescape=select_autoescape(["html", "xml", "html.j2", "xml.j2"]))
        html = env.get_template("delivery_packet.html.j2").render(delivery_packet=packet)
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
        path = config.output_dir / "delivery" / f"{lead_artifact_slug(lead)}-delivery--{digest}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(html, encoding="utf-8")
            path.with_suffix(".json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
        return path


def _known(value: str) -> bool:
    return bool(value.strip()) and not any(term in value.casefold() for term in ("unknown", "pending", "not recorded", "tbd", "todo"))


def _implementation_brief(scope, proof: dict) -> str:
    if tuple(scope) == ("local SEO title/meta/H1 fixes",):
        return (f'After confirming editable access to the preferred page {proof.get("page_url") or "UNKNOWN"}, review title, meta description and H1 '
                f'for the selected service {proof.get("service") or "UNKNOWN"} and query "{proof.get("query") or "UNKNOWN"}". '
                "Record current and owner-approved replacement text, implement only these fields, preserve content/routes/canonical directives, "
                "check rendered text and customer paths, and retain the approved recovery copy. No ranking improvement is promised.")
    return "Confirm and implement only the listed indivisible deliverables using the recorded access, approval and recovery plan."
