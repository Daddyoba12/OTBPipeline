"""
regen_slots.py — Slot regeneration tool  (run locally, not via Telegram)

Shows today's posted slots, lets you pick which ones to regenerate.
For each selected slot:
  1. Attempts to delete old posts from YouTube + LinkedIn via API
  2. Shows TikTok / Instagram IDs so you can delete manually (no API support)
  3. Clears the "ran today" flag so the pipeline treats it as fresh
  4. Launches pipeline.py --slot N --force  (sequential, one at a time)

Usage:
  python regen_slots.py              # interactive slot picker
  python regen_slots.py --all        # regenerate all 4 slots without prompting
  python regen_slots.py 2 3          # regenerate slots 2 and 3 without prompting
"""

import argparse, json, subprocess, sys, time
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from config import DATA, OUTPUT, YOUTUBE_TOKEN, YOUTUBE_CREDS, CREDS_PATH

POST_LOG  = DATA / "post_log.json"
RAN_TODAY = DATA / "pipeline_ran_today.json"
REGEN_LOG = DATA / "regen_log.json"
PYTHON    = sys.executable

_PLATFORM_LABELS = {
    "tiktok":          "TikTok",
    "instagram":       "Instagram Reel",
    "instagram_story": "Instagram Story",
    "youtube":         "YouTube Shorts",
    "linkedin":        "LinkedIn",
    "newspaper":       "Newspaper",
    "blog":            "Blog",
}

_SLOT_LABELS = {
    1: "Slot 1 — 7am  (Story / Blog / LinkedIn)",
    2: "Slot 2 — 9am  (TikTok V1+V2 / Instagram V1+V2)",
    3: "Slot 3 — 6pm  (TikTok V1+V2 / Instagram V1+V2)",
    4: "Slot 4 — 9pm  (TikTok / YouTube)",
}


# ── Post log helpers ──────────────────────────────────────────────────────────

def _load_post_log() -> list[dict]:
    try:
        return json.loads(POST_LOG.read_text(encoding="utf-8")) if POST_LOG.exists() else []
    except Exception:
        return []


def _today_posts_by_slot(log: list[dict]) -> dict[int, list[dict]]:
    today = date.today().isoformat()
    result: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for entry in log:
        if entry.get("posted_at", "").startswith(today):
            slot = entry.get("slot", 0)
            if slot in result:
                result[slot].append(entry)
    return result


# ── Platform deletion ─────────────────────────────────────────────────────────

