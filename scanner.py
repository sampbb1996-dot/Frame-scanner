#!/usr/bin/env python3
"""
deal_radar_min.py — irreducible constraint-first deal monitor

Principles:
- Silence by default
- Veto-first gating
- One justified interruption only
- No optimization, no learning, no escalation

Action emitted:
- REVIEW LISTING
"""

import re
import time
import feedparser

# ----------------------------
# USER INPUT (only real knobs)
# ----------------------------

FEEDS = [
    # Example:
    # "https://www.gumtree.com.au/s-sydney/chairs/k0l3003435r10/rss",
]

MAX_BUY_PRICE = 80        # hard ceiling
POLL_SECONDS = 300        # 5 minutes

# ----------------------------
# Hard veto terms (disqualifiers)
# ----------------------------

VETO_TERMS = re.compile(
    r"\b(broken|faulty|repair|spares|not working|damaged|as[- ]is)\b",
    re.IGNORECASE,
)

PRICE_RE = re.compile(r"\$?\s*([0-9]{1,6})")

# ----------------------------
# Helpers
# ----------------------------

def parse_price(text: str):
    if not text:
        return None
    m = PRICE_RE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def disqualified(text: str) -> bool:
    return bool(VETO_TERMS.search(text))


# ----------------------------
# Core loop
# ----------------------------

def main():
    if not FEEDS:
        print("No feeds configured.")
        return

    seen = set()  # per-run only; not persistent

    while True:
        for feed_url in FEEDS:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:50]:
                title = entry.get("title", "") or ""
                link = entry.get("link", "") or ""
                summary = entry.get("summary", "") or ""

                key = link or title
                if not key or key in seen:
                    continue
                seen.add(key)

                text = f"{title} {summary}"

                # Hard veto first
                if disqualified(text):
                    continue

                price = parse_price(text)
                if price is None or price <= 0:
                    continue

                if price > MAX_BUY_PRICE:
                    continue

                # ---- ONLY JUSTIFIED EMISSION ----
                print("\n=== REVIEW LISTING ===")
                print(f"Title: {title}")
                print(f"Price: ${price}")
                print(f"Link: {link}")
                print("Reason: price ≤ ceiling and no disqualifiers")
                print("======================\n")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
