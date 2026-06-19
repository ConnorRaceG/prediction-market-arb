"""
DraftKings Predictions adapter (browser-loaded, API-priced).

predictions.draftkings.com is DraftKings' CFTC-regulated prediction market — NOT
the sportsbook. Its boards are multi-outcome "who wins X" markets priced as binary
YES/NO contracts in cents, exactly like Kalshi (Person of the Year, awards, politics,
economics, business). This is where the loosely-priced, low-volume edge lives.

Pricing is DETERMINISTIC: we read exact cent prices from DraftKings' own JSON API
(`api.draftkings.com/en/predict/v1/polling/...` -> per-ticker yesAsk/yesBid/noAsk/
noBid), captured off the wire. We drive a real browser only to satisfy DK's geo/CDN
and load each board; we do NOT read prices off the screen. Candidate names come from
the rendered board and are joined to the API tickers by display order (both the DOM
rows and the polling request are in the same candidate order). If that join can't be
trusted (counts differ), we fall back to the on-screen American odds.

Detection only — like the other novelty/Polymarket tracks, this reads public prices
to compare against Kalshi; it never touches a DK account or places a trade.
"""

import json
from src.adapters.base import BaseAdapter
from src.models import Market, Outcome

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

ORIGIN = "https://predictions.draftkings.com"
BASE = ORIGIN + "/en"
POLL_MARKER = "predict/v1/polling"  # the DK Predictions price-polling endpoint

# The four most interesting (loosely-priced) categories per the user.
DEFAULT_CATEGORIES = ("culture", "politics", "economics", "business")

# Collect the market-group detail links on a category page.
_GROUP_LINKS_JS = """
() => Array.from(document.querySelectorAll('a[href]'))
  .map(a => a.getAttribute('href'))
  .filter(h => h && h.includes('market-group-details'))
"""

# Read one board: the group title + each candidate's name and on-screen Yes/No odds,
# in display order. We anchor on each Yes button and climb to the nearest ancestor
# holding the row's name <p>, so name and (fallback) price stay paired.
_BOARD_JS = r"""
() => {
  const norm = s => (s || '').replace(/−/g, '-').replace(/\s+/g, ' ').trim();
  // Prefer the page <title> (the board name); fall back to the longest heading.
  let title = norm(document.title).split('|')[0].split(' - ')[0].trim();
  if (!title || /^(draftkings predictions|predictions|home)$/i.test(title)) {
    const heads = Array.from(document.querySelectorAll('h1,h2,h3'))
      .map(h => norm(h.textContent))
      .filter(t => t && t.length <= 60 && !/^(DraftKings Predictions|Predictions|Home)$/i.test(t));
    title = heads.sort((a, b) => b.length - a.length)[0] || title;
  }
  const rows = [];
  const seen = new Set();
  for (const btn of document.querySelectorAll('button')) {
    const compact = norm(btn.innerText).replace(/\s+/g, '');
    const m = compact.match(/^Yes([+\-]\d+)$/);
    if (!m) continue;
    const yes = m[1];
    let row = btn, name = '', no = '';
    for (let i = 0; i < 7 && row; i++) {
      row = row.parentElement;
      if (!row) break;
      const p = row.querySelector('p');
      if (p && norm(p.textContent)) {
        name = norm(p.textContent);
        for (const b2 of row.querySelectorAll('button')) {
          const c2 = norm(b2.innerText).replace(/\s+/g, '');
          const mn = c2.match(/^No([+\-]\d+)$/);
          if (mn) no = mn[1];
        }
        break;
      }
    }
    if (name && !seen.has(name)) { seen.add(name); rows.push({ name, yes, no }); }
  }
  return { title, rows };
}
"""


def _parse_american(s) -> float | None:
    """DK uses a Unicode minus (U+2212) for negatives; normalize and parse."""
    if not s:
        return None
    s = str(s).replace("−", "-").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _american_to_implied(american: float | None) -> float | None:
    if american is None:
        return None
    decimal = 1 + (american / 100 if american > 0 else 100 / abs(american))
    return 1 / decimal


