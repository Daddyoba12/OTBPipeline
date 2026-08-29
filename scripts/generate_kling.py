"""
generate_kling.py — Daily 30-40s BootHop video for otb_midas
─────────────────────────────────────────────────────────────
Composition
  0–15s   Kling cinematic hook  (Kling -> Runway -> Sora -> Pexels fallback chain)
  15–40s  Live journey cards    (landmark photo + route + price + Gen-Z text + music)

Schedule  Monday morning (slot 1) / Tuesday afternoon (slot 2) — alternating, one per day
Client    otb_midas only (KLING_ENABLED_SLUGS in config.py)
Fallback  Kling -> Runway gen4_turbo -> Sora-2 -> Pexels -> cards-only
"""

import json, os, random, sys, time, textwrap
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ── Path bootstrap ────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from config import (
    KLING_API_KEY, KLING_API_BASE,
    PEXELS_KEY, PIXABAY_KEY, OPENAI_API_KEY,
    RUNWAY_API_KEY, RUNWAY_VIDEO_MODEL, RUNWAY_VIDEO_DURATION,
    MUSIC_DIR, MUSIC_ARCHIVE,
    ASSETS, TEMP, OUTPUT,
    FONT_TITLE, FONT_BODY, FONT_TITLE_FB, FONT_BODY_FB,
    VIDEO_W, VIDEO_H,
)

# ── Lazy FFmpeg helper ────────────────────────────────────────────────────────
def _ffmpeg(*args, timeout: int = 300):
    import subprocess
    r = subprocess.run(["ffmpeg", "-y", *[str(a) for a in args]],
                       capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[-600:])
    return r


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Gen-Z lingua banks
# ═══════════════════════════════════════════════════════════════════════════════

_GENZ = {
    "nigeria": [
        "Package dey go Naija? 📦 We move.",
        "Your parcel wan land Lagos — sorted fam.",
        "Abeg, who dey fly to Lag? Space available.",
        "Omo, your package wan reach Naija soon 🔥",
        "Bros, this trip dey carry packages. Book now.",
        "Naija-bound traveller — space available no cap.",
    ],
    "uk": [
        "Taking a package to London fam? 💷 Sorted.",
        "Heathrow bound — luggage space available. No cap.",
        "London move sorted. Slide into BootHop.",
        "Flying to the UK? Turn your luggage into income.",
        "Ting going London? We got you fam 🇬🇧",
        "UK-bound traveller. Small packages welcome.",
    ],
    "usa": [
        "NYC to Lagos? We move 🇺🇸➡️🇳🇬 No cap.",
        "Sliding from the States to Naija. Book it.",
        "Houston to Lagos — space available fr.",
        "US to Naija? BootHop connects the route fam.",
        "JFK-Lagos traveller. Packages accepted. Book now.",
        "America to Lagos drop-off. Legit and verified ✅",
    ],
    "ireland": [
        "Dublin to Lagos — space available 🇮🇪 Slide in.",
        "Flying Naija from Ireland? Earn on your luggage.",
        "Dublin-bound packages sorted fam. Book it.",
    ],
    "canada": [
        "Toronto to Lagos — we move 🍁 No middleman.",
        "Canada to Naija — your luggage earns. Register now.",
        "Flying Lagos from Canada? BootHop connects.",
    ],
    "default": [
        "Package needs to move? BootHop connects 📦",
        "Verified traveller. Space available. Book now.",
        "Your journey can earn. Register at BootHop.",
        "Space on this route. No courier needed.",
    ],
}

_CITY_MARKET = {
    "lagos": "nigeria", "abuja": "nigeria", "port harcourt": "nigeria",
    "kano": "nigeria",  "enugu": "nigeria", "ibadan": "nigeria",
    "london": "uk",     "manchester": "uk", "birmingham": "uk",
    "glasgow": "uk",    "edinburgh": "uk",  "leeds": "uk",   "bristol": "uk",
    "new york": "usa",  "houston": "usa",   "atlanta": "usa",
    "washington": "usa","chicago": "usa",   "dallas": "usa", "los angeles": "usa",
    "dublin": "ireland","cork": "ireland",
    "toronto": "canada","calgary": "canada","vancouver": "canada",
}

def _clean_city(city: str) -> str:
    """Strip country suffix from city name: 'London, UK' → 'london'."""
    return city.split(',')[0].strip().lower()

def _market(city: str) -> str:
    return _CITY_MARKET.get(_clean_city(city), "default")

def _genz_text(origin: str, dest: str) -> str:
    # choose hook based on destination market
    market = _market(dest) or _market(origin) or "default"
    return random.choice(_GENZ[market])


def _wrap_genz(text: str, max_chars: int = 30) -> tuple[str, str]:
    """Split Gen-Z hook text into up to 2 lines. Returns (line1, line2); line2 may be empty."""
    if len(text) <= max_chars:
        return text, ""
    # Prefer splitting at natural punctuation so the break feels intentional
    for punct in ["?", ".", "!", "—"]:
        idx = text.find(punct, 12)
        if 12 <= idx <= max_chars + 8:
            return text[:idx + 1].strip(), text[idx + 1:].strip()
    # Fall back to last word boundary before max_chars
    split_at = text.rfind(" ", 0, max_chars)
    if split_at == -1:
        split_at = max_chars
    return text[:split_at].strip(), text[split_at:].strip()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Daily hook concepts (15-second Kling scenes)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Actor diversity & visual rotation ────────────────────────────────────────
