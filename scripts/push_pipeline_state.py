"""
OTB Pipeline — Supabase cloud sync
Called by pipeline.py after render and by telegram_commander.py during approval poll.

push_slot_state()    — upload videos + upsert slot row
push_global_status() — update slot=0 row with pipeline-wide status
clear_slot_pending() — mark slot no longer awaiting approval
poll_pending_commands() — return unexecuted commands for a slot
mark_command_done()  — mark command executed
"""

import json, sys, time
from datetime import datetime
from pathlib import Path

import requests

SUPABASE_URL = "https://zwgngbzbdvnrdnanjded.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp3Z25nYnpiZHZucmRuYW5qZGVkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5NTA0NSwiZXhwIjoyMDkwODcxMDQ1fQ"
    ".jP_Ukh4Dwlxfiei5tyHblJ0psgCXntDwnnZBRQch9zw"
)
BUCKET = "promo-videos"

_HDR = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates",
}


def _rest(method: str, path: str, **kwargs) -> requests.Response | None:
    try:
        url = f"{SUPABASE_URL}/rest/v1/{path}"
        r = requests.request(method, url, headers=_HDR, timeout=20, **kwargs)
        return r
    except Exception as e:
        print(f"[Supabase] REST error: {e}")
        return None


def _upload_video(local_path: str, storage_key: str) -> str:
    """Upload video to Supabase storage bucket. Returns public URL or ''."""
    p = Path(local_path)
    if not p.exists():
        return ""
    size_mb = p.stat().st_size / 1_048_576
    print(f"[Supabase] Uploading {p.name} ({size_mb:.1f} MB)…")
    try:
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{storage_key}"
        with open(local_path, "rb") as f:
            r = requests.post(
                upload_url,
                headers={
                    "apikey":        SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type":  "video/mp4",
                    "x-upsert":      "true",
                },
                data=f,
                timeout=600,
            )
        if r.ok:
            pub_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{storage_key}"
            print(f"[Supabase] Uploaded → {pub_url[:80]}")
            return pub_url
        print(f"[Supabase] Upload failed {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[Supabase] Upload error: {e}")
    return ""


def push_slot_state(
    slot: int,
    content: dict,
    v1_path: str = "",
    v2_path: str = "",
    pending_approval: bool = True,
) -> bool:
    """Upsert slot row. Uploads V1/V2 videos to Supabase storage first."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    v1_url = v2_url = ""

    if v1_path:
        v1_url = _upload_video(v1_path, f"pipeline/slot{slot}_v1_{ts}.mp4")
    if v2_path:
        v2_url = _upload_video(v2_path, f"pipeline/slot{slot}_v2_{ts}.mp4")

    row = {
        "slot":               slot,
        "hook":               content.get("hook",               ""),
        "hook_v2":            content.get("hook_v2",            ""),
        "lesson":             content.get("lesson",             ""),
        "lesson_v2":          content.get("lesson_v2",          ""),
        "problem":            content.get("problem",            ""),
        "stakes":             content.get("stakes",             ""),
        "resolution":         content.get("resolution",         ""),
        "rendered_at":        content.get("rendered_at",        datetime.now().isoformat()),
        "caption_tiktok":     content.get("caption_tiktok",    ""),
        "caption_instagram":  content.get("caption_instagram",  ""),
        "v1_url":             v1_url,
        "v2_url":             v2_url,
        "pending_approval":   pending_approval,
        "updated_at":         datetime.now().isoformat(),
    }

    r = _rest("POST", "otb_pipeline_state", json=row)
    if r and r.ok:
        print(f"[Supabase] Slot {slot} state pushed (pending={pending_approval})")
        return True
    print(f"[Supabase] Slot {slot} push failed: {r.text[:200] if r else 'no response'}")
    return False


def clear_slot_pending(slot: int):
    """Clear pending_approval flag after decision (post/skip/regen/edit)."""
    _rest("PATCH", f"otb_pipeline_state?slot=eq.{slot}",
          json={"pending_approval": False, "updated_at": datetime.now().isoformat()})


def push_global_status(
    current_step: str = "",
    posts_today: int = 0,
    ran_slots: list = None,
    pending_slots: list = None,
):
    """Upsert slot=0 row with global pipeline status."""
    row = {
        "slot":               0,
        "current_step":       current_step,
        "posts_today":        posts_today,
        "ran_slots_json":     json.dumps(ran_slots or []),
        "pending_slots_json": json.dumps(pending_slots or []),
        "updated_at":         datetime.now().isoformat(),
    }
    _rest("POST", "otb_pipeline_state", json=row)


def poll_pending_commands(slot: int) -> list[dict]:
    """Return list of pending commands for this slot (oldest first)."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/otb_pipeline_commands",
            headers=_HDR,
            params={
                "slot":   f"eq.{slot}",
                "status": "eq.pending",
                "order":  "created_at.asc",
                "limit":  "5",
            },
            timeout=15,
        )
        if r.ok:
            return r.json()
    except Exception as e:
        print(f"[Supabase] Poll commands error: {e}")
    return []


def mark_command_done(cmd_id: int, status: str = "done"):
    """Mark a command as done or failed."""
    _rest("PATCH", f"otb_pipeline_commands?id=eq.{cmd_id}",
          json={"status": status, "done_at": datetime.now().isoformat()})
