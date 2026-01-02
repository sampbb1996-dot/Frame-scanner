#!/usr/bin/env python3
"""
deal_radar.py — constraint-first deal monitor with explicit BUY+SELL instructions.

What it does:
- Polls one or more RSS/Atom feeds (e.g., Gumtree search RSS).
- Extracts title/link/price.
- Applies simple "misprice band" rules.
- Emits *explicit* instruction checklists for:
    (1) BUY stage (how to message + offer bands)
    (2) SELL stage (how to list + accept/counter/floor bands)
- Optional email notification (SMTP) if you set env vars.

What it does NOT do:
- No adaptive negotiation.
- No stateful learning.
- No dynamic threshold tuning.
- No FB Marketplace scraping (use saved searches + RSS where available, or manual inputs).

Requires:
    pip install feedparser
"""

from __future__ import annotations

import os
import re
import time
import json
import sqlite3
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

import feedparser

# ----------------------------
# User-editable settings
# ----------------------------

# Add Gumtree RSS feeds here. You can generate these by doing a search on Gumtree
# and appending "/rss" in many cases, or using the "RSS" link if present.
FEEDS = [
    # مثال:
    # "https://www.gumtree.com.au/s-sydney/bar-stools/k0l3003435r10/rss",
]

# Keywords per feed (optional). If empty, accept all items in that feed.
KEYWORDS = {
    # feed_url: ["stool", "bar stool", "wicker"]
}

# Price bands per "category" tag. You can map feeds to categories in FEED_CATEGORY.
PRICE_BANDS = {
    # category: (max_buy_price, list_price, accept_at_or_above, floor_price)
    # "bar_stools": (80, 90, 70, 60),
}

FEED_CATEGORY = {
    # feed_url: "bar_stools"
}

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "300"))  # 5 minutes default
DB_PATH = os.getenv("DB_PATH", "deals.sqlite3")

# Optional: set to "1" to print verbose debug info
DEBUG = os.getenv("DEBUG", "0") == "1"

# Optional Email (SMTP). Leave unset to disable.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)

# ----------------------------
# Logging
# ----------------------------

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ----------------------------
# Data structures
# ----------------------------

@dataclass
class Listing:
    feed_url: str
    title: str
    link: str
    price: Optional[float]  # AUD
    published: Optional[str]

# ----------------------------
# Helpers
# ----------------------------

_PRICE_RE = re.compile(r"\$?\s*([0-9]{1,6})(?:\.[0-9]{1,2})?")

def parse_price(text: str) -> Optional[float]:
    """
    Extract first plausible price from a string.
    Gumtree RSS often contains "$123" in title/summary.
    """
    if not text:
        return None
    m = _PRICE_RE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def matches_keywords(listing: Listing) -> bool:
    kws = KEYWORDS.get(listing.feed_url, [])
    if not kws:
        return True
    hay = normalize(f"{listing.title} {listing.link}")
    return any(normalize(k) in hay for k in kws)

def listing_id(listing: Listing) -> str:
    h = hashlib.sha256()
    h.update((listing.link or listing.title).encode("utf-8", errors="ignore"))
    return h.hexdigest()[:24]

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ----------------------------
# SQLite storage
# ----------------------------

