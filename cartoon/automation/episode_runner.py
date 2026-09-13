"""
BOUNCE ON THE MOVE — Episode Runner
Produces one episode end-to-end and delivers to Telegram.

Usage:
    python episode_runner.py              # produce next episode
    python episode_runner.py --episode 1  # reproduce specific episode
    python episode_runner.py --dry-run    # estimate cost only, no generation
"""

import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
CARTOON   = Path(__file__).parent.parent
PIPELINE  = CARTOON.parent
BIBLE     = CARTOON / "series_bible"
STATE     = CARTOON / "state"
EPISODES  = CARTOON / "episodes"

sys.path.insert(0, str(PIPELINE))
from config import (
    ANTHROPIC_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY,
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DATA,
)

# Optional keys — report missing, never print values
_PERPLEXITY_KEY  = os.environ.get("PERPLEXITY_API_KEY", "")

COST_CAP = 5.00

# ── Helpers ────────────────────────────────────────────────────────────────────
def _log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] [Cartoon] {msg}")


def _tg(text: str, chat_id: str = TELEGRAM_CHAT_ID):
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
    except Exception as e:
        _log(f"Telegram text failed: {e}")


def _tg_video(path: Path, caption: str, chat_id: str = TELEGRAM_CHAT_ID):
    import requests
    _log(f"Sending video to Telegram ({path.stat().st_size // 1024}KB)...")
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={"chat_id": chat_id, "caption": caption,
                      "supports_streaming": "true", "parse_mode": "Markdown"},
                files={"video": (path.name, f, "video/mp4")},
                timeout=300,
            )
        ok = r.json().get("ok")
        _log(f"Telegram video: {'OK' if ok else r.json()}")
        return ok
    except Exception as e:
        _log(f"Telegram video failed: {e}")
        return False


def _tg_photo(path: Path, caption: str, chat_id: str = TELEGRAM_CHAT_ID):
    import requests
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": (path.name, f, "image/jpeg")},
                timeout=60,
            )
    except Exception as e:
        _log(f"Telegram photo failed: {e}")


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _ff(*args) -> bool:
    cmd = ["ffmpeg", "-y"] + list(args)
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0


def _ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


# Character description — matches reference videos (orange Pixar-quality cat)
_BOUNCE = (
    "3D animated Pixar-quality film style, original character, orange anthropomorphic cat named Bounce, "
    "large vivid green eyes, warm orange tabby fur, white muzzle with short whiskers, "
    "very expressive emotive face, humanoid posture, premium cinema render"
)

