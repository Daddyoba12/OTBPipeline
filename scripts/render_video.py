"""
OTB_Pipeline â€” video renderer
5-beat structure: Hook(0-8s) â†’ Problem(8-16s) â†’ Stakes(16-20s) â†’ Resolution(20-28s) â†’ Lesson card(28-33s) â†’ Brand end(33-42s)
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

# ── 14-day video clip dedup ───────────────────────────────────────────────────
_VIDEO_LOG = DATA / "video_clip_log.json"
_VIDEO_COOLDOWN_DAYS = 14

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

# â”€â”€ Fetch-time query guard (3rd and final safety layer) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Mirrors BANNED_QUERY_TERMS in generate_content.py â€” catches anything that
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
    # Generic stock clichÃ©s
    "handshake","trophy","medal","piggy bank","cartoon","illustration",
}

# Transport-focused fallbacks organised by clip index (beat order)
# Medium/wide shots only — no close-ups, no extreme face shots
_TRANSPORT_FALLBACKS = [
    "woman london apartment worried medium shot",   # 0 hook
    "airport departures hall travellers wide shot", # 1 hook
    "person post office counter medium shot",       # 2 problem
    "traveller train station luggage medium shot",  # 3 problem
    "woman sitting phone call worried medium shot", # 4 stakes
    "parcel handover train station wide shot",      # 5 resolution
    "plane window seat flight medium shot",         # 6 resolution
    "london city street wide establishing shot",    # 7 lesson
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

# Beat text layout â€” one entry per beat type.
# Each line of text is rendered as a SEPARATE drawtext filter with an explicit pixel Y,
# matching BHP pipeline's approach (no \n / line_spacing squash).
#
# y_start   : pixel Y of the first line (1080Ã—1920 frame)
# line_gap  : pixels between lines  â‰ˆ font_size Ã— 1.35
# size      : primary font size (px)
# size_cont : continuation font for hook h2/h3 (smaller than punch)
# max_chars : max chars per line before wrapping
# max_lines : max lines rendered per clip
# title_font: True = Oswald-Bold (condensed), False = Montserrat (body)
# color     : hex string, no '#'
BEAT_STYLE = {
    "hook": {
        "size": 78, "size_cont": 60,
        "color": "FFE600",
        "y_start": 100,   # shifted up to give room for 4th line
        "line_gap": 96,
        "max_chars": 20,
        "max_lines": 4,
        "title_font": True,
    },
    "problem": {
        "size": 52, "color": "FFFFFF",
        "y_start": 780,   # shifted up 40px to fit 4th line
        "line_gap": 70,
        "max_chars": 26,
        "max_lines": 4,
        "title_font": False,
    },
    "stakes": {
        "size": 58, "color": "FF8C00",
        "y_start": 730,   # shifted up 50px to fit 4th line
        "line_gap": 78,
        "max_chars": 22,
        "max_lines": 4,
        "title_font": True,
    },
    "resolution": {
        "size": 52, "color": "FFFFFF",
        "y_start": 780,   # shifted up 40px to fit 4th line
        "line_gap": 70,
        "max_chars": 26,
        "max_lines": 4,
        "title_font": False,
    },
    "lesson_pre": {
        "size": 48, "color": "FFFFFF",
        "y_start": 780,   # shifted up 40px to fit 4th line
        "line_gap": 65,
        "max_chars": 28,
        "max_lines": 4,
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
    "hook", "hook",          # clips 0-1  â†’ Hook
    "problem", "problem",    # clips 2-3  â†’ Problem
    "stakes",                # clip  4    â†’ Stakes
    "resolution", "resolution",  # clips 5-6  â†’ Resolution
    "lesson_pre",            # clip  7    â†’ Lesson lead-in
]


def _ff(*args, timeout=600):
    cmd = ["ffmpeg", "-y"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
            .replace("â€”", "-").replace("â€“", "-")
            .replace("â€˜", "").replace("â€™", "").replace("'", "")
            .replace("â€œ", '"').replace("â€", '"')
            .replace("â€¦", "..."))
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


_BEAT_LABELS = {
    "hook":       "",           # hook text IS the label â€” no duplicate tag
    "problem":    "THE PROBLEM",
    "stakes":     "THE STAKES",
    "resolution": "THE RESOLUTION",
    "lesson_pre": "THE LESSON",
}


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
            f"box=1:boxcolor=0x000000@0.72:boxborderw=18:"
            f"shadowx=3:shadowy=3:shadowcolor=0x000000"
        )
    return ",".join(parts)

# â”€â”€ Video clip fetching â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _pexels_video(query: str, exclude_ids: set) -> dict | None:
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": 50, "orientation": "portrait", "size": "medium"},
            headers={"Authorization": PEXELS_KEY},
            timeout=15,
        )
        videos = r.json().get("videos", [])
        for v in random.sample(videos, min(len(videos), 8)):
            if v["id"] in exclude_ids:
                continue
            # Check Pexels page URL slug for animal/banned terms (e.g. ".../dog-at-airport-1234/")
            page_slug = v.get("url", "").lower()
            if any(term in page_slug for term in _BANNED_FETCH_TERMS):
                print(f"    [Pexels] Skipped banned metadata: {page_slug.split('/')[-2]}")
                continue
            files = sorted(v.get("video_files", []), key=lambda f: f.get("width", 0), reverse=True)
            # Only accept FHD portrait (width=1080) â€” 720p upscales 1.5x and looks blurry
            hd = next((f for f in files if f.get("width", 0) >= 1080 and "portrait" in f.get("quality", "").lower()), None)
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
        for v in random.sample(hits, min(len(hits), 8)):
            vid_id = f"pb_{v['id']}"
            if vid_id in exclude_ids:
                continue
            # Check Pixabay tags string for animal/banned terms (e.g. "airport, dog, travel")
            tags = v.get("tags", "").lower()
            if any(term in tags for term in _BANNED_FETCH_TERMS):
                print(f"    [Pixabay] Skipped banned tags: {tags[:80]}")
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


def _dalle_image_as_clip(beat: str, query: str, dest: Path, duration: int = CLIP_DUR) -> bool:
    """Generate a unique image with DALL-E 3 and Ken-Burns animate it into a clip."""
    if not OPENAI_API_KEY:
        return False
    # Craft a cinematic prompt from the beat type and query
    beat_mood = {
        "hook":       "dramatic cinematic medium-wide shot, golden hour lighting",
        "problem":    "tense medium shot, moody blue tones, documentary style",
        "stakes":     "emotional medium shot, shallow depth of field, orange accent light",
        "resolution": "warm joyful medium-wide scene, soft natural light, hopeful mood",
        "lesson_pre": "clean professional wide shot, bright neutral tones",
    }.get(beat, "cinematic medium wide shot")
    prompt = (
        f"Photorealistic {beat_mood}. Scene: {query}. "
        f"Vertical 9:16 portrait orientation. No text, no logos, no watermarks. "
        f"High quality professional photography."
    )
    try:
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": prompt[:4000], "n": 1,
                  "size": "1024x1792", "quality": "standard"},
        )
        data = resp.json()
        img_url = data["data"][0]["url"]
        img_bytes = requests.get(img_url, timeout=30).content
        img_path = dest.with_suffix(".jpg")
        img_path.write_bytes(img_bytes)
        frames = duration * VIDEO_FPS
        ok = _ff(
            "-loop", "1", "-i", str(img_path),
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"zoompan=z='min(zoom+0.002,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H},"
            "setsar=1",
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(dest),
        )
        img_path.unlink(missing_ok=True)
        if ok and dest.exists():
            print(f"    [DALL-E] Generated unique image for: {query[:50]}")
            return True
    except Exception as e:
        print(f"    [DALL-E] {query}: {e}")
    return False


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


def _process_clip(src: Path, dest: Path, beat: str, beat_text: str, style_override: dict | None = None) -> bool:
    """Resize, crop to 9:16, sharpen, add beat text overlay, trim to CLIP_DUR."""
    text_f = _drawtext_filters(beat_text, beat, style_override)
    vf_parts = [
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}",
        "setsar=1",
        # Counteract upscaling blur (BHP premium mode approach)
        "unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount=0.8",
    ]
    if text_f:
        vf_parts.append(text_f)
    vf = ",".join(vf_parts)
    return _ff(
        "-ss", "0", "-i", str(src),
        "-t", str(CLIP_DUR),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an",
        str(dest),
    )


def _make_lesson_card(lesson: str, hook: str, pillar_color: str, dest: Path) -> bool:
    """Create a 5-second lesson card: dark overlay + lesson text + CTA.
    Two-pass approach: generate plain colour video first, then overlay text via -vf.
    This avoids the lavfi+drawtext parsing issue with apostrophes on Windows.
    """
    color_map = {
        "community":          "4F46E5",
        "family":             "7C3AED",
        "airport":            "1D4ED8",
        "smart":              "0369A1",
        "travel_hacks":       "0891B2",
        "logistics_stories":  "047857",
        "airport_deliveries": "B45309",
        "supply_chain":       "DC2626",
    }
    bg = color_map.get(pillar_color, "4F46E5")
    font_t = _font("title")
    font_b = _font("body")

    # Split lesson into at most 2 lines (28 chars each) â€” separate drawtext per line
    lesson_lines = _split_lines(_esc(lesson), 28, 3)

    # Pass 1 â€” plain colour card
    plain = dest.parent / (dest.stem + "_plain.mp4")
    ok = _ff(
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x{bg}:rate={VIDEO_FPS}",
        "-t", str(LESSON_DUR),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(plain),
    )
    if not ok or not plain.exists():
        return False

    # Pass 2 â€” overlay text: label + lesson lines (each separate drawtext) + URL
    # Lesson block centred vertically â€” y_mid is the top of the text block
    n_lines  = len(lesson_lines)
    line_gap = 80   # 62px font * 1.3
    y_mid    = f"(h - {n_lines * line_gap}) / 2"
    lesson_parts = []
    for i, ln in enumerate(lesson_lines):
        y_expr = f"({y_mid}) + {i * line_gap}"
        lesson_parts.append(
            f"drawtext=fontfile='{font_t}':text='{ln}':fontsize=62:"
            f"fontcolor=0xFFE600:x=(w-text_w)/2:y={y_expr}:"
            f"shadowcolor=0x000000@0.8:shadowx=3:shadowy=3"
        )
    vf = ",".join([
        f"drawtext=fontfile='{font_t}':text='THE LESSON':fontsize=34:"
        f"fontcolor=0xFFFFFF@0.6:x=(w-text_w)/2:y=h*0.26",
    ] + lesson_parts + [
        f"drawtext=fontfile='{font_b}':text='boothop.com':fontsize=38:"
        f"fontcolor=0xFFFFFF@0.85:x=(w-text_w)/2:y=h*0.74",
    ])
    result = _ff(
        "-i", str(plain),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(dest),
    )
    plain.unlink(missing_ok=True)
    return result


def _add_progress_bar(src: Path, dest: Path) -> bool:
    """Burn a static accent bar at the bottom of the video."""
    import shutil
    # Use ih/iw (lowercase) â€” uppercase H/W are not defined in drawbox expressions
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
        f"[1:v]scale=180:-1[logo];[0:v][logo]overlay=W-180-20:20",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy", str(dest),
    )


def _add_music(src: Path, dest: Path, slot: int = None, exclude_track: Path | None = None) -> Path | None:
    """
    Mix in slot-specific trending music. Priority:
      1. music/daily/track_{slot}.mp3  â€” today's trending pick for this slot
      2. Any file in music/daily/       â€” another slot's trending pick
      3. music/archive/                 â€” royalty-free fallback library
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
                track = slot_track

    # 2. Any daily track (excluding the one already used)
    if track is None:
        daily = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.m4a"))
        daily = [t for t in daily
                 if t.stat().st_size > 50_000 and "_tmp" not in str(t)
                 and (exclude_track is None or t.resolve() != exclude_track.resolve())]
        if daily:
            track = random.choice(daily)

    # 3. Archive fallback
    if track is None:
        archive = list(MUSIC_ARCHIVE.glob("*.mp3")) + list(MUSIC_ARCHIVE.glob("*.m4a"))
        archive = [t for t in archive
                   if exclude_track is None or t.resolve() != exclude_track.resolve()]
        if archive:
            track = random.choice(archive)

    if track is None:
        shutil.copy(src, dest)
        return None

    total = float(TOTAL_DUR)
    print(f"    [Music] Using: {track.name}")
    # -stream_loop -1 loops the audio file at the demuxer level (reliable across all
    # FFmpeg versions). The old aloop filter approach stopped at the track's natural
    # length (~22s for short tracks) because the filter isn't guaranteed to loop.
    _ff(
        "-i", str(src),
        "-stream_loop", "-1", "-i", str(track),
        "-filter_complex",
        f"[1:a]atrim=0:{total},afade=t=out:st={total-3}:d=3,volume=0.85[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(total),
        str(dest),
    )
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
                 version: str = "v1", exclude_ids: set | None = None) -> tuple[bool, set]:
    """
    Full render pipeline.
    version:     "v1" (gold palette, primary queries) or "v2" (cyan palette, alt queries, diff music)
    exclude_ids: clip IDs to skip (pass V1's used_ids so V2 gets fresh footage)
    Returns (success, used_clip_ids).
    """
    pillar  = content.get("pillar", "community")
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

    # V2 uses the same visual queries as V1 — exclude_ids ensures V2 gets different
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

    for i in range(N_CLIPS):
        query  = _guard_query(queries[i], i)
        beat   = CLIP_BEAT[i]
        text   = beat_texts[i]
        raw    = TEMP / f"{prefix}_raw_{i}.mp4"
        proc   = TEMP / f"{prefix}_proc_{i}.mp4"

        print(f"    Clip {i} [{beat}]: {query}")

        clip_info = _pexels_video(query, used_ids) or _pixabay_video(query, used_ids)
        got_video = False

        if clip_info:
            used_ids.add(clip_info["id"])
            own_ids.add(clip_info["id"])
            if _download_clip(clip_info["url"], raw):
                if _process_clip(raw, proc, beat, text, beat_style):
                    got_video = True
                    try: report_hit(query, "video")
                    except Exception: pass
                raw.unlink(missing_ok=True)

        if not got_video:
            print(f"    Clip {i}: falling back to Pexels photo")
            photo_raw = TEMP / f"{prefix}_photo_{i}.mp4"
            if _pexels_photo_as_clip(query, photo_raw):
                if _process_clip(photo_raw, proc, beat, text, beat_style):
                    got_video = True
                    try: report_hit(query, "photo")
                    except Exception: pass
                photo_raw.unlink(missing_ok=True)

        if not got_video:
            print(f"    Clip {i}: falling back to DALL-E generation")
            dalle_raw = TEMP / f"{prefix}_dalle_{i}.mp4"
            if _dalle_image_as_clip(beat, query, dalle_raw):
                if _process_clip(dalle_raw, proc, beat, text, beat_style):
                    got_video = True
                    try: report_hit(query, "dalle")
                    except Exception: pass
                dalle_raw.unlink(missing_ok=True)

        if not got_video:
            # Final safety net before black placeholder — use guaranteed transport query
            transport_q = _TRANSPORT_FALLBACKS[i % len(_TRANSPORT_FALLBACKS)]
            print(f"    Clip {i}: transport safety fallback -> {transport_q}")
            clip_info = _pexels_video(transport_q, used_ids) or _pixabay_video(transport_q, used_ids)
            if clip_info:
                used_ids.add(clip_info["id"])
                if _download_clip(clip_info["url"], raw):
                    if _process_clip(raw, proc, beat, text, beat_style):
                        got_video = True
                        try: report_hit(transport_q, "transport_fallback")
                        except Exception: pass
                    raw.unlink(missing_ok=True)
            if not got_video:
                photo_raw = TEMP / f"{prefix}_photo_fb_{i}.mp4"
                if _pexels_photo_as_clip(transport_q, photo_raw):
                    if _process_clip(photo_raw, proc, beat, text, beat_style):
                        got_video = True
                        try: report_hit(transport_q, "transport_photo_fallback")
                        except Exception: pass
                    photo_raw.unlink(missing_ok=True)

        if not got_video:
            try: report_hit(query, "placeholder")
            except Exception: pass
            _ff("-f", "lavfi", "-i",
                f"color=size={W}x{H}:color=0x111111:rate={VIDEO_FPS}",
                "-t", str(CLIP_DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(proc))

        proc_clips.append(str(proc))

    # Lesson card
    lesson_card = TEMP / f"{prefix}_lesson.mp4"
    print("    Making lesson card...")
    _make_lesson_card(lesson, hook, pillar, lesson_card)
    proc_clips.append(str(lesson_card))

    # Brand end card (reuse FIG4End.png from main pipeline)
    brand_card = TEMP / f"{prefix}_brand.mp4"
    if FIG_END.exists():
        _ff(
            "-loop", "1", "-i", str(FIG_END),
            "-t", str(BRAND_DUR),
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p", "-an", str(brand_card),
        )
    else:
        # Two-pass brand card (plain colour â†’ overlay text via -vf, same as lesson card)
        _plain = TEMP / f"{prefix}_brand_plain.mp4"
        _ff("-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x0F172A:rate={VIDEO_FPS}",
            "-t", str(BRAND_DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(_plain))
        if _plain.exists():
            _ff("-i", str(_plain),
                "-vf", (f"drawtext=fontfile='{_font('title')}':text='BootHop':fontsize=90:"
                        f"fontcolor=0xFFE600:x=(w-text_w)/2:y=(h-th)/2-30,"
                        f"drawtext=fontfile='{_font('body')}':text='boothop.com':fontsize=42:"
                        f"fontcolor=0xFFFFFF:x=(w-text_w)/2:y=(h-th)/2+70"),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p", "-an", str(brand_card))
            _plain.unlink(missing_ok=True)

    proc_clips.append(str(brand_card))

    # Concatenate all
    joined    = TEMP / f"{prefix}_joined.mp4"
    with_bar  = TEMP / f"{prefix}_bar.mp4"
    with_logo = TEMP / f"{prefix}_logo.mp4"

    print("    Concatenating clips...")
    if not _concat_clips(proc_clips, joined):
        print("  [Render] Concat failed")
        return False

    print("    Adding progress bar...")
    _add_progress_bar(joined, with_bar)
    joined.unlink(missing_ok=True)

    print("    Adding logo...")
    _add_logo(with_bar, LOGO_PATH, with_logo)
    with_bar.unlink(missing_ok=True)

    print("    Adding music...")
    exclude_music = content.get("_v1_music_track")   # set by pipeline after V1 render
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
        print(f”  [Render-{version.upper()}] Done â€” {size_mb}MB -> {output_path}”)
        if own_ids:
            _save_video_log(own_ids)
            print(f”  [Render-{version.upper()}] Logged {len(own_ids)} clip IDs (14-day cooldown)”)
    else:
        print(f”  [Render-{version.upper()}] Output missing or too small”)
    return ok, own_ids


# â”€â”€ Platform-specific video variants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#
# Why each platform gets its own file:
#
# TIKTOK  â€” base render (crisp, high-contrast, text centred for TikTok UI)
# YOUTUBE â€” identical to TikTok (YouTube Shorts doesn't penalise cross-posts)
# INSTAGRAM â€” warm colour grade applied:
#   â€¢ Breaks visual fingerprinting: Instagram's crawler detects bit-for-bit identical
#     content that was already posted on TikTok and suppresses Reel reach by up to 30%.
#     A different colour matrix = different file hash = treated as original content.
#   â€¢ Suits IG aesthetic: Instagram feed skews warmer and more polished vs TikTok's
#     raw/contrasty look. Warm grade performs better in IG Explore.
# LINKEDIN â€” professional colour grade + 5-second B2B intro card prepended:
#   â€¢ LinkedIn audience is desktop-heavy, professional, B2B mindset.
#     The TikTok hook energy reads as entertainment content on LinkedIn feeds.
#     A 5-second "LOGISTICS INTELLIGENCE" branded card frames it as business insight first.
#   â€¢ Cooler, more desaturated grade signals professionalism vs TikTok's vibrant palette.
#   â€¢ LinkedIn's algorithm rewards watch-time; the intro card adds 5s, bumping average watch %.


def _grade_instagram(src: Path, dest: Path) -> bool:
    """Warm colour grade: breaks TikTok fingerprint + matches IG feed aesthetic."""
    return _ff(
        "-i", str(src),
        "-vf", "eq=brightness=0.03:saturation=1.12:contrast=1.02",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-c:a", "copy", str(dest),
    )


def _grade_linkedin(src: Path, dest: Path) -> bool:
    """Cooler, desaturated grade â€” professional LinkedIn look."""
    return _ff(
        "-i", str(src),
        "-vf", "eq=brightness=0.01:saturation=0.80:contrast=1.03",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy", str(dest),
    )


def _make_linkedin_intro(content: dict, dest: Path) -> bool:
    """
    5-second professional B2B intro card for LinkedIn.
    Two-pass: plain navy â†’ overlay text via -vf (same pattern as lesson card).
    """
    hook_esc = _esc(content.get("hook", ""))[:70]
    font_t   = _font("title")
    font_b   = _font("body")

    # Split hook into up to 2 lines â€” separate drawtext per line
    hook_lines = _split_lines(hook_esc, 24, 2)
    n_lines    = len(hook_lines)
    line_gap   = 72   # 56px font Ã— 1.3
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
    plain.unlink(missing_ok=True)
    return result


def render_for_platforms(content: dict, slot: int, base_path: str, tiktok_ig_only: bool = False) -> dict:
    """
    Derive platform-specific video variants from the base render.
    Returns {platform: absolute_file_path}.

    TikTok  â€” base (no change)
    YouTube â€” base (shared with TikTok)
    Instagram â€” warm grade (fingerprint break + IG aesthetic)
    LinkedIn  â€” professional grade + 5s B2B intro card
    IG Story / Newspaper â€” use the Instagram-graded file
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

    # â”€â”€ Instagram warm grade â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ig_path = outdir / f"{stem}_ig.mp4"
    print("  [Render] Applying Instagram grade...")
    if _grade_instagram(base, ig_path) and ig_path.exists() and ig_path.stat().st_size > 200_000:
        paths["instagram"]       = str(ig_path)
        paths["instagram_story"] = str(ig_path)
        paths["newspaper"]       = str(ig_path)
        print(f"  [Render] Instagram grade OK ({ig_path.stat().st_size // 1024}KB)")
    else:
        print("  [Render] Instagram grade failed â€” using base")
        ig_path.unlink(missing_ok=True)

    # â”€â”€ LinkedIn professional grade + intro card (V1 only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not tiktok_ig_only:
        li_intro  = outdir / f"{stem}_li_intro.mp4"
        li_graded = outdir / f"{stem}_li_graded.mp4"
        li_path   = outdir / f"{stem}_li.mp4"

        print("  [Render] Creating LinkedIn variant...")
        intro_ok = _make_linkedin_intro(content, li_intro)
        grade_ok = _grade_linkedin(base, li_graded)

        if intro_ok and grade_ok and li_intro.exists() and li_graded.exists():
            list_file = outdir / "li_concat.txt"
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
                print("  [Render] LinkedIn music failed â€” using base")
        else:
            li_intro.unlink(missing_ok=True)
            li_graded.unlink(missing_ok=True)
            print("  [Render] LinkedIn variant failed â€” using base")

    return paths

