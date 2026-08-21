"""
analyse_kling_library.py — Kling clip catalogue builder

Scans kling_library/ for any clips not yet in data/kling_library.json,
extracts 3 frames per clip via FFmpeg, sends frames to GPT-4o Vision,
and stores a rich description for each clip.

Run manually:  python scripts/analyse_kling_library.py
Called by:     pipeline_kling.py before every V2 render

Output: data/kling_library.json
  {
    "filename": "kling_20260817_VIDEO_VIDEO_1____3697_0.mp4",
    "duration": 10.3,
    "width": 1080, "height": 1920,
    "scene_type": "handover|presenter|airport|lifestyle|travel|explainer",
    "people": "man|woman|couple|group|none",
    "setting": "airport|street|home|office|car|outdoor",
    "action": "short description of what is happening",
    "mood": "energetic|calm|emotional|professional|casual",
    "has_speech": true/false,
    "transcript": "...",       ← populated by render_kling_video.py via Whisper
    "dialogue_start": 0.0,    ← seconds when speech begins
    "kling_score": 0-10,      ← GPT-4o visual quality score
    "boothop_fit": 0-10,      ← how well it fits BootHop brand
    "analysed_at": "ISO timestamp",
    "cooldown_until": null    ← set by render_kling_video.py after use
  }
"""

import base64, json, os, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import KLING_LIBRARY, DATA, OPENAI_API_KEY

import requests

LIBRARY_JSON = DATA / "kling_library.json"
FFPROBE      = "ffprobe"
FFMPEG       = "ffmpeg"

# ── helpers ───────────────────────────────────────────────────────────────────

def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] [KlingLib] {msg}")


def _load_library() -> dict:
    if LIBRARY_JSON.exists():
        try:
            return {e["filename"]: e for e in json.loads(LIBRARY_JSON.read_text(encoding="utf-8"))}
        except Exception:
            return {}
    return {}


def _save_library(lib: dict):
    LIBRARY_JSON.write_text(
        json.dumps(list(lib.values()), indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def _get_video_info(path: Path) -> dict:
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(r.stdout)
        dur  = float(data["format"].get("duration", 0))
        vs   = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        return {"duration": round(dur, 2), "width": vs.get("width", 0), "height": vs.get("height", 0)}
    except Exception as e:
        _log(f"ffprobe error on {path.name}: {e}")
        return {"duration": 0, "width": 0, "height": 0}


def _extract_frames(path: Path, n: int = 3) -> list[str]:
    """Extract n evenly-spaced frames, return list of base64-encoded JPEGs."""
    info = _get_video_info(path)
    dur  = info["duration"] or 5
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for i in range(n):
            t   = round(dur * (i + 1) / (n + 1), 2)
            out = Path(td) / f"frame_{i}.jpg"
            subprocess.run(
                [FFMPEG, "-ss", str(t), "-i", str(path),
                 "-vframes", "1", "-q:v", "3",
                 "-vf", "scale=540:-2",
                 str(out), "-y"],
                capture_output=True, timeout=20
            )
            if out.exists():
                frames.append(base64.b64encode(out.read_bytes()).decode())
    return frames


def _analyse_with_vision(filename: str, frames: list[str], duration: float) -> dict:
    """Send frames to GPT-4o Vision and get structured clip analysis."""
    if not OPENAI_API_KEY:
        _log("No OPENAI_API_KEY — skipping vision analysis")
        return _fallback_entry(filename, duration)

    content = [
        {
            "type": "text",
            "text": (
                f"You are analysing a video clip called '{filename}' ({duration}s) "
                "for BootHop — a UK-to-Nigeria peer-to-peer parcel delivery app where travellers "
                "carry parcels for senders on trips they are already making.\n\n"
                "These are 3 frames from the clip (start / middle / end).\n\n"
                "CRITICAL RULE: If ANY animal (dog, cat, bird, horse, fish, wildlife, pet, livestock, "
                "or any other creature) appears in ANY frame — set best_use to 'avoid'. No exceptions.\n\n"
                "Return ONLY valid JSON with these exact fields:\n"
                "{\n"
                '  "scene_type": one of: presenter|handover|airport|lifestyle|travel|explainer|transition|other,\n'
                '  "people": one of: man|woman|couple|group|none,\n'
                '  "setting": one of: airport|street|home|office|car|outdoor|studio|other,\n'
                '  "action": "1-2 sentence description of what is visually happening",\n'
                '  "mood": one of: energetic|calm|emotional|professional|casual|urgent,\n'
                '  "has_speech": true or false,\n'
                '  "has_animals": true or false,\n'
                '  "kling_score": integer 1-10 (visual quality and cinematic feel),\n'
                '  "boothop_fit": integer 1-10 (how relevant is this to BootHop parcel delivery between UK and Nigeria),\n'
                '  "best_use": "hook|main_story|bridge|brand_message|avoid"\n'
                "}\n"
                "No markdown. No explanation. JSON only."
            )
        }
    ]
    for b64 in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}
        })

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": content}]
            },
            timeout=30
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        import re
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            return json.loads(m.group())
    except Exception as e:
        _log(f"Vision API error: {e}")

    return _fallback_entry(filename, duration)


