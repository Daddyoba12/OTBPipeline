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
    SLOT_PLATFORM_LABELS, PIPELINE_SLUG,
    ORACLE_IP, ORACLE_USER, ORACLE_KEY, ORACLE_COMPANIES,
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

    # ── 1. Determine pillar + bucket ──────────────────────────────────────────
    _step(f"slot{slot}: pillar selection")
    from generate_content import get_pillar_for_slot, get_bucket
    pillar = get_pillar_for_slot(slot)
    bucket = get_bucket()
    _log(f"Pillar: {pillar} | Bucket: {bucket}")

    # ── 2. Generate content (with regen loop) ─────────────────────────────────
    _step(f"slot{slot}: content generation")
    from generate_content import generate_content, generate_v2_content
    from telegram_commander import send_video_preview, poll_for_decision, send_result

    content = None
    regen_count = 0
    v1_path = v2_path = None
    platform_videos_v1 = platform_videos_v2 = {}

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

        # ── 3. Render V1 ──────────────────────────────────────────────────────
        _step(f"slot{slot}: render V1")
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        v1_file = OUTPUT / f"otb_slot{slot}_v1_{ts}.mp4"
        _log("Rendering V1 (gold palette — Pexels/Pixabay primary)...")

        from render_video import render_video, render_for_platforms
        ok_v1, v1_used_ids = render_video(content, slot, str(v1_file), version="v1")

        if not ok_v1 or not v1_file.exists():
            _crash(f"V1 render failed for slot {slot}")
            _tg_send(f"❌ OTB Slot {slot} — V1 render failed")
            return

        _log(f"V1 done: {v1_file.stat().st_size // 1024}KB  ({len(v1_used_ids)} clips)")

        # ── 4. Generate V2 content (alt hook + rotated queries) ───────────────
        _step(f"slot{slot}: generate V2 content")
        _log("Generating V2 hook + alt visual queries via Claude Haiku...")
        content = generate_v2_content(slot, pillar, bucket, content)

        # ── 5. Render V2 (cyan palette, different clips + music) ──────────────
        _step(f"slot{slot}: render V2")
        v2_file = OUTPUT / f"otb_slot{slot}_v2_{ts}.mp4"
        _log("Rendering V2 (cyan palette — alt queries, different music)...")
        ok_v2, _ = render_video(content, slot, str(v2_file), version="v2", exclude_ids=v1_used_ids)

        if not ok_v2 or not v2_file.exists():
            _log("V2 render failed — continuing with V1 only")
            v2_file = None

        if v2_file:
            _log(f"V2 done: {v2_file.stat().st_size // 1024}KB")

        # Save sidecar (V1 anchor, includes V2 hooks for reference)
        try:
            sidecar = v1_file.with_suffix(".json")
            sidecar.write_text(json.dumps({
                "hook":               content.get("hook", ""),
                "hook_v2":            content.get("hook_v2", ""),
                "lesson":             content.get("lesson", ""),
                "lesson_v2":          content.get("lesson_v2", ""),
                "pillar":             content.get("pillar", ""),
                "slot":               slot,
                "caption":            content.get("caption_tiktok", ""),
                "hashtags_311":       content.get("hashtags_311", []),
                "hashtags_tiktok":    content.get("hashtags_tiktok", ""),
                "hashtags_instagram": content.get("hashtags_instagram", ""),
                "rendered_at":        datetime.now().isoformat(),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

        # ── 6. Platform variants for V1 + V2 ──────────────────────────────────
        _step(f"slot{slot}: platform variants")
        _log("Creating platform variants (IG warm grade) for V1 + V2...")
        platform_videos_v1 = render_for_platforms(content, slot, str(v1_file))
        platform_videos_v2 = render_for_platforms(content, slot, str(v2_file), tiktok_ig_only=True) if v2_file else {}

        _log(f"V1 variants: {list(platform_videos_v1.keys())}")
        if platform_videos_v2:
            _log(f"V2 variants: {list(platform_videos_v2.keys())}")

        v1_path = str(v1_file)
        v2_path = str(v2_file) if v2_file else None

        # ── 7. Telegram preview — both V1 + V2 clearly labelled ───────────────
        _step(f"slot{slot}: telegram preview")
        _log("Sending Telegram preview (V1 + V2)...")
        send_video_preview(v1_path, content.get("caption_tiktok", ""), slot, content,
                           v2_path=v2_path)

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
            v1_file.unlink(missing_ok=True)
            if v2_file:
                v2_file.unlink(missing_ok=True)
            continue

        break

    if not v1_path or not content:
        _tg_send(f"❌ OTB Slot {slot} — no content after {regen_count} attempts")
        return

    # ── 8. Platform posting — V1 + V2 on each platform ────────────────────────
    platforms = SLOT_PLATFORMS.get(slot, ["tiktok", "instagram"])
    _log(f"Posting to: {platforms}")
    results = {}

    # content_v2: swap in V2 hook/lesson so captions reflect the right video
    content_v2 = {**content,
                  "hook":   content.get("hook_v2",   content.get("hook", "")),
                  "lesson": content.get("lesson_v2", content.get("lesson", ""))}

    # TikTok V1
    if "tiktok" in platforms:
        _step(f"slot{slot}: posting tiktok V1")
        _log("Posting TikTok V1 (gold)...")
        try:
            from post_tiktok import post_video as tiktok_post
            pub_id = tiktok_post(platform_videos_v1.get("tiktok", v1_path), content, slot)
            results["tiktok_v1"] = pub_id
            _log(f"TikTok V1: {'OK ' + pub_id if pub_id else 'FAILED'}")
        except Exception as e:
            _crash(f"TikTok V1 error: {e}")
            results["tiktok_v1"] = None

    # TikTok V2 — 30s gap to avoid rate-limit
    if "tiktok" in platforms and v2_path:
        time.sleep(30)
        _step(f"slot{slot}: posting tiktok V2")
        _log("Posting TikTok V2 (cyan)...")
        try:
            from post_tiktok import post_video as tiktok_post
            pub_id2 = tiktok_post(platform_videos_v2.get("tiktok", v2_path), content_v2, slot)
            results["tiktok_v2"] = pub_id2
            _log(f"TikTok V2: {'OK ' + pub_id2 if pub_id2 else 'FAILED'}")
        except Exception as e:
            _crash(f"TikTok V2 error: {e}")
            results["tiktok_v2"] = None

    # Instagram V1
    if "instagram" in platforms:
        _step(f"slot{slot}: posting instagram V1")
        _log("Posting Instagram Reel V1 (warm-graded)...")
        try:
            from post_instagram import post_video as ig_post
            media_id = ig_post(platform_videos_v1.get("instagram", v1_path), content, slot)
            results["instagram_v1"] = media_id
            _log(f"Instagram V1: {'OK ' + media_id if media_id else 'FAILED'}")
        except Exception as e:
            _crash(f"Instagram V1 error: {e}")
            results["instagram_v1"] = None

    # Instagram V2
    if "instagram" in platforms and v2_path:
        _step(f"slot{slot}: posting instagram V2")
        _log("Posting Instagram Reel V2 (warm-graded)...")
        try:
            from post_instagram import post_video as ig_post
            media_id2 = ig_post(platform_videos_v2.get("instagram", v2_path), content_v2, slot)
            results["instagram_v2"] = media_id2
            _log(f"Instagram V2: {'OK ' + media_id2 if media_id2 else 'FAILED'}")
        except Exception as e:
            _crash(f"Instagram V2 error: {e}")
            results["instagram_v2"] = None

    # YouTube Shorts — V1 only (single upload per slot)
    if "youtube" in platforms:
        _step(f"slot{slot}: posting youtube")
        _log("Posting to YouTube Shorts (V1)...")
        try:
            from post_youtube import post_video as yt_post
            vid_id = yt_post(platform_videos_v1.get("youtube", v1_path), content, slot)
            results["youtube"] = vid_id
            _log(f"YouTube: {'OK https://youtube.com/shorts/' + vid_id if vid_id else 'FAILED'}")
        except Exception as e:
            _crash(f"YouTube post error: {e}")
            results["youtube"] = None

    # LinkedIn — V1 only, professional graded, weekdays only, first-comment link
    if "linkedin" in platforms:
        _step(f"slot{slot}: posting linkedin")
        _log("Posting to LinkedIn (V1 professional variant)...")
        try:
            from post_linkedin import post_video as li_post
            li_urn = li_post(platform_videos_v1.get("linkedin", v1_path), content, slot)
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

    # ── 7. Route platform videos → Revoice Studio dashboard ──────────────────
    # Must happen BEFORE cleanup so the files still exist when we copy/SCP them
    try:
        _route_to_dashboard(platform_videos_v1, slot, v1_file)
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

    # ── 9. Clean up platform variant files (copies are now in dashboard, safe to remove)
    try:
        for path in list(platform_videos_v1.values()) + list(platform_videos_v2.values()):
            if path not in (v1_path, v2_path) and Path(path).exists():
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
