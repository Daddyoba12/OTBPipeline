"""
Standalone Telegram delivery — resend or list completed episodes.

Usage:
    python telegram_delivery.py --list            # see all episodes and their status
    python telegram_delivery.py --episode 1       # re-send episode 1 to Telegram
    python telegram_delivery.py --episode 2       # re-send episode 2 to Telegram
"""
import argparse, json, sys
from pathlib import Path

CARTOON  = Path(__file__).parent.parent
STATE    = CARTOON / "state"
EPISODES = CARTOON / "episodes"

sys.path.insert(0, str(CARTOON.parent))
from cartoon.automation.episode_runner import (
    _load_json, deliver_to_telegram, EPISODE_1, EPISODE_2, _log
)

EPISODES_MAP = {1: EPISODE_1, 2: EPISODE_2}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram delivery for BOUNCE ON THE MOVE")
    parser.add_argument("--episode", type=int, default=None, help="Episode number to re-send")
    parser.add_argument("--list",    action="store_true",    help="List all episodes and their status")
    args = parser.parse_args()

    if args.list:
        print(f"\n{'Ep':<4} {'Title':<22} {'Status':<18} {'Video':<6}")
        print("-" * 55)
        for ep_num in sorted(EPISODES_MAP.keys()):
            ep_dir   = EPISODES / f"episode_{ep_num:03}"
            final    = ep_dir / "final_video.mp4"
            manifest = _load_json(ep_dir / "episode_manifest.json")
            status   = manifest.get("status", "not started") if manifest else "not started"
            has_vid  = "YES" if final.exists() else "no"
            title    = EPISODES_MAP[ep_num]["title"]
            print(f"  {ep_num:<4} {title:<22} {status:<18} {has_vid}")
        print()
        sys.exit(0)

    if args.episode is None:
        parser.print_help()
        sys.exit(1)

    ep = EPISODES_MAP.get(args.episode)
    if not ep:
        print(f"Episode {args.episode} not in episodes map")
        sys.exit(1)

    ep_dir = EPISODES / f"episode_{args.episode:03}"
    final  = ep_dir / "final_video.mp4"

    if not final.exists():
        print(f"No final_video.mp4 for episode {args.episode}. Run episode_runner.py first.")
        sys.exit(1)

    manifest = _load_json(ep_dir / "episode_manifest.json")
    if not manifest:
        print(f"No manifest for episode {args.episode}")
        sys.exit(1)

    costs = manifest.get("actual_cost", {"total": 0})
    qa    = manifest.get("qa", {"passed": True, "issues": [], "duration": 30})

    _log(f"Re-delivering episode {args.episode} to Telegram...")
    deliver_to_telegram(ep, ep_dir, final, costs, qa)
    _log("Done.")
