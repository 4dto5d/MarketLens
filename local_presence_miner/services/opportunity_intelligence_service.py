"""Explicit, source-bound advice with no commercial write authority."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

from filelock import FileLock, Timeout
from sqlalchemy import select, text

from local_presence_miner.config import default_app_data_dir
from local_presence_miner.database.opportunity_intelligence_repository import IntelligenceResult, IntelligenceReview, IntelligenceRun
from local_presence_miner.database.schema import ConversationAssertion, Lead, WebsiteAuditRecord
from local_presence_miner.domain.opportunity_intelligence import MODES, VERSION, canonical, digest, request_body, validate_advice
from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.delivery_packet_service import DeliveryPacketService
from local_presence_miner.services.opportunity_workflow_service import latest_worksheet, save_worksheet
from local_presence_miner.services.owner_strategy_service import project_owner_strategy
from local_presence_miner.services.prospect_finding_service import project_findings
from local_presence_miner.time_utils import utc_now


def _row_data(row) -> dict:
    return {column.name: (value.isoformat() if isinstance(value := getattr(row, column.name), datetime) else value)
            for column in row.__table__.columns}


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

    def _projection(self, session, lead_id: int, selected: list[str], include_worksheet: bool, now: datetime) -> tuple[dict, str]:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ValueError("Business no longer exists.")
        findings = project_findings(session, lead_id, now=now)
        by_ref = {item["reference"]: item for item in findings}
        if len(selected) != len(set(selected)) or not set(selected) <= set(by_ref):
            raise ValueError("Choose current findings belonging to this business.")
        worksheet = latest_worksheet(session, lead_id)
        _, pricing, context = build_adaptive_sales_plan_with_context(session, lead)
        delivery = DeliveryPacketService().build(session, lead, context=context)
        strategy = project_owner_strategy(session, lead)
        assertions = list(session.scalars(select(ConversationAssertion).where(ConversationAssertion.lead_id == lead_id)
                                         .order_by(ConversationAssertion.id)))
        audits = list(session.scalars(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead_id)
                                     .order_by(WebsiteAuditRecord.id)))
        state = digest({"lead": _row_data(lead), "findings": findings, "worksheet": worksheet,
                        "assertions": [_row_data(row) for row in assertions], "audits": [_row_data(row) for row in audits]})
        evidence = []
        for ref in selected:
            item = by_ref[ref]
            evidence.append({"id": ref, **{key: item.get(key) for key in (
                "fact_id", "finding_type", "assertion_kind", "claim", "inference", "review_state", "freshness",
                "source_matches_current", "commercial_fact_eligible", "timestamp_qualification", "recorded_at", "source_sha256")},
                "source": item.get("source") if item["valid"] else None,
                "valid": item["valid"], "qualification": "Reviewed correspondence to source is not owner confirmation or verified business truth."})
        # Even if omitted for privacy, each retained finding contributes a mandatory warning.
        warnings = [{"reference": item["reference"], "type": item["finding_type"], "review_state": item["review_state"],
                     "freshness": item["freshness"], "valid": item["valid"], "content_included": item["reference"] in selected}
                    for item in findings]
        payload: dict[str, Any] = {
            "subject": {"alias": "Selected prospect", "business_type": lead.category,
                        "geography": "No target geography included; do not infer ZIP/city/radius conclusions."},
            "evidence": evidence,
            "owner_context": {key: value for key, value in strategy.items() if key not in {"provenance", "legacy_context"}},
            "worksheet": worksheet if include_worksheet else {"state": "withheld", "record_id": worksheet.get("record_id")},
            "commercial_context": {"offer_id": context.offer_id, "scope": list(context.scope), "price_available": pricing.price_available,
                                   "qualification": lead.qualification_class, "contact_warning": "Existing contact/DNC and approval gates remain binding."},
            "delivery_context": {"ready_for_payment": delivery["ready_for_payment"], "state": delivery["state"],
                                 "missing": delivery["missing"], "prerequisites": delivery["prerequisites"],
                                 "operator_skill": "UNKNOWN unless explicitly supplied as operator planning"},
            "research_context": [],
            "coverage": {"findings": warnings, "worksheet_included": include_worksheet,
                         "limitations": ["Only selected supplied evidence; no new research or live platform documentation.",
                                         "Unincluded findings may contain decisive constraints; ask for review before concluding.",
                                         "No financial workbook, contact details or raw original AI prompt is included automatically."]},
        }
        # AI visibility observations have confidential raw prompts/responses: disclosure is selected public text only.
        for item in evidence:
            if item["finding_type"] == "ai_discoverability":
                item["source"] = {"reference": item["id"], "note": "Raw prompt/response withheld; review original in Audit Evidence."}
                item["claim"] = "A manual AI observation exists. No general visibility conclusion is supported by this packet."
                item["inference"] = "Withheld; inspect approved disclosure separately."
            if not item["valid"]:
                item["claim"] = "Unavailable or corrupt evidence; no factual conclusion is supported."
                item["inference"] = "Withheld because source integrity is invalid."
        for key in ("worksheet", "owner_context", "commercial_context", "delivery_context"):
            payload[key]["evidence_id"] = key + ":" + digest(payload[key])
        return payload, digest([state, payload])

    def prepare(self, lead_id: int, *, question: str, mode: str, model: str, account_binding: str,
                selected: list[str] | None = None, include_worksheet: bool = False, now: datetime | None = None) -> dict:
        if mode not in MODES or not question.strip() or len(question) > 4000:
            raise ValueError("Choose a mode and a question of 1–4,000 characters.")
        if not account_binding or len(account_binding) > 64:
            raise ValueError("Connect a validated account first.")
        selected = selected or []
        if len(selected) > MODES[mode][1]:
            raise ValueError("Too many selected findings for this mode.")
        clock = now or utc_now()
        with self.factory() as session:
            payload, state = self._projection(session, lead_id, selected, include_worksheet, clock)
        packet = {"schema_version": 1, "policy_version": VERSION, "mode": mode, "question": question.strip(),
                  "as_of": clock.isoformat(), **payload}
        packet["context_hash"] = digest(packet)
        body = request_body(packet, model)
        semantic = {key: value for key, value in packet.items() if key not in {"as_of", "context_hash"}}
        return {"lead_id": lead_id, "account_binding": account_binding, "model": model, "packet": packet, "body": body,
                "state_hash": state, "selected": selected, "include_worksheet": include_worksheet,
                "preview_hash": digest(body), "cache_key": digest([semantic, state, model, account_binding, VERSION])}

    def _current(self, prepared: dict, session) -> None:
        _, state = self._projection(session, prepared["lead_id"], prepared["selected"], prepared["include_worksheet"], utc_now())
        if state != prepared["state_hash"]:
            raise ValueError("Evidence or worksheet changed. Create and review a new preview.")

    def execute(self, prepared: dict, transport, *, cancel: Event, current_account) -> dict:
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
            if cached:
                result = session.scalar(select(IntelligenceResult).where(IntelligenceResult.run_id == cached.id))
                assert result is not None
                advice = validate_advice(json.loads(result.response_json)["text"], json.loads(cached.packet_json))
                return {"run_id": cached.id, "advice": advice, "cached": True}
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
                return {"run_id": run_id, "advice": advice, "cached": False}
            finally:
                # Never persist credentials or arbitrary exception messages.
                with self.factory() as session:
                    session.add(IntelligenceResult(run_id=run_id, status=status, response_json=canonical(response)))
                    session.commit()

    def adopt(self, run_id: int, *, lead_id: int, account_binding: str, item_id: str, actor: str, edited_text: str) -> int:
        if not actor.strip() or len(actor) > 200 or not edited_text.strip() or len(edited_text) > 4000:
            raise ValueError("Record an actor and bounded planning text.")
        with self.factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            run = session.get(IntelligenceRun, run_id)
            result = session.scalar(select(IntelligenceResult).where(IntelligenceResult.run_id == run_id, IntelligenceResult.status == "completed"))
            if run is None or run.lead_id != lead_id or run.account_binding != account_binding or result is None:
                raise ValueError("Advice is unavailable for this prospect/account.")
            stamp = run.created_at.replace(tzinfo=UTC) if run.created_at.tzinfo is None else run.created_at
            if utc_now() - stamp > timedelta(hours=24):
                raise ValueError("Advice expired; run a new review.")
            packet = json.loads(run.packet_json)
            selected = [item["id"] for item in packet["evidence"]]
            _, state = self._projection(session, lead_id, selected, packet["coverage"]["worksheet_included"], utc_now())
            if state != run.state_hash:
                raise ValueError("Advice is stale. Evidence or worksheet changed.")
            advice = validate_advice(json.loads(result.response_json)["text"], packet)
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
            return [{"id": run.id, "created_at": run.created_at.isoformat(), "model": run.model,
                     "status": result.status if result else "interrupted_or_running", "packet": json.loads(run.packet_json),
                     "result": json.loads(result.response_json) if result else None,
                     "reviews": [{"actor": review.actor, "created_at": review.created_at.isoformat(),
                                  "review": json.loads(review.review_json)} for review in session.scalars(
                                      select(IntelligenceReview).where(IntelligenceReview.run_id == run.id).order_by(IntelligenceReview.id))]}
                    for run, result in rows]

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
