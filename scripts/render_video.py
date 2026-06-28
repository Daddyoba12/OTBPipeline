"""
OTB_Pipeline — video renderer
5-beat structure: Hook(0-8s) → Problem(8-16s) → Stakes(16-20s) → Resolution(20-28s) → Lesson card(28-33s) → Brand end(33-42s)
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
    PEXELS_KEY, PIXABAY_KEY,
    VIDEO_W, VIDEO_H, VIDEO_FPS,
    CLIP_DUR, N_CLIPS, LESSON_DUR, BRAND_DUR, TOTAL_DUR,
    PROGRESS_COLOR, PROGRESS_H,
)

import requests
from query_learner import report_hit

W, H = VIDEO_W, VIDEO_H

# ── Fetch-time query guard (3rd and final safety layer) ───────────────────────
# Mirrors BANNED_QUERY_TERMS in generate_content.py — catches anything that
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
    # Generic stock clichés
    "handshake","trophy","medal","piggy bank","cartoon","illustration",
}

# Transport-focused fallbacks organised by clip index (beat order)
_TRANSPORT_FALLBACKS = [
    "airplane takeoff runway sunrise",        # 0 hook
    "london black cab night city",            # 1 hook
    "airport queue waiting customs",          # 2 problem
    "stressed traveller missed flight gate",  # 3 problem
    "woman phone call airport emotional",     # 4 stakes
    "parcel package handover smiling",        # 5 resolution
    "plane landing runway arrival",           # 6 resolution
    "professional business person london",    # 7 lesson
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

# Beat text layout — one entry per beat type.
# Each line of text is rendered as a SEPARATE drawtext filter with an explicit pixel Y,
# matching BHP pipeline's approach (no \n / line_spacing squash).
#
# y_start   : pixel Y of the first line (1080×1920 frame)
# line_gap  : pixels between lines  ≈ font_size × 1.35
# size      : primary font size (px)
# size_cont : continuation font for hook h2/h3 (smaller than punch)
# max_chars : max chars per line before wrapping
# max_lines : max lines rendered per clip
# title_font: True = Oswald-Bold (condensed), False = Montserrat (body)
# color     : hex string, no '#'
BEAT_STYLE = {
    "hook": {
        "size": 72, "size_cont": 56,
        "color": "FFE600",
        "y_start": 160,   # top zone — below TikTok/IG UI chrome
        "line_gap": 90,
        "max_chars": 20,
        "max_lines": 3,
        "title_font": True,
    },
    "problem": {
        "size": 52, "color": "FFFFFF",
        "y_start": 880,   # center-lower — natural reading zone
        "line_gap": 70,
        "max_chars": 26,
        "max_lines": 2,
        "title_font": False,
    },
    "stakes": {
        "size": 58, "color": "FF8C00",
        "y_start": 840,
        "line_gap": 78,
        "max_chars": 22,
        "max_lines": 2,
        "title_font": True,
    },
    "resolution": {
        "size": 52, "color": "FFFFFF",
        "y_start": 880,
        "line_gap": 70,
        "max_chars": 26,
        "max_lines": 2,
        "title_font": False,
    },
    "lesson_pre": {
        "size": 48, "color": "FFFFFF",
        "y_start": 900,
        "line_gap": 65,
        "max_chars": 28,
        "max_lines": 2,
        "title_font": False,
    },
}

CLIP_BEAT = [
    "hook", "hook",          # clips 0-1  → Hook
    "problem", "problem",    # clips 2-3  → Problem
    "stakes",                # clip  4    → Stakes
    "resolution", "resolution",  # clips 5-6  → Resolution
    "lesson_pre",            # clip  7    → Lesson lead-in
]


def _ff(*args, timeout=120):
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
    Rest wraps at 22 chars into up to 2 continuation lines.
    """
    import re as _re
    clean = _esc(text)
    m = _re.search(r"[.!?]", clean[:80])
    if m and len(clean[: m.start()].split()) <= 8:
        punch = clean[: m.start()].strip()
        rest  = clean[m.end() :].strip()
        return [punch] + _split_lines(rest, 22, 2)
    return _split_lines(clean, 24, 3)