def _delete_youtube(video_id: str) -> bool:
    """Delete a YouTube video by ID using the Data API v3."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        import requests as req

        creds = Credentials.from_authorized_user_file(
            str(YOUTUBE_TOKEN),
            scopes=["https://www.googleapis.com/auth/youtube"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            YOUTUBE_TOKEN.write_text(creds.to_json())

        r = req.delete(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"id": video_id},
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=20,
        )
        if r.status_code == 204:
            return True
        print(f"    YouTube delete failed ({r.status_code}): {r.text[:120]}")
    except Exception as e:
        print(f"    YouTube delete error: {e}")
    return False


def _delete_linkedin(urn: str) -> bool:
    """Delete a LinkedIn UGC post by URN."""
    try:
        import requests as req
        creds = json.loads(Path(CREDS_PATH).read_text())
        token = creds.get("linkedin", {}).get("access_token", "")
        if not token:
            print("    LinkedIn: no access token in credentials")
            return False

        encoded = urn.replace(":", "%3A")
        r = req.delete(
            f"https://api.linkedin.com/v2/ugcPosts/{encoded}",
            headers={"Authorization": f"Bearer {token}",
                     "X-Restli-Protocol-Version": "2.0.0"},
            timeout=20,
        )
        if r.status_code in (200, 204):
            return True
        print(f"    LinkedIn delete failed ({r.status_code}): {r.text[:120]}")
    except Exception as e:
        print(f"    LinkedIn delete error: {e}")
    return False


def _attempt_deletions(posts: list[dict]) -> list[dict]:
    """
    Try to delete each post via API where supported.
    Returns list of posts that could NOT be deleted automatically
    (TikTok, Instagram) so the user knows to remove them manually.
    """
    manual = []
    for p in posts:
        platform = p.get("platform", "")
        posted   = p.get("posted_at", "")[:16]

        if platform == "youtube":
            vid_id = p.get("video_id", "")
            if vid_id:
                ok = _delete_youtube(vid_id)
                status = "deleted" if ok else "delete FAILED — remove manually"
                print(f"    YouTube  {vid_id}  {posted}  → {status}")
            else:
                print(f"    YouTube  (no video_id in log — skip)")

        elif platform == "linkedin":
            urn = p.get("urn", p.get("media_id", ""))
            if urn:
                ok = _delete_linkedin(urn)
                status = "deleted" if ok else "delete FAILED — remove manually"
                print(f"    LinkedIn  {urn[:50]}  {posted}  → {status}")
            else:
                print(f"    LinkedIn  (no URN in log — skip)")

        elif platform in ("tiktok",):
            pub_id = p.get("publish_id", "")
            print(f"    TikTok  publish_id={pub_id}  {posted}  → manual delete needed")
            print(f"      ↳ Open TikTok app → Profile → tap video → Delete")
            manual.append(p)

        elif platform in ("instagram", "instagram_story"):
            media_id = p.get("media_id", "")
            print(f"    Instagram  media_id={media_id}  {posted}  → manual delete needed")
            print(f"      ↳ Open Instagram app → Profile → tap reel → ··· → Delete")
            manual.append(p)

        elif platform in ("newspaper", "blog"):
            print(f"    {platform.title()}  {posted}  → no delete needed (static content)")

    return manual


# ── Ran-today flag ────────────────────────────────────────────────────────────

def _clear_ran_today(slots: list[int]):
    try:
        ran = json.loads(RAN_TODAY.read_text()) if RAN_TODAY.exists() else {}
        today = str(date.today())
        existing = ran.get(today, [])
        if isinstance(existing, int):
            existing = [existing]
        ran[today] = [s for s in existing if s not in slots]
        RAN_TODAY.write_text(json.dumps(ran, indent=2))
        print(f"  Cleared ran-today flag for slots: {slots}")
    except Exception as e:
        print(f"  Warning: could not clear ran-today flag: {e}")


# ── Regen log ─────────────────────────────────────────────────────────────────

def _log_regen(slot: int, status: str):
    try:
        log = json.loads(REGEN_LOG.read_text()) if REGEN_LOG.exists() else []
        log.append({"slot": slot, "date": date.today().isoformat(),
                    "ts": datetime.now().isoformat(), "status": status})
        REGEN_LOG.write_text(json.dumps(log[-200:], indent=2))
    except Exception:
        pass


# ── Pipeline launcher ─────────────────────────────────────────────────────────

def _run_slot(slot: int) -> bool:
    """Launch pipeline.py --slot N --force and stream output. Blocking."""
    print(f"\n{'='*60}")
    print(f"  Launching Slot {slot} pipeline...")
    print(f"{'='*60}\n")
    try:
        proc = subprocess.Popen(
            [PYTHON, str(BASE / "pipeline.py"), "--slot", str(slot), "--force"],
            cwd=str(BASE),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            print(line, end="", flush=True)
        proc.wait()
        ok = proc.returncode == 0
        _log_regen(slot, "success" if ok else f"failed (rc={proc.returncode})")
        return ok
    except Exception as e:
        print(f"  Pipeline launch error: {e}")
        _log_regen(slot, f"error: {e}")
        return False


# ── Display ───────────────────────────────────────────────────────────────────

def _print_summary(posts_by_slot: dict[int, list[dict]]):
    today = date.today().strftime("%A %d %B %Y")
    print(f"\n{'='*60}")
    print(f"  OTB Slot Status — {today}")
    print(f"{'='*60}")
    for slot in (1, 2, 3, 4):
        posts = posts_by_slot.get(slot, [])
        label = _SLOT_LABELS[slot]
        if posts:
            platforms = []
            for p in posts:
                pl = _PLATFORM_LABELS.get(p.get("platform", ""), p.get("platform", ""))
                t  = p.get("posted_at", "")[11:16]
                platforms.append(f"{pl} @ {t}")
            print(f"  [{slot}] {label}")
            for pl in platforms:
                print(f"        ✓ {pl}")
        else:
            print(f"  [{slot}] {label}")
            print(f"        — not posted today")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Delete and regenerate OTB pipeline slots",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python regen_slots.py          # interactive picker\n"
               "  python regen_slots.py --all    # regenerate all 4 slots\n"
               "  python regen_slots.py 2 3      # regenerate slots 2 and 3",
    )
    parser.add_argument("slots", nargs="*", type=int, choices=[1, 2, 3, 4],
                        help="Slot numbers to regenerate (1-4)")
    parser.add_argument("--all",   action="store_true", help="Regenerate all 4 slots")
    parser.add_argument("--no-delete", action="store_true",
                        help="Skip platform deletion, just rerun the pipeline")
    args = parser.parse_args()

    log = _load_post_log()
    posts_by_slot = _today_posts_by_slot(log)

    _print_summary(posts_by_slot)

    # Determine which slots to regen
    if args.all:
        selected = [1, 2, 3, 4]
    elif args.slots:
        selected = sorted(set(args.slots))
    else:
        # Interactive picker
        print("  Which slots do you want to regenerate?")
        print("  Enter slot numbers separated by spaces  (e.g. 1 2),")
        print("  'all' for all four, or 'q' to quit.\n")
        raw = input("  → ").strip().lower()
        if raw in ("q", "quit", ""):
            print("  Cancelled.")
            return
        if raw == "all":
            selected = [1, 2, 3, 4]
        else:
            try:
                selected = sorted({int(x) for x in raw.split() if x.isdigit() and int(x) in (1, 2, 3, 4)})
            except Exception:
                print("  Invalid input — cancelled.")
                return
        if not selected:
            print("  No valid slots selected — cancelled.")
            return

    print(f"\n  Selected for regeneration: Slots {selected}")

    # Confirm
    answer = input("\n  Proceed? Old posts will be deleted where possible.  [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("  Cancelled.")
        return

    # Process each slot sequentially
    for slot in selected:
        posts = posts_by_slot.get(slot, [])
        print(f"\n{'─'*60}")
        print(f"  SLOT {slot} — {_SLOT_LABELS[slot]}")
        print(f"{'─'*60}")

        if not args.no_delete:
            if posts:
                print(f"  Deleting {len(posts)} post(s) from platforms:")
                manual = _attempt_deletions(posts)
                if manual:
                    print(f"\n  ⚠  {len(manual)} post(s) need manual deletion (see above).")
                    answer2 = input("  Continue regenerating anyway? [y/N] ").strip().lower()
                    if answer2 not in ("y", "yes"):
                        print(f"  Slot {slot} skipped.")
                        continue
            else:
                print("  No posts to delete for this slot today.")
        else:
            print("  --no-delete: skipping platform deletion.")

        # Clear ran-today so pipeline runs fresh
        _clear_ran_today([slot])

        # Run pipeline (blocking — waits for completion before next slot)
        ok = _run_slot(slot)
        status = "✓ Slot regenerated" if ok else "✗ Pipeline exited with error"
        print(f"\n  {status}")

        # Brief pause between slots to avoid platform rate limits
        if slot != selected[-1]:
            print(f"\n  Waiting 60 seconds before next slot...")
            time.sleep(60)

    print(f"\n{'='*60}")
    print(f"  Done. Regenerated {len(selected)} slot(s).")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
