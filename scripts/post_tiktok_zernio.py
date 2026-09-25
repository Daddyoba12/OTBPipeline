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
from config import DATA, ZERNIO_API_KEY, ZERNIO_ACCOUNT_ID, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

BASE_URL = "https://zernio.com/api/v1"


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [TikTok/Zernio] {msg}")


def _auth_headers(api_key: str = None) -> dict:
    return {
        "Authorization": f"Bearer {api_key or ZERNIO_API_KEY}",
        "Content-Type":  "application/json",
    }


def _last_post_time(company_slug: str = "boothop") -> datetime | None:
    log_path = DATA / "post_log.json"
    try:
        if log_path.exists():
            log = json.loads(log_path.read_text())
            entries = [e for e in log
                       if e.get("platform") == "tiktok"
                       and e.get("company_slug", "boothop") == company_slug]
            if entries:
                last = entries[-1].get("posted_at", "")
                return datetime.fromisoformat(last) if last else None
    except Exception:
        pass
    return None


def _check_rate_limit(min_gap_hours: float = 2.5, company_slug: str = "boothop") -> bool:
    last = _last_post_time(company_slug)
    if last is None:
        return True
    gap = (datetime.utcnow() - last).total_seconds() / 3600
    if gap < min_gap_hours:
        _log(f"Rate limit: last post {gap:.1f}h ago — need {min_gap_hours}h gap. Skipping.")
        return False
    return True


