"""
BOUNCE ON THE MOVE — Episode Runner
Produces one episode end-to-end and delivers to Telegram.

Usage:
    python episode_runner.py              # produce next episode
    python episode_runner.py --episode 1  # reproduce specific episode
    python episode_runner.py --batch 2    # produce 2 consecutive episodes (Sunday run)
    python episode_runner.py --post 1     # re-send finished episode 1 to Telegram
    python episode_runner.py --dry-run    # estimate cost only, no generation
    python episode_runner.py --force      # re-produce even if marked completed
"""

import argparse, json, os, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
CARTOON  = Path(__file__).parent.parent
PIPELINE = CARTOON.parent
BIBLE    = CARTOON / "series_bible"
STATE    = CARTOON / "state"
EPISODES = CARTOON / "episodes"

sys.path.insert(0, str(PIPELINE))
from config import (
    ANTHROPIC_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY,
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DATA,
)

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


def _b64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode()


def _all_lines(shots: list) -> list[dict]:
    """Flatten all dialogue lines from all shots into one list."""
    return [line for shot in shots for line in shot.get("lines", [])]


def _full_dialogue_text(shots: list) -> str:
    return " ".join(l["text"] for l in _all_lines(shots))


# ── Character visual constants ─────────────────────────────────────────────────
_STYLE = (
    "3D animated Pixar-quality film style, original characters, "
    "premium cinema render, warm cinematic lighting, no text in image, "
    "NOT resembling Garfield, Tom, or any copyrighted character"
)
_BD = "slim orange tabby cat named Bounce, vivid green eyes, grey zip-up hoodie and headphones around neck, very expressive face"
_DD = "slightly stockier orange-ginger cat named Dash, round wire-frame glasses, navy blue crew-neck jumper, calm knowing expression"

def _scene(desc: str, chars: str = "both") -> str:
    who = f"{_BD} and {_DD}" if chars == "both" else (_BD if chars == "bounce" else _DD)
    return f"{_STYLE}, {who}, {desc}"


# ── Episode voices ─────────────────────────────────────────────────────────────
VOICES = {"bounce": "echo", "dash": "onyx"}