def _drawtext_filters(text: str, beat: str) -> str:
    """Return comma-chained drawtext filters - one per line - with explicit pixel Y.

    Replaces single drawtext + line_spacing=10 which squashes lines together
    (10px gap is tiny against 52-72px fonts).  Each line is absolutely positioned
    so spacing is proportional to the font size (approx font_size * 1.35).
    """
    style = BEAT_STYLE.get(beat, BEAT_STYLE["problem"])
    lines = (_split_hook(text) if beat == "hook"
             else _split_lines(_esc(text), style["max_chars"], style["max_lines"]))
    if not lines:
        return ""

    font  = _font("title" if style.get("title_font") else "body")
    y0    = style["y_start"]
    gap   = style["line_gap"]
    color = style["color"]

    parts = []
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
            f"box=1:boxcolor=0x000000@0.55:boxborderw=14:"
            f"shadowx=2:shadowy=2:shadowcolor=0x000000@0.8"
        )
    return ",".join(parts)

# ── Video clip fetching ────────────────────────────────────────────────────────

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
            # Only accept FHD portrait (width=1080) — 720p upscales 1.5x and looks blurry
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
            timeout=90,
        )
        img_path.unlink(missing_ok=True)
        return ok and dest.exists()
    except Exception as e:
        print(f"    [PhotoFallback] {query}: {e}")
    return False


def _download_clip(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return dest.exists() and dest.stat().st_size > 10_000
    except Exception as e:
        print(f"    [Download] {e}")
    return False


def _process_clip(src: Path, dest: Path, beat: str, beat_text: str) -> bool:
    """Resize, crop to 9:16, sharpen, add beat text overlay, trim to CLIP_DUR."""
    text_f = _drawtext_filters(beat_text, beat)
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
        timeout=90,
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

    # Split lesson into at most 2 lines (28 chars each) — separate drawtext per line
    lesson_lines = _split_lines(_esc(lesson), 28, 2)

    # Pass 1 — plain colour card
    plain = dest.parent / (dest.stem + "_plain.mp4")
    ok = _ff(
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x{bg}:rate={VIDEO_FPS}",
        "-t", str(LESSON_DUR),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(plain),
        timeout=30,
    )
    if not ok or not plain.exists():
        return False

    # Pass 2 — overlay text: label + lesson lines (each separate drawtext) + URL
    # Lesson block centred vertically — y_mid is the top of the text block
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
        timeout=60,
    )
    plain.unlink(missing_ok=True)
    return result


def _add_progress_bar(src: Path, dest: Path) -> bool:
    """Burn a static accent bar at the bottom of the video."""
    import shutil
    # Use ih/iw (lowercase) — uppercase H/W are not defined in drawbox expressions
    vf = f"drawbox=x=0:y=ih-{PROGRESS_H}:w=iw:h={PROGRESS_H}:color={PROGRESS_COLOR}:t=fill"
    ok = _ff(
        "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(dest),
        timeout=180,
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
        timeout=180,
    )


def _add_music(src: Path, dest: Path, slot: int = None) -> bool:
    """
    Mix in slot-specific trending music. Priority:
      1. music/daily/track_{slot}.mp3  — today's trending pick for this slot
      2. Any file in music/daily/       — another slot's trending pick
      3. music/archive/                 — royalty-free fallback library
    Falls back to copy (no audio overlay) only if all dirs are empty.
    """
    import shutil

    track = None

    # 1. Slot-specific daily track (fetched by fetch_trending_music.py at 6am)
    if slot:
        slot_track = MUSIC_DIR / f"track_{slot}.mp3"
        if slot_track.exists() and slot_track.stat().st_size > 50_000:
            track = slot_track

    # 2. Any daily track as fallback
    if track is None:
        daily = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.m4a"))
        daily = [t for t in daily if t.stat().st_size > 50_000 and "_tmp" not in str(t)]
        if daily:
            track = random.choice(daily)

    # 3. Archive fallback
    if track is None:
        archive = list(MUSIC_ARCHIVE.glob("*.mp3")) + list(MUSIC_ARCHIVE.glob("*.m4a"))
        if archive:
            track = random.choice(archive)

    if track is None:
        shutil.copy(src, dest)
        return True

    total = float(TOTAL_DUR)
    print(f"    [Music] Using: {track.name}")
    # Video has no audio track (all clips rendered with -an); use music directly
    return _ff(
        "-i", str(src), "-i", str(track),
        "-filter_complex",
        f"[1:a]atrim=0:{total},afade=t=out:st={total-3}:d=3,volume=0.85[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(dest),
        timeout=180,
    )


def _concat_clips(clip_paths: list, dest: Path) -> bool:
    """Concatenate processed clips using FFmpeg concat demuxer."""
    list_path = dest.parent / "concat_list.txt"
    list_path.write_text(
        "\n".join(f"file '{p}'" for p in clip_paths),
        encoding="utf-8",
    )
    ok = _ff(
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(dest),
        timeout=180,
    )
    list_path.unlink(missing_ok=True)
    return ok


