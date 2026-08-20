"""
render_kling_video.py — V2 video renderer (Kling library edition)

Assembles a 15-second BootHop video from Kling clips:
  0:00–0:02   Hook card (text overlay on best opening clip)
  0:02–0:11   Main story clips (2–4 Kling clips, trimmed to fill 9s)
  0:11–0:13.5 Brand message overlay on final clip
  0:13.5–0:15 CTA end card

Also produces 3 platform variants:
  TikTok       — fastest open, bold hook, direct CTA
  Instagram    — cleaner, premium, central safe area
  YouTube      — self-explanatory, hook direct, boothop.com CTA
"""

import json, os, random, re, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    OUTPUT, TEMP, ASSETS, DATA,
    VIDEO_W, VIDEO_H, VIDEO_FPS,
    FONT_BODY, FONT_TITLE, FONT_BODY_FB, FONT_TITLE_FB,
    LOGO_PATH, MUSIC_DIR, MUSIC_ARCHIVE,
    OPENAI_API_KEY, ANTHROPIC_API_KEY,
    KLING_LIBRARY, KLING_CLIP_COOLDOWN_DAYS,
    V2_TOTAL_DUR, V2_HOOK_DUR, V2_STORY_DUR, V2_BRAND_DUR, V2_CTA_DUR,
)
from analyse_kling_library import available_clips, mark_clip_used, get_library

FFMPEG = "ffmpeg"
W, H   = VIDEO_W, VIDEO_H

V2_MAX_CLIP_DUR  = 10.0    # cap any single clip at this many seconds
V2_MIN_STORY_DUR = 10.0    # if clip total is below this, prepend a hook card
V2_HOOK_CARD_DUR = 3.0     # duration of the hook text card (when used)
V2_BRAND_OVERLAY = 2.0     # how long to show brand message at end of story
V2_HOOK_OVERLAY  = 2.0     # how long to show hook text at start of story


def _ffpath(p) -> str:
    """Convert path to FFmpeg-safe string (forward slashes — required in concat files on Windows)."""
    return str(p).replace("\\", "/")


# ── font helpers ──────────────────────────────────────────────────────────────

def _font(which="body"):
    p = FONT_TITLE if which == "title" else FONT_BODY
    return p if Path(p).exists() else (FONT_TITLE_FB if which == "title" else FONT_BODY_FB)


def _esc(s: str) -> str:
    """Escape text/path for FFmpeg drawtext filter."""
    return (
        s.replace("\\", "/")                # forward slashes (Windows path fix)
         .replace(chr(39), "’")        # ASCII apostrophe -> right single quote (avoids drawtext delimiter breakage)
         .replace(":", r"\:")               # colon is special in FFmpeg filter graphs
    )


# ── music ─────────────────────────────────────────────────────────────────────

def _pick_music() -> Path | None:
    for d in [MUSIC_DIR, MUSIC_ARCHIVE]:
        if d.exists():
            tracks = list(d.glob("*.mp3")) + list(d.glob("*.m4a"))
            if tracks:
                return random.choice(tracks)
    return None


# ── Whisper transcription ─────────────────────────────────────────────────────

def _transcribe(clip_path: Path) -> list[dict]:
    """
    Transcribe audio in a clip using OpenAI Whisper.
    Returns list of {start, end, text} segments.
    """
    if not OPENAI_API_KEY:
        return []
    try:
        import requests
        with open(clip_path, "rb") as f:
            resp = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": (clip_path.name, f, "video/mp4")},
                data={"model": "whisper-1", "response_format": "verbose_json",
                      "timestamp_granularities[]": "segment"},
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"start": round(s["start"], 2),
                 "end":   round(s["end"],   2),
                 "text":  s["text"].strip()}
                for s in data.get("segments", [])
                if s["text"].strip()
            ]
    except Exception as e:
        print(f"  [Whisper] {clip_path.name}: {e}")
        return []


