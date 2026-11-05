"""Subject-bound append-only SEO checkpoints and fail-closed current projections.

Import is a local evidence recording action, not a search or a Semrush API call.
Nothing here changes contact eligibility, canonical taxonomies or outreach text.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import Lead, LeadSearch, SEOResearchSnapshot, WebsiteAuditRecord
from local_presence_miner.domain.commercial import canonical_json, fingerprint
from local_presence_miner.domain.evidence_geography import coverage_identity, fits_target, legacy_city_coverage, validate_coverage
from local_presence_miner.domain.niche_taxonomy import NICHE_TAXONOMY_VERSION, resolve_niche
from local_presence_miner.domain.seo_intelligence import analyze_seo, validate_payload
from local_presence_miner.services.query_universe_service import QUERY_UNIVERSE_VERSION
from local_presence_miner.time_utils import utc_now

MAX_IMPORT_BYTES = 2_000_000


def parse_research_json(value: str) -> dict:
    if len(value.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("SEO import exceeds the bounded two-megabyte limit.")

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError(f"Duplicate research JSON field: {key}")
            result[key] = item
        return result

    def invalid_constant(_value):
        raise ValueError("Non-finite JSON metrics are not evidence.")

    try:
        parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except RecursionError as exc:
        raise ValueError("Research nesting exceeds the supported JSON depth.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Research import must be a JSON object.")
    return parsed


def research_template(session: Session, lead: Lead, *, observation_coverage: dict | None = None) -> dict:
    """Generated queries are research hypotheses, never measured demand."""
    from local_presence_miner.services.query_universe_service import generate_query_universe

    binding = research_binding(session, lead)
    search = session.get(LeadSearch, lead.search_id)
    assert search is not None
    template = {
        "schema_version": 1, "subject": binding["subject"], "observed_at": utc_now().isoformat(),
        "source": {"provider": "manual_serp", "report": "operator-recorded query sample", "database": "manual",
                   "geography": binding["subject"]["geography"], "geo_resolution": "local",
                   "status": "partial", "reference": "Pending operator source capture", "demo": False},
        "queries": [{"query": item.query_text, "service": item.cluster_name, "service_state": "unknown",
                     "service_refs": [], "intent": "unknown", "intent_basis": "",
                     "volume": None, "difficulty": None, "organic_rank": None, "maps_rank": None,
                     "organic_window": None, "maps_window": None, "organic_complete": False, "maps_complete": False,
                     "page_url": "", "competitors": [], "serp_features": [], "refs": []}
                    for item in generate_query_universe(lead.category, search.city, search.state_region)],
        "pages": [],
    }
    if observation_coverage is not None:
        template["schema_version"] = 2
        template["source"]["coverage"] = validate_coverage(observation_coverage)
    return template


def research_binding(session: Session, lead: Lead) -> dict[str, Any]:
    search = session.get(LeadSearch, lead.search_id) if lead.search_id else None
    niche = resolve_niche(lead.category)
    geography = " ".join(part.strip() for part in (search.city, search.state_region) if part.strip()) if search else ""
    if not (lead.id and lead.place_id and lead.website and search and search.city and search.state_region and niche.resolved):
        raise ValueError("SEO research requires a persisted business, website, controlled niche and recorded city/state.")
    return {
        "subject": {"place_id": lead.place_id, "website": lead.website.rstrip("/"),
                    "geography": geography, "canonical_niche_id": niche.canonical_id},
        "target_zip_code": lead.target_zip_code or "", "target_radius_miles": lead.target_radius_miles,
        "niche_version": NICHE_TAXONOMY_VERSION, "query_version": QUERY_UNIVERSE_VERSION,
    }


def empty_research(state: str, reason: str) -> dict[str, Any]:
    return {"version": 1, "state": state, "summary": reason, "opportunities": [],
            "unknowns": ["Search opportunity and economic value remain UNKNOWN."], "limitations": [reason]}


def _current_pages(session: Session, lead: Lead, now: datetime) -> list[dict]:
    # Preserve the age of these independently collected observations; never
    # relabel old page facts as today's external research.
    from local_presence_miner.database.repositories import audit_from_record
    from local_presence_miner.domain.scoring import website_evidence_state
    from local_presence_miner.services.intervention_evidence_service import current_at
    from local_presence_miner.services.seo_page_analysis import analytical_page_sample

    audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead.id))
    if not (audit and audit.reachable and audit.url.rstrip("/") == lead.website.rstrip("/") and current_at(audit.created_at, now)):
        return []
    if website_evidence_state(audit_from_record(audit)) != "observed":
        return []
    try:
        evidence = json.loads(audit.evidence_json)
        pages = json.loads(evidence.get("seo_pages_v1", "[]"))
        if not isinstance(pages, list):
            return []
        details = json.loads(evidence.get("seo_page_details_v1", "[]"))
        identities = analytical_page_sample(pages, details)
        eligible = {row["url"] for row in identities if row.get("response_validity", {}).get("state", "legacy_unclassified")
                    in {"normal", "legacy_unclassified"}}
        stamp = audit.created_at.replace(tzinfo=UTC) if audit.created_at.tzinfo is None else audit.created_at.astimezone(UTC)
        unique_pages = {page["url"]: page for page in pages if isinstance(page, dict) and page.get("url") in eligible}
        return [{**page, "observed_at": stamp.isoformat(),
                 "source_ref": f"website_audit:{audit.id}:{fingerprint(page)}"} for page in unique_pages.values()]
    except (ValueError, TypeError, AttributeError):
        return []


def append_research(
    session: Session, lead: Lead, payload: dict, *, now: datetime | None = None,
    attach_current_pages: bool = True,
) -> SEOResearchSnapshot:
    """Validate, append and revoke material approvals in the caller's transaction.

    Malformed/foreign imports roll back without changing commercial state. A
    valid recorded failed source is a new checkpoint, not absence or old success.
    There is deliberately no internal commit or post-commit planner exception.
    """
    clock = now or utc_now()
    if len(canonical_json(payload).encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("SEO import exceeds the bounded two-megabyte limit.")
    binding = research_binding(session, lead)
    normalized = validate_payload(payload)
    if normalized["subject"] != binding["subject"]:
        raise ValueError("SEO evidence subject does not match this business, website, niche and geography.")
    if attach_current_pages and not normalized.get("pages"):
        pages = _current_pages(session, lead, clock)
        if pages:
            normalized = validate_payload({**normalized, "pages": pages})
    row = SEOResearchSnapshot(
        lead_id=lead.id, schema_version=normalized["schema_version"], binding_json=canonical_json(binding),
        payload_json=canonical_json(normalized), payload_sha256=fingerprint(normalized),
        source_status=normalized["source"]["status"], observed_at=normalized["observed_at"],
    )
    session.add(row)
    session.flush()
    from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

    # Existing targeted dependency comparison preserves unrelated locked quotes.
    # If commercial projection fails, invalidate safely but retain acquisition.
    try:
        recompute_lead_commercial_candidate(session, lead, "Current SEO evidence changed")
    except Exception as exc:
        from local_presence_miner.database.repositories import log_activity
        from local_presence_miner.services.commercial_state_service import mark_lead_commercial_stale

        mark_lead_commercial_stale(session, lead, "SEO evidence stored; commercial refresh requires review")
        log_activity(session, "seo_commercial_refresh_warning", f"Snapshot {row.id}: {type(exc).__name__}; commercial review required.", lead.id)
    return row


def project_seo_research(session: Session, lead: Lead, *, now: datetime | None = None) -> dict[str, Any]:
    """Newest checkpoint wins even when failed/stale/foreign to current context."""
    row = session.scalar(select(SEOResearchSnapshot).where(SEOResearchSnapshot.lead_id == lead.id)
                         .order_by(SEOResearchSnapshot.id.desc()).limit(1))
    if row is None:
        return empty_research("missing", "No query-scoped organic/Maps research checkpoint has been recorded.")
    try:
        binding = research_binding(session, lead)
        payload, stored_binding = _read_snapshot(row)
        if stored_binding != binding:
            return empty_research("mismatch", "Research integrity or current subject/geography binding changed; historical evidence retained.")
        if row.schema_version != payload.get("schema_version") or payload.get("subject") != binding["subject"]:
            return empty_research("mismatch", "Research subject/schema is incompatible with the current business.")
        report = analyze_seo(payload, now=now or utc_now())
    except (ValueError, TypeError, AttributeError, KeyError):
        return empty_research("invalid", "Stored research is corrupt or its current binding is unavailable; no inference made.")
    report = {**report, "snapshot_id": row.id, "snapshot_sha256": row.payload_sha256,
              "subject": binding["subject"], "observed_at": row.observed_at,
              "source": payload["source"], "commercial_plan_state": lead.commercial_plan_state}
    report["observed_coverage"] = payload["source"].get("coverage", legacy_city_coverage(payload))
    report["acquisition_target"] = {"zip_code": binding["target_zip_code"], "radius_miles": binding["target_radius_miles"]}
    # The existing acquisition selector is not a supplier's measurement scope.
    # No new stamp/hash can convert historical city observations into ZIP proof.
    from local_presence_miner.services.google_places import us_state_code

    search = session.get(LeadSearch, lead.search_id)
    state = us_state_code(search.state_region) if search else ""
    target = ({"kind": "zip", "postal_codes": [lead.target_zip_code], "country": "US", "state": state}
              if lead.target_zip_code else None)
    report["coverage_fit"] = "complete" if target is None else "unknown"
    report["coverage_limitations"] = []
    from local_presence_miner.services.owner_strategy_service import project_owner_strategy

    owner = project_owner_strategy(session, lead)
    owner_targets = owner.get("target_territories", []) if owner.get("state") == "confirmed" else []
    report["owner_target_territories"] = owner_targets
    report["coverage_basis"] = "owner-confirmed territory" if owner_targets else "operator acquisition selector"
    report["territory_coverage"] = []
    for opportunity in report.get("opportunities", []):
        coverage = opportunity["coverage"]
        fits = target is None or bool(state and fits_target(coverage, target))
        if target is None and payload["schema_version"] == 2:
            fits = bool(search and state and fits_target(coverage, {"kind": "city", "country": "US", "state": state, "city": search.city}))
        if target is not None and coverage.get("kind") == "radius":
            fits = bool(state and fits_target(coverage, {"kind": "radius", "country": "US", "state": state,
                                                       "center_postal_code": lead.target_zip_code, "radius_miles": lead.target_radius_miles}))
        opportunity["acquisition_coverage_fit"] = "complete" if fits else "unknown"
        if owner_targets:
            fits = any(fits_target(coverage, area, partial_zip=True) for area in owner_targets)
        opportunity["coverage_fit"] = "complete" if fits else "unknown" if coverage.get("kind") == "city" else "mismatch"
        if fits:
            report["coverage_fit"] = "complete"
        else:
            reason = "Recorded observation coverage does not establish the selected ZIP/circle market; retain city research and validate exact territory."
            opportunity["unknowns"] = list(dict.fromkeys([*opportunity["unknowns"], reason]))
            opportunity["selected_evidence"]["unknowns"] = opportunity["unknowns"]
            report["coverage_limitations"].append(reason)
            if opportunity["decision"] == "recommended":
                opportunity.update(decision="validate_first", confidence="low", scope=[], reason=reason)
                opportunity["selected_evidence"].update(reason=reason, hypothesis=reason, confidence="low")
    # Geography coverage is conditional on the same service/query intent. A
    # healthy water-heater observation cannot fill an emergency-plumbing gap,
    # and an informational query cannot fill a commercial-intent territory.
    service_groups: dict[tuple[str, str], list[dict]] = {}
    for op in report.get("opportunities", []):
        service_groups.setdefault((op["service"], op["intent"]), []).append(op)
    if owner_targets and not service_groups:
        # An empty failed/partial checkpoint is not territory coverage.
        service_groups[("unknown service", "unknown")] = []
    for (service, intent), opportunities in service_groups.items():
        territories = []
        for area in owner_targets:
            matching = [op for op in opportunities if fits_target(op["coverage"], area, partial_zip=True)]
            covered = [op["cluster_id"] for op in matching]
            observed_codes = {code for op in matching for code in op["coverage"].get("postal_codes", [])}
            missing_codes = sorted(set(area.get("postal_codes", [])) - observed_codes)
            territories.append({"target": area, "service": service, "intent": intent,
                                "state": "recorded" if covered and not missing_codes else "unknown",
                                "clusters": covered, "unobserved_postal_codes": missing_codes})
        report["territory_coverage"].extend(territories)
        for op in opportunities:
            op["territory_coverage"] = territories
            op["selected_evidence"]["territory_coverage"] = territories
        if any(area["state"] == "unknown" for area in territories):
            warning = (f"Some owner-confirmed target areas have no matching observations for {service} / {intent}; "
                       "do not generalize the selected scope to them.")
            report["coverage_limitations"].append(warning)
            for op in opportunities:
                op["unknowns"] = list(dict.fromkeys([*op["unknowns"], warning]))
                op["selected_evidence"]["unknowns"] = op["unknowns"]
    report["commercial_warning"] = (
        "Research storage is not commercial authorization. Review the current commercial plan before quoting or copying."
        if lead.commercial_plan_state != "current" else ""
    )
    if report.get("state") != "complete":
        # Retain raw observations in history, not in the current advice table.
        # A failed acquisition carrying partial rows is not current visibility.
        report["opportunities"] = []
        report["competitors"] = []
    ref = f"seo_snapshot:{row.id}:{row.payload_sha256}"
    for opportunity in report.get("opportunities", []):
        opportunity["evidence_refs"] = list(dict.fromkeys([ref, *opportunity.get("evidence_refs", [])]))
        opportunity["selected_evidence"]["source_refs"] = opportunity["evidence_refs"]
    return report


def research_history(session: Session, lead_id: int) -> list[dict]:
    history = []
    for row in session.scalars(select(SEOResearchSnapshot).where(SEOResearchSnapshot.lead_id == lead_id)
                              .order_by(SEOResearchSnapshot.id.desc()).limit(100)):
        item = {"id": row.id, "observed_at": row.observed_at, "created_at": row.created_at.isoformat(),
                "source_status": row.source_status, "sha256": row.payload_sha256}
        try:
            payload, binding = _read_snapshot(row)
            item.update({"binding": binding, "payload": payload, "integrity": "valid"})
        except (ValueError, TypeError, AttributeError, KeyError):
            item.update({"integrity": "invalid", "source_status": "invalid", "binding": None, "payload": None})
        history.append(item)
    return history


def _read_snapshot(row: SEOResearchSnapshot) -> tuple[dict, dict]:
    """Validate column, JSON, hash and frozen-subject consistency, also in history."""
    payload = parse_research_json(row.payload_json)
    binding = parse_research_json(row.binding_json)
    normalized = validate_payload(payload)
    if (fingerprint(payload) != row.payload_sha256 or row.schema_version != normalized["schema_version"]
            or normalized["subject"] != binding.get("subject") or normalized["source"]["status"] != row.source_status
            or normalized["observed_at"] != row.observed_at):
        raise ValueError("Stored SEO evidence hash, schema, subject or source columns are inconsistent.")
    return normalized, binding


def compare_research(session: Session, lead_id: int, before_id: int, after_id: int) -> dict:
    """Compare exact query/channel/geography observations, not inferred lift/ROI."""
    rows = [session.get(SEOResearchSnapshot, identity) for identity in (before_id, after_id)]
    if any(row is None or row.lead_id != lead_id for row in rows):
        raise ValueError("Choose two historical snapshots belonging to this business.")
    before, after = rows
    assert before is not None and after is not None
    try:
        pairs = [_read_snapshot(row) for row in (before, after)]
    except (ValueError, TypeError, AttributeError, KeyError):
        return {"comparable": False, "reason": "Historical source integrity failed.", "changes": []}
    if pairs[0][1] != pairs[1][1]:
        return {"comparable": False, "reason": "Business, geography or research context differs.", "changes": []}
    payloads = [pair[0] for pair in pairs]
    clock = utc_now()
    stamps = [payload["observed_at"] for payload in payloads]
    for payload in payloads:
        stamps.extend(coverage["observed_at"] for coverage in [payload["source"].get("coverage"),
                      *(q.get("coverage") for q in payload["queries"])] if coverage)
    if any(datetime.fromisoformat(stamp) > clock for stamp in stamps):
        return {"comparable": False, "reason": "Future observations are not historical measurement evidence.", "changes": []}
    sources = [payload["source"] for payload in payloads]
    keys = ("provider", "report", "database", "geography", "geo_resolution")
    if any(source.get("status") != "complete" or source.get("demo") is not False for source in sources) or any(
        sources[0].get(key) != sources[1].get(key) for key in keys
    ):
        return {"comparable": False, "reason": "Source method, geography or completeness differs.", "changes": []}
    if coverage_identity(sources[0].get("coverage", {})) != coverage_identity(sources[1].get("coverage", {})):
        return {"comparable": False, "reason": "Recorded observation footprints or methods differ.", "changes": []}
    maps = [{(query["query"].casefold(), fingerprint(coverage_identity(query.get("coverage", {})))): query
             for query in payload["queries"]} for payload in payloads]
    changes = []
    for query in sorted(maps[0].keys() & maps[1].keys()):
        left, right = maps[0][query], maps[1][query]
        if datetime.fromisoformat(right.get("coverage", {"observed_at": payloads[1]["observed_at"]})["observed_at"]) < datetime.fromisoformat(
            left.get("coverage", {"observed_at": payloads[0]["observed_at"]})["observed_at"]
        ):
            return {"comparable": False, "reason": "Original query capture chronology is reversed.", "changes": []}
        for channel in ("organic", "maps"):
            # Window and collection completeness are part of comparability.
            rank = f"{channel}_rank"
            if not (left.get(f"{channel}_complete") is True and right.get(f"{channel}_complete") is True
                    and left.get(f"{channel}_window") == right.get(f"{channel}_window")):
                continue
            if left.get(rank) is not None and right.get(rank) is not None:
                changes.append({"query": left["query"], "channel": channel, "before": left[rank], "after": right[rank],
                                "coverage": left.get("coverage", legacy_city_coverage(payloads[0])),
                                "positions_improved": left[rank] - right[rank]})
            for url in sorted({item["url"] for item in left.get("competitors", []) if item["channel"] == channel}
                              | {item["url"] for item in right.get("competitors", []) if item["channel"] == channel}):
                positions = [next((item["position"] for item in side.get("competitors", [])
                                   if item["url"] == url and item["channel"] == channel), None) for side in (left, right)]
                changes.append({"query": left["query"], "channel": channel, "competitor_url": url,
                                "before": positions[0], "after": positions[1],
                                "limitation": "Missing competitor position means not recorded in this sample, not vanished from search."})
    return {"comparable": True, "changes": changes,
            "limitation": "Comparable recorded observations only; causality, conversions and incremental revenue remain unproven."}
