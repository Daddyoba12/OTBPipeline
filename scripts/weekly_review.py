"""
OTB_Pipeline — Weekly performance review
=========================================
Pulls view counts from each platform independently:
  YouTube Shorts  → YouTube Data API        (YOUTUBE_API_KEY — already set)
  TikTok          → Zernio GET /v1/posts    (ZERNIO_API_KEY  — already set)
  Instagram Reels → Instagram Graph API     (add INSTAGRAM_ACCESS_TOKEN +
                                             INSTAGRAM_ACCOUNT_ID to keys.env)

Cross-references with memory.json to link each post to its hook/pillar/slot,
ranks what's working per platform, and writes:
  data/performance_log.json   — full audit trail
  data/pillar_weights.json    — pipeline reads this to bias pillar selection

Run manually : python scripts/weekly_review.py [--days 30]
Schedule     : weekly (Windows Task Scheduler or Oracle cron, Monday 06:00)
"""

import json, sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import requests

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from config import DATA

# ── Keys (all loaded from keys.env via config) ────────────────────────────────
try:
    from config import YOUTUBE_API_KEY
except ImportError:
    YOUTUBE_API_KEY = ""

try:
    from config import ZERNIO_API_KEY, ZERNIO_ACCOUNT_ID
except ImportError:
    ZERNIO_API_KEY = ZERNIO_ACCOUNT_ID = ""

try:
    from config import INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID
except (ImportError, AttributeError):
    INSTAGRAM_ACCESS_TOKEN = INSTAGRAM_ACCOUNT_ID = ""

PERF_LOG   = DATA / "performance_log.json"
POST_LOG   = DATA / "post_log.json"
MEMORY     = DATA / "memory.json"
SLOT_LABELS = {1: "08:00 morning", 2: "14:00 afternoon", 3: "21:00 evening"}


# ── Post log helpers ───────────────────────────────────────────────────────────

def _load_posts(platform: str, days: int = 30) -> list[dict]:
    if not POST_LOG.exists():
        return []
    try:
        log = json.loads(POST_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return [e for e in log
            if e.get("platform") == platform
            and e.get("posted_at", "") > cutoff]


# ── YouTube Shorts ─────────────────────────────────────────────────────────────

def _fetch_youtube(posts: list[dict]) -> list[dict]:
    """Pull real YouTube view + like counts via YouTube Data API."""
    ids = [p["video_id"] for p in posts if p.get("video_id")]
    if not ids or not YOUTUBE_API_KEY:
        if not YOUTUBE_API_KEY:
            print("  [YouTube] YOUTUBE_API_KEY not set — skipping")
        return []

    raw: dict[str, dict] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start:start + 50]
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "key":    YOUTUBE_API_KEY,
                    "id":     ",".join(chunk),
                    "part":   "statistics",
                    "fields": "items(id,statistics(viewCount,likeCount,commentCount))",
                },
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("items", []):
                s = item.get("statistics", {})
                raw[item["id"]] = {
                    "views":    int(s.get("viewCount",    0)),
                    "likes":    int(s.get("likeCount",    0)),
                    "comments": int(s.get("commentCount", 0)),
                }
        except Exception as e:
            print(f"  [YouTube] API error: {e}")

    results = []
    for p in posts:
        vid = p.get("video_id", "")
        s   = raw.get(vid, {})
        results.append({
            "platform":  "youtube",
            "post_id":   vid,
            "slot":      p.get("slot"),
            "posted_at": p.get("posted_at", ""),
            "views":     s.get("views",    0),
            "likes":     s.get("likes",    0),
            "comments":  s.get("comments", 0),
            "url":       p.get("url", f"https://youtube.com/shorts/{vid}"),
        })
    print(f"  [YouTube] {len(results)} posts, {sum(r['views'] for r in results):,} total views")
    return results


# ── TikTok via Zernio ─────────────────────────────────────────────────────────