# Paused character: the shocked woman (hand-over-mouth, wide eyes, phone).
# Do not reuse until intentionally reintroduced after 6–10 new videos.
_NEGATIVE_PROMPT = (
    "shocked woman, hand over mouth, wide eyes staring at phone, extreme surprise expression, "
    "same face repeated, same hairstyle repeated, same actor as previous video, "
    "low quality, blurry, watermark, text overlay, subtitles, cartoon, animation"
)

# Thumbnail hook styles — rotate by concept index so each video opens differently
_THUMBNAIL_HOOKS = [
    "luxury car arrival — a sleek car pulls up and a stylish person steps out",
    "airport luggage trolley — a traveller confidently pushes an overloaded trolley through departures",
    "first-class lounge — a well-dressed person relaxes in a premium airport lounge",
    "family opening a parcel — warm home setting, genuine joy as a package is unwrapped",
    "business owner checking stock — sharp professional inspects fresh inventory just delivered",
    "wedding outfit reveal — a beautiful traditional outfit lifted carefully from a box",
    "student receiving an important item — university room, emotional moment opening a care package",
    "two friends laughing at a restaurant — upscale restaurant, infectious laughter over a shared moment",
    "traveller collecting payment — airport or departure gate, phone notification showing earnings",
    "close-up of attractive luggage or packaging — cinematic product shot, premium feel",
]

_HOOK_CONCEPTS = [
    {
        "style": "glamour_bar",
        "scene": (
            "outside an upscale Lagos bar at night. Two stylish, beautiful adult Nigerian women "
            "meet beside a flashy luxury car. Colourful nightlife lighting, realistic Lagos "
            "nightlife atmosphere, fast-paced and humorous. Clear Nigerian accents and natural "
            "lip-sync. No background music."
        ),
        "timing": [
            ("0-3s",  'They excitedly greet and hug. Girl 1: "Babe! How London?"'),
            ("3-10s", 'Girl 2: "Omo, I dey buzz! Just landed — extra suitcase space and £210 to make!"'),
            ("10-13s",'Girl 1 laughs: "Ha! O ti ja si BootHop niyen!"'),
            ("13-15s","Both women laugh. Fade to black."),
        ],
    },
    {
        "style": "first_class_lounge",
        "scene": (
            "inside a premium first-class airport lounge. A stylish Nigerian woman in designer "
            "clothes sits casually holding only a small handbag. A friend rushes over wide-eyed. "
            "Warm, aspirational lighting. Clear accents, natural lip-sync. No background music."
        ),
        "timing": [
            ("0-3s",  "The friend stops and stares at the empty luggage rack. Confused."),
            ("3-10s", 'Friend: "Wait — where is your entire luggage?!" She smiles: "Sold the space on BootHop. My trip don already pay me."'),
            ("10-13s","She holds up her phone showing a BootHop earnings notification."),
            ("13-15s","Friend's jaw drops slowly. BootHop logo fades in."),
        ],
    },
    {
        "style": "wedding_rescue",
        "scene": (
            "inside a beautiful Lagos family home, warm evening lighting. A mother carefully "
            "packages a traditional Nigerian wedding outfit. Her daughter video-calls from London, "
            "visibly anxious. Emotional and heartwarming. No background music."
        ),
        "timing": [
            ("0-3s",  'Daughter on video call: "Mummy, the wedding is in five days! How will the dress reach me?!"'),
            ("3-10s", 'Mother smiles calmly: "E don sort my dear — a BootHop traveller dey bring am tomorrow."'),
            ("10-13s","A knock at the door. Daughter opens it — the outfit is there."),
            ("13-15s","Daughter gasps and hugs it. BootHop logo appears."),
        ],
    },
    {
        "style": "heathrow_earner",
        "scene": (
            "at Heathrow Airport departure gate. A sharp-suited young Nigerian man checks his "
            "phone. Clean, cinematic airport aesthetic, busy background travellers. "
            "Clear accent, natural reaction. No background music."
        ),
        "timing": [
            ("0-3s",  "He opens the BootHop app — someone nearby needs a package delivered to Lagos."),
            ("3-10s", 'He grins to himself: "£180 for luggage space I wasn\'t using anyway."'),
            ("10-13s","He taps Accept. The departure board behind him shows Lagos."),
            ("13-15s","He pockets his phone confidently. BootHop logo. 'Your journey can earn.'"),
        ],
    },
    {
        "style": "lagos_business",
        "scene": (
            "inside a premium Lagos restaurant, evening. Two sharp-dressed Nigerian business "
            "owners talk over drinks. Stylish, aspirational, fast-paced. No background music."
        ),
        "timing": [
            ("0-3s",  'One leans in: "How you dey get your products from London so fast?"'),
            ("3-10s", 'The other smiles: "BootHop fam. Traveller delivered it yesterday — no courier wahala."'),
            ("10-13s","He lifts the product onto the table. Already in his hands."),
            ("13-15s","Both clink glasses. BootHop logo appears."),
        ],
    },
    {
        "style": "student_care_package",
        "scene": (
            "in a UK university accommodation room. A young Nigerian woman opens an unexpected "
            "care package — spice kit, chin chin, handwritten note from her mum. "
            "Emotional, warm. No background music."
        ),
        "timing": [
            ("0-3s",  "She opens the box. Her face shifts from surprise to disbelief."),
            ("3-10s", 'She video-calls immediately: "Mummy! How?! I thought it would take weeks!" Mum: "BootHop — a traveller brought it."'),
            ("10-13s","She presses the note to her chest."),
            ("13-15s","BootHop logo. 'When time matters more than distance.'"),
        ],
    },
    {
        "style": "comedy_wife",
        "scene": (
            "living room of a stylish Abuja home. A man unwraps a large designer box. "
            "His wife appears with raised eyebrow. Comedy timing, realistic reactions. "
            "No background music."
        ),
        "timing": [
            ("0-3s",  'Wife appears: "How much was the shipping on that?!"'),
            ("3-10s", 'He grins: "Zero. A BootHop traveller brought it. I only paid for the item."'),
            ("10-13s","Wife's arms slowly uncross. Her expression softens into impressed."),
            ("13-15s","She picks up her own phone. BootHop logo appears."),
        ],
    },
]

