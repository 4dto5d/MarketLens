from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import (
    audit_from_record,
    dumps,
    get_google_presence_assessment,
    invalidate_contact_readiness,
    lead_google_details_retrieved,
    list_contact_points,
    loads,
)
from local_presence_miner.database.schema import CompetitorRecord, Lead
from local_presence_miner.domain.competitor_matching import is_likely_chain
from local_presence_miner.domain.niche_taxonomy import commercial_class
from local_presence_miner.domain.scoring import website_evidence_state, website_quality_score
from local_presence_miner.services.outreach_planner import build_outreach_channel_plan
from local_presence_miner.services.pricing_calibration import estimate_project_value, round_price


@dataclass(frozen=True)
class QualificationFactor:
    key: str
    label: str
    points: int
    evidence: str


@dataclass(frozen=True)
class QualificationResult:
    score: int
    classification: str
    confidence: str
    factors: tuple[QualificationFactor, ...]
    positives: tuple[str, ...]
    disconfirmers: tuple[str, ...]
    unknowns: tuple[str, ...]
    next_action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "classification": self.classification,
            "confidence": self.confidence,
            "factors": [asdict(item) for item in self.factors],
            "positives": list(self.positives),
            "disconfirmers": list(self.disconfirmers),
            "unknowns": list(self.unknowns),
            "next_action": self.next_action,
        }