def _fetch_tiktok(posts: list[dict], days: int = 30) -> list[dict]:
    """
    Pull TikTok stats via Zernio GET /v1/posts.
    Zernio stores the real TikTok post ID after publishing — this lets us link
    our 'queued' publish_ids to actual TikTok content and pull view counts.
    """
    if not ZERNIO_API_KEY:
        print("  [TikTok/Zernio] ZERNIO_API_KEY not set — skipping")
        return []

    headers = {"Authorization": f"Bearer {ZERNIO_API_KEY}", "Content-Type": "application/json"}
    cutoff  = (datetime.now() - timedelta(days=days)).isoformat()[:10]

    # Pull all posts from Zernio for our account
    zernio_posts: list[dict] = []
    try:
        r = requests.get(
            "https://zernio.com/api/v1/posts",
            headers=headers,
            params={"accountId": ZERNIO_ACCOUNT_ID, "platform": "tiktok", "limit": 100},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        # Handle both list and paginated responses
        items = data if isinstance(data, list) else data.get("posts") or data.get("data") or []
        zernio_posts = [p for p in items
                        if p.get("publishedAt", p.get("createdAt", ""))[:10] >= cutoff]
        print(f"  [TikTok/Zernio] {len(zernio_posts)} posts found since {cutoff}")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            print("  [TikTok/Zernio] GET /v1/posts not available on this plan — no TikTok stats")
        else:
            print(f"  [TikTok/Zernio] API error {e.response.status_code}: {e}")
        return []
    except Exception as e:
        print(f"  [TikTok/Zernio] Error: {e}")
        return []

    if not zernio_posts:
        print("  [TikTok/Zernio] No posts in window — check Zernio dashboard manually")
        return []

    # Map Zernio posts to our post_log by date proximity
    results = []
    for zp in zernio_posts:
        published = zp.get("publishedAt") or zp.get("createdAt") or ""
        date_str  = published[:10]
        stats     = zp.get("analytics") or zp.get("statistics") or zp.get("stats") or {}

        # Try multiple field names Zernio might use for views
        views    = (stats.get("views")    or stats.get("viewCount")  or
                    stats.get("plays")    or stats.get("playCount")  or 0)
        likes    = (stats.get("likes")    or stats.get("likeCount")  or 0)
        comments = (stats.get("comments") or stats.get("commentCount") or 0)
        shares   = (stats.get("shares")   or stats.get("shareCount") or 0)

        tiktok_id = (zp.get("tiktokId")  or zp.get("tiktok_id") or
                     zp.get("postId")     or zp.get("_id") or "")

        results.append({
            "platform":  "tiktok",
            "post_id":   tiktok_id,
            "slot":      _guess_slot(published),
            "posted_at": published,
            "views":     int(views),
            "likes":     int(likes),
            "comments":  int(comments),
            "shares":    int(shares),
            "url":       f"https://tiktok.com/@boothop/video/{tiktok_id}" if tiktok_id else "",
        })

    total_views = sum(r["views"] for r in results)
    print(f"  [TikTok] {len(results)} posts, {total_views:,} total views")
    return results


# ── Instagram Reels ────────────────────────────────────────────────────────────

def _fetch_instagram(posts: list[dict]) -> list[dict]:
    """
    Pull Instagram Reels stats via Instagram Graph API.

    SETUP: Add these to keys.env (one-time setup via Meta Developer Console):
      INSTAGRAM_ACCESS_TOKEN=<long-lived token>
      INSTAGRAM_ACCOUNT_ID=<numeric IG Business Account ID>

    The token lasts 60 days — refresh it monthly or set up auto-refresh.
    """
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        print("  [Instagram] Add INSTAGRAM_ACCESS_TOKEN + INSTAGRAM_ACCOUNT_ID to keys.env")
        print("              Get from: developers.facebook.com → your app → Instagram Graph API")
        return []

    results = []
    for p in posts:
        media_id = p.get("media_id", "")
        if not media_id:
            continue
        try:
            r = requests.get(
                f"https://graph.facebook.com/v18.0/{media_id}",
                params={
                    "fields":       "views,like_count,comments_count,shares_count,reach,plays",
                    "access_token": INSTAGRAM_ACCESS_TOKEN,
                },
                timeout=15,
            )
            r.raise_for_status()
            s = r.json()
            results.append({
                "platform":  "instagram",
                "post_id":   media_id,
                "slot":      p.get("slot"),
                "posted_at": p.get("posted_at", ""),
                "views":     int(s.get("views") or s.get("plays") or s.get("reach") or 0),
                "likes":     int(s.get("like_count", 0)),
                "comments":  int(s.get("comments_count", 0)),
                "shares":    int(s.get("shares_count", 0)),
            })
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                print("  [Instagram] Token expired — refresh INSTAGRAM_ACCESS_TOKEN in keys.env")
                break
            print(f"  [Instagram] {media_id}: HTTP {e.response.status_code}")
        except Exception as e:
            print(f"  [Instagram] {media_id}: {e}")

    total_views = sum(r["views"] for r in results)
    print(f"  [Instagram] {len(results)} posts, {total_views:,} total views")
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _guess_slot(posted_at: str) -> int:
    """Infer slot from post hour (08=1, 14=2, 21=3)."""
    try:
        h = datetime.fromisoformat(posted_at).hour
        if h < 11:  return 1
        if h < 18:  return 2
        return 3
    except Exception:
        return 0


def _load_memory() -> list[dict]:
    if not MEMORY.exists():
        return []
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def _match_memory(date_str: str, slot: int, mem: list[dict]) -> dict:
    candidates = [e for e in mem
                  if e.get("date", "") == date_str and e.get("slot") == slot]
    if candidates:
        return candidates[-1]
    day_entries = [e for e in mem if e.get("date", "") == date_str]
    return day_entries[-1] if day_entries else {}


def _hook_opener(hook: str) -> str:
    words = hook.strip().split()
    return " ".join(words[:4]).lower() if words else "(empty)"


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate_platform(posts_with_stats: list[dict], mem: list[dict]) -> dict:
    """Aggregate one platform's stats by pillar, slot, hook opener, weekday."""
    by_pillar:  defaultdict = defaultdict(list)
    by_slot:    defaultdict = defaultdict(list)
    by_opener:  defaultdict = defaultdict(list)
    by_weekday: defaultdict = defaultdict(list)
    enriched: list[dict]    = []

    for p in posts_with_stats:
        slot    = p.get("slot") or _guess_slot(p.get("posted_at", ""))
        posted  = p.get("posted_at", "")
        date_s  = posted[:10]
        views   = p.get("views", 0)
        entry   = _match_memory(date_s, slot, mem)

        pillar  = entry.get("pillar", "unknown")
        hook    = entry.get("hook", "")
        opener  = _hook_opener(hook)
        try:
            weekday = datetime.fromisoformat(posted).strftime("%A")
        except Exception:
            weekday = "Unknown"

        row = {**p, "pillar": pillar, "hook": hook[:120], "opener": opener, "weekday": weekday}
        enriched.append(row)
        by_pillar[pillar].append(views)
        by_slot[slot].append(views)
        by_opener[opener].append(views)
        by_weekday[weekday].append(views)

    def _avg(lst): return round(sum(lst) / len(lst)) if lst else 0
    def _rank(d):  return sorted(d.items(), key=lambda x: _avg(x[1]), reverse=True)

    return {
        "count":         len(enriched),
        "total_views":   sum(p.get("views", 0) for p in enriched),
        "by_pillar":     {k: {"avg": _avg(v), "count": len(v), "total": sum(v)}
                          for k, v in _rank(by_pillar)},
        "by_slot":       {str(k): {"avg": _avg(v), "label": SLOT_LABELS.get(k, ""), "count": len(v)}
                          for k, v in _rank(by_slot)},
        "by_opener":     {k: {"avg": _avg(v), "count": len(v)}
                          for k, v in _rank(by_opener)[:15]},
        "by_weekday":    {k: {"avg": _avg(v), "count": len(v)}
                          for k, v in _rank(by_weekday)},
        "top_posts":     sorted(enriched, key=lambda x: x.get("views", 0), reverse=True)[:5],
    }


# ── Report printer ────────────────────────────────────────────────────────────

def _print_platform(name: str, agg: dict):
    if not agg or agg.get("count", 0) == 0:
        print(f"\n  {name}: no data")
        return
    sep = "─" * 60
    print(f"\n{'='*60}")
    print(f"  {name.upper()} — {agg['count']} posts — {agg['total_views']:,} total views")
    print(f"{'='*60}")

    print("\nPILLARS (avg views, ranked):")
    print(sep)
    for pillar, d in list(agg["by_pillar"].items())[:8]:
        bar = "█" * min(35, d["avg"] // 50)
        print(f"  {pillar:<22}  {d['avg']:>6} avg  {d['count']:>2} posts  {bar}")

    print("\nSLOT TIMES:")
    print(sep)
    for s, d in agg["by_slot"].items():
        print(f"  Slot {s} ({d['label']:<20})  {d['avg']:>6} avg  ({d['count']} posts)")

    print("\nTOP 3 HOOK OPENERS:")
    print(sep)
    for i, (opener, d) in enumerate(list(agg["by_opener"].items())[:3], 1):
        print(f"  {i}. '{opener}...'  →  {d['avg']:>6} avg views  ({d['count']} posts)")

    print("\nBEST DAY:")
    print(sep)
    best_day = next(iter(agg["by_weekday"].items()), (None, {}))
    if best_day[0]:
        print(f"  {best_day[0]}  →  {best_day[1]['avg']:,} avg views")

    print("\nTOP 3 VIDEOS:")
    for p in agg["top_posts"][:3]:
        url = p.get("url", "")
        print(f"  {p.get('views', 0):>7,} views  [{p.get('pillar', '?')}]  {url}")


def _print_cross_platform(aggs: dict):
    """Show which pillars consistently work across all platforms."""
    all_pillars: set = set()
    for agg in aggs.values():
        all_pillars.update(agg.get("by_pillar", {}).keys())

    print(f"\n{'='*60}")
    print("  CROSS-PLATFORM — which pillars work everywhere?")
    print(f"{'='*60}")
    rows = []
    for pillar in all_pillars:
        platform_avgs = {}
        for platform, agg in aggs.items():
            d = agg.get("by_pillar", {}).get(pillar)
            if d:
                platform_avgs[platform] = d["avg"]
        if platform_avgs:
            overall = round(sum(platform_avgs.values()) / len(platform_avgs))
            rows.append((pillar, overall, platform_avgs))
    rows.sort(key=lambda x: x[1], reverse=True)
    for pillar, overall, pa in rows[:8]:
        breakdown = "  ".join(f"{pl}:{v:,}" for pl, v in pa.items())
        print(f"  {pillar:<22}  {overall:>6} avg  [{breakdown}]")


# ── Save + pipeline feedback ──────────────────────────────────────────────────

def _save_and_adapt(aggs: dict):
    """Write performance_log + pillar_weights (pipeline reads this weekly)."""
    full_log = {
        "generated_at": datetime.now().isoformat(),
        "platforms":    aggs,
    }
    PERF_LOG.write_text(json.dumps(full_log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  [Analytics] Saved to {PERF_LOG.name}")

    # Build pillar weights from the platform with the most data
    # TikTok is primary; fall back to YouTube if TikTok has no data
    primary_platform = max(aggs, key=lambda p: aggs[p].get("count", 0), default=None)
    if primary_platform:
        pillars = aggs[primary_platform].get("by_pillar", {})
        if pillars:
            max_avg = max(d["avg"] for d in pillars.values()) or 1
            weights = {k: round(max(0.3, d["avg"] / max_avg), 2) for k, d in pillars.items()}
            weights_path = DATA / "pillar_weights.json"
            weights_path.write_text(json.dumps(weights, indent=2), encoding="utf-8")
            print(f"  [Analytics] Pillar weights updated from {primary_platform} data")
            top3 = sorted(weights, key=weights.get, reverse=True)[:3]
            print(f"  [Analytics] Recommend pushing: {', '.join(top3)}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_review(days: int = 30):
    print(f"\n{'='*60}")
    print(f"  OTB WEEKLY PERFORMANCE REVIEW")
    print(f"  {datetime.now():%Y-%m-%d %H:%M}   |   last {days} days")
    print(f"{'='*60}\n")

    mem = _load_memory()
    aggs: dict = {}

    # ── TikTok ────────────────────────────────────────────────────────────────
    print("[TikTok] Fetching via Zernio...")
    tk_posts = _load_posts("tiktok", days)
    tk_stats = _fetch_tiktok(tk_posts, days)
    if tk_stats:
        aggs["tiktok"] = _aggregate_platform(tk_stats, mem)

    # ── YouTube ───────────────────────────────────────────────────────────────
    print("\n[YouTube] Fetching via YouTube Data API...")
    yt_posts = _load_posts("youtube", days)
    yt_stats = _fetch_youtube(yt_posts)
    if yt_stats:
        aggs["youtube"] = _aggregate_platform(yt_stats, mem)

    # ── Instagram ─────────────────────────────────────────────────────────────
    print("\n[Instagram] Fetching via Instagram Graph API...")
    ig_posts = _load_posts("instagram", days)
    ig_stats = _fetch_instagram(ig_posts)
    if ig_stats:
        aggs["instagram"] = _aggregate_platform(ig_stats, mem)

    # ── Reports ───────────────────────────────────────────────────────────────
    for platform, agg in aggs.items():
        _print_platform(platform, agg)

    if len(aggs) > 1:
        _print_cross_platform(aggs)

    if not aggs:
        print("\nNo platform data available. Check API credentials in keys.env.")
        return {}

    _save_and_adapt(aggs)
    return aggs


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="OTB weekly performance review")
    p.add_argument("--days", type=int, default=30, help="Look-back window in days")
    args = p.parse_args()
    run_review(args.days)
