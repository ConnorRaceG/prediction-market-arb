"""
DraftKings novelty adapter (browser-scraped).

DK's JSON API is Akamai-protected, so plain HTTP gets 403. Instead we drive a
real Chromium via Playwright, let the page load, and capture the internal
`sportscontent` JSON responses (events / markets / selections) flying by.

Novelty (sport id 9) covers awards, entertainment, and one-off contests
(e.g. Nathan's Hot Dog Eating Contest). Structure:
    events    -> the contest/show
    markets   -> a betting market within it ("Total Hot Dogs Eaten by ...")
    selections-> the priced outcomes ("Over 76.5" +180, "Under 76.5" -250)
"""

import json
from src.adapters.base import BaseAdapter
from src.models import Market, Outcome

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

NOVELTY_SPORT_ID = "9"  # DraftKings sport id for Novelty (awards/entertainment/contests)

DK_HOME = "https://sportsbook.draftkings.com/"
DK_BASE = "https://sportsbook.draftkings.com"


def _parse_american(s: str) -> float | None:
    """DK uses a Unicode minus (U+2212) for negative odds; normalize it."""
    if not s:
        return None
    s = s.replace("−", "-").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


class DKNoveltyAdapter(BaseAdapter):
    """Scrapes DraftKings novelty (sport 9) markets via a real browser."""

    def __init__(self, headless: bool = False):
        super().__init__("dk_novelty")
        self.headless = headless

    def fetch_markets(self, sport: str = "novelty", market_type: str = "novelty") -> list[Market]:
        captured = self._scrape()
        return self._parse(captured)

    # ---- Browser scrape ----

    def _scrape(self) -> dict[str, str]:
        from playwright.sync_api import sync_playwright

        captured: dict[str, str] = {}

        def on_response(resp):
            try:
                if "sportscontent" in resp.url and "json" in resp.headers.get("content-type", ""):
                    captured[resp.url] = resp.text()
            except Exception:
                pass

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            ctx = browser.new_context(locale="en-US", user_agent=UA,
                                      viewport={"width": 1366, "height": 850})
            page = ctx.new_page()
            page.on("response", on_response)

            page.goto(DK_HOME, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)

            # Discover live novelty league links from the page itself
            hrefs = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.getAttribute('href')).filter(h => h && "
                "(h.includes('novelty') || h.includes('/sport/9/')))",
            )
            league_links = [h for h in dict.fromkeys(hrefs)
                            if "/leagues/novelty/" in h or "/league/" in h]

            for h in league_links:
                url = h if h.startswith("http") else DK_BASE + h
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(4000)
                except Exception:
                    pass

            browser.close()
        return captured

    # ---- Normalize ----

    def _parse(self, captured: dict[str, str]) -> list[Market]:
        events, markets, sels_by_market = {}, {}, {}
        for body in captured.values():
            try:
                data = json.loads(body)
            except Exception:
                continue
            for e in data.get("events") or []:
                events[e["id"]] = e
            for m in data.get("markets") or []:
                markets[m["id"]] = m
            for s in data.get("selections") or []:
                sels_by_market.setdefault(s["marketId"], []).append(s)

        out = []
        for mid, m in markets.items():
            if str(m.get("sportId")) != NOVELTY_SPORT_ID:
                continue  # drop non-novelty noise captured from the home page
            outcomes = []
            for s in sels_by_market.get(mid, []):
                american = _parse_american((s.get("displayOdds") or {}).get("american"))
                if american is None:
                    continue
                outcomes.append(Outcome(name=s.get("label", "?"), odds_american=american))
            if len(outcomes) < 2:
                continue  # need both sides to be useful for arb

            ev = events.get(m.get("eventId"), {})
            out.append(self._create_market(
                market_id=mid,
                event_name=ev.get("name", m.get("name", "")),
                market_type=m.get("name", "novelty"),
                outcomes=outcomes,
                url=DK_BASE + "/leagues/novelty",
                raw_data={"event": ev, "market": m, "selections": sels_by_market.get(mid, [])},
            ))
        return out


if __name__ == "__main__":
    adapter = DKNoveltyAdapter(headless=False)
    markets = adapter.fetch_markets()
    print(f"\nScraped {len(markets)} DraftKings novelty markets:\n")
    for m in markets:
        print(f"  [{m.event_name[:40]}] {m.market_type}")
        for o in m.outcomes:
            print(f"       {o.name:22s} {o.odds_american:+.0f}  (implied {o.implied_prob:.1%})")
