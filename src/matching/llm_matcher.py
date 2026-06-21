"""
LLM-assisted novelty matcher.

Novelty markets (Oscars, contests, awards) can't be matched by a team registry:
the events and outcomes are free text, and the two venues structure them
differently (DraftKings "Over/Under 76.5" vs Kalshi bucket markets). So we ask
Claude to read both venues' markets and return economically-equivalent matches
with aligned outcomes.

Uses the official Anthropic SDK with structured JSON output. Model is
configurable (Settings.MATCHER_MODEL, default claude-haiku-4-5).
"""

import json
from dataclasses import dataclass

import anthropic

from src.models import Market
from config.settings import Settings

SYSTEM = (
    "You match betting markets across two venues: DraftKings (a sportsbook) and "
    "Kalshi (a prediction market). Two markets MATCH only if they resolve on the "
    "exact same real-world question, so that a position on one venue can be hedged "
    "by the opposite position on the other. For each match, align every DraftKings "
    "outcome to its economically-equivalent Kalshi outcome (e.g. DraftKings "
    "'Over 76.5' aligns with the union of Kalshi buckets '77 or more'). Only return "
    "matches you are confident share the same resolution. Returning no matches is "
    "correct when nothing lines up. Be conservative — a wrong match loses real money."
)

# Structured-output schema (no numeric/length constraints — unsupported).
MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dk_market_id": {"type": "string"},
                    "kalshi_market_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "note": {"type": "string"},
                    "outcome_map": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dk_outcome": {"type": "string"},
                                "kalshi_outcome": {"type": "string"},
                            },
                            "required": ["dk_outcome", "kalshi_outcome"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["dk_market_id", "kalshi_market_id", "confidence", "note", "outcome_map"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


@dataclass
class NoveltyMatch:
    dk_market_id: str
    kalshi_market_id: str
    confidence: float
    note: str
    outcome_map: dict[str, str]  # dk_outcome_name -> kalshi_outcome_name


def _describe(markets: list[Market], label: str) -> str:
    blocks = []
    for m in markets:
        lines = [f"[{label} id={m.market_id}] event={m.event_name!r} market={m.market_type!r}"]
        for o in m.outcomes:
            lines.append(f"    - {o.name!r}  {o.odds_american:+.0f} (implied {o.implied_prob:.0%})")
        blocks.append("\n".join(lines))
    return "\n".join(blocks) if blocks else "(none)"


def match_novelty(dk_markets: list[Market], kalshi_markets: list[Market]) -> list[NoveltyMatch]:
    """Ask Claude to align DraftKings novelty markets with Kalshi ones."""
    if not Settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY not set — add it to .env to use the LLM novelty matcher."
        )
    if not dk_markets or not kalshi_markets:
        return []

    user = (
        "DraftKings markets:\n" + _describe(dk_markets, "DK")
        + "\n\nKalshi markets:\n" + _describe(kalshi_markets, "K")
        + "\n\nReturn the matches."
    )

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=Settings.MATCHER_MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": MATCH_SCHEMA}},
    )

    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    return [
        NoveltyMatch(
            dk_market_id=m["dk_market_id"],
            kalshi_market_id=m["kalshi_market_id"],
            confidence=m["confidence"],
            note=m["note"],
            outcome_map={p["dk_outcome"]: p["kalshi_outcome"] for p in m["outcome_map"]},
        )
        for m in data["matches"]
    ]


# --- Polymarket <-> Kalshi (its own track; novelty path above is untouched) ---

_POLY_SYSTEM = (
    "You match betting markets across two prediction-market venues: Polymarket and "
    "Kalshi. Two markets MATCH only if they resolve on the exact same real-world "
    "question, so that a position on one venue can be hedged by the opposite "
    "position on the other. For each match, align every Polymarket outcome to its "
    "economically-equivalent Kalshi outcome (e.g. Polymarket 'Yes' on 'Will "
    "Argentina win the World Cup?' aligns with a Kalshi 'Argentina'/'Yes' outcome "
    "on the same question). Only return matches you are confident share the exact "
    "same resolution. Returning no matches is correct when nothing lines up. Be "
    "conservative — a wrong match loses real money."
)