# ── EPISODE 1: THE DHL RECEIPT ─────────────────────────────────────────────────
EPISODE_1 = {
    "number": 1,
    "title": "THE DHL RECEIPT",
    "route": "London flat — Saturday morning",
    "shots": [
        {
            "id": "s1_hook",
            "time": "0:00-0:05",
            "label": "Hook",
            "on_screen_text": "£89?!",
            "lines": [
                {"char": "bounce", "text": "Dash. DASH! Come see this receipt right now."},
            ],
            "dalle_scene": _scene(
                "Bounce holding a phone looking horrified, standing in a cosy London flat kitchen, "
                "morning light, cereal boxes on counter, Dash visible entering from hallway looking half-asleep",
            ),
        },
        {
            "id": "s2_problem",
            "time": "0:05-0:11",
            "label": "The Problem",
            "on_screen_text": "A FEW THINGS.",
            "lines": [
                {"char": "dash", "text": "What did you pack — a generator?"},
                {"char": "bounce", "text": "It's my mum's birthday tomorrow. She just needs a few things from home."},
            ],
            "dalle_scene": _scene(
                "Dash squinting at an enormous overfilled suitcase on the floor with a deadpan expression, "
                "Bounce standing next to it looking guilty, cosy London flat living room, morning light",
            ),
        },
        {
            "id": "s3_tension",
            "time": "0:11-0:17",
            "label": "The Tension",
            "on_screen_text": "BIRTHDAY IS TOMORROW.",
            "lines": [
                {"char": "bounce", "text": "Abeg help me think. Her birthday is TOMORROW."},
                {"char": "dash",   "text": "You should have thought about that before—"},
                {"char": "bounce", "text": "I KNOW. What do I do?!"},
            ],
            "dalle_scene": _scene(
                "Bounce pacing anxiously with hands on head, Dash sitting calmly on sofa eating cereal "
                "with a deadpan unbothered expression, cosy London flat, morning light",
            ),
        },
        {
            "id": "s4_idea",
            "time": "0:17-0:23",
            "label": "The Idea",
            "on_screen_text": "boothop.com",
            "lines": [
                {"char": "dash",   "text": "Is anyone going Manchester on BootHop today?"},
                {"char": "bounce", "text": "Boot... what?"},
                {"char": "dash",   "text": "Someone's always going your way, fam."},
            ],
            "dalle_scene": _scene(
                "Dash holding up his smartphone casually showing an app, Bounce leaning in confused and curious, "
                "both on sofa, warm living room light, Dash looking smug",
            ),
        },
        {
            "id": "s5_realisation",
            "time": "0:23-0:28",
            "label": "The Realisation",
            "on_screen_text": "VERIFIED ✓ MANCHESTER",
            "lines": [
                {"char": "bounce", "text": "There's someone leaving in TWO HOURS?! Verified?!"},
                {"char": "bounce", "text": "Let's GO!"},
            ],
            "dalle_scene": _scene(
                "Bounce with wide excited eyes, phone raised in triumph, jumping up from sofa, "
                "Dash watching calmly with a small smile, living room, bright morning light",
            ),
        },
        {
            "id": "s6_ending",
            "time": "0:28-0:33",
            "label": "Ending",
            "on_screen_text_sequence": ["MUMS GET THEIR PEPPER SOUP.", "BOOTHOP IT.", "boothop.com"],
            "next_teaser": "NEXT: Dash's cousin is visiting. With 7 bags.",
            "lines": [
                {"char": "bounce", "text": "Mum's getting her pepper soup. BootHop money!"},
                {"char": "dash",   "text": "You're welcome, by the way."},
            ],
            "dalle_scene": _scene(
                "Bounce at the front door grinning ear to ear, giving a thumbs up, "
                "Dash visible on sofa in background with arms folded and a satisfied smirk, "
                "a large suitcase by the door, golden morning light",
            ),
        },
    ],
    "caption": (
        "Bounce left his mum's birthday till the last minute. DHL wanted £89. "
        "Dash saved the day with BootHop. "
        "Someone's always going your way. boothop.com"
    ),
    "hashtags": (
        "#BootHop #BounceOnTheMove #DiasporaLife #NigerianBritish #UKNigerian "
        "#AfricanCommunity #SmartTravel #MumsKnowBest #LondonLife #CartoonComedy"
    ),
    "setting": "Bounce and Dash's flat, London",
    "story_summary": (
        "Bounce panics the night before his mum's birthday — the pepper soup ingredients need "
        "to reach Manchester and DHL wants £89. Dash casually suggests BootHop. A verified "
        "traveller leaves in two hours. Crisis averted. Bounce claims all the credit."
    ),
}

