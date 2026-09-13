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
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DATA, ASSETS,
    KLING_API_KEY, KLING_API_BASE, PERPLEXITY_KEY,
)

COST_CAP = 5.00

# ── Character reference images ─────────────────────────────────────────────────
CHAR_REF_BOUNCE = BIBLE / "character_refs" / "bounce_ref.png"      # BOUNCE — big orange cat
CHAR_REF_DASH   = BIBLE / "character_refs" / "whatsapp_a_2s.png"   # DASH   — grey-blue mouse

# ── Real BootHop asset library (for mixing into cartoon) ──────────────────────
REAL_ASSETS = {
    "airport_arrivals":  ASSETS / "user_clips" / "airport_travellers_departures.jpeg",
    "aerial_london_1":   ASSETS / "user_clips" / "hook_aerial_uk_1.jpeg",
    "aerial_london_2":   ASSETS / "user_clips" / "hook_aerial_uk_2.jpeg",
    "aerial_london_3":   ASSETS / "user_clips" / "hook_aerial_uk_3.jpeg",
    "lesson_journey":    ASSETS / "user_clips" / "lesson_boothop_your_journey.jpeg",
    "lesson_sign":       ASSETS / "user_clips" / "lesson_boothop_logo_sign.jpeg",
    "boothop_app":       ASSETS / "website_screens" / "boothop_homepage.jpeg",
}

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
    "3D animated Pixar-quality film style, original BootHop characters, "
    "premium cinema render, warm cinematic lighting, no text in image"
)
# BOUNCE — the BIG orange cat (primary character)
_BOUNCE = (
    "large fluffy orange tabby cat named BOUNCE, vivid bright green eyes, "
    "bold orange fur with darker tabby stripes, white muzzle and whiskers, "
    "big expressive face, chunky friendly build"
)
# DASH — the SMALL grey-blue mouse (second character)
_DASH = (
    "small grey-blue anthropomorphic mouse named DASH, big round grey ears, "
    "slim compact build, much smaller than BOUNCE, quick confident posture, "
    "always carrying a travel bag or small box"
)

def _scene(desc: str, chars: str = "both") -> str:
    who = f"{_BOUNCE} and {_DASH}" if chars == "both" else (_BOUNCE if chars == "bounce" else _DASH)
    return f"{_STYLE}, {who}, {desc}"

def _speaker_prompt(char: str, ctx: str) -> str:
    """Solo close-up prompt for a speaking character — only that character in frame."""
    desc = _BOUNCE if char == "bounce" else _DASH
    other = "DASH" if char == "bounce" else "BOUNCE"
    return (
        f"{_STYLE}, {desc}, {ctx}, mouth open and speaking expressively, "
        f"close-up or medium shot, only {char.upper()} visible in frame, "
        f"{other} is NOT in this shot, no other character present"
    )

def _speaking_motion(char: str, ctx: str) -> str:
    """Kling motion prompt — only the named character speaks, mouth animates."""
    name = "BOUNCE (large orange tabby cat)" if char == "bounce" else "DASH (small grey-blue mouse)"
    other = "DASH" if char == "bounce" else "BOUNCE"
    return (
        f"{name} speaking with natural expressive mouth movement and lip sync, "
        f"{ctx}, animated speech, only {char.upper()} visible, "
        f"{other} is completely absent from frame, smooth natural talking animation"
    )


# ── Episode voices — BOUNCE: warm dramatic Nigerian male, DASH: quick cheeky energetic ──
VOICES = {"bounce": "onyx", "dash": "echo"}


