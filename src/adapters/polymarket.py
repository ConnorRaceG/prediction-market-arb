"""
Polymarket adapter (Gamma API).

Polymarket is a CLOB prediction market on Polygon. Its public Gamma API
(https://gamma-api.polymarket.com) serves market metadata and prices with NO auth
for reads — we never touch a wallet because we only read prices (detection, not
execution).

Most Polymarket markets are binary Yes/No questions on a single proposition
("New Rihanna Album before GTA VI?"), so — like Kalshi novelty markets — they
match by TEXT (via the LLM matcher), not a team registry. Gamma returns each
outcome's price already in [0,1] (an implied probability), as JSON-encoded string
arrays alongside the outcome labels.

Multi-outcome events (e.g. an election with many candidates) are split by
Polymarket into a GROUP of binary "Will X win?" markets under one event; we treat
each binary market independently for now (negRisk grouping is a later refinement).
"""

import json
import requests

from src.adapters.base import BaseAdapter
from src.models import Market, Outcome
from src.timeutil import iso_to_unix, et_date

GAMMA_BASE = "https://gamma-api.polymarket.com"


def _parse_json_list(value) -> list:
    """Gamma encodes outcomes / prices / token-ids as JSON strings (occasionally
    already lists). Return a real list either way."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return []


class PolymarketAdapter(BaseAdapter):
    """Reads liquid, currently-tradeable Polymarket markets via the public Gamma API."""

    def __init__(self, min_liquidity: float = 1000.0):
        super().__init__("polymarket")
        self.min_liquidity = min_liquidity
        self._session = requests.Session()

    def _get(self, path: str, params: dict) -> list:
        resp = self._session.get(GAMMA_BASE + path, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])

    def fetch_markets(self, sport: str = "", market_type: str = "novelty",
                      max_markets: int = 150) -> list[Market]:
        """
        Fetch the most-liquid open, order-book-enabled markets.

        `sport` / `market_type` are accepted for interface parity but unused —
        Polymarket markets are propositions matched by text, not by sport. We page
        highest-volume-first and keep markets above the liquidity floor.
        """
        markets: list[Market] = []
        page = 100
        for offset in range(0, 2000, page):  # bounded crawl
            batch = self._get("/markets", {
                "closed": "false", "active": "true",
                "limit": page, "offset": offset,
                "order": "volumeNum", "ascending": "false",
            })
            if not batch:
                break
            for raw in batch:
                market = self._to_market(raw)
                if market is not None:
                    markets.append(market)
            if len(markets) >= max_markets or len(batch) < page:
                break
        return markets[:max_markets]

    def _to_market(self, raw: dict) -> Market | None:
        # Only markets you can actually trade right now
        if not (raw.get("enableOrderBook") and raw.get("acceptingOrders")):
            return None
        if (raw.get("liquidityNum") or 0) < self.min_liquidity:
            return None

        names = _parse_json_list(raw.get("outcomes"))
        prices = _parse_json_list(raw.get("outcomePrices"))
        if len(names) != len(prices) or len(names) < 2:
            return None
        outcomes = []
        for name, price in zip(names, prices):
            try:
                prob = float(price)
            except (TypeError, ValueError):
                continue
            if 0 < prob < 1:
                outcomes.append(Outcome(name=str(name), implied_prob=prob))
        if len(outcomes) < 2:
            return None

        # endDate is the resolution time — the only meaningful date for a
        # proposition market (there's no "kickoff"). Used for display/context.
        end_iso = raw.get("endDate") or raw.get("endDateIso")
        resolve_time = iso_to_unix(end_iso) if end_iso else None
        slug = raw.get("slug")
        return self._create_market(
            market_id=str(raw.get("id")),
            event_name=raw.get("question", ""),
            market_type="novelty",
            outcomes=outcomes,
            url=f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com",
            raw_data={
                "conditionId": raw.get("conditionId"),
                "clobTokenIds": _parse_json_list(raw.get("clobTokenIds")),
                "slug": slug,
                "liquidityNum": raw.get("liquidityNum"),
                "volumeNum": raw.get("volumeNum"),
                "negRisk": raw.get("negRisk"),
            },
            start_time=resolve_time,
            slate_date=et_date(resolve_time) if resolve_time else None,
        )


if __name__ == "__main__":
    adapter = PolymarketAdapter()
    markets = adapter.fetch_markets()
    print(f"Fetched {len(markets)} liquid Polymarket markets\n")
    for m in markets[:15]:
        liq = (m.raw_data or {}).get("liquidityNum") or 0
        print(f"  [{liq:>10,.0f}] {m.event_name[:60]}")
        for o in m.outcomes:
            print(f"       {o.name:18s} {o.implied_prob:.3f}")
