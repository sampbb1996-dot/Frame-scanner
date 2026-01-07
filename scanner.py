# scanner.py
# Adversarial mispricing sentinel:
# - pulls candidate pages
# - extracts price(s)
# - scores "belief-error signals"
# - Tier gates (no fake precision)
# - emails ONLY Tier-2 events
#
# Requires env vars (GitHub Secrets):
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO
# Optional:
#   EMAIL_FROM (defaults to SMTP_USER)
#   LABEL_TAG (defaults to "MISPRICING")
#
# Files:
#   config.yaml  (candidates + regexes + signal rules)
#   state.json   (dedupe; persisted via GitHub Actions cache if you enable it)

import json
import os
import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Dict, List, Optional, Tuple

import requests
import yaml


HEADERS = {"User-Agent": "Mozilla/5.0"}
STATE_PATH = "state.json"


# ---------------------------
# Models
# ---------------------------

@dataclass
class PageSpec:
    url: str
    price_regex: str


@dataclass
class Candidate:
    name: str
    a: PageSpec
    b: PageSpec
    # optional: ignore if either page fails to parse
    fail_closed: bool = True


@dataclass
class Thresholds:
    tier2_min_abs: float
    tier2_min_roi: float
    tier2_min_signals: int
    tier1_min_abs: float
    tier1_min_roi: float
    tier1_min_signals: int


# ---------------------------
# Config / State
# ---------------------------

def load_config(path: str = "config.yaml") -> Tuple[List[Candidate], Thresholds, List[str], Dict]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    th = cfg.get("thresholds", {}) or {}
    thresholds = Thresholds(
        tier2_min_abs=float(th.get("tier2_min_abs", 20.0)),
        tier2_min_roi=float(th.get("tier2_min_roi", 0.20)),
        tier2_min_signals=int(th.get("tier2_min_signals", 3)),
        tier1_min_abs=float(th.get("tier1_min_abs", 10.0)),
        tier1_min_roi=float(th.get("tier1_min_roi", 0.10)),
        tier1_min_signals=int(th.get("tier1_min_signals", 2)),
    )

    signals = cfg.get("belief_signals", []) or []
    if not isinstance(signals, list):
        raise ValueError("config.yaml: belief_signals must be a list of regex strings")

    raw_candidates = cfg.get("candidates", []) or []
    if not raw_candidates:
        raise ValueError("config.yaml: candidates list is empty")

    candidates: List[Candidate] = []
    for rc in raw_candidates:
        name = str(rc["name"])
        a = rc["a"]
        b = rc["b"]
        candidates.append(
            Candidate(
                name=name,
                a=PageSpec(url=str(a["url"]), price_regex=str(a["price_regex"])),
                b=PageSpec(url=str(b["url"]), price_regex=str(b["price_regex"])),
                fail_closed=bool(rc.get("fail_closed", True)),
            )
        )

    misc = cfg.get("misc", {}) or {}
    return candidates, thresholds, signals, misc


def load_state() -> Dict:
    if not os.path.exists(STATE_PATH):
        return {"seen": {}}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # fail safe: don't crash; start fresh
        return {"seen": {}}


def save_state(state: Dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


# ---------------------------
# Fetch / Parse
# ---------------------------

def fetch_html(url: str, timeout: int = 25) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def extract_price(html: str, price_regex: str) -> float:
    m = re.search(price_regex, html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        raise RuntimeError("price_regex did not match")
    return float(m.group(1))


def count_belief_signals(html_a: str, html_b: str, signal_regexes: List[str], max_chars: int = 200_000) -> Tuple[int, List[str]]:
    # Combine and truncate to keep regex work bounded
    blob = (html_a + "\n" + html_b)[:max_chars]
    hits: List[str] = []
    for rx in signal_regexes:
        if re.search(rx, blob, flags=re.IGNORECASE | re.DOTALL):
            hits.append(rx)
    return len(hits), hits


# ---------------------------
# Tier logic (discrete)
# ---------------------------

def compute_tier(abs_profit: float, roi: float, signal_count: int, th: Thresholds) -> int:
    # Tier-2: only if BOTH numeric mismatch AND belief signals are strong
    if abs_profit >= th.tier2_min_abs and roi >= th.tier2_min_roi and signal_count >= th.tier2_min_signals:
        return 2
    # Tier-1: weaker mismatch, log only (no email)
    if abs_profit >= th.tier1_min_abs and roi >= th.tier1_min_roi and signal_count >= th.tier1_min_signals:
        return 1
    return 0


# ---------------------------
# Email
# ---------------------------

def send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587").strip())
    user = os.getenv("SMTP_USER", "").strip()
    pw = os.getenv("SMTP_PASS", "").strip()
