"""
D818 Catering — Pipeline Orchestrator
Runs 2x daily via Task Scheduler (not yet registered — see README note at bottom):
  Slot 1 — 12:30 (lunch)    TikTok + Instagram (Zernio)
  Slot 2 — 20:00 (evening)  TikTok + Instagram (Zernio)

Times tuned to the overlap of TikTok's UK lunch (12:30-1pm) + post-dinner (8-9pm)
peaks and Instagram Reels' UK lunch-break + weekday-evening (7-9pm) peaks — see
client_profiles/d818.json's schedule._note. Kept in sync with that file's slots.

Flow per slot: generate content -> render video -> Telegram approval (same bot/chat
as BootHop, D818-labeled + namespaced) -> post to TikTok + Instagram via Zernio using
D818's own Zernio credentials (never BootHop's).

Run manually:
  python pipeline_d818.py --slot 1
  python pipeline_d818.py --slot 1 --force
  python pipeline_d818.py --slot 1 --no-post
"""

import argparse, json, sys, time
from datetime import datetime, date
from pathlib import Path

import platform as _plat_detect
BASE = (Path(r"C:\Users\babso\Desktop\OTB_Pipeline")
        if _plat_detect.system() == "Windows"
        else Path(__file__).resolve().parent)
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

import os
for _p in [r"C:\ffmpeg\bin", r"C:\Python314", r"C:\Python314\Scripts"]:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import (
    DATA, OUTPUT, TEMP, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    ZERNIO_API_KEY_D818, ZERNIO_TIKTOK_ACCOUNT_ID_D818, ZERNIO_IG_ACCOUNT_ID_D818,
)

COMPANY_SLUG   = "d818"
CLIENT_PROFILE = BASE / "client_profiles" / "d818.json"

CRASH_LOG     = DATA / "d818_pipeline_crash.log"
RAN_TODAY     = DATA / "d818_ran_today.json"
PIPELINE_LOCK = DATA / "d818_pipeline.lock"

# Acceptable run windows per slot (start_hour inclusive, end_hour exclusive) —
# mirrors BootHop's SLOT_WINDOWS guard to avoid Task Scheduler missed-run pile-up.
# Slot 1 brackets 12:30 (lunch), Slot 2 brackets 20:00 (evening).
SLOT_WINDOWS = {1: (10, 15), 2: (17, 22)}
SLOT_PLATFORMS = {1: ["tiktok", "instagram", "youtube"], 2: ["tiktok", "instagram", "youtube"]}

# How long to wait for a Telegram approval tap before auto-posting.
APPROVAL_MINUTES = {1: 30, 2: 30}


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [D818] {msg}")


