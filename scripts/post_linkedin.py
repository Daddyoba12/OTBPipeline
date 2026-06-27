"""
OTB_Pipeline — LinkedIn poster (algo-optimized)

LinkedIn 2026 algorithm — what actually moves the needle:
1. COMMENTS are weighted 4x more than reactions — caption must end with a genuine question
2. Dwell time matters — long-form readable text (150-300 words) outperforms short captions
3. Line breaks every 2-3 sentences — LinkedIn rewards "scannable" posts that people read fully
4. NO links in caption body — LinkedIn demotes posts with external URLs in the text
   Solution: post the link in your FIRST COMMENT after posting (standard LinkedIn growth hack)
4. 3-5 hashtags only — more than 5 actually hurts reach on LinkedIn
5. Native video outperforms image posts 3x — we post the slot video as native LinkedIn video
6. Weekdays only — LinkedIn is essentially dead on weekends (Sat/Sun → skip)
7. Best posting windows: 7-9am or 11am-1pm on Tue/Wed/Thu
   Slot 1 (7am) and Slot 2 (12pm) are ideal LinkedIn windows
8. B2B angle — BootHop is positioned as a business logistics solution, not a consumer app
9. First line = hook visible before "see more" (most critical for feed stop)
10. After posting: reply to own post with website URL (drives traffic without algo penalty)
"""

import json, os, sys, time
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA, ANTHROPIC_API_KEY

import requests


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [LinkedIn] {msg}")


def _is_weekday() -> bool:
    return date.today().weekday() < 5  # Mon=0 ... Fri=4


def _creds() -> tuple[str, str]:
    try:
        c = json.loads(Path(CREDS_PATH).read_text())
        li = c.get("linkedin", {})
        return li.get("access_token", "").strip(), li.get("person_urn", "").strip()
    except Exception as e:
        _log(f"Creds error: {e}"); return "", ""


def _auto_refresh(access_token: str, person_urn: str) -> tuple[str, str]:
    """Auto-refresh LinkedIn token if needed (token lasts 60 days)."""
    try:
        c = json.loads(Path(CREDS_PATH).read_text())
        li = c.get("linkedin", {})
        refresh = li.get("refresh_token", "")
        if not refresh:
            return access_token, person_urn
        from datetime import datetime as _dt, timedelta
        issued = li.get("issued_at", "")
        expires = li.get("expires_in", 5184000)
        if issued:
            expiry = _dt.fromisoformat(issued) + timedelta(seconds=expires)
            if (_dt.now() - expiry).total_seconds() < 7 * 86400:
                return access_token, person_urn
        resp = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={"grant_type": "refresh_token", "refresh_token": refresh,
                  "client_id": li.get("client_id",""), "client_secret": li.get("client_secret","")},
            timeout=20,
        ).json()
        if "access_token" in resp:
            li["access_token"] = resp["access_token"]
            li["issued_at"] = _dt.now().isoformat()
            if resp.get("refresh_token"):
                li["refresh_token"] = resp["refresh_token"]
            c["linkedin"] = li
            Path(CREDS_PATH).write_text(json.dumps(c, indent=2))
            _log("Token refreshed")
            return resp["access_token"], person_urn
    except Exception:
        pass
    return access_token, person_urn


def _build_linkedin_caption(content: dict) -> str:
    """
    Build LinkedIn caption optimized for algorithm.
    Structure:
      Line 1: Bold hook (visible before "see more") — B2B angle, not consumer
      Gap
      Problem paragraph (2-3 sentences, line breaks, very readable)
      Solution paragraph (how BootHop solved it — business framing)
      Insight line (the lesson rephrased as a business insight)
      Gap
      CTA question (drives comments — algo multiplier)
      Gap
      3-5 hashtags
    NO website URL — goes in first comment after posting.
    """
    hook       = content.get("hook", "")
    problem    = content.get("problem", "")
    stakes     = content.get("stakes", "")
    resolution = content.get("resolution", "")
    lesson     = content.get("lesson", "")
    pillar     = content.get("pillar", "community")
    engagement = content.get("engagement", "What's your experience with international shipping?")

    # B2B reframe of the hook
    b2b_hook = (
        f"Most businesses don't know this about the diaspora logistics corridor.\n"
        f"\n"
        f"{problem}\n"
        f"\n"
        f"{stakes}\n"
        f"\n"
        f"{resolution}\n"
        f"\n"
        f"💡 {lesson}\n"
        f"\n"
        f"{engagement}\n"
        f"\n"
        f"#BootHop #Logistics #DiasporaCommerce #SameDayDelivery #SME"
    )

    return b2b_hook[:3000]


