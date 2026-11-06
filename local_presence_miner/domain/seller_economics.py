"""Seller-side economics: pricing stage, realistic hours and a minimum-earnings check.

Clients are always quoted a flat price for a fixed scope. The operator's
minimum hourly earnings is an INTERNAL check of whether that flat price pays
enough once realistic hours are counted:

    minimum flat price = (minimum $/h x realistic hours + cash costs + fixed card fees) / (1 - card rate)

Realistic hours = delivery hours x overrun + acquisition hours for the route
+ first-job setup and sample time (stage 1 only). These are planning
assumptions from the November 2026 service catalog and 5B re-examination,
not measured delivery times or market prices. Replace them with logged
actuals as Offer History grows. These values must never appear in
customer-facing material.
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
DEFAULT_MINIMUM_HOURLY_EARNINGS = 35
MIN_HOURLY_SETTING = 10
MAX_HOURLY_SETTING = 500
# Completed paid projects needed to reach stage 2 and stage 3.
STAGE_THRESHOLDS = (3, 8)
STAGE_LABELS = {1: "first clients", 2: "proven", 3: "established"}


@dataclass(frozen=True)
class MinimumPrice:
    """Lowest flat price for one exact scope that clears the hourly minimum."""

    amount: int
    hours: float
    cash: int
    route: str
    rate: int
    stage: int

    def effective_hourly(self, flat_price: int) -> float:
        """What a given flat price pays per realistic hour after cash and card fees."""
        return (flat_price * (1 - CARD_RATE) - self.cash - CARD_FIXED_TOTAL) / self.hours

    def explanation(self, flat_price: int) -> str:
        return (
            f"Minimum-earnings check (internal): the ${flat_price:,} flat price pays about "
            f"${self.effective_hourly(flat_price):,.0f}/h over {self.hours:.1f} realistic hours "
            f"(${self.cash} cash, card fees, {self.route} acquisition, stage {self.stage}). "
            f"At your ${self.rate}/h minimum this exact scope needs at least ${self.amount:,}."
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


def clamp_hourly_minimum(value: object) -> int:
    try:
        rate = int(float(str(value)))
    except (TypeError, ValueError):
        return DEFAULT_MINIMUM_HOURLY_EARNINGS
    return rate if MIN_HOURLY_SETTING <= rate <= MAX_HOURLY_SETTING else DEFAULT_MINIMUM_HOURLY_EARNINGS


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


def minimum_price(definition: OfferDefinition, *, rate: int, stage: int = 1, route: str | None = None) -> MinimumPrice | None:
    """Return the internal minimum flat price, or None when the offer has no economics inputs."""
    if definition.delivery_hours <= 0:
        return None
    selected_route = route if route in ACQUISITION_ROUTES else definition.acquisition_route
    hours, cash = realistic_hours_and_cash(definition, route=selected_route, stage=stage)
    raw = (rate * hours + cash + CARD_FIXED_TOTAL) / (1 - CARD_RATE)
    return MinimumPrice(_ceil_to(raw), hours, cash, selected_route, rate, stage)