_POLY_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "poly_market_id": {"type": "string"},
                    "kalshi_market_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "note": {"type": "string"},
                    "outcome_map": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "poly_outcome": {"type": "string"},
                                "kalshi_outcome": {"type": "string"},
                            },
                            "required": ["poly_outcome", "kalshi_outcome"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["poly_market_id", "kalshi_market_id", "confidence", "note", "outcome_map"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


@dataclass
class PolymarketMatch:
    poly_id: str
    kalshi_id: str
    confidence: float
    note: str
    outcome_map: dict[str, str]  # polymarket outcome name -> kalshi outcome name


def match_polymarket_kalshi(poly_markets: list[Market],
                            kalshi_markets: list[Market]) -> list[PolymarketMatch]:
    """Ask Claude to align Polymarket markets with Kalshi ones (both prediction markets)."""
    if not Settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY not set — add it to .env to use the LLM matcher."
        )
    if not poly_markets or not kalshi_markets:
        return []

    user = (
        "Polymarket markets:\n" + _describe(poly_markets, "P")
        + "\n\nKalshi markets:\n" + _describe(kalshi_markets, "K")
        + "\n\nReturn the matches."
    )

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=Settings.MATCHER_MODEL,
        max_tokens=4000,
        system=_POLY_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": _POLY_SCHEMA}},
    )

    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    return [
        PolymarketMatch(
            poly_id=m["poly_market_id"],
            kalshi_id=m["kalshi_market_id"],
            confidence=m["confidence"],
            note=m["note"],
            outcome_map={p["poly_outcome"]: p["kalshi_outcome"] for p in m["outcome_map"]},
        )
        for m in data["matches"]
    ]


# --- DK Predictions <-> Kalshi futures (semantic match + outcome alignment) ---
# The deterministic name-overlap matcher handles distinctive multi-candidate boards
# (Person of the Year), but it can't match binary / generic-candidate boards (a Yes/No
# recession market, a Republicans/Democrats Senate market) whose meaning lives in the
# TITLE, not the candidates. This matcher reads both venues' full markets, picks the
# same-question Kalshi market for each DK board, AND aligns every DK outcome to its
# Kalshi equivalent — so the price comparison works even when the two venues name the
# sides differently (DK 'Republicans' -> Kalshi 'Republican Party').

_FUTURES_SYSTEM = (
    "You match prediction-market 'futures' boards across two venues: DraftKings "
    "Predictions and Kalshi. Each board is one question with one or more candidate "
    "outcomes. For each DraftKings board, find the SINGLE Kalshi market that resolves on "
    "the exact same real-world question, and align every DraftKings outcome to its "
    "economically-equivalent Kalshi outcome (e.g. DraftKings 'Republicans' -> Kalshi "
    "'Republican Party'; 'Yes' -> 'Yes'). Differently-worded titles can be the same "
    "question ('US Recession in 2026?' is the same as 'Recession this year?'); a "
    "different subject is NOT a match (a Texas Senate race is not a Georgia Senate race; "
    "2026 is not 2028; the US House is not the US Senate). Only return a match you are "
    "confident shares the exact same resolution; omit a board entirely when nothing "
    "lines up. Be conservative — a wrong match loses real money."
)

_FUTURES_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dk_market_id": {"type": "string"},
                    "kalshi_market_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "note": {"type": "string"},
                    "outcome_map": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dk_outcome": {"type": "string"},
                                "kalshi_outcome": {"type": "string"},
                            },
                            "required": ["dk_outcome", "kalshi_outcome"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["dk_market_id", "kalshi_market_id", "confidence", "note",
                             "outcome_map"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


@dataclass
class FuturesLLMMatch:
    dk_market_id: str
    kalshi_market_id: str
    confidence: float
    note: str
    outcome_map: dict[str, str]  # dk outcome name -> kalshi outcome name


def match_futures_llm(dk_markets: list[Market],
                      kalshi_markets: list[Market]) -> list[FuturesLLMMatch]:
    """Semantic match of DK Predictions boards to Kalshi markets, with outcome alignment."""
    if not Settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY not set — add it to .env to use the futures LLM matcher."
        )
    if not dk_markets or not kalshi_markets:
        return []

    user = (
        "DraftKings boards:\n" + _describe(dk_markets, "DK")
        + "\n\nKalshi markets:\n" + _describe(kalshi_markets, "K")
        + "\n\nReturn the matches."
    )

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=Settings.MATCHER_MODEL,
        max_tokens=4000,
        system=_FUTURES_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": _FUTURES_SCHEMA}},
    )

    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    return [
        FuturesLLMMatch(
            dk_market_id=m["dk_market_id"],
            kalshi_market_id=m["kalshi_market_id"],
            confidence=m["confidence"],
            note=m["note"],
            outcome_map={p["dk_outcome"]: p["kalshi_outcome"] for p in m["outcome_map"]},
        )
        for m in data["matches"]
    ]
