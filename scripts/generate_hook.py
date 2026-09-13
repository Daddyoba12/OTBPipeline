"""
generate_hook.py — Dynamic 2-second cinematic hook engine for all pipeline videos.

Every video starts with a clean 0-2 second visual (person/lifestyle, no text) over
which a dynamically AI-generated Gen-Z dialogue voiceover plays.

Visual priority: Pexels VIDEO -> Pixabay VIDEO -> OpenAI DALL-E 3 image
Dialogue: Claude generates fresh Nigerian Pidgin / UK Gen-Z Nigerian each run
Dedup: data/hook_used_log.json — 14-day cooldown per dialogue + scene query
"""

import os, re, sys, json, random, subprocess
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    GEMINI_API_KEY, PEXELS_KEY, PIXABAY_KEY, OPENAI_API_KEY,
    TEMP, DATA, VIDEO_W, VIDEO_H, VIDEO_FPS,
)

import requests

HOOK_DUR = 2          # seconds — the clean cinematic opening
W, H     = VIDEO_W, VIDEO_H

_HOOK_LOG         = DATA / "hook_used_log.json"
_HOOK_COOLDOWN    = 14  # days

# Scenes that are absolutely banned
_BANNED_SCENE_TERMS = {
    # Religious
    "church", "prayer", "masquerade", "mask", "carnival mask",
    "religious", "worship", "mosque", "cathedral", "congregation",
    "festival mask", "voodoo", "costume mask",
    # Wildlife / animals — no lions, safari, nature clips
    "lion", "lioness", "leopard", "cheetah", "elephant", "giraffe",
    "zebra", "safari", "wildlife", "animal", "tiger", "wolf",
    "savanna", "jungle animal", "nature wildlife",
}

# Dialogue lines permanently silenced — never used regardless of cooldown
# Add exact lowercase phrases here to kill them forever until removed
_PERMANENTLY_SILENCED = {
    "omo boothop na my plug for this trip!",
    "omo boothop na mi plug for this trip!",
    "omo boothop na my plug",
    "omo boothop na mi plug",
}


# ── 14-day dedup ──────────────────────────────────────────────────────────────

