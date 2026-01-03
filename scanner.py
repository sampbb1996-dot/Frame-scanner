#!/usr/bin/env python3
"""
collapse_radar.py

Terminal constraint-first deal detector.

Invariant:
- Silence is the default.
- Action is emitted ONLY when an external fact forces it.
- No suggestion, no optimisation, no decay, no pressure signals.

This system detects ONLY externally-forced BUY events.
It never suggests SELL actions or price changes.

Dependencies:
    pip install feedparser
"""

import hashlib
import sqlite3
import time
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser

# =========================
# USER CONFIG (explicit)
# =========================

FEEDS = [
    # Example:
    # "https://www.gumtree.com.au/s-sydney/chairs/k0l3003435r10/rss"
]

MAX_BUY_PRICE = 50  # hard constraint, not a heuristic
DB_PATH = "collapse_seen.sqlite"
POLL_SECONDS = 300

# =========================
# INTERNALS
# =========================

PRICE_RE = re.compile(r"\$?\s*([0-9]{1,6})")

def extract_price(text: str) -> Optional[int]:
    if not text:
        return None
    m = PRICE_RE.search(text.replace(",", ""))
    return int(m.group(1)) if m else None

def listing_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24]

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

# =========================
# STORAGE (minimal state)
# =========================

def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL
        )
    """)
    conn.commit()

def already_seen(conn, lid: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM seen WHERE id = ?", (lid,)
    ).fetchone() is not None

def mark_seen(conn, lid: str):
    conn.execute(
        "INSERT OR IGNORE INTO seen (id, first_seen) VALUES (?, ?)",
        (lid, utc_now())
    )
    conn.commit()

# =========================
# COLLAPSE CONDITION
# =========================

def forced_buy_event(price: Optional[int]) -> bool:
    """
    Returns True ONLY if reality forces a decision.
    Unknown price does NOT force action.
    """
    if price is None:
        return False
    return price <= MAX_BUY_PRICE

# =========================
# MAIN LOOP
# =========================

def main():
    if not FEEDS:
        raise RuntimeError("No feeds configured.")

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)

        while True:
            for feed_url in FEEDS:
                feed = feedparser.parse(feed_url)

                for entry in feed.entries:
                    link = entry.get("link")
                    if not link:
                        continue

                    lid = listing_id(link)
                    if already_seen(conn, lid):
                        continue

                    mark_seen(conn, lid)

                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    price = extract_price(title) or extract_price(summary)

                    if forced_buy_event(price):
                        print("\n=== FORCED ACTION ===")
                        print(f"TITLE: {title}")
                        print(f"PRICE: ${price}")
                        print(f"LINK:  {link}")
                        print("====================\n")

            time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