class QualificationService:
    """Rank prospect usefulness separately from website opportunity.

    Growth Score answers: how much public-facing improvement appears available?
    Sales Priority answers: is this business worth the operator's attention now?

    Review count is intentionally a weighted activity signal, never a hard minimum.
    """

    def evaluate(self, session: Session, lead: Lead) -> QualificationResult:
        competitors = list(session.execute(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)).scalars())
        contacts = list_contact_points(session, lead.id)
        audit = audit_from_record(lead.audit)
        details_retrieved = lead_google_details_retrieved(lead) and not bool(getattr(lead, "google_rich_data_stale", False))
        target_website_score = (
            website_quality_score(audit, bool(lead.website))
            if (not lead.website and details_retrieved) or (lead.website and website_evidence_state(audit) != "unknown")
            else None
        )
        competitor_scores = self._competitor_website_scores(session, competitors)
        competitor_average = round(sum(competitor_scores) / len(competitor_scores)) if competitor_scores else 0
        competitor_gap = competitor_average - target_website_score if competitor_scores and target_website_score is not None else 0
        plan = build_outreach_channel_plan(lead, contacts)
        project = estimate_project_value(lead, competitors)
        # Preserve the historical Qualification heuristic for the same lead and
        # catalog ID. Quotation now uses an unadjusted service-cost band; changing
        # that shared helper must not silently reclassify contact/triage state.
        # This local compatibility calculation is NOT a quote or buyer-value claim.
        catalog_low, catalog_high = project.low, project.high
        if catalog_low is not None and catalog_high is not None:
            if lead.lead_score >= 75:
                project = replace(project, low=round_price(catalog_low * 1.15), high=round_price(catalog_high * 1.15))
            elif lead.lead_score < 45:
                project = replace(project, low=round_price(catalog_low * 0.8), high=round_price(catalog_high * 0.85))
        google_presence = get_google_presence_assessment(session, lead.id)
        uses_google_presence = google_presence is not None
        website_observed = (not lead.website and details_retrieved) or website_evidence_state(audit) != "unknown"

        factors: list[QualificationFactor] = []
        positives: list[str] = []
        disconfirmers: list[str] = []
        unknowns: list[str] = []

        def add(key: str, label: str, points: int, evidence: str) -> None:
            if points:
                factors.append(QualificationFactor(key, label, points, evidence))

        # 20-25 points: documented website improvement opportunity. The legacy
        # 25-point weighting remains when no Google assessment exists.
        website_cap = 20 if uses_google_presence else 25
        opportunity = max(0, min(website_cap, round(lead.lead_score * website_cap / 100)))
        add(
            "growth_opportunity",
            "Documented online opportunity",
            opportunity,
            f"Growth Score {lead.lead_score}/100 contributes {opportunity}/{website_cap} to Sales Priority.",
        )
        if lead.lead_score >= 60:
            positives.append("The public audit shows a meaningful improvement opportunity.")
        elif lead.lead_score < 35:
            disconfirmers.append("The current audit shows relatively little improvement opportunity.")

        if google_presence is not None:
            google_points = max(0, min(12, round(google_presence.opportunity_score * 0.12)))
            add(
                "google_presence_opportunity",
                "Google Presence opportunity",
                google_points,
                f"Google Presence Opportunity {google_presence.opportunity_score}/100 contributes {google_points}/12; "
                f"evidence confidence {google_presence.confidence}.",
            )
            google_gaps = loads(google_presence.observed_gaps_json, [])
            google_strengths = loads(google_presence.observed_strengths_json, [])
            if google_presence.opportunity_score >= 55 and google_gaps:
                positives.append("Public Google evidence adds a material, separately scored improvement opportunity.")
            if google_presence.opportunity_score < 25 and google_presence.google_presence_score >= 75:
                disconfirmers.append("Public Google presence is already comparatively strong; do not sell Google work without another verified gap.")
            if google_presence.confidence == "Low":
                unknowns.append("Google Presence evidence is low-confidence and should be researched before it affects outreach claims.")
            if google_strengths:
                positives.append(str(google_strengths[0]))

        # 18-20 points: signs this is a real, active local business. Reviews are nonlinear and are not a cutoff.
        activity = 0
        activity_evidence: list[str] = []
        if details_retrieved:
            activity = review_activity_points(lead.review_count)
            activity_evidence.append(f"{lead.review_count} public review(s)")
            if lead.rating is None:
                unknowns.append("The rich-detail request did not return a public rating.")
            elif lead.rating >= 4.5:
                activity += 4
                activity_evidence.append(f"{lead.rating:.1f} rating")
                positives.append("Strong public rating suggests the underlying business has customer trust.")
            elif lead.rating >= 4.0:
                activity += 3
                activity_evidence.append(f"{lead.rating:.1f} rating")
            elif lead.rating >= 3.5:
                activity += 1
                activity_evidence.append(f"{lead.rating:.1f} rating")
            elif lead.review_count >= 10:
                disconfirmers.append(f"Rating is only {lead.rating:.1f} across {lead.review_count} reviews.")
            if lead.has_hours:
                activity += 2
                activity_evidence.append("public hours")
            if lead.phone:
                activity += 1
                activity_evidence.append("public business phone")
            if lead.photo_count >= 5:
                activity += 1
                activity_evidence.append(f"{lead.photo_count} public photos")
        else:
            unknowns.append("Rating, reviews, phone, hours, photos, and website were not requested during cheap discovery.")
            if (lead.business_status or "").upper() == "OPERATIONAL":
                activity = 2
                activity_evidence.append("operational status from discovery")
        activity_cap = 18 if uses_google_presence else 20
        activity = min(activity_cap, activity)
        add("business_activity", "Business activity / establishment", activity, ", ".join(activity_evidence) + ".")
        if details_retrieved and 5 <= lead.review_count < 20:
            positives.append("The business has customer proof even though it is still relatively small online.")
        elif details_retrieved and lead.review_count >= 20:
            positives.append("Review volume gives useful evidence that the business is established and active.")
        elif details_retrieved and lead.review_count == 0:
            unknowns.append("No public reviews were collected; activity needs more manual confirmation.")

        # 15 points: nearby competitors make the opportunity easier to demonstrate.
        competitor_points = 0
        if competitor_scores and target_website_score is not None:
            if competitor_gap >= 30:
                competitor_points += 12
            elif competitor_gap >= 15:
                competitor_points += 9
            elif competitor_gap >= 5:
                competitor_points += 5
            elif competitor_gap > 0:
                competitor_points += 2
            avg_match = round(sum(c.match_score for c in competitors) / len(competitors)) if competitors else 0
            if avg_match >= 75:
                competitor_points += 3
            elif avg_match >= 55:
                competitor_points += 2
            elif avg_match >= 40:
                competitor_points += 1
            competitor_cap = 12 if uses_google_presence else 15
            add(
                "competitor_disadvantage",
                "Competitor disadvantage",
                min(competitor_cap, competitor_points),
                f"Target website {target_website_score}/100; comparable average {competitor_average}/100; "
                f"gap {competitor_gap:+d}; average match {avg_match}/100.",
            )
            if competitor_gap >= 15:
                positives.append("Nearby comparable businesses present materially stronger websites.")
            elif competitor_gap <= 0 and target_website_score >= 70:
                disconfirmers.append("Selected competitors do not currently show a meaningful website advantage.")
        else:
            unknowns.append("No audited comparable competitors are available yet.")

        # 15 points: can the operator actually reach the prospect?
        channel_points = {
            "Email": 15,
            "Phone": 12,
            "Contact form": 9,
            "Contact research": 2 if lead.website else 0,
            "Do not contact": 0,
        }.get(plan.primary_channel, 0)
        add("contactability", "Public contactability", channel_points, f"{plan.primary_channel}: {plan.reason}")
        if plan.primary_channel == "Email":
            positives.append("A usable public email route is available.")
        elif plan.primary_channel == "Phone":
            positives.append("A usable public business phone is available.")
        elif plan.primary_channel == "Contact form":
            positives.append("A public digital contact route exists, though it is less direct.")
        elif plan.primary_channel == "Contact research":
            disconfirmers.append("No usable public contact route has been found yet.")

        # 15 points: rough commercial leverage. This is not a claim about ability to pay.
        category_points, category_reason = category_commercial_points(lead.category)
        project_points = project_value_points(project.low, project.high)
        commercial_cap = 13 if uses_google_presence else 15
        commercial = min(commercial_cap, category_points + project_points)
        add(
            "commercial_potential",
            "Commercial potential proxy",
            commercial,
            f"{category_reason}; current project-value band {project.range_text}. This is a prioritization heuristic, not proof of budget.",
        )
        if commercial >= 11:
            positives.append("The niche and likely project scope give one additional customer meaningful economic value.")

        # 10 points: how much of the ranking is actually evidenced versus unknown.
        evidence = 0
        if lead.audit is not None and website_observed:
            evidence += 3
            if audit.reachable or (details_retrieved and not lead.website):
                evidence += 1
        if competitors:
            evidence += 2
            if any(c.match_score >= 55 for c in competitors):
                evidence += 1
        if details_retrieved and (lead.rating is not None or lead.review_count > 0):
            evidence += 1
        if lead.phone or contacts:
            evidence += 1
        if lead.address:
            evidence += 1
        evidence = min(10, evidence)
        add("evidence_quality", "Evidence quality", evidence, f"{evidence}/10 evidence points are supported by collected public data.")

        raw_score = sum(item.points for item in factors)
        penalty = 0
        if is_likely_chain(lead.name):
            penalty += 18
            disconfirmers.append("Likely chain/franchise: the local location may not control its website or marketing stack.")
        if lead.rating is not None and lead.review_count >= 10:
            if lead.rating < 3.0:
                penalty += 15
            elif lead.rating < 3.5:
                penalty += 8
        if details_retrieved and lead.review_count == 0 and not lead.has_hours and not lead.phone:
            penalty += 12
            disconfirmers.append("Very little public evidence currently shows an active operating business.")
        if target_website_score is not None and target_website_score >= 85 and competitor_gap <= 5:
            penalty += 10
            disconfirmers.append("The existing website is already strong relative to the selected competitors.")
        if lead.suppressed:
            penalty += 100
            disconfirmers.append("Lead is suppressed and cannot be contacted.")

        score = max(0, min(100, raw_score - penalty))
        confidence = confidence_label(evidence, bool(competitors), plan.primary_channel)
        classification = classification_for(
            lead,
            score,
            confidence,
            competitor_gap=competitor_gap,
            target_website_score=target_website_score,
            details_retrieved=details_retrieved,
        )
        next_action = next_action_for(classification, plan.primary_channel, confidence)
        return QualificationResult(
            score=score,
            classification=classification,
            confidence=confidence,
            factors=tuple(factors),
            positives=tuple(dict.fromkeys(positives)),
            disconfirmers=tuple(dict.fromkeys(disconfirmers)),
            unknowns=tuple(dict.fromkeys(unknowns)),
            next_action=next_action,
        )

    def evaluate_and_store(self, session: Session, lead: Lead) -> QualificationResult:
        previous = (lead.qualification_class, lead.qualification_confidence, lead.qualification_json)
        result = self.evaluate(session, lead)
        lead.sales_priority_score = result.score
        lead.qualification_class = result.classification
        lead.qualification_confidence = result.confidence
        lead.qualification_json = dumps(result.to_dict())
        if previous != (lead.qualification_class, lead.qualification_confidence, lead.qualification_json):
            from local_presence_miner.services.commercial_state_service import recompute_lead_commercial_candidate

            recompute_lead_commercial_candidate(session, lead, "Qualification Intelligence changed commercial planning inputs")
        invalidate_contact_readiness(session, lead, "Qualification Intelligence changed")
        session.flush()
        return result

    def recalculate_missing(self, session: Session) -> int:
        leads = list(session.execute(select(Lead).where((Lead.qualification_json == "{}") | (Lead.qualification_json == ""))).scalars())
        for lead in leads:
            self.evaluate_and_store(session, lead)
        return len(leads)

    def _competitor_website_scores(self, session: Session, competitors: list[CompetitorRecord]) -> list[int]:
        scores: list[int] = []
        for competitor in competitors:
            if not competitor.competitor_place_id:
                continue
            candidate = session.execute(select(Lead).where(Lead.place_id == competitor.competitor_place_id)).scalar_one_or_none()
            if candidate is None:
                continue
            if not candidate.website and (
                not lead_google_details_retrieved(candidate) or candidate.google_rich_data_stale
            ):
                continue
            audit = audit_from_record(candidate.audit)
            if candidate.website and website_evidence_state(audit) == "unknown":
                continue
            scores.append(website_quality_score(audit, bool(candidate.website)))
        return scores