def _update_transcript_in_library(filename: str, segments: list[dict]):
    """Persist transcript back to kling_library.json."""
    lib_path = DATA / "kling_library.json"
    if not lib_path.exists():
        return
    try:
        lib = json.loads(lib_path.read_text(encoding="utf-8"))
        for entry in lib:
            if entry["filename"] == filename:
                entry["transcript"]    = " ".join(s["text"] for s in segments)
                entry["dialogue_start"] = segments[0]["start"] if segments else 0.0
                break
        lib_path.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ── clip selection via Claude ─────────────────────────────────────────────────

def _select_clips(story: dict, clips: list[dict], n_target: int = 1) -> list[dict]:
    """
    Ask Claude to pick the best clips from the available catalogue for this story.
    Returns ordered list of clip entries to use.
    """
    if not ANTHROPIC_API_KEY or not clips:
        return clips[:n_target]

    catalogue = "\n".join(
        f"{i}: {c['filename']} | {c['scene_type']} | {c['setting']} | "
        f"fit={c['boothop_fit']}/10 | use={c['best_use']} | {c['action'][:80]}"
        for i, c in enumerate(clips)
    )

    prompt = (
        f"You are the creative director for BootHop (UK-Nigeria peer-to-peer parcel delivery).\n\n"
        f"STORY:\n"
        f"  Hook: {story.get('hook', '')}\n"
        f"  Problem: {story.get('problem', '')}\n"
        f"  Resolution: {story.get('resolution', '')}\n"
        f"  Lesson: {story.get('lesson', '')}\n\n"
        f"AVAILABLE CLIPS (index: filename | scene_type | setting | boothop_fit | best_use | description):\n"
        f"{catalogue}\n\n"
        f"Select the single best clip that fits this BootHop story.\n"
        f"Rules:\n"
        f"- Pick the clip with the highest boothop_fit score (>= 7 preferred)\n"
        f"- The clip should work as a standalone piece — people talking, handing over parcels, travel scenes\n"
        f"- Do not select clips marked best_use=avoid\n\n"
        f"Return ONLY valid JSON: {{\"selected\": [3]}}  (one clip index)"
    )

    try:
        import requests as _req
        resp = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        m   = re.search(r"\{[\s\S]*\}", raw)
        if m:
            indices = json.loads(m.group()).get("selected", [])
            selected = [clips[i] for i in indices if i < len(clips)]
            if selected:
                print(f"  [ClipSelect] Claude picked: {[c['filename'][:40] for c in selected]}")
                return selected
    except Exception as e:
        print(f"  [ClipSelect] Claude error: {e} — using top-fit clips")

    return clips[:n_target]


# ── subtitle filter builder ───────────────────────────────────────────────────

def _subtitle_filter(segments: list[dict], time_offset: float, font: str) -> str:
    """Build FFmpeg drawtext filters for subtitle segments, offset by time_offset seconds."""
    filters = []
    for seg in segments:
        t_start = seg["start"] + time_offset
        t_end   = seg["end"]   + time_offset
        text    = _esc(seg["text"][:60])  # cap line length
        # white text, dark outline, bottom-safe zone
        filters.append(
            f"drawtext=fontfile='{_esc(font)}':text='{text}'"
            f":fontsize=48:fontcolor=white:bordercolor=black:borderw=3"
            f":x=(w-text_w)/2:y=h*0.78"
            f":enable='between(t\\,{t_start:.2f}\\,{t_end:.2f})'"
        )
    return ",".join(filters) if filters else ""


# ── hook text overlay ─────────────────────────────────────────────────────────

_HOOK_TEXTS = {
    "tiktok": [
        "Travelling soon? Watch this 👀",
        "Your journey could make you money",
        "Why travel with empty luggage?",
        "Already going that way? 👇",
        "Your empty luggage space has value",
    ],
    "instagram": [
        "Send smarter with BootHop",
        "A smarter way to send items",
        "Already going that way?",
        "Sending something abroad?",
        "Your journey can earn",
    ],
    "youtube": [
        "This is how BootHop works",
        "Send items abroad via travellers",
        "A smarter way to send home",
        "Earn money on your next trip",
        "BootHop — peer delivery explained",
    ],
}

