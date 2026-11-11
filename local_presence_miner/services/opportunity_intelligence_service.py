"""Explicit, source-bound advice with no commercial write authority."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

from filelock import FileLock, Timeout
from sqlalchemy import select, text

from local_presence_miner.config import default_app_data_dir
from local_presence_miner.database.opportunity_intelligence_repository import IntelligenceResult, IntelligenceReview, IntelligenceRun
from local_presence_miner.database.schema import ActivityLog, ConversationAssertion, Lead, OfferHistory, SearchMarketQuery, SearchMarketRun, WebsiteAuditRecord
from local_presence_miner.domain.intelligence_research import affirmative_operator_evidence, context_options, selected_research
from local_presence_miner.domain.opportunity_intelligence import MODES, VERSION, canonical, digest, present_advice, request_body, validate_advice
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.opportunity_workflow_service import latest_worksheet, save_worksheet
from local_presence_miner.services.outreach_eligibility_service import OutreachEligibilityService
from local_presence_miner.services.owner_strategy_service import project_owner_strategy
from local_presence_miner.services.prospect_finding_service import project_findings
from local_presence_miner.services.search_market_analysis import project_search_market
from local_presence_miner.services.search_offer_intelligence import _latest_run, _run_matches_current_lead
from local_presence_miner.time_utils import utc_now


def _row_data(row) -> dict:
    return {column.name: (value.isoformat() if isinstance(value := getattr(row, column.name), datetime) else value)
            for column in row.__table__.columns}


def _rejected(session, run_id: int) -> bool:
    for value in session.scalars(select(IntelligenceReview.review_json).where(IntelligenceReview.run_id == run_id)):
        try:
            if json.loads(value).get("action") == "rejected":
                return True
        except (ValueError, TypeError, AttributeError):
            return True  # An uninterpretable review cannot support reuse.
    return False


def _market_context(session, lead: Lead, now: datetime) -> dict:
    """Reuse frozen/current commercial eligibility; partial/failed evidence stays diagnostic."""
    run = _latest_run(session, lead)
    if run is None:
        return {"state": "unavailable", "reason": "No matching live market run was supplied.", "eligible": False}
    descriptor = {"run_id": run.id, "state": "unavailable_or_partial", "eligible": False,
                  "lifecycle_state": run.lifecycle_state, "recorded_at": run.started_at.isoformat(),
                  "query_universe_version": run.query_universe_version,
                  "reason": "Historical acquisition does not establish current complete market coverage."}
    if not _run_matches_current_lead(session, run, lead):
        return descriptor
    try:
        projection = project_search_market(session, run.id, now=now)
    except (TypeError, ValueError):
        return descriptor
    if projection.evidence_mode != "live" or projection.coverage_denominator != projection.tracked_queries:
        return descriptor
    queries = list(session.scalars(select(SearchMarketQuery).where(SearchMarketQuery.run_id == run.id)
                                  .order_by(SearchMarketQuery.ordinal)))
    return {**descriptor, "state": "current", "eligible": True, "reason": "Complete current frozen query windows.",
            "geography": {"label": run.geography, "target_zip_code": lead.target_zip_code,
                          "radius_miles": lead.target_radius_miles,
                          "qualification": "Collected radius/window; not ZIP-pure coverage or owner-preference measurement."},
            "service_bindings": [{"query_id": row.query_id, "service_topic_id": row.service_topic_id,
                                  "geography": row.geography} for row in queries],
            "projection": asdict(projection),
            "measurement_limits": "Sampled Places windows, not exact Maps/organic rank, demand, revenue or guaranteed lift."}


def _source_entry(label: str, kind: str, value: dict, *, eligible: bool, reference: str,
                  supports: list[str] | None = None, snapshot_path: str = "") -> dict:
    return {"label": label, "kind": kind, "type": kind, "reference": reference,
            "sha256": digest(value), "eligible": eligible, "support_allowed": eligible,
            "supports": supports or [], "paid_claim_eligible": False, "snapshot_path": snapshot_path,
            "qualification": "A retained source is not automatically verified business truth or approval."}


def _finding_disclosure(item: dict) -> dict | None:
    """Project the selected fact, never its containing immutable capture."""
    if not item["valid"]:
        return None
    source = item.get("source") or {}
    if item["finding_type"] != "website_contact_path":
        return source
    capture = source.get("payload", {})
    return {"source_kind": source.get("source_kind"), "observed_at": source.get("observed_at"),
            "reference": item["reference"], "source_sha256": item.get("source_sha256"),
            "payload": {"audit_id": capture.get("audit_id"), "fact_id": item.get("fact_id"),
                        "value": capture.get("value")},
            "qualification": "Only this recorded check is disclosed; the full original capture is retained locally under this hash."}


def _agreement_context(session, lead, context, selected_price: int | None, delivery: dict) -> dict:
    """Use the ordinary payable entry point's exact offer/scope/amount identity."""
    rows = list(session.scalars(select(OfferHistory).where(OfferHistory.lead_id == lead.id)
                               .order_by(OfferHistory.offer_date.desc(), OfferHistory.id.desc())))
    latest = rows[0] if rows else None
    result = {"state": "candidate", "current_accepted": False, "reference": None,
              "historical_records": [{"reference": f"offer_history:{row.id}", "status": row.status,
                                       "sha256": digest(_row_data(row))} for row in rows[1:]]}
    if latest is None:
        return result
    historical = session.scalar(select(ActivityLog.id).where(ActivityLog.lead_id == lead.id,
        ActivityLog.action == "offer_history_saved",
        ActivityLog.message.like(f"%offer record #{latest.id}; historical_record=True%"))
        .limit(1)) is not None
    amount = latest.closed_amount or latest.final_ask or latest.initial_ask
    # A changed Won amount can itself move the current pricing recommendation.
    # Compare to the existing recorded scope/price binding, not just that output.
    review_row = (session.get(ConversationAssertion, int(delivery["review_ref"].split(":")[-1]))
                  if delivery.get("review_ref") else None)
    try:
        recorded = json.loads(review_row.value_json) if review_row else {}
    except (ValueError, TypeError):
        recorded = {}
    recorded_binding_matches = isinstance(recorded, dict) and recorded.get("binding") == delivery["binding"]
    exact = (latest.status in {"Accepted", "Won"} and not historical and bool(context.scope)
             and latest.canonical_offer_id == context.offer_id and latest.scope_summary == "; ".join(context.scope)
             and amount == selected_price and recorded_binding_matches)
    return {**result, "state": "current_accepted" if exact else "historical" if historical else "candidate",
            "current_accepted": exact, "recorded_status": latest.status, "exact_scope_and_amount": exact,
            "reference": f"offer_history:{latest.id}", "sha256": digest(_row_data(latest)),
            "qualification": "Accepted/Won history is distinct from the current delivery readiness gate."}