def review_activity_points(review_count: int) -> int:
    """Nonlinear establishment signal. Deliberately not a minimum threshold."""
    if review_count <= 0:
        return 0
    if review_count < 5:
        return 2
    if review_count < 10:
        return 5
    if review_count < 20:
        return 8
    if review_count < 40:
        return 10
    return 12


def project_value_points(low: int | None, high: int | None) -> int:
    if low is None or high is None:
        return 0
    midpoint = (low + high) / 2
    if midpoint >= 2500:
        return 8
    if midpoint >= 1500:
        return 7
    if midpoint >= 1000:
        return 6
    if midpoint >= 700:
        return 5
    if midpoint >= 450:
        return 3
    return 1


def category_commercial_points(category: str) -> tuple[int, str]:
    classification = commercial_class(category)
    if classification == "high":
        return 7, "High-value local-service niche heuristic"
    if classification == "moderate":
        return 4, "Moderate-value local-service niche heuristic"
    return 2, "General local-business niche heuristic"


def confidence_label(evidence_points: int, has_competitors: bool, primary_channel: str) -> str:
    if evidence_points >= 8 and has_competitors and primary_channel not in {"Contact research", "Do not contact"}:
        return "Strong"
    if evidence_points >= 5:
        return "Moderate"
    return "Low"