_BRAND_MSGS = [
    "Send smarter with BootHop",
    "Same journey. Extra earning.",
    "Connecting senders with travellers",
    "Travelling anyway? Earn from it.",
    "Your journey can earn.",
]

_CTA_TRAVELLER = "Already travelling? Earn with BootHop."
_CTA_SENDER    = "Need to send it? Find a traveller at boothop.com"
_CTA_GENERAL   = "Download BootHop today — boothop.com"


# ── core render ───────────────────────────────────────────────────────────────

def _trim_clip(src: Path, out: Path, duration: float, offset: float = 0.0):
    """Trim and scale a clip to exact duration, 1080×1920 vertical."""
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )
    # First attempt: use clip's own audio
    r = subprocess.run([
        FFMPEG, "-y",
        "-ss", str(offset), "-i", str(src),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-r", str(VIDEO_FPS), str(out)
    ], capture_output=True, timeout=60)
    if not out.exists():
        # Retry with synthetic silent audio (clip may have no audio track)
        r2 = subprocess.run([
            FFMPEG, "-y",
            "-ss", str(offset), "-i", str(src),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-r", str(VIDEO_FPS), "-shortest", str(out)
        ], capture_output=True, timeout=60)
        if not out.exists():
            print(f"  [V2 trim] FAILED {src.name}: {r.stderr[-300:].decode(errors='replace')}")


def _silent_clip(out: Path, duration: float, color: str = "black"):
    """Generate a silent solid-colour clip."""
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:r={VIDEO_FPS}:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        str(out)
    ], capture_output=True, timeout=30)


def _wrap_segments(segments: list[dict], max_words: int = 8) -> list[dict]:
    """Split long subtitle segments so no line exceeds max_words."""
    result = []
    for seg in segments:
        words = seg["text"].split()
        if len(words) <= max_words:
            result.append(seg)
        else:
            dur = seg["end"] - seg["start"]
            chunks = [words[i:i + max_words] for i in range(0, len(words), max_words)]
            chunk_dur = dur / len(chunks)
            for j, chunk in enumerate(chunks):
                result.append({
                    "start": seg["start"] + j * chunk_dur,
                    "end":   seg["start"] + (j + 1) * chunk_dur,
                    "text":  " ".join(chunk),
                })
    return result


def _scale_clip(src: Path, out: Path):
    """Scale a clip to 1080×1920 without trimming — keeps full natural length."""
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )
    r = subprocess.run([
        FFMPEG, "-y", "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-r", str(VIDEO_FPS), str(out)
    ], capture_output=True, timeout=120)
    if not out.exists():
        # Retry with synthetic audio (clip may lack audio track)
        r2 = subprocess.run([
            FFMPEG, "-y", "-i", str(src),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-r", str(VIDEO_FPS), "-shortest", str(out)
        ], capture_output=True, timeout=120)
        if not out.exists():
            print(f"  [V2 scale] FAILED {src.name}: {r.stderr[-300:].decode(errors='replace')}")


