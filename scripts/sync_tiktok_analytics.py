"""
OTB_Pipeline — TikTok analytics sync
Fetches view/like/comment counts for all posted TikTok videos and writes
them into data/performance_log.json so the pipeline can see what's working.

Requires the TikTok access token to have the 'video.list' scope.
If the scope is missing, run: python auth_tiktok.py (coming soon) or
re-authorise via the TikTok developer portal.

Run manually:  python scripts/sync_tiktok_analytics.py
Scheduled:     every day at 09:00 via Task Scheduler / Oracle cron
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA

import requests


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [TikTokAnalytics] {msg}")


def _creds() -> str:
    try:
        creds = json.loads(Path(CREDS_PATH).read_text())
        return (creds.get("tiktok_production", {}).get("access_token")
                or creds.get("tiktok", {}).get("access_token", "")).strip()
    except Exception as e:
        _log(f"Creds error: {e}")
        return ""


def _load_post_log() -> list:
    p = DATA / "post_log.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _load_perf_log() -> dict:
    p = DATA / "performance_log.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_perf_log(data: dict):
    (DATA / "performance_log.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def fetch_tiktok_video_stats(access_token: str) -> list[dict]:
    """
    Call TikTok /v2/video/list/ to get the creator's recent videos + stats.
    Returns list of dicts with keys: id, title, view_count, like_count, comment_count, share_count, create_time
    """
    url = "https://open.tiktokapis.com/v2/video/list/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    fields = "id,title,video_description,create_time,cover_image_url,share_url,view_count,like_count,comment_count,share_count,play_count"
    body = {"max_count": 20, "fields": fields}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=20)
        data = resp.json()

        if resp.status_code == 401:
            _log("401 Unauthorized — TikTok token expired or missing video.list scope")
            _log("Fix: re-authorise in TikTok developer portal to add video.list scope")
            return []

        if resp.status_code == 403:
            _log("403 Forbidden — access token lacks 'video.list' scope")
            _log("Fix: re-authorise app in TikTok developer portal with video.list scope")
            return []

        if "error" in data and data["error"].get("code") not in ("ok", None, ""):
            err = data["error"]
            _log(f"TikTok API error {err.get('code')}: {err.get('message')}")
            return []

        videos = data.get("data", {}).get("videos", [])
        _log(f"Fetched {len(videos)} videos from TikTok")
        return videos

    except Exception as e:
        _log(f"Request failed: {e}")
        return []


def sync():
    token = _creds()
    if not token:
        _log("No TikTok access token — skipping"); return

    videos = fetch_tiktok_video_stats(token)
    if not videos:
        _log("No video data returned — nothing to sync"); return

    # Index by create_time so we can match to post_log by approximate timestamp
    post_log = _load_post_log()
    tiktok_posts = [e for e in post_log if e.get("platform") == "tiktok"]

    perf = _load_perf_log()
    if "tiktok" not in perf:
        perf["tiktok"] = {}

    tiktok_perf = perf["tiktok"]
    total_views = 0
    total_likes = 0
    total_comments = 0
    enriched_posts = []

    for v in videos:
        vid_id      = str(v.get("id", ""))
        views       = v.get("view_count", 0) or v.get("play_count", 0) or 0
        likes       = v.get("like_count", 0)
        comments    = v.get("comment_count", 0)
        shares      = v.get("share_count", 0)
        title       = v.get("title", "")
        create_time = v.get("create_time", 0)  # unix timestamp

        total_views    += views
        total_likes    += likes
        total_comments += comments

        entry = {
            "video_id":    vid_id,
            "title":       title,
            "views":       views,
            "likes":       likes,
            "comments":    comments,
            "shares":      shares,
            "create_time": create_time,
            "synced_at":   datetime.utcnow().isoformat(),
        }
        enriched_posts.append(entry)
        _log(f"  {views:>6} views | {likes:>4} likes | {comments:>3} comments | {title[:55]}")

    video_count = len(enriched_posts)
    avg_views   = round(total_views / video_count, 1) if video_count else 0

    # Sort by views descending for top_posts
    enriched_posts.sort(key=lambda x: x["views"], reverse=True)

    tiktok_perf.update({
        "count":        video_count,
        "total_views":  total_views,
        "total_likes":  total_likes,
        "total_comments": total_comments,
        "avg_views":    avg_views,
        "top_posts":    enriched_posts[:5],
        "all_posts":    enriched_posts,
        "synced_at":    datetime.utcnow().isoformat(),
    })

    perf["tiktok"] = tiktok_perf
    _save_perf_log(perf)

    _log(f"Sync complete — {video_count} videos | avg {avg_views} views | {total_likes} total likes")

    # Print top 3 for quick visibility
    _log("Top 3 TikTok videos by views:")
    for p in enriched_posts[:3]:
        _log(f"  [{p['views']} views] {p['title'][:70]}")


if __name__ == "__main__":
    _log("=== TikTok analytics sync starting ===")
    sync()
    _log("=== Done ===")
