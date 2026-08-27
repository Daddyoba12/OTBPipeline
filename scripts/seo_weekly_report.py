#!/usr/bin/env python3
"""
BootHop — Weekly SEO & Site Health Report
==========================================
Runs every Monday 08:00 via Windows Task Scheduler.

  1. PageSpeed Insights (mobile) for 5 key pages — scores + Core Web Vitals
  2. Sitemap URL health check (core pages + sample of city-pair routes)
  3. Pings Google to re-crawl sitemap
  4. Week-over-week delta tracking (data/seo_log.json)
  5. Sends full report to Telegram
"""

import json
import random
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = "8717698733:AAF7GI9Yw1DhdYVv_TK35fYQcwaGdk4caeA"
TELEGRAM_CHAT_ID = "8641867751"
GOOGLE_API_KEY   = "AIzaSyAWCIeNnw0mFe7clEhC7U6m08-wtQitAWM"
SITE_URL         = "https://www.boothop.com"
SITEMAP_URL      = f"{SITE_URL}/sitemap.xml"
DATA_FILE        = Path(__file__).parent.parent / "data" / "seo_log.json"

KEY_PAGES = [
    ("Home",     SITE_URL),
    ("Journeys", f"{SITE_URL}/journeys"),
    ("Send",     f"{SITE_URL}/send"),
    ("Business", f"{SITE_URL}/business"),
    ("Blog",     f"{SITE_URL}/blog"),
]

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

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


def score_bar(s: int) -> str:
    if s >= 90:
        return "🟢"
    if s >= 50:
        return "🟡"
    return "🔴"


def delta_str(now: int, prev) -> str:
    if prev is None:
        return ""
    d = now - prev
    if d > 0:
        return f" ▲{d}"
    if d < 0:
        return f" ▼{abs(d)}"
    return " ─"


