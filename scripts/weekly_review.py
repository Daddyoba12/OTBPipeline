"""
OTB_Pipeline — Weekly performance review
=========================================
Pulls view counts from each platform using existing credentials in
scripts/social_credentials.json (same file the posters use):

  TikTok    → TikTok v2 API  (video list → match by date → view counts)
  YouTube   → YouTube Data API
  Instagram → Instagram Graph API

Cross-references with memory.json to link each post to its hook/pillar/slot,
ranks what's working per platform, and writes:
  data/performance_log.json   — full audit trail
  data/pillar_weights.json    — pipeline reads this to bias pillar selection

Run manually : python scripts/weekly_review.py [--days 30]
Schedule     : weekly (Monday 06:00, before pipeline fires)
"""

import json, sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import requests

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from config import DATA, CREDS_PATH, YOUTUBE_API_KEY

PERF_LOG    = DATA / "performance_log.json"
POST_LOG    = DATA / "post_log.json"
MEMORY      = DATA / "memory.json"
SLOT_LABELS = {1: "08:00 morning", 2: "14:00 afternoon", 3: "21:00 evening"}


# ── Credential loader ─────────────────────────────────────────────────────────

def _creds(platform: str) -> dict:
    """Read credentials from social_credentials.json (same source as the posters)."""
    try:
        return json.loads(Path(CREDS_PATH).read_text(encoding="utf-8")).get(platform, {})
    except Exception as e:
        print(f"  [Creds] Could not read {CREDS_PATH}: {e}")
        return {}


# ── Post log ──────────────────────────────────────────────────────────────────

def _load_posts(platform: str, days: int) -> list[dict]:
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


# ── TikTok ─────────────────────────────────────────────────────────────────────

def _fetch_tiktok(days: int) -> list[dict]:
    """
    Query TikTok v2 API for our own videos, match to post_log by date, pull stats.
    Uses access_token + open_id from social_credentials.json.
    """
    c = _creds("tiktok")
    token   = c.get("access_token", "")
    open_id = c.get("open_id", "")
    if not token:
        print("  [TikTok] No access_token in social_credentials.json — skipping")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json; charset=UTF-8",
    }
    cutoff_dt = datetime.now() - timedelta(days=days)

    # Step 1: get our video list from TikTok
    videos: list[dict] = []
    cursor = 0
    for _page in range(5):   # up to 5 pages of 20 = 100 videos
        try:
            r = requests.post(
                "https://open.tiktokapis.com/v2/video/list/",
                headers=headers,
                params={
                    "fields": "id,create_time,statistics",
                },
                json={"max_count": 20, "cursor": cursor},
                timeout=20,
            )
            if r.status_code == 401:
                print("  [TikTok] Access token expired — refresh in social_credentials.json")
                break
            if not r.ok:
                print(f"  [TikTok] API {r.status_code}: {r.text[:120]}")
                break
            data     = r.json().get("data", {})
            batch    = data.get("videos", [])
            has_more = data.get("has_more", False)
            cursor   = data.get("cursor", 0)
            # Filter to our time window
            for v in batch:
                ts = v.get("create_time", 0)
                if ts and datetime.fromtimestamp(ts) >= cutoff_dt:
                    videos.append(v)
            if not has_more or not batch:
                break
        except Exception as e:
            print(f"  [TikTok] Request error: {e}")
            break

    if not videos:
        print("  [TikTok] No videos returned — posts may still be processing or token needs refresh")
        return []

    # Step 2: match to post_log by date (we don't have real IDs in post_log)
    posts = _load_posts("tiktok", days)
    post_dates = {p.get("posted_at", "")[:10] for p in posts}

    results = []
    for v in videos:
        ts    = v.get("create_time", 0)
        dt    = datetime.fromtimestamp(ts) if ts else None
        date_s = dt.strftime("%Y-%m-%d") if dt else ""
        stats  = v.get("statistics", {})
        results.append({
            "platform":  "tiktok",
            "post_id":   v.get("id", ""),
            "slot":      _guess_slot(dt.isoformat() if dt else ""),
            "posted_at": dt.isoformat() if dt else "",
            "views":     int(stats.get("play_count",    0)),
            "likes":     int(stats.get("digg_count",    0)),
            "comments":  int(stats.get("comment_count", 0)),
            "shares":    int(stats.get("share_count",   0)),
            "url":       f"https://tiktok.com/@boothop/video/{v.get('id', '')}",
        })

    total = sum(r["views"] for r in results)
    print(f"  [TikTok] {len(results)} videos, {total:,} total views")
    return results


