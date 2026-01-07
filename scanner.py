import os, re, smtplib, ssl
import requests, yaml
from email.message import EmailMessage

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ---------- helpers ----------

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text

def price(html, rx):
    m = re.search(rx, html, re.I | re.S)
    if not m:
        raise RuntimeError("price not found")
    return float(m.group(1))

def send_email(subject, body):
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg["Subject"] = subject
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as s:
        s.starttls(context=ctx)
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)

# ---------- main ----------

cfg = yaml.safe_load(open("config.yaml"))

for c in cfg["candidates"]:
    try:
        ha = fetch(c["a"]["url"])
        hb = fetch(c["b"]["url"])

        pa = price(ha, c["a"]["price_regex"])
        pb = price(hb, c["b"]["price_regex"])

        low, high = min(pa, pb), max(pa, pb)
        abs_profit = high - low
        roi = abs_profit / low if low else 0

        text = (ha + hb).lower()
        signals = sum(1 for rx in cfg["belief_signals"] if re.search(rx, text))

        # ---- Tier-2 gate only ----
        if (
            abs_profit >= cfg["tier2"]["min_abs"]
            and roi >= cfg["tier2"]["min_roi"]
            and signals >= cfg["tier2"]["min_signals"]
        ):
            send_email(
                f"[MISPRICING] {c['name']} Δ${abs_profit:.0f}",
                f"""
Candidate: {c['name']}

Low price:  {low}
High price: {high}
ROI:        {roi:.0%}
Signals:    {signals}

Manual contact required.
"""
            )

    except Exception as e:
        print(c["name"], "skipped:", e)
