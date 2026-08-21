"""
pipeline_kling.py — V2 BootHop pipeline (Kling library edition)

Called by pipeline.py when it's V2's turn for a slot.
Produces a 15-second BootHop video from the Kling clip library.

Can also be run directly:
  python pipeline_kling.py --slot 1
  python pipeline_kling.py --slot 2 --force
"""

import argparse, json, os, sys, time
from datetime import datetime, date
from pathlib import Path

import platform as _plat
BASE = (Path(r"C:\Users\babso\Desktop\OTB_Pipeline")
        if _plat.system() == "Windows"
        else Path(__file__).resolve().parent)
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

for _p in [r"C:\ffmpeg\bin", r"C:\Python314", r"C:\Python314\Scripts"]:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import (
    DATA, OUTPUT, TEMP,
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_BUFFER_MINUTES,
    SLOT_PLATFORMS, KLING_LIBRARY,
)

VERSION_STATE = DATA / "version_state.json"
KLING_LOG     = DATA / "kling_clip_log.json"


def _log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] [V2] {msg}")


def _git_pull():
    try:
        import subprocess as _sp
        r = _sp.run(
            ["git", "pull", "origin", "main", "--ff-only"],
            capture_output=True, text=True, timeout=30, cwd=str(BASE)
        )
        _log(f"[git] {r.stdout.strip() or r.stderr.strip()[:80] or 'up to date'}")
    except Exception as e:
        _log(f"[git] Pull error (continuing): {e}")


# ── version state ─────────────────────────────────────────────────────────────

def load_version_state() -> dict:
    if VERSION_STATE.exists():
        try:
            return json.loads(VERSION_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_version_state(state: dict):
    VERSION_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def mark_v2_posted(slot: int):
    state = load_version_state()
    key   = f"slot{slot}"
    state[key] = {
        "last_version":  "v2",
        "last_posted_at": datetime.now().isoformat(),
        "next_version":  "v1",
    }
    save_version_state(state)
    _log(f"Version state updated: slot {slot} → last=v2, next=v1")


# ── Telegram helpers ──────────────────────────────────────────────────────────

def _tg(method: str, **kwargs):
    import requests
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
            timeout=20, **kwargs
        )
        return r.json()
    except Exception as e:
        _log(f"Telegram {method} error: {e}")
        return {}


