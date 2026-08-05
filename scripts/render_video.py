"""
OTB_Pipeline " video renderer
5-beat structure: Hook(0-8s) ' Problem(8-16s) ' Stakes(16-20s) ' Resolution(20-28s) ' Lesson card(28-33s) ' Brand end(33-42s)
Innovations vs old pipeline:
  - Animated progress bar (global time, continuous)
  - Stakes text overlay (new beat, indigo accent)
  - Lesson card (dark overlay + lesson text + BootHop CTA)
  - No WC PiP
  - Pexels + Pixabay combined sourcing
"""

import os, sys, json, random, subprocess, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    ASSETS, MUSIC_DIR, MUSIC_ARCHIVE, TEMP, OUTPUT, LOGO_PATH, FIG_END,
    FONT_TITLE, FONT_BODY, FONT_TITLE_FB, FONT_BODY_FB,
    PEXELS_KEY, PIXABAY_KEY, OPENAI_API_KEY,
    VIDEO_W, VIDEO_H, VIDEO_FPS,
    CLIP_DUR, N_CLIPS, LESSON_DUR, BRAND_DUR, TOTAL_DUR,
    PROGRESS_COLOR, PROGRESS_H, DATA,
)

# -- 14-day video clip dedup ---------------------------------------------------
_VIDEO_LOG = DATA / "video_clip_log.json"
_VIDEO_COOLDOWN_DAYS = 14

# -- User clip cooldown --------------------------------------------------------
# Prevents the same user-supplied clip from appearing in consecutive renders.
# Each clip gets a 3-day rest after being used so the feed stays visually fresh.
_USER_CLIP_LOG  = DATA / "user_clip_log.json"
_USER_CLIP_COOLDOWN_DAYS = 14

def _recently_used_user_clip_names(days: int = _USER_CLIP_COOLDOWN_DAYS) -> set:
    from datetime import datetime, timedelta
    if not _USER_CLIP_LOG.exists():
        return set()
    try:
        log    = json.loads(_USER_CLIP_LOG.read_text(encoding="utf-8"))
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return {e["name"] for e in log if e.get("logged_at", "") > cutoff}
    except Exception:
        return set()

def _log_user_clips_used(paths: set):
    from datetime import datetime
    try:
        log = json.loads(_USER_CLIP_LOG.read_text(encoding="utf-8")) if _USER_CLIP_LOG.exists() else []
    except Exception:
        log = []
    now = datetime.now().isoformat()
    for p in paths:
        log.append({"name": Path(p).name, "path": str(p), "logged_at": now})
    _USER_CLIP_LOG.write_text(json.dumps(log[-200:], indent=2, ensure_ascii=False), encoding="utf-8")

# -- Music dedup + silence guard -----------------------------------------------
_MUSIC_LOG = DATA / "music_log.json"

def _track_has_audio(path: Path, min_db: float = -60.0) -> bool:
    """Return False if the track is silent (mean volume below min_db dB)."""
    import subprocess as _sp
    try:
        res = _sp.run(
            ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "NUL"],
            capture_output=True, text=True, timeout=30,
        )
        for line in res.stderr.splitlines():
            if "mean_volume" in line:
                val = float(line.split("mean_volume:")[1].strip().split()[0])
                return val > min_db
    except Exception:
        pass
    return True  # assume ok if ffmpeg unavailable

def _recently_used_music_stems(days: int = 2) -> set:
    from datetime import datetime, timedelta
    if not _MUSIC_LOG.exists():
        return set()
    try:
        log    = json.loads(_MUSIC_LOG.read_text(encoding="utf-8"))
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return {e.get("title", "").lower() for e in log if e.get("logged_at", "") > cutoff}
    except Exception:
        return set()

