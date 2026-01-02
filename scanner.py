#!/usr/bin/env python3

import json
import re
import sys
import time
from urllib.request import Request, urlopen

import feedparser


# -----------------------
# FINAL LAYER INVARIANT
# -----------------------
# The program may only emit a task if action is justified.
# Otherwise, it must emit silence.


BAD_TERMS = re.compile(
    r"\b(broken|faulty|repair|spares|not working|damaged|as[- ]is)\b",
    re.IGNORECASE,
)

DURABLE_HINT = re.compile(
    r"\b(wood|timber|metal|steel|solid|chair|table|bench|cabinet|tool|garden|outdoor)\b",
    re.IGNORECASE,
)

PRICE_RE = re.compile(r"\$?\s*([0-9][0-9,]*)")


def parse_price(text):
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def justified(title, summary, price):
    """
    FINAL LAYER: binary permission gate
    """
    if not title or price is None:
        return False

    if price <= 0 or price > 250:
        return False

    text = f"{title} {summary}"

    if BAD_TERMS.search(text):
        return False

    if not DURABLE_HINT.search(text):
        return False

    return True


def main():
    with open("config.json", "r") as f:
        cfg = json.load(f)

    tasks = []

    for feed_url in cfg["feeds"]:
        feed = feedparser.parse(feed_url)

        for e in feed.entries[:40]:
            title = e.get("title", "")
            summary = e.get("summary", "")
            link = e.get("link", "")

            price = parse_price(title) or parse_price(summary)

            if justified(title, summary, price):
                tasks.append({
                    "action": "review_listing",
                    "title": title,
                    "price_aud": price,
                    "link": link
                })

    # SILENCE IS VALID OUTPUT
    output = {
        "timestamp": int(time.time()),
        "tasks": tasks,
        "count": len(tasks)
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