# ── EPISODE 2: THE COUSIN ──────────────────────────────────────────────────────
EPISODE_2 = {
    "number": 2,
    "title": "THE COUSIN",
    "route": "Lagos -> London -> same London flat",
    "shots": [
        {
            "id": "s1_hook",
            "time": "0:00-0:05",
            "label": "Hook",
            "on_screen_text": "TOMORROW.",
            "lines": [
                {"char": "dash",   "text": "Bounce... Tunde is coming to stay."},
                {"char": "bounce", "text": "Nice! When?"},
                {"char": "dash",   "text": "Tomorrow."},
            ],
            "dalle_scene": _scene(
                "Dash sitting on sofa staring at phone with a slowly dropping face, "
                "Bounce making tea in background completely unbothered, cosy London flat morning",
            ),
        },
        {
            "id": "s2_problem",
            "time": "0:05-0:11",
            "label": "The Problem",
            "on_screen_text": "SEVEN.",
            "lines": [
                {"char": "dash",   "text": "He says he's bringing a few things from home."},
                {"char": "bounce", "text": "How many bags?"},
                {"char": "dash",   "text": "Seven."},
            ],
            "dalle_scene": _scene(
                "Both staring at a phone screen together, Dash looking horrified, "
                "Bounce with a slowly widening expression of disbelief, cosy flat interior",
            ),
        },
        {
            "id": "s3_chaos",
            "time": "0:11-0:17",
            "label": "Airport Chaos",
            "on_screen_text": "PACK LIGHT. 😭",
            "lines": [
                {"char": "bounce", "text": "Na wetin be this?! Is that a FRIDGE?!"},
                {"char": "dash",   "text": "I told him to pack light..."},
            ],
            "dalle_scene": _scene(
                "Bounce and Dash standing at airport arrivals, both looking off-screen with enormous eyes, "
                "mouths open in shock, airport terminal background, dramatic lighting, "
                "a comically massive tower of suitcases partially visible at the edge of frame",
            ),
        },
        {
            "id": "s4_stuck",
            "time": "0:17-0:23",
            "label": "The Problem",
            "on_screen_text": "NOT A REMOVAL VAN.",
            "lines": [
                {"char": "bounce", "text": "The Uber driver said he's not a removal van."},
                {"char": "dash",   "text": "So what do we do with five bags we can't carry?"},
                {"char": "bounce", "text": "...I know a guy. BootHop."},
            ],
            "dalle_scene": _scene(
                "Bounce and Dash outside airport surrounded by an absurd pile of suitcases, "
                "Bounce suddenly looking confident holding up his phone, Dash looking surprised, "
                "daytime, London Heathrow exterior",
            ),
        },
        {
            "id": "s5_reversal",
            "time": "0:23-0:28",
            "label": "The Role Reversal",
            "on_screen_text": "DIDN'T YOU JUST LEARN ABOUT THIS?",
            "lines": [
                {"char": "dash",   "text": "Wait — is that BootHop?"},
                {"char": "bounce", "text": "Someone's always going your way, fam."},
            ],
            "dalle_scene": _scene(
                "Bounce looking extremely smug holding phone out like a pro, "
                "Dash staring at him with one eyebrow raised in disbelief, "
                "airport exterior, bags stacked behind them",
            ),
        },
        {
            "id": "s6_ending",
            "time": "0:28-0:33",
            "label": "Ending",
            "on_screen_text_sequence": ["BAGS DELIVERED.", "BOOTHOP IT.", "boothop.com"],
            "next_teaser": "NEXT: Bounce wants to MAKE money on BootHop. What could go wrong?",
            "lines": [
                {"char": "dash",   "text": "You literally learned about BootHop yesterday."},
                {"char": "bounce", "text": "And I'm already a pro. You're welcome."},
            ],
            "dalle_scene": _scene(
                "Both collapsed on sofa looking exhausted but happy, "
                "a ridiculous number of suitcases neatly stacked in the background, "
                "golden hour flat light, Bounce looking insufferably smug, Dash shaking his head",
            ),
        },
    ],
    "caption": (
        "Dash's cousin came from Lagos with 7 bags. The Uber driver said no. "
        "Bounce — who just discovered BootHop yesterday — stepped up. "
        "Someone's always going your way. boothop.com"
    ),
    "hashtags": (
        "#BootHop #BounceOnTheMove #DiasporaLife #NigerianBritish #LagosToLondon "
        "#AfricanCommunity #TooMuchLuggage #CartoonComedy #UKNigerian #LondonLife"
    ),
    "setting": "Bounce and Dash's flat + Heathrow Airport",
    "story_summary": (
        "Dash's cousin Tunde arrives from Lagos with 7 bags. The Uber refuses. "
        "Bounce — who only just learned about BootHop in Ep1 — confidently steps up and finds "
        "a verified traveller to handle the overflow. Role reversal complete. "
        "Dash cannot believe what he's witnessing."
    ),
}


