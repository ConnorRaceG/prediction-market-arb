"""
Discovery v2: navigate INTO DraftKings novelty (sport 9) and capture the
offers XHR (events + markets + odds). Finds real novelty league links in the
page rather than guessing slugs.

Run:  python scripts/explore_dk.py
"""

import json
import pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path("scripts/dk_capture")
OUT.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

captured: dict[str, str] = {}


def slug(url: str) -> str:
    s = url.split("?")[0].replace("https://", "").replace("/", "_")
    return s[:90]


def on_response(resp):
    try:
        url = resp.url
        if "sportscontent" in url and "json" in resp.headers.get("content-type", ""):
            captured[url] = resp.text()
    except Exception:
        pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(locale="en-US", user_agent=UA,
                                  viewport={"width": 1366, "height": 850})
        page = ctx.new_page()
        page.on("response", on_response)

        print("--> warming homepage")
        page.goto("https://sportsbook.draftkings.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)

        # Find real novelty links in the DOM (hrefs into sport 9 / novelty)
        hrefs = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.getAttribute('href')).filter(h => h && "
            "(h.includes('novelty') || h.includes('/sport/9/')))",
        )
        hrefs = list(dict.fromkeys(hrefs))  # dedupe, keep order
        print(f"\nFound {len(hrefs)} novelty links:")
        for h in hrefs[:25]:
            print(f"   {h}")

        # Visit league-specific novelty pages and capture their offers
        league_links = [h for h in hrefs if "/league/" in h or "/leagues/novelty/" in h]
        for h in league_links[:6]:
            url = h if h.startswith("http") else "https://sportsbook.draftkings.com" + h
            try:
                print(f"\n--> {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
            except Exception as e:
                print(f"    nav error: {str(e)[:70]}")

        browser.close()

    print(f"\n=== Captured {len(captured)} sportscontent responses ===")
    for url, body in captured.items():
        has_offers = '"selections"' in body or '"markets"' in body or '"events"' in body
        fname = OUT / (slug(url) + ".json")
        try:
            parsed = json.loads(body)
            fname.write_text(json.dumps(parsed, indent=2)[:400000], encoding="utf-8")
            tag = " <-- HAS OFFERS" if has_offers else ""
            print(f"  [{len(body):>7} B]{tag} {url[:90]}")
        except Exception:
            print(f"  [unparsed] {url[:90]}")


if __name__ == "__main__":
    main()