# ── PageSpeed Insights ────────────────────────────────────────────────────────
def run_psi(url: str, strategy: str = "mobile") -> dict:
    try:
        r = requests.get(
            PSI_URL,
            params={
                "url":      url,
                "strategy": strategy,
                "key":      GOOGLE_API_KEY,
                "category": ["performance", "seo", "accessibility", "best-practices"],
            },
            timeout=90,
        )
        d      = r.json()
        cats   = d.get("lighthouseResult", {}).get("categories", {})
        audits = d.get("lighthouseResult", {}).get("audits", {})

        def get_score(k):
            return round((cats.get(k, {}).get("score") or 0) * 100)

        def get_val(k):
            return audits.get(k, {}).get("displayValue", "—")

        return {
            "perf": get_score("performance"),
            "seo":  get_score("seo"),
            "a11y": get_score("accessibility"),
            "bp":   get_score("best-practices"),
            "lcp":  get_val("largest-contentful-paint"),
            "fcp":  get_val("first-contentful-paint"),
            "cls":  get_val("cumulative-layout-shift"),
            "tbt":  get_val("total-blocking-time"),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Sitemap health ────────────────────────────────────────────────────────────
CITY_MARKERS = [
    "london-to-", "lagos-to-", "manchester-to-", "birmingham-to-",
    "-to-london", "-to-lagos", "-to-manchester", "-to-birmingham",
    "accra-to-", "abuja-to-", "-to-accra", "-to-abuja",
]


def is_city_pair(url: str) -> bool:
    return any(m in url for m in CITY_MARKERS)


def check_sitemap_health() -> dict:
    try:
        r = requests.get(SITEMAP_URL, timeout=20)
        r.raise_for_status()
        ns       = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root     = ET.fromstring(r.content)
        all_urls = [loc.text for loc in root.findall(".//sm:loc", ns) if loc.text]

        core        = [u for u in all_urls if not is_city_pair(u)]
        city_urls   = [u for u in all_urls if is_city_pair(u)]
        city_sample = random.sample(city_urls, min(10, len(city_urls)))
        to_check    = core + city_sample

        ok, fail = 0, []
        for url in to_check:
            try:
                res = requests.head(url, timeout=10, allow_redirects=True)
                if res.status_code == 200:
                    ok += 1
                else:
                    fail.append(f"{res.status_code} {url.replace(SITE_URL, '')}")
            except Exception:
                fail.append(f"ERR {url.replace(SITE_URL, '')}")
            time.sleep(0.2)

        return {
            "total":   len(all_urls),
            "checked": len(to_check),
            "ok":      ok,
            "failed":  fail[:5],
        }
    except Exception as e:
        return {"error": str(e)}


# ── History (week-over-week deltas) ──────────────────────────────────────────
def load_last_week() -> dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            weeks = data.get("weeks", [])
            return weeks[-1] if weeks else {}
        except Exception:
            pass
    return {}


def save_week(entry: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    weeks = existing.get("weeks", [])
    weeks.append(entry)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"weeks": weeks}, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    date_str = datetime.now().strftime("%d %b %Y")
    print(f"[SEO] Weekly report — {date_str}")

    prev  = load_last_week()
    entry = {"date": date_str, "pages": {}}
    lines = [f"<b>🔍 BootHop SEO Report — {date_str}</b>"]

    # ── PageSpeed ─────────────────────────────────────────────────────────────
    lines.append("\n<b>📊 PageSpeed Scores (Mobile)</b>")
    all_perf, all_seo = [], []

    for label, url in KEY_PAGES:
        print(f"  PSI → {url}")
        res = run_psi(url)
        if "error" in res:
            lines.append(f"{label}: ⚠️ {res['error'][:70]}")
            continue

        prev_page = prev.get("pages", {}).get(label, {})
        entry["pages"][label] = res

        dp = delta_str(res["perf"], prev_page.get("perf"))
        ds = delta_str(res["seo"],  prev_page.get("seo"))
        all_perf.append(res["perf"])
        all_seo.append(res["seo"])

        lines.append(
            f"\n<b>{label}</b>\n"
            f"  Perf {score_bar(res['perf'])}{res['perf']}{dp}  "
            f"SEO {score_bar(res['seo'])}{res['seo']}{ds}  "
            f"A11y {score_bar(res['a11y'])}{res['a11y']}  "
            f"BP {score_bar(res['bp'])}{res['bp']}\n"
            f"  LCP {res['lcp']} · FCP {res['fcp']} · CLS {res['cls']} · TBT {res['tbt']}"
        )
        time.sleep(3)

    if all_perf:
        avg_p = round(sum(all_perf) / len(all_perf))
        avg_s = round(sum(all_seo)  / len(all_seo))
        entry["avg_perf"] = avg_p
        entry["avg_seo"]  = avg_s
        lines.append(
            f"\n<b>Avg  Perf {score_bar(avg_p)}{avg_p}"
            f"{delta_str(avg_p, prev.get('avg_perf'))}  "
            f"SEO {score_bar(avg_s)}{avg_s}"
            f"{delta_str(avg_s, prev.get('avg_seo'))}</b>"
        )

    # ── Sitemap health ────────────────────────────────────────────────────────
    print("  Checking sitemap health...")
    sm = check_sitemap_health()
    if "error" in sm:
        lines.append(f"\n<b>🗺️ Sitemap:</b> ⚠️ {sm['error'][:80]}")
    else:
        bad_str = ""
        if sm["failed"]:
            bad_str = "\n  ❌ " + "\n  ❌ ".join(sm["failed"])
        lines.append(
            f"\n<b>🗺️ Sitemap:</b> {sm['total']} URLs  "
            f"✅ {sm['ok']}/{sm['checked']} checked{bad_str}"
        )
        entry["sitemap"] = sm

    # ── Google ping ───────────────────────────────────────────────────────────
    try:
        pr     = requests.get(f"https://www.google.com/ping?sitemap={SITEMAP_URL}", timeout=10)
        pinged = pr.status_code == 200
    except Exception:
        pinged = False
    lines.append(f"\n<b>📡 Google ping:</b> {'✅ sent' if pinged else '⚠️ failed'}")
    lines.append(f"\n<i>Runs Mon 08:00 · history: data/seo_log.json</i>")

    save_week(entry)
    msg = "\n".join(lines)
    tg(msg)
    print("[SEO] Report sent to Telegram ✓")


if __name__ == "__main__":
    main()
