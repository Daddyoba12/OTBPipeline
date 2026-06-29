"""
OTB_Pipeline — main slot orchestrator
Runs 4x daily via Task Scheduler: --slot 1|2|3|4

Schedule:
  Slot 1 — 07:00  TikTok + Instagram + YouTube + LinkedIn + Blog + Newspaper + IG Story
  Slot 2 — 12:00  TikTok + Instagram + LinkedIn (weekdays only)
  Slot 3 — 18:00  TikTok + Instagram + YouTube + Newspaper + IG Story
  Slot 4 — 21:00  TikTok + Instagram

Every platform has its own algorithm implementation:
  TikTok:    3h rate-limit guard, hook-first caption, 20 hashtags, no brand toggles
  Instagram: Reel + catbox.moe host, 125-char visible hook, 20 mid/micro hashtags
  YouTube:   Resumable upload, keyword-first title, #Shorts in description
  LinkedIn:  Weekday-only, UGC Posts API v2, NO link in caption, first-comment link, 3-5 hashtags
  Blog:      Claude SEO post, H2 structure, FAQ section, longtail keywords, Blogger API
  Newspaper: Pillow-rendered 1080x1350, rotating mastheads, IG feed IMAGE (content variety signal)
  IG Story:  Pillow story image with visual poll, posted immediately after Reel (double-tap boost)
"""

import argparse, json, os, sys, time
from datetime import datetime, date
from pathlib import Path

BASE = Path(r"C:\Users\babso\Desktop\OTB_Pipeline")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