def _pick_concept(day_index: int) -> dict:
    """Pick concept by day so it rotates predictably through the week."""
    return _HOOK_CONCEPTS[day_index % len(_HOOK_CONCEPTS)]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Kling API
# ═══════════════════════════════════════════════════════════════════════════════

def _kling_headers() -> dict:
    return {
        "Authorization": f"Bearer {KLING_API_KEY}",
        "Content-Type": "application/json",
    }

def _build_kling_prompt(concept: dict, day_index: int = 0) -> str:
    timing_text = "\n".join(f"{t}: {d}" for t, d in concept["timing"])
    thumbnail_hook = _THUMBNAIL_HOOKS[day_index % len(_THUMBNAIL_HOOKS)]
    return (
        f"Create a 15-second cinematic social-media advert for BootHop, set {concept['scene']}\n\n"
        f"Timing:\n{timing_text}\n\n"
        "Rules:\n"
        "- No background music\n"
        "- Clear Nigerian accents and natural lip-sync\n"
        "- Use on-screen text sparingly — do not try to spell BootHop on screen\n"
        "- End on a clean fade to black ready for post-editing\n"
        "- Fast-paced cuts matching the dialogue rhythm\n\n"
        "Actor diversity (mandatory):\n"
        "- Cast completely new actors — different face, hairstyle, clothing, age and body type from any previous video\n"
        "- Avoid shocked expressions, hand-over-mouth poses and extreme wide eyes\n"
        "- Use natural, subtle facial reactions — a smile, a raised eyebrow, a quiet nod\n"
        "- Mix genders, ages (20s–50s) and body types across videos\n\n"
        f"Opening thumbnail hook: {thumbnail_hook}"
    )

