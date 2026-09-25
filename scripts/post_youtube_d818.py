"""
D818 Catering — YouTube Shorts poster.

Same resumable-upload flow as post_youtube.py (BootHop), but:
  - own OAuth token (YOUTUBE_TOKEN_D818), so it never touches BootHop's channel/token
  - own metadata (title/description/tags) built from client_profiles/d818.json,
    not BootHop's parcel-delivery copy

Run auth_youtube_d818.py once (browser login as the D818 channel's Google account)
before this can post.
"""

import json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import YOUTUBE_TOKEN_D818, YOUTUBE_CREDS, DATA

import requests

CLIENT_PROFILE = Path(__file__).parent.parent / "client_profiles" / "d818.json"


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [YouTube-D818] {msg}")


def _load_profile() -> dict:
    try:
        return json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_access_token() -> str | None:
    """Get a valid YouTube access token for the D818 channel, refreshing if needed."""
    if not YOUTUBE_TOKEN_D818.exists():
        _log(f"No token at {YOUTUBE_TOKEN_D818} — run auth_youtube_d818.py first")
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(
            str(YOUTUBE_TOKEN_D818),
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            YOUTUBE_TOKEN_D818.write_text(creds.to_json())
        return creds.token
    except Exception as e:
        _log(f"Token error: {e}")
    return None


def _build_metadata(content: dict) -> dict:
    """Build YouTube Shorts metadata from D818 content + client profile."""
    profile  = _load_profile()
    hook     = content.get("hook", "")
    lesson   = content.get("lesson", "")
    website  = profile.get("website", "https://d818.co.uk")
    hashtags = profile.get("hashtags") or ["#D818Catering", "#Jollof", "#WestAfricanFood"]

    title = hook[:60].strip() or "D818 Catering"

    description_parts = [hook]
    if lesson:
        description_parts.append(f"\n{lesson}")
    description_parts.append(f"\nVisit {website}, call, or email your order — we'll get it to you.")
    description_parts.append("\n\n#Shorts " + " ".join(hashtags[:8]))
    description = "".join(description_parts)[:5000]

    tags = [h.lstrip("#") for h in hashtags[:15]] or ["D818Catering", "WestAfricanFood", "Jollof"]

    return {
        "snippet": {
            "title":              title,
            "description":        description,
            "tags":               tags,
            "categoryId":         "22",  # People & Blogs
            "defaultLanguage":    "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids":             False,
            "license":                 "youtube",
        },
    }


def post_video(video_path: str, content: dict, slot: int = 0) -> str | None:
    """
    Upload video as a YouTube Short on D818's channel.
    Returns video_id on success, None on failure.
    """
    access_token = _get_access_token()
    if not access_token:
        return None

    if not Path(video_path).exists():
        _log(f"Video not found: {video_path}"); return None

    metadata = _build_metadata(content)
    title    = metadata["snippet"]["title"]
    _log(f"Uploading slot {slot} | '{title}'")

    file_size  = Path(video_path).stat().st_size
    chunk_size = 10 * 1024 * 1024  # 10MB chunks

    init_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(file_size),
        "X-Upload-Content-Type":   "video/mp4",
    }
    try:
        r = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/videos"
            "?uploadType=resumable&part=snippet,status",
            headers=init_headers,
            json=metadata,
            timeout=30,
        )
        r.raise_for_status()
        upload_url = r.headers.get("Location")
        if not upload_url:
            _log(f"No upload URL in response: {r.headers}"); return None
    except Exception as e:
        _log(f"Upload init failed: {e}"); return None

    _log(f"Uploading {file_size//1024}KB in {file_size//chunk_size+1} chunk(s)...")
    try:
        with open(video_path, "rb") as f:
            uploaded = 0
            while uploaded < file_size:
                chunk = f.read(chunk_size)
                end = uploaded + len(chunk) - 1
                chunk_headers = {
                    "Authorization":  f"Bearer {access_token}",
                    "Content-Length": str(len(chunk)),
                    "Content-Range":  f"bytes {uploaded}-{end}/{file_size}",
                    "Content-Type":   "video/mp4",
                }
                r = requests.put(upload_url, headers=chunk_headers, data=chunk, timeout=120)
                if r.status_code in (200, 201):
                    video_id = r.json().get("id")
                    if video_id:
                        _log(f"Uploaded! video_id={video_id}")
                        _log(f"URL: https://youtube.com/shorts/{video_id}")
                        _log_post(slot, video_id)
                        return video_id
                elif r.status_code == 308:
                    uploaded += len(chunk)  # resume — next chunk
                else:
                    _log(f"Chunk upload error {r.status_code}: {r.text[:200]}")
                    return None
    except Exception as e:
        _log(f"Upload error: {e}"); return None

    _log("Upload completed but no video_id received"); return None


def _log_post(slot: int, video_id: str):
    log_path = DATA / "post_log.json"
    log_path.parent.mkdir(exist_ok=True)
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    log.append({
        "platform":     "youtube",
        "slot":         slot,
        "video_id":     video_id,
        "url":          f"https://youtube.com/shorts/{video_id}",
        "posted_at":    datetime.utcnow().isoformat(),
        "company_slug": "d818",
    })
    log_path.write_text(json.dumps(log, indent=2))
