"""Reviewed supplied-evidence methods, never market measurements or quote data."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

RESEARCH_PATH = Path(__file__).resolve().parents[1] / "assets" / "intelligence_research_cards.json"
CATALOG_SHA256 = "9b7ea79ecb61a6c368af9c60402da45a5b0ef5a35ae4399969d493003bf58245"
OPERATOR_FIELDS = ("experience", "demonstration", "tools", "assistance", "capacity", "limits")
OPERATOR_STATE_FIELDS = ("experience_state", "demonstration_state")


def affirmative_operator_evidence(operator: dict) -> bool:
    """Explicit per-task self-report, with absence markers never counted as proof."""
    absent = {"", "none", "unknown", "n/a", "not provided", "no experience", "no demonstration"}
    return all(operator.get(key + "_state") == "affirmative"
               and isinstance(operator.get(key), str) and operator[key].strip().casefold() not in absent
               for key in ("experience", "demonstration"))


def research_cards() -> list[dict]:
    """The reviewed catalog is pinned; unexplained edits fail closed."""
    raw = RESEARCH_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("Research card catalog changed or is corrupt; review its provenance before use.")
    value = json.loads(raw)
    if value.get("schema_version") != 1 or len(value.get("cards", [])) != 3:
        raise ValueError("Unsupported research card catalog.")
    for card in value["cards"]:
        if not card.get("id") or not card.get("version") or not card.get("sources"):
            raise ValueError("Research card lacks provenance.")
        for source in card["sources"]:
            if not re.fullmatch(r"[a-f0-9]{64}", source.get("sha256", "")):
                raise ValueError("Research source lacks its reviewed SHA-256.")
    cards: list[dict] = value["cards"]
    return cards


def selected_research(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    cards = {card["id"]: card for card in research_cards()}
    if not set(ids) <= cards.keys():
        raise ValueError("Choose only reviewed research cards.")
    return [{"id": f"R{index}", "card_id": key, **{k: v for k, v in cards[key].items() if k != "id"}}
            for index, key in enumerate(ids, start=1)]


def context_options(*, include_owner_context: bool = False, include_market: bool = False,
                    include_commercial_explanation: bool = False, operator_context: dict | None = None,
                    research_ids: list[str] | None = None) -> dict:
    flags = (include_owner_context, include_market, include_commercial_explanation)
    if any(type(value) is not bool for value in flags):
        raise ValueError("Context disclosure choices must be explicit booleans.")
    operator_context = {} if operator_context is None else operator_context
    if not isinstance(operator_context, dict) or set(operator_context) - set(OPERATOR_FIELDS + OPERATOR_STATE_FIELDS):
        raise ValueError("Operator planning contains unsupported fields.")
    operator = {}
    for key in OPERATOR_FIELDS:
        value = operator_context.get(key, "")
        if not isinstance(value, str) or len(value) > 1200:
            raise ValueError("Each operator planning field must be text of at most 1,200 characters.")
        operator[key] = value.strip()
    for key in OPERATOR_STATE_FIELDS:
        value = operator_context.get(key, "unknown")
        if value not in ("affirmative", "none", "unknown"):
            raise ValueError("Operator experience and demonstration states must be affirmative, none or unknown.")
        operator[key] = value
    research_ids = [] if research_ids is None else research_ids
    if (not isinstance(research_ids, list) or len(research_ids) > 3
            or any(not isinstance(key, str) for key in research_ids) or len(set(research_ids)) != len(research_ids)):
        raise ValueError("Select at most three distinct reviewed research cards.")
    return {"include_owner_context": include_owner_context, "include_market": include_market,
            "include_commercial_explanation": include_commercial_explanation,
            "operator_context": operator, "research_ids": sorted(research_ids)}
