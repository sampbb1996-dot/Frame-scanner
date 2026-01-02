#!/usr/bin/env python3
import json
import re
import time
import sys
import feedparser

# ==========================================================
# FINAL INVARIANT (DO NOT WEAKEN)
# Emit a task ONLY if action is justified.
# Otherwise emit silence (tasks=[]).
# ==========================================================

PRICE_RE = re.compile(r"\$?\s*([0-9][0-9,]*)")

BAD_TERMS = re.compile(
    r"\b(broken|faulty|repair|spares|not working|damaged|as[- ]is|cracked|missing)\b",
    re.IGNORECASE,
)

DURABLE_HINTS = re.compile(
    r"\b(wood|timber|metal|steel|aluminium|solid|chair|table|bench|cabinet|tool|garden|outdoor)\b",
    re.IGNORECASE,
)


def parse_price(text: str):
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except Exception:
        return None


def decision(title: str, summary: str, link: str, price, rules: dict):
    """
    Returns: (justified: bool, suggestive: dict)

    suggestive is NON-BINDING diagnostics only:
    - does not change behavior
    - does not schedule anything
    - does not adapt thresholds
    - does not create partial actions
    """
    s = {"notes": []}

    # Underdetermination vetoes (refuse to guess)
    if not title:
        s["notes"].append("title_missing")
        return False, s
    if not link:
        s["notes"].append("link_missing")
        return False, s
    if price is None:
        s["notes"].append("price_missing")
        return False, s

    # Hard bounds (configured, but still binary)
    min_price = int(rules.get("min_price", 1))
    max_price = int(rules.get("max_price", 250))

    if price < min_price:
        s["notes"].append("price_below_min")
        return False, s
    if price > max_price:
        s["notes"].append("price_above_max")
        return False, s

    text = f"{title} {summary}".strip()

    # Condition veto
    if BAD_TERMS.search(text):
        s["notes"].append("bad_condition_terms")
        return False, s

    # Durability requirement (minimal persistence signal)
    if not DURABLE_HINTS.search(text):
        s["notes"].append("durable_signal_weak")
        return False, s

    # If we got here, action is justified
    s["notes"].append("passes_gate")
    return True, s


def main():
    now = int(time.time())

    # Default output is silence
    output = {
        "timestamp": now,
        "tasks": [],
        "count": 0,
        # Suggestive, non-binary summary of why silence happened (informational only)
        "suggestive": {
            "silence_reason": None,
            "silence_notes": [],
            "stats": {}
        }
    }

    # Load config (silence if missing/invalid)
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        output["suggestive"]["silence_reason"] = "config_missing_or_invalid"
        print(json.dumps(output, ensure_ascii=False))
        return 0

    feeds = cfg.get("feeds", []) or []
    rules = cfg.get("rules", {}) or {}

    if not feeds:
        output["suggestive"]["silence_reason"] = "no_feeds_configured"
        print(json.dumps(output, ensure_ascii=False))
        return 0

    # Telemetry counters (non-binding)
    stats = {
        "feeds_seen": 0,
        "entries_seen": 0,
        "veto_title_or_link": 0,
        "veto_price_missing": 0,
        "veto_price_band": 0,
        "veto_bad_condition": 0,
        "veto_durable_weak": 0,
        "passed_gate": 0
    }

    for feed_url in feeds:
        stats["feeds_seen"] += 1
        feed = feedparser.parse(feed_url)

        # bounded work per feed
        for entry in (feed.entries[:40] if getattr(feed, "entries", None) else []):
            stats["entries_seen"] += 1

            title = entry.get("title", "") or ""
            summary = entry.get("summary", "") or ""
            link = entry.get("link", "") or ""

            price = parse_price(title) or parse_price(summary)

            ok, sug = decision(title, summary, link, price, rules)

            # Update telemetry (still non-binding)
            notes = set(sug.get("notes", []))
            if "title_missing" in notes or "link_missing" in notes:
                stats["veto_title_or_link"] += 1
            elif "price_missing" in notes:
                stats["veto_price_missing"] += 1
            elif "price_below_min" in notes or "price_above_max" in notes:
                stats["veto_price_band"] += 1
            elif "bad_condition_terms" in notes:
                stats["veto_bad_condition"] += 1
            elif "durable_signal_weak" in notes:
                stats["veto_durable_weak"] += 1
            elif "passes_gate" in notes:
                stats["passed_gate"] += 1

            # FINAL INVARIANT: only emit a task if justified
            if ok:
                output["tasks"].append({
                    "action": "review_listing",
                    "title": title,
                    "price_aud": price,
                    "link": link
                })

    output["count"] = len(output["tasks"])
    output["suggestive"]["stats"] = stats

    # If silent, provide a *suggestive* reason (does not trigger action)
    if output["count"] == 0:
        output["suggestive"]["silence_reason"] = "no_justified_tasks"
        # optional hinting, still non-binding
        if stats["veto_price_missing"] > 0:
            output["suggestive"]["silence_notes"].append("many_entries_missing_price")
        if stats["veto_durable_weak"] > 0:
            output["suggestive"]["silence_notes"].append("many_entries_lack_durable_terms")
        if stats["veto_bad_condition"] > 0:
            output["suggestive"]["silence_notes"].append("many_entries_flagged_bad_condition")

    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