def _send_text(msg: str):
    _tg("sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                              "parse_mode": "Markdown"})


def _send_video(path: Path, caption: str) -> str:
    with open(path, "rb") as f:
        r = _tg("sendVideo", data={"chat_id": TELEGRAM_CHAT_ID,
                                    "caption": caption, "parse_mode": "Markdown"},
                files={"video": f})
    return r.get("result", {}).get("message_id", "")


def _is_cmdr_running() -> bool:
    pid_file = DATA / "commander.pid"
    if not pid_file.exists():
        return False
    try:
        import psutil
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _poll_approval(slot: int, timeout_sec: int) -> str:
    """
    Poll for V2 approval. Uses file-based mechanism if commander is running
    (avoids 409 Conflict with the commander polling the same Telegram bot).
    Returns 'approve' | 'reject'.
    """
    import requests
    deadline = time.time() + timeout_sec

    if _is_cmdr_running():
        # Commander owns the Telegram update queue — write a pending file and
        # wait for it to write web_approval_{slot}.json after the user taps.
        _send_text(
            f"🎬 *V2 — Slot {slot} ready.*\n"
            "Tap *Post Now* on the approval buttons above, or use /approve or /reject."
        )
        pa = DATA / f"pending_approval_{slot}.json"
        pa.write_text(
            json.dumps({"slot": slot, "since": datetime.now().isoformat(), "v2": True}),
            encoding="utf-8",
        )
        while time.time() < deadline:
            wa = DATA / f"web_approval_{slot}.json"
            if wa.exists():
                try:
                    d = json.loads(wa.read_text(encoding="utf-8"))
                    decision = d.get("decision", "")
                    wa.unlink(missing_ok=True)
                    pa.unlink(missing_ok=True)
                    if decision in ("post", "skip", "approve"):
                        return "approve"
                    if decision in ("regen", "reject"):
                        return "reject"
                except Exception:
                    wa.unlink(missing_ok=True)
            time.sleep(5)
        pa.unlink(missing_ok=True)
    else:
        # No commander running — poll Telegram directly.
        _send_text(
            "🎬 *V2 Kling video ready.*\n"
            "Reply *approve* to post, *reject* to discard, *skip* to post without review."
        )
        offset = None
        while time.time() < deadline:
            params = {"chat_id": TELEGRAM_CHAT_ID, "timeout": 10, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                    params=params, timeout=15
                )
                updates = r.json().get("result", [])
                for u in updates:
                    offset = u["update_id"] + 1
                    txt = u.get("message", {}).get("text", "").strip().lower()
                    if txt in ("approve", "yes", "✅", "👍"):
                        return "approve"
                    if txt in ("reject", "no", "❌", "👎"):
                        return "reject"
                    if txt in ("skip", "post", "send"):
                        return "approve"
            except Exception:
                pass
            time.sleep(3)

    _log("Approval timeout — auto-approving V2 video")
    return "approve"


# ── main pipeline ─────────────────────────────────────────────────────────────

def run_v2(slot: int, force: bool = False) -> bool:
    _log(f"=== V2 pipeline starting — slot {slot} ===")
    _git_pull()
    OUTPUT.mkdir(exist_ok=True)
    TEMP.mkdir(exist_ok=True)

    # ── Ensure library is analysed ─────────────────────────────────────────────
    _log("Checking Kling library...")
    from analyse_kling_library import analyse_library, available_clips
    analyse_library()  # only analyses new clips
    clips = available_clips(min_fit=5)
    if not clips:
        _log("No available clips after cooldown filter — cannot produce V2 video")
        _send_text(f"⚠️ V2 slot {slot}: No available Kling clips (all on 14-day cooldown). Running V1 instead.")
        return False

    _log(f"{len(clips)} clips available for selection")

    # ── Generate story content (same generate_content.py as V1) ───────────────
    _log("Generating V2 story content...")
    try:
        from generate_content import generate_content, get_pillar_for_slot, get_bucket
        pillar  = get_pillar_for_slot(slot)
        bucket  = get_bucket()
        _log(f"Pillar: {pillar} | Bucket: {bucket}")
        content = generate_content(slot, pillar, bucket)
        if not content:
            raise ValueError("generate_content returned empty")
    except Exception as e:
        _log(f"Content generation failed: {e}")
        _send_text(f"⚠️ V2 slot {slot}: Content generation failed — {e}")
        return False

    _log(f"Story ready: {content.get('hook', '')[:60]}")

    # ── Render V2 video (15s, 3 platform variants) ────────────────────────────
    _log("Rendering V2 video...")
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_base = OUTPUT / f"otb_v2_slot{slot}_{ts}"

    try:
        from render_kling_video import render_v2_video
        success, platform_paths = render_v2_video(
            story    = content,
            slot     = slot,
            out_base = out_base,
        )
    except Exception as e:
        _log(f"Render failed: {e}")
        _send_text(f"⚠️ V2 slot {slot}: Render failed — {e}")
        return False

    if not success or not platform_paths:
        _log("Render produced no output")
        _send_text(f"⚠️ V2 slot {slot}: Render produced no output")
        return False

    # Save sidecar JSON
    sidecar = out_base.with_suffix(".json")
    sidecar.write_text(
        json.dumps({**content, "slot": slot, "version": "v2",
                    "rendered_at": datetime.now().isoformat()},
                   indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # ── Telegram approval ──────────────────────────────────────────────────────
    tiktok_path = Path(platform_paths.get("tiktok", ""))
    if tiktok_path.exists():
        caption = (
            f"🎬 *V2 — Slot {slot}*\n"
            f"Hook: _{content.get('hook', '')[:60]}_\n"
            f"Clips used: {len(clips[:3])}\n\n"
            f"Reply *approve* / *reject*"
        )
        _send_video(tiktok_path, caption)

    buffer_sec = TELEGRAM_BUFFER_MINUTES.get(slot, 30) * 60
    decision   = _poll_approval(slot, buffer_sec)

    if decision == "reject":
        _log("V2 video rejected via Telegram")
        _send_text(f"❌ V2 slot {slot} rejected — discarded. V1 will run next.")
        return False

    # ── Post to platforms ─────────────────────────────────────────────────────
    platforms = [p for p in SLOT_PLATFORMS.get(slot, []) if p not in ("newspaper",)]
    # Newspaper: generated separately below from same content
    posted = {}

    for platform in platforms:
        vid_path = platform_paths.get(platform)
        if not vid_path or not Path(vid_path).exists():
            _log(f"No {platform} variant — skipping")
            continue
        _log(f"Posting to {platform}...")
        try:
            ok = _post(platform, slot, Path(vid_path), content)
            posted[platform] = ok
            _log(f"  {platform}: {'✅' if ok else '❌'}")
        except Exception as e:
            _log(f"  {platform} error: {e}")
            posted[platform] = False

    # Newspaper (slot 1 only — same as V1)
    if slot == 1 and "newspaper" in SLOT_PLATFORMS.get(1, []):
        _log("Generating newspaper image...")
        try:
            from post_newspaper import post_newspaper
            post_newspaper(content, slot)
            posted["newspaper"] = True
        except Exception as e:
            _log(f"  newspaper error: {e}")
            posted["newspaper"] = False

    # ── Update version state ───────────────────────────────────────────────────
    if any(posted.values()):
        mark_v2_posted(slot)

    result_lines = [f"{'✅' if v else '❌'} {k}" for k, v in posted.items()]
    _send_text(f"🎬 V2 slot {slot} complete:\n" + "\n".join(result_lines))
    _log(f"=== V2 slot {slot} done: {posted} ===")
    return any(posted.values())


def _post(platform: str, slot: int, video_path: Path, content: dict) -> bool:
    """Route to the correct posting script."""
    if platform == "tiktok":
        from post_tiktok_zernio import post_video
        return bool(post_video(str(video_path), content, slot))
    if platform == "instagram":
        from post_instagram import post_video
        return bool(post_video(str(video_path), content, slot))
    if platform == "youtube":
        from post_youtube import post_video
        return bool(post_video(str(video_path), content, slot))
    return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="OTB V2 Kling pipeline")
    ap.add_argument("--slot",  type=int, required=True, choices=[1, 2, 3])
    ap.add_argument("--force", action="store_true", help="Skip version check and force V2")
    args = ap.parse_args()
    success = run_v2(slot=args.slot, force=args.force)
    sys.exit(0 if success else 1)
