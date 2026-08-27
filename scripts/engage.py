"""
OTB_Pipeline — Engagement Bot
Runs every 2 hours via cron (Oracle) / Task Scheduler (Windows).
Fetches new comments on Instagram and YouTube, replies using Claude Haiku,
then keeps the replied-ID list so it never double-replies.

TikTok: comment reply API not publicly available — first comment only
(posted inline in pipeline.py right after upload).
"""

import json, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA, GEMINI_API_KEY, YOUTUBE_TOKEN

import requests

# ── Brand voice for Haiku ───────────────────────────────────────────────────────
BRAND_SYSTEM = """You are the BootHop community manager. BootHop is a peer-to-peer platform connecting UK and Nigeria — trusted travellers carry packages on journeys they're already making, enabling same-day delivery without courier fees.

Reply rules:
- British English, warm and real — never corporate or salesy
- 1-2 sentences MAX, always tight
- Sound like a real person in the community, not a brand account
- If someone asks about the service: mention "link in bio" or "boothop.com" naturally — don't push
- If someone shares a personal story: acknowledge it genuinely first
- If someone is negative: be gracious, invite them to DM
- Never open with "Great comment!" / "Thanks for sharing!" / "Absolutely!" — dive straight in
- No hashtags in replies ever
- Only use emojis if the original comment uses them"""

MAX_REPLIES_PER_RUN = 10   # safety cap per platform per 2h run
LOOKBACK_DAYS       = 7    # only engage on posts from last 7 days


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Engage] {msg}")


# ── Engagement log (tracks replied comment IDs) ─────────────────────────────────

def _load_log() -> dict:
    path = DATA / "engagement_log.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {
        "replied_ig": [],
        "replied_yt": [],
    }


def _save_log(log: dict):
    (DATA / "engagement_log.json").write_text(json.dumps(log, indent=2))


# ── Reply generation via Gemini Flash ──────────────────────────────────────────

def _generate_reply(comment_text: str, platform: str) -> str:
    if not GEMINI_API_KEY:
        _log("No GEMINI_API_KEY — cannot generate reply"); return ""
    try:
        combined = f"{BRAND_SYSTEM}\n\nPlatform: {platform}\nComment: {comment_text}\n\nWrite a reply."
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": combined}]}],
                "generationConfig": {"maxOutputTokens": 120, "temperature": 0.7},
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        _log(f"Haiku reply error: {e}"); return ""


# ── Post log helpers ────────────────────────────────────────────────────────────

def _recent_ids(platform: str, field: str) -> list[str]:
    """Return IDs for posts on `platform` in the last LOOKBACK_DAYS."""
    log_path = DATA / "post_log.json"
    if not log_path.exists():
        return []
    cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    ids: list[str] = []
    try:
        for entry in json.loads(log_path.read_text()):
            if entry.get("platform") != platform:
                continue
            try:
                posted_at = datetime.fromisoformat(entry.get("posted_at", "2000-01-01"))
            except ValueError:
                continue
            if posted_at > cutoff and entry.get(field):
                ids.append(entry[field])
    except Exception as e:
        _log(f"post_log read error: {e}")
    return ids


# ── Instagram engagement ────────────────────────────────────────────────────────

def _ig_creds() -> tuple[str, str]:
    try:
        c = json.loads(Path(CREDS_PATH).read_text())
        ig = c.get("instagram", {})
        return ig.get("access_token", "").strip(), ig.get("ig_user_id", "").strip()
    except Exception as e:
        _log(f"IG creds error: {e}"); return "", ""