# ── EPISODE 1: THE DHL RECEIPT ─────────────────────────────────────────────────
EPISODE_1 = {
    "number": 1,
    "title": "THE DHL RECEIPT",
    "route": "London flat — Saturday morning",
    "shots": [
        {
            "id": "s1_hook",
            "label": "Hook",
            "on_screen_text": "£89?!",
            "lines": [
                {"char": "bounce", "text": "Dash. DASH! Come see this receipt right now.",
                 "speaker_context": "holding phone with horrified expression, eyes wide, London flat kitchen morning light"},
            ],
        },
        {
            "id": "s2_problem",
            "label": "The Problem",
            "on_screen_text": "A FEW THINGS.",
            "lines": [
                {"char": "dash",   "text": "What did you pack — a generator?",
                 "speaker_context": "deadpan squint, arms folded, half-amused smirk"},
                {"char": "bounce", "text": "It's my mum's birthday tomorrow. She just needs a few things from home.",
                 "speaker_context": "looking guilty, gesturing awkwardly, sheepish grin"},
            ],
        },
        {
            "id": "s3_tension",
            "label": "The Tension",
            "on_screen_text": "BIRTHDAY IS TOMORROW.",
            "lines": [
                {"char": "bounce", "text": "Abeg help me think. Her birthday is TOMORROW.",
                 "speaker_context": "pacing anxiously, hands on head, desperate expression"},
                {"char": "dash",   "text": "You should have thought about that before—",
                 "speaker_context": "sitting calmly eating cereal, completely unbothered deadpan look"},
                {"char": "bounce", "text": "I KNOW. What do I do?!",
                 "speaker_context": "throwing hands up, exasperated wide eyes"},
            ],
        },
        {
            "id": "s4_idea",
            "label": "The Idea",
            "on_screen_text": "boothop.com",
            "lines": [
                {"char": "dash",   "text": "Is anyone going Manchester on BootHop today?",
                 "speaker_context": "casually holding up smartphone, slightly smug knowing look"},
                {"char": "bounce", "text": "Boot... what?",
                 "speaker_context": "confused and curious, leaning forward, furrowed brow"},
                {"char": "dash",   "text": "Someone's always going your way, fam.",
                 "speaker_context": "looking at phone confidently, cool calm expression"},
            ],
        },
        {
            "id": "s5_realisation",
            "label": "The Realisation",
            "on_screen_text": "VERIFIED ✓ MANCHESTER",
            "lines": [
                {"char": "bounce", "text": "There's someone leaving in TWO HOURS?! Verified?!",
                 "speaker_context": "eyes wide with shock and excitement, phone raised in disbelief"},
                {"char": "bounce", "text": "Let's GO!",
                 "speaker_context": "jumping up enthusiastically, huge grin, fist pump in the air"},
            ],
        },
        {
            "id": "s6_ending",
            "label": "Ending",
            "on_screen_text_sequence": ["MUMS GET THEIR PEPPER SOUP.", "BOOTHOP IT.", "boothop.com"],
            "next_teaser": "NEXT: Dash's cousin is visiting. With 7 bags.",
            "lines": [
                {"char": "bounce", "text": "Mum's getting her pepper soup. BootHop money!",
                 "speaker_context": "at front door grinning ear to ear, giving thumbs up, suitcase beside him"},
                {"char": "dash",   "text": "You're welcome, by the way.",
                 "speaker_context": "arms folded with a satisfied smirk, looking pleased with himself"},
            ],
        },
    ],
    "caption": (
        "Bounce left his mum's birthday till the last minute. DHL wanted £89. "
        "Dash saved the day with BootHop. "
        "Someone's always going your way. boothop.com"
    ),
    "hashtags": (
        "#BootHop #BounceAndDash #DiasporaLife #NigerianBritish #UKNigerian "
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
            "label": "Hook",
            "on_screen_text": "TOMORROW.",
            "lines": [
                {"char": "dash",   "text": "Bounce... Tunde is coming to stay.",
                 "speaker_context": "sitting on sofa staring at phone with a slowly dropping face, dread in eyes"},
                {"char": "bounce", "text": "Nice! When?",
                 "speaker_context": "making tea in kitchen, completely unbothered, cheerful expression"},
                {"char": "dash",   "text": "Tomorrow.",
                 "speaker_context": "still staring at phone, flat deadpan delivery, the word lands like a verdict"},
            ],
        },
        {
            "id": "s2_problem",
            "label": "The Problem",
            "on_screen_text": "SEVEN.",
            "lines": [
                {"char": "dash",   "text": "He says he's bringing a few things from home.",
                 "speaker_context": "holding up phone showing the message, grimacing slightly"},
                {"char": "bounce", "text": "How many bags?",
                 "speaker_context": "curious but cautious expression, slowly narrowing eyes"},
                {"char": "dash",   "text": "Seven.",
                 "speaker_context": "completely deadpan, letting the word land like a bomb, long pause"},
            ],
        },
        {
            "id": "s3_chaos",
            "label": "Airport Chaos",
            "on_screen_text": "E DEY JAAPA NI?!",
            "lines": [
                {"char": "bounce", "text": "NAAA WETIIIN BE THESE?! E dey jaapa ni?! Is this man moving house or moving continent?!",
                 "speaker_context": "standing at airport arrivals, eyes enormous, jaw dropped, arms flung wide in total disbelief"},
                {"char": "dash",   "text": "I told him... pack. light.",
                 "speaker_context": "arms folded, slow defeated blink, staring into the middle distance, completely resigned"},
            ],
        },
        {
            "id": "s4_stuck",
            "label": "Stuck Outside",
            "on_screen_text": "NOT PICKFORDS.",
            "lines": [
                {"char": "bounce", "text": "The Uber man talk say he no be Pickfords ooo.",
                 "speaker_context": "outside airport, surrounded by seven suitcases, relaying the news with exasperated hands"},
                {"char": "dash",   "text": "So wetin we go do with seven bags?!",
                 "speaker_context": "looking helplessly at the mountain of luggage, hands on hips"},
                {"char": "bounce", "text": "...I know a guy. BootHop.",
                 "speaker_context": "sudden sly grin spreading across face, slowly raising phone like a pro move"},
            ],
        },
        {
            "id": "s5_reversal",
            "label": "The Role Reversal",
            "on_screen_text": "DIDN'T YOU JUST LEARN ABOUT THIS?",
            "lines": [
                {"char": "dash",   "text": "Wait — is that BootHop?",
                 "speaker_context": "staring in disbelief, one eyebrow raised very high, pointing at Bounce's phone"},
                {"char": "bounce", "text": "Someone's always going your way, fam.",
                 "speaker_context": "extremely smug, phone held out like a trophy, mimicking Dash's cool delivery back at him"},
            ],
        },
        {
            "id": "s6_ending",
            "label": "Ending",
            "on_screen_text_sequence": ["BAGS DELIVERED.", "BOOTHOP IT.", "boothop.com"],
            "next_teaser": "NEXT: Bounce wants to MAKE money on BootHop. What could go wrong?",
            "lines": [
                {"char": "dash",   "text": "You literally learned about BootHop yesterday.",
                 "speaker_context": "collapsed on sofa, shaking head slowly, can't believe what he just witnessed"},
                {"char": "bounce", "text": "And I'm already a pro. You're welcome.",
                 "speaker_context": "collapsed beside Dash, grinning insufferably, arms behind head, absolutely no shame"},
            ],
        },
    ],
    "caption": (
        "Dash's cousin came from Lagos with 7 bags. The Uber said no. "
        "Bounce — who only just discovered BootHop yesterday — stepped up. "
        "Someone's always going your way. boothop.com"
    ),
    "hashtags": (
        "#BootHop #BounceAndDash #DiasporaLife #NigerianBritish #LagosToLondon "
        "#AfricanCommunity #TooMuchLuggage #CartoonComedy #UKNigerian #LondonLife"
    ),
    "setting": "Bounce and Dash's flat + Heathrow Airport",
    "story_summary": (
        "Dash's cousin Tunde arrives from Lagos with 7 bags. The Uber man says he's not Pickfords. "
        "Bounce — who only learned about BootHop in Ep1 — confidently pulls out the app and finds "
        "a verified traveller to handle the overflow. Role reversal complete. "
        "Dash cannot believe what he is witnessing."
    ),
}