# ── Cost estimator ─────────────────────────────────────────────────────────────
def estimate_cost(episode: dict) -> dict:
    n_scenes   = len(episode["shots"])
    total_chars = sum(len(l["text"]) for l in _all_lines(episode["shots"]))
    costs = {
        "image_gen":        round(n_scenes * 0.042, 2),       # gpt-image-1 medium
        "sora_video":       round(n_scenes * 5 * 0.03, 2),    # $0.03/sec × 5s
        "openai_tts":       round(total_chars / 1_000_000 * 15, 4),
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
    try:
        r = _rq.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": shot["dalle_scene"],
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


# ── Multi-character voiceover (OpenAI TTS-1) ──────────────────────────────────
def generate_voiceover_lines(shots: list, ep_dir: Path) -> Path | None:
    import requests as _rq
    lines = _all_lines(shots)
    if not lines:
        return None

    _log(f"  Generating voiceover ({len(lines)} lines, dual-character TTS-1)...")

    # Generate 250ms silence for pauses between speakers
    silence = ep_dir / "vo_silence.mp3"
    _ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", "0.25", "-acodec", "libmp3lame", "-q:a", "9", str(silence))

    segments = []
    for i, line in enumerate(lines):
        seg = ep_dir / f"vo_{i:03}.mp3"
        if seg.exists():
            segments.append(seg)
            continue
        voice = VOICES.get(line["char"], "echo")
        try:
            r = _rq.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "tts-1", "input": line["text"],
                      "voice": voice, "speed": 0.95},
                timeout=30,
            )
            r.raise_for_status()
            seg.write_bytes(r.content)
            segments.append(seg)
            _log(f"    [{line['char']:6}] {line['text'][:55]}...")
        except Exception as e:
            _log(f"  Line TTS failed (line {i}): {e}")

    if not segments:
        return None

    out = ep_dir / "voiceover.mp3"
    if len(segments) == 1:
        shutil.copy(segments[0], out)
        return out

    # Interleave silence between lines then concat
    concat_entries = []
    for i, seg in enumerate(segments):
        concat_entries.append(f"file '{seg.resolve()}'")
        if i < len(segments) - 1:
            concat_entries.append(f"file '{silence.resolve()}'")

    concat_file = ep_dir / "vo_concat.txt"
    concat_file.write_text("\n".join(concat_entries), encoding="utf-8")

    ok = _ff("-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-acodec", "libmp3lame", "-q:a", "4", str(out))
    if ok and out.exists():
        _log(f"  Voiceover combined: {out.stat().st_size//1024}KB")
        return out
    return None


# ── Background music (ElevenLabs + BootHop vocal stab) ────────────────────────
def generate_music(duration_s: float, ep_dir: Path) -> Path | None:
    import requests as _rq
    prompt = (
        "Upbeat Afrobeats and Amapiano fusion instrumental, 110 BPM, warm log-drum, "
        "bouncy bassline, smooth modern RnB chords, vibrant playful energy, "
        "no lyrics, catchy and unique, perfect for a fun animated short"
    )
    _log(f"  Generating background music ({duration_s:.0f}s)...")
    try:
        # Step 1 — generate up to 22s from ElevenLabs
        r = _rq.post(
            "https://api.elevenlabs.io/v1/sound-generation",
            headers={"xi-api-key": ELEVENLABS_API_KEY,
                     "Content-Type": "application/json"},
            json={"text": prompt, "duration_seconds": min(duration_s, 22),
                  "prompt_influence": 0.3},
            timeout=90,
        )
        if r.status_code != 200:
            _log(f"  Music API returned {r.status_code} — skipping")
            return None

        raw_music = ep_dir / "music_raw.mp3"
        raw_music.write_bytes(r.content)
        raw_dur = _ffprobe_duration(raw_music)
        _log(f"  Music base: {raw_dur:.1f}s")

        # Step 2 — loop to fill full episode duration
        looped = ep_dir / "music_looped.mp3"
        _ff("-stream_loop", "-1", "-i", str(raw_music),
            "-t", str(duration_s + 3), "-acodec", "libmp3lame", "-q:a", "4",
            str(looped))
        if not looped.exists():
            looped = raw_music

        # Step 3 — generate "BootHop!" vocal stab (OpenAI TTS, upbeat)
        stab_path = ep_dir / "music_stab.mp3"
        try:
            rs = _rq.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "tts-1", "input": "BootHop!", "voice": "nova", "speed": 1.1},
                timeout=20,
            )
            rs.raise_for_status()
            stab_path.write_bytes(rs.content)
        except Exception as e:
            _log(f"  BootHop stab failed: {e}")
            stab_path = None

        # Step 4 — mix stab into music near the end
        out = ep_dir / "music.mp3"
        if stab_path and stab_path.exists():
            stab_offset_ms = max(0, int((duration_s - 4) * 1000))
            ok = _ff(
                "-i", str(looped), "-i", str(stab_path),
                "-filter_complex",
                f"[1:a]adelay={stab_offset_ms}|{stab_offset_ms},volume=0.9[stab];"
                f"[0:a][stab]amix=inputs=2:duration=first[aout]",
                "-map", "[aout]", "-acodec", "libmp3lame", "-q:a", "4",
                str(out),
            )
            if ok and out.exists():
                _log(f"  Music OK with BootHop stab ({out.stat().st_size//1024}KB)")
                return out

        # Fallback: just the looped track
        shutil.copy(looped, out)
        _log(f"  Music OK (no stab, {out.stat().st_size//1024}KB)")
        return out

    except Exception as e:
        _log(f"  Music failed: {e}")
        return None


