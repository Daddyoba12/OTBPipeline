"""
Generic Pipeline Orchestrator — serves any client whose profile has
"pipeline_type": "generic" (see client_profiles/<slug>.json). One file now
runs every dynamically-provisioned client; no developer hand-writes a new
pipeline_<slug>.py per client. Modeled directly on pipeline_d818.py.

v1 scope: TikTok + Instagram via Zernio only (per-client credentials read
from client_profiles/<slug>.credentials.json). YouTube/LinkedIn/Blog
explicitly out of scope — see .claude/plans/fluttering-singing-perlis.md.

Run manually:
  python pipeline_generic.py --client <slug> --slot 1
  python pipeline_generic.py --client <slug> --slot 1 --force
  python pipeline_generic.py --client <slug> --slot 1 --no-post
"""

import argparse, json, sys
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

from config import DATA, OUTPUT, TEMP, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

# Platforms supported for every generic client in v1 — Zernio only.
SLOT_PLATFORMS = ["tiktok", "instagram"]

# How long to wait for a Telegram approval tap before auto-posting.
APPROVAL_MINUTES = 30


def _profile_path(client_slug: str) -> Path:
    return BASE / "client_profiles" / f"{client_slug}.json"


def _credentials_path(client_slug: str) -> Path:
    return BASE / "client_profiles" / f"{client_slug}.credentials.json"


