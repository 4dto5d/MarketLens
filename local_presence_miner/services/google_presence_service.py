from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import audit_from_record, dumps, loads
from local_presence_miner.database.schema import CompetitorRecord, GooglePresenceAssessment, Lead
from local_presence_miner.domain.scoring import website_evidence_state, website_quality_score
from local_presence_miner.time_utils import utc_now

COMPETITOR_EVIDENCE_MAX_AGE = timedelta(days=30)


@dataclass(frozen=True)
class GooglePresenceResult:
    strength_score: int
    opportunity_score: int
    confidence: str
    observed_strengths: tuple[str, ...]
    observed_gaps: tuple[str, ...]
    unknowns: tuple[str, ...]
    provenance: tuple[dict[str, Any], ...]
    competitor_summary: tuple[str, ...]
    recommended_action: str
    top_issue: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GooglePresenceService:
    """Assess public Google/Maps evidence without implying private GBP access.

    Strength describes what is visibly present. Opportunity describes the amount
    of evidence-backed improvement available. Neither score is a probability.
    """

    def evaluate(self, session: Session, lead: Lead) -> GooglePresenceResult:
        competitors = list(
            session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars()
        )
        snapshots = [snapshot for item in competitors if (snapshot := self._competitor_snapshot(session, item))]
        current_snapshots = [snapshot for snapshot in snapshots if _current_competitor_snapshot(snapshot)]
        public_data = loads(lead.google_public_data_json, {})
        stale_rich_data = bool(getattr(lead, "google_rich_data_stale", False))
        details_retrieved = bool(public_data.get("details_retrieved")) and not stale_rich_data
        audit = audit_from_record(lead.audit)
        website_known = (not lead.website and details_retrieved) or (
            bool(lead.website) and website_evidence_state(audit) != "unknown"
        )
        website_score = website_quality_score(audit, bool(lead.website)) if website_known else None

        strengths: list[str] = []
        gaps: list[str] = []
        unknowns: list[str] = []
        strength = 0

        status = (lead.business_status or "").upper()
        if status == "CLOSED_PERMANENTLY":
            return self._closed_result(lead, snapshots)
        if status == "OPERATIONAL":
            strength += 15
            strengths.append("Google Places reports the business as operational.")
        elif status:
            strength += 5
            unknowns.append(f"Public business status is {lead.business_status}; confirm current operations manually.")
        else:
            unknowns.append("Operational status was not returned by the public source.")

        if stale_rich_data:
            unknowns.append("The last rich Google snapshot is preserved but stale because the most recent detail refresh failed.")
        elif not details_retrieved:
            unknowns.append("Public rating and review count were not requested in the discovery-stage field mask.")
        elif lead.rating is None:
            unknowns.append("A public Google rating was not returned by the rich-detail request.")
        else:
            rating_points = round(max(0.0, min(1.0, (lead.rating - 3.0) / 2.0)) * 20)
            strength += rating_points
            if lead.rating >= 4.5:
                strengths.append(f"Public rating is strong at {lead.rating:.1f}.")
            elif lead.rating < 4.0 and lead.review_count >= 10:
                gaps.append(f"Public rating is {lead.rating:.1f} across {lead.review_count} review(s).")

        review_points = review_strength_points(lead.review_count) if details_retrieved else 0
        strength += review_points
        if details_retrieved:
            if lead.review_count >= 20:
                strengths.append(f"The profile has {lead.review_count} public review(s).")
            elif lead.review_count > 0:
                strengths.append(f"The profile has early public proof from {lead.review_count} review(s).")
            else:
                unknowns.append("The rich-detail request returned no public reviews; this is not treated as automatic rejection.")

        observable_fields = {
            "phone": details_retrieved and bool(lead.phone or public_data.get("international_phone")),
            "website": details_retrieved and bool(lead.website),
            "hours": details_retrieved and bool(lead.has_hours),
            "maps link": bool(lead.google_maps_url),
            "primary type": bool(lead.primary_type or loads(lead.business_types_json, [])),
        }
        field_points = {"phone": 7, "website": 7, "hours": 6, "maps link": 3, "primary type": 7}
        detail_only = {"phone", "website", "hours"}
        for label, present in observable_fields.items():
            if present:
                strength += field_points[label]
            elif label in detail_only and not details_retrieved:
                unknowns.append(f"Public {label} was not requested in the discovery-stage field mask.")
            else:
                gaps.append(f"A public {label} was not returned by Google Places.")

        if stale_rich_data:
            unknowns.append("Photo evidence is retained from the last successful Google detail snapshot and must be refreshed before outreach claims.")
        elif not details_retrieved:
            unknowns.append("Photo references were not requested in the discovery-stage field mask.")
        elif lead.photo_count >= 10:
            strength += 10
            strengths.append(f"Google returned {lead.photo_count} public photo reference(s).")
        elif lead.photo_count > 0:
            strength += min(9, 2 + lead.photo_count)
            gaps.append(f"Only {lead.photo_count} public photo reference(s) were returned.")
        else:
            gaps.append("No public photo references were returned.")

        strength = max(0, min(100, strength))
        competitor_summary, competitor_gap_points = compare_with_competitors(lead, current_snapshots, details_retrieved)

        opportunity = 0
        if details_retrieved and (lead.rating is not None or lead.review_count):
            opportunity += min(10, 3 + review_strength_points(lead.review_count) // 2)
        elif status == "OPERATIONAL":
            opportunity += 3
        opportunity += min(
            25,
            sum(
                field_points[label]
                for label, present in observable_fields.items()
                if not present and (label not in detail_only or details_retrieved)
            ),
        )
        if details_retrieved and lead.photo_count == 0:
            opportunity += 7
        elif details_retrieved and lead.photo_count < 5:
            opportunity += 4
        opportunity += competitor_gap_points

        if website_score is not None and website_score < 45 and details_retrieved and lead.rating is not None and lead.rating >= 4.4:
            opportunity += 22
            gaps.insert(0, "Strong public Google reputation is not matched by the current website experience.")
        elif details_retrieved and not lead.website and (lead.review_count > 0 or lead.rating is not None):
            opportunity += 20
            gaps.insert(0, "The active public Google presence does not link to a business-owned website.")
        elif website_score is not None and website_score >= 75 and strength < 55:
            opportunity += 14
            gaps.insert(0, "The website is stronger than the observable public Google presence.")
        elif website_score is not None and website_score >= 75 and strength >= 75:
            opportunity = max(0, opportunity - 12)
            strengths.append("Website and public Google evidence both appear comparatively strong.")

        evidence_fields = sum(
            [
                bool(status),
                details_retrieved and lead.rating is not None,
                details_retrieved and lead.review_count > 0,
                bool(lead.google_maps_url),
                bool(lead.primary_type or loads(lead.business_types_json, [])),
                bool(lead.google_retrieved_at),
                details_retrieved,
                bool(current_snapshots),
            ]
        )
        confidence = "Strong" if evidence_fields >= 6 and current_snapshots else "Moderate" if evidence_fields >= 4 else "Low"
        if confidence == "Low":
            opportunity = min(opportunity, 35)
            unknowns.append("Public Google evidence is too limited for a confident offer decision.")

        opportunity = max(0, min(100, opportunity))
        action = recommended_action(website_score, opportunity, confidence, strength)
        top_issue = gaps[0] if gaps else "No material public Google gap is currently evidenced."
        provenance = build_provenance(lead, snapshots)
        return GooglePresenceResult(
            strength_score=strength,
            opportunity_score=opportunity,
            confidence=confidence,
            observed_strengths=tuple(dict.fromkeys(strengths)),
            observed_gaps=tuple(dict.fromkeys(gaps)),
            unknowns=tuple(dict.fromkeys(unknowns)),
            provenance=tuple(provenance),
            competitor_summary=tuple(competitor_summary),
            recommended_action=action,
            top_issue=top_issue,
        )

    def evaluate_and_store(self, session: Session, lead: Lead) -> GooglePresenceResult:
        result = self.evaluate(session, lead)
        record = session.execute(
            select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead.id)
        ).scalar_one_or_none()
        previous = None if record is None else {
            "strength_score": record.google_presence_score,
            "opportunity_score": record.opportunity_score,
            "confidence": record.confidence,
            "observed_strengths_json": record.observed_strengths_json,
            "observed_gaps_json": record.observed_gaps_json,
            "unknowns_json": record.unknowns_json,
            "competitor_summary_json": record.competitor_summary_json,
            "recommended_action": record.recommended_action,
            "top_issue": record.top_issue,
        }
        if record is None:
            record = GooglePresenceAssessment(lead_id=lead.id)
            session.add(record)
        record.google_presence_score = result.strength_score
        record.opportunity_score = result.opportunity_score
        record.confidence = result.confidence
        record.observed_strengths_json = dumps(result.observed_strengths)
        record.observed_gaps_json = dumps(result.observed_gaps)
        record.unknowns_json = dumps(result.unknowns)
        record.provenance_json = dumps(result.provenance)
        record.competitor_summary_json = dumps(result.competitor_summary)
        record.recommended_action = result.recommended_action
        record.top_issue = result.top_issue
        record.generated_at = utc_now()
        session.flush()
        current = {
            "strength_score": record.google_presence_score,
            "opportunity_score": record.opportunity_score,
            "confidence": record.confidence,
            "observed_strengths_json": record.observed_strengths_json,
            "observed_gaps_json": record.observed_gaps_json,
            "unknowns_json": record.unknowns_json,
            "competitor_summary_json": record.competitor_summary_json,
            "recommended_action": record.recommended_action,
            "top_issue": record.top_issue,
        }
        if previous != current:
            from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

            recompute_lead_commercial_candidate(session, lead, "Google Presence Intelligence changed commercial planning inputs")
        return result

    def _competitor_snapshot(self, session: Session, record: CompetitorRecord) -> dict[str, Any]:
        snapshot = loads(record.google_snapshot_json, {})
        if snapshot:
            return snapshot
        candidate = session.execute(select(Lead).where(Lead.place_id == record.competitor_place_id)).scalar_one_or_none()
        if candidate is None:
            return {}
        return {
            "place_id": candidate.place_id,
            "name": candidate.name,
            "business_status": candidate.business_status,
            "primary_type": candidate.primary_type,
            "rating": candidate.rating,
            "review_count": candidate.review_count,
            "website": bool(candidate.website),
            "phone": bool(candidate.phone),
            "hours": candidate.has_hours,
            "photo_count": candidate.photo_count,
            "retrieved_at": candidate.last_rich_google_retrieved_at,
            "details_retrieved": bool(loads(candidate.google_public_data_json, {}).get("details_retrieved"))
            and not candidate.google_rich_data_stale,
        }

    def _closed_result(self, lead: Lead, snapshots: list[dict[str, Any]]) -> GooglePresenceResult:
        issue = "Google Places reports this business as permanently closed; do not treat it as an outreach opportunity."
        return GooglePresenceResult(
            strength_score=0,
            opportunity_score=0,
            confidence="Strong" if lead.google_retrieved_at else "Moderate",
            observed_strengths=(),
            observed_gaps=(issue,),
            unknowns=(),
            provenance=tuple(build_provenance(lead, snapshots)),
            competitor_summary=(),
            recommended_action="Research-first / insufficient evidence",
            top_issue=issue,
        )