# ── Image -> 5s video clip (OpenAI Sora with fallback) ────────────────────────
def image_to_video_sora(image_path: Path, prompt: str, ep_dir: Path, shot_id: str) -> Path | None:
    import requests as _rq
    _log(f"  Sora video generation: {shot_id}...")
    try:
        body = {"model": "sora-1080p", "prompt": prompt, "duration": 5,
                "size": "1080x1920", "n": 1}
        if image_path and image_path.exists():
            body["image"] = f"data:image/png;base64,{_b64(image_path)}"

        r = _rq.post(
            "https://api.openai.com/v1/video/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json=body, timeout=60,
        )
        if r.status_code == 400 and "image" in (r.text or "").lower():
            body.pop("image", None)
            r = _rq.post("https://api.openai.com/v1/video/generations",
                         headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                                  "Content-Type": "application/json"},
                         json=body, timeout=60)

        if r.status_code not in (200, 202):
            _log(f"  Sora: API error {r.status_code} — falling back")
            return _still_to_video(image_path, ep_dir, shot_id)

        data = r.json()
        if data.get("data") and data["data"][0].get("url"):
            url = data["data"][0]["url"]
            vid_data = _rq.get(url, timeout=120).content
            out = ep_dir / f"{shot_id}_clip.mp4"
            out.write_bytes(vid_data)
            _log(f"  Sora OK: {out.name}")
            return out

        gen_id = data.get("id")
        if not gen_id:
            return _still_to_video(image_path, ep_dir, shot_id)

        for attempt in range(40):
            time.sleep(15)
            sr = _rq.get(f"https://api.openai.com/v1/video/generations/{gen_id}",
                         headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, timeout=15)
            sd = sr.json()
            state = sd.get("status", "")
            _log(f"  Sora: {state} ({attempt+1}/40)")
            if state == "completed":
                url = ((sd.get("data") or [{}])[0]).get("url", "")
                if url:
                    vid_data = _rq.get(url, timeout=120).content
                    out = ep_dir / f"{shot_id}_clip.mp4"
                    out.write_bytes(vid_data)
                    _log(f"  Sora OK: {out.name}")
                    return out
                break
            elif state in ("failed", "error", "cancelled"):
                _log(f"  Sora failed: {sd.get('error','unknown')}")
                break

        return _still_to_video(image_path, ep_dir, shot_id)
    except Exception as e:
        _log(f"  Sora error: {e}")
        return _still_to_video(image_path, ep_dir, shot_id)


def _still_to_video(img: Path, ep_dir: Path, shot_id: str, duration: int = 5) -> Path | None:
    out = ep_dir / f"{shot_id}_clip.mp4"
    ok = _ff(
        "-loop", "1", "-i", str(img),
        "-vf", (
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"zoompan=z='min(zoom+0.0015,1.3)':d={duration*30}:s=1080x1920"
        ),
        "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p",
        "-r", "30", str(out),
    )
    if ok and out.exists():
        _log(f"  Still+zoom fallback OK: {out.name}")
        return out
    _log(f"  Still->video failed for {shot_id}")
    return None