def render_v2_video(
    story: dict,
    slot: int,
    out_base: Path,
) -> tuple[bool, dict]:
    """
    Assemble a V2 BootHop video from a single Kling clip.
    Structure: [1 Kling clip, full natural duration] → [BootHop CTA card 2.5s]
    No cuts mid-speech. No mixing multiple clips.
    Returns (success, platform_paths_dict).
    """
    TEMP.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    font   = _font("body")
    music  = _pick_music()

    # ── 1. Get available clips ─────────────────────────────────────────────────
    clips = available_clips(min_fit=5)
    if not clips:
        print("  [V2] No available clips — re-run analyse_kling_library.py")
        return False, {}

    # ── 2. Select 1 best clip for this story ──────────────────────────────────
    selected_list = _select_clips(story, clips, n_target=1)
    if not selected_list:
        print("  [V2] No clip selected")
        return False, {}
    clip_entry = selected_list[0]
    src = KLING_LIBRARY / clip_entry["filename"]
    if not src.exists():
        print(f"  [V2] Clip file missing: {clip_entry['filename']}")
        return False, {}
    print(f"  [V2] Using clip: {clip_entry['filename'][:50]} ({clip_entry.get('duration',0):.1f}s)")

    # ── 3. Transcribe (Whisper) ────────────────────────────────────────────────
    segments: list[dict] = []
    if clip_entry.get("has_speech") and not clip_entry.get("transcript"):
        print(f"  [Whisper] Transcribing {clip_entry['filename'][:40]}...")
        segments = _transcribe(src)
        segments = _wrap_segments(segments, max_words=8)
        _update_transcript_in_library(clip_entry["filename"], segments)

    # ── 4. Scale clip to vertical 1080×1920 (full length, no trim) ───────────
    scaled_clip = TEMP / f"v2_{run_id}_clip.mp4"
    _scale_clip(src, scaled_clip)
    if not scaled_clip.exists():
        print("  [V2] Scale failed — aborting")
        return False, {}

    clip_dur = float(clip_entry.get("duration") or 10.0)

    # ── 5. Build CTA end card ─────────────────────────────────────────────────
    cta_path = TEMP / f"v2_{run_id}_cta.mp4"
    _build_cta_card(cta_path, run_id)

    # ── 6. Concat clip + CTA ──────────────────────────────────────────────────
    story_mp4   = TEMP / f"v2_{run_id}_story.mp4"
    concat_list = TEMP / f"v2_{run_id}_concat.txt"
    concat_list.write_text(
        f"file '{_ffpath(scaled_clip)}'\nfile '{_ffpath(cta_path)}'",
        encoding="utf-8"
    )
    r_concat = subprocess.run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        str(story_mp4)
    ], capture_output=True, timeout=90)
    if not story_mp4.exists():
        print(f"  [V2 concat] FAILED: {r_concat.stderr[-400:].decode(errors='replace')}")
        return False, {}

    total_dur = clip_dur + V2_CTA_DUR

    # ── 7. Build subtitle filter (word-wrapped) ────────────────────────────────
    sub_filter = _subtitle_filter(segments, time_offset=0.0, font=font) if segments else ""

    # ── 8. Render 3 platform variants ─────────────────────────────────────────
    platform_paths = {}
    hook_texts = {
        "tiktok":    random.choice(_HOOK_TEXTS["tiktok"]),
        "instagram": random.choice(_HOOK_TEXTS["instagram"]),
        "youtube":   random.choice(_HOOK_TEXTS["youtube"]),
    }
    brand_msg = random.choice(_BRAND_MSGS)

    for platform, hook_text in hook_texts.items():
        out_path = Path(str(out_base) + f"_{platform}.mp4")
        ok = _render_platform(
            story_mp4  = story_mp4,
            out_path   = out_path,
            hook_text  = hook_text,
            brand_msg  = brand_msg,
            sub_filter = sub_filter,
            music      = music,
            font       = font,
            platform   = platform,
            run_id     = run_id,
            clip_dur   = clip_dur,
            total_dur  = total_dur,
        )
        if ok:
            platform_paths[platform] = str(out_path)
            print(f"  [V2] {platform}: {out_path.name}")

    # ── 9. Mark clip used (14-day cooldown) ───────────────────────────────────
    mark_clip_used(clip_entry["filename"])

    # Cleanup temp files
    for f in [scaled_clip, story_mp4, concat_list, cta_path]:
        try: f.unlink()
        except Exception: pass

    return bool(platform_paths), platform_paths