class LocalRequestBudget:
    """Installation-wide reservation and in-flight lock, independent of a prospect DB."""

    def __init__(self, directory: Path | None = None, daily_limit: int | None = None):
        self.directory = directory or default_app_data_dir() / "intelligence"
        if daily_limit is None:
            preferences = self.directory / "limits.json"
            daily_limit = json.loads(preferences.read_text())["daily_limit"] if preferences.exists() else 10
        if type(daily_limit) is not int or not 1 <= daily_limit <= 100:
            raise ValueError("Local daily limit must be between 1 and 100.")
        self.daily_limit = daily_limit

    @contextmanager
    def reserve(self, *, now: datetime | None = None):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.directory / "request.lock"), timeout=0)
        try:
            with lock:
                stamp = (now or datetime.now().astimezone()).isoformat()
                day = stamp[:10]
                path = self.directory / "budget.json"
                value = json.loads(path.read_text()) if path.exists() else {"day": day, "count": 0}
                if (set(value) != {"day", "count"} or not isinstance(value["day"], str)
                        or type(value["count"]) is not int or value["count"] < 0):
                    raise ValueError("Local usage record is invalid; review it before sending.")
                if day < value["day"]:
                    raise ValueError("Clock moved backwards; local request allowance was not replenished.")
                count = value["count"] if day == value["day"] else 0
                if count >= self.daily_limit:
                    raise ValueError("Local daily request limit reached. Review limits before another request.")
                temporary = path.with_suffix(".tmp")
                temporary.write_text(canonical({"day": day, "count": count + 1}), encoding="utf-8")
                os.replace(temporary, path)
                yield
        except Timeout as exc:
            raise ValueError("Another intelligence request is already active.") from exc

    def set_limit(self, value: int) -> None:
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError("Local request limit must be 1–100.")
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(self.directory / "request.lock"), timeout=0):
                path = self.directory / "limits.json"
                temporary = path.with_suffix(".tmp")
                temporary.write_text(canonical({"daily_limit": value}), encoding="utf-8")
                os.replace(temporary, path)
        except Timeout as exc:
            raise ValueError("Wait for the current request before changing limits.") from exc
        self.daily_limit = value