# ── YouTube ───────────────────────────────────────────────────────────────────

def _fetch_youtube(posts: list[dict]) -> list[dict]:
    """Pull YouTube Shorts stats via YouTube Data API."""
    # Try social_credentials.json first, fall back to keys.env value
    yt_creds = _creds("youtube")
    api_key  = yt_creds.get("api_key", "") or YOUTUBE_API_KEY
    ids      = [p["video_id"] for p in posts if p.get("video_id")]

    if not ids:
        return []
    if not api_key:
        print("  [YouTube] No API key found — skipping")
        return []

    raw: dict[str, dict] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start:start + 50]
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "key":    api_key,
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

    total = sum(r["views"] for r in results)
    print(f"  [YouTube] {len(results)} posts, {total:,} total views")
    return results


# ── Instagram ─────────────────────────────────────────────────────────────────

def _fetch_instagram(posts: list[dict]) -> list[dict]:
    """Pull Instagram Reels stats via Instagram Graph API."""
    c     = _creds("instagram")
    token = c.get("access_token", "")
    if not token:
        print("  [Instagram] No access_token in social_credentials.json — skipping")
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
                    "access_token": token,
                },
                timeout=15,
            )
            if r.status_code == 401:
                print("  [Instagram] Token expired — run token refresh and update social_credentials.json")
                break
            r.raise_for_status()
            s = r.json()
            results.append({
                "platform":  "instagram",
                "post_id":   media_id,
                "slot":      p.get("slot"),
                "posted_at": p.get("posted_at", ""),
                "views":     int(s.get("views") or s.get("plays") or s.get("reach") or 0),
                "likes":     int(s.get("like_count",     0)),
                "comments":  int(s.get("comments_count", 0)),
                "shares":    int(s.get("shares_count",   0)),
            })
        except Exception as e:
            print(f"  [Instagram] {media_id}: {e}")

    total = sum(r["views"] for r in results)
    print(f"  [Instagram] {len(results)} posts, {total:,} total views")
    return results


# ── Memory + aggregation ──────────────────────────────────────────────────────

def _guess_slot(posted_at: str) -> int:
    try:
        h = datetime.fromisoformat(posted_at).hour
        if h < 11: return 1
        if h < 18: return 2
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


