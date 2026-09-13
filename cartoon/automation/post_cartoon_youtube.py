"""
BOUNCE ON THE MOVE — YouTube poster

Two modes:
  --scheduled   Pop the oldest unposted episode from the queue and upload to YouTube.
                Called by Task Scheduler on Tue/Thu/Sat at 09:00.

  --listen N    Poll Telegram for up to N seconds for a "Post Now" button press,
                then upload that episode immediately.
                Called after batch production so user can post straight away.

  --post EP     Directly post episode number EP to YouTube (no Telegram polling).
"""

import argparse, json, sys, time
from datetime import datetime
from pathlib import Path

CARTOON  = Path(__file__).parent.parent
BASE     = CARTOON.parent
STATE    = CARTOON / "state"
EPISODES = CARTOON / "episodes"

sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from post_youtube import post_video as _yt_post

YT_QUEUE = STATE / "youtube_queue.json"


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _load_queue() -> list:
    if YT_QUEUE.exists():
        try:
            return json.loads(YT_QUEUE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_queue(queue: list):
    YT_QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")


def _tg_notify(text: str):
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
    except Exception:
        pass


def _post_episode(entry: dict) -> bool:
    """Upload one queue entry to YouTube. Returns True on success."""
    ep_num     = entry["ep_num"]
    video_path = Path(entry["video_path"])
    if not video_path.exists():
        _log(f"  Video not found: {video_path}")
        return False

    special_label = " 🎉 SPECIAL" if entry.get("special_type") else ""
    yt_content = {
        "hook":    entry.get("caption", entry["title"]),
        "lesson":  entry.get("story", ""),
        "youtube_title": f"BOUNCE ON THE MOVE — Ep{ep_num}{special_label}: {entry['title']} | BootHop",
        "youtube_description": (
            f"{entry.get('caption', '')}\n\n"
            f"{entry.get('story', '')}\n\n"
            f"BootHop.com — same-day delivery by trusted travellers.\n\n"
            f"{entry.get('hashtags', '#BootHop #Cartoon #DiasporaLife')}\n"
            "#Shorts #Animation #BounceOnTheMove"
        ),
    }
    _log(f"  Uploading Ep{ep_num}: {entry['title']}...")
    yt_id = _yt_post(str(video_path), yt_content, slot=ep_num)
    if yt_id:
        _log(f"  YouTube OK: https://youtu.be/{yt_id}")
        _tg_notify(
            f"✅ *BOUNCE ON THE MOVE — Ep{ep_num}* is live on YouTube!\n"
            f"https://youtu.be/{yt_id}"
        )
        return True
    _log("  YouTube upload failed")
    return False


def post_scheduled():
    """Post the oldest unposted episode in the queue."""
    queue = _load_queue()
    pending = [e for e in queue if not e.get("posted")]
    if not pending:
        _log("No episodes queued for YouTube.")
        return
    entry = pending[0]
    _log(f"Scheduled post: Ep{entry['ep_num']} — {entry['title']}")
    ok = _post_episode(entry)
    if ok:
        for e in queue:
            if e["ep_num"] == entry["ep_num"]:
                e["posted"]    = True
                e["posted_at"] = datetime.now().isoformat()
        _save_queue(queue)


def post_direct(ep_num: int):
    """Post a specific episode to YouTube immediately."""
    queue = _load_queue()
    matches = [e for e in queue if e["ep_num"] == ep_num]
    if not matches:
        _log(f"Ep{ep_num} not in queue. Run episode_runner.py first.")
        return
    entry = matches[0]
    ok = _post_episode(entry)
    if ok:
        for e in queue:
            if e["ep_num"] == ep_num:
                e["posted"]    = True
                e["posted_at"] = datetime.now().isoformat()
        _save_queue(queue)


def listen_for_postnow(timeout_sec: int = 300):
    """
    Poll Telegram for cartoon_youtube_N callback queries.
    When a Post Now button is tapped, upload that episode immediately.
    Runs for timeout_sec seconds then exits.
    """
    import requests
    _log(f"Listening for Post Now button presses ({timeout_sec}s)...")
    offset_file = STATE / "cartoon_tg_offset.json"
    offset = 0
    if offset_file.exists():
        try:
            offset = json.loads(offset_file.read_text())["offset"]
        except Exception:
            pass

    deadline = time.time() + timeout_sec
    posted   = set()

    while time.time() < deadline:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 20,
                        "allowed_updates": ["callback_query"]},
                timeout=30,
            )
            updates = r.json().get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                cb = upd.get("callback_query", {})
                data = cb.get("data", "")
                cb_id = cb.get("id")
                if data.startswith("cartoon_youtube_"):
                    try:
                        ep_num = int(data.split("_")[-1])
                    except ValueError:
                        continue
                    if ep_num not in posted:
                        posted.add(ep_num)
                        # Acknowledge button tap
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cb_id,
                                  "text": f"Posting Ep{ep_num} to YouTube..."},
                            timeout=10,
                        )
                        post_direct(ep_num)
            offset_file.write_text(json.dumps({"offset": offset}), encoding="utf-8")
        except Exception as e:
            _log(f"  Poll error: {e}")
            time.sleep(5)

    _log("Post Now listener finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BOUNCE ON THE MOVE YouTube poster")
    parser.add_argument("--scheduled", action="store_true",
                        help="Post the next queued episode (Tue/Thu/Sat scheduler)")
    parser.add_argument("--listen", type=int, default=0, metavar="SECONDS",
                        help="Listen for Telegram PostNow button for N seconds")
    parser.add_argument("--post", type=int, default=None, metavar="EP_NUM",
                        help="Post a specific episode number immediately")
    args = parser.parse_args()

    if args.post:
        post_direct(args.post)
    elif args.scheduled:
        post_scheduled()
    elif args.listen:
        listen_for_postnow(args.listen)
    else:
        parser.print_help()