# ── Cost estimator ─────────────────────────────────────────────────────────────
def estimate_cost(episode: dict, is_dynamic: bool = False) -> dict:
    n_scenes    = len(episode["shots"])
    total_chars = sum(len(l["text"]) for l in _all_lines(episode["shots"]))
    costs = {
        "image_gen":        round(n_scenes * 0.042, 2),   # gpt-image-1 edits ~$0.042/image
        "kling_video":      round(n_scenes * 0.14,  2),   # Kling v1 5s clip  ~$0.14/clip
        "openai_tts":       round(total_chars / 1_000_000 * 15, 4),   # TTS-1 $15/1M chars
        "elevenlabs_music": 0.10,                          # ElevenLabs sound gen
        "perplexity":       0.005 if is_dynamic else 0.0, # Perplexity sonar ~$0.005/call
        "claude_writer":    0.04  if is_dynamic else 0.0, # Claude Sonnet episode script
    }
    costs["total"] = round(sum(costs.values()), 2)
    return costs


# ── Cost logger — call after each API spend ────────────────────────────────────
def _log_cost(costs: dict, service: str, amount: float, note: str = ""):
    costs[service] = round(costs.get(service, 0.0) + amount, 4)
    _log(f"  Cost +${amount:.4f} [{service}]{' — ' + note if note else ''}")


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


