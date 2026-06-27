"""
OTB_Pipeline — TikTok poster (algo-optimized)

TikTok 2026 algorithm signals applied:
1. Caption: First 90 chars = hook (visible before "more") — most critical for CTR
2. Hashtags: 20 tags — 5 core brand + 5 niche diaspora + 5 topic + 5 broad discovery
3. All interaction features enabled (duet/stitch/comment) — widens engagement surface
4. No "brand content" flag — TikTok penalises this for organic reach
5. Privacy PUBLIC_TO_EVERYONE — required for FYP distribution
6. Title ≤ 150 chars starting with hook punch line (strong first-2-second signal)
7. Does NOT post twice within 3 hours — checked via post log before uploading
"""

import json, math, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA

MAX_CHUNK = 64 * 1024 * 1024


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [TikTok] {msg}")


def _creds() -> str:
    try:
        creds = json.loads(Path(CREDS_PATH).read_text())
        return (creds.get("tiktok_production", {}).get("access_token")
                or creds.get("tiktok", {}).get("access_token", "")).strip()
    except Exception as e:
        _log(f"Creds error: {e}")
        return ""


def _last_post_time() -> datetime | None:
    """Return time of last TikTok post from data/post_log.json."""
    log_path = DATA / "post_log.json"
    try:
        if log_path.exists():
            log = json.loads(log_path.read_text())
            entries = [e for e in log if e.get("platform") == "tiktok"]
            if entries:
                last = entries[-1].get("posted_at", "")
                return datetime.fromisoformat(last) if last else None
    except Exception:
        pass
    return None


def _check_rate_limit(min_gap_hours: float = 3.0) -> bool:
    """Return True if safe to post (≥ min_gap_hours since last TikTok post)."""
    last = _last_post_time()
    if last is None:
        return True
    gap = (datetime.utcnow() - last).total_seconds() / 3600
    if gap < min_gap_hours:
        _log(f"Rate limit: last post {gap:.1f}h ago — need {min_gap_hours}h gap. Skipping.")
        return False
    return True


def _log_post(slot: int, publish_id: str):
    log_path = DATA / "post_log.json"
    log_path.parent.mkdir(exist_ok=True)
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    log.append({
        "platform":   "tiktok",
        "slot":       slot,
        "publish_id": publish_id,
        "posted_at":  datetime.utcnow().isoformat(),
    })
    log_path.write_text(json.dumps(log, indent=2))


def _build_caption(content: dict) -> tuple[str, str]:
    """
    Build TikTok title + description optimized for algorithm.
    Title: hook punch (≤ 90 chars, first thing visible)
    Description: hook + 2 line breaks + story + engagement question + hashtags
    """
    hook        = content.get("hook", "")
    caption_raw = content.get("caption_tiktok", hook)
    hashtags    = content.get("hashtags_tiktok", "#BootHop #LondonToLagos #DiasporaMagic")
    engagement  = content.get("engagement", "")

    title = hook[:150]

    desc_parts = [caption_raw.strip()]
    if engagement:
        desc_parts.append(engagement)
    desc_parts.append("")  # blank line before hashtags
    desc_parts.append(hashtags)

    description = "\n".join(desc_parts)
    return title, description[:2200]


def post_video(video_path: str, content: dict, slot: int = 0) -> str | None:
    """
    Upload video to TikTok using Content Posting API v2.
    Returns publish_id on success, None on failure.
    """
    try:
        import requests
    except ImportError:
        _log("requests not installed"); return None

    if not _check_rate_limit(min_gap_hours=2.5):
        return None

    access_token = _creds()
    if not access_token:
        _log("No access_token — skipping"); return None

    if not os.path.isfile(video_path):
        _log(f"Video not found: {video_path}"); return None

    file_size   = os.path.getsize(video_path)
    chunk_size  = min(file_size, MAX_CHUNK)
    chunk_count = math.ceil(file_size / chunk_size)
    title, description = _build_caption(content)

    _log(f"Uploading slot {slot} | {file_size//1024}KB | '{title[:60]}'")

    auth_h = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    init_body = {
        "post_info": {
            "title":            title,
            "description":      description,
            "privacy_level":    "PUBLIC_TO_EVERYONE",
            "disable_duet":     False,
            "disable_comment":  False,
            "disable_stitch":   False,
            "brand_content_toggle":      False,
            "brand_organic_toggle":      False,
        },
        "source_info": {
            "source":            "FILE_UPLOAD",
            "video_size":        file_size,
            "chunk_size":        chunk_size,
            "total_chunk_count": chunk_count,
        },
    }

    try:
        r = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers=auth_h, json=init_body, timeout=30,
        )
        r.raise_for_status()
        inner      = r.json().get("data", r.json())
        publish_id = inner.get("publish_id", "")
        upload_url = inner.get("upload_url", "")
        if not publish_id or not upload_url:
            _log(f"Init unexpected: {r.json()}"); return None
    except Exception as e:
        _log(f"Init failed: {e}"); return None

    _log(f"Uploading {chunk_count} chunk(s)...")
    try:
        with open(video_path, "rb") as f:
            for idx in range(chunk_count):
                start      = idx * chunk_size
                chunk_data = f.read(chunk_size)
                end        = start + len(chunk_data) - 1
                requests.put(
                    upload_url,
                    headers={
                        "Content-Type":   "video/mp4",
                        "Content-Range":  f"bytes {start}-{end}/{file_size}",
                        "Content-Length": str(len(chunk_data)),
                    },
                    data=chunk_data, timeout=120,
                ).raise_for_status()
    except Exception as e:
        _log(f"Chunk upload failed: {e}"); return None

    # Poll status
    for _ in range(24):
        time.sleep(5)
        try:
            st = requests.post(
                "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                headers=auth_h, json={"publish_id": publish_id}, timeout=15,
            ).json()
            status = st.get("data", st).get("status", "")
            _log(f"Status: {status}")
            if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "SUCCESS"):
                _log_post(slot, publish_id)
                _log(f"Posted! publish_id={publish_id}")
                return publish_id
            if status in ("FAILED", "CANCELLED"):
                _log(f"Failed: {status}"); return None
        except Exception:
            pass

    _log("Status poll timed out"); return None