# Make scripts importable without package prefix
import importlib, types
_scripts_dir = str(BASE / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# Ensure ffmpeg on PATH
for _p in [r"C:\ffmpeg\bin", r"C:\Python314", r"C:\Python314\Scripts"]:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import (
    DATA, OUTPUT, TEMP, SLOT_PLATFORMS, APPROVAL_TIMEOUT,
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
)

CRASH_LOG  = DATA / "pipeline_crash.log"
STEP_FILE  = DATA / "pipeline_step.txt"
POST_LOG   = DATA / "post_log.json"
RAN_TODAY  = DATA / "pipeline_ran_today.json"


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def _crash(msg: str):
    try:
        with open(CRASH_LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def _step(s: str):
    try:
        STEP_FILE.write_text(f"[{datetime.now().isoformat()}] {s}", encoding="utf-8")
    except Exception:
        pass


def _clear_step():
    try:
        STEP_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _already_ran_today(slot: int) -> bool:
    """Prevent double-runs of same slot on same day."""
    try:
        if RAN_TODAY.exists():
            ran = json.loads(RAN_TODAY.read_text())
            return ran.get(str(date.today())) == slot or slot in ran.get(str(date.today()), [])
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


def _tg_send(text: str) -> None:
    """Quick Telegram send without reply markup."""
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def run_slot(slot: int, force: bool = False):
    """Run a full pipeline slot: generate → render → approve → post."""
    _log(f"{'='*56}")
    _log(f"OTB_Pipeline — Slot {slot} — {date.today()}")
    _log(f"{'='*56}")

    DATA.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    TEMP.mkdir(exist_ok=True)

    if not force and _already_ran_today(slot):
        _log(f"Slot {slot} already ran today — skipping (use --force to override)")
        return

    # ── 1. Determine pillar + bucket ──────────────────────────────────────────
    _step(f"slot{slot}: pillar selection")
    from generate_content import get_pillar_for_slot, get_bucket
    pillar = get_pillar_for_slot(slot)
    bucket = get_bucket()
    _log(f"Pillar: {pillar} | Bucket: {bucket}")

    # ── 2. Generate content (with regen loop) ─────────────────────────────────
    _step(f"slot{slot}: content generation")
    from generate_content import generate_content
    from telegram_commander import send_video_preview, poll_for_decision, send_result

    content = None
    video_path = None
    regen_count = 0

    while regen_count <= 2:
        _log(f"Generating content (attempt {regen_count + 1})...")
        try:
            content = generate_content(slot, pillar, bucket)
        except Exception as e:
            _crash(f"Content gen failed: {e}")
            _tg_send(f"❌ OTB Slot {slot} — content generation failed: {e}")
            return

        _log(f"Hook: {content.get('hook','')[:80]}")
        _log(f"Lesson: {content.get('lesson','')[:80]}")

        # ── 3. Render video ────────────────────────────────────────────────────
        _step(f"slot{slot}: video render")
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_file = OUTPUT / f"otb_slot{slot}_{ts}.mp4"
        _log("Rendering base video...")

        from render_video import render_video, render_for_platforms
        ok = render_video(content, slot, str(video_file))

        if not ok or not video_file.exists():
            _crash(f"Render failed for slot {slot}")
            _tg_send(f"❌ OTB Slot {slot} — render failed")
            return

        _log(f"Base render done: {video_file.stat().st_size // 1024}KB")

        # Save sidecar so Revoice Studio can read hook/caption text
        try:
            sidecar = video_file.with_suffix(".json")
            sidecar.write_text(json.dumps({
                "hook":             content.get("hook", ""),
                "lesson":           content.get("lesson", ""),
                "pillar":           content.get("pillar", ""),
                "slot":             slot,
                "caption":          content.get("caption_tiktok", ""),
                "hashtags_311":     content.get("hashtags_311", []),
                "hashtags_tiktok":  content.get("hashtags_tiktok", ""),
                "hashtags_instagram": content.get("hashtags_instagram", ""),
                "rendered_at":      datetime.now().isoformat(),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

        # Derive platform-specific variants (Instagram warm grade, LinkedIn B2B card)
        _step(f"slot{slot}: platform variants")
        _log("Creating platform variants (IG grade, LinkedIn intro)...")
        platform_videos = render_for_platforms(content, slot, str(video_file))

        video_path = str(video_file)   # used for Telegram preview (base version)
        _log(f"Variants ready: {list(platform_videos.keys())}")

        # ── 4. Telegram approval ───────────────────────────────────────────────
        _step(f"slot{slot}: telegram approval")
        _log("Sending Telegram preview...")
        send_video_preview(video_path, content.get("caption_tiktok", ""), slot, content)

        decision = poll_for_decision(slot, APPROVAL_TIMEOUT)
        _log(f"Decision: {decision}")

        if decision == "skip":
            _log(f"Slot {slot} skipped by operator.")
            _tg_send(f"⏭ Slot {slot} skipped.")
            _clear_step()
            return

        if decision == "regen":
            regen_count += 1
            _log(f"Regenerating... (attempt {regen_count + 1})")
            video_file.unlink(missing_ok=True)
            continue

        # post or timeout — proceed to posting
        break

    if not video_path or not content:
        _tg_send(f"❌ OTB Slot {slot} — no content after {regen_count} attempts")
        return

    # ── 5. Platform posting — each platform runs its own algo-optimised poster ──
    platforms = SLOT_PLATFORMS.get(slot, ["tiktok", "instagram"])
    _log(f"Posting to: {platforms}")
    results = {}

    # Each platform receives its own video file — different colour grade, different fingerprint.
    # TikTok/YouTube: base render. Instagram: warm grade. LinkedIn: professional grade + intro card.

    # TikTok — base video, 20 hashtags, organic flags off, 3h rate-limit guard
    if "tiktok" in platforms:
        _step(f"slot{slot}: posting tiktok")
        _log("Posting to TikTok (base video)...")
        try:
            from post_tiktok import post_video as tiktok_post
            pub_id = tiktok_post(platform_videos.get("tiktok", video_path), content, slot)
            results["tiktok"] = pub_id
            _log(f"TikTok: {'OK ' + pub_id if pub_id else 'FAILED'}")
        except Exception as e:
            _crash(f"TikTok post error: {e}")
            results["tiktok"] = None

    # Instagram Reel — warm-graded video (different fingerprint from TikTok), 20 mid+micro hashtags
    if "instagram" in platforms:
        _step(f"slot{slot}: posting instagram")
        _log("Posting to Instagram Reel (warm-graded video)...")
        try:
            from post_instagram import post_video as ig_post
            media_id = ig_post(platform_videos.get("instagram", video_path), content, slot)
            results["instagram"] = media_id
            _log(f"Instagram Reel: {'OK ' + media_id if media_id else 'FAILED'}")
        except Exception as e:
            _crash(f"Instagram post error: {e}")
            results["instagram"] = None

    # YouTube Shorts — shares base video with TikTok (YouTube doesn't penalise cross-posts)
    if "youtube" in platforms:
        _step(f"slot{slot}: posting youtube")
        _log("Posting to YouTube Shorts (base video)...")
        try:
            from post_youtube import post_video as yt_post
            vid_id = yt_post(platform_videos.get("youtube", video_path), content, slot)
            results["youtube"] = vid_id
            _log(f"YouTube: {'OK https://youtube.com/shorts/' + vid_id if vid_id else 'FAILED'}")
        except Exception as e:
            _crash(f"YouTube post error: {e}")
            results["youtube"] = None

    # LinkedIn — professional graded video + B2B intro card, weekdays only, first-comment link
    if "linkedin" in platforms:
        _step(f"slot{slot}: posting linkedin")
        _log("Posting to LinkedIn (professional variant)...")
        try:
            from post_linkedin import post_video as li_post
            li_urn = li_post(platform_videos.get("linkedin", video_path), content, slot)
            results["linkedin"] = li_urn
            _log(f"LinkedIn: {'OK' if li_urn else 'SKIPPED (weekend or no creds)'}")
        except Exception as e:
            _crash(f"LinkedIn post error: {e}")
            results["linkedin"] = None

    # IG Story — uses Instagram-graded video for consistency; visual poll baked in
    if "instagram_story" in platforms:
        _step(f"slot{slot}: posting instagram story")
        _log("Posting Instagram Story...")
        try:
            from post_stories import post_story
            story_id = post_story(content, slot)
            results["instagram_story"] = story_id
            _log(f"IG Story: {'OK ' + story_id if story_id else 'FAILED'}")
        except Exception as e:
            _crash(f"IG Story error: {e}")
            results["instagram_story"] = None

    # Newspaper — Pillow-rendered 1080x1350, rotating masthead, posted as IG feed IMAGE
    if "newspaper" in platforms:
        _step(f"slot{slot}: posting newspaper")
        _log("Rendering + posting newspaper image...")
        try:
            from post_newspaper import post_newspaper
            np_id = post_newspaper(content, slot)
            results["newspaper"] = np_id
            _log(f"Newspaper: {'OK ' + np_id if np_id else 'FAILED'}")
        except Exception as e:
            _crash(f"Newspaper post error: {e}")
            results["newspaper"] = None

    # Blog — Claude SEO post, H2+FAQ, longtail keywords, Blogger API (Slot 1 daily)
    if "blog" in platforms:
        _step(f"slot{slot}: posting blog")
        _log("Generating + posting blog article...")
        try:
            from post_blog import post_blog
            ok = post_blog(content, slot)
            results["blog"] = "posted" if ok else None
            _log(f"Blog: {'OK' if ok else 'FAILED (HTML saved for retry)'}")
        except Exception as e:
            _crash(f"Blog post error: {e}")
            results["blog"] = None

    # ── 6. Log + notify ────────────────────────────────────────────────────────
    _mark_ran_today(slot)
    send_result(slot, results)

    success_count = sum(1 for v in results.values() if v)
    _log(f"Slot {slot} done — {success_count}/{len(platforms)} platforms posted")
    _crash(f"[{datetime.now().isoformat()}] Slot {slot} DONE — {results}")
    _clear_step()

    # Push data files to Oracle so commander has latest post_log / query_log
    try:
        sync_script = BASE / "deploy" / "sync_data.ps1"
        if sync_script.exists():
            import subprocess as _sp
            _sp.Popen(
                ["powershell.exe", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
                 "-File", str(sync_script), "-Direction", "push"],
                creationflags=0x00000008,  # DETACHED_PROCESS
            )
            _log("Data sync → Oracle started (background)")
    except Exception as _e:
        _log(f"Data sync warning: {_e}")

    # Clean up platform variant files (keep base video, remove derived copies)
    try:
        for plat, path in platform_videos.items():
            if path != video_path and Path(path).exists():
                Path(path).unlink()
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OTB_Pipeline slot runner")
    parser.add_argument("--slot",  type=int, required=True, choices=[1, 2, 3, 4],
                        help="Slot to run (1=7am, 2=12pm, 3=6pm, 4=9pm)")
    parser.add_argument("--force", action="store_true",
                        help="Force run even if slot already ran today")
    args = parser.parse_args()

    try:
        run_slot(args.slot, force=args.force)
    except Exception as exc:
        _crash(f"UNHANDLED: {exc}")
        _tg_send(f"💥 OTB Slot {args.slot} crashed: {exc}")
        raise