def _crash(msg: str):
    try:
        with open(CRASH_LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def _tg_send(text: str) -> None:
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _already_ran_today(slot: int) -> bool:
    today = str(date.today())
    try:
        if RAN_TODAY.exists():
            ran = json.loads(RAN_TODAY.read_text())
            existing = ran.get(today, [])
            if isinstance(existing, int):
                existing = [existing]
            return slot in existing
    except Exception:
        pass
    return False


def _mark_ran_today(slot: int):
    try:
        ran = {}
        if RAN_TODAY.exists():
            ran = json.loads(RAN_TODAY.read_text())
        today_key = str(date.today())
        existing = ran.get(today_key, [])
        if isinstance(existing, int):
            existing = [existing]
        if slot not in existing:
            existing.append(slot)
        ran[today_key] = existing
        RAN_TODAY.write_text(json.dumps(ran, indent=2))
    except Exception:
        pass


def _acquire_lock(slot: int) -> bool:
    try:
        if PIPELINE_LOCK.exists():
            try:
                info    = json.loads(PIPELINE_LOCK.read_text(encoding="utf-8"))
                held_at = datetime.fromisoformat(info.get("locked_at", ""))
                age_min = (datetime.now() - held_at).total_seconds() / 60
                if age_min < 90:
                    _log(f"[Lock] Slot {info.get('slot')} locked since {held_at:%H:%M} ({age_min:.0f}m ago)")
                    return False
                _log("[Lock] Stale lock (>90m) — clearing")
            except Exception:
                pass
        PIPELINE_LOCK.write_text(
            json.dumps({"slot": slot, "locked_at": datetime.now().isoformat()}),
            encoding="utf-8",
        )
        return True
    except Exception:
        return True


def _release_lock():
    try:
        PIPELINE_LOCK.unlink(missing_ok=True)
    except Exception:
        pass


def _load_profile() -> dict:
    try:
        return json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_slot(slot: int, force: bool = False, no_post: bool = False):
    _log("=" * 56)
    _log(f"D818 Pipeline — Slot {slot} — {date.today()}")
    _log("=" * 56)

    if not force:
        now_h = datetime.now().hour
        win   = SLOT_WINDOWS.get(slot, (0, 24))
        if not (win[0] <= now_h < win[1]):
            _log(f"Slot {slot} outside window {win[0]:02d}:00-{win[1]:02d}:00 "
                 f"(current {now_h:02d}:xx) — skipping. Use --force to override.")
            return

    if not _acquire_lock(slot):
        _tg_send(f"🍽️ D818 Slot {slot} skipped — pipeline lock held.")
        return

    DATA.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    TEMP.mkdir(exist_ok=True)

    if not force and _already_ran_today(slot):
        _log(f"Slot {slot} already ran today — skipping (use --force to override)")
        _release_lock()
        return

    _mark_ran_today(slot)

    # ── 1. Pillar + content generation ─────────────────────────────────────────
    from generate_content_d818 import get_pillar_for_slot, get_bucket, generate_content
    from telegram_commander import send_video_preview_d818, poll_for_decision_d818, send_result_d818

    pillar = get_pillar_for_slot(slot)
    bucket = get_bucket()
    _log(f"Pillar: {pillar} | Bucket: {bucket}")

    content = None
    regen_count = 0
    video_path = None
    platform_videos = {}

    while regen_count <= 2:
        _log(f"Generating content (attempt {regen_count + 1})...")
        try:
            content = generate_content(slot, pillar, bucket)
        except Exception as e:
            _crash(f"D818 content gen failed: {e}")
            _tg_send(f"❌ D818 Slot {slot} — content generation failed: {e}")
            _release_lock()
            return

        _log(f"Hook: {content.get('hook','')[:80]}")

        # ── 2. Render ─────────────────────────────────────────────────────────
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_file = OUTPUT / f"d818_slot{slot}_{ts}.mp4"
        _log("Rendering...")

        from render_video import render_video, render_for_platforms
        ok, used_ids = render_video(content, slot, str(video_file), version="v1")

        if not ok or not video_file.exists():
            _crash(f"D818 render failed for slot {slot}")
            _tg_send(f"❌ D818 Slot {slot} — render failed")
            _release_lock()
            return

        _log(f"Render done: {video_file.stat().st_size // 1024}KB")

        platform_videos = render_for_platforms(content, slot, str(video_file), tiktok_ig_only=True)
        video_path = str(video_file)

        if no_post:
            _log(f"--no-post: video ready → {video_path}")
            _release_lock()
            return

        # ── 3. Telegram approval ─────────────────────────────────────────────
        _log("Sending Telegram preview...")
        send_video_preview_d818(video_path, content.get("caption_tiktok", ""), slot, content)

        timeout_secs = APPROVAL_MINUTES.get(slot, 30) * 60
        decision = poll_for_decision_d818(slot, timeout_secs)
        _log(f"Decision: {decision}")

        if decision == "skip":
            _log(f"Slot {slot} skipped by operator.")
            _release_lock()
            return

        if decision == "regen":
            regen_count += 1
            _log(f"Regenerating... (attempt {regen_count + 1})")
            video_file.unlink(missing_ok=True)
            continue

        break  # "post" or "timeout" → proceed to posting

    if not video_path or not content:
        _tg_send(f"❌ D818 Slot {slot} — no content after {regen_count} attempts")
        _release_lock()
        return

    # ── 4. Posting — TikTok + Instagram via Zernio, YouTube via its own OAuth ──
    # Each platform posts independently — missing credentials for one (e.g. no
    # YouTube token yet) never blocks the others.
    platforms = SLOT_PLATFORMS.get(slot, ["tiktok", "instagram", "youtube"])
    _log(f"Posting to: {platforms}")
    results = {}

    _zernio_ok = ZERNIO_API_KEY_D818 and ZERNIO_TIKTOK_ACCOUNT_ID_D818 and ZERNIO_IG_ACCOUNT_ID_D818
    if not _zernio_ok and ("tiktok" in platforms or "instagram" in platforms):
        _log("D818 Zernio credentials missing from keys.env — TikTok/Instagram will be skipped")

    if "tiktok" in platforms and not _zernio_ok:
        results["tiktok"] = None
    if "instagram" in platforms and not _zernio_ok:
        results["instagram"] = None

    if "tiktok" in platforms and _zernio_ok:
        _log("Posting TikTok via Zernio (D818 account)...")
        try:
            from post_tiktok_zernio import post_video as tk_post
            pub_id = tk_post(
                platform_videos.get("tiktok", video_path), content, slot,
                api_key=ZERNIO_API_KEY_D818, account_id=ZERNIO_TIKTOK_ACCOUNT_ID_D818,
                company_slug=COMPANY_SLUG,
            )
            results["tiktok"] = pub_id
            _log(f"TikTok: {'OK ' + pub_id if pub_id else 'FAILED'}")
        except Exception as e:
            _crash(f"D818 TikTok error: {e}")
            results["tiktok"] = None

    if "instagram" in platforms and _zernio_ok:
        _log("Posting Instagram via Zernio (D818 account)...")
        try:
            from post_instagram_zernio import post_video as ig_post
            media_id = ig_post(
                platform_videos.get("instagram", video_path), content, slot,
                api_key=ZERNIO_API_KEY_D818, account_id=ZERNIO_IG_ACCOUNT_ID_D818,
                company_slug=COMPANY_SLUG,
            )
            results["instagram"] = media_id
            _log(f"Instagram: {'OK ' + media_id if media_id else 'FAILED'}")
        except Exception as e:
            _crash(f"D818 Instagram error: {e}")
            results["instagram"] = None

    if "youtube" in platforms:
        _log("Posting YouTube (D818 channel)...")
        try:
            from post_youtube_d818 import post_video as yt_post
            video_id = yt_post(platform_videos.get("youtube", video_path), content, slot)
            results["youtube"] = video_id
            _log(f"YouTube: {'OK ' + video_id if video_id else 'FAILED/skipped'}")
        except Exception as e:
            _crash(f"D818 YouTube error: {e}")
            results["youtube"] = None

    # ── 5. Results + cleanup ────────────────────────────────────────────────────
    send_result_d818(slot, results, content=content)

    success_count = sum(1 for v in results.values() if v)
    _log(f"Slot {slot} done — {success_count}/{len(platforms)} platforms posted")
    _crash(f"[{datetime.now().isoformat()}] D818 Slot {slot} DONE — {results}")

    _release_lock()

    # Clean up platform variant files (video_path itself kept)
    try:
        for path in list(platform_videos.values()):
            if path != video_path and Path(path).exists():
                Path(path).unlink()
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="D818 catering pipeline slot runner")
    parser.add_argument("--slot", type=int, required=True, choices=[1, 2],
                        help="1=12:30 (lunch)  2=20:00 (evening) — TikTok + Instagram via Zernio")
    parser.add_argument("--force", action="store_true",
                        help="Force run even if slot already ran today / outside time window")
    parser.add_argument("--no-post", action="store_true",
                        help="Generate + render only — skip Telegram approval and posting")
    args = parser.parse_args()

    # Respect schedule.active flag (flippable via Telegram Pause/Resume -> D818),
    # unless --force is explicitly passed. Same pattern as BootHop's pipeline.py.
    if not args.force:
        try:
            _cp = json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
            if not _cp.get("schedule", {}).get("active", True):
                print("[pipeline_d818] schedule.active = false — paused. Use --force to override.")
                sys.exit(0)
        except Exception:
            pass

    try:
        run_slot(args.slot, force=args.force, no_post=args.no_post)
    except Exception as exc:
        _crash(f"UNHANDLED: {exc}")
        _tg_send(f"💥 D818 Slot {args.slot} crashed: {exc}")
        raise
