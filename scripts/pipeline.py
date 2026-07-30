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
for _p in [r"C:\ffmpeg\bin", r"C:\Python314", r"C:\Python314\Scripts",
           r"C:\Windows\System32\OpenSSH"]:
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
    SLOT_PLATFORM_LABELS, PIPELINE_SLUG,
    ORACLE_IP, ORACLE_USER, ORACLE_KEY, ORACLE_COMPANIES,
    TIKTOK_POSTER, TELEGRAM_BUFFER_MINUTES,
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


def _route_to_dashboard(platform_videos: dict, slot: int, base_video: Path) -> None:
    """Copy platform videos to Revoice Studio dashboard with proper labels.

    On Oracle (Linux): local copy to /opt/otb_pipeline/dashboard/companies/{slug}/
    On Windows (backup run): SCP to Oracle over SSH.
    """
    import platform as _plat, shutil as _sh, subprocess as _sp

    labels = SLOT_PLATFORM_LABELS.get(slot, {})
    if not labels:
        return

    on_windows = _plat.system() == "Windows"

    if on_windows:
        if not ORACLE_KEY or not Path(str(ORACLE_KEY)).exists():
            _log("Oracle SSH key not found — skipping dashboard video routing")
            return
        key    = str(ORACLE_KEY)
        oracle = f"{ORACLE_USER}@{ORACLE_IP}"
        rdir   = f"{ORACLE_COMPANIES}/{PIPELINE_SLUG}"
        try:
            _sp.run(["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
                     oracle, f"mkdir -p {rdir}"],
                    capture_output=True, timeout=30)
        except Exception as e:
            _log(f"Oracle mkdir error: {e}")
            return
        synced = []
        for plat, path in platform_videos.items():
            label = labels.get(plat)
            if not label or not Path(path).exists():
                continue
            r = _sp.run(["scp", "-i", key, "-o", "StrictHostKeyChecking=no",
                          path, f"{oracle}:{rdir}/{label}.mp4"],
                         capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                synced.append(f"{plat}→{label}.mp4")
            else:
                _log(f"SCP failed {plat}: {r.stderr[:80]}")
        sidecar = base_video.with_suffix(".json")
        if sidecar.exists():
            _sp.run(["scp", "-i", key, "-o", "StrictHostKeyChecking=no",
                      str(sidecar), f"{oracle}:{rdir}/slot_{slot}.json"],
                     capture_output=True, timeout=30)
        _log(f"Dashboard route (→Oracle): {synced}")
    else:
        co_dir = Path(f"{ORACLE_COMPANIES}/{PIPELINE_SLUG}")
        co_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for plat, path in platform_videos.items():
            label = labels.get(plat)
            if not label or not Path(path).exists():
                continue
            try:
                _sh.copy2(path, co_dir / f"{label}.mp4")
                copied.append(f"{plat}→{label}.mp4")
            except Exception as e:
                _log(f"Copy error {plat}: {e}")
        sidecar = base_video.with_suffix(".json")
        if sidecar.exists():
            try:
                _sh.copy2(str(sidecar), co_dir / f"slot_{slot}.json")
            except Exception:
                pass
        _log(f"Dashboard route (local): {copied}")


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

    # On Windows backup runs: pull Oracle's latest data first so dedup logs are current
    import platform as _plat
    if _plat.system() == "Windows" and force:
        try:
            import subprocess as _spp
            sync_script = BASE / "deploy" / "sync_data.ps1"
            if sync_script.exists():
                _spp.run(
                    ["powershell.exe", "-ExecutionPolicy", "Bypass",
                     "-File", str(sync_script), "-Direction", "pull"],
                    capture_output=True, timeout=45,
                )
                _log("Pre-run data pulled from Oracle")
        except Exception:
            pass  # Oracle offline — proceed with local data

    if not force and _already_ran_today(slot):
        _log(f"Slot {slot} already ran today — skipping (use --force to override)")
        return

    # ── 0. Refresh daily music tracks (slot 1 only, once per day) ────────────
    if slot == 1:
        _step("slot1: music refresh")
        try:
            sys.path.insert(0, str(BASE / "scripts"))
            from fetch_trending_music import fetch_trending_music, _already_fresh_today
            if _already_fresh_today():
                _log("Music already fresh today — skipping refresh")
            else:
                _log("Fetching today's music tracks...")
                info = fetch_trending_music()
                _log(f"Music ready: {[t['title'][:40] for t in info.get('tracks', [])]}")
        except Exception as e:
            _log(f"Music refresh failed (pipeline will use yesterday's tracks): {e}")

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
    regen_count = 0
    skip_generate = False   # set True after an edit so we reuse existing content
    video_path = None
    platform_videos = {}

    while regen_count <= 2:
        if skip_generate:
            skip_generate = False
            _log("Re-rendering with edited content (skipping AI stages)...")
        else:
            _log(f"Generating content (attempt {regen_count + 1})...")
            try:
                content = generate_content(slot, pillar, bucket)
            except Exception as e:
                from generate_content import ContentDuplicateError
                if isinstance(e, ContentDuplicateError):
                    regen_count += 1
                    _log(f"[DupCheck] {e} — regenerating ({regen_count}/{2})")
                    if regen_count > 2:
                        _tg_send(f"⚠️ OTB Slot {slot} — 3 duplicate hooks in a row. Check memory.json or expand pillars.")
                        _clear_step()
                        return
                    continue
                _crash(f"Content gen failed: {e}")
                _tg_send(f"❌ OTB Slot {slot} — content generation failed: {e}")
                return

        _log(f"Hook: {content.get('hook','')[:80]}")
        _log(f"Lesson: {content.get('lesson','')[:80]}")

        # ── 3. Render ─────────────────────────────────────────────────────────
        _step(f"slot{slot}: render")
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_file = OUTPUT / f"otb_slot{slot}_{ts}.mp4"
        _log("Rendering (gold palette — Pexels/Pixabay primary)...")

        from render_video import render_video, render_for_platforms
        ok, used_ids = render_video(content, slot, str(video_file), version="v1")

        if not ok or not video_file.exists():
            _crash(f"Render failed for slot {slot}")
            _tg_send(f"❌ OTB Slot {slot} — render failed")
            return

        _log(f"Render done: {video_file.stat().st_size // 1024}KB  ({len(used_ids)} clips)")

        # Save sidecar
        try:
            sidecar = video_file.with_suffix(".json")
            sidecar.write_text(json.dumps({
                "hook":               content.get("hook", ""),
                "problem":            content.get("problem", ""),
                "stakes":             content.get("stakes", ""),
                "resolution":         content.get("resolution", ""),
                "lesson":             content.get("lesson", ""),
                "pillar":             content.get("pillar", ""),
                "slot":               slot,
                "caption_tiktok":     content.get("caption_tiktok", ""),
                "caption_instagram":  content.get("caption_instagram", ""),
                "hashtags_tiktok":    content.get("hashtags_tiktok", ""),
                "hashtags_instagram": content.get("hashtags_instagram", ""),
                "rendered_at":        datetime.now().isoformat(),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

        # ── Push slot state to Supabase ───────────────────────────────────────
        try:
            from push_pipeline_state import push_slot_state
            content["rendered_at"] = datetime.now().isoformat()
            push_slot_state(slot, content, v1_path=str(video_file), v2_path="")
            _log("Slot state synced to Supabase")
        except Exception as _pe:
            _log(f"Supabase push skipped: {_pe}")

        # ── Platform variants (IG warm grade, YouTube base) ───────────────────
        _step(f"slot{slot}: platform variants")
        _log("Creating platform variants (IG warm grade)...")
        platform_videos = render_for_platforms(content, slot, str(video_file), tiktok_ig_only=True)
        _log(f"Variants: {list(platform_videos.keys())}")

        # ── Voice-over ────────────────────────────────────────────────────────
        _step(f"slot{slot}: voiceover")
        try:
            from voiceover import add_voiceover_to_video
            _log("Generating voice-over narration (OpenAI TTS)...")
            voiced = add_voiceover_to_video(content, str(video_file), mix_into_video=True)
            if voiced:
                _log(f"Voice-over ready: {voiced}")
                content["voiced_video"] = voiced
            else:
                _log("Voice-over generation skipped (no key or API error)")
        except Exception as _ve:
            _log(f"Voice-over failed: {_ve} — continuing without narration")

        video_path = str(video_file)

        # ── Telegram preview ──────────────────────────────────────────────────
        _step(f"slot{slot}: telegram preview")
        _log("Sending Telegram preview...")
        send_video_preview(video_path, content.get("caption_tiktok", ""), slot, content)

        timeout_secs = TELEGRAM_BUFFER_MINUTES.get(slot, 30) * 60
        decision = poll_for_decision(slot, timeout_secs)
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

        if decision == "edit":
            edit_path = DATA / f"pending_edit_{slot}.json"
            try:
                edit_data = json.loads(edit_path.read_text(encoding="utf-8"))
                for field in ("hook", "problem", "stakes", "resolution", "lesson",
                              "caption_tiktok", "caption_instagram"):
                    if field in edit_data and edit_data[field].strip():
                        content[field] = edit_data[field].strip()
                edit_path.unlink(missing_ok=True)
                _log(f"Edits applied: {[f for f in edit_data if f in content]}")
            except Exception as e:
                _log(f"Edit file load failed ({e}) — treating as regen")
                regen_count += 1
            skip_generate = True
            video_file.unlink(missing_ok=True)
            continue

        break

    if not video_path or not content:
        _tg_send(f"❌ OTB Slot {slot} — no content after {regen_count} attempts")
        return

    # ── 8. Platform posting — V1 + V2 on each platform ────────────────────────
    platforms = SLOT_PLATFORMS.get(slot, ["tiktok", "instagram"])
    _log(f"Posting to: {platforms}")
    results = {}

    # TikTok
    if "tiktok" in platforms:
        _step(f"slot{slot}: posting tiktok")
        _tiktok_mod = "post_tiktok_zernio" if TIKTOK_POSTER == "zernio" else "post_tiktok"
        _log(f"Posting TikTok via {_tiktok_mod}...")
        try:
            import importlib
            _tk = importlib.import_module(_tiktok_mod)
            pub_id = _tk.post_video(platform_videos.get("tiktok", video_path), content, slot)
            results["tiktok"] = pub_id
            _log(f"TikTok: {'OK ' + pub_id if pub_id else 'FAILED'}")
        except Exception as e:
            _crash(f"TikTok error: {e}")
            results["tiktok"] = None

    # Instagram Reel (warm-graded)
    if "instagram" in platforms:
        _step(f"slot{slot}: posting instagram")
        _log("Posting Instagram Reel (warm-graded)...")
        try:
            from post_instagram import post_video as ig_post
            media_id = ig_post(platform_videos.get("instagram", video_path), content, slot)
            results["instagram"] = media_id
            _log(f"Instagram: {'OK ' + media_id if media_id else 'FAILED'}")
        except Exception as e:
            _crash(f"Instagram error: {e}")
            results["instagram"] = None

    # YouTube Shorts
    if "youtube" in platforms:
        _step(f"slot{slot}: posting youtube")
        _log("Posting to YouTube Shorts...")
        try:
            from post_youtube import post_video as yt_post
            vid_id = yt_post(platform_videos.get("youtube", video_path), content, slot)
            results["youtube"] = vid_id
            _log(f"YouTube: {'OK https://youtube.com/shorts/' + vid_id if vid_id else 'FAILED'}")
        except Exception as e:
            _crash(f"YouTube post error: {e}")
            results["youtube"] = None

    # Newspaper — Pillow-rendered 1080x1350, rotating masthead, posted as IG feed image
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

    # LinkedIn — weekdays only, professional grade, first-comment link
    if "linkedin" in platforms:
        _step(f"slot{slot}: posting linkedin")
        _log("Posting to LinkedIn...")
        try:
            from post_linkedin import post_video as li_post
            li_urn = li_post(platform_videos.get("linkedin", video_path), content, slot)
            results["linkedin"] = li_urn
            _log(f"LinkedIn: {'OK' if li_urn else 'SKIPPED (weekend or no creds)'}")
        except Exception as e:
            _crash(f"LinkedIn post error: {e}")
            results["linkedin"] = None

    # Blog
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

    # ── Log + notify ───────────────────────────────────────────────────────────
    _mark_ran_today(slot)
    send_result(slot, results, content=content)

    success_count = sum(1 for v in results.values() if v)
    _log(f"Slot {slot} done — {success_count}/{len(platforms)} platforms posted")
    _crash(f"[{datetime.now().isoformat()}] Slot {slot} DONE — {results}")
    _clear_step()

    # ── Route platform videos → Revoice Studio dashboard ──────────────────────
    try:
        _route_to_dashboard(platform_videos, slot, video_file)
    except Exception as _re:
        _log(f"Dashboard routing error: {_re}")

    # ── 8. Push data files to Oracle (laptop-side push, or no-op on Oracle) ──
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

    # ── Clean up platform variant files (copies now in dashboard, safe to remove)
    try:
        for path in list(platform_videos.values()):
            if path != video_path and Path(path).exists():
                Path(path).unlink()
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OTB_Pipeline slot runner")
    parser.add_argument("--slot",  type=int, required=True, choices=[1, 2, 3, 4],
                        help="1=09:00 TikTok/IG/YT  2=15:00 TikTok/IG/YT  3=22:00 TikTok/IG/YT  4=LinkedIn/Blog (Tue/Fri)")
    parser.add_argument("--force", action="store_true",
                        help="Force run even if slot already ran today")
    args = parser.parse_args()

    try:
        run_slot(args.slot, force=args.force)
    except Exception as exc:
        _crash(f"UNHANDLED: {exc}")
        _tg_send(f"💥 OTB Slot {args.slot} crashed: {exc}")
        raise
