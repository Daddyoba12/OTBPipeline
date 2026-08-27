"""
OTB_Pipeline — Voice-over (Stage 7)

Generates Nigerian-accented narration for each video.
Runs after the video is rendered. Saves an MP3 alongside the video and
optionally mixes the narration into the final video (lowers background music,
adds voice track on top).

Voice provider priority: ElevenLabs → Azure en-NG → OpenAI (fallback)
Gender selection by pillar:
  family / community / travel_hacks / cultural_earn → female
  smart / supply_chain / brand_authority / logistics → male
  default → female
"""

import json, re, subprocess, sys, tempfile
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUTPUT, TEMP

_MALE_PILLARS = {"smart", "supply_chain", "brand_authority", "logistics_stories", "airport_deliveries"}


def _build_narration(content: dict) -> str:
    """
    Build the spoken narration text from story beats.
    Short punchy sentences with natural pauses (... for TTS).
    """
    hook       = content.get("hook", "").strip().rstrip(".")
    problem    = content.get("problem", "").strip().rstrip(".")
    stakes     = content.get("stakes", "").strip().rstrip(".")
    resolution = content.get("resolution", "").strip().rstrip(".")
    lesson     = content.get("lesson", "").strip().rstrip(".")

    lines = []
    if hook:
        lines.append(hook + ".")
    if problem:
        lines.append(problem + ".")
    if stakes:
        lines.append(stakes + ".")
    if resolution:
        lines.append(resolution + ".")
    if lesson:
        lines.append(lesson + ".")
    lines.append("BootHop. Same-day delivery, peer to peer.")

    return "  ".join(lines)


def generate_tts(content: dict, output_mp3: str | Path) -> Path | None:
    """
    Generate TTS audio from story beats and save to output_mp3.
    Routes to the right provider based on pillar:
      car_feature (G-Inspired) → ElevenLabs American English → OpenAI
      all others  (BootHop)    → Azure Nigerian en-NG → ElevenLabs → OpenAI
    """
    from tts_nigerian import generate_nigerian_tts, generate_american_tts

    pillar = content.get("pillar", "family")
    gender = "male" if pillar in _MALE_PILLARS else "female"
    text   = _build_narration(content)

    out = Path(output_mp3)
    out.parent.mkdir(parents=True, exist_ok=True)

    if pillar == "car_feature":
        print(f"  [Voiceover] G-Inspired: ElevenLabs American English ({gender}, {len(text)} chars)...")
        ok = generate_american_tts(text, out, gender=gender)
    else:
        print(f"  [Voiceover] BootHop: Azure Nigerian TTS ({gender}, {len(text)} chars)...")
        ok = generate_nigerian_tts(text, out, gender=gender)

    if ok and out.exists():
        print(f"  [Voiceover] Saved: {out} ({out.stat().st_size // 1024}KB)")
        return out

    print("  [Voiceover] TTS failed — no audio generated")
    return None


def mix_voiceover(video_path: str | Path, voice_mp3: str | Path,
                  output_path: str | Path,
                  music_vol: float = 0.20,
                  voice_vol: float = 1.0) -> bool:
    """
    Mix voice-over into a rendered video using FFmpeg.
    Lowers background music to music_vol (default 20%) and places
    the voice track at full volume on top.

    Returns True on success, False on failure.
    """
    video = Path(video_path)
    voice = Path(voice_mp3)
    out   = Path(output_path)

    if not video.exists():
        print(f"  [Voiceover] Video not found: {video}")
        return False
    if not voice.exists():
        print(f"  [Voiceover] Voice MP3 not found: {voice}")
        return False

    filter_graph = (
        f"[0:a]volume={music_vol}[bg];"
        f"[1:a]volume={voice_vol}[vo];"
        f"[bg][vo]amix=inputs=2:duration=first:normalize=0[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(voice),
        "-filter_complex", filter_graph,
        "-map", "0:v",
        "-map", "[out]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out),
    ]

    print(f"  [Voiceover] Mixing voice into video...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  [Voiceover] FFmpeg error: {result.stderr[-300:]}")
            return False
        if out.exists():
            print(f"  [Voiceover] Mixed video saved: {out} ({out.stat().st_size // 1024}KB)")
            return True
        return False
    except Exception as e:
        print(f"  [Voiceover] Mix failed: {e}")
        return False


def add_voiceover_to_video(content: dict, video_path: str | Path,
                            mix_into_video: bool = True) -> str | None:
    """
    High-level helper — generates TTS and optionally mixes it into the video.

    If mix_into_video=True: returns path to the new video with voice baked in.
    If mix_into_video=False: returns path to the MP3 only.
    Returns None on any failure.
    """
    video = Path(video_path)
    mp3_path = video.with_suffix(".voiceover.mp3")
    voice_mp3 = generate_tts(content, mp3_path)

    if not voice_mp3:
        return None

    if not mix_into_video:
        return str(voice_mp3)

    # Create voiced version alongside the original
    voiced_path = video.with_stem(video.stem + "_voiced")
    ok = mix_voiceover(video, voice_mp3, voiced_path)

    if ok:
        return str(voiced_path)
    return str(voice_mp3)  # Fall back to returning just the MP3


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate voice-over for a video")
    parser.add_argument("video", help="Path to the rendered MP4")
    parser.add_argument("--content-json", help="Path to sidecar JSON with story beats")
    parser.add_argument("--no-mix", action="store_true", help="Only generate MP3, do not mix into video")
    args = parser.parse_args()

    if args.content_json:
        content = json.loads(Path(args.content_json).read_text(encoding="utf-8"))
    else:
        # Demo content for testing
        content = {
            "pillar":     "family",
            "hook":       "She nearly cried when she saw the price",
            "problem":    "A reputable courier quoted £45 for a phone charger",
            "stakes":     "Her mum had waited 3 weeks already",
            "resolution": "She found a traveller on BootHop who carried it for £8",
            "lesson":     "The flight was already going. You just needed someone on it",
        }

    result = add_voiceover_to_video(content, args.video, mix_into_video=not args.no_mix)
    print(f"\nResult: {result}")
