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
import random
import time
from dataclasses import dataclass

from src.adapters.base import BaseAdapter
from src.models import Market, Outcome

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

ORIGIN = "https://predictions.draftkings.com"
BASE = ORIGIN + "/en"
POLL_MARKER = "predict/v1/polling"  # the DK Predictions price-polling endpoint

# The four most interesting (loosely-priced) categories per the user.
DEFAULT_CATEGORIES = ("culture", "politics", "economics", "business")

# Human-like pause (seconds) between page loads. Back-to-back loads are the single
# most bot-looking thing we can do, and the thing that trips DraftKings' (Akamai) bot
# detection; a little jitter spreads the footprint so a scan reads less like a script.
JITTER_SECS = (1.2, 3.5)

# Minimal anti-automation shim: hide the `navigator.webdriver` flag Akamai keys on.
# Cheap, low-risk, and helps in both headed and headless modes.
_STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


@dataclass
class BoardSpec:
    """A discovered board we *could* price, before paying to load it."""
    ticker: str
    title: str
    url: str
    category: str = ""


# Collect the market-group detail links on a category page, with a best-effort board
# name from the card text (used only to pre-rank what's worth pricing — the real title
# is read off the board itself when we actually price it).
_GROUP_LINKS_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const h = a.getAttribute('href');
    if (!h || !h.includes('market-group-details')) continue;
    let title = '';
    for (const ln of (a.innerText || '').split('\n')) {
      const t = norm(ln);
      if (t.length >= 4 && t.length <= 70 && /[a-zA-Z]/.test(t) && !/^(Yes|No)[+\-]/.test(t)) {
        title = t; break;
      }
    }
    out.push({ href: h, title });
  }
  return out;
}
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
    """Scrapes DraftKings Predictions multi-outcome boards (browser + API prices).

    Discovery and pricing are separated on purpose: listing the boards on a category
    page is cheap (a handful of loads) and tells us everything that's open right now,
    including brand-new boards. Pricing a board is the expensive part (a page load plus
    a wait for its price poll). Callers discover the full catalog every time but only
    pay to price the boards worth pricing, which keeps the request footprint small
    enough to stay under DraftKings' throttle.
    """

    def __init__(self, headless: bool = False, profile_dir: str | None = None,
                 verbose: bool = False):
        super().__init__("dk_predictions")
        self.headless = headless
        # A persistent browser profile keeps Akamai's sensor cookies between runs, so
        # we look like a returning browser instead of a cold bot each scan. Optional:
        # falls back to an ephemeral context if the profile can't be opened (e.g. a
        # second process already holds it).
        self.profile_dir = profile_dir
        # A headless scan is silent for minutes; verbose prints per-step progress so the
        # caller can see it's working (and which board it's on) instead of a black box.
        self.verbose = verbose
        self._order: list[str] = []     # this group's tickers, in display order
        self._prices: dict[str, dict] = {}  # ticker -> {yesAsk, yesBid, noAsk, noBid}

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    # ---- public API: discover cheaply, then price selectively ----

    def discover(self, categories=DEFAULT_CATEGORIES,
                 max_per_cat: int = 40) -> list[BoardSpec]:
        """List every open board across the categories (no pricing). Cheap: one load
        per category. Returns BoardSpecs the caller can prioritize before pricing."""
        return self._run_session(
            lambda page: self._discover_on(page, categories, max_per_cat))

    def price_boards(self, specs: list[BoardSpec],
                     market_type: str = "futures") -> list[Market]:
        """Price a specific list of discovered boards in one browser session."""
        if not specs:
            return []
        return self._run_session(
            lambda page: self._price_on(page, specs, market_type))

    def fetch_markets(self, categories=DEFAULT_CATEGORIES,
                      max_groups_per_cat: int = 25, market_type: str = "futures") -> list[Market]:
        """Discover and price every board, in one session (the old all-in-one path)."""
        def _both(page):
            specs = self._discover_on(page, categories, max_groups_per_cat)
            return self._price_on(page, specs, market_type)
        return self._run_session(_both)

    def fetch_group(self, group_url: str, category: str = "",
                    market_type: str = "futures") -> Market | None:
        """Scrape a single market-group detail page."""
        ticker = group_url.rstrip("/").split("/")[-1]
        spec = BoardSpec(ticker=ticker, title=ticker.replace("-", " "),
                         url=group_url, category=category)
        out = self.price_boards([spec], market_type)
        return out[0] if out else None

    # ---- internals ----

    def _run_session(self, fn):
        """Open one browser session (warm profile if set, else ephemeral), wire up the
        price-capture handler and stealth shim, run `fn(page)`, and always clean up."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = browser = None
            try:
                if self.profile_dir:
                    try:
                        ctx = p.chromium.launch_persistent_context(
                            self.profile_dir, headless=self.headless, locale="en-US",
                            user_agent=UA, viewport={"width": 1440, "height": 900})
                    except Exception:
                        ctx = None  # profile busy/unwritable -> ephemeral below
                if ctx is None:
                    browser = p.chromium.launch(headless=self.headless)
                    ctx = browser.new_context(locale="en-US", user_agent=UA,
                                              viewport={"width": 1440, "height": 900})
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.add_init_script(_STEALTH_JS)
                page.on("response", self._on_response)
                return fn(page)
            finally:
                if browser is not None:
                    browser.close()
                elif ctx is not None:
                    ctx.close()

    @staticmethod
    def _jitter(page) -> None:
        page.wait_for_timeout(int(random.uniform(*JITTER_SECS) * 1000))

    def _discover_on(self, page, categories, max_per_cat: int) -> list[BoardSpec]:
        specs, seen = [], set()
        for cat in categories:
            found = self._category_boards(page, cat)[:max_per_cat]
            for spec in found:
                if spec.ticker not in seen:
                    seen.add(spec.ticker)
                    specs.append(spec)
            self._log(f"[dk] discovered {len(found)} boards in '{cat}'")
            self._jitter(page)
        self._log(f"[dk] {len(specs)} unique boards discovered")
        return specs

    def _price_on(self, page, specs: list[BoardSpec], market_type: str) -> list[Market]:
        markets = []
        total = len(specs)
        for i, spec in enumerate(specs, 1):
            self._log(f"[dk] pricing {i}/{total}: {spec.ticker}")
            m = self._scrape_group(page, spec.url, spec.category, market_type)
            if m is not None:
                markets.append(m)
            self._jitter(page)
        self._log(f"[dk] priced {len(markets)}/{total} boards")
        return markets

    def _category_boards(self, page, category: str) -> list[BoardSpec]:
        try:
            page.goto(f"{BASE}/{category}", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            raw = page.evaluate(_GROUP_LINKS_JS)
        except Exception:
            return []
        out, seen = [], set()
        for item in raw:
            h = item.get("href") or ""
            u = h if h.startswith("http") else ORIGIN + h
            ticker = u.rstrip("/").split("/")[-1]
            if ticker in seen:
                continue
            seen.add(ticker)
            title = (item.get("title") or "").strip() or ticker.replace("-", " ")
            out.append(BoardSpec(ticker=ticker, title=title, url=u, category=category))
        return out

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