def review_strength_points(review_count: int) -> int:
    if review_count <= 0:
        return 0
    if review_count < 5:
        return 2
    if review_count < 15:
        return 5
    if review_count < 40:
        return 8
    if review_count < 100:
        return 12
    return 15


def _current_competitor_snapshot(snapshot: dict[str, Any]) -> bool:
    observed = snapshot.get("retrieved_at")
    if not observed or not snapshot.get("details_retrieved"):
        return False
    try:
        timestamp = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        age = utc_now() - timestamp.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return False
    return timedelta(0) <= age <= COMPETITOR_EVIDENCE_MAX_AGE


def compare_with_competitors(lead: Lead, snapshots: list[dict[str, Any]], target_details_retrieved: bool = True) -> tuple[list[str], int]:
    comparable = [item for item in snapshots if _current_competitor_snapshot(item)]
    if not comparable:
        return ["No current selected competitor Google evidence is available yet; older or undated snapshots are excluded."], 0
    summaries: list[str] = []
    points = 0
    ratings = [float(item["rating"]) for item in comparable if item.get("rating") is not None]
    reviews = [int(item.get("review_count") or 0) for item in comparable if item.get("details_retrieved")]
    if target_details_retrieved and lead.rating is not None and ratings:
        stronger = sum(lead.rating > rating for rating in ratings)
        summaries.append(f"Target rating exceeds {stronger} of {len(ratings)} selected competitor(s).")
        if lead.rating + 0.2 < median(ratings):
            points += 8
    if target_details_retrieved and reviews:
        higher = sum(lead.review_count < count for count in reviews)
        if higher:
            summaries.append(f"Target review volume trails {higher} of {len(reviews)} selected competitor(s).")
        else:
            summaries.append("Target review volume does not trail the selected comparison set.")
        competitor_median = median(reviews)
        if competitor_median >= max(20, lead.review_count * 2):
            points += 12
        elif competitor_median > lead.review_count:
            points += 6
    competitor_sites = sum(bool(item.get("website")) for item in comparable if item.get("details_retrieved"))
    if target_details_retrieved and not lead.website and competitor_sites:
        summaries.append(f"{competitor_sites} selected competitor(s) have linked websites; the target does not.")
        points += 8
    elif target_details_retrieved and lead.website and competitor_sites == len(comparable):
        summaries.append("Target and all selected competitors have linked websites.")
    competitor_hours = sum(bool(item.get("hours")) for item in comparable if item.get("details_retrieved"))
    if target_details_retrieved and not lead.has_hours and competitor_hours:
        summaries.append(f"Public hours are present for {competitor_hours} selected competitor(s) but not the target.")
        points += 4
    return summaries, min(28, points)


