"""
OTB_Pipeline — Memory Database

Stores every piece of content generated, with performance placeholders
that get populated when platform analytics are pulled.

After enough entries the AI can learn:
  - Which story types perform best per pillar
  - Which hooks get the most views
  - Which lessons get the most shares
  - Which visual scenes drive watch time

Schema per entry:
  id, date, slot, pillar, version
  hook, problem, stakes, resolution, lesson
  visual_queries, image_prompts, video_prompts
  qa_scores (from QA Director), review_scores (from Reviewer)
  captions (tiktok, instagram, youtube)
  performance (views, likes, shares, comments, watch_time per platform)
"""

import json, uuid
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA

MEMORY_FILE = DATA / "memory.json"


def _load() -> list:
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: list):
    DATA.mkdir(exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def save_entry(content: dict, slot: int, version: str = "v1") -> str:
    """
    Save a generated content entry to the memory database.
    Returns the entry ID so it can be referenced when updating performance data.
    """
    entries = _load()

    entry_id = str(uuid.uuid4())[:8]

    entry = {
        "id":      entry_id,
        "date":    date.today().isoformat(),
        "slot":    slot,
        "version": version,
        "pillar":  content.get("pillar", ""),

        # Story beats
        "hook":       content.get("hook", ""),
        "problem":    content.get("problem", ""),
        "stakes":     content.get("stakes", ""),
        "resolution": content.get("resolution", ""),
        "lesson":     content.get("lesson", ""),

        # Visual planning
        "visual_queries": content.get("visual_queries", []),
        "image_prompts":  content.get("image_prompts", []),
        "video_prompts":  content.get("video_prompts", []),

        # Quality scores
        "qa_scores":     content.get("qa_scores", {}),
        "review_scores": content.get("review_scores", {}),

        # Captions
        "caption_tiktok":    content.get("caption_tiktok", ""),
        "caption_instagram": content.get("caption_instagram", ""),
        "youtube_title":     content.get("youtube_title", ""),

        # Performance — starts at 0, updated by analytics pull
        "performance": {
            "tiktok":    {"views": 0, "likes": 0, "shares": 0, "comments": 0, "watch_pct": 0},
            "instagram": {"views": 0, "likes": 0, "saves": 0, "shares": 0},
            "youtube":   {"views": 0, "likes": 0, "watch_time_sec": 0},
        },
    }

    entries.append(entry)
    _save(entries)
    print(f"  [MemoryDB] Saved entry {entry_id} ({content.get('pillar', '')} slot {slot} {version})")
    return entry_id


def update_performance(entry_id: str, platform: str, metrics: dict):
    """
    Update the performance metrics for a stored entry.
    Called by platform analytics scripts after fetching post stats.

    Example:
      update_performance("a1b2c3d4", "tiktok", {"views": 12400, "likes": 890, "shares": 45})
    """
    entries = _load()
    for entry in entries:
        if entry.get("id") == entry_id:
            if platform in entry.get("performance", {}):
                entry["performance"][platform].update(metrics)
                _save(entries)
                print(f"  [MemoryDB] Updated {platform} performance for entry {entry_id}")
                return
    print(f"  [MemoryDB] Entry {entry_id} not found")


def get_top_performers(pillar: str = None, platform: str = "tiktok", n: int = 10) -> list:
    """
    Return the top N performing entries by views, optionally filtered by pillar.
    Useful for understanding what story types work best.
    """
    entries = _load()
    if pillar:
        entries = [e for e in entries if e.get("pillar") == pillar]

    def views(e):
        return e.get("performance", {}).get(platform, {}).get("views", 0)

    entries.sort(key=views, reverse=True)
    return entries[:n]


def get_stats() -> str:
    """Return a quick text summary of the memory database."""
    entries = _load()
    if not entries:
        return "Memory database: empty"

    by_pillar: dict[str, int] = {}
    for e in entries:
        p = e.get("pillar", "unknown")
        by_pillar[p] = by_pillar.get(p, 0) + 1

    total_tiktok_views = sum(
        e.get("performance", {}).get("tiktok", {}).get("views", 0) for e in entries
    )

    lines = [
        f"Memory database: {len(entries)} entries",
        f"Total TikTok views tracked: {total_tiktok_views:,}",
        "Entries by pillar:",
    ]
    for pillar, count in sorted(by_pillar.items(), key=lambda x: -x[1]):
        lines.append(f"  {pillar}: {count}")

    return "\n".join(lines)