def _load_profile(client_slug: str) -> dict:
    try:
        return json.loads(_profile_path(client_slug).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_credentials(client_slug: str) -> dict:
    try:
        return json.loads(_credentials_path(client_slug).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _log(client_slug: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{client_slug}] {msg}")


def _crash(client_slug: str, msg: str):
    try:
        path = DATA / f"{client_slug}_pipeline_crash.log"
        with open(path, "a", encoding="utf-8", errors="replace") as f:
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


def _slot_window(profile: dict, slot: int) -> tuple:
    """Derive an acceptable run window from this slot's scheduled time —
    generalizes D818's hardcoded SLOT_WINDOWS dict. Falls back to all-day
    if the profile has no matching schedule entry (e.g. during manual
    testing before a schedule is configured)."""
    for s in (profile.get("schedule", {}).get("slots") or []):
        if s.get("pipeline_slot") == slot:
            try:
                hour = int(str(s.get("time", "")).split(":")[0])
                return (max(0, hour - 2), min(24, hour + 3))
            except Exception:
                break
    return (0, 24)


def _already_ran_today(client_slug: str, slot: int, ran_today_path: Path) -> bool:
    """Local-file dedup, mirroring D818's pattern. Cross-machine dedup via
    Supabase otb_pipeline_claims (Phase 0) is attempted in _claim_slot but
    this local check alone is enough for a single-machine (Oracle-only)
    client, which is the expected v1 deployment target."""
    today = str(date.today())
    try:
        if ran_today_path.exists():
            ran = json.loads(ran_today_path.read_text())
            existing = ran.get(today, [])
            if isinstance(existing, int):
                existing = [existing]
            if slot in existing:
                return True
    except Exception:
        pass
    return False


def _mark_ran_today(ran_today_path: Path, slot: int):
    try:
        ran = {}
        if ran_today_path.exists():
            ran = json.loads(ran_today_path.read_text())
        today_key = str(date.today())
        existing = ran.get(today_key, [])
        if isinstance(existing, int):
            existing = [existing]
        if slot not in existing:
            existing.append(slot)
        ran[today_key] = existing
        ran_today_path.write_text(json.dumps(ran, indent=2))
    except Exception:
        pass


def _claim_slot_supabase(client_slug: str, slot: int):
    """Write today's claim to the otb_pipeline_claims table (Phase 0) so any
    second machine running this same client sees it instantly. Table may not
    exist yet (created once via the Supabase SQL console per the plan) — a
    failure here is silently non-fatal, same as D818's Supabase calls."""
    today = str(date.today())
    try:
        from push_pipeline_state import SUPABASE_URL, SUPABASE_KEY, _HDR
        import requests as _req
        _req.post(
            f"{SUPABASE_URL}/rest/v1/otb_pipeline_claims",
            headers={**_HDR, "Prefer": "resolution=ignore-duplicates"},
            json={"client_slug": client_slug, "claim_date": today, "slot": slot},
            timeout=8,
        )
    except Exception:
        pass


def _acquire_lock(lock_path: Path, slot: int) -> bool:
    try:
        if lock_path.exists():
            try:
                info    = json.loads(lock_path.read_text(encoding="utf-8"))
                held_at = datetime.fromisoformat(info.get("locked_at", ""))
                age_min = (datetime.now() - held_at).total_seconds() / 60
                if age_min < 90:
                    return False
            except Exception:
                pass
        lock_path.write_text(
            json.dumps({"slot": slot, "locked_at": datetime.now().isoformat()}),
            encoding="utf-8",
        )
        return True
    except Exception:
        return True


def _release_lock(lock_path: Path):
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def run_slot(client_slug: str, slot: int, force: bool = False, no_post: bool = False):
    profile = _load_profile(client_slug)
    if not profile:
        print(f"[pipeline_generic] client_profiles/{client_slug}.json missing or unreadable — aborting")
        return
    brand = profile.get("brand_name", client_slug)

    lock_path      = DATA / f"{client_slug}_pipeline.lock"
    ran_today_path = DATA / f"{client_slug}_ran_today.json"

    _log(client_slug, "=" * 56)
    _log(client_slug, f"{brand} Pipeline — Slot {slot} — {date.today()}")
    _log(client_slug, "=" * 56)

    if not force:
        now_h = datetime.now().hour
        win   = _slot_window(profile, slot)
        if not (win[0] <= now_h < win[1]):
            _log(client_slug, f"Slot {slot} outside window {win[0]:02d}:00-{win[1]:02d}:00 "
                 f"(current {now_h:02d}:xx) — skipping. Use --force to override.")
            return

    if not _acquire_lock(lock_path, slot):
        _tg_send(f"🎬 {brand} Slot {slot} skipped — pipeline lock held.")
        return

    try:
        _run_slot_locked(client_slug, profile, slot, lock_path, ran_today_path,
                          force=force, no_post=no_post)
    finally:
        _release_lock(lock_path)


def _run_slot_locked(client_slug: str, profile: dict, slot: int,
                      lock_path: Path, ran_today_path: Path,
                      force: bool = False, no_post: bool = False):
    DATA.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    TEMP.mkdir(exist_ok=True)
    brand = profile.get("brand_name", client_slug)

    if not force and _already_ran_today(client_slug, slot, ran_today_path):
        _log(client_slug, f"Slot {slot} already ran today — skipping (use --force to override)")
        return

    _mark_ran_today(ran_today_path, slot)
    _claim_slot_supabase(client_slug, slot)

    # ── 1. Pillar + content generation ──────────────────────────────────────
    from generate_content_generic import get_pillar_for_slot, get_bucket, generate_content
    from telegram_commander import (
        send_video_preview_generic, poll_for_decision_generic, send_result_generic,
    )

    pillar = get_pillar_for_slot(slot, client_slug)
    bucket = get_bucket()
    _log(client_slug, f"Pillar: {pillar} | Bucket: {bucket}")

    content = None
    regen_count = 0
    video_path = None
    platform_videos = {}

    while regen_count <= 2:
        _log(client_slug, f"Generating content (attempt {regen_count + 1})...")
        try:
            content = generate_content(slot, pillar, bucket, client_slug=client_slug)
        except Exception as e:
            _crash(client_slug, f"Content gen failed: {e}")
            _tg_send(f"❌ {brand} Slot {slot} — content generation failed: {e}")
            return

        _log(client_slug, f"Hook: {content.get('hook','')[:80]}")

        # ── 2. Render ─────────────────────────────────────────────────────
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_file = OUTPUT / f"{client_slug}_slot{slot}_{ts}.mp4"
        _log(client_slug, "Rendering...")

        from render_video import render_video, render_for_platforms
        ok, used_ids = render_video(content, slot, str(video_file), version="v1")

        if not ok or not video_file.exists():
            _crash(client_slug, f"Render failed for slot {slot}")
            _tg_send(f"❌ {brand} Slot {slot} — render failed")
            return

        _log(client_slug, f"Render done: {video_file.stat().st_size // 1024}KB")

        platform_videos = render_for_platforms(content, slot, str(video_file), tiktok_ig_only=True)
        video_path = str(video_file)

        # Release the lock now — the slot is already claimed, so the only
        # risk left is the Telegram approval wait, which needs no exclusive
        # access (same reasoning as pipeline_d818.py).
        _release_lock(lock_path)

        if no_post:
            _log(client_slug, f"--no-post: video ready → {video_path}")
            return

        # ── 3. Telegram approval ─────────────────────────────────────────
        _log(client_slug, "Sending Telegram preview...")
        send_video_preview_generic(video_path, content.get("caption_tiktok", ""), slot,
                                    content, client_slug, brand)

        timeout_secs = APPROVAL_MINUTES * 60
        decision = poll_for_decision_generic(slot, client_slug, timeout_secs)
        _log(client_slug, f"Decision: {decision}")

        if decision == "skip":
            _log(client_slug, f"Slot {slot} skipped by operator.")
            return

        if decision == "regen":
            regen_count += 1
            _log(client_slug, f"Regenerating... (attempt {regen_count + 1})")
            video_file.unlink(missing_ok=True)
            if not _acquire_lock(lock_path, slot):
                _tg_send(f"🎬 {brand} Slot {slot} — regen blocked, lock held.")
                return
            continue

        break  # "post" or "timeout" → proceed to posting

    if not video_path or not content:
        _tg_send(f"❌ {brand} Slot {slot} — no content after {regen_count} attempts")
        return

    # ── 4. Posting — TikTok + Instagram via Zernio (v1 scope only) ─────────
    creds = _load_credentials(client_slug)
    zernio = creds.get("zernio", {})
    results = {}

    for platform_name in SLOT_PLATFORMS:
        pcreds = zernio.get(platform_name)
        if not pcreds or not pcreds.get("api_key") or not pcreds.get("account_id"):
            _log(client_slug, f"No Zernio credentials for {platform_name} — skipping")
            results[platform_name] = None
            continue

        _log(client_slug, f"Posting {platform_name} via Zernio ({brand})...")
        try:
            if platform_name == "tiktok":
                from post_tiktok_zernio import post_video as tk_post
                pub_id = tk_post(
                    platform_videos.get("tiktok", video_path), content, slot,
                    api_key=pcreds["api_key"], account_id=pcreds["account_id"],
                    company_slug=client_slug,
                )
                results["tiktok"] = pub_id
                _log(client_slug, f"TikTok: {'OK ' + pub_id if pub_id else 'FAILED'}")
            elif platform_name == "instagram":
                from post_instagram_zernio import post_video as ig_post
                media_id = ig_post(
                    platform_videos.get("instagram", video_path), content, slot,
                    api_key=pcreds["api_key"], account_id=pcreds["account_id"],
                    company_slug=client_slug,
                )
                results["instagram"] = media_id
                _log(client_slug, f"Instagram: {'OK ' + media_id if media_id else 'FAILED'}")
        except Exception as e:
            _crash(client_slug, f"{platform_name} error: {e}")
            results[platform_name] = None

    # ── 5. Results + cleanup ────────────────────────────────────────────────
    send_result_generic(slot, results, client_slug, brand, content=content)

    success_count = sum(1 for v in results.values() if v)
    _log(client_slug, f"Slot {slot} done — {success_count}/{len(SLOT_PLATFORMS)} platforms posted")
    _crash(client_slug, f"[{datetime.now().isoformat()}] Slot {slot} DONE — {results}")

    try:
        for path in list(platform_videos.values()):
            if path != video_path and Path(path).exists():
                Path(path).unlink()
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generic client pipeline slot runner")
    parser.add_argument("--client", required=True, help="client_profiles/<slug>.json slug")
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--force", action="store_true",
                        help="Force run even if slot already ran today / outside time window")
    parser.add_argument("--no-post", action="store_true",
                        help="Generate + render only — skip Telegram approval and posting")
    args = parser.parse_args()

    if not args.force:
        try:
            _cp = json.loads(_profile_path(args.client).read_text(encoding="utf-8"))
            if not _cp.get("schedule", {}).get("active", True):
                print(f"[pipeline_generic] {args.client}: schedule.active = false — paused. Use --force to override.")
                sys.exit(0)
        except Exception:
            pass

    try:
        run_slot(args.client, args.slot, force=args.force, no_post=args.no_post)
    except Exception as exc:
        _crash(args.client, f"UNHANDLED: {exc}")
        _tg_send(f"💥 {args.client} Slot {args.slot} crashed: {exc}")
        raise