# ── Trim a video clip to a given duration ─────────────────────────────────────
def _trim_clip(src: Path, duration: float, out: Path) -> Path | None:
    ok = _ff("-i", str(src), "-t", f"{duration:.3f}",
             "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(out))
    return out if (ok and out.exists()) else None


# ── Solo speaker image — only the named character, close/medium shot ───────────
def generate_speaker_image(line: dict, ep_dir: Path,
                           scene_id: str, line_idx: int) -> Path | None:
    import requests as _rq, base64 as _b64m
    char     = line["char"]
    ctx      = line.get("speaker_context", "speaking expressively")
    prompt   = _speaker_prompt(char, ctx)
    ref      = CHAR_REF_BOUNCE if char == "bounce" else CHAR_REF_DASH
    img_path = ep_dir / f"{scene_id}_l{line_idx:02}_{char}.png"

    if img_path.exists():
        _log(f"    Reusing speaker image: {img_path.name}")
        return img_path

    _log(f"    Speaker image [{char}]: {ctx[:50]}...")

    if ref and ref.exists():
        try:
            with open(ref, "rb") as ref_f:
                r = _rq.post(
                    "https://api.openai.com/v1/images/edits",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    data={"model": "gpt-image-1", "prompt": prompt,
                          "n": "1", "size": "1024x1536"},
                    files={"image": (ref.name, ref_f, "image/png")},
                    timeout=90,
                )
            r.raise_for_status()
            item = r.json()["data"][0]
            if item.get("b64_json"):
                img_path.write_bytes(_b64m.b64decode(item["b64_json"]))
            elif item.get("url"):
                img_path.write_bytes(_rq.get(item["url"], timeout=60).content)
            _log(f"    Image OK (ref-edit): {img_path.name}")
            return img_path
        except Exception as e:
            _log(f"    Ref-edit failed: {e} — falling back to generation")

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
        if item.get("b64_json"):
            img_path.write_bytes(_b64m.b64decode(item["b64_json"]))
        elif item.get("url"):
            img_path.write_bytes(_rq.get(item["url"], timeout=60).content)
        _log(f"    Image OK (generation): {img_path.name}")
        return img_path
    except Exception as e:
        _log(f"    Speaker image failed: {e}")
        return None


# ── Scene image generation — ALWAYS uses existing character reference images ───
# Primary:  /v1/images/edits  with bounce_ref.png  → preserves exact original look
# Fallback: /v1/images/generations but prompt still hard-references the character
def generate_scene_image(shot: dict, ep_dir: Path, retry: int = 0) -> Path | None:
    import requests as _rq, base64 as _b64m
    _log(f"  Generating image: {shot['id']}...")
    img_path = ep_dir / f"{shot['id']}.png"

    # ── Path 1: edits endpoint — pick ref based on which characters are in shot ──
    chars_in_shot = {l["char"] for l in shot.get("lines", [])}
    if chars_in_shot == {"dash"} and CHAR_REF_DASH.exists():
        ref = CHAR_REF_DASH        # Dash-only shot → use Dash reference
    elif CHAR_REF_BOUNCE.exists():
        ref = CHAR_REF_BOUNCE      # Bounce or both → anchor to Bounce (primary character)
    else:
        ref = None
    if ref:
        try:
            with open(ref, "rb") as ref_f:
                r = _rq.post(
                    "https://api.openai.com/v1/images/edits",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    data={"model": "gpt-image-1", "prompt": shot["dalle_scene"],
                          "n": "1", "size": "1024x1536"},
                    files={"image": (ref.name, ref_f, "image/png")},
                    timeout=90,
                )
            r.raise_for_status()
            item = r.json()["data"][0]
            if item.get("b64_json"):
                img_path.write_bytes(_b64m.b64decode(item["b64_json"]))
            elif item.get("url"):
                img_path.write_bytes(_rq.get(item["url"], timeout=60).content)
            else:
                raise ValueError("No image data")
            _log(f"  Image OK (ref-edit): {img_path.name} ({img_path.stat().st_size//1024}KB)")
            return img_path
        except Exception as e:
            _log(f"  Ref-edit failed ({shot['id']}): {e} — retrying via generations")

    # ── Path 2: generations endpoint — character description still fully embedded ─
    # The prompt already contains the full character spec (_STYLE + _BD + _DD), so
    # even without the reference file the model gets strong character anchoring.
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
        if item.get("b64_json"):
            img_path.write_bytes(_b64m.b64decode(item["b64_json"]))
        elif item.get("url"):
            img_path.write_bytes(_rq.get(item["url"], timeout=60).content)
        else:
            raise ValueError("No image data in response")
        _log(f"  Image OK (generation): {img_path.name} ({img_path.stat().st_size//1024}KB)")
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
        "High-energy Afrobeats street banger, 2024 trending UK-Nigerian sound, "
        "heavy punchy log-drum, deep 808 bass, bright synth stabs, fast confident groove, "
        "inspired by Rema or Asake instrumental style, bold and infectious, "
        "no vocals or lyrics, cinematic cartoon energy, "
        "perfect for a 30-second animated comedy advert — make it hit hard from bar one"
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


# ── Image -> 5s animated clip (Kling AI, primary video engine) ────────────────
def image_to_video_kling(image_path: Path, motion_prompt: str,
                         ep_dir: Path, shot_id: str) -> Path | None:
    import requests as _rq, base64 as _b64m
    _log(f"  Kling video: {shot_id}...")
    try:
        img_b64 = _b64m.b64encode(image_path.read_bytes()).decode()
        r = _rq.post(
            f"{KLING_API_BASE}/v1/videos/image2video",
            headers={"Authorization": f"Bearer {KLING_API_KEY}",
                     "Content-Type": "application/json"},
            json={
                "model_name": "kling-v1",
                "image":       img_b64,
                "prompt":      motion_prompt,
                "duration":    "5",
                "aspect_ratio": "9:16",
                "cfg_scale":   0.5,
            },
            timeout=60,
        )
        if r.status_code != 200:
            _log(f"  Kling submit error {r.status_code}: {r.text[:200]}")
            return _still_to_video(image_path, ep_dir, shot_id)

        task_id = (r.json().get("data") or {}).get("task_id")
        if not task_id:
            _log(f"  Kling: no task_id — {r.json()}")
            return _still_to_video(image_path, ep_dir, shot_id)

        _log(f"  Kling task: {task_id}")
        for attempt in range(48):          # up to ~4 min
            time.sleep(5)
            pr = _rq.get(
                f"{KLING_API_BASE}/v1/videos/image2video/{task_id}",
                headers={"Authorization": f"Bearer {KLING_API_KEY}"},
                timeout=20,
            )
            td = pr.json().get("data", {})
            status = td.get("task_status", "")
            _log(f"  Kling: {status} ({attempt+1}/48)")
            if status == "succeed":
                works = (td.get("task_result") or {}).get("videos", [])
                url = works[0].get("url") if works else None
                if url:
                    vid = _rq.get(url, timeout=120).content
                    out = ep_dir / f"{shot_id}_clip.mp4"
                    out.write_bytes(vid)
                    _log(f"  Kling OK: {out.name} ({len(vid)//1024}KB)")
                    return out
                break
            elif status in ("failed", "error"):
                _log(f"  Kling failed: {td.get('task_status_msg', 'unknown')}")
                break

        return _still_to_video(image_path, ep_dir, shot_id)
    except Exception as e:
        _log(f"  Kling error: {e}")
        return _still_to_video(image_path, ep_dir, shot_id)


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


# ── Dialogue-first assembly (one clip per line, each muxed with its audio) ────
def assemble_dialogue_video(line_clips: list[tuple], music_path: Path | None,
                            ep_dir: Path) -> Path | None:
    _log("  Muxing each speaker clip with its voice line...")
    muxed = []
    for i, (clip, audio, _dur) in enumerate(line_clips):
        out = ep_dir / f"muxed_{i:03}.mp4"
        if out.exists():
            muxed.append(out)
            continue
        ok = _ff(
            "-i", str(clip), "-i", str(audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p", "-shortest",
            str(out),
        )
        if ok and out.exists():
            muxed.append(out)
        else:
            _log(f"  Mux failed for clip {i} — skipping")

    if not muxed:
        _log("  No muxed clips — aborting assembly")
        return None

    # Concat all muxed clips into one dialogue track
    concat_list = ep_dir / "dialogue_concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{c.resolve()}'" for c in muxed), encoding="utf-8"
    )
    raw = ep_dir / "dialogue_raw.mp4"
    if not _ff("-f", "concat", "-safe", "0", "-i", str(concat_list),
               "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(raw)):
        _log("  Concat failed")
        return None

    total_dur = _ffprobe_duration(raw)
    _log(f"  Dialogue duration: {total_dur:.1f}s")

    # Scale to 9:16 and overlay music at low volume (dialogue stays clear)
    final = ep_dir / "final_video.mp4"
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if music_path and music_path.exists():
        audio_filter = (
            "[0:a]volume=1.0[dialogue];"
            f"[1:a]volume=0.15,afade=t=out:st={max(0, total_dur-2)}:d=2[music];"
            "[dialogue][music]amix=inputs=2:duration=first[aout]"
        )
        ok = _ff(
            "-i", str(raw), "-i", str(music_path),
            "-filter_complex", audio_filter,
            "-map", "0:v", "-map", "[aout]",
            "-vf", vf,
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            str(final),
        )
    else:
        ok = _ff("-i", str(raw), "-vf", vf,
                 "-c:v", "libx264", "-crf", "20", str(final))

    if ok and final.exists():
        dur = _ffprobe_duration(final)
        _log(f"  Assembly OK: {final.name} ({final.stat().st_size//1024}KB, {dur:.1f}s)")
        return final
    _log("  Assembly failed")
    return None


# ── Final assembly (FFmpeg) — kept for reference ──────────────────────────────
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
    breakdown_lines = "\n".join(
        f"  {svc}: ${amt:.4f}"
        for svc, amt in costs.items()
        if svc != "total" and amt > 0
    )
    msg = (
        f"*BOUNCE ON THE MOVE — EP{ep_num}: {episode['title']}*\n"
        f"Setting: {episode['setting']}\n"
        f"Duration: {dur:.1f}s\n\n"
        f"*Cost breakdown:*\n{breakdown_lines}\n"
        f"*Total: ${costs.get('total', 0):.4f}*\n\n"
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


# ── Perplexity: weekly research brief ─────────────────────────────────────────
def research_weekly_brief() -> tuple[str | None, float]:
    """Returns (brief_text, cost_usd). Cost estimated from token usage."""
    import requests as _rq
    if not PERPLEXITY_KEY:
        _log("  PERPLEXITY_KEY not set — add it to keys.env to enable live research")
        return None, 0.0
    _log("  Querying Perplexity for weekly trends...")
    try:
        r = _rq.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_KEY}",
                     "Content-Type": "application/json"},
            json={
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a research assistant for a UK/Nigeria diaspora animated comedy series. "
                            "Return factual, concise research briefs only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Search the web for trending stories this week relevant to:\n"
                            "1. UK–Nigeria diaspora: luggage, sending items home, parcel costs\n"
                            "2. Airport chaos, excess baggage fees, courier prices at UK airports\n"
                            "3. Nigerian/British-Black community humour, viral slang, TikTok trends\n"
                            "4. Student travel between UK cities (London, Manchester, Birmingham)\n"
                            "5. Trending dances or sounds on UK/Nigerian TikTok or Instagram this week\n"
                            "6. Upcoming Nigerian or diasporic holiday travel patterns\n\n"
                            "Return a concise brief (200-300 words) with:\n"
                            "- The #1 most relevant travel/parcel story or trend this week\n"
                            "- 2-3 relatable UK diaspora frustrations (price shock, overpacking, etc.)\n"
                            "- A trending dance name or cultural moment if one exists this week\n"
                            "- A suggested episode angle: what BootHop problem should our characters face?\n"
                        ),
                    },
                ],
                "max_tokens": 600,
            },
            timeout=30,
        )
        r.raise_for_status()
        body  = r.json()
        brief = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        # Perplexity sonar pricing: $1/1M input tokens, $1/1M output tokens
        cost  = round(
            usage.get("prompt_tokens", 150)     / 1_000_000 * 1.0 +
            usage.get("completion_tokens", 400) / 1_000_000 * 1.0,
            5,
        )
        _log(f"  Research brief received ({len(brief)} chars, ${cost:.5f})")
        return brief, cost
    except Exception as e:
        _log(f"  Perplexity research failed: {e}")
        return None, 0.0