def _kling_generate_video(prompt: str, negative_prompt: str = "") -> str | None:
    """
    POST to Kling API → returns task_id, then polls until video URL available.
    Returns local file path on success, None on failure/unavailable.
    """
    if not KLING_API_KEY:
        return None

    payload = {
        "model":    "kling-v1",
        "prompt":   prompt,
        "duration": 5,     # Kling generates 5s segments; we request 3× for 15s
        "cfg_scale": 0.5,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    try:
        r = requests.post(
            f"{KLING_API_BASE}/v1/videos/text2video",
            headers=_kling_headers(),
            json=payload,
            timeout=30,
        )
        if r.status_code == 429:
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            msg  = body.get("message", r.text[:120])
            print(f"[Kling] ⚠️ ACCOUNT ISSUE ({r.status_code}): {msg}")
            if "balance" in msg.lower():
                print("[Kling] → Top up at: https://klingai.com (check wallet)")
            return None
        r.raise_for_status()
        task_id = r.json().get("data", {}).get("task_id")
        if not task_id:
            print(f"[Kling] No task_id in response: {r.text[:200]}")
            return None

        print(f"[Kling] Task created: {task_id} — polling…")
        return _kling_poll(task_id)

    except Exception as e:
        print(f"[Kling] API error: {e}")
        return None


def _kling_poll(task_id: str, max_wait: int = 600) -> str | None:
    """Poll until video is ready, download and return local path."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{KLING_API_BASE}/v1/tasks/{task_id}",
                headers=_kling_headers(),
                timeout=20,
            )
            r.raise_for_status()
            data = r.json().get("data", {})
            status = data.get("task_status", "")

            if status == "succeed":
                video_url = (data.get("task_result") or {}).get("videos", [{}])[0].get("url")
                if video_url:
                    return _download_file(video_url, TEMP / f"kling_hook_{task_id}.mp4")
                return None

            if status in ("failed", "cancelled"):
                print(f"[Kling] Task {status}: {data.get('task_status_msg', '')}")
                return None

            print(f"[Kling] Status: {status} — waiting 15s…")
            time.sleep(15)

        except Exception as e:
            print(f"[Kling] Poll error: {e}")
            time.sleep(15)

    print("[Kling] Timed out waiting for video")
    return None


def _sora_generate_video(prompt: str) -> str | None:
    """
    Generate a short hook video via OpenAI Sora-2.
    Fallback when Kling API has no credits.
    Returns local .mp4 path or None.

    API: POST /v1/videos  →  poll GET /v1/videos/{id}  →  GET /v1/videos/{id}/content
    Supported seconds: 4 | 8 | 12.  Default size: 720x1280 (9:16 portrait).
    """
    if not OPENAI_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        # Submit generation job — request 8s for a richer hook
        r = requests.post(
            "https://api.openai.com/v1/videos",
            headers=headers,
            json={
                "model":   "sora-2",
                "prompt":  prompt,
                "seconds": "8",
                "size":    "720x1280",
            },
            timeout=30,
        )
        if not r.ok:
            print(f"[Sora] Submit error {r.status_code}: {r.text[:200]}")
            return None

        vid_id = r.json().get("id")
        if not vid_id:
            print(f"[Sora] No video ID in response: {r.text[:200]}")
            return None

        print(f"[Sora] Job submitted: {vid_id} — polling…")

        # Poll until complete (max 10 min)
        deadline = time.time() + 600
        while time.time() < deadline:
            poll = requests.get(
                f"https://api.openai.com/v1/videos/{vid_id}",
                headers=headers,
                timeout=20,
            )
            data   = poll.json()
            status = data.get("status", "")
            prog   = data.get("progress", 0)
            print(f"[Sora] {status} {prog}%")

            if status == "completed":
                # Download the video binary
                dl = requests.get(
                    f"https://api.openai.com/v1/videos/{vid_id}/content",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    timeout=120,
                    stream=True,
                )
                dl.raise_for_status()
                out = TEMP / f"sora_hook_{vid_id[:20]}.mp4"
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(out, "wb") as f:
                    for chunk in dl.iter_content(65536):
                        f.write(chunk)
                size_mb = out.stat().st_size / (1024 * 1024)
                print(f"[Sora] Downloaded: {out.name} ({size_mb:.1f}MB)")
                # Scale to full 1080x1920 for consistency with the rest of the pipeline
                scaled = TEMP / f"sora_hook_scaled_{vid_id[:20]}.mp4"
                _ffmpeg(
                    "-i", str(out),
                    "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
                           f"crop={VIDEO_W}:{VIDEO_H},setsar=1",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-an", str(scaled),
                    timeout=120,
                )
                return str(scaled)

            if status in ("failed", "cancelled"):
                print(f"[Sora] Job {status}: {data.get('error', '')}")
                return None

            time.sleep(15)

        print("[Sora] Timed out waiting for video")
        return None

    except Exception as e:
        print(f"[Sora] Error: {e}")
        return None


def _runway_generate_video(prompt: str) -> str | None:
    """
    Generate a hook video via Runway SDK.
    Primary non-Kling fallback. Model + duration configurable via config/keys.env.
    Returns local .mp4 path or None.

    Duration options: 5 (cheaper) or 10 seconds.  Ratio: 720:1280 (9:16 portrait).
    """
    if not RUNWAY_API_KEY:
        return None
    try:
        from runwayml import RunwayML
        client = RunwayML(api_key=RUNWAY_API_KEY)

        task = client.text_to_video.create(
            model=RUNWAY_VIDEO_MODEL,
            prompt_text=prompt,
            ratio="720:1280",
            duration=RUNWAY_VIDEO_DURATION,
        )
        print(f"[Runway] Job submitted: {task.id} ({RUNWAY_VIDEO_MODEL}, {RUNWAY_VIDEO_DURATION}s) — polling…")

        deadline = time.time() + 600
        while time.time() < deadline:
            task = client.tasks.retrieve(task.id)
            print(f"[Runway] {task.status}")
            if task.status == "SUCCEEDED":
                urls = task.output or []
                if not urls:
                    print("[Runway] No output URLs in response")
                    return None
                dl = requests.get(urls[0], timeout=120, stream=True)
                dl.raise_for_status()
                out = TEMP / f"runway_hook_{task.id[:20]}.mp4"
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(out, "wb") as f:
                    for chunk in dl.iter_content(65536):
                        f.write(chunk)
                size_mb = out.stat().st_size / (1024 * 1024)
                print(f"[Runway] Downloaded: {out.name} ({size_mb:.1f}MB)")
                scaled = TEMP / f"runway_hook_scaled_{task.id[:20]}.mp4"
                _ffmpeg(
                    "-i", str(out),
                    "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
                           f"crop={VIDEO_W}:{VIDEO_H},setsar=1",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-an", str(scaled),
                    timeout=120,
                )
                return str(scaled)
            if task.status in ("FAILED", "CANCELLED"):
                print(f"[Runway] Job {task.status}: {getattr(task, 'failure', '')}")
                return None
            time.sleep(15)

        print("[Runway] Timed out waiting for video")
        return None

    except Exception as e:
        print(f"[Runway] Error: {e}")
        return None


def _kling_tts(text: str) -> str | None:
    """Generate voiceover audio via Kling TTS. Returns local .mp3 path or None."""
    if not KLING_API_KEY:
        return None
    try:
        r = requests.post(
            f"{KLING_API_BASE}/v1/audio/text-to-speech",
            headers=_kling_headers(),
            json={
                "text":    text,
                "voice_id": "default",   # Kling default neutral voice
                "speed":    0.95,
            },
            timeout=30,
        )
        r.raise_for_status()
        audio_url = r.json().get("data", {}).get("url")
        if audio_url:
            return _download_file(audio_url, TEMP / "kling_voiceover.mp3")
    except Exception as e:
        print(f"[Kling TTS] Error: {e} — will skip voiceover")
    return None


def _gtts_fallback(text: str) -> str | None:
    """gTTS fallback voiceover when Kling TTS unavailable."""
    try:
        from gtts import gTTS
        out = TEMP / "voiceover_fallback.mp3"
        gTTS(text=text, lang="en", tld="co.uk").save(str(out))
        return str(out)
    except Exception as e:
        print(f"[gTTS] Not available: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Live journey fetcher
# ═══════════════════════════════════════════════════════════════════════════════

JOURNEYS_API = "https://boothop.com/api/journeys"

def _fetch_journeys(limit: int = 4) -> list[dict]:
    """Fetch active live journeys from the BootHop platform API."""
    try:
        r = requests.get(JOURNEYS_API, timeout=15)
        r.raise_for_status()
        journeys = r.json().get("journeys", [])
        # Filter: must have origin, destination, and a future travel date
        today = datetime.now().date().isoformat()
        valid = [
            j for j in journeys
            if j.get("originCity") and j.get("destinationCity")
            and (j.get("departureDate") or "9999") >= today
        ]
        return valid[:limit]
    except Exception as e:
        print(f"[Journeys] Fetch failed: {e} — using template routes")
        return _template_journeys()


def _template_journeys() -> list[dict]:
    """Fallback: hardcoded popular routes when API is down."""
    return [
        {"originCity": "London",    "destinationCity": "Lagos",   "price": 30,  "departureDate": ""},
        {"originCity": "Lagos",     "destinationCity": "London",  "price": 40,  "departureDate": ""},
        {"originCity": "Houston",   "destinationCity": "Lagos",   "price": 45,  "departureDate": ""},
        {"originCity": "Dublin",    "destinationCity": "Lagos",   "price": 35,  "departureDate": ""},
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Landmark photo fetcher (Pexels → Pixabay fallback)
# ═══════════════════════════════════════════════════════════════════════════════

_LANDMARK_QUERIES = {
    "lagos":         ["Lagos skyline Nigeria", "Lagos island aerial night"],
    "abuja":         ["Abuja skyline Nigeria", "Nnamdi Azikiwe Airport"],
    "london":        ["Heathrow Airport terminal premium", "London city skyline aerial"],
    "manchester":    ["Manchester Airport UK", "Manchester Piccadilly"],
    "birmingham":    ["Birmingham Airport", "Birmingham UK skyline"],
    "edinburgh":     ["Edinburgh Airport", "Edinburgh Scotland"],
    "new york":      ["JFK Airport New York", "Manhattan skyline night"],
    "houston":       ["Houston airport terminal", "Houston Texas skyline"],
    "atlanta":       ["Atlanta Hartsfield airport", "Atlanta skyline"],
    "chicago":       ["Chicago O'Hare airport", "Chicago skyline Lake Michigan"],
    "los angeles":   ["LAX airport terminal", "Los Angeles skyline"],
    "dublin":        ["Dublin Airport Ireland", "Dublin city River Liffey"],
    "toronto":       ["Toronto Pearson Airport", "Toronto skyline CN Tower"],
    "default":       ["international airport luxury terminal", "departure lounge premium"],
}

def _landmark_query(city: str) -> str:
    key = _clean_city(city)
    queries = _LANDMARK_QUERIES.get(key, _LANDMARK_QUERIES["default"])
    return random.choice(queries)


def _fetch_photo_pexels(query: str) -> str | None:
    if not PEXELS_KEY:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "per_page": 10, "orientation": "portrait"},
            timeout=15,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            return None
        photo = random.choice(photos[:5])
        url = photo["src"].get("large2x") or photo["src"].get("large")
        return _download_file(url, TEMP / f"landmark_{abs(hash(query))}.jpg")
    except Exception as e:
        print(f"[Pexels] {e}")
        return None


def _fetch_photo_pixabay(query: str) -> str | None:
    if not PIXABAY_KEY:
        return None
    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key":           PIXABAY_KEY,
                "q":             query,
                "image_type":    "photo",
                "orientation":   "vertical",
                "per_page":      10,
                "safesearch":    "true",
            },
            timeout=15,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
        if not hits:
            return None
        hit = random.choice(hits[:5])
        url = hit.get("largeImageURL") or hit.get("webformatURL")
        return _download_file(url, TEMP / f"landmark_px_{abs(hash(query))}.jpg")
    except Exception as e:
        print(f"[Pixabay] {e}")
        return None


def _fetch_pexels_video(query: str, dest: Path, min_duration: int = 15) -> str | None:
    """Download a portrait-orientation Pexels video clip and trim to 15s."""
    if not PEXELS_KEY:
        return None
    try:
        for _attempt in range(3):
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_KEY},
                params={"query": query, "per_page": 15, "orientation": "portrait"},
                timeout=15,
            )
            if r.status_code == 401:
                time.sleep(8)
                continue
            break
        r.raise_for_status()
        videos = [
            v for v in r.json().get("videos", [])
            if v.get("duration", 0) >= min_duration
        ]
        if not videos:
            return None
        vid  = random.choice(videos[:5])
        # Prefer HD portrait file
        files = sorted(
            [f for f in vid.get("video_files", [])
             if f.get("quality") in ("hd", "sd") and f.get("height", 0) >= f.get("width", 1)],
            key=lambda f: f.get("height", 0), reverse=True,
        )
        if not files:
            return None
        raw = _download_file(files[0]["link"], dest.with_suffix(".raw.mp4"))
        # Trim to exactly 15 seconds, scale to 1080x1920
        trimmed = str(dest)
        _ffmpeg(
            "-ss", "0", "-i", raw,
            "-t", "15",
            "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
                   f"crop={VIDEO_W}:{VIDEO_H},setsar=1",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-an", trimmed,
            timeout=120,
        )
        try:
            Path(raw).unlink(missing_ok=True)
        except Exception:
            pass
        return trimmed
    except Exception as e:
        print(f"[Kling] Pexels video fallback error: {e}")
        return None


# Concept → Pexels query map for the hook fallback
_CONCEPT_PEXELS = {
    "airport_earner":   "traveller airport departure lounge stylish",
    "lagos_business":   "business professional Lagos Nigeria city",
    "glamour_bar":      "upscale bar nightlife friends laughing Nigeria",
    "parcel_unboxing":  "family unboxing parcel excited home",
    "comedy_wife":      "couple living room laughing surprise",
}

def _pexels_hook_fallback(concept: dict, day_index: int) -> str | None:
    """Return a trimmed Pexels video to use as the hook when Kling API is unavailable."""
    style   = concept.get("style", "")
    query   = _CONCEPT_PEXELS.get(style) or f"Nigerian lifestyle airport travel {style}"
    dest    = TEMP / f"kling_hook_pexels_{day_index}.mp4"
    result  = _fetch_pexels_video(query, dest)
    if not result:
        # Generic fallback query
        result = _fetch_pexels_video("airport departure lounge traveller", dest)
    return result


def _fetch_landmark_photo(city: str) -> str | None:
    q = _landmark_query(city)
    photo = _fetch_photo_pexels(q) or _fetch_photo_pixabay(q)
    if not photo:
        # widen the search
        q = f"{city} cityscape night"
        photo = _fetch_photo_pexels(q) or _fetch_photo_pixabay(q)
    return photo


def _download_file(url: str, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=60, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    return str(dest)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Journey card renderer (FFmpeg)
# ═══════════════════════════════════════════════════════════════════════════════

CARD_DURATION = 7   # seconds per card
CARD_W = VIDEO_W    # 1080
CARD_H = VIDEO_H    # 1920

def _safe_font() -> str:
    p = Path(FONT_TITLE)
    return str(p) if p.exists() else FONT_TITLE_FB

def _ffmpeg_text(text: str) -> str:
    """Sanitise text for FFmpeg drawtext: strip emoji, escape special chars, fix currency."""
    import unicodedata, re
    text = text.replace('£', 'GBP ').replace('€', 'EUR ').replace('$', 'USD ')
    # Strip non-ASCII (emoji etc)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    # Escape FFmpeg drawtext special chars
    text = text.replace('\\', '\\\\').replace("'", "\\'").replace(':', '\\:')
    return text.strip()

def _ffmpeg_font(font: str) -> str:
    """Return FFmpeg-safe font path. Uses relative path for project fonts (avoids fontconfig)."""
    p = Path(font)
    try:
        rel = p.relative_to(BASE)
        # Use forward-slash relative path — works when ffmpeg is run from BASE dir
        return str(rel).replace('\\', '/')
    except ValueError:
        # System font (e.g. C:\Windows\Fonts\impact.ttf) — use C\:/ format
        font = font.replace('\\', '/')
        if len(font) >= 2 and font[1] == ':':
            font = font[0] + '\\:' + font[2:]
        return font

def _render_journey_card(journey: dict, out_path: Path) -> str:
    """
    Render a single journey card as a video clip.
    Layout:
      - Landmark photo as full-bleed background (dark overlay)
      - Route text centred top-third: LONDON → LAGOS
      - Gen-Z hook text below route
      - Price pill bottom third: "Small package from £30"
      - BootHop brand strip at very bottom
    """
    origin_raw = (journey.get("originCity") or "")
    dest_raw   = (journey.get("destinationCity") or "")
    origin     = _clean_city(origin_raw).upper()
    dest       = _clean_city(dest_raw).upper()
    price      = journey.get("price")
    price_str  = _ffmpeg_text(f"From GBP {int(price)}" if price else "Competitive rates")
    genz_raw   = _ffmpeg_text(_genz_text(origin_raw, dest_raw))
    genz_l1, genz_l2 = _wrap_genz(genz_raw)
    route      = _ffmpeg_text(f"{origin}  to  {dest}")

    photo = _fetch_landmark_photo(journey.get("destinationCity") or dest)
    font  = _ffmpeg_font(_safe_font())
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build text overlay chain dynamically so Gen-Z text wraps cleanly
    def _dt(text: str, size: int, color: str, y: str, sx: int = 2, sy: int = 2) -> str:
        return (
            f"drawtext=fontfile='{font}':fontsize={size}:fontcolor={color}:"
            f"text='{text}':x=(w-text_w)/2:y={y}:"
            f"shadowcolor=black:shadowx={sx}:shadowy={sy}"
        )

    text_layers = [_dt(route, 82, "white", "h*0.25", sx=3, sy=3)]
    if genz_l2:
        text_layers += [
            _dt(genz_l1, 36, "#FFCC00", "h*0.37"),
            _dt(genz_l2, 36, "#FFCC00", "h*0.46"),
        ]
    else:
        text_layers.append(_dt(genz_l1, 40, "#FFCC00", "h*0.42"))
    text_layers += [
        _dt(price_str, 52, "white", "h*0.62"),
        _dt("BootHop.com", 34, "#FF6A00", "h*0.92", sx=1, sy=1),
    ]
    text_chain = ",".join(text_layers)

    if photo and Path(photo).exists():
        # Background: photo scaled + dark overlay + text
        filtergraph = (
            f"[0:v]scale={CARD_W}:{CARD_H}:force_original_aspect_ratio=increase,"
            f"crop={CARD_W}:{CARD_H},setsar=1,"
            f"colorchannelmixer=rr=0.3:gg=0.3:bb=0.3:aa=1[bg];"
            f"[bg]{text_chain}[out]"
        )
        _ffmpeg(
            "-loop", "1", "-i", photo,
            "-filter_complex", filtergraph,
            "-map", "[out]",
            "-t", str(CARD_DURATION),
            "-r", "30",
            "-pix_fmt", "yuv420p",
            str(out_path),
        )
    else:
        # Fallback: coloured card when photo unavailable
        filtergraph = (
            f"color=c=0x0d0d18:s={CARD_W}x{CARD_H}:r=30[bg];"
            f"[bg]{text_chain}[out]"
        )
        _ffmpeg(
            "-f", "lavfi", "-i", f"color=c=0x0d0d18:s={CARD_W}x{CARD_H}:r=30",
            "-filter_complex", filtergraph,
            "-map", "[out]",
            "-t", str(CARD_DURATION),
            "-r", "30",
            "-pix_fmt", "yuv420p",
            str(out_path),
        )

    return str(out_path)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Music picker
# ═══════════════════════════════════════════════════════════════════════════════

def _pick_music() -> str | None:
    for folder in [MUSIC_DIR, MUSIC_ARCHIVE]:
        if not Path(str(folder)).exists():
            continue
        tracks = list(Path(str(folder)).glob("*.mp3")) + list(Path(str(folder)).glob("*.m4a"))
        if tracks:
            return str(random.choice(tracks))
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Narrator script builder
# ═══════════════════════════════════════════════════════════════════════════════

def _hook_narrator_script(concept: dict) -> str:
    """Build spoken narration from the concept's timing dialogue for TTS over the hook section."""
    import re as _re
    lines = []
    for _time, dialogue in concept.get("timing", []):
        quotes = _re.findall(r'"([^"]+)"', dialogue)
        if quotes:
            lines.extend(quotes)
    return " ".join(lines)


def _narrator_script(journeys: list[dict], day_index: int = 0) -> str:
    """
    Voiceover for the journey cards section. Rotates between 3 angles so the same
    script never plays two days running. Warm, direct, TikTok-paced.
    """
    if not journeys:
        return (
            "BootHop connects verified travellers with people who need items delivered. "
            "Real people. Real routes. A fraction of courier prices. "
            "Register at BootHop dot com."
        )

    j0 = journeys[0]
    dest1  = j0.get("destinationCity", "Lagos")
    orig1  = j0.get("originCity", "London")
    price1 = j0.get("price")
    p1_str = f"from just GBP {int(price1)}" if price1 else "at competitive rates"

    route_lines = []
    for j in journeys[:3]:
        o = j.get("originCity", "")
        d = j.get("destinationCity", "")
        p = j.get("price")
        route_lines.append(f"{o} to {d}, GBP {int(p)}" if p else f"{o} to {d}")
    routes_str = ". ".join(route_lines) + "."

    template = day_index % 3

    if template == 0:
        # Earner angle — speaks to the traveller
        return (
            f"Flying to {dest1} soon? "
            f"Your empty luggage could be earning. "
            f"Verified senders waiting — {p1_str} per delivery. "
            f"No middleman. No hassle. "
            f"Register at BootHop dot com in minutes."
        )
    elif template == 1:
        # Sender angle — speaks to the sender
        return (
            f"Someone is heading to {dest1} — with space for your parcel. "
            f"{p1_str}. No courier. No delays. "
            f"BootHop connects you with verified travellers already going your way. "
            f"Book at BootHop dot com today."
        )
    else:
        # Discovery angle — announces live routes
        return (
            f"Live on BootHop right now. {routes_str} "
            f"Real travellers. Verified community. "
            f"Skip the courier — send smarter. "
            f"BootHop dot com."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — Final video assembler
# ═══════════════════════════════════════════════════════════════════════════════

def _assemble(
    hook_video:      str | None,
    card_paths:      list[str],
    music_path:      str | None,
    voiceover_path:  str | None,
    out_path:        Path,
    hook_audio_path: str | None = None,
):
    """
    Assemble final 30-40s video:
      [hook_video 15s] + [card_1] + [card_2] + [card_3] + [card_4]

    Audio layers:
      - Music: plays from t=0 throughout at low volume
      - Hook dialogue TTS: plays from t=0 over the Kling hook section
      - Journey narrator: plays from t=15s over the journey cards
    """
    inputs = []
    parts  = []

    has_hook_vid = bool(hook_video and Path(hook_video).exists())

    if has_hook_vid:
        inputs += ["-i", hook_video]
        parts.append(f"[{len(inputs)//2 - 1}:v]scale={CARD_W}:{CARD_H},setsar=1[hook]")

    for i, cp in enumerate(card_paths):
        if Path(cp).exists():
            inputs += ["-i", cp]
            parts.append(f"[{len(inputs)//2 - 1}:v]scale={CARD_W}:{CARD_H},setsar=1[c{i}]")

    music_idx    = None
    vo_idx       = None
    hook_aud_idx = None

    if music_path and Path(music_path).exists():
        inputs += ["-i", music_path]
        music_idx = len(inputs) // 2 - 1

    if voiceover_path and Path(voiceover_path).exists():
        inputs += ["-i", voiceover_path]
        vo_idx = len(inputs) // 2 - 1

    if hook_audio_path and Path(hook_audio_path).exists() and has_hook_vid:
        inputs += ["-i", hook_audio_path]
        hook_aud_idx = len(inputs) // 2 - 1

    # Build video concat
    video_labels = []
    if has_hook_vid:
        video_labels.append("[hook]")
    for i in range(len(card_paths)):
        if Path(card_paths[i]).exists():
            video_labels.append(f"[c{i}]")

    n = len(video_labels)
    concat_input = "".join(video_labels)
    filter_chain = ";".join(parts)
    filter_chain += f";{concat_input}concat=n={n}:v=1:a=0[vout]"

    # Build audio mix: music (full video) + hook TTS (0-15s) + narrator (15s+)
    cards_offset  = 15 if has_hook_vid else 0
    audio_filters = []
    audio_labels  = []

    if music_idx is not None:
        audio_filters.append(f"[{music_idx}:a]volume=0.25[music]")
        audio_labels.append("[music]")

    if hook_aud_idx is not None:
        audio_filters.append(f"[{hook_aud_idx}:a]volume=1.0[hvo]")
        audio_labels.append("[hvo]")

    if vo_idx is not None:
        audio_filters.append(
            f"[{vo_idx}:a]adelay={cards_offset * 1000}|{cards_offset * 1000},volume=1.0[vo]"
        )
        audio_labels.append("[vo]")

    if audio_labels:
        n_aud = len(audio_labels)
        filter_chain += ";" + ";".join(audio_filters)
        mix_input = "".join(audio_labels)
        filter_chain += f";{mix_input}amix=inputs={n_aud}:duration=longest:normalize=0[aout]"

    has_audio = bool(audio_labels)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        *inputs,
        "-filter_complex", filter_chain,
        "-map", "[vout]",
        *(["-map", "[aout]"] if has_audio else []),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        *(["-c:a", "aac", "-b:a", "192k"] if has_audio else []),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]
    _ffmpeg(*cmd, timeout=600)
    return str(out_path)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def run_kling_production(slot: int = 1) -> str | None:
    """
    Full production run for one Kling video.
    Returns path to final assembled video, or None on failure.

    slot=1 → morning run
    slot=2 → afternoon run
    """
    print("[Kling] Starting production run…")
    today = datetime.now()
    day_index = today.weekday() * 2 + (0 if slot == 1 else 1)

    # ── Guard: skip if another machine already ran Kling today ────────────────
    today_str = today.strftime("%Y%m%d")
    existing = list(OUTPUT.glob(f"kling_{today_str}_*.mp4"))
    if existing:
        print(f"[Kling] Already ran today: {existing[0].name} — skipping duplicate run")
        return str(existing[0])

    # ── 1. Pick concept
    concept = _pick_concept(day_index)
    print(f"[Kling] Concept: {concept['style']}")

    # ── 2. Generate Kling hook video (15s)
    kling_prompt = _build_kling_prompt(concept, day_index=day_index)
    print(f"[Kling] Submitting hook prompt to API…")
    hook_video = _kling_generate_video(kling_prompt, negative_prompt=_NEGATIVE_PROMPT)
    if not hook_video:
        print("[Kling] Kling API unavailable — trying Runway fallback…")
        hook_video = _runway_generate_video(kling_prompt)
        if hook_video:
            print(f"[Kling] Runway hook ready: {Path(hook_video).name}")
        else:
            print("[Kling] Runway unavailable — trying Sora-2 fallback…")
            hook_video = _sora_generate_video(kling_prompt)
            if hook_video:
                print(f"[Kling] Sora-2 hook ready: {Path(hook_video).name}")
            else:
                print("[Kling] Sora unavailable — trying Pexels video fallback…")
                hook_video = _pexels_hook_fallback(concept, day_index)
                if hook_video:
                    print(f"[Kling] Pexels hook ready: {Path(hook_video).name}")
                else:
                    print("[Kling] No hook available — cards-only composition")

    # ── 3. Fetch live journeys
    journeys = _fetch_journeys(limit=4)
    print(f"[Kling] {len(journeys)} live journeys loaded")

    # ── 4. Render journey cards
    card_paths = []
    for i, journey in enumerate(journeys):
        card_out = TEMP / f"kling_card_{i}_{today.strftime('%Y%m%d_%H%M')}.mp4"
        try:
            card_paths.append(_render_journey_card(journey, card_out))
            print(f"[Kling] Card {i+1}: {journey.get('originCity')} -> {journey.get('destinationCity')}")
        except Exception as e:
            print(f"[Kling] Card {i+1} failed: {str(e).encode('ascii', errors='replace').decode()}")

    if not card_paths:
        print("[Kling] No cards rendered — aborting")
        return None

    # ── 5. Build narrator script + journey cards voiceover
    script = _narrator_script(journeys, day_index=day_index)
    print(f"[Kling] Journey narrator: {script[:80]}…")
    voiceover = _kling_tts(script) or _gtts_fallback(script)
    if voiceover:
        print("[Kling] Journey voiceover ready")
    else:
        print("[Kling] No journey voiceover — continuing without")

    # ── 5b. Generate hook dialogue audio (actors' dialogue as TTS over 0-15s)
    hook_audio = None
    if hook_video:
        hook_script = _hook_narrator_script(concept)
        if hook_script:
            print(f"[Kling] Hook dialogue: {hook_script[:80]}…")
            hook_audio = _kling_tts(hook_script) or _gtts_fallback(hook_script)
            if hook_audio:
                print("[Kling] Hook audio ready")
            else:
                print("[Kling] Hook audio unavailable — hook section will use music only")

    # ── 6. Pick music
    music = _pick_music()
    if music:
        print(f"[Kling] Music: {Path(music).name}")
    else:
        print("[Kling] No music found — cards will be silent")

    # ── 7. Assemble final video
    final_out = OUTPUT / f"kling_{today.strftime('%Y%m%d')}_{concept['style']}.mp4"
    print(f"[Kling] Assembling final video -> {final_out.name}")
    result = None
    try:
        result = _assemble(
            hook_video=hook_video,
            card_paths=card_paths,
            music_path=music,
            voiceover_path=voiceover,
            out_path=final_out,
            hook_audio_path=hook_audio,
        )
        print(f"[Kling] Done — {result}")
    except Exception as e:
        print(f"[Kling] Assembly failed: {e}")

    if result:
        size_mb = Path(result).stat().st_size / (1024 * 1024)
        print(f"[Kling] Final output: {size_mb:.1f}MB")
        if size_mb < 5.0:
            print(
                f"[Kling] WARNING: Output is very small ({size_mb:.1f}MB). "
                "Hook video may have failed — check Kling API response above."
            )

    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=1, choices=[1, 2],
                    help="1=morning, 2=afternoon")
    args = ap.parse_args()
    out = run_kling_production(slot=args.slot)
    print(f"\nOutput: {out or 'FAILED'}")