def _log_music_used(track_path: Path):
    from datetime import datetime
    if not _MUSIC_LOG.exists():
        log = []
    else:
        try:
            log = json.loads(_MUSIC_LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []
    log.append({"title": track_path.stem, "artist": "archive",
                "source": "archive_render", "logged_at": datetime.now().isoformat()})
    _MUSIC_LOG.write_text(json.dumps(log[-90:], indent=2, ensure_ascii=False), encoding="utf-8")

def _load_video_log() -> list:
    if _VIDEO_LOG.exists():
        try: return json.loads(_VIDEO_LOG.read_text(encoding="utf-8"))
        except Exception: return []
    return []

def _save_video_log(clip_ids: set):
    from datetime import datetime
    log = _load_video_log()
    now = datetime.now().isoformat()
    for cid in clip_ids:
        log.append({"id": str(cid), "logged_at": now})
    # Keep 90 days rolling
    _VIDEO_LOG.write_text(json.dumps(log[-500:], indent=2), encoding="utf-8")

def _recently_used_video_ids() -> set:
    from datetime import datetime, timedelta
    log    = _load_video_log()
    cutoff = (datetime.now() - timedelta(days=_VIDEO_COOLDOWN_DAYS)).isoformat()
    return {e["id"] for e in log if e.get("logged_at", "") > cutoff}

import requests
from query_learner import report_hit

W, H = VIDEO_W, VIDEO_H

# "" Fetch-time query guard (3rd and final safety layer) """""""""""""""""""""""
# Mirrors BANNED_QUERY_TERMS in generate_content.py " catches anything that
# somehow survived the first two layers (sanitizer + 14-day dedup).
_BANNED_FETCH_TERMS = {
    # Animals
    "animal","animals","dog","dogs","cat","cats","horse","horses","pet","pets",
    "puppy","puppies","kitten","kittens","bird","birds","lion","tiger","elephant",
    "monkey","fish","rabbit","wildlife","farm","zoo","livestock","parrot",
    "sheep","cow","goat","duck","chicken","pig","hamster","turtle","snake","insect",
    # Food / food delivery brands
    "food","food delivery","uber eats","ubereats","deliveroo","just eat","doordash",
    "grubhub","restaurant","takeaway","takeout","pizza delivery","meal delivery",
    "grocery delivery","grocery","meal","cooking","chef","kitchen","cafe","diner",
    "burger","bakery","supermarket","fast food","dining","breakfast",
    # Christmas / holidays
    "christmas","xmas","santa","reindeer","baubles","nativity","tinsel","advent",
    "carol","festive","halloween","pumpkin","easter","thanksgiving","fireworks",
    "new year party","valentine","bonfire",
    # Generic stock clichs
    "handshake","trophy","medal","piggy bank","cartoon","illustration",
}

# Transport-focused fallbacks organised by clip index (beat order)
# Black/African diaspora subjects — medium/wide shots only, no close-ups
_TRANSPORT_FALLBACKS = [
    "Black British woman london flat worried medium shot",     # 0 hook
    "African travellers airport departures hall wide shot",   # 1 hook
    "Nigerian woman post office counter shocked medium shot", # 2 problem
    "Black traveller train station luggage medium shot",      # 3 problem
    "African woman phone call worried stressed medium shot",  # 4 stakes
    "Black man handing parcel station traveller wide shot",   # 5 resolution
    "African man seated plane window relaxed medium shot",    # 6 resolution
    "Black woman door receiving parcel smiling medium shot",  # 7 lesson
]

# Car-dealership fallbacks for G-Inspired — used when stock footage fails
_CAR_FALLBACKS = [
    "luxury SUV driving mountain road",          # 0 hook
    "sedan driving highway golden hour",         # 1 hook
    "couple at car dealership lot",              # 2 problem
    "man looking at used car stressed",          # 3 problem
    "highway traffic morning commute",           # 4 stakes
    "car salesman handshake customer smiling",   # 5 resolution
    "couple drives new car dealership exit",     # 6 resolution
    "businessman walking to luxury car",         # 7 lesson
]


def _car_dalle_prompt(car: dict, beat: str) -> str:
    """Build a beat-specific DALL-E prompt for G-Inspired automotive clips."""
    make  = car.get("make", "")
    model = car.get("model", "")
    year  = car.get("year", "")
    scenes = {
        "hook": (
            f"Dramatic golden hour automotive commercial photography. "
            f"A {year} {make} {model} parked on an open road, low angle, the car fills the frame. "
            f"No people blocking the car. Cinematic sunset lighting, warm amber sky."
        ),
        "problem": (
            "A stressed man standing in an outdoor used-car lot, surrounded by price tags with hidden fees. "
            "Moody overcast lighting, hands in pockets, clearly frustrated. "
            "Documentary-style, realistic photography."
        ),
        "stakes": (
            "Wide view from inside a car on a busy morning highway, traffic jam ahead. "
            "Driver's hands on steering wheel, commuter stress. "
            "Cinematic bokeh, warm morning light."
        ),
        "resolution": (
            "A happy couple at a clean, bright car dealership signing paperwork. "
            "Friendly salesperson across the desk, all three smiling. "
            "Natural warm lighting, professional dealership interior. Realistic photography."
        ),
        "lesson_pre": (
            f"Confident car owner opening the door of a clean {make} {model} in a bright parking lot. "
            "Professional clean lighting, executive energy. Realistic commercial photography."
        ),
    }
    scene = scenes.get(beat, (
        f"Cinematic automotive photography featuring a {year} {make} {model}. "
        "Clean exterior, professional studio-quality lighting."
    ))
    return (
        f"Photorealistic commercial photography. {scene} "
        f"Vertical 9:16 portrait orientation. No text, no logos, no watermarks. "
        f"High production quality."
    )


def _bh_dalle_prompt(beat: str, content: dict) -> str:
    """Beat-specific DALL-E prompts for BootHop UK-Nigeria delivery clips."""
    scenes = {
        "hook": (
            "Extreme close-up of a Black British woman's face — eyes wide in shock, "
            "staring at her phone screen which shows a large expensive courier price. "
            "Hand raised to mouth in disbelief. Intense emotional expression, shallow "
            "depth of field. Vertical 9:16 portrait orientation."
        ),
        "problem": (
            "Close-up of a stressed Black British woman's face — eyes wide, staring in "
            "disbelief at a phone screen showing a courier price over £300. One hand "
            "pressed to her mouth in shock. Portrait orientation, documentary lighting."
        ),
        "stakes": (
            "Black British woman at kitchen table — head in hands, phone showing expensive "
            "courier fees, bills in background. Defeated and stressed. Tight medium shot, "
            "dim warm home lighting. Portrait orientation."
        ),
        "resolution": (
            "A Black British woman's face lighting up with relief — warm smile, eyes bright, "
            "holding her phone showing a much lower price. Hopeful, relieved expression. "
            "Close-up medium portrait shot, soft natural light."
        ),
        "lesson_pre": (
            "A joyful Nigerian woman standing at her doorstep receiving a delivered parcel "
            "from a smiling visitor. Warm evening light on a residential street. "
            "Emotional medium shot, authentic documentary feel."
        ),
    }
    scene = scenes.get(beat, scenes["hook"])
    return (
        f"Photorealistic commercial photography. {scene} "
        f"Subjects are Black British or Nigerian British people. "
        f"Vertical 9:16 portrait orientation. No text, no logos, no watermarks. "
        f"High production quality."
    )


# Website screenshot directory — user drops screenshots of boothop.com here
# for use as branded fallback clips when all stock footage fails
_WEBSITE_SCREENS_DIR = ASSETS / "website_screens"

# User-provided clips — sent via Telegram and saved here.
# These are used FIRST before Pexels/Pixabay — authentic footage beats stock.
# Beat-tag files: prefix filename with beat name (hook_, problem_, resolution_, etc.)
# Untagged files are used for any beat position.
_USER_CLIPS_DIR = ASSETS / "user_clips"
_BEAT_TAGS = ["hook", "problem", "stakes", "resolution", "lesson"]


_USER_CLIP_CAP = 3   # max user assets per video — rest come from Pexels/Pixabay

def _pick_user_clip(beat: str, exclude_paths: set, allow_untagged: bool = False) -> Path | None:
    """
    Pick a user clip from assets/user_clips/.
    Beat-tagged files (e.g. hook_*, resolution_*) are preferred.
    allow_untagged=True (assets-only mode): if no tagged clip is fresh, fall back to
    any untagged clip, then any available clip, so we never reach external stock sources.
    """
    if not _USER_CLIPS_DIR.exists():
        return None
    all_clips = (list(_USER_CLIPS_DIR.glob("*.mp4"))
                 + list(_USER_CLIPS_DIR.glob("*.mov"))
                 + list(_USER_CLIPS_DIR.glob("*.jpg"))
                 + list(_USER_CLIPS_DIR.glob("*.jpeg"))
                 + list(_USER_CLIPS_DIR.glob("*.png")))
    if not all_clips:
        return None

    recent_names = _recently_used_user_clip_names()
    avail  = [p for p in all_clips if str(p) not in exclude_paths]

    # Beat-tagged clips first
    tagged = [p for p in avail if p.name.lower().startswith(beat)]
    fresh_tagged = [p for p in tagged if p.name not in recent_names]
    if fresh_tagged:
        return random.choice(fresh_tagged)
    if tagged:
        # All tagged clips on cooldown
        if not allow_untagged:
            print(f"    [UserClip] All {beat} clips on 14-day cooldown — skipping to stock footage")
            return None
        # assets-only: use cooldown clip rather than going to stock
        return random.choice(tagged)

    # No tagged clips for this beat at all
    if not allow_untagged:
        return None

    # assets-only fallback: untagged clips (no beat prefix)
    untagged = [p for p in avail if not any(p.name.lower().startswith(t) for t in _BEAT_TAGS)]
    fresh_untagged = [p for p in untagged if p.name not in recent_names]
    if fresh_untagged:
        return random.choice(fresh_untagged)
    if untagged:
        return random.choice(untagged)

    # Last resort in assets-only: any available clip
    fresh_any = [p for p in avail if p.name not in recent_names]
    return random.choice(fresh_any) if fresh_any else (random.choice(avail) if avail else None)

# Airport-specific fallbacks for slot 2 — enforced at every beat position
_AIRPORT_FALLBACKS = [
    "busy airport departures hall Black African travellers luggage wide shot",  # 0 hook
    "airplane taking off runway dramatic wide shot",                             # 1 hook
    "Nigerian woman stressed airport check-in counter medium shot",              # 2 problem
    "Black traveller oversized luggage airport customs shocked medium shot",     # 3 problem
    "African woman worried phone call airport departure lounge medium shot",     # 4 stakes
    "Black traveller handing small parcel cabin bag airport gate wide shot",    # 5 resolution
    "airplane landing runway wide shot cinematic",                               # 6 resolution
    "airport arrivals hall African family reunion smiling wide shot",            # 7 lesson
]


def _guard_query(query: str, clip_index: int = 0) -> str:
    """Block any banned term before it hits Pexels/Pixabay."""
    if any(term in query.lower() for term in _BANNED_FETCH_TERMS):
        safe = _TRANSPORT_FALLBACKS[clip_index % len(_TRANSPORT_FALLBACKS)]
        print(f"    [QueryGuard] Blocked '{query}' -> '{safe}'")
        return safe
    return query

# Beat timing (seconds within the 32s content section)
BEATS = [
    (0,   8,  "hook"),       # clips 0-1
    (8,   16, "problem"),    # clips 2-3
    (16,  20, "stakes"),     # clip  4
    (20,  28, "resolution"), # clips 5-6
    (28,  32, "lesson_pre"), # clip  7 (leads into lesson card)
]

# Beat text layout " one entry per beat type.
# Each line of text is rendered as a SEPARATE drawtext filter with an explicit pixel Y,
# matching BHP pipeline's approach (no \n / line_spacing squash).
#
# y_start   : pixel Y of the first line (1080-1920 frame)
# line_gap  : pixels between lines   font_size - 1.35
# size      : primary font size (px)
# size_cont : continuation font for hook h2/h3 (smaller than punch)
# max_chars : max chars per line before wrapping
# max_lines : max lines rendered per clip
# title_font: True = Oswald-Bold (condensed), False = Montserrat (body)
# color     : hex string, no '#'
BEAT_STYLE = {
    "hook": {
        "size": 82, "size_cont": 64,
        "color": "FFE600",
        "y_start": 1280,  # lower third: face fills top, text below it
        "line_gap": 90,
        "max_chars": 18,
        "max_lines": 3,
        "title_font": True,
    },
    "problem": {
        "size": 72, "color": "FFFFFF",
        "y_start": 750,
        "line_gap": 88,
        "max_chars": 20,
        "max_lines": 3,
        "title_font": False,
    },
    "stakes": {
        "size": 72, "color": "FF8C00",
        "y_start": 740,
        "line_gap": 88,
        "max_chars": 18,
        "max_lines": 3,
        "title_font": True,
    },
    "resolution": {
        "size": 72, "color": "FFFFFF",
        "y_start": 750,
        "line_gap": 88,
        "max_chars": 20,
        "max_lines": 3,
        "title_font": False,
    },
    "lesson_pre": {
        "size": 68, "color": "FFFFFF",
        "y_start": 760,
        "line_gap": 84,
        "max_chars": 20,
        "max_lines": 3,
        "title_font": False,
    },
}

# V2 uses a different colour palette so the two versions are visually distinct.
# Inherits the updated max_lines=3 and y_start values from BEAT_STYLE automatically.
BEAT_STYLE_V2 = {
    "hook":       {**BEAT_STYLE["hook"],       "color": "00CFFF"},  # electric cyan
    "problem":    {**BEAT_STYLE["problem"],    "color": "FFB300"},  # amber
    "stakes":     {**BEAT_STYLE["stakes"],     "color": "FF4081"},  # pink
    "resolution": {**BEAT_STYLE["resolution"], "color": "69FF47"},  # lime green
    "lesson_pre": {**BEAT_STYLE["lesson_pre"], "color": "FFFFFF"},
}

CLIP_BEAT = [
    "hook", "hook",          # clips 0-1  ' Hook
    "problem", "problem",    # clips 2-3  ' Problem
    "stakes",                # clip  4    ' Stakes
    "resolution", "resolution",  # clips 5-6  ' Resolution
    "lesson_pre",            # clip  7    ' Lesson lead-in
]


def _ff(*args, timeout=1200):
    cmd = ["ffmpeg", "-y"] + list(args)
    env = os.environ.copy()
    # Suppress fontconfig "Cannot load default config" warning on Windows.
    # NUL is the Windows null device — on Linux use /dev/null instead.
    _null = "NUL" if os.name == "nt" else "/dev/null"
    env.setdefault("FONTCONFIG_FILE", _null)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        print(f"  [FFmpeg] TIMEOUT after {timeout}s — killing hung process: {' '.join(cmd[-6:])}")
        try:
            _kill = "taskkill" if os.name == "nt" else "killall"
            _args = (["/F", "/IM", "ffmpeg.exe"] if os.name == "nt" else ["ffmpeg"])
            subprocess.run([_kill] + _args, capture_output=True, timeout=5)
        except Exception:
            pass
        return False
    if r.returncode != 0:
        print(f"  [FFmpeg] {' '.join(cmd[-6:])}")
        print(f"  [FFmpeg] stderr: {r.stderr[-400:]}")
    return r.returncode == 0


def _font(kind="title") -> str:
    """Return font path in FFmpeg drawtext format (forward slashes, colon escaped as C\\:/)."""
    path     = FONT_TITLE if kind == "title" else FONT_BODY
    fallback = FONT_TITLE_FB if kind == "title" else FONT_BODY_FB
    # Normalise to a real filesystem path for existence check
    real = path.replace("C\\:/", "C:/").replace("\\", "/")
    if not Path(real).exists():
        return fallback
    # Convert to FFmpeg drawtext format: forward slashes, drive colon escaped
    ffmpeg_path = real.replace("C:/", "C\\:/")
    return ffmpeg_path


def _esc(text: str) -> str:
    """Sanitise text for FFmpeg drawtext single-quoted option values.

    Apostrophes REMOVED (not escaped) - inside text='...' the char closes the
    quoted string; there is no valid escape.  Smart punctuation -> ASCII.
    Currency symbols (pound, euro) kept as Unicode - our fonts support them.
    """
    text = (text
            .replace("—", "-").replace("–", "-")
            .replace("‘", "").replace("’", "").replace("'", "")
            .replace("“", '"').replace("”", '"')
            .replace("…", "..."))
    # Escape FFmpeg drawtext special chars only
    text = (text
            .replace("\\", "\\\\")
            .replace(":",  "\\:")
            .replace("%",  "\\%")
            .replace("[",  "\\[")
            .replace("]",  "\\]"))
    return text[:140]


def _split_lines(text: str, max_chars: int, max_lines: int) -> list[str]:
    """Word-wrap into a list of strings - no newlines, just a list."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if len(test) <= max_chars:
            cur = test
        else:
            if cur:
                lines.append(cur)
                if len(lines) >= max_lines:
                    break
            cur = w[:max_chars]
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines[:max_lines]


def _split_hook(text: str) -> list[str]:
    """BHP-style hook split: first sentence (<=8 words) = punch line.
    Punch line is also word-wrapped at 20 chars so it never renders as one
    overlong line at size=72 (which overflows the 1080px frame or looks cramped).
    Continuation wraps at 22 chars into up to 2 extra lines.
    """
    import re as _re
    clean = _esc(text)
    m = _re.search(r"[.!?]", clean[:80])
    if m and len(clean[: m.start()].split()) <= 8:
        punch       = clean[: m.start()].strip()
        rest        = clean[m.end() :].strip()
        punch_lines = _split_lines(punch, 20, 2)
        rest_lines  = _split_lines(rest, 22, max(1, 4 - len(punch_lines)))
        return (punch_lines + rest_lines)[:4]
    return _split_lines(clean, 24, 4)


_BEAT_LABELS: dict = {}   # beat section labels removed — story text only


def _drawtext_filters(text: str, beat: str, style_override: dict | None = None) -> str:
    """Return comma-chained drawtext filters - one per line - with explicit pixel Y.

    Replaces single drawtext + line_spacing=10 which squashes lines together
    (10px gap is tiny against 52-72px fonts).  Each line is absolutely positioned
    so spacing is proportional to the font size (approx font_size * 1.35).
    """
    palette = style_override or BEAT_STYLE
    style = palette.get(beat, palette.get("problem", BEAT_STYLE["problem"]))
    lines = (_split_hook(text) if beat == "hook"
             else _split_lines(_esc(text), style["max_chars"], style["max_lines"]))
    if not lines:
        return ""

    font  = _font("title" if style.get("title_font") else "body")
    font_b = _font("body")
    y0    = style["y_start"]
    gap   = style["line_gap"]
    color = style["color"]

    parts = []

    # Section label at top-left for non-hook beats (BD-style story structure marker)
    label = _BEAT_LABELS.get(beat, "")
    if label:
        parts.append(
            f"drawtext=fontfile='{font_b}':text='{label}':fontsize=28:"
            f"fontcolor=0xFFFFFF@0.85:x=44:y=72:"
            f"box=1:boxcolor=0x000000@0.5:boxborderw=10"
        )

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        size = (style["size"] if (i == 0 or beat != "hook")
                else style.get("size_cont", style["size"]))
        y = y0 + i * gap
        parts.append(
            f"drawtext=fontfile='{font}':"
            f"text='{line}':"
            f"fontsize={size}:"
            f"fontcolor=0x{color}:"
            f"x=(w-text_w)/2:"
            f"y={y}:"
            f"box=1:boxcolor=0x000000@0.45:boxborderw=10:"
            f"shadowx=4:shadowy=4:shadowcolor=0x000000"
        )
    return ",".join(parts)


def _apply_caption_overlay(clip: Path, text: str) -> None:
    """Overlay a two-line caption bar at the top of a clip using PIL (no fontconfig needed)."""
    if not text or not clip.exists():
        return
    try:
        from PIL import Image, ImageDraw
        CAP_H = 140
        img   = Image.new("RGBA", (W, CAP_H), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (W, CAP_H)], fill=(0, 0, 0, 160))

        font = _load_pil_font("body", 48)
        words = text.split()
        lines: list[str] = []
        cur: list[str]   = []
        for word in words:
            test = " ".join(cur + [word])
            try:
                tw = draw.textbbox((0, 0), test, font=font)[2]
            except Exception:
                tw = len(test) * 20
            if tw > W - 60 and cur:
                lines.append(" ".join(cur))
                cur = [word]
            else:
                cur.append(word)
        if cur:
            lines.append(" ".join(cur))
        lines = lines[:2]

        line_h = 52
        y0     = max(8, (CAP_H - len(lines) * line_h) // 2)
        for i, line in enumerate(lines):
            try:
                tw = draw.textbbox((0, 0), line, font=font)[2]
            except Exception:
                tw = len(line) * 20
            x = max(20, (W - tw) // 2)
            y = y0 + i * line_h
            draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 210))
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

        cap_png = clip.parent / (clip.stem + "_cap.png")
        img.save(str(cap_png), "PNG")

        tmp = clip.parent / (clip.stem + "_caped.mp4")
        # y=130: clears TikTok's native search/status bar (~0-100px) so the
        # story header appears on its own line below it, not overlapping.
        ok  = _ff(
            "-i", str(clip), "-i", str(cap_png),
            "-filter_complex", "[0:v][1:v]overlay=0:192",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-an", str(tmp),
        )
        cap_png.unlink(missing_ok=True)
        if ok and tmp.exists() and tmp.stat().st_size > 5000:
            clip.unlink()
            tmp.rename(clip)
        else:
            tmp.unlink(missing_ok=True)
    except Exception as e:
        print(f"    [Caption] Error: {e}")


# "" Video clip fetching """"""""""""""""""""""""""""""""""""""""""""""""""""""""

def _pexels_video(query: str, exclude_ids: set) -> dict | None:
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": 50, "orientation": "portrait", "size": "medium"},
            headers={"Authorization": PEXELS_KEY},
            timeout=15,
        )
        videos = r.json().get("videos", [])
        for v in random.sample(videos, len(videos)):
            if v["id"] in exclude_ids:
                continue
            # Check Pexels page URL slug for animal/banned terms (e.g. ".../dog-at-airport-1234/")
            page_slug = v.get("url", "").lower()
            if any(term in page_slug for term in _BANNED_FETCH_TERMS):
                print(f"    [Pexels] Skipped banned metadata: {page_slug.split('/')[-2]}")
                continue
            files = sorted(v.get("video_files", []), key=lambda f: f.get("width", 0), reverse=True)
            # Accept portrait files (height > width) at 720p+; orientation=portrait in
            # the API call already filters, so quality field never says "portrait".
            hd = next((f for f in files
                       if f.get("width", 0) >= 720
                       and f.get("height", 0) > f.get("width", 0)), None)
            if not hd:
                # fallback: take any file ≥720px wide (will be cropped to portrait in _process_clip)
                hd = next((f for f in files if f.get("width", 0) >= 720), None)
            if hd:
                return {"id": v["id"], "url": hd["link"], "source": "pexels"}
    except Exception as e:
        print(f"    [Pexels] {query}: {e}")
    return None


def _pixabay_video(query: str, exclude_ids: set) -> dict | None:
    if not PIXABAY_KEY:
        return None
    try:
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": PIXABAY_KEY, "q": query, "video_type": "film",
                    "orientation": "vertical", "per_page": 15},
            timeout=15,
        )
        hits = r.json().get("hits", [])
        for v in random.sample(hits, len(hits)):
            vid_id = f"pb_{v['id']}"
            if vid_id in exclude_ids:
                continue
            # Check Pixabay tags for banned terms using whole-word match so "pig" doesn't
            # block "pigeon", "cat" doesn't block "aircraft", etc.
            tags = v.get("tags", "").lower()
            tag_set = {t.strip() for t in tags.split(",")}
            if tag_set & _BANNED_FETCH_TERMS:
                continue
            sizes = v.get("videos", {})
            url = (sizes.get("large", {}).get("url") or
                   sizes.get("medium", {}).get("url") or
                   sizes.get("small", {}).get("url"))
            if url:
                return {"id": vid_id, "url": url, "source": "pixabay"}
    except Exception as e:
        print(f"    [Pixabay] {query}: {e}")
    return None


def _pexels_photo_as_clip(query: str, dest: Path, duration: int = CLIP_DUR) -> bool:
    """Fallback: download Pexels photo and convert to Ken Burns clip."""
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 8, "orientation": "portrait"},
            headers={"Authorization": PEXELS_KEY},
            timeout=15,
        )
        photos = r.json().get("photos", [])
        if not photos:
            return False
        photo = random.choice(photos[:5])
        url = photo["src"].get("large2x") or photo["src"].get("large")
        img = requests.get(url, timeout=20).content
        img_path = dest.with_suffix(".jpg")
        img_path.write_bytes(img)
        frames = duration * VIDEO_FPS
        ok = _ff(
            "-loop", "1", "-i", str(img_path),
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"zoompan=z='min(zoom+0.003,1.2)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},"
            "setsar=1",
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
        )
        img_path.unlink(missing_ok=True)
        return ok and dest.exists()
    except Exception as e:
        print(f"    [PhotoFallback] {query}: {e}")
    return False


def _dalle_image_as_clip(beat: str, query: str, dest: Path, duration: int = CLIP_DUR,
                         dalle_prompt: str | None = None, cheap: bool = False) -> bool:
    """Generate an AI image and Ken-Burns animate it into a clip.
    cheap=True uses gpt-image-1-mini/medium — for slots 2 & 3 fallback only."""
    if not OPENAI_API_KEY:
        return False
    if dalle_prompt:
        prompt = dalle_prompt
    else:
        beat_mood = {
            "hook":       "dramatic cinematic medium-wide shot, golden hour lighting",
            "problem":    "tense medium shot, moody blue tones, documentary style",
            "stakes":     "emotional medium shot, shallow depth of field, orange accent light",
            "resolution": "warm joyful medium-wide scene, soft natural light, hopeful mood",
            "lesson_pre": "clean professional wide shot, bright neutral tones",
        }.get(beat, "cinematic medium wide shot")
        prompt = (
            f"Photorealistic {beat_mood}. Scene: {query}. "
            f"The main subject should be a person living in the UK — "
            f"could be Black British, Nigerian, or any Western/European ethnicity. "
            f"Vertical 9:16 portrait orientation. No text, no logos, no watermarks. "
            f"High quality professional photography."
        )

    import base64 as _b64
    # cheap=True (slots 2 & 3 fallback): use mini at standard size
    if cheap:
        _models = [("gpt-image-1-mini", "1024x1024", "medium")]
    else:
        _models = [
            ("gpt-image-1", "1024x1536", "medium"),
            ("gpt-image-1-mini", "1024x1536", "medium"),
        ]
    for _model, _size, _quality in _models:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": _model, "prompt": prompt[:4000], "n": 1,
                      "size": _size, "quality": _quality},
                timeout=90,
            )
            data = resp.json()
            if "error" in data:
                print(f"    [ImageGen] {_model}: {data['error'].get('message','')[:80]}")
                continue
            img_item = data["data"][0]
            if "b64_json" in img_item:
                img_bytes = _b64.b64decode(img_item["b64_json"])
            elif "url" in img_item:
                img_bytes = requests.get(img_item["url"], timeout=30).content
            else:
                continue
            img_path = dest.with_suffix(".png")
            img_path.write_bytes(img_bytes)
            frames = duration * VIDEO_FPS
            ok = _ff(
                "-loop", "1", "-i", str(img_path),
                "-vf",
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"zoompan=z='min(zoom+0.002,1.15)':d={frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},setsar=1",
                "-t", str(duration),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
            )
            img_path.unlink(missing_ok=True)
            if ok and dest.exists() and dest.stat().st_size > 5000:
                print(f"    [ImageGen] {_model} generated for: {query[:50]}")
                return True
        except Exception as e:
            print(f"    [ImageGen] {_model}: {e}")
    return False


def _perplexity_suggest_queries(query: str, beat: str) -> list[str]:
    """
    When Pexels + Pixabay + photo fallback all fail, ask Perplexity to suggest
    3 better Pexels-friendly search terms. Returns up to 3 alternative query strings.
    This keeps us on licensed stock media rather than jumping straight to DALL-E.
    """
    import re as _re
    try:
        from config import PERPLEXITY_KEY
        if not PERPLEXITY_KEY or not PERPLEXITY_KEY.startswith("pplx-"):
            return []
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"},
            json={
                "model": "sonar",
                "messages": [{
                    "role": "user",
                    "content": (
                        f"I'm searching Pexels for stock footage but got no results for: \"{query}\"\n"
                        f"Beat type: {beat} (hook=tense/worried, problem=shocked/frustrated, "
                        f"stakes=emotional, resolution=relief/handover, lesson_pre=happy/confident)\n"
                        f"Suggest 3 alternative Pexels search queries with more likely results.\n"
                        f"Rules: max 6 words each, include 'medium shot' or 'wide shot', "
                        f"Black British/Nigerian/African subjects where people appear, "
                        f"no animals, no food, no brand names, no close-ups.\n"
                        f"Return ONLY valid JSON: {{\"alternatives\": [\"query1\", \"query2\", \"query3\"]}}"
                    ),
                }],
                "max_tokens": 120,
            },
            timeout=12,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        m = _re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group())
            alts = [str(a).strip() for a in data.get("alternatives", []) if a]
            print(f"    [Perplexity] Suggested alternatives: {alts}")
            return alts[:3]
    except Exception as e:
        print(f"    [Perplexity] Query suggest failed: {e}")
    return []


def _veo_video_as_clip(beat: str, video_prompt: str, dest: Path, duration: int = CLIP_DUR) -> bool:
    """
    Generate a 4-second vertical video clip using Google Veo via the Gemini API.
    Uses the full cinematic prompt already written by the Cinematographer (Stage 5).
    Falls back gracefully if Veo API is unavailable or quota exceeded.

    The operation is async: we start generation, then poll every 8s for up to 3 minutes.
    """
    import time, re as _re
    try:
        from config import GEMINI_API_KEY
        if not GEMINI_API_KEY:
            return False

        if not video_prompt or len(video_prompt) < 10:
            return False

        # Build a safe 9:16 portrait prompt — add vertical framing instruction
        safe_prompt = (
            f"{video_prompt.strip()} "
            f"Vertical 9:16 portrait orientation. "
            f"Photorealistic. No text overlays. No logos. No watermarks. "
            f"High production quality short film style."
        )[:4000]

        # POST — start video generation (long-running operation)
        # Use veo-3.1-fast for speed (pipeline runs 8 clips); full quality = veo-3.1-generate-preview
        start_resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-fast-generate-preview:generateVideo",
            params={"key": GEMINI_API_KEY},
            json={
                "instances": [{"prompt": safe_prompt}],
                "parameters": {
                    "aspectRatio":     "9:16",
                    "durationSeconds": max(5, duration),  # Veo minimum is 5s
                    "sampleCount":     1,
                },
            },
            timeout=30,
        )
        if start_resp.status_code in (400, 401, 403, 429, 503):
            print(f"    [Veo] API error {start_resp.status_code}: {start_resp.text[:120]}")
            return False
        start_resp.raise_for_status()

        operation = start_resp.json()
        op_name = operation.get("name", "")
        if not op_name:
            print(f"    [Veo] No operation name in response")
            return False

        print(f"    [Veo] Generation started: {op_name[-40:]}")

        # Poll for completion — Veo typically takes 60-120s
        for attempt in range(23):   # up to ~3 minutes (23 × 8s = 184s)
            time.sleep(8)
            poll = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/{op_name}",
                params={"key": GEMINI_API_KEY},
                timeout=20,
            )
            if not poll.ok:
                continue
            data = poll.json()
            if not data.get("done"):
                print(f"    [Veo] Still generating... ({attempt * 8}s elapsed)")
                continue

            # Done — extract video URI
            error = data.get("error")
            if error:
                print(f"    [Veo] Generation error: {error.get('message', error)[:100]}")
                return False

            videos = (data.get("response", {}).get("videos")
                      or data.get("response", {}).get("generatedVideos", []))
            if not videos:
                print(f"    [Veo] No videos in response")
                return False

            video_uri = (videos[0].get("uri") or videos[0].get("video", {}).get("uri", ""))
            if not video_uri:
                print(f"    [Veo] No URI in video object")
                return False

            # Download the generated video
            vid_bytes = requests.get(
                video_uri,
                headers={"Authorization": f"Bearer {GEMINI_API_KEY}"}
                if not video_uri.startswith("https://generativelanguage") else {},
                params={"key": GEMINI_API_KEY}
                if video_uri.startswith("https://generativelanguage") else {},
                timeout=60,
                stream=True,
            ).content

            if len(vid_bytes) < 10_000:
                print(f"    [Veo] Downloaded file too small ({len(vid_bytes)} bytes)")
                return False

            # Write raw Veo file and re-encode to our target spec (trim to CLIP_DUR)
            raw_veo = dest.parent / (dest.stem + "_veo_raw.mp4")
            raw_veo.write_bytes(vid_bytes)
            ok = _ff(
                "-i", str(raw_veo),
                "-t", str(duration),
                "-vf",
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1",
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
            )
            raw_veo.unlink(missing_ok=True)
            if ok and dest.exists() and dest.stat().st_size > 10_000:
                print(f"    [Veo] Generated clip for: {video_prompt[:60]}")
                return True
            return False

        print(f"    [Veo] Timed out after 3 minutes")
        return False

    except Exception as e:
        print(f"    [Veo] Failed: {e}")
        return False


def _website_fallback_as_clip(beat: str, query: str, dest: Path, duration: int = CLIP_DUR) -> bool:
    """
    Branded fallback when all stock footage AND DALL-E fail.
    Priority:
      1. Pre-saved website screenshots in assets/website_screens/ — Ken Burns animated
      2. Generated BootHop brand card (purple/navy with tagline + URL)
    The output is a silent clip that _process_clip() will overlay with beat text.
    """
    font_t = _font("title")
    font_b = _font("body")

    # 1. Use a pre-saved boothop.com screenshot if available
    if _WEBSITE_SCREENS_DIR.exists():
        screens = (list(_WEBSITE_SCREENS_DIR.glob("*.jpg"))
                   + list(_WEBSITE_SCREENS_DIR.glob("*.png"))
                   + list(_WEBSITE_SCREENS_DIR.glob("*.jpeg")))
        if screens:
            recent_names = _recently_used_user_clip_names()
            fresh = [p for p in screens if p.name not in recent_names]
            img_path = random.choice(fresh if fresh else screens)
            frames = duration * VIDEO_FPS
            ok = _ff(
                "-loop", "1", "-i", str(img_path),
                "-vf",
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"zoompan=z='min(zoom+0.002,1.15)':d={frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},"
                "setsar=1",
                "-t", str(duration),
                "-c:v", "libx264", "-crf", "22", "-preset", "fast",
                "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
            )
            if ok and dest.exists() and dest.stat().st_size > 5000:
                print(f"    [WebsiteFallback] Screenshot used: {img_path.name}")
                _log_user_clips_used({str(img_path)})
                return True

    # 2. Generate a BootHop branded card as background for beat-text overlay
    plain = dest.parent / (dest.stem + "_wb_plain.mp4")
    ok = _ff(
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x130B4D:rate={VIDEO_FPS}",
        "-t", str(duration), "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(plain),
    )
    if not ok or not plain.exists():
        return False

    vf = ",".join([
        f"drawtext=fontfile='{font_t}':text='BootHop':fontsize=120:"
        f"fontcolor=0xFFE600:x=(w-text_w)/2:y=h*0.35:"
        f"shadowcolor=0x000000@0.7:shadowx=4:shadowy=4",
        f"drawtext=fontfile='{font_b}':text='Movement already exists.':fontsize=40:"
        f"fontcolor=0xFFFFFF@0.85:x=(w-text_w)/2:y=h*0.52",
        f"drawtext=fontfile='{font_b}':text='BootHop makes it useful.':fontsize=40:"
        f"fontcolor=0xFFFFFF@0.85:x=(w-text_w)/2:y=h*0.58",
        f"drawtext=fontfile='{font_b}':text='boothop.com':fontsize=48:"
        f"fontcolor=0xFFE600@0.95:x=(w-text_w)/2:y=h*0.72",
    ])
    result = _ff(
        "-i", str(plain), "-vf", vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(dest),
    )
    plain.unlink(missing_ok=True)
    if not result and plain.exists():
        import shutil; shutil.copy2(plain, dest)
    return dest.exists() and dest.stat().st_size > 5000


def _download_clip(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return dest.exists() and dest.stat().st_size > 10_000
    except Exception as e:
        print(f"    [Download] {e}")
    return False


def _process_clip(src: Path, dest: Path, beat: str, beat_text: str,
                  style_override: dict | None = None, top_caption: str = "") -> bool:
    """Resize, crop to 9:16, sharpen, add beat text overlay, trim to CLIP_DUR."""
    base_vf = ",".join([
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}",
        "setsar=1",
        "unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount=0.8",
    ])
    text_f = _drawtext_filters(beat_text, beat, style_override)
    vf = f"{base_vf},{text_f}" if text_f else base_vf
    ok = _ff(
        "-ss", "0", "-i", str(src),
        "-t", str(CLIP_DUR),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an",
        str(dest),
    )
    if not ok and text_f:
        # drawtext failed (Windows fontconfig issue) — retry without text overlay
        dest.unlink(missing_ok=True)
        ok = _ff(
            "-ss", "0", "-i", str(src),
            "-t", str(CLIP_DUR),
            "-vf", base_vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an",
            str(dest),
        )
    # Burn top caption onto every beat via PIL (reliable, no fontconfig needed)
    if top_caption and ok and dest.exists():
        _apply_caption_overlay(dest, top_caption)
    return ok


# ── PIL card helpers (used by lesson card and CTA card) ───────────────────────

def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _load_pil_font(kind: str, size: int):
    from PIL import ImageFont
    custom = FONT_TITLE if kind == "title" else FONT_BODY
    custom = custom.replace("C\\:/", "C:/").replace("\\", "/")
    for path in [custom,
                 r"C:\Windows\Fonts\impact.ttf" if kind == "title" else r"C:\Windows\Fonts\arialbd.ttf",
                 r"C:\Windows\Fonts\arial.ttf"]:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _pil_draw_centered(draw, text: str, y: int, font, color: tuple, shadow: bool = True):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(text) * (font.size if hasattr(font, "size") else 20)
    x = max(0, (W - tw) // 2)
    if shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=color)


def _eval_y(expr: str) -> int:
    import re
    m = re.match(r"h\s*\*\s*(\d+\.?\d*)", expr.strip())
    if m:
        return int(H * float(m.group(1)))
    return H // 2


def _pil_png_to_video(png: Path, dest: Path, duration: int) -> bool:
    ok = _ff(
        "-loop", "1", "-i", str(png),
        "-t", str(duration),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
    )
    return ok and dest.exists() and dest.stat().st_size > 5000


def _text_card_clip(hook_text: str, dest: Path, duration: int = CLIP_DUR) -> bool:
    """
    Proven TikTok hook format: dark branded background + centered hook text.
    First sentence in large yellow (punch), rest in smaller white (sub-hook).
    No stock footage — text IS the visual. Native, not ad-like.
    """
    try:
        from PIL import Image, ImageDraw
        img  = Image.new("RGB", (W, H), (8, 14, 28))   # #080E1C very dark navy
        draw = ImageDraw.Draw(img)

        # Thin brand-accent strip at the very bottom
        draw.rectangle([(0, H - 8), (W, H)], fill=(255, 107, 0))

        font_punch = _load_pil_font("title", 88)   # Oswald Bold — punch line
        font_cont  = _load_pil_font("body",  52)   # Montserrat  — sub-hook

        hook_lines  = _split_hook(_esc(hook_text))
        punch_lines = hook_lines[:2]
        cont_lines  = hook_lines[2:]

        punch_h = 104   # px per punch line
        cont_h  = 72    # px per cont line
        gap_mid = 36    # gap between punch and sub-hook

        total = (len(punch_lines) * punch_h
                 + (gap_mid + len(cont_lines) * cont_h if cont_lines else 0))
        y = (H - total) // 2 - 50   # slightly above dead center

        for line in punch_lines:
            _pil_draw_centered(draw, line, y, font_punch, (255, 230, 0), shadow=True)
            y += punch_h

        if cont_lines:
            y += gap_mid
            for line in cont_lines:
                _pil_draw_centered(draw, line, y, font_cont, (210, 210, 210), shadow=True)
                y += cont_h

        png = dest.with_suffix(".png")
        img.save(str(png), "PNG")
        ok = _ff(
            "-loop", "1", "-i", str(png),
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
        )
        png.unlink(missing_ok=True)
        return ok and dest.exists() and dest.stat().st_size > 1000
    except Exception as e:
        print(f"    [TextCard] PIL failed ({e}) — ffmpeg plain card")
        ok = _ff(
            "-f", "lavfi", "-i",
            f"color=size={W}x{H}:color=0x080E1C:rate={VIDEO_FPS}",
            "-vf",
            f"drawbox=x=0:y={H-8}:w={W}:h=8:color=0xFF6B00:t=fill",
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-an", str(dest),
        )
        return ok and dest.exists() and dest.stat().st_size > 1000


# ── Lesson card ───────────────────────────────────────────────────────────────

def _make_merged_end_card(lesson: str, client: str, client_profile: dict, dest: Path) -> bool:
    """
    Single 10-second end card that merges the lesson takeaway + CTA contact block.
    Layout  (top → bottom):
      - Lesson text  (large yellow, centred, upper half)
      - Divider line
      - CTA phrase   (rotating, body font, white)
      - Brand name   (title font, yellow)
      - Contact info (phone / email / website)
    Background colour picked randomly from client’s palette each render.
    """
    duration = LESSON_DUR + BRAND_DUR   # 10 seconds

    # ── Pick a random palette from client profile ────────────────────────────
    palettes = client_profile.get("end_card_palettes", [
        {"bg": "4F46E5", "title": "FFE600", "body": "FFFFFF"},
    ])
    pal     = random.choice(palettes)
    bg_hex  = pal.get("bg", "4F46E5")
    tc_hex  = pal.get("title", "FFE600")   # title / accent colour
    bc_hex  = pal.get("body",  "FFFFFF")   # body text colour

    # ── Pick a random CTA phrase ─────────────────────────────────────────────
    phrases = client_profile.get("cta_phrases", ["Visit us today"])
    cta     = random.choice(phrases)

    # ── Contact info (non-BootHop only) ─────────────────────────────────────
    phone   = client_profile.get("phone", "")
    email   = client_profile.get("contact_email", "")
    website = (client_profile.get("website", "")
               .replace("https://www.", "").replace("https://", ""))
    brand   = client_profile.get("brand_name", "")

    png = dest.parent / (dest.stem + "_end.png")
    try:
        from PIL import Image, ImageDraw

        img  = Image.new("RGB", (W, H), _hex_to_rgb(bg_hex))
        draw = ImageDraw.Draw(img)

        tc = _hex_to_rgb(tc_hex)
        bc = _hex_to_rgb(bc_hex)

        # ── Lesson text (upper ~40% of frame) ───────────────────────────────
        lesson_clean = (lesson
                        .replace("’", "").replace("‘", "").replace("’", "")
                        .replace("—", "-").replace("–", "-"))
        lesson_lines = _split_lines(lesson_clean, 26, 3)
        ft_lesson    = _load_pil_font("title", 66)
        n            = len(lesson_lines)
        line_gap     = 90
        y_lesson     = int(H * 0.22)
        for i, ln in enumerate(lesson_lines):
            _pil_draw_centered(draw, ln, y_lesson + i * line_gap, ft_lesson, tc, shadow=True)

        # ── Divider ──────────────────────────────────────────────────────────
        div_y = int(H * 0.48)
        draw.rectangle([(80, div_y), (W - 80, div_y + 4)], fill=_hex_to_rgb(tc_hex))

        # ── CTA phrase ───────────────────────────────────────────────────────
        ft_cta = _load_pil_font("body", 42)
        _pil_draw_centered(draw, cta, int(H * 0.54), ft_cta, bc, shadow=False)

        # ── Brand + contact (BootHop: just website; others: full contact) ───
        ft_brand   = _load_pil_font("title", 72)
        ft_contact = _load_pil_font("body",  38)
        ft_small   = _load_pil_font("body",  32)

        if client == "boothop" or not client:
            _pil_draw_centered(draw, brand,   int(H * 0.64), ft_brand,   tc, shadow=True)
            _pil_draw_centered(draw, website, int(H * 0.76), ft_contact, bc, shadow=False)
        else:
            _pil_draw_centered(draw, brand,   int(H * 0.62), ft_brand,   tc, shadow=True)
            if phone:
                _pil_draw_centered(draw, phone, int(H * 0.72), ft_contact, bc, shadow=False)
            if email:
                _pil_draw_centered(draw, email, int(H * 0.80), ft_small,   bc, shadow=False)
            if website:
                _pil_draw_centered(draw, website, int(H * 0.87), ft_small, tc, shadow=False)

        img.save(str(png))
        ok = _pil_png_to_video(png, dest, duration)
        png.unlink(missing_ok=True)
        return ok

    except Exception as e:
        print(f"    [EndCard] PIL error: {e} — plain fallback")
        png.unlink(missing_ok=True)
        ok = _ff(
            "-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x{bg_hex}:rate={VIDEO_FPS}",
            "-t", str(duration), "-c:v", "libx264", "-crf", "20",
            "-preset", "fast", "-pix_fmt", "yuv420p", "-an", str(dest),
        )
        return ok and dest.exists() and dest.stat().st_size > 5000


def _add_progress_bar(src: Path, dest: Path) -> bool:
    """Burn a static accent bar at the bottom of the video."""
    import shutil
    # Use ih/iw (lowercase) " uppercase H/W are not defined in drawbox expressions
    vf = f"drawbox=x=0:y=ih-{PROGRESS_H}:w=iw:h={PROGRESS_H}:color={PROGRESS_COLOR}:t=fill"
    ok = _ff(
        "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(dest),
    )
    if not ok:
        shutil.copy(src, dest)
    return dest.exists() and dest.stat().st_size > 0


def _add_logo(src: Path, logo: Path, dest: Path) -> bool:
    if not logo.exists():
        import shutil; shutil.copy(src, dest); return True
    return _ff(
        "-i", str(src), "-i", str(logo),
        "-filter_complex",
        f"[1:v]scale=180:-1[logo];[0:v][logo]overlay=W-180-20:160",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy", str(dest),
    )


def _add_music(src: Path, dest: Path, slot: int = None, exclude_track: Path | None = None) -> Path | None:
    """
    Mix in slot-specific trending music. Priority:
      1. music/daily/track_{slot}.mp3  " today's trending pick for this slot
      2. Any file in music/daily/       " another slot's trending pick
      3. music/archive/                 " royalty-free fallback library
    exclude_track: skip this specific file (used so V2 gets different music from V1).
    Returns the Path of the track used, or None if no audio was available.
    Falls back to file copy (no audio) if all dirs are empty.
    """
    import shutil

    track = None

    # 1. Slot-specific daily track
    if slot:
        slot_track = MUSIC_DIR / f"track_{slot}.mp3"
        if slot_track.exists() and slot_track.stat().st_size > 50_000:
            if exclude_track is None or slot_track.resolve() != exclude_track.resolve():
                if _track_has_audio(slot_track):
                    track = slot_track
                else:
                    print(f"    [Music] Skipping silent daily track: {slot_track.name}")

    # 2. Any daily track (excluding silent and already used)
    if track is None:
        daily = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.m4a"))
        daily = [t for t in daily
                 if t.stat().st_size > 50_000 and "_tmp" not in str(t)
                 and (exclude_track is None or t.resolve() != exclude_track.resolve())
                 and _track_has_audio(t)]
        if daily:
            track = random.choice(daily)

    # 3. Archive fallback — exclude recently used and silent tracks
    if track is None:
        archive = list(MUSIC_ARCHIVE.glob("*.mp3")) + list(MUSIC_ARCHIVE.glob("*.m4a"))
        archive = [t for t in archive
                   if (exclude_track is None or t.resolve() != exclude_track.resolve())
                   and _track_has_audio(t)]
        if archive:
            recent_stems = _recently_used_music_stems(days=2)
            fresh = [t for t in archive if t.stem.lower() not in recent_stems]
            track = random.choice(fresh) if fresh else random.choice(archive)

    if track is None:
        shutil.copy(src, dest)
        return None

    # Log archive picks so the 2-day dedup works across renders
    if track.parent == MUSIC_ARCHIVE.resolve() or track.parent == MUSIC_ARCHIVE:
        _log_music_used(track)

    total = float(TOTAL_DUR)
    print(f"    [Music] Using: {track.name}")
    # -stream_loop -1 loops audio at demuxer level; -t cuts output at exactly total
    # seconds. atrim is intentionally omitted — it interacts badly with looped MP3
    # timestamps on Windows and causes audio to cut short on tracks < TOTAL_DUR.
    _ff(
        "-i", str(src),
        "-stream_loop", "-1", "-i", str(track),
        "-filter_complex",
        f"[1:a]afade=t=out:st={total-3}:d=3,volume=0.85[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(total),
        str(dest),
    )
    return track


def _tts_narration(content: dict, dest: Path) -> bool:
    """Generate OpenAI TTS narration for story beats. Returns True on success."""
    if not OPENAI_API_KEY:
        return False
    parts = []
    for key in ("hook", "problem", "stakes", "resolution", "lesson"):
        t = content.get(key, "").strip().rstrip(".")
        if t:
            parts.append(t)
    script = ". ".join(parts) + "."
    try:
        resp = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "tts-1", "input": script[:4096], "voice": "nova", "speed": 0.88},
            timeout=30,
        )
        if not resp.ok:
            print(f"    [TTS] API error {resp.status_code}: {resp.text[:80]}")
            return False
        dest.write_bytes(resp.content)
        return dest.exists() and dest.stat().st_size > 1000
    except Exception as e:
        print(f"    [TTS] Failed: {e}")
        return False


def _add_music_with_voiceover(src: Path, dest: Path, tts_path: Path,
                               slot: int = None, exclude_track: Path | None = None) -> Path | None:
    """Mix TTS narration (full volume) + music (25% ducked) into the video."""
    import shutil
    track = None
    if slot:
        slot_track = MUSIC_DIR / f"track_{slot}.mp3"
        if slot_track.exists() and slot_track.stat().st_size > 50_000:
            if (exclude_track is None or slot_track.resolve() != exclude_track.resolve()):
                if _track_has_audio(slot_track):
                    track = slot_track
    if track is None:
        daily = [t for t in (list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.m4a")))
                 if t.stat().st_size > 50_000 and "_tmp" not in str(t)
                 and (exclude_track is None or t.resolve() != exclude_track.resolve())
                 and _track_has_audio(t)]
        if daily:
            track = random.choice(daily)
    if track is None:
        archive = [t for t in (list(MUSIC_ARCHIVE.glob("*.mp3")) + list(MUSIC_ARCHIVE.glob("*.m4a")))
                   if (exclude_track is None or t.resolve() != exclude_track.resolve())
                   and _track_has_audio(t)]
        if archive:
            recent_stems = _recently_used_music_stems(days=2)
            fresh = [t for t in archive if t.stem.lower() not in recent_stems]
            track = random.choice(fresh) if fresh else random.choice(archive)
    if track is None:
        shutil.copy(src, dest)
        return None
    total = float(TOTAL_DUR)
    print(f"    [Music+TTS] Using: {track.name}")
    ok = _ff(
        "-i", str(src),
        "-stream_loop", "-1", "-i", str(track),
        "-i", str(tts_path),
        "-filter_complex",
        f"[1:a]afade=t=out:st={total-3}:d=3,volume=0.22[mus];"
        f"[2:a]volume=1.0,adelay=400|400[nar];"
        f"[mus][nar]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(total),
        str(dest),
    )
    if not ok:
        print("    [TTS] Mix failed — falling back to music-only")
        return _add_music(src, dest, slot=slot, exclude_track=exclude_track)
    if track.parent in (MUSIC_ARCHIVE.resolve(), MUSIC_ARCHIVE):
        _log_music_used(track)
    return track


def _make_youtube_thumbnail(content: dict, dest: Path) -> bool:
    """
    Generate a custom YouTube thumbnail (1280×720) via PIL.
    Dark background, bold hook text in yellow, BootHop branding.
    High CTR format: left=face shock visual area, right=text.
    """
    try:
        from PIL import Image, ImageDraw
        TW, TH = 1280, 720
        img  = Image.new("RGB", (TW, TH), (8, 14, 28))
        draw = ImageDraw.Draw(img)

        # Orange accent strip top
        draw.rectangle([(0, 0), (TW, 8)], fill=(255, 107, 0))
        draw.rectangle([(0, TH - 8), (TW, TH)], fill=(255, 107, 0))

        # Right half: text block
        hook   = content.get("hook", "").rstrip("?").rstrip(".")
        lesson = content.get("lesson", "")

        ft_hook = _load_pil_font("title", 72)
        ft_sub  = _load_pil_font("body",  38)
        ft_cta  = _load_pil_font("title", 52)

        # Split hook into ≤20 chars/line for the thumbnail
        hook_lines = _split_lines(hook, 20, 3)
        y = 120
        for line in hook_lines:
            try:
                tw = draw.textbbox((0, 0), line, font=ft_hook)[2]
            except Exception:
                tw = len(line) * 40
            x = max(640, (TW - tw) // 2)  # right half
            draw.text((x + 3, y + 3), line, font=ft_hook, fill=(0, 0, 0))
            draw.text((x, y), line, font=ft_hook, fill=(255, 230, 0))
            y += 90

        # Divider
        draw.rectangle([(660, y + 10), (TW - 40, y + 14)], fill=(255, 107, 0))
        y += 40

        # Sub-text: lesson or brand line
        sub = lesson[:60] if lesson else "boothop.com"
        sub_lines = _split_lines(sub, 28, 2)
        for line in sub_lines:
            try:
                tw = draw.textbbox((0, 0), line, font=ft_sub)[2]
            except Exception:
                tw = len(line) * 22
            x = max(640, (TW - tw) // 2)
            draw.text((x, y), line, font=ft_sub, fill=(200, 200, 200))
            y += 52

        # BootHop brand bottom right
        brand = "BootHop"
        try:
            btw = draw.textbbox((0, 0), brand, font=ft_cta)[2]
        except Exception:
            btw = len(brand) * 28
        draw.text((TW - btw - 30 + 2, TH - 80 + 2), brand, font=ft_cta, fill=(0, 0, 0))
        draw.text((TW - btw - 30, TH - 80), brand, font=ft_cta, fill=(255, 230, 0))

        dest.parent.mkdir(exist_ok=True)
        img.save(str(dest), "JPEG", quality=95)
        return dest.exists()
    except Exception as e:
        print(f"    [Thumbnail] Failed: {e}")
        return False


_HOOK_DUR          = 2   # seconds — the clean cinematic hook opening
_HOOK_STORY_N      = 3   # story clips rendered when hook engine is active
# When hook is active: 2s hook + 3×4s story + 10s end = 24s total


def _find_music_track(slot: int | None, exclude_track: Path | None) -> Path | None:
    """Locate a music track (slot-specific daily -> any daily -> archive)."""
    if slot:
        slot_track = MUSIC_DIR / f"track_{slot}.mp3"
        if (slot_track.exists() and slot_track.stat().st_size > 50_000
                and (exclude_track is None or slot_track.resolve() != exclude_track.resolve())
                and _track_has_audio(slot_track)):
            return slot_track
    daily = [t for t in (list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.m4a")))
             if t.stat().st_size > 50_000 and "_tmp" not in str(t)
             and (exclude_track is None or t.resolve() != exclude_track.resolve())
             and _track_has_audio(t)]
    if daily:
        return random.choice(daily)
    archive = [t for t in (list(MUSIC_ARCHIVE.glob("*.mp3")) + list(MUSIC_ARCHIVE.glob("*.m4a")))
               if (exclude_track is None or t.resolve() != exclude_track.resolve())
               and _track_has_audio(t)]
    if archive:
        recent_stems = _recently_used_music_stems(days=2)
        fresh = [t for t in archive if t.stem.lower() not in recent_stems]
        return random.choice(fresh) if fresh else random.choice(archive)
    return None


def _add_hook_audio_and_music(
    src: Path, dest: Path,
    hook_audio: Path | None,
    total_dur: float,
    slot: int | None = None,
    exclude_track: Path | None = None,
) -> Path | None:
    """
    Add music to a hook-engine video.

    When hook_audio is provided: music is ducked to 20% for the first 2 seconds
    while the dialogue plays, then rises to 85% for the rest of the video.
    """
    import shutil
    track = _find_music_track(slot, exclude_track)
    if track is None:
        shutil.copy(src, dest)
        return None

    print(f"    [Music/Hook] Using: {track.name}")

    if hook_audio and hook_audio.exists():
        ok = _ff(
            "-i", str(src),
            "-stream_loop", "-1", "-i", str(track),
            "-i", str(hook_audio),
            "-filter_complex",
            (
                f"[1:a]afade=t=out:st={total_dur - 3}:d=3,"
                f"volume='if(lt(t,2),0.18,0.85)':eval=frame[mus];"
                f"[2:a]volume=1.6[dial];"
                f"[mus][dial]amix=inputs=2:duration=first:normalize=0[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_dur),
            str(dest),
        )
        if ok and dest.exists() and dest.stat().st_size > 200_000:
            if track.parent in (MUSIC_ARCHIVE.resolve(), MUSIC_ARCHIVE):
                _log_music_used(track)
            return track
        print("    [Music/Hook] Dialogue mix failed — falling back to music-only")
        dest.unlink(missing_ok=True)

    # Music only (no hook audio or mix failed)
    _ff(
        "-i", str(src),
        "-stream_loop", "-1", "-i", str(track),
        "-filter_complex",
        f"[1:a]afade=t=out:st={total_dur - 3}:d=3,volume=0.85[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(total_dur),
        str(dest),
    )
    if track.parent in (MUSIC_ARCHIVE.resolve(), MUSIC_ARCHIVE):
        _log_music_used(track)
    return track


def _concat_clips(clip_paths: list, dest: Path) -> bool:
    """Concatenate processed clips using FFmpeg concat demuxer."""
    list_path = dest.parent / f"concat_{dest.stem}.txt"
    list_path.write_text(
        "\n".join(f"file '{p}'" for p in clip_paths),
        encoding="utf-8",
    )
    ok = _ff(
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(dest),
    )
    list_path.unlink(missing_ok=True)
    return ok


def render_video(content: dict, slot: int, output_path: str,
                 version: str = "v1", exclude_ids: set | None = None,
                 hook_clip: str | None = None,
                 hook_audio: str | None = None) -> tuple[bool, set]:
    """
    Full render pipeline.
    version:     "v1" (gold palette, primary queries) or "v2" (cyan palette, alt queries, diff music)
    exclude_ids: clip IDs to skip (pass V1's used_ids so V2 gets fresh footage)
    Returns (success, used_clip_ids).
    """
    # Kill any orphaned ffmpeg from a prior crashed run before touching temp files
    try:
        subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"],
                       capture_output=True, timeout=5)
    except Exception:
        pass

    # Reset per-render user clip state so each video starts fresh
    setattr(render_video, "_used_user_clips_this_run", set())
    setattr(render_video, "_user_clip_count_this_run", 0)
    setattr(render_video, "_used_user_beat_types_this_run", set())

    pillar      = content.get("pillar", "community")
    top_caption = content.get("top_caption", "")
    _client     = content.get("client", "boothop")
    _is_car     = (_client == "g-inspired")
    _is_boothop = (_client == "boothop" or not _client)
    _car_data   = content.get("car", {})

    # ── Hook engine setup ────────────────────────────────────────────────────
    # When a hook_clip is supplied the video starts with a 2-second clean visual,
    # then only 3 story clips are rendered — total target: ~24 seconds.
    _has_hook       = bool(hook_clip and Path(hook_clip).exists())
    _hook_clip_path = Path(hook_clip) if _has_hook else None
    _hook_audio_pth = Path(hook_audio) if (hook_audio and Path(hook_audio).exists()) else None
    _n_clips_eff    = _HOOK_STORY_N if _has_hook else N_CLIPS   # 3 or 8
    _total_dur_eff  = float(_HOOK_DUR + _HOOK_STORY_N * CLIP_DUR + LESSON_DUR + BRAND_DUR) if _has_hook else float(TOTAL_DUR)
    if _has_hook:
        print(f"  [Render] Hook engine active — {_HOOK_DUR}s cinematic opening, {_n_clips_eff} story clips, target {_total_dur_eff:.0f}s")

    # user_clips_disabled: skip assets/user_clips folder entirely for this client.
    # Set "user_clips_disabled": true in client_profile.json to stop repeating
    # supplied photos/videos. Set to false to re-enable whenever ready.
    _user_clips_disabled = False
    if _is_boothop:
        _cp_check_path = Path(__file__).parent.parent / "client_profile.json"
        try:
            _cp_check = json.loads(_cp_check_path.read_text(encoding="utf-8"))
            _user_clips_disabled = bool(_cp_check.get("user_clips_disabled", False))
            if _user_clips_disabled:
                print(f"  [UserClips] Disabled until further notice — using AI/stock only")
        except Exception:
            pass
    # V2 uses alternate hook/lesson/queries if Claude generated them; falls back to V1 fields
    is_v2   = (version == "v2")
    hook    = content.get("hook_v2" if is_v2 else "hook", content.get("hook", ""))
    problem = content.get("problem", "")
    stakes  = content.get("stakes", "")
    resolution = content.get("resolution", "")
    lesson  = content.get("lesson_v2" if is_v2 else "lesson", content.get("lesson", ""))
    queries_key = "visual_queries_v2" if is_v2 else "visual_queries"
    queries = content.get(queries_key) or content.get("visual_queries", ["airport travel"] * N_CLIPS)
    if len(queries) < N_CLIPS:
        queries += ["diaspora delivery uk"] * (N_CLIPS - len(queries))

    # V2 uses the same visual queries as V1 - exclude_ids ensures V2 gets different
    # footage. The old half-rotation shifted resolution/stakes queries into hook/problem
    # positions (beat mismatch), causing more Pexels failures and blank placeholder clips.

    beat_style = BEAT_STYLE_V2 if is_v2 else None   # None = use default BEAT_STYLE

    beat_texts = [
        hook, hook,
        problem, problem,
        stakes,
        resolution, resolution,
        lesson,
    ]

    TEMP.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    prefix = f"otb_slot{slot}_{version}"
    # Seed used_ids with 14-day history so we never repeat clips across days
    used_ids: set = _recently_used_video_ids() | set(exclude_ids or [])
    own_ids: set  = set()   # IDs found by THIS render (returned to caller)
    proc_clips: list = []

    print(f"\n  [Render-{version.upper()}] Hook: {hook[:60]}")
    print(f"  [Render] Pillar: {pillar} | Slot: {slot} | Version: {version}")

    # When hook engine is active: skip clip 0 (text card), render clips 1-3 only.
    # Clip 0 is replaced by the 2-second cinematic hook_clip prepended at concat time.
    _clip_start = 1 if _has_hook else 0
    _clip_end   = _clip_start + _n_clips_eff

    for i in range(_clip_start, _clip_end):
        query  = _guard_query(queries[i], i)
        # Clips 0-1: close-up face grabs attention (face at top, hook text at bottom)
        # Clip 4: stakes beat — tight stressed shot at peak tension
        if i == 0:
            query = "Black woman close up face shocked expression phone screen"
        elif i == 1:
            query = "Nigerian woman shocked face expensive price reaction close up"
        elif i == 4:
            query = "Black woman stressed worried phone bills money close up"
        beat   = CLIP_BEAT[i]
        text   = beat_texts[i]
        raw    = TEMP / f"{prefix}_raw_{i}.mp4"
        proc   = TEMP / f"{prefix}_proc_{i}.mp4"

        print(f"    Clip {i} [{beat}]: {query}")

        got_video = False
        used_user_clips: set      = getattr(render_video, "_used_user_clips_this_run", set())
        user_clip_count: int      = getattr(render_video, "_user_clip_count_this_run", 0)
        used_user_beat_types: set = getattr(render_video, "_used_user_beat_types_this_run", set())

        # ── Clip 0: Text-card hook (proven TikTok format) ─────────────────────
        # Dark branded background + hook text centered — native feel, no stock footage.
        # Text baked in by _text_card_clip (PIL), so _process_clip is NOT called.
        if i == 0:
            if _text_card_clip(text, proc):
                got_video = True
                if top_caption and proc.exists():
                    _apply_caption_overlay(proc, top_caption)
                print(f"    Clip 0: text-card hook [{len(text.split())} words]")

        # ── Priority 0: User-provided clips ──────────────────────────────────────
        # Skipped when user_clips_disabled=true in client_profile.json (e.g. to avoid
        # repeating the same supplied photos). Falls through to AI/stock sources.
        user_clip = None
        if not _user_clips_disabled and user_clip_count < _USER_CLIP_CAP and beat not in used_user_beat_types:
            user_clip = _pick_user_clip(beat, used_user_clips)
        if user_clip:
            if user_clip.suffix.lower() in (".jpg", ".jpeg", ".png"):
                # Image → Ken Burns animated clip
                photo_temp = TEMP / f"{prefix}_user_photo_{i}.mp4"
                _frames = CLIP_DUR * VIDEO_FPS
                _ff("-loop", "1", "-i", str(user_clip),
                    "-vf",
                    f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                    f"zoompan=z='min(zoom+0.002,1.15)':d={_frames}"
                    f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},setsar=1",
                    "-t", str(CLIP_DUR), "-c:v", "libx264", "-crf", "22", "-preset", "fast",
                    "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(photo_temp))
                if photo_temp.exists():
                    if _process_clip(photo_temp, proc, beat, text, beat_style, top_caption=top_caption):
                        got_video = True
                        used_user_clips.add(str(user_clip))
                        used_user_beat_types.add(beat)
                        user_clip_count += 1
                        print(f"    Clip {i}: using user photo {user_clip.name}")
                    photo_temp.unlink(missing_ok=True)
            else:
                # Video → process directly
                if _process_clip(user_clip, proc, beat, text, beat_style, top_caption=top_caption):
                    got_video = True
                    used_user_clips.add(str(user_clip))
                    used_user_beat_types.add(beat)
                    user_clip_count += 1
                    print(f"    Clip {i}: using user clip {user_clip.name}")

        setattr(render_video, "_used_user_clips_this_run", used_user_clips)
        setattr(render_video, "_user_clip_count_this_run", user_clip_count)
        setattr(render_video, "_used_user_beat_types_this_run", used_user_beat_types)

        # ── G-Inspired: DALL-E first for slot 1 (morning/premium render only) ──
        if not got_video and _is_car and _car_data and slot == 1:
            print(f"    Clip {i}: [car-{beat}] generating {_car_data.get('make','')}/{_car_data.get('model','')} via AI image")
            dalle_first_raw = TEMP / f"{prefix}_dalle_{beat}_{i}.mp4"
            _dp = _car_dalle_prompt(_car_data, beat)
            if _dalle_image_as_clip(beat, query, dalle_first_raw, dalle_prompt=_dp):
                if _process_clip(dalle_first_raw, proc, beat, text, beat_style, top_caption=top_caption):
                    got_video = True
                    try: report_hit(query, f"dalle_car_{beat}")
                    except Exception: pass
            dalle_first_raw.unlink(missing_ok=True)

        # ── BootHop: DALL-E first for slot 1 (morning/premium render only) ──
        if not got_video and _is_boothop and slot == 1:
            print(f"    Clip {i}: [bh-{beat}] generating BootHop scene via AI image")
            bh_dalle_raw = TEMP / f"{prefix}_bh_{beat}_{i}.mp4"
            _dp = _bh_dalle_prompt(beat, content)
            if _dalle_image_as_clip(beat, query, bh_dalle_raw, dalle_prompt=_dp):
                if _process_clip(bh_dalle_raw, proc, beat, text, beat_style, top_caption=top_caption):
                    got_video = True
                    try: report_hit(query, f"dalle_bh_{beat}")
                    except Exception: pass
            bh_dalle_raw.unlink(missing_ok=True)

        clip_info = None
        if not got_video:
            clip_info = _pexels_video(query, used_ids) or _pixabay_video(query, used_ids)

        if clip_info:
            used_ids.add(clip_info["id"])
            own_ids.add(clip_info["id"])
            if _download_clip(clip_info["url"], raw):
                if _process_clip(raw, proc, beat, text, beat_style, top_caption=top_caption):
                    got_video = True
                    try: report_hit(query, "video")
                    except Exception: pass
                raw.unlink(missing_ok=True)

        if not got_video:
            print(f"    Clip {i}: falling back to Pexels photo")
            photo_raw = TEMP / f"{prefix}_photo_{i}.mp4"
            if _pexels_photo_as_clip(query, photo_raw):
                if _process_clip(photo_raw, proc, beat, text, beat_style, top_caption=top_caption):
                    got_video = True
                    try: report_hit(query, "photo")
                    except Exception: pass
                photo_raw.unlink(missing_ok=True)

        if not got_video:
            # Ask Perplexity for better search terms and try Pexels/Pixabay again
            print(f"    Clip {i}: asking Perplexity for alternative queries")
            for alt_q in _perplexity_suggest_queries(query, beat):
                alt_q = _guard_query(alt_q, i)
                clip_info = _pexels_video(alt_q, used_ids) or _pixabay_video(alt_q, used_ids)
                if clip_info:
                    used_ids.add(clip_info["id"])
                    own_ids.add(clip_info["id"])
                    if _download_clip(clip_info["url"], raw):
                        if _process_clip(raw, proc, beat, text, beat_style, top_caption=top_caption):
                            got_video = True
                            try: report_hit(alt_q, "perplexity_alt")
                            except Exception: pass
                        raw.unlink(missing_ok=True)
                if got_video:
                    break
                # Try as photo fallback too
                if not got_video:
                    photo_alt = TEMP / f"{prefix}_photo_alt_{i}.mp4"
                    if _pexels_photo_as_clip(alt_q, photo_alt):
                        if _process_clip(photo_alt, proc, beat, text, beat_style, top_caption=top_caption):
                            got_video = True
                            try: report_hit(alt_q, "perplexity_alt_photo")
                            except Exception: pass
                        photo_alt.unlink(missing_ok=True)
                if got_video:
                    break

        # G-Inspired already tried DALL-E at the top of this clip loop (before Pexels).
        # Nothing to do here for car client — fall through to Veo if still needed.

        if not got_video:
            # Google Veo — use the Cinematographer's pre-written video prompt
            veo_prompts = content.get("video_prompts", [])
            veo_prompt = ""
            if veo_prompts and i < len(veo_prompts):
                veo_prompt = veo_prompts[i].get("full_prompt", "") if isinstance(veo_prompts[i], dict) else ""
            if not veo_prompt:
                beat_mood = {
                    "hook":       "dramatic tense scene medium shot",
                    "problem":    "frustrated worried scene medium shot",
                    "stakes":     "emotional charged moment medium shot",
                    "resolution": "warm hopeful relief scene medium shot",
                    "lesson_pre": "confident aspirational wide shot",
                }.get(beat, "cinematic medium shot")
                veo_prompt = f"{query}. {beat_mood}. 4 seconds. Vertical 9:16 portrait."
            veo_raw = TEMP / f"{prefix}_veo_{i}.mp4"
            print(f"    Clip {i}: trying Google Veo")
            if _veo_video_as_clip(beat, veo_prompt, veo_raw):
                if _process_clip(veo_raw, proc, beat, text, beat_style, top_caption=top_caption):
                    got_video = True
                    try: report_hit(query, "veo")
                    except Exception: pass
                veo_raw.unlink(missing_ok=True)

        if not got_video and not _is_car:
            print(f"    Clip {i}: falling back to DALL-E generation")
            dalle_raw = TEMP / f"{prefix}_dalle_{i}.mp4"
            if _dalle_image_as_clip(beat, query, dalle_raw, cheap=(slot != 1)):
                if _process_clip(dalle_raw, proc, beat, text, beat_style, top_caption=top_caption):
                    got_video = True
                    try: report_hit(query, "dalle")
                    except Exception: pass
                dalle_raw.unlink(missing_ok=True)

        if not got_video:
            # Final safety net — client-appropriate fallback queries
            if _is_car:
                fb_bank = _CAR_FALLBACKS
            elif slot == 2:
                fb_bank = _AIRPORT_FALLBACKS
            else:
                fb_bank = _TRANSPORT_FALLBACKS
            transport_q = fb_bank[i % len(fb_bank)]
            print(f"    Clip {i}: safety fallback -> {transport_q}")
            clip_info = (_pexels_video(transport_q, used_ids) or _pixabay_video(transport_q, used_ids)
                         or _pexels_video(transport_q, own_ids) or _pixabay_video(transport_q, own_ids))
            if clip_info:
                used_ids.add(clip_info["id"])
                own_ids.add(clip_info["id"])
                if _download_clip(clip_info["url"], raw):
                    if _process_clip(raw, proc, beat, text, beat_style, top_caption=top_caption):
                        got_video = True
                        try: report_hit(transport_q, "transport_fallback")
                        except Exception: pass
                    raw.unlink(missing_ok=True)
            if not got_video:
                photo_raw = TEMP / f"{prefix}_photo_fb_{i}.mp4"
                if _pexels_photo_as_clip(transport_q, photo_raw):
                    if _process_clip(photo_raw, proc, beat, text, beat_style, top_caption=top_caption):
                        got_video = True
                        try: report_hit(transport_q, "transport_photo_fallback")
                        except Exception: pass
                    photo_raw.unlink(missing_ok=True)
            # Try DALL-E with the fallback query as a final visual rescue
            if not got_video:
                dalle_fb = TEMP / f"{prefix}_dalle_fb_{i}.mp4"
                if _dalle_image_as_clip(beat, transport_q, dalle_fb, cheap=(slot != 1)):
                    if _process_clip(dalle_fb, proc, beat, text, beat_style, top_caption=top_caption):
                        got_video = True
                    dalle_fb.unlink(missing_ok=True)

        if not got_video:
            # Last resort: branded BootHop card (website screenshot or brand card)
            # Much better than a plain dark screen — keeps the brand visible.
            try: report_hit(query, "branded_fallback")
            except Exception: pass
            placeholder_src = TEMP / f"{prefix}_ph_src_{i}.mp4"
            if not _website_fallback_as_clip(beat, query, placeholder_src):
                # Absolute fallback if even the brand card generation fails
                _ff("-f", "lavfi", "-i",
                    f"color=size={W}x{H}:color=0x0F172A:rate={VIDEO_FPS}",
                    "-t", str(CLIP_DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(placeholder_src))
            if placeholder_src.exists():
                _process_clip(placeholder_src, proc, beat, text, beat_style, top_caption=top_caption)
                placeholder_src.unlink(missing_ok=True)
            if not proc.exists():
                _ff("-f", "lavfi", "-i",
                    f"color=size={W}x{H}:color=0x130B4D:rate={VIDEO_FPS}",
                    "-t", str(CLIP_DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(proc))

        if proc.exists() and proc.stat().st_size > 5000:
            proc_clips.append(str(proc))
        else:
            print(f"    WARNING: clip {i} missing after all fallbacks — skipping from concat")

    # ── Detect client + load client profile for end card ─────────────────────
    _client     = content.get("client", "boothop")
    _is_boothop = (_client == "boothop" or not _client)

    # Load client profile (local client folder first, then OTB shared copy)
    import os as _os
    _client_base = _os.environ.get("OTB_CLIENT_BASE")
    _cp_local    = Path(_client_base) / "client_profile.json" if _client_base else None
    _cp_shared   = Path(__file__).parent.parent / ("client_profile.json" if _is_boothop
                   else f"client_profiles/{_client}.json")
    _cp_path     = (_cp_local if _cp_local and _cp_local.exists() else _cp_shared)
    try:
        _cp = json.loads(_cp_path.read_text(encoding="utf-8"))
    except Exception:
        _cp = {}

    # ── Merged end card (lesson takeaway + CTA, 10 seconds, dynamic colour) ──
    end_card = TEMP / f"{prefix}_end.mp4"
    print("    Making end card...")
    _make_merged_end_card(lesson, _client, _cp, end_card)
    if end_card.exists() and end_card.stat().st_size > 5000:
        proc_clips.append(str(end_card))
    else:
        print("    WARNING: end card failed — omitting from concat")

    # Prepend hook clip (2s clean visual, no text) when hook engine supplied one
    if _has_hook and _hook_clip_path and _hook_clip_path.exists():
        proc_clips.insert(0, str(_hook_clip_path))
        print(f"    Hook clip prepended: {_hook_clip_path.name}")

    # Safety: remove any paths that don't exist before concat
    proc_clips = [p for p in proc_clips if Path(p).exists() and Path(p).stat().st_size > 5000]

    # Concatenate all
    joined    = TEMP / f"{prefix}_joined.mp4"
    with_bar  = TEMP / f"{prefix}_bar.mp4"
    with_logo = TEMP / f"{prefix}_logo.mp4"

    print("    Concatenating clips...")
    if not _concat_clips(proc_clips, joined):
        print("  [Render] Concat failed")
        return False, set()

    print("    Adding progress bar...")
    _add_progress_bar(joined, with_bar)
    joined.unlink(missing_ok=True)

    # Logo: BootHop only — non-BootHop clients get their own branding in the CTA card
    if _is_boothop:
        print("    Adding logo...")
        _add_logo(with_bar, LOGO_PATH, with_logo)
        with_bar.unlink(missing_ok=True)
    else:
        import shutil
        shutil.move(str(with_bar), str(with_logo))

    exclude_music = content.get("_v1_music_track")
    print("    Adding music...")

    if _has_hook:
        # Hook engine: use dedicated mixer that ducks music during 2-second dialogue.
        # Skip regular TTS narration (hook dialogue already baked in as hook_audio).
        with_audio = TEMP / f"{prefix}_audio.mp4"
        used_track = _add_hook_audio_and_music(
            with_logo, with_audio,
            hook_audio  = _hook_audio_pth,
            total_dur   = _total_dur_eff,
            slot        = slot,
            exclude_track = Path(exclude_music) if exclude_music else None,
        )
        with_logo.unlink(missing_ok=True)
        import shutil
        shutil.move(str(with_audio), output_path)
    else:
        tts_path = TEMP / f"{prefix}_tts.mp3"
        if slot == 1:
            print("    Generating voiceover (slot 1 only)...")
            tts_ok = _tts_narration(content, tts_path)
        else:
            print("    Skipping voiceover (slot 2/3)...")
            tts_ok = False
        if tts_ok and tts_path.exists():
            print("    [TTS] Mixing narration + music")
            with_audio = TEMP / f"{prefix}_audio.mp4"
            used_track = _add_music_with_voiceover(
                with_logo, with_audio, tts_path,
                slot=slot,
                exclude_track=Path(exclude_music) if exclude_music else None,
            )
            tts_path.unlink(missing_ok=True)
            with_logo.unlink(missing_ok=True)
            import shutil
            shutil.move(str(with_audio), output_path)
        else:
            if tts_path.exists():
                tts_path.unlink(missing_ok=True)
            used_track = _add_music(with_logo, Path(output_path), slot=slot,
                                    exclude_track=Path(exclude_music) if exclude_music else None)
            with_logo.unlink(missing_ok=True)

    # Store which track was used so pipeline can pass it as exclude for V2
    if used_track:
        content[f"_{version}_music_track"] = str(used_track)

    for p in proc_clips:
        Path(p).unlink(missing_ok=True)

    ok = Path(output_path).exists() and Path(output_path).stat().st_size > 500_000
    if ok:
        size_mb = Path(output_path).stat().st_size // 1_048_576
        print(f"  [Render-{version.upper()}] Done {size_mb}MB -> {output_path}")
        if own_ids:
            _save_video_log(own_ids)
            print(f"  [Render-{version.upper()}] Logged {len(own_ids)} clip IDs (14-day cooldown)")
        used_user_clips: set = getattr(render_video, "_used_user_clips_this_run", set())
        if used_user_clips:
            _log_user_clips_used(used_user_clips)
            print(f"  [Render-{version.upper()}] Logged {len(used_user_clips)} user clip(s) ({_USER_CLIP_COOLDOWN_DAYS}-day cooldown)")
    else:
        print(f"  [Render-{version.upper()}] Output missing or too small")
    return ok, own_ids


# "" Platform-specific video variants """""""""""""""""""""""""""""""""""""""""
#
# Why each platform gets its own file:
#
# TIKTOK  " base render (crisp, high-contrast, text centred for TikTok UI)
# YOUTUBE " identical to TikTok (YouTube Shorts doesn't penalise cross-posts)
# INSTAGRAM " warm colour grade applied:
#   * Breaks visual fingerprinting: Instagram's crawler detects bit-for-bit identical
#     content that was already posted on TikTok and suppresses Reel reach by up to 30%.
#     A different colour matrix = different file hash = treated as original content.
#   * Suits IG aesthetic: Instagram feed skews warmer and more polished vs TikTok's
#     raw/contrasty look. Warm grade performs better in IG Explore.
# LINKEDIN " professional colour grade + 5-second B2B intro card prepended:
#   * LinkedIn audience is desktop-heavy, professional, B2B mindset.
#     The TikTok hook energy reads as entertainment content on LinkedIn feeds.
#     A 5-second "LOGISTICS INTELLIGENCE" branded card frames it as business insight first.
#   * Cooler, more desaturated grade signals professionalism vs TikTok's vibrant palette.
#   * LinkedIn's algorithm rewards watch-time; the intro card adds 5s, bumping average watch %.


def _grade_instagram(src: Path, dest: Path) -> bool:
    """Warm colour grade: breaks TikTok fingerprint + matches IG feed aesthetic."""
    return _ff(
        "-i", str(src),
        "-vf", "eq=brightness=0.03:saturation=1.12:contrast=1.02",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-c:a", "copy", str(dest),
    )


def _grade_linkedin(src: Path, dest: Path) -> bool:
    """Cooler, desaturated grade " professional LinkedIn look."""
    return _ff(
        "-i", str(src),
        "-vf", "eq=brightness=0.01:saturation=0.80:contrast=1.03",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy", str(dest),
    )


def _make_linkedin_intro(content: dict, dest: Path) -> bool:
    """
    5-second professional B2B intro card for LinkedIn.
    Two-pass: plain navy ' overlay text via -vf (same pattern as lesson card).
    """
    hook_esc = _esc(content.get("hook", ""))[:70]
    font_t   = _font("title")
    font_b   = _font("body")

    # Split hook into up to 2 lines " separate drawtext per line
    hook_lines = _split_lines(hook_esc, 24, 2)
    n_lines    = len(hook_lines)
    line_gap   = 72   # 56px font - 1.3
    y_mid      = f"(h - {n_lines * line_gap}) / 2 - 20"

    plain = dest.parent / (dest.stem + "_plain.mp4")
    ok = _ff(
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x0F172A:rate={VIDEO_FPS}",
        "-t", "5",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(plain),
    )
    if not ok or not plain.exists():
        return False

    hook_parts = []
    for i, ln in enumerate(hook_lines):
        y_expr = f"({y_mid}) + {i * line_gap}"
        hook_parts.append(
            f"drawtext=fontfile='{font_t}':text='{ln}':"
            f"fontsize=56:fontcolor=0xFFE600:x=(w-text_w)/2:y={y_expr}:"
            f"shadowcolor=0x000000@0.6:shadowx=2:shadowy=2"
        )
    vf = ",".join([
        f"drawtext=fontfile='{font_t}':text='LOGISTICS INTELLIGENCE':"
        f"fontsize=26:fontcolor=0x4F46E5:x=(w-text_w)/2:y=h*0.27",
    ] + hook_parts + [
        f"drawtext=fontfile='{font_b}':text='BootHop - boothop.com':"
        f"fontsize=34:fontcolor=0xFFFFFF@0.75:x=(w-text_w)/2:y=h*0.73",
    ])
    result = _ff(
        "-i", str(plain),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(dest),
    )
    if not result:
        import shutil
        shutil.copy2(plain, dest)
        result = dest.exists()
    plain.unlink(missing_ok=True)
    return result


def render_for_platforms(content: dict, slot: int, base_path: str, tiktok_ig_only: bool = False) -> dict:
    """
    Derive platform-specific video variants from the base render.
    Returns {platform: absolute_file_path}.

    TikTok  " base (no change)
    YouTube " base (shared with TikTok)
    Instagram " warm grade (fingerprint break + IG aesthetic)
    LinkedIn  " professional grade + 5s B2B intro card
    IG Story / Newspaper " use the Instagram-graded file
    """
    base   = Path(base_path)
    stem   = base.stem
    outdir = base.parent

    paths = {
        "tiktok":           str(base),
        "youtube":          str(base),
        "instagram":        str(base),   # will be overwritten if grade succeeds
        "instagram_story":  str(base),
        "newspaper":        str(base),
        "linkedin":         str(base),   # will be overwritten if grade succeeds
    }

    # YouTube thumbnail — custom image boosts CTR on Shorts browse
    thumb_path = outdir / f"{stem}_thumb.jpg"
    print("  [Render] Generating YouTube thumbnail...")
    if _make_youtube_thumbnail(content, thumb_path):
        paths["youtube_thumbnail"] = str(thumb_path)
        print(f"  [Render] Thumbnail OK ({thumb_path.stat().st_size // 1024}KB)")

    # "" Instagram warm grade """"""""""""""""""""""""""""""""""""""""""""""""""
    ig_path = outdir / f"{stem}_ig.mp4"
    print("  [Render] Applying Instagram grade...")
    if _grade_instagram(base, ig_path) and ig_path.exists() and ig_path.stat().st_size > 200_000:
        paths["instagram"]       = str(ig_path)
        paths["instagram_story"] = str(ig_path)
        paths["newspaper"]       = str(ig_path)
        print(f"  [Render] Instagram grade OK ({ig_path.stat().st_size // 1024}KB)")
    else:
        print("  [Render] Instagram grade failed - using base")
        ig_path.unlink(missing_ok=True)

    # "" LinkedIn professional grade + intro card (V1 only) """""""""""""""""""
    if not tiktok_ig_only:
        li_intro  = outdir / f"{stem}_li_intro.mp4"
        li_graded = outdir / f"{stem}_li_graded.mp4"
        li_path   = outdir / f"{stem}_li.mp4"

        print("  [Render] Creating LinkedIn variant...")
        intro_ok = _make_linkedin_intro(content, li_intro)
        grade_ok = _grade_linkedin(base, li_graded)

        if intro_ok and grade_ok and li_intro.exists() and li_graded.exists():
            list_file = outdir / f"{stem}_li_concat.txt"
            list_file.write_text(
                f"file '{li_intro}'\nfile '{li_graded}'",
                encoding="utf-8",
            )
            ok = _ff(
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p", "-an", str(li_path),
            )
            list_file.unlink(missing_ok=True)
            li_intro.unlink(missing_ok=True)
            li_graded.unlink(missing_ok=True)

            li_music = outdir / f"{stem}_li_music.mp4"
            _add_music(li_path, li_music, slot=slot)
            li_path.unlink(missing_ok=True)
            if li_music.exists() and li_music.stat().st_size > 200_000:
                paths["linkedin"] = str(li_music)
                print(f"  [Render] LinkedIn variant OK ({li_music.stat().st_size // 1024}KB)")
            else:
                li_music.unlink(missing_ok=True)
                print("  [Render] LinkedIn music failed - using base")
        else:
            li_intro.unlink(missing_ok=True)
            li_graded.unlink(missing_ok=True)
            print("  [Render] LinkedIn variant failed - using base")

    return paths