def _aggregate(posts_with_stats: list[dict], mem: list[dict]) -> dict:
    by_pillar:  defaultdict = defaultdict(list)
    by_slot:    defaultdict = defaultdict(list)
    by_opener:  defaultdict = defaultdict(list)
    by_weekday: defaultdict = defaultdict(list)
    enriched: list[dict]    = []

    for p in posts_with_stats:
        slot   = p.get("slot") or _guess_slot(p.get("posted_at", ""))
        posted = p.get("posted_at", "")
        date_s = posted[:10]
        views  = p.get("views", 0)
        entry  = _match_memory(date_s, slot, mem)

        pillar  = entry.get("pillar", "unknown")
        hook    = entry.get("hook", "")
        opener  = _hook_opener(hook)
        try:
            weekday = datetime.fromisoformat(posted).strftime("%A")
        except Exception:
            weekday = "Unknown"

        enriched.append({**p, "pillar": pillar, "hook": hook[:120],
                         "opener": opener, "weekday": weekday})
        by_pillar[pillar].append(views)
        by_slot[slot].append(views)
        by_opener[opener].append(views)
        by_weekday[weekday].append(views)

    def _avg(lst): return round(sum(lst) / len(lst)) if lst else 0
    def _rank(d):  return sorted(d.items(), key=lambda x: _avg(x[1]), reverse=True)

    return {
        "count":       len(enriched),
        "total_views": sum(p.get("views", 0) for p in enriched),
        "by_pillar":   {k: {"avg": _avg(v), "count": len(v), "total": sum(v)}
                        for k, v in _rank(by_pillar)},
        "by_slot":     {str(k): {"avg": _avg(v), "label": SLOT_LABELS.get(k, ""), "count": len(v)}
                        for k, v in _rank(by_slot)},
        "by_opener":   {k: {"avg": _avg(v), "count": len(v)}
                        for k, v in _rank(by_opener)[:15]},
        "by_weekday":  {k: {"avg": _avg(v), "count": len(v)}
                        for k, v in _rank(by_weekday)},
        "top_posts":   sorted(enriched, key=lambda x: x.get("views", 0), reverse=True)[:5],
    }


# ── Report ────────────────────────────────────────────────────────────────────

def _print_platform(name: str, agg: dict):
    if not agg or agg.get("count", 0) == 0:
        print(f"\n  {name}: no data this period")
        return
    sep = "─" * 60
    print(f"\n{'='*60}")
    print(f"  {name.upper()} — {agg['count']} posts — {agg['total_views']:,} total views")
    print(f"{'='*60}")

    print("\nPILLARS (avg views, ranked):")
    print(sep)
    for pillar, d in list(agg["by_pillar"].items())[:8]:
        bar = "█" * min(30, d["avg"] // 50)
        print(f"  {pillar:<22}  {d['avg']:>7,} avg  {d['count']:>2} posts  {bar}")

    print("\nSLOT TIMES:")
    print(sep)
    for s, d in agg["by_slot"].items():
        print(f"  Slot {s} ({d['label']:<20})  {d['avg']:>7,} avg  ({d['count']} posts)")

    print("\nTOP 3 HOOK OPENERS:")
    print(sep)
    for i, (opener, d) in enumerate(list(agg["by_opener"].items())[:3], 1):
        print(f"  {i}. '{opener}...'  {d['avg']:>7,} avg  ({d['count']} posts)")

    print("\nTOP 3 VIDEOS:")
    for p in agg["top_posts"][:3]:
        print(f"  {p.get('views', 0):>8,} views  [{p.get('pillar', '?')}]  {p.get('url', '')}")
        if p.get("hook"):
            print(f"              {p['hook'][:70]}")


def _print_cross(aggs: dict):
    all_pillars: set = set()
    for agg in aggs.values():
        all_pillars.update(agg.get("by_pillar", {}).keys())
    rows = []
    for pillar in all_pillars:
        pa = {pl: agg["by_pillar"][pillar]["avg"]
              for pl, agg in aggs.items()
              if pillar in agg.get("by_pillar", {})}
        if pa:
            overall = round(sum(pa.values()) / len(pa))
            rows.append((pillar, overall, pa))
    rows.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'='*60}")
    print("  CROSS-PLATFORM — consistent winners")
    print(f"{'='*60}")
    for pillar, overall, pa in rows[:8]:
        breakdown = "  ".join(f"{pl[:2].upper()}:{v:,}" for pl, v in pa.items())
        print(f"  {pillar:<22}  {overall:>7,} avg  [{breakdown}]")


# ── Save + adapt ──────────────────────────────────────────────────────────────

