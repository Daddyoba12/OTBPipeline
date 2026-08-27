"""
OTB_Pipeline — Live post alert
Sends a Telegram push immediately after a post goes live,
reminding the team to reply to early comments (first-hour algorithm boost).

Research basis (2026):
- Posts with strong first-hour engagement get pushed to Explore/FYP
- "Sends per reach" is now IG's strongest signal — encourage sharing in the CTA
- Replying to every comment within the first hour creates a conversation loop the algorithm rewards
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

import requests

_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

_ICONS = {"instagram": "📸", "tiktok": "🎵", "youtube": "▶️"}


def send_live_alert(platform: str, slot: int, hook: str = "", post_id: str = ""):
    """
    Send an immediate Telegram alert after a post goes live.
    Call this right after a successful upload — every minute of delay costs reach.
    """
    icon     = _ICONS.get(platform.lower(), "📲")
    time_str = datetime.utcnow().strftime("%H:%M UTC")

    lines = [
        f"{icon} <b>{platform.upper()} POST LIVE</b> — Slot {slot}  [{time_str}]",
        "",
        "🔴 <b>REPLY TO COMMENTS NOW — first hour is everything.</b>",
        "• Reply to every comment within the hour",
        "• Ask followers to <b>send it to a friend</b> (sends = strongest signal)",
        "• Share to your Story to warm up the closest audience first",
        "",
    ]
    if hook:
        lines.append(f"📝 <i>{hook[:120]}</i>")
    if post_id:
        lines.append(f"<code>{post_id}</code>")

    try:
        requests.post(
            f"{_BASE}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       "\n".join(lines),
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[GrowthAlert] Telegram send failed (non-fatal): {e}")
