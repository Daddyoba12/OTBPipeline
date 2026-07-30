"""
OTB_Pipeline — Weekly performance review
=========================================
Fetches YouTube Shorts view counts for the last 30 days, cross-references with
memory.json to identify which hooks/pillars/slots drive the most views, then
writes data/performance_log.json that the pipeline reads to auto-adapt.

Run manually : python scripts/weekly_review.py
Run weekly   : add to Windows Task Scheduler or Oracle cron

Output
------
  stdout          : ranked human-readable report
  data/performance_log.json : machine-readable results for pipeline adaptation
"""

import json, sys, re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import requests

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from config import DATA

try:
    from config import YOUTUBE_API_KEY
except ImportError:
    YOUTUBE_API_KEY = ""

PERF_LOG = DATA / "performance_log.json"
POST_LOG  = DATA / "post_log.json"
MEMORY    = DATA / "memory.json"

SLOT_LABELS = {1: "08:00 morning", 2: "14:00 afternoon", 3: "21:00 evening"}


# ── Data loaders ──────────────────────────────────────────────────────────────

def _load_youtube_posts(days: int = 30) -> list[dict]:
    if not POST_LOG.exists():
        return []
    try:
        log = json.loads(POST_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return [
        e for e in log
        if e.get("platform") == "youtube"
        and e.get("video_id")
        and e.get("posted_at", "") > cutoff
    ]


def _fetch_view_counts(video_ids: list[str]) -> dict[str, int]:
    if not YOUTUBE_API_KEY or not video_ids:
        print("  [Analytics] No YouTube API key — view counts unavailable")
        return {}
    counts: dict[str, int] = {}
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start : start + 50]
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "key":    YOUTUBE_API_KEY,
                    "id":     ",".join(chunk),
                    "part":   "statistics",
                    "fields": "items(id,statistics/viewCount,statistics/likeCount)",
                },
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("items", []):
                vid   = item["id"]
                stats = item.get("statistics", {})
                counts[vid] = {
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                }
        except Exception as e:
            print(f"  [YouTube API] Error: {e}")
    return counts


def _load_memory() -> list[dict]:
    if not MEMORY.exists():
        return []
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def _match_memory(date_str: str, slot: int, mem: list[dict]) -> dict:
    """Find the memory entry for a given date + slot."""
    candidates = [
        e for e in mem
        if e.get("date", "") == date_str and e.get("slot") == slot
    ]
    if candidates:
        return candidates[-1]
    # Fallback: same date, any slot
    day_entries = [e for e in mem if e.get("date", "") == date_str]
    return day_entries[-1] if day_entries else {}


def _hook_opener(hook: str) -> str:
    """Return the first 4 words of a hook as the opener pattern."""
    words = hook.strip().split()
    return " ".join(words[:4]).lower() if words else "(empty)"


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate(posts: list[dict], counts: dict, mem: list[dict]) -> dict:
    """Merge YouTube stats with memory entries and aggregate by dimension."""
    by_pillar:  defaultdict = defaultdict(list)
    by_slot:    defaultdict = defaultdict(list)
    by_opener:  defaultdict = defaultdict(list)
    by_weekday: defaultdict = defaultdict(list)
    enriched: list[dict]    = []

    for post in posts:
        vid     = post.get("video_id", "")
        slot    = post.get("slot", 0)
        posted  = post.get("posted_at", "")
        date_s  = posted[:10]
        stats   = counts.get(vid, {"views": 0, "likes": 0})
        views   = stats.get("views", 0) if isinstance(stats, dict) else int(stats)
        likes   = stats.get("likes", 0) if isinstance(stats, dict) else 0
        entry   = _match_memory(date_s, slot, mem)

        pillar  = entry.get("pillar", "unknown")
        hook    = entry.get("hook", "")
        opener  = _hook_opener(hook)
        try:
            weekday = datetime.fromisoformat(posted).strftime("%A")
        except Exception:
            weekday = "Unknown"

        row = {
            "video_id":  vid,
            "date":      date_s,
            "slot":      slot,
            "pillar":    pillar,
            "hook":      hook[:120],
            "opener":    opener,
            "weekday":   weekday,
            "views":     views,
            "likes":     likes,
            "url":       f"https://youtube.com/shorts/{vid}",
        }
        enriched.append(row)
        by_pillar[pillar].append(views)
        by_slot[slot].append(views)
        by_opener[opener].append(views)
        by_weekday[weekday].append(views)

    def _avg(lst): return round(sum(lst) / len(lst)) if lst else 0
    def _rank(d):  return sorted(d.items(), key=lambda x: _avg(x[1]), reverse=True)

    return {
        "generated_at":      datetime.now().isoformat(),
        "posts_analysed":    len(enriched),
        "by_pillar":         {k: {"avg_views": _avg(v), "count": len(v), "total": sum(v)}
                              for k, v in _rank(by_pillar)},
        "by_slot":           {str(k): {"avg_views": _avg(v), "label": SLOT_LABELS.get(k, ""), "count": len(v)}
                              for k, v in _rank(by_slot)},
        "by_opener":         {k: {"avg_views": _avg(v), "count": len(v)}
                              for k, v in _rank(by_opener)[:20]},    # top 20 openers
        "by_weekday":        {k: {"avg_views": _avg(v), "count": len(v)}
                              for k, v in _rank(by_weekday)},
        "top_posts":         sorted(enriched, key=lambda x: x["views"], reverse=True)[:10],
        "bottom_posts":      sorted(enriched, key=lambda x: x["views"])[:5],
        "recommended_pillars": [k for k, v in _rank(by_pillar) if v["avg_views"] > 0][:4],
    }


