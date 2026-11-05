from __future__ import annotations

from enum import StrEnum


class LeadStatus(StrEnum):
    NEW = "New"
    AUDITING = "Auditing"
    NEEDS_REVIEW = "Needs Review"
    QUALIFIED = "Qualified"
    NOT_QUALIFIED = "Not Qualified"
    OUTREACH_DRAFTED = "Outreach Drafted"
    APPROVED_TO_CONTACT = "Approved to Contact"
    CONTACTED = "Contacted"
    REPLIED = "Replied"
    MEETING_SCHEDULED = "Meeting Scheduled"
    WON = "Won"
    LOST = "Lost"
    OPTED_OUT = "Opted Out"
    DO_NOT_CONTACT = "Do Not Contact"


OUTREACH_BLOCKED_STATUSES = frozenset({LeadStatus.OPTED_OUT.value, LeadStatus.DO_NOT_CONTACT.value})


class CommercialDisposition(StrEnum):
    """Current commercial action state, deliberately separate from CRM/compliance."""

    OPEN = "OPEN"
    DEFERRED = "DEFERRED"
    NO_SELL = "NO_SELL"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"
    UNKNOWN = "UNKNOWN"


class FollowUpPermission(StrEnum):
    AGREED = "AGREED"
    NOT_AGREED = "NOT_AGREED"
    UNKNOWN = "UNKNOWN"


class AssertionState(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    CLEARED = "CLEARED"
    UNKNOWN = "UNKNOWN"


class AssertionSourceKind(StrEnum):
    OWNER_LITERAL = "OWNER_LITERAL"
    OPERATOR_OBSERVATION = "OPERATOR_OBSERVATION"
    OPERATOR_INTERPRETATION = "OPERATOR_INTERPRETATION"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"
    LEGACY_IMPORT = "LEGACY_IMPORT"


class AssertionSourceTextMode(StrEnum):
    VERBATIM = "VERBATIM"
    PARAPHRASED = "PARAPHRASED"
    NOT_RECORDED = "NOT_RECORDED"


class AssertionConfidence(StrEnum):
    CONFIRMED = "CONFIRMED"
    TENTATIVE = "TENTATIVE"
    UNKNOWN = "UNKNOWN"


class EligibilityState(StrEnum):
    BLOCKED_COMPLIANCE = "BLOCKED_COMPLIANCE"
    BLOCKED_BUSINESS_CLOSED = "BLOCKED_BUSINESS_CLOSED"
    BLOCKED_DISPOSITION = "BLOCKED_DISPOSITION"
    BLOCKED_DEFERRED = "BLOCKED_DEFERRED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    CONTACT_RESEARCH_REQUIRED = "CONTACT_RESEARCH_REQUIRED"
    ELIGIBLE_FOR_HUMAN_REVIEW = "ELIGIBLE_FOR_HUMAN_REVIEW"


class OutreachKind(StrEnum):
    INITIAL_EMAIL = "Initial cold email"
    SHORT_FOLLOW_UP = "Short follow-up"
    FINAL_FOLLOW_UP = "Final follow-up"
    INTERESTED_REPLY = "Reply — interested"
    PRICE_REPLY = "Reply — asks price"
    PROVIDER_REPLY = "Reply — already has provider"
    NOT_NOW_REPLY = "Reply — not now / needs time"
    CALL_OPENING = "Call opening script"
    VOICEMAIL = "Voicemail script"
    REPORT_DELIVERY = "Report-delivery email"
    MOCKUP_DELIVERY = "Mockup-delivery email"


class Priority(StrEnum):
    A = "A"
    B = "B"
    C = "C"
