"""
OTB_Pipeline — Instagram poster via Zernio API
For clients whose Instagram is connected through Zernio (e.g. D818), as opposed to
BootHop's native Meta Graph API integration in post_instagram.py.

api_key/account_id are REQUIRED and must be passed explicitly by the caller — this
file has no BootHop-style global default. Each client's Zernio credentials must stay
scoped to that client only.

Same shape as post_tiktok_zernio.py:
  1. POST /v1/media/presign  — get presigned upload URL
  2. PUT uploadUrl           — upload the MP4
  3. POST /v1/posts          — publish immediately to Instagram (Reel)
"""

import json, os, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA

BASE_URL = "https://zernio.com/api/v1"


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Instagram/Zernio] {msg}")


def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }


def _last_post_time(company_slug: str) -> datetime | None:
    log_path = DATA / "post_log.json"
    try:
        if log_path.exists():
            log = json.loads(log_path.read_text())
            entries = [e for e in log
                       if e.get("platform") == "instagram"
                       and e.get("company_slug", "") == company_slug]
            if entries:
                last = entries[-1].get("posted_at", "")
                return datetime.fromisoformat(last) if last else None
    except Exception:
        pass
    return None


def _check_rate_limit(company_slug: str, min_gap_hours: float = 2.5) -> bool:
    last = _last_post_time(company_slug)
    if last is None:
        return True
    gap = (datetime.utcnow() - last).total_seconds() / 3600
    if gap < min_gap_hours:
        _log(f"Rate limit: last post {gap:.1f}h ago — need {min_gap_hours}h gap. Skipping.")
        return False
    return True


def _log_post(slot: int, publish_id: str, company_slug: str, zernio_raw: dict | None = None):
    log_path = DATA / "post_log.json"
    log_path.parent.mkdir(exist_ok=True)
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    entry = {
        "platform":     "instagram",
        "slot":         slot,
        "publish_id":   publish_id,
        "posted_at":    datetime.utcnow().isoformat(),
        "company_slug": company_slug,
    }
    if zernio_raw:
        entry["zernio_response"] = zernio_raw
    log.append(entry)
    log_path.write_text(json.dumps(log, indent=2))


def _build_caption(content: dict) -> str:
    hook       = content.get("hook", "")
    caption    = content.get("caption_instagram", content.get("caption_tiktok", hook))
    hashtags   = content.get("hashtags_instagram", content.get("hashtags_tiktok", ""))
    engagement = content.get("engagement", "")

    parts = [caption.strip()]
    if engagement:
        parts.append(engagement)
    if hashtags:
        parts.append("")
        parts.append(hashtags)

    return "\n".join(parts)[:2200]


def _presign_upload(filename: str, api_key: str) -> tuple[str, str] | tuple[None, None]:
    """Returns (uploadUrl, publicUrl) or (None, None) on failure."""
    import requests
    try:
        r = requests.post(
            f"{BASE_URL}/media/presign",
            headers=_auth_headers(api_key),
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


def _build_body(public_url: str, content_text: str, account_id: str, draft: bool = False) -> dict:
    # Instagram publishes as a Reel (shareToFeed=true) by default under Zernio's
    # InstagramPlatformData schema — no platformSpecificData block is required for
    # that default behaviour. See https://zernio.com/openapi.json
    return {
        "publishNow": not draft,
        "content":    content_text,
        "platforms": [{"platform": "instagram", "accountId": account_id}],
        "mediaItems": [{"type": "video", "url": public_url}],
    }


def _publish(public_url: str, content_text: str, account_id: str, api_key: str,
             slot: int = 0) -> str | None:
    """POST to Zernio /v1/posts. Returns Zernio post _id on success, None on failure."""
    import requests

    try:
        r = requests.post(
            f"{BASE_URL}/posts",
            headers=_auth_headers(api_key),
            json=_build_body(public_url, content_text, account_id),
            timeout=60,
        )
        data = r.json() if r.content else {}
        _log(f"Zernio response {r.status_code}: {json.dumps(data)[:300]}")

        if r.status_code in (400, 401, 402, 403, 422, 429):
            try:
                from quota_alert import alert as _qa
                _qa("Zernio", r.status_code, data.get("error", "Instagram post blocked"))
            except Exception:
                pass
            return None

        inner = data.get("data") or data.get("post") or data.get("result") or {}
        if isinstance(inner, list):
            inner = inner[0] if inner else {}

        plat_list = inner.get("platforms") or data.get("platforms") or []
        if isinstance(plat_list, list) and plat_list:
            plat_status = plat_list[0].get("status", "")
            plat_error  = plat_list[0].get("errorMessage", "")
            if plat_status == "failed":
                _log(f"Instagram platform failed: {plat_error}")
                return None

        post_id = (
            inner.get("_id") or inner.get("id") or
            inner.get("postId") or inner.get("post_id") or
            data.get("_id") or data.get("id") or ""
        )
        plat_ig_id = plat_list[0].get("instagramId", "") if plat_list else ""
        result_id  = plat_ig_id or post_id
        _log(f"Instagram posted: zernio_id={post_id!r} instagram_id={plat_ig_id!r}")
        return result_id or "queued"

    except Exception as e:
        _log(f"Publish failed: {e}")
        return None


def post_video(video_path: str, content: dict, slot: int = 0, *,
                api_key: str, account_id: str, company_slug: str) -> str | None:
    """
    Upload video to Instagram (Reel) via Zernio.
    Returns Zernio post _id on success, None on failure.

    api_key, account_id, company_slug are required keyword-only args — this file
    has no default credentials, so a caller can never accidentally post using
    another client's Zernio workspace.
    """
    try:
        import requests  # noqa: F401 — confirm installed
    except ImportError:
        _log("requests not installed"); return None

    if not api_key:
        _log("No Zernio api_key supplied"); return None
    if not account_id:
        _log("No Zernio account_id supplied"); return None

    if not _check_rate_limit(company_slug):
        return None

    if not os.path.isfile(video_path):
        _log(f"Video not found: {video_path}"); return None

    caption  = _build_caption(content)
    filename = Path(video_path).name

    _log(f"Slot {slot} | '{caption[:60]}...'")

    # Step 1 — presign
    upload_url, public_url = _presign_upload(filename, api_key)
    if not upload_url:
        return None

    # Step 2 — upload
    if not _upload_file(upload_url, video_path):
        return None

    _log(f"Upload complete. publicUrl={public_url[:60]}...")

    # Step 3 — publish
    post_id = _publish(public_url, caption, account_id, api_key, slot=slot)
    if post_id:
        _log_post(slot, post_id, company_slug)
        _log(f"Posted! zernio_id={post_id}")
        if post_id == "queued":
            _log("WARNING: Zernio returned no post ID — check pipeline_crash.log for full response")

    return post_id