def _render_platform(
    story_mp4, out_path, hook_text, brand_msg,
    sub_filter, music, font, platform, run_id,
    clip_dur: float, total_dur: float,
) -> bool:
    """Add text overlays + background music to the merged clip+CTA video."""

    hook_y  = {"tiktok": "h*0.12", "instagram": "h*0.10", "youtube": "h*0.12"}.get(platform, "h*0.12")
    brand_y = "h*0.78"

    hook_end = min(V2_HOOK_OVERLAY, clip_dur * 0.25)
    hook_filter = (
        f"drawtext=fontfile='{_esc(font)}':text='{_esc(hook_text)}'"
        f":fontsize=56:fontcolor=white:bordercolor=black:borderw=4"
        f":x=(w-text_w)/2:y={hook_y}"
        f":enable='between(t\\,0\\,{hook_end:.2f})'"
    )

    brand_start = max(0.0, clip_dur - V2_BRAND_OVERLAY)
    brand_end   = clip_dur
    brand_filter = (
        f"drawtext=fontfile='{_esc(font)}':text='{_esc(brand_msg)}'"
        f":fontsize=50:fontcolor=white:bordercolor=black:borderw=3"
        f":x=(w-text_w)/2:y={brand_y}"
        f":enable='between(t\\,{brand_start:.2f}\\,{brand_end:.2f})'"
    )

    vf_parts = [hook_filter, brand_filter]
    if sub_filter:
        vf_parts.append(sub_filter)
    vf = ",".join(vf_parts)

    fade_out_start = max(0.0, total_dur - 1.0)

    # ── Audio mixing ─────────────────────────────────────────────────────────
    music_input = ["-i", str(music)] if music else []
    has_music   = bool(music)

    if has_music:
        audio_filter = (
            f"[1:a]volume=0.13,afade=t=in:st=0:d=0.5,"
            f"afade=t=out:st={fade_out_start:.2f}:d=0.8[mus];"
            "[0:a][mus]amix=inputs=2:duration=first:weights=1 0.13[outa]"
        )
        cmd = [FFMPEG, "-y", "-i", str(story_mp4)] + music_input + ["-vf", vf]
        cmd += ["-filter_complex", audio_filter, "-map", "0:v", "-map", "[outa]"]
    else:
        cmd = [FFMPEG, "-y", "-i", str(story_mp4)] + ["-vf", vf, "-c:a", "copy"]

    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        str(out_path)
    ]

    r = subprocess.run(cmd, capture_output=True, timeout=180)

    if not out_path.exists():
        print(f"  [V2 render/{platform}] FAILED: {r.stderr[-400:].decode(errors='replace')}")
        return False

    return out_path.stat().st_size > 50_000


def _build_cta_card(out_path: Path, run_id: str):
    """Build a 2.5s BootHop CTA end card using PIL, then encode to video."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        img  = Image.new("RGB", (W, H), color=(10, 10, 10))
        draw = ImageDraw.Draw(img)

        # Background gradient feel — indigo block
        draw.rectangle([(0, H//3), (W, H*2//3)], fill=(30, 20, 80))

        # Logo
        logo_p = Path(str(LOGO_PATH))
        if logo_p.exists():
            logo = Image.open(logo_p).convert("RGBA")
            logo.thumbnail((320, 160))
            lx = (W - logo.width) // 2
            ly = H // 5
            img.paste(logo, (lx, ly), logo)

        # CTA text
        try:
            fnt_big = ImageFont.truetype(str(FONT_BODY), 52)
            fnt_sm  = ImageFont.truetype(str(FONT_BODY), 36)
        except Exception:
            fnt_big = ImageFont.load_default()
            fnt_sm  = fnt_big

        lines = ["boothop.com", "Available on iOS & Android"]
        y = H // 2 + 20
        for i, line in enumerate(lines):
            fnt = fnt_big if i == 0 else fnt_sm
            col = (255, 255, 255) if i == 0 else (180, 180, 220)
            bbox = draw.textbbox((0, 0), line, font=fnt)
            tw   = bbox[2] - bbox[0]
            draw.text(((W - tw) // 2, y), line, font=fnt, fill=col)
            y += 70

        # Save frame to temp PNG then encode to video
        png = TEMP / f"v2_{run_id}_cta.png"
        img.save(str(png))

        subprocess.run([
            FFMPEG, "-y",
            "-loop", "1", "-i", str(png),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(V2_CTA_DUR),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-r", str(VIDEO_FPS),
            str(out_path)
        ], capture_output=True, timeout=30)

        try: png.unlink()
        except Exception: pass

    except Exception as e:
        print(f"  [CTA card] PIL error: {e} — using silent black card")
        _silent_clip(out_path, V2_CTA_DUR)
