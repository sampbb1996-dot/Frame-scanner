#!/usr/bin/env python3
"""
deal_radar.py — constraint-first deal monitor (RANGES ONLY)

What it does:
- Polls RSS/Atom feeds (e.g., Gumtree search RSS).
- Extracts title / link / price.
- Applies simple mispricing gate.
- Emits:
    • review task
    • non-binding BUY RANGE
    • non-binding SELL RANGE
    • reason the listing passed

What it does NOT do:
- No scripts
- No negotiation instructions
- No counters / floors
- No future commitments
- No adaptive logic
"""

import re
import time
import sqlite3
import hashlib
import feedparser
from datetime import datetime, timezone
from typing import Optional, Tuple

# ----------------------------
# USER SETTINGS (simple)
# ----------------------------

FEEDS = [
    # "https://www.gumtree.com.au/s-sydney/bar-stools/k0l3003435r10/rss",
]

# Map feed → category
FEED_CATEGORY = {
    # feed_url: "bar_stools"
}

# Category price logic (ranges only)
# category: (max_buy, suggested_list)
PRICE_LOGIC = {
    # "bar_stools": (80, 100),
}

POLL_SECONDS = 300
DB_PATH = "seen.sqlite3"

# ----------------------------
# Helpers
# ----------------------------

PRICE_RE = re.compile(r"\$?\s*([0-9]{1,6})")

BAD_TERMS = re.compile(
    r"\b(broken|faulty|repair|spares|not working|damaged|as[- ]is)\b",
    re.IGNORECASE,
)

DURABLE_HINTS = re.compile(
    r"\b(wood|metal|steel|solid|chair|table|bench|cabinet|tool|garden|outdoor)\b",
    re.IGNORECASE,
)


def parse_price(text: str) -> Optional[int]:
    if not text:
        return None
    m = PRICE_RE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def listing_id(link: str, title: str) -> str:
    h = hashlib.sha256()
    h.update((link or title).encode("utf-8", errors="ignore"))
    return h.hexdigest()[:24]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------
# SQLite (dedupe only)
# ----------------------------

def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen (
            id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL
        )
        """
    )
    conn.commit()


def seen(conn, lid: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen WHERE id = ?", (lid,))
    return cur.fetchone() is not None


def mark_seen(conn, lid: str):
    conn.execute(
        "INSERT OR IGNORE INTO seen (id, first_seen) VALUES (?, ?)",
        (lid, now_iso()),
    )
    conn.commit()


# ----------------------------
# Core logic
# ----------------------------

def passed_gate(title: str, summary: str, price: Optional[int], max_buy: int) -> bool:
    if not title or price is None:
        return False
    if price > max_buy or price <= 0:
        return False
    text = f"{title} {summary}"
    if BAD_TERMS.search(text):
        return False
    if not DURABLE_HINTS.search(text):
        return False
    return True


def ranges(max_buy: int, list_price: int) -> Tuple[str, str]:
    buy_low = int(max_buy * 0.7)
    buy_high = max_buy
    sell_low = int(list_price * 0.85)
    sell_high = int(list_price * 1.1)

    buy_range = f"${buy_low}–${buy_high}"
    sell_range = f"${sell_low}–${sell_high}"
    return buy_range, sell_range


# ----------------------------
# Main loop
# ----------------------------

def main():
    if not FEEDS:
        print("No feeds configured.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)

        while True:
            for feed_url in FEEDS:
                category = FEED_CATEGORY.get(feed_url)
                logic = PRICE_LOGIC.get(category)

                if not category or not logic:
                    continue

                max_buy, list_price = logic

                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:50]:
                    title = entry.get("title", "") or ""
                    link = entry.get("link", "") or ""
                    summary = entry.get("summary", "") or ""

                    price = parse_price(title) or parse_price(summary)
                    lid = listing_id(link, title)

                    if seen(conn, lid):
                        continue

                    mark_seen(conn, lid)

                    if not passed_gate(title, summary, price, max_buy):
                        continue

                    buy_r, sell_r = ranges(max_buy, list_price)

                    # SINGLE allowed task: review listing
                    print("\n=== REVIEW LISTING ===")
                    print(f"Title: {title}")
                    print(f"Link: {link}")
                    print(f"Seen price: ${price}")
                    print(f"Reason: price ≤ max_buy and durability signal present")
                    print("\nNon-binding ranges:")
                    print(f"- Buy range:  {buy_r}")
                    print(f"- Sell range: {sell_r}")
                    print("Use judgment at contact time.")
                    print("======================\n")

            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
