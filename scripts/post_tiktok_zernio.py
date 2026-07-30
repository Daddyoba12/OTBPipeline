"""
OTB_Pipeline — TikTok poster via Zernio API
Replaces direct TikTok OAuth with Zernio's managed auth.

Same public signature as post_tiktok.py:
    post_video(video_path, content, slot) -> publish_id | None

Flow:
  1. POST /v1/media/presign  — get presigned upload URL
  2. PUT uploadUrl           — upload the MP4
  3. POST /v1/posts          — publish immediately to TikTok
"""

import json, os, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA, ZERNIO_API_KEY, ZERNIO_ACCOUNT_ID

BASE_URL = "https://zernio.com/api/v1"


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [TikTok/Zernio] {msg}")


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {ZERNIO_API_KEY}",
        "Content-Type":  "application/json",
    }


def _last_post_time() -> datetime | None:
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


def _check_rate_limit(min_gap_hours: float = 2.5) -> bool:
    last = _last_post_time()
    if last is None:
        return True
    gap = (datetime.utcnow() - last).total_seconds() / 3600
    if gap < min_gap_hours:
        _log(f"Rate limit: last post {gap:.1f}h ago — need {min_gap_hours}h gap. Skipping.")
        return False
    return True


def _log_post(slot: int, publish_id: str, zernio_raw: dict | None = None):
    log_path = DATA / "post_log.json"
    log_path.parent.mkdir(exist_ok=True)
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    entry = {
        "platform":   "tiktok",
        "slot":       slot,
        "publish_id": publish_id,
        "posted_at":  datetime.utcnow().isoformat(),
    }
    if zernio_raw:
        entry["zernio_response"] = zernio_raw
    log.append(entry)
    log_path.write_text(json.dumps(log, indent=2))


def _build_caption(content: dict) -> tuple[str, str]:
    hook        = content.get("hook", "")
    caption_raw = content.get("caption_tiktok", hook)
    hashtags    = content.get("hashtags_tiktok", "#BootHop #LondonToLagos #DiasporaMagic")
    engagement  = content.get("engagement", "")

    title = hook[:150]

    desc_parts = [caption_raw.strip()]
    if engagement:
        desc_parts.append(engagement)
    desc_parts.append("")
    desc_parts.append(hashtags)

    description = "\n".join(desc_parts)
    return title, description[:2200]


def _presign_upload(filename: str) -> tuple[str, str] | tuple[None, None]:
    """Returns (uploadUrl, publicUrl) or (None, None) on failure."""
    import requests
    try:
        r = requests.post(
            f"{BASE_URL}/media/presign",
            headers=_auth_headers(),
            json={"filename": filename, "contentType": "video/mp4"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data["uploadUrl"], data["publicUrl"]
    except Exception as e:
        _log(f"Presign failed: {e}")
        return None, None


def _upload_file(upload_url: str, video_path: str) -> bool:
    """PUT the raw MP4 bytes to the presigned URL."""
    import requests
    file_size = os.path.getsize(video_path)
    _log(f"Uploading {file_size // 1024}KB to presigned URL...")
    try:
        with open(video_path, "rb") as f:
            r = requests.put(
                upload_url,
                data=f,
                headers={
                    "Content-Type":   "video/mp4",
                    "Content-Length": str(file_size),
                },
                timeout=300,
            )
            r.raise_for_status()
        return True
    except Exception as e:
        _log(f"Upload failed: {e}")
        return False


def _publish(public_url: str, title: str, description: str) -> str | None:
    """POST to Zernio /v1/posts. Returns Zernio post _id on success."""
    import requests
    body = {
        "publishNow": True,
        "title":      title,
        "content":    description,
        "platforms": [
            {
                "platform":  "tiktok",
                "accountId": ZERNIO_ACCOUNT_ID,
            }
        ],
        "mediaItems": [
            {
                "type": "video",
                "url":  public_url,
            }
        ],
        "tiktokSettings": {
            "privacy_level":            "PUBLIC_TO_EVERYONE",
            "allow_comment":            True,
            "allow_duet":               True,
            "allow_stitch":             True,
            "commercial_content_type":  "none",
            "content_preview_confirmed": True,
            "express_consent_given":    True,
            "media_type":               "video",
            "video_made_with_ai":       False,
        },
    }
    try:
        r = requests.post(
            f"{BASE_URL}/posts",
            headers=_auth_headers(),
            json=body,
            timeout=60,
        )
        if r.status_code in (429, 402, 403):
            from quota_alert import alert as _qa
            _qa("Zernio", r.status_code, "TikTok post blocked")
        data = r.json() if r.content else {}
        # Log full raw response — helps diagnose "queued" fallback vs real post IDs
        _log(f"Zernio response {r.status_code}: {json.dumps(data)}")

        # Hard failures — Zernio explicitly rejected the post
        if r.status_code in (400, 401, 402, 403, 422, 429):
            from quota_alert import alert as _qa
            _qa("Zernio", r.status_code, data.get("error", "TikTok post blocked"))
            return None

        # 2xx → Zernio accepted the post. Walk all known ID field names.
        inner = data.get("data") or data.get("post") or data.get("result") or {}
        if isinstance(inner, list):
            inner = inner[0] if inner else {}
        post_id = (
            data.get("_id") or data.get("id") or
            data.get("postId") or data.get("post_id") or
            data.get("tiktokId") or data.get("tiktok_id") or
            inner.get("_id") or inner.get("id") or
            inner.get("postId") or inner.get("post_id") or
            inner.get("tiktokId") or inner.get("tiktok_id") or ""
        )
        status = (
            data.get("status") or data.get("state") or data.get("publishStatus") or
            inner.get("status") or inner.get("state") or inner.get("publishStatus") or ""
        )
        _log(f"Zernio post accepted: id={post_id!r} status={status!r} keys={list(data.keys())}")
        return post_id or status or "queued"
    except Exception as e:
        _log(f"Publish failed: {e}")
        return None


def post_video(video_path: str, content: dict, slot: int = 0) -> str | None:
    """
    Upload video to TikTok via Zernio.
    Returns Zernio post _id on success, None on failure.
    """
    try:
        import requests  # noqa: F401 — confirm installed
    except ImportError:
        _log("requests not installed"); return None

    if not ZERNIO_API_KEY:
        _log("ZERNIO_API_KEY not set in keys.env"); return None

    if not ZERNIO_ACCOUNT_ID:
        _log("ZERNIO_ACCOUNT_ID not set in keys.env"); return None

    if not _check_rate_limit():
        return None

    if not os.path.isfile(video_path):
        _log(f"Video not found: {video_path}"); return None

    title, description = _build_caption(content)
    filename = Path(video_path).name

    _log(f"Slot {slot} | '{title[:60]}...'")

    # Step 1 — presign
    upload_url, public_url = _presign_upload(filename)
    if not upload_url:
        return None

    # Step 2 — upload
    if not _upload_file(upload_url, video_path):
        return None

    _log(f"Upload complete. publicUrl={public_url[:60]}...")

    # Step 3 — publish
    post_id = _publish(public_url, title, description)
    if post_id:
        _log_post(slot, post_id)
        _log(f"Posted! zernio_id={post_id}")
        if post_id == "queued":
            _log("WARNING: Zernio returned no post ID — check pipeline_crash.log for full response")

    return post_id
