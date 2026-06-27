"""
OTB_Pipeline — Instagram Reels poster (algo-optimized)

Instagram 2026 algorithm signals applied:
1. media_type=REELS (not VIDEO) — gets Reels tab distribution not just feed
2. share_to_feed=true — appears in both Reels tab AND follower feed (2x surface)
3. Caption: First 125 chars = hook punch (visible before "more" in feed)
   After that: story sentences + double line break + hashtags
4. Hashtags: 20-25 tags — mix of 5 mega (10M+) + 8 mid (1-10M) + 7 micro (<1M) + 5 location
   In caption body (not comment) — Instagram API puts them in caption
5. Cover frame: first frame of video (ensure it's visually strong — handled at render time)
6. Best slots: 12pm (slot 2) and 6pm (slot 3) for IG — 7am and 9pm also fine
7. Upload via catbox.moe temporary host (proven approach from BootHop BD)
"""

import json, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA

import requests


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Instagram] {msg}")


def _creds() -> tuple[str, str]:
    try:
        c = json.loads(Path(CREDS_PATH).read_text())
        ig = c.get("instagram", {})
        return ig.get("access_token", "").strip(), ig.get("ig_user_id", "").strip()
    except Exception as e:
        _log(f"Creds error: {e}"); return "", ""


def _log_post(slot: int, media_id: str):
    log_path = DATA / "post_log.json"
    log_path.parent.mkdir(exist_ok=True)
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    log.append({
        "platform": "instagram",
        "slot":     slot,
        "media_id": media_id,
        "posted_at": datetime.utcnow().isoformat(),
    })
    log_path.write_text(json.dumps(log, indent=2))


def _build_caption(content: dict) -> str:
    """
    Build IG caption optimized for algorithm:
    - First 125 chars visible without "more" — must hook immediately
    - Story in 3-4 sentences
    - Double line break before hashtags (standard IG algo-friendly format)
    """
    caption_raw = content.get("caption_instagram", content.get("hook", ""))
    hashtags    = content.get("hashtags_instagram", "#BootHop #LondonToLagos #DiasporaMagic")
    engagement  = content.get("engagement", "")

    parts = [caption_raw.strip()]
    if engagement:
        parts.append(f"\n{engagement}")
    parts.append(f"\n\n{hashtags}")

    return "".join(parts)[:2200]


def _upload_to_host(video_path: str) -> str | None:
    """Upload video to catbox.moe for temporary hosting (proven BootHop BD approach)."""
    _log("Uploading to catbox.moe...")
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (Path(video_path).name, f, "video/mp4")},
                timeout=120,
            )
        url = r.text.strip()
        if url.startswith("https://"):
            _log(f"Hosted: {url}")
            return url
        _log(f"catbox error: {url}")
    except Exception as e:
        _log(f"catbox upload failed: {e}")
    return None


def post_video(video_path: str, content: dict, slot: int = 0) -> str | None:
    """
    Post video as Instagram Reel.
    Returns media_id on success, None on failure.
    """
    access_token, ig_user_id = _creds()
    if not access_token or not ig_user_id:
        _log("No credentials — skipping"); return None

    video_url = _upload_to_host(video_path)
    if not video_url:
        return None

    caption = _build_caption(content)
    base_url = f"https://graph.instagram.com/v21.0"

    _log("Creating Reels container...")
    try:
        r = requests.post(
            f"{base_url}/{ig_user_id}/media",
            data={
                "media_type":    "REELS",
                "video_url":     video_url,
                "caption":       caption,
                "share_to_feed": "true",   # appears in feed AND reels tab
                "access_token":  access_token,
            },
            timeout=30,
        )
        data = r.json()
    except Exception as e:
        _log(f"Container create failed: {e}"); return None

    if "error" in data:
        _log(f"Container error: {data['error']}"); return None

    container_id = data.get("id")
    if not container_id:
        _log(f"No container_id in response: {data}"); return None

    _log(f"Container: {container_id} — polling...")

    # Poll until FINISHED (usually 30-90 seconds for Reels)
    for attempt in range(40):
        time.sleep(10)
        try:
            st = requests.get(
                f"{base_url}/{container_id}",
                params={"fields": "status_code,status", "access_token": access_token},
                timeout=15,
            ).json()
            status = st.get("status_code", "")
            _log(f"Container status: {status}")
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                _log(f"Container failed: {status} — {st.get('status')}"); return None
        except Exception:
            pass

    _log("Publishing Reel...")
    try:
        pub = requests.post(
            f"{base_url}/{ig_user_id}/media_publish",
            params={"creation_id": container_id, "access_token": access_token},
            timeout=30,
        ).json()
    except Exception as e:
        _log(f"Publish failed: {e}"); return None

    if "error" in pub:
        _log(f"Publish error: {pub['error']}"); return None

    media_id = str(pub.get("id", ""))
    if media_id:
        _log_post(slot, media_id)
        _log(f"Reel posted! media_id={media_id}")
    return media_id or None