# ── Claude: generate episode script from research brief ───────────────────────
def generate_episode_from_research(ep_num: int, research_brief: str | None) -> tuple[dict | None, float]:
    import anthropic as _ant
    _log(f"  Writing Episode {ep_num} with Claude...")
    research_section = (
        f"\n\n## This week's research (source: Perplexity live web search)\n{research_brief}"
        if research_brief
        else "\n\n(No live research available — write a timeless diaspora travel story.)"
    )
    system = (
        "You are the head writer for BOUNCE ON THE MOVE — a 30-second animated comedy "
        "for UK/Nigeria diaspora audiences. Every episode ends with BootHop.com solving "
        "a travel, parcel, or luggage problem.\n\n"
        "CHARACTERS (must be described EXACTLY as below — they are the official BootHop brand characters):\n"
        "- Bounce: LARGE fluffy ORANGE TABBY CAT, vivid green eyes, bold orange fur with "
        "darker tabby stripes, white muzzle, big expressive face. Warm, funny, panicky, "
        "British-Nigerian swagger. Voice: warm and youthful.\n"
        "- Dash: SMALL GREY-BLUE MOUSE, big round grey ears, slim compact build — "
        "much smaller than Bounce — always carrying a travel bag or small box. "
        "Calm, quick, dry wit. Bounce's flatmate. Very different species from Bounce.\n\n"
        "EPISODE RULES:\n"
        "• 6 shots, ~30 seconds total\n"
        "• Shots: s1_hook, s2_problem, s3_tension/chaos, s4_idea, s5_realisation, s6_ending\n"
        "• Each shot has 1-3 dialogue lines (alternating chars: 'bounce' / 'dash')\n"
        "• Tone: warm family comedy — funny to both 8-year-olds and 40-year-olds\n"
        "• BootHop solves the problem in shots 4-5\n"
        "• Never use: 'will earn', 'guaranteed earnings', 'you\\'ll make', 'earn every time'\n"
        "• dalle_scene: full scene description starting with: "
        "'3D animated Pixar-quality film style, original BootHop characters, premium cinema render, "
        "warm cinematic lighting, no text in image, large fluffy orange tabby cat named Bounce "
        "with vivid green eyes, AND small grey-blue mouse named Dash with big round grey ears "
        "and a travel bag, [then describe the scene action]'\n"
        "• s6_ending must have a 'next_teaser' key\n"
    )
    user = (
        f"Write Episode {ep_num} of BOUNCE ON THE MOVE.{research_section}\n\n"
        "Return ONLY valid JSON (no markdown fences, no comments) matching this structure:\n"
        "{\n"
        '  "number": <int>,\n'
        '  "title": "<EPISODE TITLE IN CAPS>",\n'
        '  "route": "<brief setting>",\n'
        '  "shots": [\n'
        '    { "id": "s1_hook", "time": "0:00-0:05", "label": "Hook",\n'
        '      "on_screen_text": "<short text on screen>",\n'
        '      "lines": [{"char": "bounce", "text": "..."}, {"char": "dash", "text": "..."}],\n'
        '      "dalle_scene": "<full Pixar-style scene prompt>"\n'
        '    },\n'
        '    ... (all 6 shots)\n'
        '  ],\n'
        '  "caption": "<social caption 1-2 sentences>",\n'
        '  "hashtags": "<10 hashtags>",\n'
        '  "setting": "<setting name>",\n'
        '  "story_summary": "<2-3 sentence summary>"\n'
        "}\n\n"
        f'The s6_ending shot must include "next_teaser": "NEXT: <teaser for ep {ep_num+1}>"\n'
        "Make it hilarious, warm, and tied to the research brief. "
        "Bounce should panic first, Dash should be the calm one who knows BootHop."
    )
    try:
        client = _ant.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        ep = json.loads(raw)
        # Claude Sonnet 4.6 pricing: $3/1M input, $15/1M output
        usage = resp.usage
        cost  = round(
            usage.input_tokens  / 1_000_000 * 3.0 +
            usage.output_tokens / 1_000_000 * 15.0,
            5,
        )
        _log(f"  Episode written: {ep.get('title','?')} (${cost:.4f})")
        ep_out = EPISODES / f"episode_{ep_num:03}"
        ep_out.mkdir(parents=True, exist_ok=True)
        _save_json(ep_out / "generated_script.json", ep)
        return ep, cost
    except Exception as e:
        _log(f"  Episode generation failed: {e}")
        return None, 0.0