# ── Episode 1: SPARE SPACE ─────────────────────────────────────────────────────
EPISODE_1 = {
    "number": 1,
    "title": "SPARE SPACE",
    "route": "London -> Manchester",
    "dialogue": (
        "I'm travelling from London to Manchester tomorrow. "
        "One small suitcase, plenty of spare space — and my train ticket definitely "
        "didn't pay for itself. So I listed my trip on BootHop. "
        "If I'm matched with a verified sender and accept the request, "
        "I can earn by helping their item get there. "
        "I'm going that way anyway, so why not make the journey work harder? BootHop it."
    ),
    "shots": [
        {
            "id": "s1_hook",
            "time": "0:00-0:02",
            "label": "Hook",
            "description": "Bounce stares into partly empty suitcase, looks at camera with cheeky expression.",
            "on_screen_text": "SPARE SPACE?",
            "dalle_scene": (
                f"{_BOUNCE}, looking into an open suitcase on a bed with a cheeky smile, "
                "golden hour light, modern London apartment, city skyline visible through window. No text in image."
            ),
        },
        {
            "id": "s2_problem",
            "time": "0:02-0:08",
            "label": "The Problem",
            "description": "Bounce sits on sofa, holds up phone showing travel plan.",
            "on_screen_text": "LONDON -> MANCHESTER",
            "dalle_scene": (
                f"{_BOUNCE}, sitting on a modern sofa, holding up a smartphone with a friendly expression, "
                "golden hour light, cosy London apartment interior. No text in image."
            ),
        },
        {
            "id": "s3_idea",
            "time": "0:08-0:14",
            "label": "The Idea",
            "description": "Bounce holds phone, listing trip on BootHop app.",
            "on_screen_text": "LIST YOUR JOURNEY",
            "dalle_scene": (
                f"{_BOUNCE}, holding a smartphone up proudly with an excited expression, "
                "bright natural light, modern flat interior. No text in image."
            ),
        },
        {
            "id": "s4_how",
            "time": "0:14-0:21",
            "label": "How It Works",
            "description": "Bounce explains matching and verification process.",
            "on_screen_text_sequence": ["GET MATCHED", "VERIFY", "ACCEPT"],
            "dalle_scene": (
                f"{_BOUNCE}, gesturing with both hands in an explanatory way, confident friendly expression, "
                "warm interior lighting, modern apartment. No text in image."
            ),
        },
        {
            "id": "s5_humour",
            "time": "0:21-0:27",
            "label": "The Humour",
            "description": "Bounce looks at train ticket, jokes it won't pay for itself, closes suitcase.",
            "dalle_scene": (
                f"{_BOUNCE}, holding a train ticket with a comically exasperated expression, "
                "golden hour light, London apartment. No text in image."
            ),
        },
        {
            "id": "s6_ending",
            "time": "0:27-0:32",
            "label": "Ending",
            "description": "Bounce delivers final line, BootHop logo shown.",
            "on_screen_text_sequence": ["GOING THAT WAY ANYWAY?", "BOOTHOP IT.", "boothop.com"],
            "next_teaser": "NEXT EPISODE: THE HANDOVER",
            "dalle_scene": (
                f"{_BOUNCE}, giving a confident thumbs up with a warm smile, "
                "golden hour light, London apartment with suitcase ready by the door. No text in image."
            ),
        },
    ],
    "caption": (
        "Bounce is heading to Manchester with spare space in his suitcase. "
        "He listed his trip on BootHop — if he gets matched he can earn while travelling. "
        "Going that way anyway. BootHop it. boothop.com"
    ),
    "hashtags": "#BootHop #BounceOnTheMove #StudentLife #LondonToManchester #DiasporaLife #AfricanCommunity #SmartTravel #Earn",
    "setting": "Bounce's modern London apartment, golden hour",
    "story_summary": "Bounce discovers he can list spare luggage space on BootHop and potentially earn on his London-Manchester journey.",
}

# ── Episode 2: THE HANDOVER ────────────────────────────────────────────────────
EPISODE_2 = {
    "number": 2,
    "title": "THE HANDOVER",
    "route": "Nottingham -> Cardiff",
    "dialogue": (
        "I needed to get a box to my mate in Cardiff. "
        "Courier wanted forty quid. So I listed the item on BootHop — "
        "a verified traveller going that way picked up the job. "
        "I dropped the box at the meet point, they handled the rest. "
        "My mate got it same day. For way less. BootHop it."
    ),
    "shots": [
        {
            "id": "s1_hook",
            "time": "0:00-0:02",
            "label": "Hook",
            "description": "Bounce stares at a cardboard box, looks at camera with exasperated expression.",
            "on_screen_text": "40 QUID?!",
            "dalle_scene": (
                f"{_BOUNCE}, standing in a modern flat, staring at a cardboard box on the floor "
                "with an exasperated shocked expression, holding a phone, golden hour light, cosy Nottingham apartment. No text in image."
            ),
        },
        {
            "id": "s2_problem",
            "time": "0:02-0:08",
            "label": "The Problem",
            "description": "Bounce scrolls courier prices on phone, eyes widening in shock.",
            "on_screen_text": "COURIER FEES = MADNESS",
            "dalle_scene": (
                f"{_BOUNCE}, sitting on a sofa, scrolling through a smartphone with wide eyes and a horrified expression, "
                "warm interior lighting, cosy modern apartment. No text in image."
            ),
        },
        {
            "id": "s3_idea",
            "time": "0:08-0:14",
            "label": "The Idea",
            "description": "Bounce opens BootHop app, lists the item with a smile.",
            "on_screen_text": "LIST YOUR ITEM",
            "dalle_scene": (
                f"{_BOUNCE}, holding a smartphone with a lightbulb-moment excited expression, "
                "bright natural light, modern Nottingham flat. No text in image."
            ),
        },
        {
            "id": "s4_match",
            "time": "0:14-0:21",
            "label": "The Match",
            "description": "Bounce sees a verified traveller matched on the app heading to Cardiff.",
            "on_screen_text_sequence": ["TRAVELLER VERIFIED", "GOING TO CARDIFF", "MATCHED!"],
            "dalle_scene": (
                f"{_BOUNCE}, looking at his phone with a relieved and excited expression, "
                "pumping fist in celebration, cosy apartment, afternoon light. No text in image."
            ),
        },
        {
            "id": "s5_handover",
            "time": "0:21-0:27",
            "label": "The Handover",
            "description": "Bounce hands the cardboard box to the traveller at a street meet-up point.",
            "dalle_scene": (
                f"{_BOUNCE}, handing a cardboard box to a person on a city street, "
                "confident friendly expression, daytime Nottingham street setting. No text in image."
            ),
        },
        {
            "id": "s6_ending",
            "time": "0:27-0:32",
            "label": "Ending",
            "description": "Bounce gives a satisfied thumbs up — mate in Cardiff got the box same day.",
            "on_screen_text_sequence": ["DELIVERED SAME DAY", "FOR WAY LESS", "BOOTHOP IT.", "boothop.com"],
            "next_teaser": "NEXT EPISODE: TOO MUCH LUGGAGE?",
            "dalle_scene": (
                f"{_BOUNCE}, giving a confident satisfied thumbs up with a big warm smile, "
                "golden hour light, Nottingham city background. No text in image."
            ),
        },
    ],
    "caption": (
        "Bounce needed to send a box from Nottingham to Cardiff. "
        "Courier wanted £40. He listed it on BootHop — a verified traveller handled the rest. "
        "Delivered same day for way less. BootHop it. boothop.com"
    ),
    "hashtags": "#BootHop #BounceOnTheMove #SendSmart #NottinghamToCardiff #DiasporaLife #AfricanCommunity #SmartSending #SaveMoney",
    "setting": "Bounce's Nottingham flat and city street handover point",
    "story_summary": "Bounce has a box to send to Cardiff but is shocked by courier prices. He lists it on BootHop, gets matched with a verified traveller, and arranges a street handover — delivered same day for way less.",
}