def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen (
            id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            feed_url TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            price REAL,
            published TEXT
        )
        """
    )
    conn.commit()

def is_seen(conn: sqlite3.Connection, lid: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen WHERE id = ?", (lid,))
    return cur.fetchone() is not None

def mark_seen(conn: sqlite3.Connection, lid: str, listing: Listing) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO seen (id, first_seen, feed_url, title, link, price, published)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (lid, now_utc_iso(), listing.feed_url, listing.title, listing.link, listing.price, listing.published),
    )
    conn.commit()

# ----------------------------
# Instruction templates (fixed, non-adaptive)
# ----------------------------

def buy_instructions(listing: Listing, max_buy: float) -> str:
    offer_open = max(1, int(max_buy * 0.75))  # simple fixed open anchor
    offer_cap = int(max_buy)

    msg = (
        "BUY STAGE — DO THIS (ONE PASS)\n"
        f"- Listing: {listing.title}\n"
        f"- Link: {listing.link}\n"
        f"- Seen price: {listing.price if listing.price is not None else 'unknown'}\n\n"
        "1) Message seller (copy/paste):\n"
        f"   \"Hi — is this still available? I can pick up today. Would you take ${offer_open}?\"\n\n"
        "2) Your hard cap:\n"
        f"   - Do NOT exceed: ${offer_cap}\n\n"
        "3) Counter rule (ONE counter max):\n"
        f"   - If they counter <= ${offer_cap}: accept.\n"
        f"   - If they counter > ${offer_cap}: decline politely and stop.\n\n"
        "4) Pickup constraint:\n"
        "   - Only proceed if pickup time/location is concrete.\n"
        "   - No long chats. No negotiation loops.\n"
    )
    return msg

def sell_instructions(list_price: float, accept_at: float, floor: float) -> str:
    midpoint = int((accept_at + floor) / 2)

    msg = (
        "SELL STAGE — DO THIS (ONE PASS)\n"
        f"- List price: ${int(list_price)}\n"
        f"- Accept at/above: ${int(accept_at)}\n"
        f"- Floor: ${int(floor)}\n\n"
        "Rules:\n"
        f"1) If offer >= ${int(accept_at)}: ACCEPT.\n"
        f"2) If offer < ${int(floor)}: DECLINE (polite) and STOP.\n"
        f"3) If ${int(floor)} <= offer < ${int(accept_at)}:\n"
        f"   - Counter ONCE at ${midpoint}.\n"
        "   - If they don’t accept: STOP. No loops.\n\n"
        "Listing copy (minimal):\n"
        "\"Outdoor bar stools / stools. Sturdy frame, good condition. Pickup.\"\n"
    )
    return msg

def combined_instructions(listing: Listing, bands: Tuple[float, float, float, float]) -> str:
    max_buy, list_price, accept_at, floor = bands
    return (
        "=== DEAL RADAR: ACTION PACKET ===\n"
        f"Category bands: max_buy=${int(max_buy)} | list=${int(list_price)} | accept>=${int(accept_at)} | floor=${int(floor)}\n\n"
        + buy_instructions(listing, max_buy)
        + "\n"
        + sell_instructions(list_price, accept_at, floor)
    )

# ----------------------------
# Email (optional)
# ----------------------------

def send_email(subject: str, body: str) -> None:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and EMAIL_TO and EMAIL_FROM):
        logging.info("Email not configured; skipping email send.")
        return

    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())

    logging.info("Email sent to %s", EMAIL_TO)

# ----------------------------
# Core loop
# ----------------------------

def extract_listing(feed_url: str, entry: Dict) -> Listing:
    title = entry.get("title", "") or ""
    link = entry.get("link", "") or ""
    published = entry.get("published", None) or entry.get("updated", None)

    # price often appears in title/summary
    summary = entry.get("summary", "") or entry.get("description", "") or ""
    price = parse_price(title) or parse_price(summary)

    return Listing(feed_url=feed_url, title=title, link=link, price=price, published=published)

def get_bands_for_listing(listing: Listing) -> Optional[Tuple[float, float, float, float]]:
    cat = FEED_CATEGORY.get(listing.feed_url, "")
    if not cat:
        return None
    bands = PRICE_BANDS.get(cat)
    return bands

def is_mispriced(listing: Listing, max_buy: float) -> bool:
    # If price unknown, we still alert (you can decide).
    if listing.price is None:
        return True
    return listing.price <= max_buy

def main() -> None:
    if not FEEDS:
        logging.error("No FEEDS configured. Add Gumtree RSS feed URLs to FEEDS in this file.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)

        logging.info("Deal radar started. Polling %d feeds every %ds", len(FEEDS), POLL_SECONDS)

        while True:
            for feed_url in FEEDS:
                try:
                    d = feedparser.parse(feed_url)
                    if d.bozo:
                        logging.warning("Feed parse issue for %s", feed_url)

                    for entry in d.entries[:50]:
                        listing = extract_listing(feed_url, entry)
                        if not listing.title and not listing.link:
                            continue

                        if not matches_keywords(listing):
                            continue

                        lid = listing_id(listing)
                        if is_seen(conn, lid):
                            continue

                        # mark as seen immediately to avoid repeats
                        mark_seen(conn, lid, listing)

                        bands = get_bands_for_listing(listing)
                        if not bands:
                            logging.info("Seen new listing (no bands configured): %s | %s", listing.title, listing.link)
                            continue

                        max_buy, list_price, accept_at, floor = bands
                        if not is_mispriced(listing, max_buy):
                            logging.info("New listing above max_buy ($%s): %s", int(max_buy), listing.title)
                            continue

                        packet = combined_instructions(listing, bands)
                        print("\n" + packet + "\n")

                        # Optional email
                        subject = f"Deal Radar: {listing.title[:80]}"
                        send_email(subject, packet)

                except Exception as e:
                    logging.exception("Error polling feed %s: %s", feed_url, e)

            time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