class OpportunityIntelligenceService:
    def __init__(self, session_factory, *, budget: LocalRequestBudget | None = None):
        self.factory = session_factory
        self.budget = budget or LocalRequestBudget()

    def _projection(self, session, lead_id: int, selected: list[str], include_worksheet: bool, now: datetime,
                    options: dict | None = None) -> tuple[dict, str]:
        options = context_options(**(options or {}))
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ValueError("Business no longer exists.")
        findings = project_findings(session, lead_id, now=now)
        by_ref = {item["reference"]: item for item in findings}
        if len(selected) != len(set(selected)) or not set(selected) <= set(by_ref):
            raise ValueError("Choose current findings belonging to this business.")
        worksheet = latest_worksheet(session, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        delivery = DeliveryPacketService().build(session, lead, context=context, selected_price=pricing.recommended)
        agreement = _agreement_context(session, lead, context, pricing.recommended, delivery)
        strategy = project_owner_strategy(session, lead)
        contact = OutreachEligibilityService().evaluate(session, lead, today=now.date())
        assertions = list(session.scalars(select(ConversationAssertion).where(ConversationAssertion.lead_id == lead_id)
                                         .order_by(ConversationAssertion.id)))
        audits = list(session.scalars(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead_id)
                                     .order_by(WebsiteAuditRecord.id)))
        state = digest({"lead": _row_data(lead), "findings": findings, "worksheet": worksheet, "owner_strategy": strategy,
                        "assertions": [_row_data(row) for row in assertions], "audits": [_row_data(row) for row in audits]})
        evidence = []
        for index, ref in enumerate(selected, start=1):
            item = by_ref[ref]
            evidence.append({"id": f"F{index}", "reference": ref, **{key: item.get(key) for key in (
                "fact_id", "finding_type", "assertion_kind", "claim", "inference", "review_state", "freshness",
                "source_matches_current", "commercial_fact_eligible", "timestamp_qualification", "recorded_at", "source_sha256")},
                "source": _finding_disclosure(item),
                "valid": item["valid"], "qualification": "Reviewed correspondence to source is not owner confirmation or verified business truth."})
        # Even if omitted for privacy, each retained finding contributes a mandatory warning.
        warnings = [{"reference": item["reference"], "type": item["finding_type"], "review_state": item["review_state"],
                     "freshness": item["freshness"], "valid": item["valid"], "content_included": item["reference"] in selected}
                    for item in findings]
        payload: dict[str, Any] = {
            "subject": {"alias": "Selected prospect", "business_type": lead.category,
                        "geography": {"business_location": "Withheld; not inferred from a target ZIP.",
                                      "owner_desired_area": strategy.get("target_territories", []) if options["include_owner_context"] else [],
                                      "measured_market_area": "Only market_context may establish collected coverage; owner preference does not."}},
            "evidence": evidence,
            "owner_context": ({key: value for key, value in strategy.items() if key not in {"legacy_context", "provenance"}}
                              if options["include_owner_context"] else {
                                  "state": strategy.get("state", "unknown"), "content_included": False,
                                  "constraints": [{"kind": fact["kind"]} for fact in strategy.get("constraints", [])],
                                  "territory_recorded": bool(strategy.get("target_territories")),
                                  "warning": "Owner instructions are withheld; their recorded state is a constraint, not disclosed wording or permission."}),
            "worksheet": worksheet if include_worksheet else {"state": "withheld", "record_id": worksheet.get("record_id")},
            "commercial_context": {"offer_id": context.offer_id, "scope": list(context.scope), "price_available": pricing.price_available,
                                   "qualification": lead.qualification_class, "selection_source": context.selection_source,
                                   "context_fingerprint": context.context_fingerprint,
                                   "selected_price": pricing.recommended, "agreement": agreement,
                                   "scope_status": ("Matching current Accepted/Won agreement; delivery readiness is checked separately."
                                                    if agreement["current_accepted"] else
                                                    "Current canonical candidate; recorded history does not establish a matching current accepted agreement."),
                                   "contact_eligibility": {"state": contact.state.value, "reasons": list(contact.reasons),
                                                           "permits_live_use": contact.permits_live_use},
                                   "contact_warning": "Existing contact/DNC and approval gates remain binding."},
            "delivery_context": {"ready_for_payment": delivery["ready_for_payment"], "state": delivery["state"],
                                 "missing": delivery["missing"],
                                 "prerequisites": [{key: value for key, value in item.items()
                                                    if key != "notes" or options["include_commercial_explanation"]}
                                                   for item in delivery["prerequisites"]],
                                 "binding": delivery["binding"], "review_ref": delivery["review_ref"],
                                 "operator_skill": "UNKNOWN unless explicitly supplied as operator planning"},
            "research_context": selected_research(options["research_ids"]),
            "coverage": {"findings": warnings, "worksheet_included": include_worksheet,
                         "limitations": ["Only selected supplied evidence; no new research or live platform documentation.",
                                         "Unincluded findings may contain decisive constraints; ask for review before concluding.",
                                         "No financial workbook, contact details or raw original AI prompt is included automatically."]},
        }
        legacy = strategy.get("legacy_context", {})
        if options["include_owner_context"]:
            payload["owner_context"]["legacy_context"] = legacy
        payload["coverage"]["owner_context"] = {
            "included": options["include_owner_context"], "recorded_fields": sorted(legacy),
            "warning": "Withheld owner statements may contain decisive constraints; do not guess their meaning."
            if legacy and not options["include_owner_context"] else "Owner reports retain their original attribution."}
        assessment = context.intervention_assessment
        rationale = {key: assessment.get(key) for key in ("version", "state", "confidence", "recommended_offer_id")}
        candidates = assessment.get("ranked_candidates", ())
        fields: tuple[str, ...] = ("intervention_id", "offer_id", "status", "confidence")
        if options["include_commercial_explanation"]:
            rationale.update({key: assessment.get(key) for key in ("summary", "unknowns", "evidence_refs", "owner_fit_status",
                                                                   "owner_fit_reason", "owner_validation_question")})
            fields += ("problem_hypothesis", "why_now", "why_over_alternatives", "falsifier", "unknowns", "evidence_refs")
        rationale["ranked_candidates"] = [{key: item.get(key) for key in fields} for item in candidates]
        payload["commercial_context"]["intervention_rationale"] = rationale
        payload["coverage"]["commercial_explanation_included"] = options["include_commercial_explanation"]
        payload["coverage"]["commercial_explanation_warning"] = "Detailed reasoning may contain owner context; withheld unless explicitly selected."
        operator = options["operator_context"]
        operator_supplied = any(operator.get(key) for key in ("experience", "demonstration", "tools", "assistance", "capacity", "limits"))
        payload["operator_context"] = {"evidence_id": "operator_context", "self_reported": True, **operator,
                                       "qualification": "Operator planning is not verified competence or execution permission."}
        if operator_supplied:
            payload["delivery_context"]["operator_skill"] = "Explicit self-reported planning supplied; review demonstration and limits."
        payload["market_context"] = (_market_context(session, lead, now) if options["include_market"] else
                                     {"state": "withheld", "eligible": False, "reason": "Market evidence was not selected."})
        payload["market_context"]["evidence_id"] = "market_context"
        payload["coverage"]["market_included"] = options["include_market"]
        # New failed captures and source changes must invalidate consumed market advice,
        # even when they produce no eligible commercial finding.
        market_rows = list(session.scalars(select(SearchMarketRun).where(SearchMarketRun.prospect_place_id == lead.place_id)
                                           .order_by(SearchMarketRun.id))) if options["include_market"] else []
        state = digest([state, [_row_data(row) for row in market_rows]])
        # AI visibility observations have confidential raw prompts/responses: disclosure is selected public text only.
        for item in evidence:
            if item["finding_type"] == "ai_discoverability":
                item["source"] = {"reference": item["reference"], "note": "Raw prompt/response withheld; review original in Audit Evidence."}
                item["claim"] = "A manual AI observation exists. No general visibility conclusion is supported by this packet."
                item["inference"] = "Withheld; inspect approved disclosure separately."
            if not item["valid"]:
                item["claim"] = "Unavailable or corrupt evidence; no factual conclusion is supported."
                item["inference"] = "Withheld because source integrity is invalid."
        for key in ("worksheet", "owner_context", "commercial_context", "delivery_context"):
            payload[key]["evidence_id"] = key
        registry = {}
        for key, label, kind, eligible in (
            ("worksheet", "Saved operator worksheet", "operator_planning", include_worksheet and worksheet.get("state") == "recorded"),
            ("owner_context", "Current owner strategy", "owner_strategy", options["include_owner_context"] and strategy.get("state") == "confirmed"),
            ("commercial_context", "Current canonical commercial decision", "app_decision", bool(context.offer_id)),
            ("delivery_context", "Current delivery and permission gate", "app_gate", True),
            ("operator_context", "Self-reported operator capabilities and limits", "operator_self_report", bool(operator_supplied)),
            ("market_context", "Selected sampled Places market evidence", "market_observation", payload["market_context"]["eligible"]),
        ):
            supports = (["operator"] if key == "operator_context" and affirmative_operator_evidence(operator) else
                        ["execution"] if key == "delivery_context" and delivery["ready_for_payment"] else [])
            registry[key] = _source_entry(label, kind, payload[key], eligible=eligible, reference=key,
                                          supports=supports, snapshot_path=key)
        for item in evidence:
            eligible = bool(item["valid"] and item.get("freshness") == "CURRENT" and item.get("commercial_fact_eligible"))
            registry[item["id"]] = _source_entry(str(item.get("fact_id") or item["finding_type"]), "prospect_finding", item,
                                                  eligible=eligible, reference=item["reference"])
            registry[item["id"]].update(review_state=item.get("review_state"), freshness=item.get("freshness"))
            registry[item["id"]]["paid_claim_eligible"] = eligible
        if options["include_owner_context"]:
            for field, item in legacy.items():
                alias = "owner_" + field
                registry[alias] = _source_entry("Recorded owner " + field, "owner_report", item,
                                                eligible=bool(item.get("confirmed_owner")),
                                                reference=",".join(item.get("evidence_refs", [])),
                                                snapshot_path="owner_context.legacy_context." + field)
                registry[alias]["snapshot"] = item
        for card in payload["research_context"]:
            registry[card["id"]] = _source_entry(card["title"], "research_method", card, eligible=True,
                                                  reference=card["card_id"] + ":" + card["version"])
        payload["source_registry"] = registry
        return payload, digest([state, payload])

    def prepare(self, lead_id: int, *, question: str, mode: str, model: str, account_binding: str,
                selected: list[str] | None = None, include_worksheet: bool = False, now: datetime | None = None,
                include_owner_context: bool = False, include_market: bool = False,
                include_commercial_explanation: bool = False, operator_context: dict | None = None,
                research_ids: list[str] | None = None, reasoning_effort: str | None = None) -> dict:
        if mode not in MODES or not question.strip() or len(question) > 4000:
            raise ValueError("Choose a mode and a question of 1–4,000 characters.")
        if not account_binding or len(account_binding) > 64:
            raise ValueError("Connect a validated account first.")
        selected = selected or []
        if len(selected) > MODES[mode][1]:
            raise ValueError("Too many selected findings for this mode.")
        clock = now or utc_now()
        options = context_options(include_owner_context=include_owner_context, include_market=include_market,
                                  include_commercial_explanation=include_commercial_explanation,
                                  operator_context=operator_context, research_ids=research_ids)
        with self.factory() as session:
            payload, state = self._projection(session, lead_id, selected, include_worksheet, clock, options)
        packet = {"schema_version": 2, "policy_version": VERSION, "mode": mode, "question": question.strip(),
                  "as_of": clock.isoformat(), "context_options": options, "reasoning_effort": reasoning_effort, **payload}
        packet["operator_context"]["task_scope"] = question.strip()
        packet["source_registry"]["operator_context"]["sha256"] = digest(packet["operator_context"])
        packet["context_hash"] = digest(packet)
        body = request_body(packet, model)
        semantic = {key: value for key, value in packet.items() if key not in {"as_of", "context_hash"}}
        cache_key = digest([semantic, state, model, account_binding, VERSION])
        return {"lead_id": lead_id, "account_binding": account_binding, "model": model, "packet": packet, "body": body,
                "state_hash": state, "selected": selected, "include_worksheet": include_worksheet,
                "preview_hash": digest(body), "cache_key": cache_key, "request_signature": cache_key}

    def _current(self, prepared: dict, session) -> None:
        _, state = self._projection(session, prepared["lead_id"], prepared["selected"], prepared["include_worksheet"], utc_now(),
                                    prepared["packet"].get("context_options"))
        if state != prepared["state_hash"]:
            raise ValueError("Evidence or worksheet changed. Create and review a new preview.")

    def execute(self, prepared: dict, transport, *, cancel: Event, current_account) -> dict:
        if prepared["packet"].get("policy_version") != VERSION:
            raise ValueError("Intelligence interpretation changed. Create and review a new preview.")
        if digest(prepared["body"]) != prepared["preview_hash"] or request_body(prepared["packet"], prepared["model"]) != prepared["body"]:
            raise ValueError("Outbound preview was changed.")
        def authorized():
            if cancel.is_set() or current_account() != prepared["account_binding"]:
                raise ValueError("Request cancelled or account changed.")
        authorized()
        with self.factory() as session:
            self._current(prepared, session)
            cached = session.scalar(select(IntelligenceRun).join(IntelligenceResult).where(
                IntelligenceRun.cache_key == prepared["cache_key"], IntelligenceResult.status == "completed",
                IntelligenceRun.created_at >= utc_now() - timedelta(hours=24)).order_by(IntelligenceRun.id.desc()))
            if cached and not _rejected(session, cached.id):
                result = session.scalar(select(IntelligenceResult).where(IntelligenceResult.run_id == cached.id))
                assert result is not None
                try:
                    packet = json.loads(cached.packet_json)
                    if packet.get("policy_version") != VERSION:
                        raise ValueError("Cached advice uses a different interpretation policy.")
                    advice = present_advice(validate_advice(json.loads(result.response_json)["text"], packet), packet)
                except (ValueError, TypeError, KeyError, AttributeError):
                    # An incompatible retained receipt cannot block an explicitly
                    # authorized fresh request. Its immutable history stays intact.
                    pass
                else:
                    return {"run_id": cached.id, "advice": advice, "packet": packet, "cached": True}
        with self.budget.reserve():
            authorized()
            with self.factory() as session:
                abandoned = list(session.scalars(select(IntelligenceRun).outerjoin(IntelligenceResult)
                                                .where(IntelligenceResult.id.is_(None))))
                for old in abandoned:
                    session.add(IntelligenceResult(run_id=old.id, status="interrupted", response_json=canonical({
                        "warning": "Previous request ended without a terminal receipt; no automatic retry.", "usage": None})))
                self._current(prepared, session)
                run = IntelligenceRun(lead_id=prepared["lead_id"], account_binding=prepared["account_binding"], model=prepared["model"],
                                      packet_json=canonical(prepared["packet"]), body_json=canonical(prepared["body"]),
                                      context_hash=prepared["packet"]["context_hash"], state_hash=prepared["state_hash"], cache_key=prepared["cache_key"])
                session.add(run)
                session.flush()
                run_id = run.id
                session.commit()
            status, response = "failed", {"warning": "Inference failed; no commercial state was changed."}
            try:
                mode = MODES[prepared["packet"]["mode"]]
                response = transport.run(prepared["body"], cancel=cancel, timeout=mode[2], max_bytes=mode[3],
                                         expected_binding=prepared["account_binding"])
                authorized()
                advice = validate_advice(response["text"], prepared["packet"])
                with self.factory() as session:
                    self._current(prepared, session)
                status = "completed"
                advice = present_advice(advice, prepared["packet"])
                response["presentation"] = advice
                return {"run_id": run_id, "advice": advice, "packet": prepared["packet"], "cached": False}
            finally:
                # Never persist credentials or arbitrary exception messages.
                with self.factory() as session:
                    session.add(IntelligenceResult(run_id=run_id, status=status, response_json=canonical(response)))
                    session.commit()

    def adopt(self, run_id: int, *, lead_id: int, account_binding: str, item_id: str, actor: str, edited_text: str,
              active_request_signature: str | None = None) -> int:
        if not actor.strip() or len(actor) > 200 or not edited_text.strip() or len(edited_text) > 4000:
            raise ValueError("Record an actor and bounded planning text.")
        with self.factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            run = session.get(IntelligenceRun, run_id)
            result = session.scalar(select(IntelligenceResult).where(IntelligenceResult.run_id == run_id, IntelligenceResult.status == "completed"))
            if run is None or run.lead_id != lead_id or run.account_binding != account_binding or result is None:
                raise ValueError("Advice is unavailable for this prospect/account.")
            if active_request_signature is not None and active_request_signature != run.cache_key:
                raise ValueError("Active request changed. Create and review a fresh brief before adopting planning text.")
            if _rejected(session, run_id):
                raise ValueError("Advice was rejected; create an explicit new review.")
            stamp = run.created_at.replace(tzinfo=UTC) if run.created_at.tzinfo is None else run.created_at
            if utc_now() - stamp > timedelta(hours=24):
                raise ValueError("Advice expired; run a new review.")
            packet = json.loads(run.packet_json)
            if packet.get("policy_version") != VERSION:
                raise ValueError("Intelligence interpretation changed. Historical advice is retained; create a new review.")
            selected = [item.get("reference", item["id"]) for item in packet["evidence"]]
            _, state = self._projection(session, lead_id, selected, packet["coverage"]["worksheet_included"], utc_now(),
                                        packet.get("context_options"))
            if state != run.state_hash:
                raise ValueError("Advice is stale. Evidence or worksheet changed.")
            advice = present_advice(validate_advice(json.loads(result.response_json)["text"], packet), packet)
            options = {item["id"]: ("owner_question", item["question"]) for item in advice["owner_questions"]}
            options.update({item["id"]: ("next_action", item["action"]) for item in advice["next_actions"]})
            if item_id not in options:
                raise ValueError("Only explicit questions and next actions can be adopted.")
            field, original = options[item_id]
            worksheet = latest_worksheet(session, lead_id)
            if worksheet["state"] != "recorded":
                raise ValueError("Save a source-attributed worksheet before adopting advice.")
            data = dict(worksheet["data"])
            addition = f"AI-assisted operator planning: {edited_text.strip()}"
            data[field] = (data[field] + "\n" + addition).strip()
            lead = session.get(Lead, lead_id)
            assert lead is not None
            row = save_worksheet(session, lead, data)
            session.add(IntelligenceReview(run_id=run_id, lead_id=lead_id, worksheet_id=row.id, actor=actor.strip(),
                                          review_json=canonical({"item_id": item_id, "field": field, "original_hash": digest(original),
                                                                 "edited_text": edited_text, "expected_worksheet": worksheet["record_id"],
                                                                 "action": "adopted_to_worksheet"})))
            session.commit()
            return row.id

    def history(self, lead_id: int) -> list[dict]:
        with self.factory() as session:
            rows = session.execute(select(IntelligenceRun, IntelligenceResult).outerjoin(IntelligenceResult).where(
                IntelligenceRun.lead_id == lead_id).order_by(IntelligenceRun.id.desc()).limit(20))
            history = []
            for run, result in rows:
                packet = json.loads(run.packet_json)
                response = json.loads(result.response_json) if result else None
                reviews = [{"actor": review.actor, "created_at": review.created_at.isoformat(),
                            "review": json.loads(review.review_json)} for review in session.scalars(
                                select(IntelligenceReview).where(IntelligenceReview.run_id == run.id).order_by(IntelligenceReview.id))]
                current, reason, advice = False, "Historical/incomplete; not available for adoption.", None
                if result and result.status == "completed" and isinstance(response, dict):
                    try:
                        advice = present_advice(validate_advice(response["text"], packet), packet)
                        stamp = run.created_at.replace(tzinfo=UTC) if run.created_at.tzinfo is None else run.created_at
                        selected = [item.get("reference", item["id"]) for item in packet["evidence"]]
                        _, state = self._projection(session, lead_id, selected, packet["coverage"]["worksheet_included"],
                                                    utc_now(), packet.get("context_options"))
                        current = (packet.get("policy_version") == VERSION and state == run.state_hash and not _rejected(session, run.id)
                                   and utc_now() - stamp <= timedelta(hours=24))
                        reason = "Current sources; explicit account-bound review still required." if current else "Stale or older policy; create a new preview."
                    except (ValueError, TypeError, KeyError, OSError):
                        reason = "Source or response unavailable/invalid; historical record retained."
                history.append({"id": run.id, "created_at": run.created_at.isoformat(), "model": run.model,
                                "status": result.status if result else "interrupted_or_running", "packet": packet,
                                "result": response, "advice": advice, "eligibility": {"current": current, "reason": reason},
                                "reviews": reviews})
            return history

    def review(self, run_id: int, *, lead_id: int, account_binding: str, actor: str, action: str) -> None:
        if action not in {"noted", "rejected"} or not actor.strip() or len(actor) > 200:
            raise ValueError("Select a review action and operator name.")
        with self.factory() as session:
            run = session.get(IntelligenceRun, run_id)
            if run is None or run.lead_id != lead_id or run.account_binding != account_binding:
                raise ValueError("Advice belongs to another business or account.")
            session.add(IntelligenceReview(run_id=run_id, lead_id=lead_id, worksheet_id=None, actor=actor,
                                          review_json=canonical({"action": action, "warning": "Review is not factual verification or commercial approval."})))
            session.commit()
