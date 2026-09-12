"""
Standalone Telegram delivery — resend a completed episode if delivery failed.
Usage: python telegram_delivery.py --episode 1
"""
import argparse, json, sys
from pathlib import Path

CARTOON = Path(__file__).parent.parent
STATE   = CARTOON / "state"
EPISODES = CARTOON / "episodes"

sys.path.insert(0, str(CARTOON.parent))
from cartoon.automation.episode_runner import (
    _load_json, deliver_to_telegram, EPISODE_1, _log
)

EPISODES_MAP = {1: EPISODE_1}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", type=int, required=True)
    args = parser.parse_args()

    ep_dir = EPISODES / f"episode_{args.episode:03}"
    manifest = _load_json(ep_dir / "episode_manifest.json")
    if not manifest:
        print(f"No manifest for episode {args.episode}")
        sys.exit(1)

    final = ep_dir / "final_video.mp4"
    if not final.exists():
        print("final_video.mp4 not found")
        sys.exit(1)

    episode = EPISODES_MAP.get(args.episode)
    if not episode:
        print(f"Episode {args.episode} not in episodes map")
        sys.exit(1)

    costs = manifest.get("actual_cost", {"total": 0})
    qa    = manifest.get("qa", {"passed": True, "issues": [], "duration": 30})

    _log(f"Re-delivering episode {args.episode} to Telegram...")
    deliver_to_telegram(episode, ep_dir, final, costs, qa)
    _log("Done.")
