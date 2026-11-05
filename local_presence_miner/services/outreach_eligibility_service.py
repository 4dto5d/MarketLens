from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import ContactPoint, Lead
from local_presence_miner.domain.enums import (
    OUTREACH_BLOCKED_STATUSES,
    CommercialDisposition,
    EligibilityState,
    FollowUpPermission,
)
from local_presence_miner.domain.offer_registry import OfferID


@dataclass(frozen=True)
class OutreachEligibilityResult:
    state: EligibilityState
    reasons: tuple[str, ...]

    @property
    def is_blocked(self) -> bool:
        return self.state in {
            EligibilityState.BLOCKED_COMPLIANCE,
            EligibilityState.BLOCKED_BUSINESS_CLOSED,
            EligibilityState.BLOCKED_DISPOSITION,
            EligibilityState.BLOCKED_DEFERRED,
        }

    @property
    def permits_live_use(self) -> bool:
        return self.state is EligibilityState.ELIGIBLE_FOR_HUMAN_REVIEW


class OutreachEligibilityService:
    """Single reason-coded eligibility projection for current commercial contact."""

    def evaluate(self, session: Session, lead: Lead, *, today: date | None = None) -> OutreachEligibilityResult:
        from local_presence_miner.database.repositories import is_suppressed

        if lead.suppressed or lead.status in OUTREACH_BLOCKED_STATUSES or is_suppressed(session, lead):
            return OutreachEligibilityResult(
                EligibilityState.BLOCKED_COMPLIANCE,
                ("Suppressed lead or marked Do Not Contact / Opted Out.",),
            )

        if (lead.business_status or "").strip().upper() == "CLOSED_PERMANENTLY":
            return OutreachEligibilityResult(
                EligibilityState.BLOCKED_BUSINESS_CLOSED,
                ("Google Places currently reports the business as permanently closed.",),
            )

        try:
            disposition = CommercialDisposition((lead.commercial_disposition or "UNKNOWN").strip().upper())
        except ValueError:
            disposition = CommercialDisposition.UNKNOWN
        if disposition in {
            CommercialDisposition.NO_SELL,
            CommercialDisposition.CLOSED_WON,
            CommercialDisposition.CLOSED_LOST,
        }:
            return OutreachEligibilityResult(
                EligibilityState.BLOCKED_DISPOSITION,
                (f"Commercial disposition is {disposition.value}; routine cold commercial outreach is blocked.",),
            )

        if disposition is CommercialDisposition.DEFERRED:
            try:
                permission = FollowUpPermission((lead.follow_up_permission or "UNKNOWN").strip().upper())
            except ValueError:
                permission = FollowUpPermission.UNKNOWN
            not_before = self._date_or_none(lead.disposition_not_before)
            current_day = today or date.today()
            if permission is not FollowUpPermission.AGREED:
                return OutreachEligibilityResult(
                    EligibilityState.BLOCKED_DEFERRED,
                    ("Commercial disposition is DEFERRED without an agreed follow-up permission.",),
                )
            if not_before is None:
                return OutreachEligibilityResult(
                    EligibilityState.BLOCKED_DEFERRED,
                    ("Commercial disposition is DEFERRED without an agreed revisit date.",),
                )
            if current_day < not_before:
                return OutreachEligibilityResult(
                    EligibilityState.BLOCKED_DEFERRED,
                    (f"Commercial disposition is DEFERRED until {not_before.isoformat()}.",),
                )

        qualification = (lead.qualification_class or "").strip().casefold()
        offer_id_text = (lead.recommended_offer_id or "").strip()
        offer_state = (lead.offer_resolution_state or "").strip().casefold()
        try:
            OfferID(offer_id_text)
            offer_id_is_known = True
        except ValueError:
            offer_id_is_known = False
        # Fail closed on unknown/corrupt resolution states. Only the explicit
        # successful resolver outcomes are allowed to support commercial use.
        resolved_offer_states = {"canonical_id", "display_label", "legacy_alias"}
        unresolved_offer = not offer_id_is_known or offer_state not in resolved_offer_states
        if qualification in {"hold", "reject"} or unresolved_offer:
            reasons: list[str] = []
            if qualification in {"hold", "reject"}:
                reasons.append(f"Qualification is {lead.qualification_class}; research/manual review is required.")
            if unresolved_offer:
                reasons.append("Current commercial Offer is unresolved or research-only; commercial outreach is not ready.")
            return OutreachEligibilityResult(EligibilityState.RESEARCH_ONLY, tuple(reasons))

        if not self._has_verified_public_route(session, lead):
            return OutreachEligibilityResult(
                EligibilityState.CONTACT_RESEARCH_REQUIRED,
                ("No verified public phone, email, or contact-page route is currently stored.",),
            )

        return OutreachEligibilityResult(
            EligibilityState.ELIGIBLE_FOR_HUMAN_REVIEW,
            ("Current state permits human review of outreach; this is not consent or automatic approval.",),
        )

    @staticmethod
    def _date_or_none(value: str) -> date | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _has_verified_public_route(session: Session, lead: Lead) -> bool:
        # Lead.phone is populated from the public Google/business record in the
        # existing model and remains a supported compatibility route.
        if (lead.phone or "").strip():
            return True
        return session.scalar(
            select(ContactPoint.id).where(
                ContactPoint.lead_id == lead.id,
                ContactPoint.verified_public.is_(True),
                ContactPoint.kind.in_(("phone", "email", "contact_page")),
                ContactPoint.value != "",
            ).limit(1)
        ) is not None
