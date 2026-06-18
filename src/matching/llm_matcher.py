"""
LLM-assisted novelty matcher.

Novelty markets (Oscars, contests, awards) can't be matched by a team registry:
the events and outcomes are free text, and the two venues structure them
differently (DraftKings "Over/Under 76.5" vs Kalshi bucket markets). So we ask
Claude to read both venues' markets and return economically-equivalent matches
with aligned outcomes.

Uses the official Anthropic SDK with structured JSON output. Model is
configurable (Settings.MATCHER_MODEL, default claude-opus-4-8).
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