def recommended_action(website_score: int | None, google_opportunity: int, confidence: str, strength: int) -> str:
    if confidence == "Low":
        return "Research-first / insufficient evidence"
    if website_score is None:
        return "Research-first / website audit required"
    website_opportunity = 100 - website_score
    if website_opportunity >= 45 and strength >= 70:
        return "Website-only"
    if website_opportunity >= 45 and google_opportunity >= 45:
        return "Website + Google Presence"
    if google_opportunity >= 45 and website_opportunity < 45:
        return "Google Presence-only"
    if website_opportunity >= 45 and google_opportunity < 45:
        return "Website-only"
    if strength >= 75:
        return "Research-first / already strong"
    return "Research-first / insufficient evidence"


def build_provenance(lead: Lead, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_data = loads(lead.google_public_data_json, {})
    source = public_data.get("source") or "Public Google Places data"
    details_retrieved = bool(public_data.get("details_retrieved"))
    retrieved = lead.google_retrieved_at or ""
    entries: list[dict[str, Any]] = [
        {
            "provider": source,
            "place_id": lead.place_id,
            "subject": f"Target: {lead.name}",
            "retrieved_at": retrieved,
            "public_fields": ["businessStatus", "primaryType/types", "formattedAddress", "location", "googleMapsUri"],
            "derived": False,
            "human_readable": "Target discovery-stage public Google fields; rich fields have a separate observation date.",
        }
    ]
    if details_retrieved:
        stale = bool(lead.google_rich_data_stale)
        entries.append(
            {
                "provider": source,
                "place_id": lead.place_id,
                "subject": f"Target rich details: {lead.name}",
                "retrieved_at": lead.last_rich_google_retrieved_at or "",
                "public_fields": ["rating/userRatingCount", "websiteUri/nationalPhoneNumber", "regularOpeningHours", "photos"],
                "derived": False,
                "human_readable": (
                    "Prior rich snapshot retained after a failed refresh; not current assessment evidence."
                    if stale else "Target rich public fields from the last successful detail retrieval."
                ),
            }
        )
    for snapshot in snapshots:
        entries.append(
            {
                "provider": source,
                "place_id": snapshot.get("place_id", ""),
                "subject": f"Competitor: {snapshot.get('name', 'Unknown')}",
                "retrieved_at": snapshot.get("retrieved_at") or "",
                "public_fields": ["rating", "review_count", "website", "phone", "hours", "photo_count"],
                "derived": False,
                "human_readable": (
                    "Current selected competitor public fields used for comparison."
                    if _current_competitor_snapshot(snapshot)
                    else "Stale or undated competitor snapshot; excluded from scored comparison."
                ),
            }
        )
    entries.append(
        {
            "provider": "Local Presence Miner",
            "place_id": lead.place_id,
            "subject": "Derived assessment",
            "retrieved_at": utc_now().isoformat(timespec="seconds"),
            "public_fields": ["strength", "opportunity", "competitor context", "website alignment"],
            "derived": True,
            "human_readable": "Scores and recommendations are derived from the listed public observations; they are not probabilities or Maps rankings.",
        }
    )
    return entries


def assessment_to_dict(record: GooglePresenceAssessment | None) -> dict[str, Any]:
    if record is None:
        return {}
    return {
        "strength_score": record.google_presence_score,
        "opportunity_score": record.opportunity_score,
        "confidence": record.confidence,
        "observed_strengths": loads(record.observed_strengths_json, []),
        "observed_gaps": loads(record.observed_gaps_json, []),
        "unknowns": loads(record.unknowns_json, []),
        "provenance": loads(record.provenance_json, []),
        "competitor_summary": loads(record.competitor_summary_json, []),
        "recommended_action": record.recommended_action,
        "top_issue": record.top_issue,
        "generated_at": record.generated_at.isoformat() if record.generated_at else "",
    }