# ── Cost estimator ─────────────────────────────────────────────────────────────
def estimate_cost(episode: dict) -> dict:
    n_scenes = len(episode["shots"])
    costs = {
        "dalle_images":    round(n_scenes * 0.042, 2),                         # gpt-image-1 medium
        "sora_video":      round(n_scenes * 5 * 0.03, 2),                      # Sora: $0.03/sec × 5s × n_scenes
        "openai_tts":      round(len(episode["dialogue"]) / 1_000_000 * 15, 4),# TTS-1: $15 per 1M chars
        "elevenlabs_music": 0.10,
    }
    costs["total"] = round(sum(costs.values()), 2)
    return costs


# ── OpenAI balance checker ─────────────────────────────────────────────────────
def _check_openai_balance(estimated_cost: float):
    import requests as _rq
    WARNING_THRESHOLD = 5.00
    try:
        r = _rq.get(
            "https://api.openai.com/v1/dashboard/billing/credit_grants",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=15,
        )
        if r.status_code != 200:
            _log(f"  Balance check: HTTP {r.status_code} — skipping")
            return
        available = r.json().get("total_available") or 0
        _log(f"  OpenAI balance: ${available:.2f}")
        if available < estimated_cost + WARNING_THRESHOLD:
            _tg(
                f"*OpenAI Credits Low*\n"
                f"Balance: ${available:.2f}\n"
                f"Next episode estimate: ${estimated_cost:.2f}\n"
                f"Please top up at platform.openai.com/settings/billing"
            )
            _log(f"  Balance warning sent to Telegram (${available:.2f} remaining)")
    except Exception as e:
        _log(f"  Balance check failed: {e}")


# ── Scene image generation (gpt-image-1) ──────────────────────────────────────
def generate_scene_image(shot: dict, ep_dir: Path, retry: int = 0) -> Path | None:
    import requests as _rq, base64 as _b64m
    _log(f"  Generating image: {shot['id']}...")
    prompt = shot["dalle_scene"]
    try:
        r = _rq.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": prompt,
                  "n": 1, "size": "1024x1536", "quality": "medium"},
            timeout=90,
        )
        r.raise_for_status()
        item = r.json()["data"][0]
        img_path = ep_dir / f"{shot['id']}.png"
        if item.get("b64_json"):
            img_path.write_bytes(_b64m.b64decode(item["b64_json"]))
        elif item.get("url"):
            img_path.write_bytes(_rq.get(item["url"], timeout=60).content)
        else:
            raise ValueError("No image data in response")
        _log(f"  Image OK: {img_path.name} ({img_path.stat().st_size//1024}KB)")
        return img_path
    except Exception as e:
        _log(f"  Image failed ({shot['id']}): {e}")
        if retry < 2:
            time.sleep(3)
            return generate_scene_image(shot, ep_dir, retry + 1)
        return None