# ── Report printer ────────────────────────────────────────────────────────────

def _print_report(agg: dict):
    sep = "─" * 62
    print(f"\n{'='*62}")
    print(f"  OTB WEEKLY PERFORMANCE REPORT")
    print(f"  {agg['generated_at'][:16]}   |   {agg['posts_analysed']} posts analysed")
    print(f"{'='*62}\n")

    print("PILLARS — avg views (YouTube Shorts, last 30 days)")
    print(sep)
    for pillar, d in agg["by_pillar"].items():
        bar = "█" * min(40, d["avg_views"] // 50)
        print(f"  {pillar:<22}  {d['avg_views']:>5} avg  {d['count']:>2} posts  {bar}")
    print()

    print("POSTING SLOT — avg views")
    print(sep)
    for slot, d in agg["by_slot"].items():
        print(f"  Slot {slot} ({d['label']:<20})  {d['avg_views']:>5} avg  {d['count']:>2} posts")
    print()

    print("TOP 5 HOOK OPENERS — avg views")
    print(sep)
    for i, (opener, d) in enumerate(list(agg["by_opener"].items())[:5], 1):
        print(f"  {i}. '{opener}...'   {d['avg_views']:>5} avg  ({d['count']} posts)")
    print()

    print("BEST DAY TO POST")
    print(sep)
    for day, d in agg["by_weekday"].items():
        print(f"  {day:<12}  {d['avg_views']:>5} avg views  ({d['count']} posts)")
    print()

    print("TOP 3 VIDEOS")
    print(sep)
    for p in agg["top_posts"][:3]:
        print(f"  {p['views']:>6} views  [{p['pillar']}]  {p['url']}")
        print(f"            Hook: {p['hook'][:70]}")
    print()

    recs = agg.get("recommended_pillars", [])
    if recs:
        print(f"PIPELINE RECOMMENDATION → prioritise pillars: {', '.join(recs)}")
    print(f"{'='*62}\n")


# ── Save + pipeline feedback ──────────────────────────────────────────────────

def _save_and_adapt(agg: dict):
    """Write performance_log.json. Pipeline reads this to bias pillar selection."""
    PERF_LOG.write_text(json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [Analytics] Saved to {PERF_LOG}")

    # Write a simple pillar-weights file the pipeline can import
    weights_path = DATA / "pillar_weights.json"
    pillars = list(agg["by_pillar"].items())
    if pillars:
        max_avg = max(d["avg_views"] for _, d in pillars) or 1
        weights = {
            k: round(max(0.3, d["avg_views"] / max_avg), 2)
            for k, d in pillars
        }
        weights_path.write_text(json.dumps(weights, indent=2), encoding="utf-8")
        print(f"  [Analytics] Pillar weights updated → {weights_path.name}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_review(days: int = 30):
    print(f"\n[Analytics] Fetching last {days} days of YouTube Shorts performance...")
    posts  = _load_youtube_posts(days)
    if not posts:
        print("  No YouTube posts found in post_log.json — nothing to analyse.")
        return {}

    ids    = [p["video_id"] for p in posts]
    print(f"  Found {len(ids)} YouTube Shorts")
    counts = _fetch_view_counts(ids)
    print(f"  Fetched view counts for {len(counts)} videos")

    mem = _load_memory()
    agg = _aggregate(posts, counts, mem)
    _print_report(agg)
    _save_and_adapt(agg)
    return agg


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OTB weekly performance review")
    parser.add_argument("--days", type=int, default=30, help="Look-back window in days")
    args = parser.parse_args()
    run_review(args.days)