def _save_and_adapt(aggs: dict):
    PERF_LOG.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(), "platforms": aggs},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # Pillar weights come from TikTok first (that's where we want views), else YouTube
    primary = "tiktok" if "tiktok" in aggs and aggs["tiktok"].get("count", 0) > 0 else \
              "youtube" if "youtube" in aggs else None
    if primary:
        pillars = aggs[primary].get("by_pillar", {})
        if pillars:
            max_avg = max(d["avg"] for d in pillars.values()) or 1
            weights = {k: round(max(0.3, d["avg"] / max_avg), 2) for k, d in pillars.items()}
            (DATA / "pillar_weights.json").write_text(
                json.dumps(weights, indent=2), encoding="utf-8"
            )
            top3 = sorted(weights, key=weights.get, reverse=True)[:3]
            print(f"\n  [Adapt] Pillar weights updated from {primary} data")
            print(f"  [Adapt] Push these pillars this week: {', '.join(top3)}")
    print(f"  [Adapt] Full log → {PERF_LOG.name}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_review(days: int = 30):
    print(f"\n{'='*60}")
    print(f"  OTB WEEKLY PERFORMANCE REVIEW")
    print(f"  {datetime.now():%Y-%m-%d %H:%M}   |   last {days} days")
    print(f"{'='*60}\n")

    mem  = _load_memory()
    aggs: dict = {}

    print("[TikTok] Fetching from TikTok API...")
    tk = _fetch_tiktok(days)
    if tk:
        aggs["tiktok"] = _aggregate(tk, mem)

    print("\n[YouTube] Fetching from YouTube Data API...")
    yt_posts = _load_posts("youtube", days)
    yt = _fetch_youtube(yt_posts)
    if yt:
        aggs["youtube"] = _aggregate(yt, mem)

    print("\n[Instagram] Fetching from Instagram Graph API...")
    ig_posts = _load_posts("instagram", days)
    ig = _fetch_instagram(ig_posts)
    if ig:
        aggs["instagram"] = _aggregate(ig, mem)

    for platform, agg in aggs.items():
        _print_platform(platform, agg)

    if len(aggs) > 1:
        _print_cross(aggs)

    if not aggs:
        print("\nNo data — check social_credentials.json and API access.")
        return {}

    _save_and_adapt(aggs)
    _print_follower_growth()
    return aggs


def _print_follower_growth():
    """Print 7-day and 30-day follower deltas from follower_log.json."""
    log_path = DATA / "follower_log.json"
    if not log_path.exists():
        print("\n  [Followers] No follower_log.json yet — run follower_tracker.py daily to populate")
        return

    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if not log:
        return

    def _delta(platform: str, days: int) -> int | None:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        past   = next((e.get(platform) for e in log if e.get("date", "") <= cutoff and e.get(platform) is not None), None)
        now    = next((e.get(platform) for e in reversed(log) if e.get(platform) is not None), None)
        return (now - past) if (past is not None and now is not None) else None

    sep = "─" * 60
    print(f"\n{'='*60}")
    print("  FOLLOWER GROWTH")
    print(f"{'='*60}")
    print(sep)

    for platform, label in [("ig", "Instagram"), ("tiktok", "TikTok")]:
        now = next((e.get(platform) for e in reversed(log) if e.get(platform) is not None), None)
        if now is None:
            print(f"  {label:<12}  —  (no data)")
            continue
        d7  = _delta(platform, 7)
        d30 = _delta(platform, 30)
        def _fmt(d): return (f"+{d}" if d > 0 else str(d)) if d is not None else "n/a"
        print(f"  {label:<12}  {now:>8,} followers   7d: {_fmt(d7):<6}   30d: {_fmt(d30)}")

    # Best single day this review period
    week = [e for e in log[-8:] if e.get("ig") is not None]
    if len(week) >= 2:
        gains = [(week[i]["ig"] - week[i-1]["ig"], week[i]["date"]) for i in range(1, len(week))]
        best  = max(gains, key=lambda x: x[0])
        if best[0] > 0:
            print(f"\n  Best IG day this week: {best[1]}  (+{best[0]} followers)")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    run_review(args.days)