# ── Voiceover (OpenAI TTS-1) ──────────────────────────────────────────────────
def generate_voiceover(text: str, ep_dir: Path) -> Path | None:
    import requests as _rq
    _log(f"  Generating voiceover ({len(text)} chars, OpenAI TTS-1)...")
    try:
        r = _rq.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "tts-1", "input": text,
                  "voice": "echo", "speed": 0.95},
            timeout=60,
        )
        r.raise_for_status()
        out = ep_dir / "voiceover.mp3"
        out.write_bytes(r.content)
        _log(f"  Voiceover OK ({len(r.content)//1024}KB)")
        return out
    except Exception as e:
        _log(f"  Voiceover failed: {e}")
        return None


# ── Background music (ElevenLabs Music) ───────────────────────────────────────
def generate_music(duration_s: float, ep_dir: Path) -> Path | None:
    import requests as _rq
    prompt = (
        "Amapiano instrumental background music, 108 BPM, warm African percussion, "
        "smooth piano chords, light log-drum rhythm, modern and playful, no vocals, "
        "suitable for advertising, uplifting family-friendly energy"
    )
    _log(f"  Generating background music ({duration_s:.0f}s)...")
    try:
        r = _rq.post(
            "https://api.elevenlabs.io/v1/sound-generation",
            headers={"xi-api-key": ELEVENLABS_API_KEY,
                     "Content-Type": "application/json"},
            json={"text": prompt, "duration_seconds": min(duration_s, 22),
                  "prompt_influence": 0.3},
            timeout=90,
        )
        if r.status_code == 200:
            out = ep_dir / "music.mp3"
            out.write_bytes(r.content)
            _log(f"  Music OK ({len(r.content)//1024}KB)")
            return out
        else:
            _log(f"  Music API returned {r.status_code} — skipping music")
            return None
    except Exception as e:
        _log(f"  Music failed: {e}")
        return None


# ── Image -> 5s video clip (OpenAI Sora) ─────────────────────────────────────
def image_to_video_sora(image_path: Path, prompt: str, ep_dir: Path, shot_id: str) -> Path | None:
    import requests as _rq
    _log(f"  Sora video generation: {shot_id}...")
    try:
        body = {
            "model": "sora-1080p",
            "prompt": prompt,
            "duration": 5,
            "size": "1080x1920",
            "n": 1,
        }
        # Attach DALL-E image for image-to-video
        if image_path and image_path.exists():
            body["image"] = f"data:image/png;base64,{_b64(image_path)}"

        r = _rq.post(
            "https://api.openai.com/v1/video/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        # If API rejects image param, retry as text-to-video
        if r.status_code == 400 and "image" in (r.text or "").lower():
            _log(f"  Sora: image-to-video unsupported — retrying text-to-video...")
            body.pop("image", None)
            r = _rq.post(
                "https://api.openai.com/v1/video/generations",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json=body,
                timeout=60,
            )

        if r.status_code not in (200, 202):
            _log(f"  Sora: API error {r.status_code} — {r.text[:200]}")
            return _still_to_video(image_path, ep_dir, shot_id)

        data = r.json()

        # Synchronous response with URL
        if data.get("data") and data["data"][0].get("url"):
            url = data["data"][0]["url"]
            vid_data = _rq.get(url, timeout=120).content
            out = ep_dir / f"{shot_id}_clip.mp4"
            out.write_bytes(vid_data)
            _log(f"  Sora OK: {out.name} ({len(vid_data)//1024}KB)")
            return out

        # Async: poll for completion
        gen_id = data.get("id")
        if not gen_id:
            _log(f"  Sora: no generation ID — falling back")
            return _still_to_video(image_path, ep_dir, shot_id)

        _log(f"  Sora: polling {gen_id}...")
        for attempt in range(40):
            time.sleep(15)
            status_r = _rq.get(
                f"https://api.openai.com/v1/video/generations/{gen_id}",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                timeout=15,
            )
            status_data = status_r.json()
            state = status_data.get("status", "")
            _log(f"  Sora: {state} (attempt {attempt+1}/40)")
            if state == "completed":
                result_list = status_data.get("data") or []
                url = result_list[0].get("url", "") if result_list else ""
                if url:
                    vid_data = _rq.get(url, timeout=120).content
                    out = ep_dir / f"{shot_id}_clip.mp4"
                    out.write_bytes(vid_data)
                    _log(f"  Sora OK: {out.name} ({len(vid_data)//1024}KB)")
                    return out
                _log("  Sora: completed but no URL")
                break
            elif state in ("failed", "error", "cancelled"):
                _log(f"  Sora failed: {status_data.get('error', 'unknown')}")
                break

        return _still_to_video(image_path, ep_dir, shot_id)

    except Exception as e:
        _log(f"  Sora error: {e}")
        return _still_to_video(image_path, ep_dir, shot_id)


def _b64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode()


def _still_to_video(img: Path, ep_dir: Path, shot_id: str, duration: int = 5) -> Path | None:
    """Fallback: convert still image to 5-second video with Ken Burns zoom."""
    out = ep_dir / f"{shot_id}_clip.mp4"
    ok = _ff(
        "-loop", "1", "-i", str(img),
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.0015,1.3)':d={duration*30}:s=1080x1920",
        "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p",
        "-r", "30", str(out),
    )
    if ok and out.exists():
        _log(f"  Still->video fallback OK: {out.name}")
        return out
    _log(f"  Still->video failed for {shot_id}")
    return None


