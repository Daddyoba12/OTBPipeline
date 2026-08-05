"""
generate_kling.py — Daily 30-40s BootHop video for otb_midas
─────────────────────────────────────────────────────────────
Composition
  0–15s   Kling cinematic hook  (AI-generated video + Kling built-in voiceover)
  15–40s  Live journey cards    (landmark photo + route + price + Gen-Z text + music)

Schedule  Monday morning (slot 1) / Tuesday afternoon (slot 2) — alternating, one per day
Client    otb_midas only (KLING_ENABLED_SLUGS in config.py)
Fallback  If KLING_API_KEY missing or API down → journey cards + music only (no hook video)
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
    PEXELS_KEY, PIXABAY_KEY, ANTHROPIC_API_KEY,
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

def _market(city: str) -> str:
    return _CITY_MARKET.get(city.lower().strip(), "default")

def _genz_text(origin: str, dest: str) -> str:
    # choose hook based on destination market
    market = _market(dest) or _market(origin) or "default"
    return random.choice(_GENZ[market])


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
        today = datetime.utcnow().date().isoformat()
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
    key = city.lower().strip()
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
    """Convert Windows font path to FFmpeg drawtext format: backslashes→/, escape drive colon."""
    font = font.replace('\\', '/')
    # Escape drive letter colon: C:/ → C\:/
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
    origin = (journey.get("originCity") or "").upper()
    dest   = (journey.get("destinationCity") or "").upper()
    price  = journey.get("price")
    price_str = _ffmpeg_text(f"From GBP {int(price)}" if price else "Competitive rates")
    genz      = _ffmpeg_text(_genz_text(origin, dest))
    route     = _ffmpeg_text(f"{origin}  to  {dest}")

    photo = _fetch_landmark_photo(journey.get("destinationCity") or dest)
    font  = _ffmpeg_font(_safe_font())
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if photo and Path(photo).exists():
        # Background: photo scaled + dark overlay + text
        filtergraph = (
            f"[0:v]scale={CARD_W}:{CARD_H}:force_original_aspect_ratio=increase,"
            f"crop={CARD_W}:{CARD_H},setsar=1,"
            f"colorchannelmixer=rr=0.3:gg=0.3:bb=0.3:aa=1[bg];"
            f"[bg]"
            f"drawtext=fontfile='{font}':fontsize=88:fontcolor=white:"
            f"text='{route}':x=(w-text_w)/2:y=h*0.28:shadowcolor=black:shadowx=3:shadowy=3,"
            f"drawtext=fontfile='{font}':fontsize=44:fontcolor=#FFCC00:"
            f"text='{genz}':x=(w-text_w)/2:y=h*0.42:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=fontfile='{font}':fontsize=56:fontcolor=white:"
            f"text='{price_str}':x=(w-text_w)/2:y=h*0.62:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=fontfile='{font}':fontsize=36:fontcolor=#FF6A00:"
            f"text='BootHop.com':x=(w-text_w)/2:y=h*0.92:shadowcolor=black:shadowx=1:shadowy=1"
            f"[out]"
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
            f"[bg]"
            f"drawtext=fontfile='{font}':fontsize=88:fontcolor=white:"
            f"text='{route}':x=(w-text_w)/2:y=h*0.28:shadowcolor=black:shadowx=3:shadowy=3,"
            f"drawtext=fontfile='{font}':fontsize=44:fontcolor=#FFCC00:"
            f"text='{genz}':x=(w-text_w)/2:y=h*0.42:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=fontfile='{font}':fontsize=56:fontcolor=white:"
            f"text='{price_str}':x=(w-text_w)/2:y=h*0.62,"
            f"drawtext=fontfile='{font}':fontsize=36:fontcolor=#FF6A00:"
            f"text='BootHop.com':x=(w-text_w)/2:y=h*0.92"
            f"[out]"
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

def _narrator_script(journeys: list[dict]) -> str:
    """
    Claude-authored voiceover for the 15-40s journey cards section.
    Reads naturally over the landmark cards. Warm, direct, Gen-Z tone.
    """
    if not journeys:
        return (
            "BootHop connects verified travellers with people who need items delivered — "
            "safely, quickly, at a fraction of courier prices. "
            "Real people. Real routes. Real prices. "
            "Register at BootHop dot com and turn your journey into income."
        )

    route_lines = []
    for j in journeys[:3]:
        o = j.get("originCity", "")
        d = j.get("destinationCity", "")
        p = j.get("price")
        price_str = f"from just £{int(p)}" if p else "at competitive rates"
        route_lines.append(f"{o} to {d}, {price_str}.")

    routes = "  ".join(route_lines)
    return (
        f"These are live journeys available right now on BootHop. "
        f"{routes}  "
        "Verified travellers. No hidden fees. No courier delays. "
        "Your journey can earn — or your package can move today. "
        "Register at BootHop dot com."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — Final video assembler
# ═══════════════════════════════════════════════════════════════════════════════

def _assemble(
    hook_video:     str | None,
    card_paths:     list[str],
    music_path:     str | None,
    voiceover_path: str | None,
    out_path:       Path,
):
    """
    Assemble final 30-40s video:
      [hook_video 15s] + [card_1] + [card_2] + [card_3] + [card_4]
      Music starts at 15s under the cards.
      Voiceover layered over the cards at lower volume.
    """
    inputs  = []
    parts   = []

    if hook_video and Path(hook_video).exists():
        inputs += ["-i", hook_video]
        parts.append(f"[{len(inputs)//2 - 1}:v]scale={CARD_W}:{CARD_H},setsar=1[hook]")

    for i, cp in enumerate(card_paths):
        if Path(cp).exists():
            inputs += ["-i", cp]
            parts.append(f"[{len(inputs)//2 - 1}:v]scale={CARD_W}:{CARD_H},setsar=1[c{i}]")

    if music_path and Path(music_path).exists():
        inputs += ["-i", music_path]
        music_idx = len(inputs) // 2 - 1

    if voiceover_path and Path(voiceover_path).exists():
        inputs += ["-i", voiceover_path]
        vo_idx = len(inputs) // 2 - 1

    # Build concat list
    video_labels = []
    if hook_video and Path(hook_video).exists():
        video_labels.append("[hook]")
    for i in range(len(card_paths)):
        if Path(card_paths[i]).exists():
            video_labels.append(f"[c{i}]")

    n = len(video_labels)
    concat_input = "".join(video_labels)
    filter_chain = "\n".join(parts)
    filter_chain += f"\n{concat_input}concat=n={n}:v=1:a=0[vout]"

    # Audio: mix music + voiceover, music fades in at 15s
    music_offset = 15 if (hook_video and Path(hook_video).exists()) else 0
    audio_filters = []

    if music_path and Path(music_path).exists():
        audio_filters.append(
            f"[{music_idx}:a]adelay={music_offset * 1000}|{music_offset * 1000},"
            f"volume=0.6[music]"
        )

    if voiceover_path and Path(voiceover_path).exists():
        audio_filters.append(
            f"[{vo_idx}:a]adelay={music_offset * 1000}|{music_offset * 1000},"
            f"volume=1.0[vo]"
        )

    if audio_filters:
        if len(audio_filters) == 2:
            filter_chain += "\n" + audio_filters[0]
            filter_chain += "\n" + audio_filters[1]
            filter_chain += "\n[music][vo]amix=inputs=2:duration=shortest[aout]"
        elif len(audio_filters) == 1:
            filter_chain += "\n" + audio_filters[0]
            a_label = audio_filters[0].split("[")[-1].rstrip("]")
            filter_chain += f"\n[{a_label}]acopy[aout]"

    has_audio = bool(audio_filters)
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

    # ── 1. Pick concept
    concept = _pick_concept(day_index)
    print(f"[Kling] Concept: {concept['style']}")

    # ── 2. Generate Kling hook video (15s)
    kling_prompt = _build_kling_prompt(concept, day_index=day_index)
    print(f"[Kling] Submitting hook prompt to API…")
    hook_video = _kling_generate_video(kling_prompt, negative_prompt=_NEGATIVE_PROMPT)
    if not hook_video:
        print("[Kling] Hook video unavailable — will produce cards-only composition")

    # ── 3. Fetch live journeys
    journeys = _fetch_journeys(limit=4)
    print(f"[Kling] {len(journeys)} live journeys loaded")

    # ── 4. Render journey cards
    card_paths = []
    for i, journey in enumerate(journeys):
        card_out = TEMP / f"kling_card_{i}_{today.strftime('%Y%m%d_%H%M')}.mp4"
        try:
            card_paths.append(_render_journey_card(journey, card_out))
            print(f"[Kling] Card {i+1}: {journey.get('originCity')} → {journey.get('destinationCity')}")
        except Exception as e:
            print(f"[Kling] Card {i+1} failed: {str(e).encode('ascii', errors='replace').decode()}")

    if not card_paths:
        print("[Kling] No cards rendered — aborting")
        return None

    # ── 5. Build narrator script + voiceover
    script = _narrator_script(journeys)
    print(f"[Kling] Narrator script: {script[:80]}…")
    voiceover = _kling_tts(script) or _gtts_fallback(script)
    if voiceover:
        print("[Kling] Voiceover ready")
    else:
        print("[Kling] No voiceover — continuing without")

    # ── 6. Pick music
    music = _pick_music()
    if music:
        print(f"[Kling] Music: {Path(music).name}")
    else:
        print("[Kling] No music found — cards will be silent")

    # ── 7. Assemble final video
    final_out = OUTPUT / f"kling_{today.strftime('%Y%m%d')}_{concept['style']}.mp4"
    print(f"[Kling] Assembling final video → {final_out.name}")
    try:
        result = _assemble(
            hook_video=hook_video,
            card_paths=card_paths,
            music_path=music,
            voiceover_path=voiceover,
            out_path=final_out,
        )
        print(f"[Kling] Done — {result}")
        return result
    except Exception as e:
        print(f"[Kling] Assembly failed: {e}")
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=1, choices=[1, 2],
                    help="1=morning, 2=afternoon")
    args = ap.parse_args()
    out = run_kling_production(slot=args.slot)
    print(f"\nOutput: {out or 'FAILED'}")
