"""Seller-side economics: pricing stage, realistic hours and a walk-away floor.

The walk-away is the least the operator should accept for one exact scope:

    walk-away = (hourly rate x realistic hours + cash costs + fixed card fees) / (1 - card rate)

Realistic hours = delivery hours x overrun + acquisition hours for the route
+ first-job setup and sample time (stage 1 only). These are planning
assumptions from the November 2026 service catalog and 5B re-examination,
not measured delivery times or market prices. Replace them with logged
actuals as Offer History grows. Walk-away values are internal and must never
appear in customer-facing material.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from local_presence_miner.domain.offer_registry import ACQUISITION_ROUTES, OfferDefinition

CARD_RATE = 0.029
CARD_FIXED_TOTAL = 0.60  # two ordinary card payments at $0.30
DELIVERY_OVERRUN = 1.35  # first-job slowness plus revision overrun
# Route -> (hours, cash). Cold assumes ~20 researched contacts per paid job,
# lost meetings and proposals, and local travel. Reached means the owner is
# already in conversation, so acquisition effort is already spent.
ACQUISITION: dict[str, tuple[float, int]] = {"cold": (27.0, 80), "warm": (6.0, 10), "reached": (1.0, 0)}
LARGE_PROJECT_THRESHOLD = 1_500
FIRST_FAMILY_SETUP: dict[str, tuple[float, int]] = {"large": (6.0, 60), "small": (2.0, 20)}
CONTINGENCY_CASH = 40  # large projects only
DEFAULT_OPERATOR_RATE = 35
MIN_OPERATOR_RATE = 10
MAX_OPERATOR_RATE = 500
# Completed paid projects needed to reach stage 2 and stage 3.
STAGE_THRESHOLDS = (3, 8)
STAGE_LABELS = {1: "first clients", 2: "proven", 3: "established"}


@dataclass(frozen=True)
class WalkAway:
    amount: int
    hours: float
    cash: int
    route: str
    rate: int
    stage: int

    def explanation(self) -> str:
        return (
            f"Internal walk-away for this exact scope: ${self.amount:,} = (${self.rate}/h x {self.hours:.1f} realistic h "
            f"+ ${self.cash} cash + card fees) / {1 - CARD_RATE:.3f}, {self.route} acquisition, stage {self.stage}. "
            "Never sell the same scope below it; cut scope instead."
        )


def pricing_stage(completed_paid_projects: int) -> int:
    if completed_paid_projects >= STAGE_THRESHOLDS[1]:
        return 3
    if completed_paid_projects >= STAGE_THRESHOLDS[0]:
        return 2
    return 1


def stage_quote(definition: OfferDefinition, stage: int) -> int:
    if not definition.stage_quotes:
        return definition.price_low
    index = min(max(stage, 1), len(definition.stage_quotes)) - 1
    return definition.stage_quotes[index]


def clamp_operator_rate(value: object) -> int:
    try:
        rate = int(float(str(value)))
    except (TypeError, ValueError):
        return DEFAULT_OPERATOR_RATE
    return rate if MIN_OPERATOR_RATE <= rate <= MAX_OPERATOR_RATE else DEFAULT_OPERATOR_RATE


def _ceil_to(value: float, step: int = 25) -> int:
    return int(math.ceil(value / step) * step)


def realistic_hours_and_cash(definition: OfferDefinition, *, route: str, stage: int) -> tuple[float, int]:
    if definition.billing == "monthly":
        # Recurring work: no acquisition or setup inside the monthly fee.
        return round(definition.delivery_hours * DELIVERY_OVERRUN, 2), definition.project_cash
    acquisition_hours, acquisition_cash = ACQUISITION[route]
    large = stage_quote(definition, 1) >= LARGE_PROJECT_THRESHOLD
    hours = definition.delivery_hours * DELIVERY_OVERRUN + acquisition_hours
    cash = definition.project_cash + acquisition_cash
    if stage == 1:
        setup_hours, setup_cash = FIRST_FAMILY_SETUP["large" if large else "small"]
        hours += setup_hours + definition.sample_hours
        cash += setup_cash
    if large:
        cash += CONTINGENCY_CASH
    return round(hours, 2), cash


def walk_away(definition: OfferDefinition, *, rate: int, stage: int = 1, route: str | None = None) -> WalkAway | None:
    """Return the internal floor, or None when the offer has no economics inputs."""
    if definition.delivery_hours <= 0:
        return None
    selected_route = route if route in ACQUISITION_ROUTES else definition.acquisition_route
    hours, cash = realistic_hours_and_cash(definition, route=selected_route, stage=stage)
    raw = (rate * hours + cash + CARD_FIXED_TOTAL) / (1 - CARD_RATE)
    return WalkAway(_ceil_to(raw), hours, cash, selected_route, rate, stage)