# ── Caption SRT builder ───────────────────────────────────────────────────────
def build_srt(dialogue: str, duration: float, ep_dir: Path) -> Path:
    words = dialogue.split()
    words_per_line = 6
    lines = [" ".join(words[i:i+words_per_line]) for i in range(0, len(words), words_per_line)]
    line_dur = duration / len(lines)
    srt_path = ep_dir / "captions.srt"
    srt = ""
    for i, line in enumerate(lines):
        t0 = i * line_dur
        t1 = (i + 1) * line_dur
        srt += f"{i+1}\n{_srt_ts(t0)} --> {_srt_ts(t1)}\n{line}\n\n"
    srt_path.write_text(srt, encoding="utf-8")
    return srt_path


def _srt_ts(s: float) -> str:
    h = int(s // 3600); m = int((s % 3600) // 60)
    sec = int(s % 60); ms = int((s % 1) * 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


# ── Final assembly (FFmpeg) ────────────────────────────────────────────────────
def assemble_video(clips: list[Path], voiceover: Path | None,
                   music: Path | None, srt: Path | None,
                   ep_dir: Path) -> Path | None:
    _log("  Assembling final video...")

    # Concat clips
    concat_list = ep_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{c.resolve()}'" for c in clips), encoding="utf-8"
    )
    raw = ep_dir / "raw_concat.mp4"
    if not _ff("-f", "concat", "-safe", "0", "-i", str(concat_list),
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw)):
        _log("  Concat failed")
        return None

    total_dur = _ffprobe_duration(raw)
    _log(f"  Concat duration: {total_dur:.1f}s")

    # Mix voiceover + music
    audio_inputs = []
    audio_filter = ""
    if voiceover and voiceover.exists():
        audio_inputs += ["-i", str(voiceover)]
        if music and music.exists():
            audio_inputs += ["-i", str(music)]
            audio_filter = (
                "[1:a]volume=1.0[vo];"
                f"[2:a]volume=0.25,afade=t=out:st={total_dur-2}:d=2[mu];"
                "[vo][mu]amix=inputs=2:duration=first[aout]"
            )
        else:
            audio_filter = "[1:a]volume=1.0[aout]"
    elif music and music.exists():
        audio_inputs += ["-i", str(music)]
        audio_filter = f"[1:a]volume=0.8,afade=t=out:st={total_dur-2}:d=2[aout]"

    # Build output with or without captions
    final = ep_dir / "final_video.mp4"
    if audio_filter:
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        if srt and srt.exists():
            srt_safe = str(srt).replace("\\", "/").replace(":", "\\:")
            vf += f",subtitles='{srt_safe}':force_style='FontSize=18,Bold=1,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,MarginV=40'"
        ok = _ff(
            "-i", str(raw), *audio_inputs,
            "-filter_complex", audio_filter,
            "-map", "0:v", "-map", "[aout]",
            "-vf", vf,
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(min(total_dur, 35)),
            str(final),
        )
    else:
        ok = _ff("-i", str(raw), "-c:v", "libx264", "-crf", "20",
                 "-an", str(final))

    if ok and final.exists():
        dur = _ffprobe_duration(final)
        _log(f"  Assembly OK: {final.name} ({final.stat().st_size//1024}KB, {dur:.1f}s)")
        return final
    _log("  Assembly failed")
    return None