# ── Main production flow ───────────────────────────────────────────────────────
def produce_episode(episode: dict, dry_run: bool = False, force: bool = False,
                    ai_costs: dict | None = None):
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
    actual_costs = {
        "image_gen":        0.0,
        "kling_video":      0.0,
        "openai_tts":       0.0,
        "elevenlabs_music": 0.0,
        "perplexity":       (ai_costs or {}).get("perplexity",    0.0),
        "claude_writer":    (ai_costs or {}).get("claude_writer", 0.0),
    }

    # Stage 1 — Voice lines FIRST (needed for clip timing)
    _log("Stage 1: Voiceover lines (generate all, get timings)...")
    vo_path = ep_dir / "voiceover.mp3"
    if not vo_path.exists():
        vo_path = generate_voiceover_lines(episode["shots"], ep_dir)
        if vo_path:
            total_chars = sum(len(l["text"]) for l in _all_lines(episode["shots"]))
            tts_cost = round(total_chars / 1_000_000 * 15, 4)
            _log_cost(actual_costs, "openai_tts", tts_cost, f"{total_chars} chars")
    else:
        _log("  Reusing voiceover")

    # Stage 2 — One Kling clip per spoken line (shot/reverse-shot)
    _log("Stage 2: Speaker clips — one per dialogue line...")
    line_clips = []   # [(video_clip, audio_file, duration_s)]
    global_line_idx = 0

    for shot in episode["shots"]:
        _log(f"  Scene: {shot['id']}")
        for line in shot.get("lines", []):
            char     = line["char"]
            audio_f  = ep_dir / f"vo_{global_line_idx:03}.mp3"
            audio_dur = _ffprobe_duration(audio_f) if audio_f.exists() else 2.5
            clip_id  = f"{shot['id']}_l{global_line_idx:02}"

            # Generate solo speaker image (only this character in frame)
            img = generate_speaker_image(line, ep_dir, shot["id"], global_line_idx)
            if img:
                _log_cost(actual_costs, "image_gen", 0.042, clip_id)

            # Kling: animate the speaker with mouth movement
            kling_clip = ep_dir / f"{clip_id}_clip.mp4"
            if not kling_clip.exists():
                if img and img.exists():
                    motion = _speaking_motion(char, line.get("speaker_context", ""))
                    kling_clip = image_to_video_kling(img, motion, ep_dir, clip_id)
                    if kling_clip:
                        _log_cost(actual_costs, "kling_video", 0.14, clip_id)
            else:
                _log(f"    Reusing clip: {kling_clip.name}")

            # Trim Kling clip to audio duration + 0.3s natural pause
            if kling_clip and kling_clip.exists():
                trim_dur = max(audio_dur + 0.3, 1.0)
                trimmed  = ep_dir / f"{clip_id}_trimmed.mp4"
                if not trimmed.exists():
                    _trim_clip(kling_clip, trim_dur, trimmed)
                clip_to_use = trimmed if trimmed.exists() else kling_clip
                line_clips.append((clip_to_use, audio_f, audio_dur))

            global_line_idx += 1

    if not line_clips:
        _log("No speaker clips generated — aborting")
        _tg(f"BOUNCE Ep{ep_num} FAILED: no clips generated")
        return

    # Stage 3 — Music with BootHop stab
    _log("Stage 3: Music (ElevenLabs + BootHop stab)...")
    music_path = ep_dir / "music.mp3"
    total_dialogue_dur = sum(d for _, _, d in line_clips) + len(line_clips) * 0.3
    if not music_path.exists():
        target_dur = max(total_dialogue_dur + 3, 30)
        music_path = generate_music(target_dur, ep_dir)
        if music_path:
            _log_cost(actual_costs, "elevenlabs_music", 0.10, "sound generation")
    else:
        _log("  Reusing music")

    # Stage 4 — Captions
    _log("Stage 4: Captions...")
    full_text = _full_dialogue_text(episode["shots"])
    srt_path = build_srt(full_text, total_dialogue_dur, ep_dir)

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

    # Stage 5 — Assemble: mux each clip with its audio, concat, add music low
    _log("Stage 5: Final assembly (per-line lip-sync mux)...")
    final = ep_dir / "final_video.mp4"
    if not final.exists():
        final = assemble_dialogue_video(line_clips, music_path, ep_dir)

    if not final or not final.exists():
        _tg(f"BOUNCE Ep{ep_num} FAILED: assembly failed")
        return

    # Stage 6 — QA
    _log("Stage 6: QA...")
    make_contact_sheet(final, ep_dir)
    qa = qa_check(final, episode)
    _log(f"QA: {'PASSED' if qa['passed'] else 'ISSUES: ' + str(qa['issues'])}")

    actual_costs["total"] = round(sum(v for k, v in actual_costs.items() if k != "total"), 4)
    _log(f"Actual cost breakdown:")
    for svc, amt in actual_costs.items():
        if svc != "total" and amt > 0:
            _log(f"  {svc:<20} ${amt:.4f}")
    _log(f"  {'TOTAL':<20} ${actual_costs['total']:.4f}")

    manifest.update({
        "status": "completed",
        "completed_at": datetime.now().isoformat(),
        "actual_cost": actual_costs,
        "qa": qa,
    })
    _save_json(manifest_path, manifest)

    counter = _load_json(STATE / "episode_counter.json")
    counter["last_completed"] = ep_num
    counter["next_episode"]   = ep_num + 1
    _save_json(STATE / "episode_counter.json", counter)

    history = _load_json(STATE / "story_history.json")
    history.setdefault("episodes", []).append({
        "number": ep_num, "title": episode["title"],
        "route": episode["route"], "date": datetime.now().strftime("%Y-%m-%d"),
    })
    _save_json(STATE / "story_history.json", history)

    cost_h = _load_json(STATE / "cost_history.json")
    cost_h.setdefault("episodes", []).append({
        "episode":   ep_num,
        "title":     episode["title"],
        "date":      datetime.now().strftime("%Y-%m-%d"),
        "estimated": costs["total"],
        "actual":    actual_costs["total"],
        "breakdown": {k: v for k, v in actual_costs.items() if k != "total"},
    })
    cost_h["total_spent_usd"] = round(
        cost_h.get("total_spent_usd", 0) + actual_costs["total"], 4
    )
    _save_json(STATE / "cost_history.json", cost_h)

    # Stage 7 — Deliver
    _log("Stage 7: Telegram delivery...")
    deliver_to_telegram(episode, ep_dir, final, actual_costs, qa)
    _log(f"=== Episode {ep_num} DONE — ${actual_costs['total']:.4f} ===")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BOUNCE ON THE MOVE episode runner")
    parser.add_argument("--episode", type=int, default=None)
    parser.add_argument("--batch",   type=int, default=1,    help="Produce N consecutive episodes")
    parser.add_argument("--post",    type=int, default=None, help="Re-post completed episode N to Telegram")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force",   action="store_true",    help="Re-produce even if already completed")
    parser.add_argument("--costs",   action="store_true",    help="Print cost history and exit")
    args = parser.parse_args()

    # ── --costs: print history and exit ───────────────────────────────────────
    if args.costs:
        cost_h = _load_json(STATE / "cost_history.json")
        eps    = cost_h.get("episodes", [])
        total  = cost_h.get("total_spent_usd", 0)
        print(f"\n{'Ep':<4} {'Title':<24} {'Date':<12} {'Est':>7} {'Actual':>8}  Breakdown")
        print("-" * 80)
        for e in eps:
            bd = "  ".join(f"{k}=${v:.3f}" for k,v in e.get("breakdown",{}).items() if v > 0)
            print(f"  {e['episode']:<4} {e.get('title','?'):<24} {e.get('date','?'):<12} "
                  f"${e.get('estimated',0):>6.4f}  ${e.get('actual',0):>6.4f}  {bd}")
        print("-" * 80)
        print(f"  {'TOTAL SPENT':>40}  ${total:.4f}\n")
        sys.exit(0)

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

    # Fetch weekly research once per batch — feeds every dynamically generated episode
    _research_brief  = None
    _research_cost   = 0.0

    for i in range(args.batch):
        ep_num  = start_ep + i
        episode = episodes_map.get(ep_num)
        _ai_costs = {}  # perplexity + claude costs to inject into this episode

        if not episode:
            # Episode 3+ — auto-generate using Perplexity research + Claude
            if _research_brief is None:
                _research_brief, _research_cost = research_weekly_brief()
            episode, claude_cost = generate_episode_from_research(ep_num, _research_brief)
            if not episode:
                _log(f"Failed to generate episode {ep_num} — stopping batch")
                break
            _ai_costs = {"perplexity": _research_cost, "claude_writer": claude_cost}

        produce_episode(episode, dry_run=args.dry_run, force=args.force,
                        ai_costs=_ai_costs)
