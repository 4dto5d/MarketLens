"""Small, conservative evidence seam for owner-facing sales conversation.

The product already stores several kinds of public evidence.  This module does
not score, fuse, or predict from them.  It normalizes only what the Guided Call
may use, and keeps an explicit contract beside every bounded finding so a
rendered owner-facing surface cannot accidentally imply an unverified audit,
comparison, report, or prepared artifact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from local_presence_miner.database.repositories import audit_from_record, loads
from local_presence_miner.database.schema import CompetitorRecord, ConversationAssertion, GooglePresenceAssessment, WebsiteAuditRecord
from local_presence_miner.domain.commercial import fingerprint
from local_presence_miner.domain.website_evidence import capture_state

if TYPE_CHECKING:  # pragma: no cover - imports only for static checking
    from sqlalchemy.orm import Session

    from local_presence_miner.database.schema import Lead


USAGE_INTERNAL_GUIDANCE = "internal_guidance"
USAGE_OWNER_SPOKEN = "owner_spoken"
USAGE_OWNER_COPIED = "owner_copied"

# A website observation is current-owner-usable for 30 days.  Older,
# unreachable, missing-time, or future-dated observations remain available as
# internal historical context but fail closed at owner-facing boundaries.
WEBSITE_EVIDENCE_MAX_AGE = timedelta(days=30)
REVIEW_SUBJECT = "sales.evidence_review"


@dataclass(frozen=True)
class EvidenceFinding:
    """One bounded observation and the usages its evidence contract permits."""

    source_identity: str
    observed_at: str
    freshness: str
    verification_state: str
    confidence: str
    claim: str
    allowed_usages: tuple[str, ...]
    selected_evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SalesEvidence:
    findings: tuple[EvidenceFinding, ...] = ()
    selected_evidence: dict = field(default_factory=dict)
    review_state: str = "REVIEW_REQUIRED"
    review_ref: str = ""
    owner_question: str = "What customer-facing job would you like the website to do?"
    next_step: str = "Verify the observation and owner priority before proposing changes."

    @property
    def plain_finding(self) -> str:
        packet = self.selected_evidence
        if not packet:
            return ""
        position = packet.get("observed_position")
        window = packet.get("result_window")
        visibility = f"position {position}" if position is not None else f"not found in the observed window {window}"
        prefix = "The reviewed source reports" if self.review_state == "REVIEWED" else "The source record, awaiting human review, reports"
        return (f'{prefix} {packet.get("channel", "unknown")} {visibility} for "{packet.get("query", "")}" '
                f'in {packet.get("coverage_label") or "coverage not recorded"}, observed {packet.get("observed_at", "UNKNOWN")}')

    def for_usage(self, usage: str) -> tuple[EvidenceFinding, ...]:
        return tuple(item for item in self.findings if usage in item.allowed_usages)

    def identity(self) -> tuple[dict[str, object], ...]:
        """Stable, consumed dependency payload; timestamps never imply freshness."""
        return tuple(item.to_dict() for item in self.findings)


class SalesEvidenceService:
    """Adapt existing evidence through a deliberately narrow, fail-closed seam."""

    def build(self, session: Session, lead: Lead, *, now: datetime | None = None,
              assessment: dict | None = None, offer_id: str | None = None, scope: tuple[str, ...] | None = None) -> SalesEvidence:
        now_utc = self._as_utc(now or datetime.now(UTC))
        verification = loads(lead.verification_json, {})
        if not isinstance(verification, dict):
            verification = {}
        findings: list[EvidenceFinding] = []

        audit = session.scalar(select(WebsiteAuditRecord).where(WebsiteAuditRecord.lead_id == lead.id))
        if audit is not None:
            projected = audit_from_record(audit)
            weaknesses = self._strings(audit.weaknesses_json)
            content_eligible = capture_state(evidence=projected.evidence, url=projected.url, final_url=projected.final_url,
                                             title=projected.title, status_code=projected.status_code) in {"normal", "legacy_unclassified"}
            if not content_eligible:
                weaknesses = tuple(projected.weaknesses)
            evidence = loads(audit.evidence_json, {})
            source = (audit.final_url or audit.url or "public website audit").strip()
            if weaknesses:
                freshness = self._website_freshness(audit.created_at, bool(audit.reachable), now_utc)
                verified = bool(verification.get("audit_claims")) and bool(evidence)
                owner_current = verified and freshness == "OBSERVED" and content_eligible
                findings.append(
                    EvidenceFinding(
                        source_identity=source,
                        observed_at=self._datetime(audit.created_at),
                        freshness=freshness,
                        verification_state="VERIFIED" if verified else "REVIEW_REQUIRED",
                        confidence="MODERATE" if verified else "UNKNOWN",
                        claim=weaknesses[0],
                        allowed_usages=(USAGE_INTERNAL_GUIDANCE, USAGE_OWNER_SPOKEN, USAGE_OWNER_COPIED)
                        if owner_current
                        else (USAGE_INTERNAL_GUIDANCE,),
                    )
                )

        google = session.scalar(select(GooglePresenceAssessment).where(GooglePresenceAssessment.lead_id == lead.id))
        if google is not None:
            gaps = self._strings(google.observed_gaps_json)
            if gaps:
                confidence = (google.confidence or "UNKNOWN").strip().upper() or "UNKNOWN"
                verified = bool(verification.get("google_presence")) and confidence not in {"LOW", "UNKNOWN"}
                findings.append(
                    EvidenceFinding(
                        source_identity="Google public presence assessment",
                        observed_at=self._datetime(google.generated_at),
                        freshness="STALE" if lead.google_rich_data_stale else "OBSERVED",
                        verification_state="VERIFIED" if verified else "REVIEW_REQUIRED",
                        confidence=confidence,
                        claim=gaps[0],
                        allowed_usages=(USAGE_INTERNAL_GUIDANCE, USAGE_OWNER_SPOKEN, USAGE_OWNER_COPIED)
                        if verified and not lead.google_rich_data_stale
                        else (USAGE_INTERNAL_GUIDANCE,),
                    )
                )

        competitors = list(session.scalars(select(CompetitorRecord).where(CompetitorRecord.lead_id == lead.id)))
        if competitors:
            supported = [item for item in competitors if (item.evidence_notes or "").strip()]
            findings.append(
                EvidenceFinding(
                    source_identity=f"{len(competitors)} selected public competitor record(s)",
                    observed_at="UNKNOWN",
                    freshness="UNKNOWN",
                    verification_state="VERIFIED" if bool(verification.get("competitors")) and supported else "REVIEW_REQUIRED",
                    confidence="UNKNOWN",
                    claim="Competitor material is available only for internal review until a bounded public claim is verified.",
                    allowed_usages=(USAGE_INTERNAL_GUIDANCE,),
                )
            )

        # No pricing/planner call here: the planner itself consumes this seam.
        # Fusion only reads the existing source and canonical-selection contracts.
        if assessment is None:
            from local_presence_miner.services.search_offer_intelligence import fuse_offer

            fusion = fuse_offer(session, lead, lead.recommended_offer_id or "", now=now_utc)
            assessment = fusion.intervention_assessment
            offer_id = fusion.selected_offer_id
        candidates = assessment.get("ranked_candidates", ())
        selected = next((item for item in candidates if item.get("offer_id") == offer_id and offer_id), None)
        packet = dict(selected.get("selected_evidence") or {}) if selected else {}
        if packet:
            from local_presence_miner.services.seo_research_service import project_seo_research

            research = project_seo_research(session, lead, now=now_utc)
            selected_identity = str(selected.get("intervention_id", "")) if selected else ""
            source_match = next((item for item in research.get("opportunities", ())
                                 if item.get("selected_evidence") == packet
                                 and selected_identity.endswith(":" + str(item.get("cluster_id", "")))), None)
            if research.get("state") != "complete" or source_match is None:
                packet = {}
        actual_scope = tuple(scope if scope is not None else selected.get("scope", ()) if selected else ())
        review_state, review_ref = "REVIEW_REQUIRED", ""
        question = str(assessment.get("owner_validation_question") or
                       (f'Is {packet.get("service")} in this observed area work you want and can take on now?' if packet else
                        "What customer-facing job would you like the website to do?"))
        next_step = "Review the exact page, confirm owner fit and editable platform with Sammi before agreeing implementation."
        if packet:
            binding = evidence_review_binding(lead, str(offer_id or ""), actual_scope, packet)
            review = current_review(session, lead.id, REVIEW_SUBJECT, binding, now_utc)
            if review:
                review_state, review_ref = "REVIEWED", f"conversation_assertion:{review.id}"
            proof = SalesEvidence(selected_evidence=packet, review_state=review_state)
            findings.insert(0, EvidenceFinding(
                source_identity="; ".join(str(item) for item in packet.get("source_refs", ())),
                observed_at=str(packet.get("observed_at") or "UNKNOWN"), freshness="OBSERVED",
                verification_state=review_state, confidence=str(packet.get("confidence") or "UNKNOWN"),
                claim=proof.plain_finding,
                allowed_usages=(USAGE_INTERNAL_GUIDANCE, USAGE_OWNER_SPOKEN, USAGE_OWNER_COPIED)
                if review else (USAGE_INTERNAL_GUIDANCE,), selected_evidence=packet,
            ))
        return SalesEvidence(tuple(findings), packet, review_state, review_ref, question, next_step)

    def record_review(self, session: Session, lead: Lead, *, context, reviewer: str, source_text: str):
        """Record human fact review; it grants neither owner approval nor contact permission."""
        from local_presence_miner.services.conversation_state_service import ConversationStateService

        evidence = self.build(session, lead, assessment=context.intervention_assessment, offer_id=context.offer_id, scope=context.scope)
        if not reviewer.strip() or not source_text.strip() or not evidence.selected_evidence:
            raise ValueError("Review requires a named reviewer, review notes and current selected proof.")
        binding = evidence_review_binding(lead, context.offer_id, context.scope, evidence.selected_evidence)
        return ConversationStateService().append_assertion(
            session, lead, subject_key=REVIEW_SUBJECT,
            value={"version": 1, "binding": binding, "reviewed": True, "reviewer": reviewer.strip(),
                   "reviewed_at": datetime.now(UTC).isoformat()},
            actor_id=reviewer, source_text=source_text, source_text_mode="PARAPHRASED", supersede_current=True,
        )

    @staticmethod
    def _strings(raw: str) -> tuple[str, ...]:
        value = loads(raw, [])
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    @staticmethod
    def _datetime(value: datetime | None) -> str:
        return value.isoformat() if value is not None else "UNKNOWN"

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _website_freshness(cls, observed_at: datetime | None, reachable: bool, now_utc: datetime) -> str:
        if not reachable or observed_at is None:
            return "UNKNOWN"
        age = now_utc - cls._as_utc(observed_at)
        if age < timedelta(0):
            return "UNKNOWN"
        return "OBSERVED" if age <= WEBSITE_EVIDENCE_MAX_AGE else "STALE"


def evidence_review_binding(lead: Lead, offer_id: str, scope, packet: dict) -> str:
    return fingerprint({"lead_id": lead.id, "place_id": lead.place_id, "offer_id": offer_id,
                        "scope": list(scope), "selected_evidence": packet})


def current_review(session: Session, lead_id: int, subject: str, binding: str, now: datetime):
    """Corrections/unknowns and contradictory records fail closed, preserving all rows."""
    rows = list(session.scalars(select(ConversationAssertion).where(
        ConversationAssertion.lead_id == lead_id, ConversationAssertion.subject_key == subject,
    ).order_by(ConversationAssertion.id)))
    superseded = {row.supersedes_assertion_id for row in rows if row.supersedes_assertion_id is not None}
    current = [row for row in rows if row.id not in superseded]
    if len(current) != 1:
        return None
    row = current[0]
    value = loads(row.value_json, {})
    if (row.assertion_state != "ACTIVE" or row.confidence != "CONFIRMED" or not isinstance(value, dict)
            or value.get("version") != 1 or row.source_kind not in {"OPERATOR_OBSERVATION", "OWNER_LITERAL"}
            or value.get("binding") != binding or value.get("reviewed") is not True
            or not isinstance(value.get("reviewer"), str) or not value["reviewer"].strip()
            or value["reviewer"].strip() != row.actor_id.strip() or not row.source_text.strip()):
        return None
    try:
        stamp = SalesEvidenceService._as_utc(datetime.fromisoformat(value["reviewed_at"]))
        if not timedelta(0) <= now - stamp <= WEBSITE_EVIDENCE_MAX_AGE:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return row