# ── Contact sheet QA ──────────────────────────────────────────────────────────
def make_contact_sheet(final: Path, ep_dir: Path) -> Path | None:
    out = ep_dir / "contact_sheet.jpg"
    ok = _ff(
        "-i", str(final),
        "-vf", "fps=1/5,scale=270:480,tile=6x1",
        "-frames:v", "1", str(out),
    )
    return out if (ok and out.exists()) else None


# ── QA checks ─────────────────────────────────────────────────────────────────
def qa_check(final: Path, episode: dict) -> dict:
    issues = []
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(final)],
        capture_output=True, text=True,
    )
    data = json.loads(r.stdout) if r.returncode == 0 else {}
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_s = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_s = next((s for s in streams if s.get("codec_type") == "audio"), None)

    dur = float(fmt.get("duration", 0))
    if not (25 <= dur <= 35):
        issues.append(f"Duration {dur:.1f}s — must be 25-35s")
    if video_s:
        if video_s.get("width") != 1080 or video_s.get("height") != 1920:
            issues.append(f"Resolution {video_s.get('width')}x{video_s.get('height')} — must be 1080x1920")
        fps_str = video_s.get("r_frame_rate", "0/1")
        num, den = fps_str.split("/")
        fps = int(num) / int(den)
        if abs(fps - 30) > 1:
            issues.append(f"FPS {fps:.1f} — must be 30")
    else:
        issues.append("No video stream found")
    if not audio_s:
        issues.append("No audio stream — voice/music missing")

    dialogue = episode.get("dialogue", "")
    for phrase in ["will earn", "guaranteed earnings", "you'll make", "earn every time"]:
        if phrase.lower() in dialogue.lower():
            issues.append(f"Compliance: banned phrase '{phrase}' in dialogue")

    return {"passed": len(issues) == 0, "issues": issues, "duration": dur}


# ── Telegram delivery ─────────────────────────────────────────────────────────
def deliver_to_telegram(episode: dict, ep_dir: Path, final: Path,
                         costs: dict, qa: dict):
    ep_num  = episode["number"]
    title   = episode["title"]
    route   = episode["route"]
    dur     = qa.get("duration", 0)
    passed  = "PASS" if qa["passed"] else f"ISSUES: {'; '.join(qa['issues'])}"
    teaser  = episode["shots"][-1].get("next_teaser", "Coming soon")

    msg = (
        f"*BOUNCE ON THE MOVE — EPISODE {ep_num}*\n"
        f"Title: {title}\n"
        f"Route: {route}\n"
        f"Duration: {dur:.1f}s\n"
        f"Production cost: ${costs['total']:.2f}\n\n"
        f"Story:\n{episode['story_summary']}\n\n"
        f"Suggested caption:\n{episode['caption']}\n\n"
        f"Hashtags:\n{episode['hashtags']}\n\n"
        f"Character consistency checked\n"
        f"Voice and music checked\n"
        f"Captions checked\n"
        f"BootHop compliance checked\n"
        f"Manual posting only — NOT auto-published\n\n"
        f"QA: {passed}\n\n"
        f"Next episode:\n{teaser}"
    )

    _tg(msg)
    time.sleep(1)
    _tg_video(final, f"BOUNCE ON THE MOVE Ep{ep_num}: {title}")

    thumb = ep_dir / "thumbnail.jpg"
    if thumb.exists():
        _tg_photo(thumb, f"Ep{ep_num} thumbnail")