def _load_log() -> list:
    if _HOOK_LOG.exists():
        try:
            return json.loads(_HOOK_LOG.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_entry(dialogue: str, scene_query: str):
    log = _load_log()
    log.append({
        "dialogue":    dialogue[:100],
        "scene_query": scene_query[:80],
        "logged_at":   datetime.now().isoformat(),
    })
    DATA.mkdir(exist_ok=True)
    _HOOK_LOG.write_text(
        json.dumps(log[-150:], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _recent_used(days: int = _HOOK_COOLDOWN) -> set:
    log    = _load_log()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    recent: set = set()
    for e in log:
        if e.get("logged_at", "") > cutoff:
            recent.add(e.get("dialogue", "")[:60].lower())
            recent.add(e.get("scene_query", "").lower())
    return recent


def _recent_clip_ids(days: int = 28) -> set:
    """Return Pexels/Pixabay clip IDs used in the last N days — skip these when picking."""
    try:
        import json as _j
        vlog = DATA / "video_clip_log.json"
        if not vlog.exists():
            return set()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return {
            e["id"] for e in _j.loads(vlog.read_text(encoding="utf-8"))
            if e.get("logged_at", "") > cutoff
        }
    except Exception:
        return set()


# ── Claude: fresh dialogue + scene description ────────────────────────────────

def _claude_generate(client: str, used: set) -> dict:
    """Ask Claude to generate fresh hook dialogue and scene description."""
    if not GEMINI_API_KEY:
        return {}

    used_list = "\n".join(f"- {h}" for h in list(used)[:20]) or "none yet"

    if client == "g-inspired":
        prompt = (
            f"You are writing the opening 2-second hook for a short social media video for "
            f"G-Inspired Automall — a no-hidden-fee used car dealership in Washington, IL.\n\n"
            f"Platform: TikTok and Instagram Reels\n"
            f"Duration of hook: 2 seconds only\n\n"
            f"GENERATE:\n"
            f"1. dialogue — A spoken line by the person on screen (max 10 words).\n"
            f"   Style: casual American English — car enthusiast, excited buyer, or lifestyle energy.\n"
            f"   Should feel like a real person who just got a great deal or loves their car.\n"
            f"   Examples of STYLE (do not copy these):\n"
            f"     - 'Bro this truck is clean and I paid zero fees!'\n"
            f"     - 'No cap, I got this SUV for exactly what the tag said.'\n"
            f"     - 'She pulled up in that and I had to ask where she got it.'\n"
            f"     - 'Gym after this — just picked up my new ride, no fees, no drama.'\n"
            f"     - 'Pulled up different today. G-Inspired hit different.'\n\n"
            f"2. scene_query — A Pexels/Pixabay video search query (6-8 words).\n"
            f"   MUST show a real person (not landscape, not objects alone).\n"
            f"   PREFERRED scene ideas (use these often — fresh, high-energy):\n"
            f"     - beautiful woman dancing confidently indoors lifestyle wide shot\n"
            f"     - Black men at gym talking laughing energetic medium shot\n"
            f"     - woman having great time friends laughing celebrating wide shot\n"
            f"     - men gym workout motivated talking excited wide shot\n"
            f"     - stylish woman luxury car keys smiling confident medium shot\n"
            f"   Shot type: medium shot or wide shot ONLY — no extreme close-ups.\n"
            f"   NO church, NO religious scenes, NO food, NO farm, NO plantation, NO rural scenery, NO animals.\n\n"
            f"3. scene_style — one of: dancing_vibes | gym_energy | luxury_travel | "
            f"car_lifestyle | money_moment\n"
            f"   Prefer dancing_vibes or gym_energy for scroll-stopping energy.\n\n"
            f"ALREADY USED (do not repeat within 14 days):\n{used_list}\n\n"
            f"Reply ONLY with valid JSON, no other text:\n"
            f'{{\"dialogue\": \"...\", \"scene_query\": \"...\", \"scene_style\": \"...\"}}'
        )
    else:
        prompt = (
            f"You are writing the opening 2-second hook for a social media short video about "
            f"BootHop — a UK-Nigeria parcel delivery and travel money service used by the diaspora.\n\n"
            f"Client slug: {client}\n"
            f"Platform: TikTok and Instagram Reels\n"
            f"Duration of hook: 2 seconds only\n\n"
            f"GENERATE:\n"
            f"1. dialogue — A spoken line by the person on screen (max 12 words).\n"
            f"   Style: Nigerian Pidgin, UK Gen-Z Nigerian, or US Nigerian slang. Vary each time.\n"
            f"   Should sound natural — someone talking about travel, sending a parcel, or earning.\n"
            f"   Examples of STYLE (do not copy these):\n"
            f"     - 'Pack that envelope fam — someone dey carry am for cheap, trust me!'\n"
            f"     - 'Omo this trip dey pay for itself, boothop money never lie!'\n"
            f"     - 'Babe you load that bag already? — BootHop sorted everything!'\n"
            f"     - 'Bro after the gym I sorted my mum's parcel through BootHop — quick quick!'\n"
            f"     - 'No cap, I was dancing when I saw how cheap BootHop was, free money!'\n"
            f"     - 'Ayo how you manage that luggage allowance? Earning from every trip!'\n\n"
            f"2. scene_query — A Pexels/Pixabay video search query (6-8 words).\n"
            f"   MUST show a real person (not landscape, not objects alone).\n"
            f"   PREFERRED scene ideas (use these often — fresh, high-energy):\n"
            f"     - Black British woman dancing confidently indoors lifestyle wide shot\n"
            f"     - Black men at gym talking laughing energetic medium shot\n"
            f"     - Black British woman great time friends laughing lifestyle wide shot\n"
            f"     - Black men gym workout motivated talking wide shot\n"
            f"   Other scene ideas: stylish woman at airport lounge, person loading luxury\n"
            f"   suitcase into car, couple at departure gate, Black British woman celebrating outdoors.\n"
            f"   NEVER use 'African' in the scene query — it returns wildlife clips. Use 'Black British' instead.\n"
            f"   Shot type: medium shot or wide shot ONLY — no extreme close-ups.\n"
            f"   NO church, NO masquerade, NO religious ceremony, NO mask performers, NO food, NO animals.\n\n"
            f"3. scene_style — one of: dancing_vibes | gym_energy | luxury_travel | "
            f"airport_vibes | parcel_delivery | excited_packing | money_moment\n"
            f"   Prefer dancing_vibes or gym_energy for variety and scroll-stopping energy.\n\n"
            f"ALREADY USED (do not repeat within 14 days):\n{used_list}\n\n"
            f"Reply ONLY with valid JSON, no other text:\n"
            f'{{\"dialogue\": \"...\", \"scene_query\": \"...\", \"scene_style\": \"...\"}}'
        )

    try:
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 220, "temperature": 0.7},
            },
            timeout=25,
        )
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        m   = re.search(r"\{[\s\S]*?\}", raw)
        if not m:
            return {}
        data        = json.loads(m.group())
        dialogue    = data.get("dialogue", "").strip()
        scene_query = data.get("scene_query", "").strip()

        # Guard scene query against banned terms
        if any(b in scene_query.lower() for b in _BANNED_SCENE_TERMS):
            scene_query = "stylish Black British woman airport departure lounge wide shot"

        print(f"  [HookEngine] Dialogue: '{dialogue[:60]}'")
        print(f"  [HookEngine] Scene:    '{scene_query}'")
        return {
            "dialogue":    dialogue,
            "scene_query": scene_query,
            "scene_style": data.get("scene_style", "luxury_travel"),
        }
    except Exception as e:
        print(f"  [HookEngine] Claude error: {e}")
    return {}


