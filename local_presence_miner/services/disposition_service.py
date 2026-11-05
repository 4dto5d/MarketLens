from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from local_presence_miner.database.schema import CommercialDispositionRecord, ContactInteraction, Lead
from local_presence_miner.domain.enums import (
    OUTREACH_BLOCKED_STATUSES,
    CommercialDisposition,
    FollowUpPermission,
    LeadStatus,
)
from local_presence_miner.time_utils import utc_now


class DispositionService:
    """Own explicit commercial-disposition transitions and their CRM projection."""

    def set_disposition(
        self,
        session: Session,
        lead: Lead,
        disposition: CommercialDisposition | str,
        *,
        reason: str,
        confirmed: bool = False,
        not_before: str = "",
        follow_up_permission: FollowUpPermission | str = FollowUpPermission.UNKNOWN,
        source_interaction_id: int | None = None,
        actor_id: str = "",
        close_no_sell_as_lost: bool = False,
    ) -> CommercialDispositionRecord:
        if not confirmed:
            raise ValueError("Disposition changes require explicit operator confirmation.")
        if lead.id is None:
            raise ValueError("Disposition changes require a persisted lead.")
        try:
            value = CommercialDisposition(disposition)
        except ValueError as exc:
            raise ValueError(f"Unsupported commercial disposition: {disposition!r}") from exc
        try:
            permission = FollowUpPermission(follow_up_permission)
        except ValueError as exc:
            raise ValueError(f"Unsupported follow-up permission: {follow_up_permission!r}") from exc
        if not reason.strip():
            raise ValueError("Disposition changes require an explicit operator reason.")
        if source_interaction_id is not None:
            interaction = session.get(ContactInteraction, source_interaction_id)
            if interaction is None or interaction.lead_id != lead.id:
                raise ValueError("Disposition source interaction does not belong to this lead.")

        canonical_not_before = self._canonical_date(not_before)
        if value is not CommercialDisposition.DEFERRED:
            if canonical_not_before:
                raise ValueError("A not-before date is only valid for DEFERRED disposition.")
            permission = FollowUpPermission.UNKNOWN

        try:
            previous_value = CommercialDisposition((lead.commercial_disposition or "UNKNOWN").strip().upper())
        except ValueError:
            previous_value = CommercialDisposition.UNKNOWN
        try:
            previous_permission = FollowUpPermission((lead.follow_up_permission or "UNKNOWN").strip().upper())
        except ValueError:
            previous_permission = FollowUpPermission.UNKNOWN
        previous_not_before = (lead.disposition_not_before or "").strip()

        if previous_value is CommercialDisposition.CLOSED_WON and value is not CommercialDisposition.CLOSED_WON:
            raise ValueError("A CLOSED_WON opportunity cannot be reopened in place; create a deliberate new opportunity instead.")
        if (
            value is previous_value
            and canonical_not_before == previous_not_before
            and permission is previous_permission
        ):
            raise ValueError("Disposition transition does not change the current commercial state.")

        crm_before = lead.status
        previous_follow_up_was_disposition_projection = (
            previous_value is CommercialDisposition.DEFERRED
            and previous_permission is FollowUpPermission.AGREED
            and bool(previous_not_before)
            and lead.next_follow_up_date == previous_not_before
        )

        # Compliance remains authoritative over CRM synchronization. A disposition
        # change can never make a suppressed/opted-out lead look contactable.
        from local_presence_miner.database.repositories import is_suppressed

        compliance_locked = (
            lead.suppressed
            or lead.status in OUTREACH_BLOCKED_STATUSES
            or is_suppressed(session, lead)
        )

        next_revision = int(lead.commercial_disposition_revision or 0) + 1
        lead.commercial_disposition = value.value
        lead.commercial_disposition_revision = next_revision
        lead.disposition_not_before = canonical_not_before
        lead.follow_up_permission = permission.value

        if compliance_locked:
            lead.suppressed = True
            if lead.status != LeadStatus.OPTED_OUT.value:
                lead.status = LeadStatus.DO_NOT_CONTACT.value
        elif value is CommercialDisposition.CLOSED_WON:
            lead.status = LeadStatus.WON.value
        elif value is CommercialDisposition.CLOSED_LOST or value is CommercialDisposition.NO_SELL and close_no_sell_as_lost:
            lead.status = LeadStatus.LOST.value
        elif value is CommercialDisposition.OPEN and previous_value in {
            CommercialDisposition.CLOSED_LOST,
            CommercialDisposition.NO_SELL,
        } and lead.status == LeadStatus.LOST.value:
            # Reopening is explicit, but do not guess a relationship stage. The
            # conservative CRM projection is a human-review state.
            lead.status = LeadStatus.NEEDS_REVIEW.value

        # A deferred date only becomes the lead's due follow-up when the owner
        # explicitly agreed to it. Unknown/non-agreed dates cannot authorize a
        # proactive callback. When leaving a defer, clear only the date that this
        # disposition service itself had projected; preserve unrelated CRM dates.
        if value is CommercialDisposition.DEFERRED and permission is FollowUpPermission.AGREED:
            lead.next_follow_up_date = canonical_not_before
        elif value is CommercialDisposition.DEFERRED or previous_follow_up_was_disposition_projection:
            lead.next_follow_up_date = ""

        crm_after = lead.status
        record = CommercialDispositionRecord(
            lead_id=lead.id,
            disposition=value.value,
            previous_disposition=previous_value.value,
            not_before=canonical_not_before,
            follow_up_permission=permission.value,
            reason=reason.strip(),
            source_interaction_id=source_interaction_id,
            actor_id=actor_id.strip(),
            crm_status_before=crm_before,
            crm_status_after=crm_after,
            revision=next_revision,
        )
        session.add(record)

        lead.updated_at = utc_now()
        session.flush()

        # Reuse existing v0.1.14 invalidation boundaries rather than creating a
        # second propagation bus.
        from local_presence_miner.database.repositories import invalidate_contact_readiness, log_activity
        from local_presence_miner.services.commercial_state_service import mark_lead_commercial_stale

        invalidate_contact_readiness(session, lead, "Commercial disposition changed")
        mark_lead_commercial_stale(session, lead, "Commercial disposition changed")
        log_activity(
            session,
            "commercial_disposition_changed",
            f"Disposition -> {value.value} (revision {next_revision}): {reason.strip()}",
            lead.id,
        )
        return record

    @staticmethod
    def _canonical_date(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError("Disposition not-before date must use ISO format YYYY-MM-DD.") from exc