# ── Caption SRT builder ───────────────────────────────────────────────────────
def build_srt(dialogue: str, duration: float, ep_dir: Path) -> Path:
    words = dialogue.split()
    if not words:
        words = ["BootHop"]
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

    audio_inputs, audio_filter = [], ""
    if voiceover and voiceover.exists():
        audio_inputs += ["-i", str(voiceover)]
        if music and music.exists():
            audio_inputs += ["-i", str(music)]
            audio_filter = (
                "[1:a]volume=1.0[vo];"
                f"[2:a]volume=0.22,afade=t=out:st={max(0,total_dur-2)}:d=2[mu];"
                "[vo][mu]amix=inputs=2:duration=first[aout]"
            )
        else:
            audio_filter = "[1:a]volume=1.0[aout]"
    elif music and music.exists():
        audio_inputs += ["-i", str(music)]
        audio_filter = f"[1:a]volume=0.8,afade=t=out:st={max(0,total_dur-2)}:d=2[aout]"

    final = ep_dir / "final_video.mp4"
    if audio_filter:
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        if srt and srt.exists():
            srt_safe = str(srt).replace("\\", "/").replace(":", "\\:")
            vf += (
                f",subtitles='{srt_safe}':force_style='"
                "FontSize=18,Bold=1,PrimaryColour=&HFFFFFF,"
                "OutlineColour=&H000000,Outline=2,MarginV=40'"
            )
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
        ok = _ff("-i", str(raw), "-c:v", "libx264", "-crf", "20", "-an", str(final))

    if ok and final.exists():
        dur = _ffprobe_duration(final)
        _log(f"  Assembly OK: {final.name} ({final.stat().st_size//1024}KB, {dur:.1f}s)")
        return final
    _log("  Assembly failed")
    return None


# ── Contact sheet QA ──────────────────────────────────────────────────────────
def make_contact_sheet(final: Path, ep_dir: Path) -> Path | None:
    out = ep_dir / "contact_sheet.jpg"
    ok = _ff("-i", str(final), "-vf", "fps=1/5,scale=270:480,tile=6x1",
             "-frames:v", "1", str(out))
    return out if (ok and out.exists()) else None


# ── QA checks ─────────────────────────────────────────────────────────────────
def qa_check(final: Path, episode: dict) -> dict:
    issues = []
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(final)],
        capture_output=True, text=True,
    )
    data   = json.loads(r.stdout) if r.returncode == 0 else {}
    streams = data.get("streams", [])
    fmt    = data.get("format", {})
    video_s = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_s = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(fmt.get("duration", 0))
    if not (25 <= dur <= 36):
        issues.append(f"Duration {dur:.1f}s — must be 25-36s")
    if video_s:
        if video_s.get("width") != 1080 or video_s.get("height") != 1920:
            issues.append(f"Resolution {video_s.get('width')}x{video_s.get('height')} — must be 1080x1920")
    else:
        issues.append("No video stream found")
    if not audio_s:
        issues.append("No audio stream — voice/music missing")
    all_text = _full_dialogue_text(episode["shots"])
    for phrase in ["will earn", "guaranteed earnings", "you'll make", "earn every time"]:
        if phrase.lower() in all_text.lower():
            issues.append(f"Compliance: banned phrase '{phrase}'")
    return {"passed": len(issues) == 0, "issues": issues, "duration": dur}


# ── Telegram delivery ─────────────────────────────────────────────────────────
def deliver_to_telegram(episode: dict, ep_dir: Path, final: Path,
                        costs: dict, qa: dict):
    ep_num = episode["number"]
    dur    = qa.get("duration", 0)
    passed = "PASS" if qa["passed"] else f"ISSUES: {'; '.join(qa['issues'])}"
    teaser = episode["shots"][-1].get("next_teaser", "Coming soon")
    msg = (
        f"*BOUNCE ON THE MOVE — EP{ep_num}: {episode['title']}*\n"
        f"Setting: {episode['setting']}\n"
        f"Duration: {dur:.1f}s  |  Cost: ${costs.get('total', 0):.2f}\n\n"
        f"Story:\n{episode['story_summary']}\n\n"
        f"Caption:\n{episode['caption']}\n\n"
        f"Hashtags:\n{episode['hashtags']}\n\n"
        f"QA: {passed}\n"
        f"Next: {teaser}"
    )
    _tg(msg)
    time.sleep(1)
    _tg_video(final, f"Ep{ep_num}: {episode['title']}")
    thumb = ep_dir / "thumbnail.jpg"
    if thumb.exists():
        _tg_photo(thumb, f"Ep{ep_num} thumbnail")