# ── FFmpeg helper ──────────────────────────────────────────────────────────────

def _ff(*args, timeout: int = 120) -> bool:
    cmd = ["ffmpeg", "-y"] + list(args)
    env = os.environ.copy()
    env.setdefault("FONTCONFIG_FILE", "NUL" if os.name == "nt" else "/dev/null")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False
    if r.returncode != 0:
        print(f"  [FFmpeg/Hook] cmd: {' '.join(cmd[-4:])}")
        print(f"  [FFmpeg/Hook] err: {r.stderr[-250:]}")
    return r.returncode == 0


def _download_and_trim(url: str, dest: Path) -> bool:
    """Download video URL and trim to HOOK_DUR seconds at 9:16."""
    try:
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        raw = dest.with_suffix(".raw.mp4")
        with open(raw, "wb") as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)
        if not raw.exists() or raw.stat().st_size < 10_000:
            raw.unlink(missing_ok=True)
            return False
        ok = _ff(
            "-ss", "0", "-i", str(raw),
            "-t", str(HOOK_DUR),
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,"
            f"unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount=0.8",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
        )
        raw.unlink(missing_ok=True)
        return ok and dest.exists() and dest.stat().st_size > 5_000
    except Exception as e:
        print(f"  [HookEngine] Download error: {e}")
    return False


# ── Video sources: Pexels -> Pixabay -> DALL-E ────────────────────────────────

def _pexels_video(query: str, used_ids: set | None = None) -> dict | None:
    if not PEXELS_KEY:
        return None
    used_ids = used_ids or set()
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": 25, "orientation": "portrait", "size": "medium"},
            headers={"Authorization": PEXELS_KEY},
            timeout=15,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        for v in random.sample(videos, len(videos)):
            if str(v["id"]) in used_ids:
                continue
            slug = v.get("url", "").lower()
            if any(b in slug for b in _BANNED_SCENE_TERMS):
                continue
            files = sorted(v.get("video_files", []), key=lambda f: f.get("width", 0), reverse=True)
            hd = next(
                (f for f in files
                 if f.get("height", 0) > f.get("width", 0) and f.get("width", 0) >= 720),
                None,
            )
            if not hd:
                hd = next((f for f in files if f.get("width", 0) >= 720), None)
            if hd:
                return {"url": hd["link"], "id": str(v["id"]), "source": "pexels"}
    except Exception as e:
        print(f"  [HookEngine] Pexels error: {e}")
    return None