def _log_post(slot: int, publish_id: str, zernio_raw: dict | None = None,
              company_slug: str = "boothop"):
    log_path = DATA / "post_log.json"
    log_path.parent.mkdir(exist_ok=True)
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    entry = {
        "platform":     "tiktok",
        "slot":         slot,
        "publish_id":   publish_id,
        "posted_at":    datetime.utcnow().isoformat(),
        "company_slug": company_slug,
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


def _presign_upload(filename: str, api_key: str = None) -> tuple[str, str] | tuple[None, None]:
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


def _build_body(public_url: str, title: str, description: str, draft: bool = False,
                 account_id: str = None) -> dict:
    return {
        "publishNow": not draft,
        "title":      title,
        "content":    description,
        "platforms": [{"platform": "tiktok", "accountId": account_id or ZERNIO_ACCOUNT_ID}],
        "mediaItems": [{"type": "video", "url": public_url}],
        "tiktokSettings": {
            "privacy_level":             "PUBLIC_TO_EVERYONE",
            "allow_comment":             True,
            "allow_duet":                True,
            "allow_stitch":              True,
            "commercial_content_type":   "none",
            "content_preview_confirmed": True,
            "express_consent_given":     True,
            "media_type":                "video",
            "video_made_with_ai":        False,
            "draft":                     draft,
        },
    }


def _publish(public_url: str, title: str, description: str, slot: int = 0,
             api_key: str = None, account_id: str = None) -> str | None:
    """POST to Zernio /v1/posts. Returns Zernio post _id on success, None on failure."""
    import requests

    def _attempt(draft: bool = False) -> tuple[int, dict]:
        r = requests.post(
            f"{BASE_URL}/posts",
            headers=_auth_headers(api_key),
            json=_build_body(public_url, title, description, draft=draft, account_id=account_id),
            timeout=60,
        )
        data = r.json() if r.content else {}
        _log(f"Zernio response {r.status_code} (draft={draft}): {json.dumps(data)[:300]}")
        return r.status_code, data

    try:
        status_code, data = _attempt(draft=False)

        # Hard HTTP failures
        if status_code in (400, 401, 402, 403, 422, 429):
            from quota_alert import alert as _qa
            _qa("Zernio", status_code, data.get("error", "TikTok post blocked"))
            return None

        # Check platform-level status inside the response (Zernio returns 207 on partial failure)
        inner = data.get("data") or data.get("post") or data.get("result") or {}
        if isinstance(inner, list):
            inner = inner[0] if inner else {}

        plat_list = inner.get("platforms") or data.get("platforms") or []
        if isinstance(plat_list, list) and plat_list:
            plat_status = plat_list[0].get("status", "")
            plat_error  = plat_list[0].get("errorMessage", "")
            if plat_status == "failed":
                _log(f"TikTok platform failed: {plat_error}")
                # Capacity error — retry as draft so video lands in Creator Inbox
                if "capacity" in plat_error.lower() or "draft" in plat_error.lower():
                    _log("Retrying as draft -> TikTok Creator Inbox...")
                    status_code, data = _attempt(draft=True)
                    inner = data.get("data") or data.get("post") or data.get("result") or {}
                    if isinstance(inner, list):
                        inner = inner[0] if inner else {}
                    draft_id = inner.get("_id") or inner.get("id") or ""
                    if draft_id:
                        _log(f"Draft sent to TikTok Creator Inbox: {draft_id}")
                        try:
                            import requests as _rq
                            _rq.post(
                                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                json={"chat_id": TELEGRAM_CHAT_ID,
                                      "text": f"TikTok capacity full - Slot {slot} video sent to Creator Inbox as draft.\nOpen TikTok Creator Center > Drafts and post manually."},
                                timeout=10,
                            )
                        except Exception:
                            pass
                        return f"draft:{draft_id}"
                return None

        post_id = (
            inner.get("_id") or inner.get("id") or
            inner.get("postId") or inner.get("post_id") or
            inner.get("tiktokId") or inner.get("tiktok_id") or
            data.get("_id") or data.get("id") or ""
        )
        plat_tk_id = plat_list[0].get("tiktokId", "") if plat_list else ""
        result_id  = plat_tk_id or post_id
        _log(f"TikTok posted: zernio_id={post_id!r} tiktok_id={plat_tk_id!r}")
        return result_id or "queued"

    except Exception as e:
        _log(f"Publish failed: {e}")
        return None


def post_video(video_path: str, content: dict, slot: int = 0,
                api_key: str = None, account_id: str = None,
                company_slug: str = "boothop") -> str | None:
    """
    Upload video to TikTok via Zernio.
    Returns Zernio post _id on success, None on failure.

    api_key/account_id: optional per-client override. When omitted, falls back to
    BootHop's ZERNIO_API_KEY/ZERNIO_ACCOUNT_ID (this file's original single-tenant
    behaviour, unchanged). Other clients (e.g. D818) must always pass their own
    credentials explicitly — this default is BootHop-only and never resolves to
    another client's key.

    company_slug: tags the shared post_log.json entry and scopes the rate-limit
    check to that client, so two clients posting close together never throttle
    each other.
    """
    try:
        import requests  # noqa: F401 — confirm installed
    except ImportError:
        _log("requests not installed"); return None

    _api_key    = api_key or ZERNIO_API_KEY
    _account_id = account_id or ZERNIO_ACCOUNT_ID

    if not _api_key:
        _log("ZERNIO_API_KEY not set in keys.env"); return None

    if not _account_id:
        _log("ZERNIO_ACCOUNT_ID not set in keys.env"); return None

    if not _check_rate_limit(company_slug=company_slug):
        return None

    if not os.path.isfile(video_path):
        _log(f"Video not found: {video_path}"); return None

    title, description = _build_caption(content)
    filename = Path(video_path).name

    _log(f"Slot {slot} | '{title[:60]}...'")

    # Step 1 — presign
    upload_url, public_url = _presign_upload(filename, api_key=_api_key)
    if not upload_url:
        return None

    # Step 2 — upload
    if not _upload_file(upload_url, video_path):
        return None

    _log(f"Upload complete. publicUrl={public_url[:60]}...")

    # Step 3 — publish
    post_id = _publish(public_url, title, description, slot=slot,
                        api_key=_api_key, account_id=_account_id)
    if post_id:
        _log_post(slot, post_id, company_slug=company_slug)
        _log(f"Posted! zernio_id={post_id}")
        if post_id == "queued":
            _log("WARNING: Zernio returned no post ID — check pipeline_crash.log for full response")

    return post_id