class DKPredictionsAdapter(BaseAdapter):
    """Scrapes DraftKings Predictions multi-outcome boards (browser + API prices)."""

    def __init__(self, headless: bool = False):
        super().__init__("dk_predictions")
        self.headless = headless
        self._order: list[str] = []     # this group's tickers, in display order
        self._prices: dict[str, dict] = {}  # ticker -> {yesAsk, yesBid, noAsk, noBid}

    def fetch_markets(self, categories=DEFAULT_CATEGORIES,
                      max_groups_per_cat: int = 25, market_type: str = "futures") -> list[Market]:
        """Scrape each category's market groups into one Market per group."""
        from playwright.sync_api import sync_playwright

        markets: list[Market] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = self._new_page(browser)
            for cat in categories:
                for url in self._group_links(page, cat)[:max_groups_per_cat]:
                    m = self._scrape_group(page, url, cat, market_type)
                    if m is not None:
                        markets.append(m)
            browser.close()
        return markets

    def fetch_group(self, group_url: str, category: str = "",
                    market_type: str = "futures") -> Market | None:
        """Scrape a single market-group detail page (own browser session)."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = self._new_page(browser)
            m = self._scrape_group(page, group_url, category, market_type)
            browser.close()
        return m

    # ---- internals ----

    def _new_page(self, browser):
        ctx = browser.new_context(locale="en-US", user_agent=UA,
                                  viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("response", self._on_response)
        return page

    def _on_response(self, resp):
        """Capture exact cent prices (and candidate order) from the polling API."""
        try:
            if POLL_MARKER not in resp.url:
                return
            req = json.loads(resp.request.post_data or "{}")
            tickers = req.get("marketTickers")
            if tickers:
                self._order = tickers  # ordered candidate tickers for the live board
            body = json.loads(resp.text())
            for tk, m in (body.get("markets") or {}).items():
                binary = (m.get("details") or {}).get("binary") or {}
                self._prices[tk] = binary
        except Exception:
            pass

    def _group_links(self, page, category: str) -> list[str]:
        try:
            page.goto(f"{BASE}/{category}", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            hrefs = page.evaluate(_GROUP_LINKS_JS)
        except Exception:
            return []
        seen, out = set(), []
        for h in hrefs:
            u = h if h.startswith("http") else ORIGIN + h
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _scrape_group(self, page, url: str, category: str, market_type: str) -> Market | None:
        self._order = []  # reset so we only use THIS group's polling
        group_ticker = url.rstrip("/").split("/")[-1]
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # the price poll fires a few seconds after load; wait for THIS group's poll
            for _ in range(24):  # up to ~12s
                page.wait_for_timeout(500)
                if any(t.startswith(group_ticker) for t in self._order):
                    break
            page.wait_for_timeout(800)  # settle once prices have arrived
            board = page.evaluate(_BOARD_JS)
        except Exception:
            return None

        rows = board.get("rows", [])
        tickers = [t for t in self._order if t.startswith(group_ticker)]
        # Trust the exact-cent API join only when its candidate count matches the board.
        use_api = bool(tickers) and len(tickers) == len(rows)

        # implied prob (cost to buy) per side; None where there's no real ask offer.
        candidates = []
        for i, r in enumerate(rows):
            yes = no = None
            if use_api:
                b = self._prices.get(tickers[i], {})
                if b.get("hasYesAskOffers") and b.get("yesAsk") is not None:
                    yes = b["yesAsk"] / 100
                if b.get("hasNoAskOffers") and b.get("noAsk") is not None:
                    no = b["noAsk"] / 100
            else:  # no trustworthy API join -> fall back to on-screen American odds
                yes = _american_to_implied(_parse_american(r.get("yes")))
                no = _american_to_implied(_parse_american(r.get("no")))
            candidates.append({"name": r["name"], "yes": yes, "no": no})

        priced = [c for c in candidates if c["yes"] is not None]
        if len(priced) < 2:
            return None

        outcomes = [Outcome(name=c["name"], implied_prob=c["yes"]) for c in priced]
        return self._create_market(
            market_id=group_ticker,
            event_name=board.get("title") or group_ticker,
            market_type=market_type,
            outcomes=outcomes,
            url=url,
            raw_data={"category": category, "candidates": candidates,
                      "priced_via": "api" if use_api else "dom"},
        )


if __name__ == "__main__":
    adapter = DKPredictionsAdapter(headless=False)
    markets = adapter.fetch_markets(categories=("culture",), max_groups_per_cat=5)
    print(f"\nScraped {len(markets)} DK Predictions culture boards:\n")
    for m in markets:
        via = (m.raw_data or {}).get("priced_via")
        print(f"  [{m.event_name}] ({len(m.outcomes)} candidates, priced_via={via})")
        for o in m.outcomes[:6]:
            print(f"       {o.name:28s} {o.implied_prob*100:5.1f}c")