def _pixabay_video(query: str, used_ids: set | None = None) -> dict | None:
    if not PIXABAY_KEY:
        return None
    used_ids = used_ids or set()
    try:
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": PIXABAY_KEY, "q": query, "video_type": "film",
                    "orientation": "vertical", "per_page": 15},
            timeout=15,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
        for v in random.sample(hits, len(hits)):
            if f"pb_{v['id']}" in used_ids:
                continue
            tags = {t.strip() for t in v.get("tags", "").lower().split(",")}
            if tags & _BANNED_SCENE_TERMS:
                continue
            sizes = v.get("videos", {})
            url = (sizes.get("large", {}).get("url")
                   or sizes.get("medium", {}).get("url")
                   or sizes.get("small", {}).get("url"))
            if url:
                return {"url": url, "id": f"pb_{v['id']}", "source": "pixabay"}
    except Exception as e:
        print(f"  [HookEngine] Pixabay error: {e}")
    return None


def _dalle_image(scene_query: str, dest: Path) -> bool:
    """Generate DALL-E image, Ken-Burns animate it to HOOK_DUR seconds."""
    if not OPENAI_API_KEY:
        return False
    prompt = (
        f"Photorealistic commercial photography. "
        f"Scene: {scene_query}. "
        f"Subject is a real person — Black British, Nigerian British, or stylish British youth. "
        f"Medium or wide shot, natural authentic setting. "
        f"No text, no logos, no watermarks. "
        f"Vertical 9:16 portrait orientation. High production quality."
    )
    try:
        import base64 as _b64
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": prompt[:4000],
                  "n": 1, "size": "1024x1536", "quality": "medium"},
            timeout=90,
        )
        data = resp.json()
        if "error" in data:
            print(f"  [HookEngine] DALL-E error: {data['error'].get('message','')[:80]}")
            return False
        item = data["data"][0]
        if "b64_json" in item:
            img_bytes = _b64.b64decode(item["b64_json"])
        elif "url" in item:
            img_bytes = requests.get(item["url"], timeout=30).content
        else:
            return False
        img_path = dest.with_suffix(".png")
        img_path.write_bytes(img_bytes)
        frames = HOOK_DUR * VIDEO_FPS
        ok = _ff(
            "-loop", "1", "-i", str(img_path),
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"zoompan=z='min(zoom+0.008,1.15)':d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},setsar=1",
            "-t", str(HOOK_DUR),
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
        )
        img_path.unlink(missing_ok=True)
        return ok and dest.exists() and dest.stat().st_size > 5_000
    except Exception as e:
        print(f"  [HookEngine] DALL-E exception: {e}")
    return False


# ── Nigerian TTS voiceover ─────────────────────────────────────────────────────

