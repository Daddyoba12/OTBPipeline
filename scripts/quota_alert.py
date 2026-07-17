"""Single-line Telegram alert when any paid API hits its limit or quota."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def alert(service: str, status_code: int = 0, detail: str = ""):
    """Send one Telegram line when a paid subscription/API limit is hit."""
    from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    import requests as _req
    hint = {
        429: "rate-limited",
        402: "payment required",
        403: "quota exceeded",
    }.get(status_code, "error")
    msg = f"⚠️ {service} {hint} (HTTP {status_code}) — check billing/quota. {detail}".strip(" .")
    try:
        _req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=8,
        )
    except Exception:
        pass
    print(f"[QuotaAlert] {msg}")
