"""
revoice_v2.py — Auto-TTS narration for V2 rendered videos.
Re-mixes audio only (voice + music). No Kling clip or content regeneration.

Usage (standalone):
  python revoice_v2.py otb_v2_slot3_20260819_203554
  python revoice_v2.py --slot 3          # finds the latest V2 video for slot 3

Called by the Telegram commander via do_autorevoice(slot).
"""

import argparse, json, os, random, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import OUTPUT, TEMP, MUSIC_DIR, MUSIC_ARCHIVE, OPENAI_API_KEY

FFMPEG = "ffmpeg"


def find_latest_v2_base(slot: int) -> str | None:
    """Return the base filename (no platform suffix, no extension) for the most recent V2 slot video."""
    sidecars = sorted(
        OUTPUT.glob(f"otb_v2_slot{slot}_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if sidecars:
        return sidecars[0].stem   # e.g. "otb_v2_slot3_20260819_203554"
    return None


def _pick_music() -> Path | None:
    for d in [MUSIC_DIR, MUSIC_ARCHIVE]:
        if d and Path(d).exists():
            tracks = list(Path(d).glob("*.mp3")) + list(Path(d).glob("*.m4a"))
            if tracks:
                return random.choice(tracks)
    return None


def _build_narration(story: dict) -> str:
    hook   = story.get("hook",   "").strip()
    lesson = story.get("lesson", "").strip()
    cta    = "Download BootHop and connect with travellers today."
    return " ".join(p for p in [hook, lesson, cta] if p)


def _generate_tts(text: str, out_path: Path, voice: str = "nova") -> bool:
    if not text.strip():
        return False
    if OPENAI_API_KEY:
        try:
            import requests
            r = requests.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={"model": "tts-1", "input": text, "voice": voice},
                timeout=30,
            )
            r.raise_for_status()
            out_path.write_bytes(r.content)
            print(f"  [TTS] OpenAI {voice} - {len(text)} chars - {out_path.name}")
            return True
        except Exception as e:
            print(f"  [TTS] OpenAI failed: {e} - trying gTTS")
    try:
        from gtts import gTTS
        gTTS(text=text, lang="en", tld="co.uk").save(str(out_path))
        print(f"  [TTS] gTTS (British) - {out_path.name}")
        return True
    except Exception as e:
        print(f"  [TTS] Both TTS methods failed: {e}")
        return False


def _remix_audio(video_in: Path, narr: Path | None, music: Path | None, video_out: Path) -> bool:
    if not video_in.exists():
        print(f"  [Remix] Source not found: {video_in.name}")
        return False

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_in)],
        capture_output=True, text=True,
    )
    try:
        total_dur = float(json.loads(probe.stdout).get("format", {}).get("duration", 15))
    except Exception:
        total_dur = 15.0

    fade_out_start = max(0.0, total_dur - 1.0)
    has_narr  = bool(narr  and narr.exists())
    has_music = bool(music and music.exists())

    narr_input  = ["-i", str(narr)]  if has_narr  else []
    music_input = ["-i", str(music)] if has_music else []

    if has_narr and has_music:
        af = (
            f"[1:a]volume=1.0,afade=t=in:st=0:d=0.3,"
            f"afade=t=out:st={fade_out_start:.2f}:d=0.8[narr];"
            f"[2:a]volume=0.10,afade=t=in:st=0:d=0.5,"
            f"afade=t=out:st={fade_out_start:.2f}:d=0.8[mus];"
            "[narr][mus]amix=inputs=2:duration=first:normalize=0[outa]"
        )
        cmd = (
            [FFMPEG, "-y", "-i", str(video_in)] + narr_input + music_input +
            ["-filter_complex", af,
             "-map", "0:v", "-map", "[outa]",
             "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
             str(video_out)]
        )
    elif has_narr:
        af = (
            f"[1:a]volume=1.0,afade=t=in:st=0:d=0.3,"
            f"afade=t=out:st={fade_out_start:.2f}:d=0.8[outa]"
        )
        cmd = (
            [FFMPEG, "-y", "-i", str(video_in)] + narr_input +
            ["-filter_complex", af,
             "-map", "0:v", "-map", "[outa]",
             "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
             str(video_out)]
        )
    else:
        print(f"  [Remix] No narration or music - skipping {video_in.name}")
        return False

    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if video_out.exists() and video_out.stat().st_size > 50_000:
        size_kb = video_out.stat().st_size // 1024
        print(f"  [Remix] OK {video_out.name}  ({size_kb} KB)")
        return True
    else:
        print(f"  [Remix] FAILED: {r.stderr[-300:].decode(errors='replace')}")
        return False


def revoice(base_name: str) -> dict:
    """
    Add TTS narration to all platform variants of a V2 video.
    Returns dict: {platform: output_path} for succeeded variants.
    Originals are overwritten in-place.
    """
    json_path = OUTPUT / f"{base_name}.json"
    if not json_path.exists():
        print(f"ERROR: Sidecar not found: {json_path}")
        return {}

    story = json.loads(json_path.read_text(encoding="utf-8"))
    slot  = story.get("slot", "?")
    date  = story.get("date", "?")
    print(f"\n{'='*60}")
    print(f"  Auto-revoice: {base_name}")
    print(f"  Slot {slot} - {date}")
    print(f"  Hook: {story.get('hook','')[:70]}")
    print(f"{'='*60}\n")

    TEMP.mkdir(exist_ok=True)
    narr_text = _build_narration(story)
    print(f"Narration:\n  {narr_text}\n")

    narr_path = TEMP / f"revoice_{base_name}_narr.mp3"
    if not _generate_tts(narr_text, narr_path):
        print("WARNING: TTS failed - proceeding with music only")
        narr_path = None

    music = _pick_music()
    if music:
        print(f"Music: {music.name}\n")
    else:
        print("WARNING: No music tracks found\n")

    results = {}
    for platform in ["tiktok", "instagram", "youtube"]:
        src  = OUTPUT / f"{base_name}_{platform}.mp4"
        dest = OUTPUT / f"{base_name}_{platform}_voiced.mp4"
        if not src.exists():
            print(f"  [Skip] {platform} not found: {src.name}")
            continue
        ok = _remix_audio(src, narr_path, music, dest)
        if ok and dest.exists():
            src.unlink(missing_ok=True)
            dest.rename(src)
            results[platform] = str(src)

    if narr_path and narr_path.exists():
        narr_path.unlink()

    success = len(results)
    print(f"\n  Done - {success}/3 platforms voiced")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base_name", nargs="?", help="Base filename without platform suffix or .json")
    ap.add_argument("--slot", type=int, help="Find latest V2 video for this slot number")
    args = ap.parse_args()

    if args.slot:
        base = find_latest_v2_base(args.slot)
        if not base:
            print(f"ERROR: No V2 video found for slot {args.slot}")
            sys.exit(1)
        print(f"Found: {base}")
    elif args.base_name:
        base = args.base_name
    else:
        ap.print_help()
        sys.exit(1)

    revoice(base)
