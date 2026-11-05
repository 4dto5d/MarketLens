"""Canonical current-commercial planning value objects.

These objects intentionally carry no ORM state and never read a persisted Smart
Offer cache.  They are safe to serialize into current-plan and historical
dependency records without making historical JSON a source of current truth.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class CommercialPlanState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNAVAILABLE_REVIEW_REQUIRED = "unavailable_review_required"
    LEGACY_UNKNOWN_REVIEW_REQUIRED = "legacy_unknown_review_required"


@dataclass(frozen=True)
class CurrentOfferContext:
    """The single authority for an offer and exact scope in one planning run."""

    schema_version: int
    lead_id: int | None
    lead_place_id: str
    raw_label: str
    supplied_canonical_id: str
    offer_id: str
    resolution_state: str
    matched_alias: str
    registry_version: int
    selection_source: str
    raw_category: str
    canonical_niche_id: str
    niche_rule: str
    niche_registry_version: int
    scope: tuple[str, ...]
    scope_template_key: str
    planning_inputs: dict[str, Any]
    planning_input_fingerprint: str
    scope_fingerprint: str
    context_fingerprint: str
    offer_fusion: dict[str, Any] = field(default_factory=dict)
    intervention_assessment: dict[str, Any] = field(default_factory=dict)

    @property
    def price_available(self) -> bool:
        return bool(self.offer_id and self.planning_inputs.get("intervention_decision", {}).get("price_allowed", True))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if not self.offer_fusion:
            result.pop("offer_fusion")
        return result

    def dependency_dict(self) -> dict[str, Any]:
        """Exclude advisory/lock narration from the commercial dependency."""
        result = self.to_dict()
        result.pop("offer_fusion", None)
        result.pop("intervention_assessment", None)
        # Approval/lock metadata must not stale its own unchanged selection.
        # Identity, scope and consumed evidence already express material choice.
        result["selection_source"] = "canonical_selection"
        return result


@dataclass(frozen=True)
class CommercialDependencySnapshot:
    """Consumer-specific current dependencies and the resulting output."""

    schema_version: int
    consumer_kind: str
    lead_id: int | None
    current_offer_context_fingerprint: str
    dependencies: dict[str, Any]
    output: dict[str, Any]
    dependency_fingerprint: str
    output_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_dependency_snapshot(
    *,
    consumer_kind: str,
    lead_id: int | None,
    current_offer_context_fingerprint: str,
    dependencies: dict[str, Any],
    output: dict[str, Any],
) -> CommercialDependencySnapshot:
    """Create a stable snapshot without timestamps or unrelated revisions."""

    dependency_document = {
        "schema_version": 1,
        "consumer_kind": consumer_kind,
        "lead_id": lead_id,
        "current_offer_context_fingerprint": current_offer_context_fingerprint,
        "dependencies": dependencies,
    }
    output_document = {
        "schema_version": 1,
        "consumer_kind": consumer_kind,
        "output": output,
    }
    return CommercialDependencySnapshot(
        schema_version=1,
        consumer_kind=consumer_kind,
        lead_id=lead_id,
        current_offer_context_fingerprint=current_offer_context_fingerprint,
        dependencies=dependencies,
        output=output,
        dependency_fingerprint=fingerprint(dependency_document),
        output_fingerprint=fingerprint(output_document),
    )
