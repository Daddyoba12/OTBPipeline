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

from config import MUSIC_DIR, D818_MUSIC_DIR, G_INSPIRED_MUSIC_DIR

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
        _log(f"[{label}] synced {pushed}/{len(files)} file(s) -> {remote_dir}")


if __name__ == "__main__":
    _log("=" * 56)
    _log("Daily Music Refresh — BootHop + D818 + G-Inspired")
    _log("=" * 56)
    _fetch_all()
    _sync_to_oracle()
    _log("Done.")