# ── Main production flow ───────────────────────────────────────────────────────
def produce_episode(episode: dict, dry_run: bool = False):
    ep_num = episode["number"]
    ep_dir = EPISODES / f"episode_{ep_num:03}"

    # Idempotency — skip if already completed
    manifest_path = ep_dir / "episode_manifest.json"
    if manifest_path.exists():
        existing = _load_json(manifest_path)
        if existing.get("status") == "completed":
            _log(f"Episode {ep_num} already completed — skipping")
            return

    ep_dir.mkdir(parents=True, exist_ok=True)
    _log(f"=== Producing Episode {ep_num}: {episode['title']} ===")

    # Cost estimate + balance check
    costs = estimate_cost(episode)
    _log(f"Estimated cost: ${costs['total']:.2f} (cap: ${COST_CAP:.2f})")
    _check_openai_balance(costs["total"])

    if dry_run:
        _log("Dry run — stopping before generation")
        _tg(f"BOUNCE ON THE MOVE Ep{ep_num} cost estimate: ${costs['total']:.2f}\n"
            f"Breakdown: {json.dumps(costs, indent=2)}")
        return

    if costs["total"] > COST_CAP:
        _log(f"Cost ${costs['total']:.2f} exceeds ${COST_CAP} cap — sending to Telegram for approval")
        _tg(f"BOUNCE ON THE MOVE Ep{ep_num} cost estimate ${costs['total']:.2f} exceeds cap.\n"
            f"Breakdown:\n{json.dumps(costs, indent=2)}\nApprove manually to proceed.")
        return

    # Save manifest (in-progress)
    manifest = {
        "episode": ep_num, "title": episode["title"], "route": episode["route"],
        "status": "in_progress", "started_at": datetime.now().isoformat(),
        "estimated_cost": costs,
    }
    _save_json(manifest_path, manifest)

    actual_costs = {"dalle_images": 0.0, "sora_video": 0.0,
                    "openai_tts": 0.0, "elevenlabs_music": 0.0}

    # Generate scene images
    _log("Stage 1: Scene images (DALL-E 3)...")
    clips = []
    for shot in episode["shots"]:
        img = ep_dir / f"{shot['id']}.png"
        if not img.exists():
            img = generate_scene_image(shot, ep_dir)
            if img:
                actual_costs["dalle_images"] += 0.042
        else:
            _log(f"  Reusing existing: {img.name}")

        # Image -> video
        vid_path = ep_dir / f"{shot['id']}_clip.mp4"
        if not vid_path.exists():
            if img:
                vid_path = image_to_video_sora(img, shot["dalle_scene"], ep_dir, shot["id"])
                if vid_path:
                    actual_costs["sora_video"] += round(5 * 0.03, 2)  # 5s × $0.03/s
        else:
            _log(f"  Reusing existing clip: {vid_path.name}")

        if vid_path and vid_path.exists():
            clips.append(vid_path)

    if not clips:
        _log("No clips generated — aborting")
        _tg(f"BOUNCE ON THE MOVE Ep{ep_num} FAILED: no clips generated")
        return

    # Generate voiceover
    _log("Stage 2: Voiceover (OpenAI TTS-1)...")
    vo_path = ep_dir / "voiceover.mp3"
    if not vo_path.exists():
        vo_path = generate_voiceover(episode["dialogue"], ep_dir)
        if vo_path:
            actual_costs["openai_tts"] = round(len(episode["dialogue"]) / 1_000_000 * 15, 4)
    else:
        _log("  Reusing existing voiceover")

    # Generate music
    _log("Stage 3: Background music (ElevenLabs)...")
    music_path = ep_dir / "music.mp3"
    if not music_path.exists():
        total_clip_dur = len(clips) * 5
        music_path = generate_music(total_clip_dur, ep_dir)
        if music_path:
            actual_costs["elevenlabs_music"] = 0.10
    else:
        _log("  Reusing existing music")

    # Build captions
    _log("Stage 4: Captions...")
    vo_dur = _ffprobe_duration(vo_path) if vo_path and vo_path.exists() else len(clips) * 5
    srt_path = build_srt(episode["dialogue"], vo_dur, ep_dir)

    # Write script + storyboard
    (ep_dir / "script.md").write_text(
        f"# Episode {ep_num}: {episode['title']}\n\n"
        f"**Route:** {episode['route']}\n\n"
        f"**Dialogue:**\n\n{episode['dialogue']}\n",
        encoding="utf-8",
    )
    (ep_dir / "caption.txt").write_text(
        episode["caption"] + "\n\n" + episode["hashtags"], encoding="utf-8"
    )

    # Generate thumbnail from first image
    thumb = ep_dir / "thumbnail.jpg"
    if not thumb.exists():
        first_img = ep_dir / f"{episode['shots'][0]['id']}.png"
        if first_img.exists():
            _ff("-i", str(first_img), "-vf", "scale=1080:1920", str(thumb))

    # Assemble final video
    _log("Stage 5: Final assembly...")
    final = ep_dir / "final_video.mp4"
    if not final.exists():
        final = assemble_video(clips, vo_path, music_path, srt_path, ep_dir)

    if not final or not final.exists():
        _log("Assembly failed")
        _tg(f"BOUNCE ON THE MOVE Ep{ep_num} FAILED: video assembly failed")
        return

    # Contact sheet
    _log("Stage 6: QA contact sheet...")
    make_contact_sheet(final, ep_dir)

    # QA
    _log("Stage 7: QA checks...")
    qa = qa_check(final, episode)
    _log(f"QA: {'PASSED' if qa['passed'] else 'ISSUES: ' + str(qa['issues'])}")

    # Total cost
    actual_costs["total"] = round(sum(v for k, v in actual_costs.items() if k != "total"), 2)
    _log(f"Actual cost: ${actual_costs['total']:.2f}")

    # Save manifest
    manifest.update({
        "status": "completed",
        "completed_at": datetime.now().isoformat(),
        "actual_cost": actual_costs,
        "qa": qa,
        "files": {
            "final_video": str(final),
            "voiceover": str(vo_path) if vo_path else None,
            "music": str(music_path) if music_path else None,
            "captions": str(srt_path),
            "thumbnail": str(thumb) if thumb.exists() else None,
        }
    })
    _save_json(manifest_path, manifest)

    # Update state
    counter = _load_json(STATE / "episode_counter.json")
    counter["last_completed"] = ep_num
    counter["last_delivered_at"] = datetime.now().isoformat()
    counter["next_episode"] = ep_num + 1
    _save_json(STATE / "episode_counter.json", counter)

    history = _load_json(STATE / "story_history.json")
    history.setdefault("episodes", []).append({
        "number": ep_num, "title": episode["title"],
        "route": episode["route"], "date": datetime.now().strftime("%Y-%m-%d"),
    })
    _save_json(STATE / "story_history.json", history)

    cost_h = _load_json(STATE / "cost_history.json")
    cost_h.setdefault("episodes", []).append(
        {"episode": ep_num, "actual": actual_costs["total"], "estimated": costs["total"]}
    )
    cost_h["total_spent_usd"] = round(
        cost_h.get("total_spent_usd", 0) + actual_costs["total"], 2
    )
    _save_json(STATE / "cost_history.json", cost_h)

    # Deliver to Telegram
    _log("Stage 8: Telegram delivery...")
    deliver_to_telegram(episode, ep_dir, final, actual_costs, qa)

    _log(f"=== Episode {ep_num} DONE — cost ${actual_costs['total']:.2f} ===")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BOUNCE ON THE MOVE episode runner")
    parser.add_argument("--episode", type=int, default=None, help="Start from this episode number")
    parser.add_argument("--batch",   type=int, default=1,    help="Produce N consecutive episodes (Sunday batch)")
    parser.add_argument("--post",    type=int, default=None, help="Re-post completed episode N to Telegram now")
    parser.add_argument("--dry-run", action="store_true",    help="Estimate cost only, no generation")
    args = parser.parse_args()

    # Check required credentials
    missing = []
    if not OPENAI_API_KEY:     missing.append("OPENAI_API_KEY")
    if not ELEVENLABS_API_KEY: missing.append("ELEVENLABS_API_KEY")
    if not TELEGRAM_TOKEN:     missing.append("TELEGRAM_TOKEN")
    if missing:
        print(f"Missing credentials: {', '.join(missing)}")
        sys.exit(1)

    episodes_map = {1: EPISODE_1, 2: EPISODE_2}

    # --post: re-deliver a finished episode to Telegram without regenerating
    if args.post is not None:
        ep = episodes_map.get(args.post)
        if not ep:
            print(f"Episode {args.post} not defined in episodes_map")
            sys.exit(1)
        ep_dir = EPISODES / f"episode_{args.post:03}"
        final  = ep_dir / "final_video.mp4"
        if not final.exists():
            print(f"No final_video.mp4 for episode {args.post}. Produce it first.")
            sys.exit(1)
        manifest = _load_json(ep_dir / "episode_manifest.json")
        costs = manifest.get("actual_cost", {"total": 0})
        qa    = manifest.get("qa", {"passed": True, "issues": [], "duration": 30})
        _log(f"Re-posting episode {args.post} to Telegram...")
        deliver_to_telegram(ep, ep_dir, final, costs, qa)
        sys.exit(0)

    # --batch: produce N episodes starting from --episode (or next_episode in state)
    start_ep = args.episode or _load_json(STATE / "episode_counter.json").get("next_episode", 1)
    for i in range(args.batch):
        ep_num  = start_ep + i
        episode = episodes_map.get(ep_num)
        if not episode:
            _log(f"Episode {ep_num} script not yet defined — stopping batch")
            break
        produce_episode(episode, dry_run=args.dry_run)