def engage_instagram():
    token, ig_user_id = _ig_creds()
    if not token:
        _log("No IG credentials — skipping Instagram"); return

    media_ids = _recent_ids("instagram", "media_id")
    if not media_ids:
        _log("No recent IG posts to engage on"); return

    log          = _load_log()
    replied_ids  = set(log.get("replied_ig", []))
    sent_count   = 0
    base         = "https://graph.instagram.com/v21.0"

    for media_id in media_ids:
        if sent_count >= MAX_REPLIES_PER_RUN:
            break
        try:
            resp = requests.get(
                f"{base}/{media_id}/comments",
                params={"fields": "id,text,username,timestamp", "access_token": token},
                timeout=15,
            ).json()
            comments = resp.get("data", [])
        except Exception as e:
            _log(f"IG comments fetch error ({media_id}): {e}"); continue

        for c in comments:
            if sent_count >= MAX_REPLIES_PER_RUN:
                break
            cid      = c.get("id", "")
            text     = c.get("text", "").strip()
            username = c.get("username", "")
            if not cid or not text or cid in replied_ids:
                continue
            if "boothop" in username.lower():
                continue  # skip our own first comments

            _log(f"  IG @{username}: {text[:70]}")
            reply = _generate_reply(text, "Instagram")
            if not reply:
                continue

            try:
                pub = requests.post(
                    f"{base}/{cid}/replies",
                    params={"message": reply, "access_token": token},
                    timeout=15,
                ).json()
                if pub.get("id"):
                    _log(f"    → replied ✓")
                    replied_ids.add(cid)
                    sent_count += 1
                else:
                    _log(f"    → reply failed: {pub}")
            except Exception as e:
                _log(f"    → reply error: {e}")

    log["replied_ig"] = list(replied_ids)
    _save_log(log)
    _log(f"Instagram done — {sent_count} replies sent")


# ── YouTube engagement ──────────────────────────────────────────────────────────

def _yt_token() -> str | None:
    """Load YT access token, refreshing if expired. No scope restriction."""
    if not YOUTUBE_TOKEN.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        # from_authorized_user_file with no scopes = no scope validation, just loads + refreshes
        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN))
        if not creds.valid:
            if creds.refresh_token:
                creds.refresh(Request())
                YOUTUBE_TOKEN.write_text(creds.to_json())
            else:
                _log("YT token invalid and no refresh_token"); return None
        return creds.token
    except Exception as e:
        _log(f"YT token error: {e}"); return None


def engage_youtube():
    access_token = _yt_token()
    if not access_token:
        _log("No YT token — skipping YouTube"); return

    video_ids = _recent_ids("youtube", "video_id")
    if not video_ids:
        _log("No recent YT posts to engage on"); return

    log         = _load_log()
    replied_ids = set(log.get("replied_yt", []))
    sent_count  = 0
    base        = "https://www.googleapis.com/youtube/v3"
    headers     = {"Authorization": f"Bearer {access_token}"}

    for video_id in video_ids:
        if sent_count >= MAX_REPLIES_PER_RUN:
            break
        try:
            resp = requests.get(
                f"{base}/commentThreads",
                params={"part": "snippet", "videoId": video_id, "maxResults": 50, "order": "time"},
                headers=headers,
                timeout=15,
            ).json()
        except Exception as e:
            _log(f"YT comments fetch error ({video_id}): {e}"); continue

        if "error" in resp:
            err = resp["error"]
            if err.get("code") == 403:
                _log("YT comment access denied — token may need re-auth with youtube.force-ssl scope")
            else:
                _log(f"YT API error: {err}")
            break  # no point retrying other videos with same token

        for thread in resp.get("items", []):
            if sent_count >= MAX_REPLIES_PER_RUN:
                break
            thread_id = thread.get("id", "")
            top       = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            text      = top.get("textOriginal", "").strip()
            author    = top.get("authorDisplayName", "")
            if not thread_id or not text or thread_id in replied_ids:
                continue
            if "boothop" in author.lower():
                continue

            _log(f"  YT {author}: {text[:70]}")
            reply = _generate_reply(text, "YouTube")
            if not reply:
                continue

            try:
                pub = requests.post(
                    f"{base}/comments",
                    params={"part": "snippet"},
                    headers={**headers, "Content-Type": "application/json"},
                    json={"snippet": {"parentId": thread_id, "textOriginal": reply}},
                    timeout=15,
                ).json()
                if pub.get("id"):
                    _log(f"    → replied ✓")
                    replied_ids.add(thread_id)
                    sent_count += 1
                else:
                    _log(f"    → reply failed: {pub}")
            except Exception as e:
                _log(f"    → reply error: {e}")

    log["replied_yt"] = list(replied_ids)
    _save_log(log)
    _log(f"YouTube done — {sent_count} replies sent")


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _log("=== Engagement run starting ===")
    engage_instagram()
    engage_youtube()
    _log("=== Engagement run complete ===")