def render_video(content: dict, slot: int, output_path: str) -> bool:
    """
    Full render pipeline.
    content: dict from generate_content() with hook/problem/stakes/resolution/lesson/visual_queries
    output_path: final .mp4 path
    """
    pillar  = content.get("pillar", "community")
    hook    = content.get("hook", "")
    problem = content.get("problem", "")
    stakes  = content.get("stakes", "")
    resolution = content.get("resolution", "")
    lesson  = content.get("lesson", "")
    queries = content.get("visual_queries", ["airport travel"] * N_CLIPS)
    if len(queries) < N_CLIPS:
        queries += ["diaspora delivery uk"] * (N_CLIPS - len(queries))

    # Beat text per clip
    beat_texts = [
        hook, hook,              # clips 0-1 hook
        problem, problem,        # clips 2-3 problem
        stakes,                  # clip 4 stakes
        resolution, resolution,  # clips 5-6 resolution
        lesson,                  # clip 7 lesson lead-in
    ]

    TEMP.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    prefix = f"otb_slot{slot}"
    used_ids: set = set()
    proc_clips: list = []

    print(f"\n  [Render] Hook: {hook[:60]}")
    print(f"  [Render] Pillar: {pillar} | Slot: {slot}")

    for i in range(N_CLIPS):
        query  = _guard_query(queries[i], i)   # second-layer safety filter
        beat   = CLIP_BEAT[i]
        text   = beat_texts[i]
        raw    = TEMP / f"{prefix}_raw_{i}.mp4"
        proc   = TEMP / f"{prefix}_proc_{i}.mp4"

        print(f"    Clip {i} [{beat}]: {query}")

        # Try video sources
        clip_info = _pexels_video(query, used_ids) or _pixabay_video(query, used_ids)
        got_video = False

        if clip_info:
            used_ids.add(clip_info["id"])
            if _download_clip(clip_info["url"], raw):
                if _process_clip(raw, proc, beat, text):
                    got_video = True
                    try: report_hit(query, "video")   # learner: good query
                    except Exception: pass
                raw.unlink(missing_ok=True)

        if not got_video:
            # Photo fallback
            print(f"    Clip {i}: falling back to photo")
            photo_raw = TEMP / f"{prefix}_photo_{i}.mp4"
            if _pexels_photo_as_clip(query, photo_raw):
                if _process_clip(photo_raw, proc, beat, text):
                    got_video = True
                    try: report_hit(query, "photo")   # learner: weak query (no video found)
                    except Exception: pass
                photo_raw.unlink(missing_ok=True)

        if not got_video:
            # Solid colour placeholder
            try: report_hit(query, "placeholder")     # learner: very weak query
            except Exception: pass
            _ff("-f", "lavfi", "-i",
                f"color=size={W}x{H}:color=0x111111:rate={VIDEO_FPS}",
                "-t", str(CLIP_DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(proc), timeout=30)

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
            timeout=60,
        )
    else:
        # Two-pass brand card (plain colour → overlay text via -vf, same as lesson card)
        _plain = TEMP / f"{prefix}_brand_plain.mp4"
        _ff("-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x0F172A:rate={VIDEO_FPS}",
            "-t", str(BRAND_DUR), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(_plain), timeout=30)
        if _plain.exists():
            _ff("-i", str(_plain),
                "-vf", (f"drawtext=fontfile='{_font('title')}':text='BootHop':fontsize=90:"
                        f"fontcolor=0xFFE600:x=(w-text_w)/2:y=(h-th)/2-30,"
                        f"drawtext=fontfile='{_font('body')}':text='boothop.com':fontsize=42:"
                        f"fontcolor=0xFFFFFF:x=(w-text_w)/2:y=(h-th)/2+70"),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p", "-an", str(brand_card), timeout=30)
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
    _add_music(with_logo, Path(output_path), slot=slot)
    with_logo.unlink(missing_ok=True)

    # Clean up clip temps
    for p in proc_clips:
        Path(p).unlink(missing_ok=True)

    ok = Path(output_path).exists() and Path(output_path).stat().st_size > 500_000
    if ok:
        size_mb = Path(output_path).stat().st_size // 1_048_576
        print(f"  [Render] Done — {size_mb}MB -> {output_path}")
    else:
        print(f"  [Render] Output missing or too small")
    return ok


# ── Platform-specific video variants ─────────────────────────────────────────
#
# Why each platform gets its own file:
#
# TIKTOK  — base render (crisp, high-contrast, text centred for TikTok UI)
# YOUTUBE — identical to TikTok (YouTube Shorts doesn't penalise cross-posts)
# INSTAGRAM — warm colour grade applied:
#   • Breaks visual fingerprinting: Instagram's crawler detects bit-for-bit identical
#     content that was already posted on TikTok and suppresses Reel reach by up to 30%.
#     A different colour matrix = different file hash = treated as original content.
#   • Suits IG aesthetic: Instagram feed skews warmer and more polished vs TikTok's
#     raw/contrasty look. Warm grade performs better in IG Explore.
# LINKEDIN — professional colour grade + 5-second B2B intro card prepended:
#   • LinkedIn audience is desktop-heavy, professional, B2B mindset.
#     The TikTok hook energy reads as entertainment content on LinkedIn feeds.
#     A 5-second "LOGISTICS INTELLIGENCE" branded card frames it as business insight first.
#   • Cooler, more desaturated grade signals professionalism vs TikTok's vibrant palette.
#   • LinkedIn's algorithm rewards watch-time; the intro card adds 5s, bumping average watch %.


def _grade_instagram(src: Path, dest: Path) -> bool:
    """Warm colour grade: breaks TikTok fingerprint + matches IG feed aesthetic."""
    return _ff(
        "-i", str(src),
        "-vf", "eq=brightness=0.03:saturation=1.12:contrast=1.02",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-c:a", "copy", str(dest),
        timeout=180,
    )


def _grade_linkedin(src: Path, dest: Path) -> bool:
    """Cooler, desaturated grade — professional LinkedIn look."""
    return _ff(
        "-i", str(src),
        "-vf", "eq=brightness=0.01:saturation=0.80:contrast=1.03",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy", str(dest),
        timeout=180,
    )


def _make_linkedin_intro(content: dict, dest: Path) -> bool:
    """
    5-second professional B2B intro card for LinkedIn.
    Two-pass: plain navy → overlay text via -vf (same pattern as lesson card).
    """
    hook_esc = _esc(content.get("hook", ""))[:70]
    font_t   = _font("title")
    font_b   = _font("body")

    # Split hook into up to 2 lines — separate drawtext per line
    hook_lines = _split_lines(hook_esc, 24, 2)
    n_lines    = len(hook_lines)
    line_gap   = 72   # 56px font × 1.3
    y_mid      = f"(h - {n_lines * line_gap}) / 2 - 20"

    plain = dest.parent / (dest.stem + "_plain.mp4")
    ok = _ff(
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color=0x0F172A:rate={VIDEO_FPS}",
        "-t", "5",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-an", str(plain),
        timeout=30,
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
        timeout=60,
    )
    plain.unlink(missing_ok=True)
    return result


def render_for_platforms(content: dict, slot: int, base_path: str) -> dict:
    """
    Derive platform-specific video variants from the base render.
    Returns {platform: absolute_file_path}.

    TikTok  — base (no change)
    YouTube — base (shared with TikTok)
    Instagram — warm grade (fingerprint break + IG aesthetic)
    LinkedIn  — professional grade + 5s B2B intro card
    IG Story / Newspaper — use the Instagram-graded file
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

    # ── Instagram warm grade ──────────────────────────────────────────────────
    ig_path = outdir / f"{stem}_ig.mp4"
    print("  [Render] Applying Instagram grade...")
    if _grade_instagram(base, ig_path) and ig_path.exists() and ig_path.stat().st_size > 200_000:
        paths["instagram"]       = str(ig_path)
        paths["instagram_story"] = str(ig_path)
        paths["newspaper"]       = str(ig_path)
        print(f"  [Render] Instagram grade OK ({ig_path.stat().st_size // 1024}KB)")
    else:
        print("  [Render] Instagram grade failed — using base")
        ig_path.unlink(missing_ok=True)

    # ── LinkedIn professional grade + intro card ──────────────────────────────
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
            timeout=180,
        )
        list_file.unlink(missing_ok=True)
        li_intro.unlink(missing_ok=True)
        li_graded.unlink(missing_ok=True)

        # Add music to LinkedIn version too
        li_music = outdir / f"{stem}_li_music.mp4"
        _add_music(li_path, li_music, slot=slot)
        li_path.unlink(missing_ok=True)
        if li_music.exists() and li_music.stat().st_size > 200_000:
            paths["linkedin"] = str(li_music)
            print(f"  [Render] LinkedIn variant OK ({li_music.stat().st_size // 1024}KB)")
        else:
            li_music.unlink(missing_ok=True)
            print("  [Render] LinkedIn music failed — using base")
    else:
        li_intro.unlink(missing_ok=True)
        li_graded.unlink(missing_ok=True)
        print("  [Render] LinkedIn variant failed — using base")

    return paths
