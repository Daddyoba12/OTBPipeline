"""
Daily Music Refresh — all clients, standalone.

Runs once early each morning (05:30 UK, via Task Scheduler) on the laptop —
well before any client's first slot of the day (BootHop 08:00 UK, D818 12:30 UK,
G-Inspired 09:00 America/Chicago). Fetches fresh tracks for all three, then
pushes every folder to Oracle so Oracle always has same-day music without
needing its own SoundCloud access (datacenter IPs get blocked/rate-limited
there — this is why Oracle's tracks used to go stale).

Each client's own pipeline still has a fetch-if-not-fresh fallback at its own
slot time, so nothing breaks if this job fails to run — that client just
falls back to fetching (or reusing yesterday's tracks) later, at its own risk
of missing its optimized posting window.

Run manually:
    python scripts/music_refresh_all.py
"""

import subprocess, sys, os
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from config import (
    MUSIC_DIR, D818_MUSIC_DIR, G_INSPIRED_MUSIC_DIR,
    MUSIC_ARCHIVE, D818_MUSIC_ARCHIVE, G_INSPIRED_MUSIC_ARCHIVE,
)

ORACLE_KEY = Path.home() / ".ssh" / "oracle_boothop.pem"
ORACLE     = "ubuntu@130.162.162.189"


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [MusicRefresh] {msg}")


def _fetch_all():
    from fetch_trending_music import (
        fetch_trending_music, _already_fresh_today,
        fetch_d818_music, _d818_already_fresh_today,
        fetch_gi_music,
    )

    _log("BootHop...")
    try:
        if _already_fresh_today():
            _log("  already fresh today — skip")
        else:
            fetch_trending_music()
    except Exception as e:
        _log(f"  BootHop fetch failed: {e}")

    _log("D818...")
    try:
        if _d818_already_fresh_today():
            _log("  already fresh today — skip")
        else:
            fetch_d818_music()
    except Exception as e:
        _log(f"  D818 fetch failed: {e}")

    _log("G-Inspired...")
    try:
        fetch_gi_music()
    except Exception as e:
        _log(f"  G-Inspired fetch failed: {e}")


def _remote_listing(remote_dir: str) -> set:
    """One SSH call to list filenames already on Oracle in remote_dir, so the
    archive sync only pushes files Oracle doesn't have yet instead of
    re-uploading the whole (growing) pool every single day."""
    try:
        r = subprocess.run(
            ["ssh", "-i", str(ORACLE_KEY), "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", ORACLE,
             f"ls -1 {remote_dir} 2>/dev/null"],
            timeout=15, capture_output=True,
        )
        if r.returncode == 0:
            return set(r.stdout.decode(errors="replace").split())
    except Exception as e:
        _log(f"  remote listing failed for {remote_dir}: {e}")
    return set()


def _push_files(label: str, files: list, remote_dir: str):
    pushed = 0
    for f in sorted(files):
        try:
            r = subprocess.run(
                ["scp", "-i", str(ORACLE_KEY), "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
                 str(f), f"{ORACLE}:{remote_dir}"],
                timeout=30, capture_output=True,
            )
            if r.returncode == 0:
                pushed += 1
            else:
                _log(f"[{label}] SCP failed for {f.name} (exit {r.returncode}): "
                     f"{r.stderr.decode(errors='replace')[:150]}")
        except Exception as e:
            _log(f"[{label}] SCP error for {f.name}: {e}")
    return pushed


def _sync_to_oracle():
    """Push all three clients' daily music folders to Oracle. Laptop only."""
    if os.name != "nt":
        return
    if not ORACLE_KEY.exists():
        _log("No Oracle SSH key found — skipping sync")
        return

    folders = [
        ("BootHop",    MUSIC_DIR,            "/opt/otb_pipeline/music/daily/"),
        ("D818",       D818_MUSIC_DIR,       "/opt/otb_pipeline/music_d818/daily/"),
        ("G-Inspired", G_INSPIRED_MUSIC_DIR, "/opt/otb_pipeline/g_inspired_music/daily/"),
    ]
    for label, local_dir, remote_dir in folders:
        local_dir = Path(local_dir)
        files = list(local_dir.glob("track_*.mp3")) + list(local_dir.glob("daily_info.json"))
        if not files:
            _log(f"[{label}] nothing to sync")
            continue
        pushed = _push_files(label, files, remote_dir)
        _log(f"[{label}] synced {pushed}/{len(files)} file(s) -> {remote_dir}")

    # ── Archive pools ─────────────────────────────────────────────────────────
    # fetch_trending_music.py's _archive_track() grows each client's LOCAL
    # archive whenever a fresh SoundCloud track is found, but nothing used to
    # carry that growth to Oracle — the archive just kept accumulating on the
    # laptop only, while Oracle's copy (what its own archive-only fallback
    # actually draws from) stayed frozen at whatever it started with. Only
    # push files Oracle doesn't already have — these pools only grow, so a
    # full re-upload every day would be pure waste.
    archive_folders = [
        ("BootHop archive",    MUSIC_ARCHIVE,            "/opt/otb_pipeline/music/archive/"),
        ("D818 archive",       D818_MUSIC_ARCHIVE,       "/opt/otb_pipeline/music_d818/archive/"),
        ("G-Inspired archive", G_INSPIRED_MUSIC_ARCHIVE, "/opt/otb_pipeline/g_inspired_music/archive/"),
    ]
    for label, local_dir, remote_dir in archive_folders:
        local_dir = Path(local_dir)
        local_files = list(local_dir.glob("*.mp3")) + list(local_dir.glob("*.m4a"))
        if not local_files:
            _log(f"[{label}] empty locally — nothing to sync")
            continue
        remote_names = _remote_listing(remote_dir)
        new_files = [f for f in local_files if f.name not in remote_names]
        if not new_files:
            _log(f"[{label}] Oracle already has all {len(local_files)} track(s)")
            continue
        pushed = _push_files(label, new_files, remote_dir)
        _log(f"[{label}] synced {pushed}/{len(new_files)} new track(s) -> {remote_dir}")


if __name__ == "__main__":
    _log("=" * 56)
    _log("Daily Music Refresh — BootHop + D818 + G-Inspired")
    _log("=" * 56)
    _fetch_all()
    _sync_to_oracle()
    _log("Done.")
