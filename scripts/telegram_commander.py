"""
OTB_Pipeline — Telegram commander
Handles approval flow for each slot + /status /rerun commands.
Runs continuously as a background process (OTB-Commander task).
"""

import json, os, sys, time, subprocess
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DATA, BASE

import requests

OFFSET_FILE  = DATA / "tg_offset.json"
MSG_LOG_FILE = DATA / "tg_message_log.json"
BASE_URL     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def _load_offset() -> int:
    try:
        if OFFSET_FILE.exists():
            return json.loads(OFFSET_FILE.read_text()).get("offset", 0)
    except Exception:
        pass
    return 0


def _save_offset(offset: int):
    OFFSET_FILE.parent.mkdir(exist_ok=True)
    OFFSET_FILE.write_text(json.dumps({"offset": offset}))


def _log_message(msg_id: int):
    """Record a sent message ID so clean_old_messages() can delete it after 48h."""
    try:
        log = json.loads(MSG_LOG_FILE.read_text(encoding="utf-8")) if MSG_LOG_FILE.exists() else []
        log.append({"id": msg_id, "sent_at": datetime.utcnow().isoformat()})
        log = log[-500:]   # keep last 500 entries max
        MSG_LOG_FILE.write_text(json.dumps(log, indent=2), encoding="utf-8")
    except Exception:
        pass


def clean_old_messages():
    """
    Delete bot messages older than 48 hours from the Telegram chat.
    Called from run_commander() every 48 hours automatically.
    """
    if not MSG_LOG_FILE.exists():
        return
    try:
        log      = json.loads(MSG_LOG_FILE.read_text(encoding="utf-8"))
        cutoff   = datetime.utcnow() - timedelta(hours=48)
        keep     = []
        deleted  = 0
        for entry in log:
            sent_at = datetime.fromisoformat(entry.get("sent_at", "2000-01-01"))
            if sent_at < cutoff:
                try:
                    requests.post(
                        f"{BASE_URL}/deleteMessage",
                        json={"chat_id": TELEGRAM_CHAT_ID, "message_id": entry["id"]},
                        timeout=8,
                    )
                    deleted += 1
                except Exception:
                    keep.append(entry)   # keep if delete fails
            else:
                keep.append(entry)
        MSG_LOG_FILE.write_text(json.dumps(keep, indent=2), encoding="utf-8")
        print(f"[Cmdr] Clean: deleted {deleted} messages older than 48h ({len(keep)} remaining)")
    except Exception as e:
        print(f"[Cmdr] Clean error: {e}")


def send(text: str, reply_markup: dict = None) -> dict:
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r    = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=15)
        data = r.json()
        if data.get("ok"):
            _log_message(data["result"]["message_id"])
        return data
    except Exception as e:
        print(f"[Cmdr] Send error: {e}")
        return {}


def send_video_preview(video_path: str, caption: str, slot: int, content: dict) -> int | None:
    """Send video preview to Telegram with Post Now / Skip / Regen buttons."""
    hook   = content.get("hook", "")
    pillar = content.get("pillar", "")
    text   = (f"<b>OTB Slot {slot}</b> — {pillar.upper()}\n\n"
              f"<b>Hook:</b> {hook}\n\n"
              f"<b>Stakes:</b> {content.get('stakes','')}\n\n"
              f"<b>Lesson:</b> {content.get('lesson','')}\n\n"
              f"<i>Approve or skip within 20 minutes — auto-posts if no response.</i>")
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Post Now",  "callback_data": f"post_{slot}"},
            {"text": "⏭ Skip",      "callback_data": f"skip_{slot}"},
            {"text": "🔄 Regen",     "callback_data": f"regen_{slot}"},
        ]]
    }
    try:
        with open(video_path, "rb") as vf:
            r = requests.post(
                f"{BASE_URL}/sendVideo",
                data={
                    "chat_id":     TELEGRAM_CHAT_ID,
                    "caption":     text,
                    "parse_mode":  "HTML",
                    "reply_markup": json.dumps(keyboard),
                },
                files={"video": vf},
                timeout=60,
            )
        data = r.json()
        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            _log_message(msg_id)
            print(f"[Cmdr] Preview sent, msg_id={msg_id}")
            return msg_id
    except Exception as e:
        print(f"[Cmdr] Preview send failed: {e}")
    # Fallback: send text only
    msg = send(text, keyboard)
    return msg.get("result", {}).get("message_id")


