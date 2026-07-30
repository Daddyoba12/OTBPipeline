"""
post_pending.py — runs on the laptop after every Oracle sync pull.

If Oracle failed to post to TikTok / Instagram / YouTube (key missing, network blip, etc.),
it writes the failed post to data/pending_posts.json. This script:
  1. Reads that file
  2. SCPs the video from Oracle to a local temp file
  3. Posts it using the same scripts the pipeline uses
  4. Marks the entry done and writes the result back

Called automatically by deploy/sync_data.ps1 after a pull.
"""

import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from config import DATA, ORACLE_IP, ORACLE_USER, ORACLE_KEY, TIKTOK_POSTER


def run():
    if platform.system() != "Windows":
        return  # Only the laptop handles pending posts

    pending_path = DATA / "pending_posts.json"
    if not pending_path.exists():
        return

    try:
        state = json.loads(pending_path.read_text())
    except Exception:
        return

    pending = state.get("pending", [])
    has_pending = any(e.get("status") == "pending" for e in pending)
    if not has_pending:
        return

    print(f"[PendingPosts] Processing {sum(1 for e in pending if e.get('status') == 'pending')} queued post(s) from Oracle...")

    temp_dir = BASE / "temp"
    temp_dir.mkdir(exist_ok=True)

    key_arg = f'-i "{ORACLE_KEY}"' if ORACLE_KEY else ""

    for entry in pending:
        if entry.get("status") != "pending":
            continue

        plat      = entry["platform"]
        slot      = entry["slot"]
        ora_path  = entry["video_path"]
        content   = entry["content"]
        local_vid = temp_dir / f"pending_{plat}_slot{slot}.mp4"

        print(f"[PendingPosts] Fetching {plat} video from Oracle...")
        scp_cmd = f'scp {key_arg} -o StrictHostKeyChecking=no {ORACLE_USER}@{ORACLE_IP}:"{ora_path}" "{local_vid}"'
        r = subprocess.run(scp_cmd, shell=True, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[PendingPosts] SCP failed: {r.stderr.strip()}")
            entry["status"]     = "scp_failed"
            entry["error"]      = r.stderr.strip()
            entry["attempted_at"] = datetime.now().isoformat()
            continue

        print(f"[PendingPosts] Posting {plat}...")
        try:
            if plat == "tiktok":
                import importlib
                mod    = "post_tiktok_zernio" if TIKTOK_POSTER == "zernio" else "post_tiktok"
                tk     = importlib.import_module(mod)
                result = tk.post_video(str(local_vid), content, slot)
            elif plat == "instagram":
                from post_instagram import post_video as ig_post
                result = ig_post(str(local_vid), content, slot)
            elif plat == "youtube":
                from post_youtube import post_video as yt_post
                result = yt_post(str(local_vid), content, slot)
            else:
                print(f"[PendingPosts] Unknown platform: {plat}")
                entry["status"] = "unknown_platform"
                continue

            if result:
                print(f"[PendingPosts] {plat} OK — {result}")
                entry["status"]     = "posted"
                entry["result"]     = str(result)
                entry["posted_at"]  = datetime.now().isoformat()
                entry["posted_by"]  = "laptop"
            else:
                print(f"[PendingPosts] {plat} post returned no ID — marking failed")
                entry["status"]     = "post_failed"
                entry["attempted_at"] = datetime.now().isoformat()

        except Exception as e:
            print(f"[PendingPosts] {plat} error: {e}")
            entry["status"]       = "post_failed"
            entry["error"]        = str(e)
            entry["attempted_at"] = datetime.now().isoformat()
        finally:
            try:
                local_vid.unlink(missing_ok=True)
            except Exception:
                pass

    state["pending"] = pending
    pending_path.write_text(json.dumps(state, indent=2))
    print("[PendingPosts] Done.")


if __name__ == "__main__":
    run()
