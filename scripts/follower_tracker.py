"""
OTB_Pipeline — Follower tracker
Snapshots IG + TikTok follower counts daily and reports growth deltas to Telegram.

Schedule: run once daily (e.g. 09:30 after the morning analytics sync).
Output:   data/follower_log.json   — 90-day rolling daily snapshots
          Telegram message         — current counts + 7d/30d deltas

Why track this: the IG Graph API has no per-post follower-conversion field.
Tracking daily snapshots lets us calculate which content days grew the account
by cross-referencing with post_log.json posting times.
"""
import json, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

import requests

LOG_FILE = DATA / "follower_log.json"
_BASE_TG = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Followers] {msg}")


def _load_log() -> list:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_log(log: list):
    LOG_FILE.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


# ── IG follower count ──────────────────────────────────────────────────────────

def _ig_creds() -> tuple[str, str]:
    try:
        c = json.loads(Path(CREDS_PATH).read_text())
        ig = c.get("instagram", {})
        return ig.get("access_token", "").strip(), ig.get("ig_user_id", "").strip()
    except Exception as e:
        _log(f"IG creds error: {e}")
        return "", ""


def fetch_ig_followers() -> int | None:
    token, user_id = _ig_creds()
    if not token or not user_id:
        _log("No IG creds — skipping")
        return None
    try:
        r = requests.get(
            f"https://graph.instagram.com/v22.0/{user_id}",
            params={"fields": "followers_count", "access_token": token},
            timeout=15,
        ).json()
        count = r.get("followers_count")
        if count is not None:
            _log(f"IG followers: {count:,}")
            return int(count)
        _log(f"IG unexpected response: {r}")
    except Exception as e:
        _log(f"IG fetch error: {e}")
    return None


# ── TikTok follower count ──────────────────────────────────────────────────────

def _tiktok_token() -> str:
    try:
        creds = json.loads(Path(CREDS_PATH).read_text())
        return (creds.get("tiktok_production", {}).get("access_token")
                or creds.get("tiktok", {}).get("access_token", "")).strip()
    except Exception as e:
        _log(f"TikTok creds error: {e}")
        return ""


def fetch_tiktok_followers() -> int | None:
    token = _tiktok_token()
    if not token:
        _log("No TikTok token — skipping")
        return None
    try:
        r = requests.get(
            "https://open.tiktokapis.com/v2/user/info/",
            params={"fields": "follower_count"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        ).json()
        count = r.get("data", {}).get("user", {}).get("follower_count")
        if count is not None:
            _log(f"TikTok followers: {count:,}")
            return int(count)
        _log(f"TikTok unexpected response: {r}")
    except Exception as e:
        _log(f"TikTok fetch error: {e}")
    return None


# ── Delta helpers ──────────────────────────────────────────────────────────────

def _delta(log: list, platform: str, days: int) -> int | None:
    """Return follower change over the last N days, or None if not enough history."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    past_entries = [e for e in log if e.get("date", "") <= cutoff and e.get(platform) is not None]
    if not past_entries:
        return None
    past  = past_entries[-1][platform]
    today = next((e[platform] for e in reversed(log) if e.get(platform) is not None), None)
    if today is None:
        return None
    return today - past


def _fmt_delta(d: int | None) -> str:
    if d is None:
        return "n/a"
    return f"+{d}" if d > 0 else str(d)


# ── Telegram report ────────────────────────────────────────────────────────────

def _send_report(log: list, ig_now: int | None, tt_now: int | None):
    lines = ["📊 <b>Follower Growth Snapshot</b>", ""]

    for platform, now, label in [("ig", ig_now, "Instagram"), ("tiktok", tt_now, "TikTok")]:
        if now is None:
            lines.append(f"<b>{label}:</b> — (unavailable)")
            continue
        d7  = _delta(log, platform, 7)
        d30 = _delta(log, platform, 30)
        lines.append(
            f"<b>{label}:</b> {now:,}  "
            f"(7d: {_fmt_delta(d7)} | 30d: {_fmt_delta(d30)})"
        )

    # Cross-reference: which post days had the highest follower gain this week
    _add_best_day(log, lines)

    try:
        requests.post(
            f"{_BASE_TG}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": "\n".join(lines), "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        _log(f"Telegram report failed (non-fatal): {e}")


def _add_best_day(log: list, lines: list):
    """Append the day this week with the biggest single-day IG gain."""
    week_entries = [e for e in log[-8:] if e.get("ig") is not None]
    if len(week_entries) < 2:
        return
    best_gain = 0
    best_date = ""
    for i in range(1, len(week_entries)):
        gain = week_entries[i]["ig"] - week_entries[i - 1]["ig"]
        if gain > best_gain:
            best_gain = gain
            best_date = week_entries[i]["date"]
    if best_gain > 0:
        lines.append("")
        lines.append(f"🏆 Best IG day this week: <b>{best_date}</b> (+{best_gain} followers)")


# ── Main snapshot ──────────────────────────────────────────────────────────────

def snapshot():
    ig_count = fetch_ig_followers()
    tt_count = fetch_tiktok_followers()
    today    = datetime.utcnow().strftime("%Y-%m-%d")

    log = _load_log()

    entry = {"date": today, "timestamp": datetime.utcnow().isoformat()}
    if ig_count is not None:
        entry["ig"] = ig_count
    if tt_count is not None:
        entry["tiktok"] = tt_count

    # Update today's entry if it already exists, otherwise append
    existing = next((e for e in log if e.get("date") == today), None)
    if existing:
        existing.update(entry)
    else:
        log.append(entry)

    # Keep 90-day rolling window
    cutoff = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    log = [e for e in log if e.get("date", "") >= cutoff]
    _save_log(log)

    _send_report(log, ig_count, tt_count)


if __name__ == "__main__":
    _log("=== Follower snapshot starting ===")
    snapshot()
    _log("=== Done ===")