# ── Main production flow ───────────────────────────────────────────────────────
def produce_episode(episode: dict, dry_run: bool = False, force: bool = False):
    ep_num = episode["number"]
    ep_dir = EPISODES / f"episode_{ep_num:03}"

    manifest_path = ep_dir / "episode_manifest.json"
    if not force and manifest_path.exists():
        existing = _load_json(manifest_path)
        if existing.get("status") == "completed":
            _log(f"Episode {ep_num} already completed — skipping (use --force to redo)")
            return

    ep_dir.mkdir(parents=True, exist_ok=True)
    _log(f"=== Producing Episode {ep_num}: {episode['title']} ===")

    costs = estimate_cost(episode)
    _log(f"Estimated cost: ${costs['total']:.2f} (cap: ${COST_CAP:.2f})")
    _check_openai_balance(costs["total"])

    if dry_run:
        _tg(f"BOUNCE Ep{ep_num} estimate: ${costs['total']:.2f}\n{json.dumps(costs, indent=2)}")
        return

    if costs["total"] > COST_CAP:
        _tg(f"BOUNCE Ep{ep_num} cost ${costs['total']:.2f} exceeds cap. Approve manually.")
        return

    manifest = {
        "episode": ep_num, "title": episode["title"], "route": episode["route"],
        "status": "in_progress", "started_at": datetime.now().isoformat(),
        "estimated_cost": costs,
    }
    _save_json(manifest_path, manifest)
    actual_costs = {"image_gen": 0.0, "sora_video": 0.0,
                    "openai_tts": 0.0, "elevenlabs_music": 0.0}

    # Stage 1 — Scene images
    _log("Stage 1: Scene images (gpt-image-1)...")
    clips = []
    for shot in episode["shots"]:
        img = ep_dir / f"{shot['id']}.png"
        if not img.exists():
            img = generate_scene_image(shot, ep_dir)
            if img:
                actual_costs["image_gen"] += 0.042
        else:
            _log(f"  Reusing: {img.name}")

        vid_path = ep_dir / f"{shot['id']}_clip.mp4"
        if not vid_path.exists():
            if img:
                vid_path = image_to_video_sora(img, shot["dalle_scene"], ep_dir, shot["id"])
                if vid_path:
                    actual_costs["sora_video"] += round(5 * 0.03, 2)
        else:
            _log(f"  Reusing clip: {vid_path.name}")

        if vid_path and vid_path.exists():
            clips.append(vid_path)

    if not clips:
        _log("No clips generated — aborting")
        _tg(f"BOUNCE Ep{ep_num} FAILED: no clips generated")
        return

    # Stage 2 — Dual-character voiceover
    _log("Stage 2: Voiceover (dual-character TTS-1)...")
    vo_path = ep_dir / "voiceover.mp3"
    if not vo_path.exists():
        vo_path = generate_voiceover_lines(episode["shots"], ep_dir)
        if vo_path:
            total_chars = sum(len(l["text"]) for l in _all_lines(episode["shots"]))
            actual_costs["openai_tts"] = round(total_chars / 1_000_000 * 15, 4)
    else:
        _log("  Reusing voiceover")

    # Stage 3 — Music with BootHop stab
    _log("Stage 3: Music (ElevenLabs + BootHop stab)...")
    music_path = ep_dir / "music.mp3"
    if not music_path.exists():
        vo_dur = _ffprobe_duration(vo_path) if vo_path and vo_path.exists() else len(clips) * 5
        target_dur = max(len(clips) * 5, vo_dur + 2)
        music_path = generate_music(target_dur, ep_dir)
        if music_path:
            actual_costs["elevenlabs_music"] = 0.10
    else:
        _log("  Reusing music")

    # Stage 4 — Captions
    _log("Stage 4: Captions...")
    full_text = _full_dialogue_text(episode["shots"])
    vo_dur = _ffprobe_duration(vo_path) if vo_path and vo_path.exists() else len(clips) * 5
    srt_path = build_srt(full_text, vo_dur, ep_dir)

    # Write script file
    script_lines = "\n".join(
        f"**{l['char'].title()}:** {l['text']}"
        for l in _all_lines(episode["shots"])
    )
    (ep_dir / "script.md").write_text(
        f"# Episode {ep_num}: {episode['title']}\n\n"
        f"**Setting:** {episode['setting']}\n\n"
        f"## Script\n\n{script_lines}\n",
        encoding="utf-8",
    )
    (ep_dir / "caption.txt").write_text(
        episode["caption"] + "\n\n" + episode["hashtags"], encoding="utf-8"
    )

    # Thumbnail
    thumb = ep_dir / "thumbnail.jpg"
    if not thumb.exists():
        first_img = ep_dir / f"{episode['shots'][0]['id']}.png"
        if first_img.exists():
            _ff("-i", str(first_img), "-vf", "scale=1080:1920", str(thumb))

    # Stage 5 — Assemble
    _log("Stage 5: Final assembly...")
    final = ep_dir / "final_video.mp4"
    if not final.exists():
        final = assemble_video(clips, vo_path, music_path, srt_path, ep_dir)

    if not final or not final.exists():
        _tg(f"BOUNCE Ep{ep_num} FAILED: assembly failed")
        return

    # Stage 6 — QA
    _log("Stage 6: QA...")
    make_contact_sheet(final, ep_dir)
    qa = qa_check(final, episode)
    _log(f"QA: {'PASSED' if qa['passed'] else 'ISSUES: ' + str(qa['issues'])}")

    actual_costs["total"] = round(sum(v for k, v in actual_costs.items() if k != "total"), 2)
    _log(f"Actual cost: ${actual_costs['total']:.2f}")

    manifest.update({
        "status": "completed",
        "completed_at": datetime.now().isoformat(),
        "actual_cost": actual_costs,
        "qa": qa,
    })
    _save_json(manifest_path, manifest)

    counter = _load_json(STATE / "episode_counter.json")
    counter["last_completed"] = ep_num
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
    cost_h["total_spent_usd"] = round(cost_h.get("total_spent_usd", 0) + actual_costs["total"], 2)
    _save_json(STATE / "cost_history.json", cost_h)

    # Stage 7 — Deliver
    _log("Stage 7: Telegram delivery...")
    deliver_to_telegram(episode, ep_dir, final, actual_costs, qa)
    _log(f"=== Episode {ep_num} DONE — ${actual_costs['total']:.2f} ===")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BOUNCE ON THE MOVE episode runner")
    parser.add_argument("--episode", type=int, default=None)
    parser.add_argument("--batch",   type=int, default=1,    help="Produce N consecutive episodes")
    parser.add_argument("--post",    type=int, default=None, help="Re-post completed episode N to Telegram")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force",   action="store_true",    help="Re-produce even if already completed")
    args = parser.parse_args()

    missing = []
    if not OPENAI_API_KEY:     missing.append("OPENAI_API_KEY")
    if not ELEVENLABS_API_KEY: missing.append("ELEVENLABS_API_KEY")
    if not TELEGRAM_TOKEN:     missing.append("TELEGRAM_TOKEN")
    if missing:
        print(f"Missing credentials: {', '.join(missing)}")
        sys.exit(1)

    episodes_map = {1: EPISODE_1, 2: EPISODE_2}

    if args.post is not None:
        ep = episodes_map.get(args.post)
        if not ep:
            print(f"Episode {args.post} not defined")
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

    start_ep = args.episode or _load_json(STATE / "episode_counter.json").get("next_episode", 1)
    for i in range(args.batch):
        ep_num  = start_ep + i
        episode = episodes_map.get(ep_num)
        if not episode:
            _log(f"Episode {ep_num} not yet defined — stopping batch")
            break
        produce_episode(episode, dry_run=args.dry_run, force=args.force)
