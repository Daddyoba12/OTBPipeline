"""
OTB_Pipeline — YouTube Shorts poster (algo-optimized)

YouTube Shorts 2026 algorithm signals applied:
1. Title: keyword-first, question or number format, ≤ 60 chars — primary discovery signal
2. Description: first 100 chars are keyword-rich (search index weight)
   Include #Shorts tag in description — auto-marks for Shorts shelf
3. Tags: 10-15 specific, NOT generic ("diaspora delivery uk" > "delivery")
4. Category: 22 (People & Blogs) or 19 (Travel & Events) — matched to pillar
5. Made for Kids: false — adults only, needed for monetisation eligibility
6. License: youtube — standard, required for Shorts distribution
7. Video: 9:16, 1080x1920, ≤ 60s — auto-detected as Short by YouTube
8. Post on slots 1 (7am) and 3 (6pm) — YouTube Shorts peaks 12pm and 6-9pm UK
9. selfDeclaredMadeForKids: false — explicitly set for safe mode compliance
"""

import json, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import YOUTUBE_TOKEN, YOUTUBE_CREDS, DATA

import requests


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [YouTube] {msg}")


def _get_access_token() -> str | None:
    """Get a valid YouTube access token, refreshing if needed."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(
            str(YOUTUBE_TOKEN),
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            YOUTUBE_TOKEN.write_text(creds.to_json())
        return creds.token
    except Exception as e:
        _log(f"Token error: {e}")
    return None


def _build_metadata(content: dict) -> dict:
    """Build YouTube video metadata optimized for Shorts algorithm."""
    hook        = content.get("hook", "")
    lesson      = content.get("lesson", "")
    pillar      = content.get("pillar", "community")
    yt_title    = content.get("youtube_title", hook[:60])
    yt_desc_raw = content.get("youtube_description", "")
    tags        = content.get("youtube_tags", ["BootHop", "diaspora delivery"])
    category_id = str(content.get("youtube_category", 22))
    engagement  = content.get("engagement", "")

    # Title: max 60 chars, keyword-first
    title = yt_title[:60].strip()

    # Description: keyword-rich first 100 chars, then full text, then #Shorts
    description_parts = []
    if yt_desc_raw:
        description_parts.append(yt_desc_raw.strip())
    if lesson:
        description_parts.append(f"\n💡 {lesson}")
    if engagement:
        description_parts.append(f"\n{engagement}")
    description_parts.append("\nBoothop.com — same-day delivery by trusted travellers.")
    description_parts.append("\n\n#Shorts #BootHop #LondonToLagos #DiasporaMagic #SameDayDelivery")

    description = "".join(description_parts)[:5000]

    return {
        "snippet": {
            "title":              title,
            "description":        description,
            "tags":               tags[:15],
            "categoryId":         category_id,
            "defaultLanguage":    "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus":             "public",
            "selfDeclaredMadeForKids":   False,
            "madeForKids":               False,
            "license":                   "youtube",
        },
    }


def post_video(video_path: str, content: dict, slot: int = 0) -> str | None:
    """
    Upload video as YouTube Short.
    Returns video_id on success, None on failure.
    """
    if not YOUTUBE_TOKEN.exists():
        _log("No YouTube token — skipping"); return None

    access_token = _get_access_token()
    if not access_token:
        _log("Could not get access token"); return None

    if not Path(video_path).exists():
        _log(f"Video not found: {video_path}"); return None

    metadata = _build_metadata(content)
    title    = metadata["snippet"]["title"]
    _log(f"Uploading slot {slot} | '{title}'")

    file_size = Path(video_path).stat().st_size
    chunk_size = 10 * 1024 * 1024  # 10MB chunks

    # Step 1: Initiate resumable upload
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

    # Step 2: Upload file in chunks
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
                    video_data = r.json()
                    video_id = video_data.get("id")
                    if video_id:
                        _log(f"Uploaded! video_id={video_id}")
                        _log(f"URL: https://youtube.com/shorts/{video_id}")
                        _log_post(slot, video_id)
                        return video_id
                elif r.status_code == 308:
                    # Resume incomplete — next chunk
                    uploaded += len(chunk)
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
        "platform": "youtube",
        "slot":     slot,
        "video_id": video_id,
        "url":      f"https://youtube.com/shorts/{video_id}",
        "posted_at": datetime.utcnow().isoformat(),
    })
    log_path.write_text(json.dumps(log, indent=2))