def poll_for_decision(slot: int, timeout_sec: int = 20 * 60) -> str:
    """
    Poll Telegram for a callback decision on this slot.
    Returns: "post" | "skip" | "regen" | "timeout"
    """
    start   = time.time()
    offset  = _load_offset()
    print(f"[Cmdr] Polling for slot {slot} decision ({timeout_sec//60}min window)...")

    while time.time() - start < timeout_sec:
        try:
            r = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"offset": offset, "timeout": 20, "allowed_updates": ["callback_query"]},
                timeout=30,
            )
            updates = r.json().get("result", [])
        except Exception as e:
            print(f"[Cmdr] Poll error: {e}")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            _save_offset(offset)
            cb = upd.get("callback_query", {})
            data = cb.get("data", "")
            # Answer callback (removes spinner in Telegram)
            try:
                requests.post(f"{BASE_URL}/answerCallbackQuery",
                              json={"callback_query_id": cb.get("id", "")}, timeout=5)
            except Exception:
                pass

            if data == f"post_{slot}":
                send(f"✅ Slot {slot} — posting now!")
                return "post"
            elif data == f"skip_{slot}":
                send(f"⏭ Slot {slot} — skipped.")
                return "skip"
            elif data == f"regen_{slot}":
                send(f"🔄 Slot {slot} — regenerating...")
                return "regen"

    print(f"[Cmdr] Slot {slot} timed out — auto-posting.")
    send(f"⏱ Slot {slot} — no response, auto-posting now.")
    return "timeout"


def send_result(slot: int, results: dict):
    """Send post results summary to Telegram."""
    lines = [f"<b>OTB Slot {slot} — Posted</b>"]
    for platform, result in results.items():
        icon = "✅" if result else "❌"
        lines.append(f"{icon} {platform.capitalize()}: {result or 'failed'}")
    send("\n".join(lines))


# ── Standalone commander (long-running background process) ─────────────────────
def _handle_command(text: str, chat_id: str):
    """Handle /status, /rerun, /menu commands from the standalone commander."""
    text = text.lower().strip()
    if "/status" in text:
        log_path = DATA / "post_log.json"
        try:
            log = json.loads(log_path.read_text()) if log_path.exists() else []
            today_posts = [e for e in log if e.get("posted_at", "").startswith(datetime.utcnow().strftime("%Y-%m-%d"))]
            platforms = [f"{e['platform']}:{e['slot']}" for e in today_posts]
            # Query bank stats
            try:
                import sys as _sys
                _sys.path.insert(0, str(BASE / "scripts"))
                from query_learner import bank_stats
                bank_line = "\n\n" + bank_stats()
            except Exception:
                bank_line = ""
            send(f"<b>OTB Status</b>\n\nPosts today: {len(today_posts)}\n{', '.join(platforms) or 'none yet'}{bank_line}")
        except Exception as e:
            send(f"Status error: {e}")

    elif "/menu" in text:
        send(
            "<b>OTB Pipeline</b>\n\n"
            "/status — today's post log\n"
            "/rerun 1 — rerun slot 1 (or 2/3/4)\n\n"
            "4 posts/day: 7am · 12pm · 6pm · 9pm"
        )

    elif "/rerun" in text:
        parts = text.split()
        slot  = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else 1
        if slot not in (1, 2, 3, 4):
            send("Usage: /rerun 1|2|3|4"); return
        send(f"🔄 Rerunning slot {slot}...")
        pipeline = str(BASE / "pipeline.py")
        subprocess.Popen(
            [sys.executable, pipeline, "--slot", str(slot), "--force"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def run_commander():
    """Long-running commander loop."""
    print("[Cmdr] OTB Commander started")
    offset       = _load_offset()
    last_clean   = datetime.utcnow() - timedelta(hours=49)  # run clean on first startup
    while True:
        # 48-hour Telegram cleanup
        if (datetime.utcnow() - last_clean).total_seconds() >= 48 * 3600:
            clean_old_messages()
            last_clean = datetime.utcnow()

        try:
            r = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"offset": offset, "timeout": 30,
                        "allowed_updates": ["message", "callback_query"]},
                timeout=40,
            )
            if r.status_code == 409:
                print("[Cmdr] 409 — pipeline is polling, backing off 30s")
                time.sleep(30)
                continue

            updates = r.json().get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                _save_offset(offset)
                msg = upd.get("message", {})
                text = msg.get("text", "")
                if text.startswith("/"):
                    _handle_command(text, str(msg.get("chat", {}).get("id", "")))

        except Exception as e:
            print(f"[Cmdr] Loop error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    run_commander()