def classification_for(
    lead: Lead,
    score: int,
    confidence: str,
    *,
    competitor_gap: int,
    target_website_score: int | None,
    details_retrieved: bool = True,
) -> str:
    if lead.suppressed:
        return "Reject"
    if (lead.business_status or "").upper() == "CLOSED_PERMANENTLY":
        return "Reject"
    if not details_retrieved:
        return "Hold"
    if is_likely_chain(lead.name) and score < 70:
        return "Reject"
    if lead.review_count == 0 and not lead.has_hours and not lead.phone and not lead.website:
        return "Reject"
    if score < 35:
        return "Reject" if confidence != "Low" else "Hold"
    if score < 50 or (confidence == "Low" and score < 65):
        return "Hold"
    if score < 65:
        return "Qualified"
    if score < 80:
        return "High Priority"
    strong_demo_case = lead.lead_score >= 55 and (
        not lead.website or (target_website_score is not None and (competitor_gap >= 15 or target_website_score < 45))
    )
    return "Demo Priority" if strong_demo_case else "High Priority"


def next_action_for(classification: str, primary_channel: str, confidence: str) -> str:
    if classification == "Reject":
        return "Skip outreach unless manual review overturns the disqualifier."
    if classification == "Hold":
        return "Collect the missing evidence/contact data, then recalculate qualification."
    if classification == "Qualified":
        return f"Prepare {primary_channel.lower()} outreach and verify the strongest claim before approval."
    if classification == "High Priority":
        return f"Move near the front of the outreach queue; use {primary_channel.lower()} first."
    if classification == "Demo Priority":
        return f"Prioritize outreach by {primary_channel.lower()}; build a custom demo after interest or for a tightly selected top prospect."
    return "Review qualification."
