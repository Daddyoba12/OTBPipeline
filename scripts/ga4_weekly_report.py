#!/usr/bin/env python3
"""
BootHop — GA4 Weekly Analytics Report
======================================
Runs every Monday 08:05 via Windows Task Scheduler (5 min after SEO report).

Pulls data from Google Analytics 4 Data API and sends a Telegram report with:
  • Sessions, users, new users (this week vs last week)
  • Top 5 landing pages
  • Top 5 countries
  • Bounce rate + avg session duration
  • Top conversion events (register, send_request, checkout_started)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP REQUIRED (one-time, ~5 minutes):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Go to: https://console.cloud.google.com/
2. Select your project (same one your Maps/Blogger API key is in)
3. Enable "Google Analytics Data API" (search for it in APIs & Services)
4. Create a Service Account:
   IAM & Admin → Service Accounts → Create
   Name: boothop-analytics-reader
   Role: None (we'll add it in GA)
5. Create and download a JSON key for that service account
6. Save the JSON as: scripts/ga4_credentials.json  (in this folder)
7. In Google Analytics:
   Admin → Property → Property Access Management
   Add the service account email (looks like: boothop-analytics-reader@your-project.iam.gserviceaccount.com)
   Role: Viewer
8. Run this script — it will start pulling live data.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = "8717698733:AAF7GI9Yw1DhdYVv_TK35fYQcwaGdk4caeA"
TELEGRAM_CHAT_ID = "8641867751"
GA4_PROPERTY_ID  = "properties/YOUR_GA4_PROPERTY_ID"  # e.g. properties/123456789
CREDS_FILE       = Path(__file__).parent / "ga4_credentials.json"
DATA_FILE        = Path(__file__).parent.parent / "data" / "ga4_log.json"

# Find your Property ID in GA4: Admin → Property Settings → Property ID


# ── Telegram ──────────────────────────────────────────────────────────────────
def tg(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


# ── GA4 Auth (Service Account JWT) ───────────────────────────────────────────
def get_access_token(creds: dict) -> str:
    import base64, hashlib, hmac, json, time, struct

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header  = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    now     = int(time.time())
    payload = b64url(json.dumps({
        "iss":   creds["client_email"],
        "scope": "https://www.googleapis.com/auth/analytics.readonly",
        "aud":   "https://oauth2.googleapis.com/token",
        "iat":   now,
        "exp":   now + 3600,
    }).encode())

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    private_key = serialization.load_pem_private_key(
        creds["private_key"].encode(), password=None
    )
    sig_input   = f"{header}.{payload}".encode()
    signature   = private_key.sign(sig_input, padding.PKCS1v15(), hashes.SHA256())
    jwt_token   = f"{header}.{payload}.{b64url(signature)}"

    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion":  jwt_token,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ── GA4 Data API ──────────────────────────────────────────────────────────────
def run_report(token: str, property_id: str, body: dict) -> dict:
    r = requests.post(
        f"https://analyticsdata.googleapis.com/v1beta/{property_id}:runReport",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def date_range(days_ago_start: int, days_ago_end: int = 0) -> dict:
    today = datetime.now()
    start = (today - timedelta(days=days_ago_start)).strftime("%Y-%m-%d")
    end   = (today - timedelta(days=days_ago_end)).strftime("%Y-%m-%d")
    return {"startDate": start, "endDate": end}


def extract_rows(result: dict) -> list[dict]:
    dims   = [h["name"] for h in result.get("dimensionHeaders", [])]
    mets   = [h["name"] for h in result.get("metricHeaders", [])]
    rows   = []
    for row in result.get("rows", []):
        entry = {}
        for i, v in enumerate(row.get("dimensionValues", [])):
            entry[dims[i]] = v["value"]
        for i, v in enumerate(row.get("metricValues", [])):
            entry[mets[i]] = v["value"]
        rows.append(entry)
    return rows


def delta_str(now_val: float, prev_val: float) -> str:
    if prev_val == 0:
        return ""
    pct = round(((now_val - prev_val) / prev_val) * 100)
    if pct > 0:  return f" ▲{pct}%"
    if pct < 0:  return f" ▼{abs(pct)}%"
    return " ─"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    date_str = datetime.now().strftime("%d %b %Y")
    print(f"[GA4] Weekly report — {date_str}")

    # ── Check credentials ──────────────────────────────────────────────────────
    if not CREDS_FILE.exists():
        msg = (
            f"<b>📊 BootHop GA4 — {date_str}</b>\n\n"
            "⚠️ <b>Setup needed</b>\n\n"
            "GA4 reporting is ready but needs a Google service account key.\n\n"
            "Steps (5 mins):\n"
            "1. console.cloud.google.com\n"
            "2. Enable: Google Analytics Data API\n"
            "3. IAM → Service Accounts → Create → download JSON key\n"
            "4. Save as: OTB_Pipeline/scripts/ga4_credentials.json\n"
            "5. In GA4: Admin → Property Access → add service account email → Viewer\n\n"
            "Once done, this will auto-report every Monday.\n"
            f"GA4 Property: <code>{GA4_PROPERTY_ID}</code>"
        )
        tg(msg)
        print("[GA4] Credentials not found — sent setup instructions to Telegram.")
        return

    # ── Auth ───────────────────────────────────────────────────────────────────
    try:
        with open(CREDS_FILE, encoding="utf-8") as f:
            creds = json.load(f)
        token = get_access_token(creds)
    except Exception as e:
        tg(f"<b>📊 GA4 Error</b>\n\nAuth failed: {e}")
        print(f"[GA4] Auth error: {e}")
        return

    # ── Fetch data ─────────────────────────────────────────────────────────────
    this_week = date_range(7)
    last_week = date_range(14, 8)

    try:
        # Overview — this week vs last week
        overview_now  = run_report(token, GA4_PROPERTY_ID, {
            "dateRanges": [this_week],
            "metrics": [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "newUsers"},
                {"name": "bounceRate"},
                {"name": "averageSessionDuration"},
            ],
        })
        overview_prev = run_report(token, GA4_PROPERTY_ID, {
            "dateRanges": [last_week],
            "metrics": [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "newUsers"},
            ],
        })

        # Top landing pages
        top_pages = run_report(token, GA4_PROPERTY_ID, {
            "dateRanges": [this_week],
            "dimensions": [{"name": "landingPage"}],
            "metrics":    [{"name": "sessions"}, {"name": "newUsers"}],
            "orderBys":   [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit":      5,
        })

        # Top countries
        top_countries = run_report(token, GA4_PROPERTY_ID, {
            "dateRanges": [this_week],
            "dimensions": [{"name": "country"}],
            "metrics":    [{"name": "sessions"}],
            "orderBys":   [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit":      5,
        })

        # Key events (conversions)
        key_events = run_report(token, GA4_PROPERTY_ID, {
            "dateRanges": [this_week],
            "dimensions": [{"name": "eventName"}],
            "metrics":    [{"name": "eventCount"}],
            "dimensionFilter": {
                "filter": {
                    "fieldName": "eventName",
                    "inListFilter": {"values": [
                        "sign_up", "begin_checkout", "purchase",
                        "send_request", "journey_matched",
                    ]},
                },
            },
            "orderBys": [{"metric": {"metricName": "eventCount"}, "desc": True}],
        })

    except Exception as e:
        tg(f"<b>📊 GA4 Error</b>\n\nAPI call failed: {e}")
        print(f"[GA4] API error: {e}")
        return

    # ── Parse results ──────────────────────────────────────────────────────────
    def first_metric(result, idx=0):
        rows = result.get("rows", [])
        if not rows:
            return 0.0
        return float(rows[0].get("metricValues", [{}])[idx].get("value", 0))

    sessions_now  = first_metric(overview_now,  0)
    users_now     = first_metric(overview_now,  1)
    new_now       = first_metric(overview_now,  2)
    bounce_now    = first_metric(overview_now,  3)
    duration_now  = first_metric(overview_now,  4)

    sessions_prev = first_metric(overview_prev, 0)
    users_prev    = first_metric(overview_prev, 1)
    new_prev      = first_metric(overview_prev, 2)

    def fmt_dur(secs: float) -> str:
        m, s = divmod(int(secs), 60)
        return f"{m}m {s:02d}s"

    # ── Build message ──────────────────────────────────────────────────────────
    lines = [f"<b>📊 BootHop GA4 — {date_str}</b>"]

    lines.append(
        f"\n<b>This week</b>\n"
        f"  Sessions: <b>{int(sessions_now):,}</b>{delta_str(sessions_now, sessions_prev)}\n"
        f"  Users: <b>{int(users_now):,}</b>{delta_str(users_now, users_prev)}\n"
        f"  New users: <b>{int(new_now):,}</b>{delta_str(new_now, new_prev)}\n"
        f"  Bounce: <b>{round(bounce_now * 100, 1)}%</b>\n"
        f"  Avg session: <b>{fmt_dur(duration_now)}</b>"
    )

    page_rows = extract_rows(top_pages)
    if page_rows:
        lines.append("\n<b>🔝 Top landing pages</b>")
        for row in page_rows:
            path  = (row.get("landingPage") or "/")[:45]
            sess  = int(row.get("sessions", 0))
            lines.append(f"  {path} — {sess:,} sessions")

    country_rows = extract_rows(top_countries)
    if country_rows:
        lines.append("\n<b>🌍 Top countries</b>")
        for row in country_rows:
            country = row.get("country", "Unknown")[:25]
            sess    = int(row.get("sessions", 0))
            lines.append(f"  {country}: {sess:,}")

    event_rows = extract_rows(key_events)
    if event_rows:
        lines.append("\n<b>🎯 Conversions this week</b>")
        for row in event_rows:
            evt   = row.get("eventName", "?")
            count = int(row.get("eventCount", 0))
            lines.append(f"  {evt}: {count:,}")

    lines.append(f"\n<i>Runs Mon 08:05 · data/ga4_log.json</i>")

    # ── Save & send ────────────────────────────────────────────────────────────
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    weeks = existing.get("weeks", [])
    weeks.append({
        "date":     date_str,
        "sessions": int(sessions_now),
        "users":    int(users_now),
        "new":      int(new_now),
        "bounce":   round(bounce_now * 100, 1),
        "duration": int(duration_now),
    })
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"weeks": weeks}, f, indent=2)

    tg("\n".join(lines))
    print("[GA4] Report sent to Telegram ✓")


if __name__ == "__main__":
    main()