def _nigerian_audio(text: str, dest: Path, client: str = "boothop") -> bool:
    """
    Generate hook voiceover MP3.
    G-Inspired: always ElevenLabs (US/UK English).
    BootHop: Azure Nigerian mostly, ElevenLabs occasionally (~1 in 4) for variety.
    """
    try:
        from tts_nigerian import generate_nigerian_tts, generate_american_tts, _elevenlabs
        clean = re.sub(r"[^\x00-\x7F]", "", text).strip()
        if not clean:
            clean = "BootHop, your travel plug" if client != "g-inspired" else "G-Inspired. Zero fees."

        if client == "g-inspired":
            return generate_american_tts(clean, dest, gender="female")

        # BootHop: ~10% chance of using ElevenLabs for voice variety (once every ~10 runs)
        if random.random() < 0.10:
            from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
            if ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID:
                if _elevenlabs(clean, dest):
                    print("  [HookEngine] ElevenLabs voice (variety)")
                    return True

        return generate_nigerian_tts(clean, dest, gender="female")
    except Exception as e:
        print(f"  [HookEngine] TTS error: {e}")
    return False


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_hook(client: str = "boothop", slot: int = 1) -> dict:
    """
    Generate a 2-second cinematic hook clip + voiceover audio.

    Returns:
        {
            "video_path": str | None,   # 1080x1920, 2s, silent video
            "audio_path": str | None,   # 2s hook dialogue MP3
            "dialogue":   str,
            "scene_query": str,
            "success": bool,
        }
    """
    TEMP.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)

    used      = _recent_used()
    used_clips = _recent_clip_ids()
    data    = _claude_generate(client, used)

    # Hard-enforce dedup in code — AI prompt alone is not reliable.
    # Reject if: (a) matches a recently used line, or (b) is permanently silenced.
    if data:
        dialogue_key = data.get("dialogue", "").lower()
        in_cooldown  = dialogue_key[:60] in used
        is_silenced  = any(s in dialogue_key for s in _PERMANENTLY_SILENCED)
        if in_cooldown or is_silenced:
            reason = "permanently silenced" if is_silenced else "14-day cooldown repeat"
            print(f"  [HookEngine] Rejected ({reason}): '{data['dialogue'][:55]}' — forcing fallback")
            data = None

    if not data:
        if client == "g-inspired":
            data = {
                "dialogue":    "Pulled up different today. Zero fees, no drama.",
                "scene_query": "beautiful woman dancing confidently lifestyle wide shot",
                "scene_style": "dancing_vibes",
            }
        else:
            _FALLBACK_HOOKS = [
                # ── Parcel / sending home ───────────────────────────────────────────
                ("DHL quoted me £89. I laughed and opened BootHop.",              "young man laughing on phone outdoors confident wide shot",            "money_moment"),
                ("My parcel reached Lagos before I even got to Heathrow. Mad.",   "Black man smiling checking phone airport departure lounge wide shot",  "airport_vibes"),
                ("Naija aunty asked for groundnut oil. BootHop sorted it for £9.","Black British woman excitedly packing box at home kitchen wide shot", "dancing_vibes"),
                ("Babe tell them BootHop. Stop paying DHL money for no reason.",  "two women friends laughing together smartphone lifestyle wide shot",   "dancing_vibes"),
                ("Someone on this flight is carrying my mum's birthday present.", "smiling woman at airport gate holding boarding pass wide shot",       "airport_vibes"),
                ("The parcel got to Lagos in 2 days. Not DHL. BootHop.",          "stylish Black British man smiling confidently outdoors wide shot",    "money_moment"),
                # ── Earning / traveller side ────────────────────────────────────────
                ("Fam I'm not even going Naija but I'm still making money.",      "young man gym smiling holding phone confident medium shot",           "gym_energy"),
                ("My cousin flew with empty suitcase space. BootHop paid her trip.","young woman pulling wheeled suitcase airport terminal excited wide", "airport_vibes"),
                ("Omo I'm earning just by going home for Christmas. Different.",   "woman celebrating arms raised outdoors lifestyle wide shot",          "dancing_vibes"),
                ("Every traveller is a courier now. BootHop changed the game.",   "stylish man loading suitcase into car boot confidently wide shot",    "luxury_travel"),
                ("She said how did your parcel beat you to Lagos — BootHop did.", "two friends laughing excitedly outdoors lifestyle wide shot",         "dancing_vibes"),
                # ── Savings / price shock ───────────────────────────────────────────
                ("No stress fam — I used BootHop and saved bare money.",          "young woman happy dancing home bedroom confident wide shot",          "dancing_vibes"),
                ("Bro the courier price was what?! BootHop saved my whole budget.","Black men gym talking laughing energetic medium shot",               "gym_energy"),
                ("Diaspora hack: find someone already flying. That's BootHop.",   "stylish Black woman airport lounge confident medium shot",            "airport_vibes"),
                ("Ayo how you manage that luggage allowance? BootHop money!",     "couple at airport departure gate excited wide shot",                  "airport_vibes"),
                # ── Hype / energy ───────────────────────────────────────────────────
                ("Pack that bag fam — BootHop got you sorted, trust!",            "beautiful Black British woman dancing confidently indoors lifestyle wide", "dancing_vibes"),
                ("No cap, BootHop is the smartest thing in the diaspora right now.","Black men at gym talking laughing energetic medium shot",           "gym_energy"),
                ("Omo this trip dey pay for itself, boothop money never lie!",    "stylish woman luxury car keys smiling confident medium shot",         "money_moment"),
                ("Guy where you dey go? Make BootHop handle the logistics.",      "stylish Black British woman airport departure lounge wide shot",      "airport_vibes"),
                ("Bro after the gym I sorted my mum's parcel. Quick quick.",      "Black man gym bag smiling confident leaving gym wide shot",           "gym_energy"),
                ("Sending jollof to Manchester costs less than a Pret sandwich.", "woman laughing kitchen table food friends lifestyle wide shot",       "dancing_vibes"),
            ]
            # Pick a fallback that isn't in the recent used set or permanently silenced
            fresh = [
                f for f in _FALLBACK_HOOKS
                if f[0][:60].lower() not in used
                and not any(s in f[0].lower() for s in _PERMANENTLY_SILENCED)
            ]
            _fb  = random.choice(fresh if fresh else _FALLBACK_HOOKS)
            data = {"dialogue": _fb[0], "scene_query": _fb[1], "scene_style": _fb[2]}

    dialogue    = data["dialogue"]
    scene_query = data["scene_query"]

    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_dest  = TEMP / f"hook_vid_{ts}.mp4"
    audio_dest  = TEMP / f"hook_aud_{ts}.mp3"

    # ── Visual: Pexels -> Pixabay -> DALL-E ──────────────────────────────────
    video_ok = False
    clip_info = _pexels_video(scene_query, used_clips)
    if not clip_info:
        clip_info = _pixabay_video(scene_query, used_clips)

    if clip_info:
        print(f"  [HookEngine] {clip_info['source']} clip id={clip_info['id']}")
        video_ok = _download_and_trim(clip_info["url"], video_dest)

    if not video_ok:
        print(f"  [HookEngine] Stock video failed — trying DALL-E image")
        video_ok = _dalle_image(scene_query, video_dest)

    if not video_ok:
        print(f"  [HookEngine] All visual sources failed — hook skipped")

    # ── Voiceover ─────────────────────────────────────────────────────────────
    audio_ok = _nigerian_audio(dialogue, audio_dest, client=client)
    if not audio_ok:
        print(f"  [HookEngine] Nigerian TTS unavailable — hook will be visual-only")

    # ── Log for dedup ─────────────────────────────────────────────────────────
    if video_ok:
        _save_entry(dialogue, scene_query)
        if clip_info:
            try:
                import json as _json
                from datetime import datetime as _dt
                _vlog = DATA / "video_clip_log.json"
                _log = _json.loads(_vlog.read_text()) if _vlog.exists() else []
                _log.append({"id": str(clip_info["id"]), "logged_at": _dt.now().isoformat()})
                _vlog.write_text(_json.dumps(_log[-500:], indent=2))
            except Exception as _le:
                print(f"  [HookEngine] Local clip log failed: {_le}")
            try:
                from push_pipeline_state import SUPABASE_URL as _SU, SUPABASE_KEY as _SK, _HDR as _SH
                import requests as _rq
                from datetime import datetime as _dt2, timezone as _tz, timedelta as _td
                _now = _dt2.now(_tz.utc)
                _rq.post(
                    f"{_SU}/rest/v1/otb_clip_library",
                    headers={**_SH, "Prefer": "resolution=merge-duplicates,return=minimal"},
                    json=[{
                        "clip_id":        str(clip_info["id"]),
                        "source":         clip_info.get("source", "pixabay"),
                        "beat_type":      "hook",
                        "scene_desc":     scene_query[:200],
                        "pillar":         "hook",
                        "last_used_at":   _now.isoformat(),
                        "cooldown_until": (_now + _td(days=28)).isoformat(),
                        "video_origin":   "hook_engine",
                    }],
                    timeout=10,
                )
            except Exception as _se:
                print(f"  [HookEngine] Supabase clip log failed: {_se}")

    return {
        "video_path":  str(video_dest) if video_ok  else None,
        "audio_path":  str(audio_dest) if audio_ok  else None,
        "dialogue":    dialogue,
        "scene_query": scene_query,
        "success":     video_ok,
    }