def _post_comment(post_urn: str, access_token: str, person_urn: str, comment: str) -> bool:
    """Post a comment on your own LinkedIn post — used to add the website URL."""
    try:
        r = requests.post(
            "https://api.linkedin.com/v2/socialActions/{}/comments".format(
                requests.utils.quote(post_urn, safe="")
            ),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json={
                "actor": person_urn,
                "message": {"text": comment},
            },
            timeout=15,
        )
        return r.status_code in (200, 201)
    except Exception as e:
        _log(f"Comment post failed: {e}")
        return False


def _log_post(slot: int, post_urn: str):
    log_path = DATA / "post_log.json"
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    log.append({"platform": "linkedin", "slot": slot, "post_urn": post_urn,
                 "posted_at": datetime.utcnow().isoformat()})
    log_path.write_text(json.dumps(log, indent=2))


def post_video(video_path: str, content: dict, slot: int = 0) -> str | None:
    """
    Post native video to LinkedIn with B2B caption.
    Returns post URN on success, None on failure.
    LinkedIn only fires on weekdays — returns None silently on weekends.
    """
    if not _is_weekday():
        _log("Weekend — LinkedIn skipped (algorithm rewards weekday-only posting).")
        return None

    access_token, person_urn = _creds()
    if not access_token or not person_urn:
        _log("No LinkedIn credentials — skipping"); return None

    access_token, person_urn = _auto_refresh(access_token, person_urn)

    if not os.path.isfile(video_path):
        _log(f"Video not found: {video_path}"); return None

    caption = _build_linkedin_caption(content)
    file_size = os.path.getsize(video_path)
    _log(f"Posting slot {slot} | {file_size//1024}KB")

    auth_h = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    # Step 1: Register upload
    try:
        r = requests.post(
            "https://api.linkedin.com/v2/assets?action=registerUpload",
            headers=auth_h,
            json={
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
                    "owner": person_urn,
                    "serviceRelationships": [
                        {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                    ],
                }
            },
            timeout=30,
        )
        r.raise_for_status()
        reg = r.json()
        upload_url = reg["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = reg["value"]["asset"]
    except Exception as e:
        _log(f"Register upload failed: {e}"); return None

    # Step 2: Upload video bytes
    _log("Uploading video...")
    try:
        with open(video_path, "rb") as f:
            requests.put(
                upload_url,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/octet-stream"},
                data=f.read(), timeout=300,
            ).raise_for_status()
    except Exception as e:
        _log(f"Video upload failed: {e}"); return None

    # Step 3: Create UGC post (NO link in caption — link goes in comment)
    _log("Creating post...")
    try:
        r = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=auth_h,
            json={
                "author": person_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": caption},
                        "shareMediaCategory": "VIDEO",
                        "media": [{
                            "status": "READY",
                            "description": {"text": content.get("lesson", "")[:200]},
                            "media": asset_urn,
                            "title": {"text": content.get("hook", "")[:100]},
                        }],
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
            timeout=30,
        )
        r.raise_for_status()
        post_urn = r.json().get("id", "")
    except Exception as e:
        _log(f"UGC post failed: {e}"); return None

    if not post_urn:
        _log("No post URN returned"); return None

    _log(f"Posted! URN: {post_urn}")

    # Step 4: Post website URL in first comment (LinkedIn growth hack — link in comment avoids algo penalty)
    time.sleep(3)
    comment_text = (
        "📦 Same-day delivery by trusted travellers already making the journey.\n"
        "Book a delivery or list your next trip → https://boothop.com"
    )
    if _post_comment(post_urn, access_token, person_urn, comment_text):
        _log("First comment with link posted ✅")
    else:
        _log("First comment failed (non-critical)")

    _log_post(slot, post_urn)
    return post_urn