def _fallback_entry(filename: str, duration: float) -> dict:
    return {
        "scene_type": "other", "people": "unknown", "setting": "other",
        "action": "Not yet analysed", "mood": "casual", "has_speech": False,
        "kling_score": 5, "boothop_fit": 5, "best_use": "main_story"
    }


# ── main ──────────────────────────────────────────────────────────────────────

def analyse_library(force: bool = False) -> dict:
    """
    Scan kling_library/ for new clips, analyse any not yet in the catalogue.
    Returns the full library dict keyed by filename.
    """
    KLING_LIBRARY.mkdir(exist_ok=True)
    lib = _load_library()

    clips = sorted(KLING_LIBRARY.glob("*.mp4"))
    new_count = 0

    for clip in clips:
        if clip.name in lib and not force:
            continue

        _log(f"Analysing: {clip.name}")
        info   = _get_video_info(clip)
        frames = _extract_frames(clip, n=3)

        if not frames:
            _log(f"  Could not extract frames — skipping")
            continue

        analysis = _analyse_with_vision(clip.name, frames, info["duration"])

        lib[clip.name] = {
            "filename":     clip.name,
            "duration":     info["duration"],
            "width":        info["width"],
            "height":       info["height"],
            "transcript":   "",
            "dialogue_start": 0.0,
            "cooldown_until": None,
            "analysed_at":  datetime.now().isoformat(),
            **analysis,
        }
        _log(f"  scene={analysis.get('scene_type')} fit={analysis.get('boothop_fit')}/10 use={analysis.get('best_use')}")
        new_count += 1

    # Remove entries for clips that no longer exist
    existing_names = {c.name for c in clips}
    removed = [k for k in list(lib.keys()) if k not in existing_names]
    for k in removed:
        del lib[k]
        _log(f"Removed from catalogue (file gone): {k}")

    _save_library(lib)
    _log(f"Library: {len(lib)} clips total, {new_count} newly analysed")
    return lib


def get_library() -> list[dict]:
    """Return the full catalogue as a list. Runs analysis if catalogue is empty."""
    if not LIBRARY_JSON.exists():
        analyse_library()
    try:
        return json.loads(LIBRARY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []


def mark_clip_used(filename: str):
    """Set cooldown_until = today + 14 days after a clip is used in a video."""
    from datetime import timedelta
    lib = _load_library()
    if filename in lib:
        lib[filename]["cooldown_until"] = (datetime.now() + timedelta(days=14)).date().isoformat()
        _save_library(lib)


def available_clips(min_fit: int = 5) -> list[dict]:
    """Return clips not on cooldown, no animals, boothop_fit >= min_fit, sorted by fit score."""
    from datetime import date
    today = date.today().isoformat()
    clips = get_library()
    return sorted(
        [c for c in clips
         if (c.get("cooldown_until") or "0000-00-00") < today
         and c.get("boothop_fit", 0) >= min_fit
         and c.get("best_use") != "avoid"
         and not c.get("has_animals", False)],
        key=lambda x: x.get("boothop_fit", 0),
        reverse=True
    )


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Re-analyse all clips even if already catalogued")
    args = ap.parse_args()
    analyse_library(force=args.force)
