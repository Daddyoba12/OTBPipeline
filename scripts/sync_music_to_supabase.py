"""
One-time script: sync all local music files to Supabase music_tracks table,
then assign all tracks to the boothop pipeline_clients entry.

Run from OTB_Pipeline root:
    python scripts/sync_music_to_supabase.py
"""

import json, sys
from pathlib import Path

import requests

SUPABASE_URL = "https://zwgngbzbdvnrdnanjded.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp3Z25nYnpiZHZucmRuYW5qZGVkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5NTA0NSwiZXhwIjoyMDkwODcxMDQ1fQ"
    ".jP_Ukh4Dwlxfiei5tyHblJ0psgCXntDwnnZBRQch9zw"
)
HDR = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates",
}

MUSIC_DIR = Path(__file__).parent.parent / "music"

FOLDER_META = {
    "archive":      {"genre": "Archive",  "artist": "BootHop Library"},
    "clips":        {"genre": "Clips",    "artist": "BootHop Clips"},
    "daily":        {"genre": "Daily",    "artist": "BootHop Daily"},
    "yt_downloads": {"genre": "YouTube",  "artist": "YouTube"},
}


def rest(method, path, **kwargs):
    r = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=HDR, timeout=20, **kwargs)
    return r


def get_boothop_client_id():
    r = rest("GET", "pipeline_clients", params={"slug": "eq.boothop", "select": "id", "limit": "1"})
    if r.ok:
        rows = r.json()
        if rows:
            return rows[0]["id"]
    print("[!] Could not find boothop client — trying super admin user")
    # Fall back: return None and skip client assignment
    return None


def upsert_track(title: str, source: str, genre: str, artist: str) -> str | None:
    """Upsert a track and return its UUID."""
    r = rest("POST", "music_tracks", json={
        "title":  title,
        "artist": artist,
        "genre":  genre,
        "source": source,
    })
    if not r.ok:
        print(f"  [err] upsert {title}: {r.status_code} {r.text[:80]}")
        return None
    # Fetch the id back
    r2 = rest("GET", "music_tracks", params={"title": f"eq.{title}", "source": f"eq.{source}", "select": "id", "limit": "1"})
    if r2.ok and r2.json():
        return r2.json()[0]["id"]
    return None


def assign_track(client_id: str, track_id: str):
    rest("POST", "client_music", json={"client_id": client_id, "track_id": track_id})


def main():
    client_id = get_boothop_client_id()
    if client_id:
        print(f"Boothop client ID: {client_id}")
    else:
        print("No boothop client found — tracks will be added to library but not assigned")

    total_inserted = 0
    total_assigned = 0

    for folder, meta in FOLDER_META.items():
        d = MUSIC_DIR / folder
        if not d.exists():
            print(f"  Skipping {folder}/ — not found")
            continue
        files = sorted(d.glob("*.mp3"))
        print(f"\n[{folder}] {len(files)} tracks")
        for f in files:
            title = f.stem
            track_id = upsert_track(title, folder, meta["genre"], meta["artist"])
            if track_id:
                total_inserted += 1
                print(f"  OK {title}  ({track_id[:8]})")
                if client_id:
                    assign_track(client_id, track_id)
                    total_assigned += 1
            else:
                print(f"  FAIL {title}")

    print(f"\nDone: {total_inserted} tracks synced, {total_assigned} assigned to boothop")


if __name__ == "__main__":
    main()
