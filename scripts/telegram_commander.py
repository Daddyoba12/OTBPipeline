"""
OTB_Pipeline — Telegram commander (Full Edition)
Ported from BootHopPipeline commander, adapted for OTB slot-based pipeline.

Approval flow:   send_video_preview / poll_for_decision / send_result  (called by pipeline.py)
Revoice Studio:  /revoice [2|3|4] → record voice → pick music → bake → post
Commands:        /menu  /status  /pause  /resume  /rerun [slot]  /revoice [slot]  /story  /music  /block
Natural lang:    "pause", "resume", "rerun", "status", "what's running", "get music", etc.
Pending queue:   pending_newspaper.json / pending_story.json / pending_linkedin.json
Cleanup:         48-hour message deletion (runs automatically on startup)
"""

import json, os, subprocess, sys, tempfile, threading, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DATA, BASE, OUTPUT,
    MUSIC_DIR, MUSIC_ARCHIVE,
    ORACLE_IP, ORACLE_USER, ORACLE_KEY,
)

import requests

# ── Constants ──────────────────────────────────────────────────────────────────
OFFSET_FILE       = DATA / "tg_offset.json"
MSG_LOG_FILE      = DATA / "tg_message_log.json"
PENDING_REVOICE   = DATA / "pending_revoice.json"
LATEST_REVOICED   = DATA / "latest_revoiced.json"
PENDING_NEWSPAPER = DATA / "pending_newspaper.json"
PENDING_STORY     = DATA / "pending_story.json"
PENDING_LINKEDIN  = DATA / "pending_linkedin.json"
REVOICE_STUDIO    = DATA / "revoice_studio.json"
EDIT_SESSION_FILE = DATA / "edit_session.json"
SWAPMUSIC_SESSION = DATA / "swapmusic_session.json"

PYTHON    = sys.executable
FFMPEG    = "ffmpeg"
FFPROBE   = "ffprobe"
INSTANCE  = os.environ.get("OTB_INSTANCE", "laptop")
BASE_URL  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

_SLOT_LABELS = {
    1: "Slot 1 — IG Story / Blog / LinkedIn (7am)",
    2: "Slot 2 — TikTok + IG Reel (9am)",
    3: "Slot 3 — TikTok + IG Reel (6pm)",
    4: "Slot 4 — TikTok + YouTube (9pm)",
}

# ── Offset + 48h message log ───────────────────────────────────────────────────

def _load_offset() -> int:
    try:
        return json.loads(OFFSET_FILE.read_text())["offset"]
    except Exception:
        return 0


def _save_offset(offset: int):
    try:
        OFFSET_FILE.parent.mkdir(exist_ok=True)
        OFFSET_FILE.write_text(json.dumps({"offset": offset}))
    except Exception:
        pass


def _is_commander_running() -> bool:
    """Return True if a separate commander process is already running (checked via PID file)."""
    try:
        if not _PID_FILE.exists():
            return False
        pid = int(_PID_FILE.read_text().strip())
        if pid == os.getpid():
            return False  # we ARE the commander
        import platform
        if platform.system() == "Windows":
            import subprocess as _sp
            r = _sp.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in r.stdout
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def _write_web_approval(slot: int, decision: str):
    """Write an approval decision file so poll_for_decision can pick it up."""
    try:
        f = DATA / f"web_approval_{slot}.json"
        f.write_text(json.dumps({"decision": decision, "source": "telegram_button"}))
        print(f"[Cmdr] Approval written → {decision} (Slot {slot})")
    except Exception as e:
        print(f"[Cmdr] Could not write approval file: {e}")


def _log_message(msg_id: int):
    try:
        log = json.loads(MSG_LOG_FILE.read_text(encoding="utf-8")) if MSG_LOG_FILE.exists() else []
        log.append({"id": msg_id, "sent_at": datetime.utcnow().isoformat()})
        log = log[-500:]
        MSG_LOG_FILE.write_text(json.dumps(log, indent=2), encoding="utf-8")
    except Exception:
        pass


def clean_old_messages():
    """Delete bot messages older than 48h. Called once on startup then every 48h."""
    if not MSG_LOG_FILE.exists():
        return
    try:
        log     = json.loads(MSG_LOG_FILE.read_text(encoding="utf-8"))
        cutoff  = datetime.utcnow() - timedelta(hours=48)
        keep, deleted = [], 0
        for entry in log:
            sent_at = datetime.fromisoformat(entry.get("sent_at", "2000-01-01"))
            if sent_at < cutoff:
                try:
                    requests.post(f"{BASE_URL}/deleteMessage",
                                  json={"chat_id": TELEGRAM_CHAT_ID, "message_id": entry["id"]},
                                  timeout=8)
                    deleted += 1
                except Exception:
                    keep.append(entry)
            else:
                keep.append(entry)
        MSG_LOG_FILE.write_text(json.dumps(keep, indent=2), encoding="utf-8")
        print(f"[Cmdr] Cleanup: deleted {deleted} messages ({len(keep)} remaining)")
    except Exception as e:
        print(f"[Cmdr] Cleanup error: {e}")


# ── Telegram helpers ──────────────────────────────────────────────────────────

def _send(text: str, reply_markup: dict = None) -> dict:
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r    = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=15)
        data = r.json()
        if data.get("ok"):
            _log_message(data["result"]["message_id"])
        return data
    except Exception as e:
        print(f"[Cmdr] Send error: {e}")
        return {}


def _send_video(path: Path, caption: str = "", reply_markup: dict = None):
    try:
        markup_str = json.dumps(reply_markup) if reply_markup else None
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "supports_streaming": "true"}
        if markup_str:
            data["reply_markup"] = markup_str
        with open(path, "rb") as f:
            r = requests.post(f"{BASE_URL}/sendVideo", data=data, files={"video": f}, timeout=180)
        if r.ok:
            result = r.json().get("result", {})
            _log_message(result.get("message_id", 0))
            return result
    except Exception as e:
        _send(f"❌ Could not send video: {e}")
    return {}


def _ack(cb_id: str, text: str = "Got it"):
    try:
        requests.post(f"{BASE_URL}/answerCallbackQuery",
                      json={"callback_query_id": cb_id, "text": text}, timeout=10)
    except Exception:
        pass


def _get_audio_duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 30.0


# ── Music helpers ─────────────────────────────────────────────────────────────

_MUSIC_PAGE_SIZE = 6  # tracks shown per page


def _list_music_tracks(max_tracks: int = 999) -> list:
    seen, tracks = set(), []
    for folder in [MUSIC_DIR, MUSIC_ARCHIVE, BASE / "music" / "yt_downloads"]:
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac") and f not in seen:
                seen.add(f)
                tracks.append(f)
                if len(tracks) >= max_tracks:
                    return tracks
    return tracks


def _music_page_keyboard(page: int = 0, prefix: str = "rs") -> dict:
    """Paged music browser. Each track has a ▶️ preview button.
    prefix: 'rs' for revoice studio, 'ms' for swap-music standalone."""
    tracks   = _list_music_tracks()
    total    = len(tracks)
    pages    = max(1, (total + _MUSIC_PAGE_SIZE - 1) // _MUSIC_PAGE_SIZE)
    page     = max(0, min(page, pages - 1))
    start    = page * _MUSIC_PAGE_SIZE
    chunk    = tracks[start:start + _MUSIC_PAGE_SIZE]

    rows = []
    for i, t in enumerate(chunk):
        abs_i = start + i
        rows.append([{"text": f"▶️  {t.stem[:34]}", "callback_data": f"{prefix}_mpreview_{abs_i}"}])

    nav = []
    if page > 0:
        nav.append({"text": "◀️ Prev", "callback_data": f"{prefix}_mpage_{page - 1}"})
    nav.append({"text": f"{page + 1}/{pages}", "callback_data": "rs_noop"})
    if page < pages - 1:
        nav.append({"text": "Next ▶️", "callback_data": f"{prefix}_mpage_{page + 1}"})
    rows.append(nav)

    rows.append([
        {"text": "📺 Download from YouTube", "callback_data": f"{prefix}_music_yt"},
        {"text": "🔇 No music",              "callback_data": f"{prefix}_music_none"},
    ])
    return {"inline_keyboard": rows}


def _music_keyboard() -> dict:
    return _music_page_keyboard(0, "rs")


def _send_music_preview(track: Path):
    """Extract first 30s of a track and send as playable audio to Telegram."""
    tmp = TEMP / f"mpreview_{track.stem[:20]}.mp3"
    try:
        subprocess.run(
            [FFMPEG, "-y", "-i", str(track), "-t", "30", "-q:a", "4", str(tmp)],
            capture_output=True, timeout=20
        )
        if tmp.exists():
            with open(tmp, "rb") as f:
                requests.post(
                    f"{BASE_URL}/sendAudio",
                    data={"chat_id": TELEGRAM_CHAT_ID,
                          "caption": f"🎵 Preview: {track.stem}",
                          "title": track.stem, "performer": "BootHop Music"},
                    files={"audio": f}, timeout=30
                )
    except Exception as e:
        _send(f"⚠️ Preview error: {e}")
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _trim_keyboard() -> dict:
    return {"inline_keyboard": [[
        {"text": "15s", "callback_data": "rs_trim_15"},
        {"text": "30s", "callback_data": "rs_trim_30"},
        {"text": "45s", "callback_data": "rs_trim_45"},
    ]]}


def _slot_picker_keyboard(callback_prefix: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "S2 — 9am",  "callback_data": f"{callback_prefix}_2"},
        {"text": "S3 — 6pm",  "callback_data": f"{callback_prefix}_3"},
        {"text": "S4 — 9pm",  "callback_data": f"{callback_prefix}_4"},
    ]]}


# ── Revoice Studio state machine ──────────────────────────────────────────────

def _rs_load() -> dict:
    try:
        d = json.loads(REVOICE_STUDIO.read_text(encoding="utf-8"))
        if time.time() > d.get("expires", 0):
            REVOICE_STUDIO.unlink(missing_ok=True)
            return {}
        return d
    except Exception:
        return {}


def _rs_save(data: dict):
    data.setdefault("expires", time.time() + 3600)
    REVOICE_STUDIO.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _rs_clear():
    try:
        REVOICE_STUDIO.unlink(missing_ok=True)
    except Exception:
        pass


# ── Find latest slot video ────────────────────────────────────────────────────

def _find_latest_video(slot: int) -> tuple:
    """Return (video_path, sidecar_data) for the most recent otb_slot{slot}_*.mp4."""
    candidates = sorted(
        [f for f in OUTPUT.glob(f"otb_slot{slot}_*.mp4") if "_revoiced" not in f.name],
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not candidates:
        return None, {}
    video   = candidates[0]
    sidecar = video.with_suffix(".json")
    data    = {}
    if sidecar.exists():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            pass
    return video, data


def _find_latest_v2_base(slot: int) -> str | None:
    """Return the base filename (no platform/extension) for the most recent V2 slot sidecar."""
    sidecars = sorted(
        OUTPUT.glob(f"otb_v2_slot{slot}_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return sidecars[0].stem if sidecars else None


# ── Revoice Studio flow ───────────────────────────────────────────────────────

def do_revoice(slot: int):
    video, data = _find_latest_video(slot)
    v2_base     = _find_latest_v2_base(slot)
    if not video and not v2_base:
        _send(f"❌ No Slot {slot} video found in output. Run /rerun {slot} first.")
        return

    hook    = data.get("hook", "")
    caption = data.get("caption", hook)
    label   = _SLOT_LABELS.get(slot, f"Slot {slot}")

    # Determine preview video (prefer V2 tiktok, fall back to V1)
    preview_path = None
    if v2_base:
        p = OUTPUT / f"{v2_base}_tiktok.mp4"
        if p.exists():
            preview_path = p
    if not preview_path and video and video.exists():
        preview_path = video

    # Save studio state (needed for record flow)
    if video:
        _rs_save({
            "step":          "idle",
            "slot":          slot,
            "video_path":    str(video),
            "hook":          hook,
            "caption":       caption,
            "music_path":    "",
            "trim_seconds":  30,
            "recorded_path": None,
            "expires":       time.time() + 3600,
        })
    elif v2_base:
        _rs_save({
            "step":    "idle",
            "slot":    slot,
            "v2_base": v2_base,
            "hook":    hook,
            "expires": time.time() + 3600,
        })

    # ── Step 1: Send the current video so user knows what they're working with
    if preview_path:
        _send_video(preview_path, caption=f"📺 <b>{label}</b> — current video")

    # ── Step 2: Show action menu
    rows = []
    action_row = []
    if video:
        action_row.append({"text": "🎤 Record Voice", "callback_data": "rs_record"})
    if v2_base:
        action_row.append({"text": "🤖 Auto TTS",     "callback_data": f"cmd_autorevoice_{slot}"})
    if action_row:
        rows.append(action_row)
    rows.append([
        {"text": "🎵 Swap Music Only", "callback_data": f"cmd_swapmusic_{slot}"},
        {"text": "⏭ Cancel",           "callback_data": "rs_skip_studio"},
    ])

    script_note = f"\n\n<b>Script to record:</b>\n<i>{hook[:280]}</i>" if hook else ""
    _send(
        f"🎬 <b>Re-voice Studio — {label}</b>{script_note}\n\n"
        f"🎤 <b>Record Voice</b> — hold Telegram mic, record, release. Bot collects it.\n"
        f"🤖 <b>Auto TTS</b> — AI generates narration, you hear it first before baking.\n"
        f"🎵 <b>Swap Music</b> — change background music only, no new voice.",
        reply_markup={"inline_keyboard": rows},
    )


_TTS_VOICES = ["nova", "alloy", "echo", "fable", "onyx", "shimmer"]


def do_autorevoice(slot: int, voice: str = "nova"):
    """Preview TTS narration as audio first, then let user confirm before baking."""
    base = _find_latest_v2_base(slot)
    if not base:
        _send(f"❌ No V2 video found for Slot {slot}. Run /rerun {slot} first.")
        return
    label = _SLOT_LABELS.get(slot, f"Slot {slot}")

    # Build narration text from sidecar
    sidecar = OUTPUT / f"{base}.json"
    story   = {}
    if sidecar.exists():
        try:
            story = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            pass
    hook    = story.get("hook", "").strip()
    lesson  = story.get("lesson", "").strip()
    narr    = " ".join(p for p in [hook, lesson, "Download BootHop and connect with travellers today."] if p)

    _send(f"🤖 Generating <b>{voice}</b> voice preview for {label}…  (~5 seconds)")

    # Generate TTS preview audio
    from config import OPENAI_API_KEY as _OAI_KEY
    narr_tmp = TEMP / f"tts_preview_slot{slot}.mp3"
    tts_ok = False
    if _OAI_KEY:
        try:
            r = requests.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {_OAI_KEY}"},
                json={"model": "tts-1", "input": narr, "voice": voice},
                timeout=30,
            )
            r.raise_for_status()
            narr_tmp.write_bytes(r.content)
            tts_ok = True
        except Exception as e:
            _send(f"⚠️ TTS preview failed: {e}. Baking directly…")

    if tts_ok and narr_tmp.exists():
        # Send audio preview
        try:
            with open(narr_tmp, "rb") as f:
                requests.post(
                    f"{BASE_URL}/sendAudio",
                    data={"chat_id": TELEGRAM_CHAT_ID,
                          "caption": f"🎧 <b>{voice}</b> narration preview — {label}\n<i>{narr[:100]}…</i>",
                          "parse_mode": "HTML",
                          "title": f"Narration - {label}", "performer": "BootHop AI"},
                    files={"audio": f}, timeout=30
                )
        except Exception:
            pass

        # Save state so confirm knows what to bake
        _rs_save({
            "step":     "tts_preview",
            "slot":     slot,
            "v2_base":  base,
            "voice":    voice,
            "narr_path": str(narr_tmp),
            "expires":  time.time() + 1800,
        })

        vi = _TTS_VOICES.index(voice) if voice in _TTS_VOICES else 0
        next_voice = _TTS_VOICES[(vi + 1) % len(_TTS_VOICES)]
        _send(
            f"🎧 <b>Narration preview above</b> — happy with the <b>{voice}</b> voice?",
            reply_markup={"inline_keyboard": [
                [
                    {"text": "✅ Bake it in",         "callback_data": f"rs_tts_confirm_{slot}"},
                    {"text": f"🔄 Try {next_voice}",  "callback_data": f"rs_tts_voice_{slot}_{next_voice}"},
                ],
                [
                    {"text": "🎤 Record instead",     "callback_data": "rs_record"},
                    {"text": "❌ Cancel",              "callback_data": "rs_skip_studio"},
                ],
            ]},
        )
    else:
        # No preview possible — bake directly
        _do_bake_autorevoice(slot, base, voice)


def _do_bake_autorevoice(slot: int, base: str, voice: str = "nova"):
    """Run revoice_v2.py to bake TTS into the V2 video, then send result. Runs in background thread."""
    label = _SLOT_LABELS.get(slot, f"Slot {slot}")
    _send(f"⏳ Baking {label} — adding narration + music… ~30 seconds")
    threading.Thread(target=_bake_autorevoice_bg, args=(slot, base, voice, label), daemon=True).start()


def _bake_autorevoice_bg(slot: int, base: str, voice: str, label: str):

    revoice_script = BASE / "revoice_v2.py"
    try:
        result = subprocess.run(
            [PYTHON, str(revoice_script), base],
            capture_output=True, text=True, timeout=120, cwd=str(BASE),
        )
        if result.returncode != 0:
            _send(f"❌ Bake failed:\n<code>{result.stderr[-300:]}</code>")
            return
    except Exception as e:
        _send(f"❌ Bake error: {e}")
        return

    tiktok_path = OUTPUT / f"{base}_tiktok.mp4"
    if tiktok_path.exists():
        _send_video(
            tiktok_path,
            caption=f"✅ <b>Done — {label}</b>",
            reply_markup={"inline_keyboard": [
                [
                    {"text": "🚀 Post TikTok", "callback_data": f"post_revoiced_{slot}_tiktok"},
                    {"text": "📸 Post IG",     "callback_data": f"post_revoiced_{slot}_ig"},
                ],
                [
                    {"text": "🎵 Swap Music",  "callback_data": f"cmd_swapmusic_{slot}"},
                    {"text": "📝 Blog",        "callback_data": f"cmd_blog_{slot}"},
                ],
                [{"text": "⏭ Done", "callback_data": "rs_skip_studio"}],
            ]},
        )
        try:
            LATEST_REVOICED.write_text(json.dumps({
                "path": str(tiktok_path), "hook": base,
                "slot": slot, "has_music": True,
                "timestamp": datetime.now().isoformat(),
            }), encoding="utf-8")
        except Exception:
            pass
    else:
        _send(f"⚠️ Baked but tiktok file missing — check output/")
    _rs_clear()


def _rs_handle_voice_received(file_id: str, st: dict):
    """Download voice note, save, send playback + Keep/Try-again buttons."""
    try:
        r        = requests.get(f"{BASE_URL}/getFile", params={"file_id": file_id}, timeout=15).json()
        tg_path  = r["result"]["file_path"]
        ext      = Path(tg_path).suffix or ".ogg"
        raw      = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{tg_path}",
                                timeout=60).content
    except Exception as e:
        _send(f"❌ Could not download voice: {e}")
        return

    slot     = st.get("slot", 2)
    recorded = BASE / "temp" / f"studio_rec_slot{slot}{ext}"
    recorded.write_bytes(raw)

    st["step"]          = "reviewing_record"
    st["recorded_path"] = str(recorded)
    _rs_save(st)

    try:
        with open(recorded, "rb") as f:
            requests.post(f"{BASE_URL}/sendAudio",
                          data={"chat_id": TELEGRAM_CHAT_ID,
                                "caption": "🎧 Your recording — how does it sound?"},
                          files={"audio": f}, timeout=60)
    except Exception:
        pass

    _send("Recording received!", reply_markup={"inline_keyboard": [[
        {"text": "✅ Keep — choose music", "callback_data": "rs_keep"},
        {"text": "🔄 Record again",        "callback_data": "rs_record_again"},
    ]]})


def _rs_bake(st: dict):
    video_path    = Path(st.get("video_path", ""))
    recorded_path = Path(st.get("recorded_path") or "")
    music_path    = st.get("music_path", "")
    trim_sec      = int(st.get("trim_seconds", 30))
    slot          = st.get("slot", 2)
    hook          = st.get("hook", "")
    has_music     = bool(music_path and Path(music_path).exists())

    if not video_path.exists():
        _send("❌ Source video not found.")
        _rs_clear()
        return
    if not recorded_path.exists():
        _send("❌ Recording file not found.")
        _rs_clear()
        return

    out_path   = video_path.with_name(video_path.stem + "_revoiced.mp4")
    tmp_silent = Path(tempfile.mktemp(suffix="_si.mp4"))
    tmp_music  = Path(tempfile.mktemp(suffix="_mu.aac"))
    tmp_audio  = Path(tempfile.mktemp(suffix="_mix.aac"))

    try:
        subprocess.run([FFMPEG, "-y", "-i", str(video_path), "-c:v", "copy", "-an", str(tmp_silent)],
                       check=True, capture_output=True)
        dur     = _get_audio_duration(str(tmp_silent))
        fade_st = max(0, dur - 2.0)

        if has_music:
            music_end  = min(float(trim_sec), dur)
            music_fade = max(0.0, music_end - 1.5)
            subprocess.run(
                [FFMPEG, "-y",
                 "-i", str(recorded_path), "-stream_loop", "-1", "-i", music_path,
                 "-filter_complex",
                 f"[1:a]atrim=end={music_end:.2f},asetpts=PTS-STARTPTS,volume=0.18,"
                 f"afade=t=out:st={music_fade:.2f}:d=1.5[m];"
                 f"[0:a][m]amix=inputs=2:duration=first:normalize=0[mx];"
                 f"[mx]afade=t=out:st={fade_st:.2f}:d=2[out]",
                 "-map", "[out]", "-t", str(dur),
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(tmp_audio)],
                check=True, capture_output=True,
            )
        else:
            subprocess.run(
                [FFMPEG, "-y", "-i", str(recorded_path),
                 "-filter_complex", f"afade=t=out:st={fade_st}:d=2",
                 "-t", str(dur), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                 str(tmp_audio)],
                check=True, capture_output=True,
            )

        subprocess.run(
            [FFMPEG, "-y", "-i", str(tmp_silent), "-i", str(tmp_audio),
             "-c:v", "copy", "-c:a", "copy", "-t", str(dur), "-movflags", "+faststart",
             str(out_path)],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode(errors="replace")[-400:]
        _send(f"❌ Bake failed:\n<code>{err}</code>")
        _rs_clear()
        return
    finally:
        for f in [tmp_silent, tmp_music, tmp_audio]:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass

    try:
        LATEST_REVOICED.write_text(json.dumps({
            "path":      str(out_path),
            "hook":      hook,
            "slot":      slot,
            "has_music": has_music,
            "timestamp": datetime.now().isoformat(),
        }), encoding="utf-8")
    except Exception:
        pass

    label      = _SLOT_LABELS.get(slot, f"Slot {slot}")
    music_note = (f"🎵 {Path(music_path).stem[:25]} ({trim_sec}s)" if has_music else "🔇 Voice only")
    _send(f"✅ Done! Sending preview…\n{music_note}")

    result = _send_video(
        out_path,
        caption=f"Re-voiced {label}\n{hook[:120]}",
        reply_markup={"inline_keyboard": [
            [
                {"text": "🚀 Post TikTok", "callback_data": f"post_revoiced_{slot}_tiktok"},
                {"text": "📸 Post IG",     "callback_data": f"post_revoiced_{slot}_ig"},
            ],
            [
                {"text": "🎤 Record again", "callback_data": f"cmd_revoice_{slot}"},
                {"text": "⏭ Done",          "callback_data": "rs_skip_studio"},
            ],
        ]},
    )

    file_id = result.get("video", {}).get("file_id")
    if file_id:
        _send(f"REVOICE_META:{json.dumps({'tg_file_id': file_id, 'slot': slot, 'hook': hook, 'has_music': has_music, 'timestamp': datetime.now().isoformat()})}")

    _rs_clear()


def _rs_set_record():
    st = _rs_load()
    if not st:
        _send("⚠️ No active studio session. Tap Re-voice from /menu first.")
        return
    hook = st.get("hook", "")
    st["step"] = "awaiting_record"
    _rs_save(st)
    script_block = f"\n\n📄 <b>Read this script:</b>\n<i>{hook}</i>" if hook else ""
    _send(
        f"🎙️ <b>HOW TO RECORD IN TELEGRAM</b>{script_block}\n\n"
        f"<b>On your phone (iOS / Android):</b>\n"
        f"• Look at the message input bar at the bottom of this chat\n"
        f"• <b>Press and HOLD the 🎤 microphone icon</b> on the right\n"
        f"• Speak your script clearly while holding\n"
        f"• <b>Release</b> the mic — the voice note sends automatically\n"
        f"• (Slide left while holding to cancel if you stumble)\n\n"
        f"<b>On Telegram Desktop (Windows/Mac):</b>\n"
        f"• Click the 🎤 mic icon once to start recording\n"
        f"• Speak your script\n"
        f"• Click the ✅ send button (or press Enter) to send\n\n"
        f"<i>Once sent, the bot plays it back here so you can approve or re-record.</i>",
        reply_markup={"inline_keyboard": [[
            {"text": "❌ Cancel — go back", "callback_data": "rs_skip_studio"},
        ]]},
    )


def _rs_keep():
    st = _rs_load()
    if not st or st.get("step") != "reviewing_record":
        _send("⚠️ Record a voice note first.")
        return
    st["step"] = "awaiting_music"
    _rs_save(st)
    total = len(_list_music_tracks())
    _send(
        f"🎵 <b>Pick your music</b> ({total} tracks available)\n"
        f"Tap ▶️ on any track to hear a 30-second preview first.",
        reply_markup=_music_page_keyboard(0, "rs"),
    )


def _rs_record_again():
    st = _rs_load()
    if not st:
        _send("⚠️ No active studio session.")
        return
    old = st.get("recorded_path")
    if old:
        try:
            Path(old).unlink(missing_ok=True)
        except Exception:
            pass
    st["step"]          = "awaiting_record"
    st["recorded_path"] = None
    _rs_save(st)
    _send("🎤 OK — send a new voice note now.")


def _rs_preview_music(idx: int):
    """Send 30s audio preview of track[idx], then show Use/Back buttons."""
    tracks = _list_music_tracks()
    if idx >= len(tracks):
        _send("⚠️ Track not found.")
        return
    track = tracks[idx]
    _send(f"⏳ Generating 30s preview of <b>{track.stem}</b>…")
    threading.Thread(target=_send_music_preview, args=(track,), daemon=True).start()
    _send(
        f"🎵 <b>{track.stem}</b>\n\nUse this track?",
        reply_markup={"inline_keyboard": [
            [
                {"text": "✅ Use this track", "callback_data": f"rs_mpick_{idx}"},
                {"text": "↩️ Back to list",   "callback_data": "rs_mshow_0"},
            ],
            [{"text": "🔇 No music",          "callback_data": "rs_music_none"}],
        ]},
    )


def _rs_confirm_music(idx: int):
    """Pick a track (after preview) and move to trim step."""
    st = _rs_load()
    if not st:
        _send("⚠️ No active studio session.")
        return
    tracks = _list_music_tracks()
    if idx >= len(tracks):
        _send("⚠️ Track not found.")
        return
    st["music_path"] = str(tracks[idx])
    st["step"]       = "awaiting_trim"
    _rs_save(st)
    _send(
        f"✅ <b>{tracks[idx].stem}</b> selected.\n\nHow long should the music play?",
        reply_markup=_trim_keyboard(),
    )


def _rs_show_music_page(page: int):
    """Navigate to a different page of the music browser."""
    total = len(_list_music_tracks())
    _send(
        f"🎵 <b>Pick your music</b> ({total} tracks)\n"
        f"Tap ▶️ to hear 30s preview before picking.",
        reply_markup=_music_page_keyboard(page, "rs"),
    )


def _ms_preview_music(idx: int):
    """Swap Music: preview track, then show Use/Back/Cancel."""
    try:
        sess = json.loads(SWAPMUSIC_SESSION.read_text(encoding="utf-8"))
    except Exception:
        _send("⚠️ No active swap session. Use Swap Music again.")
        return
    tracks = _list_music_tracks()
    if idx >= len(tracks):
        _send("⚠️ Track not found.")
        return
    track = tracks[idx]
    _send(f"⏳ Generating 30s preview of <b>{track.stem}</b>…")
    threading.Thread(target=_send_music_preview, args=(track,), daemon=True).start()
    _send(
        f"🎵 <b>{track.stem}</b>\n\nSwap to this track?",
        reply_markup={"inline_keyboard": [
            [
                {"text": "✅ Use this track", "callback_data": f"ms_pick_{idx}"},
                {"text": "↩️ Back to list",   "callback_data": "ms_mshow_0"},
            ],
            [{"text": "❌ Cancel", "callback_data": "ms_cancel"}],
        ]},
    )


def _ms_show_page(page: int):
    total = len(_list_music_tracks())
    _send(
        f"🎵 <b>Swap Music</b> ({total} tracks)\n"
        f"Tap ▶️ to hear 30s preview before picking.",
        reply_markup=_ms_keyboard(page),
    )


def _rs_music_yt():
    _send(
        "📺 <b>YouTube music</b>\n\n"
        "Send a search term or URL:\n"
        "  <code>/music lofi hip hop chill</code>\n"
        "  <code>/music https://youtu.be/...</code>\n\n"
        "<i>After download, tap Re-voice again to see the updated track list.</i>"
    )


def _rs_music_none():
    st = _rs_load()
    if not st or st.get("step") != "awaiting_music":
        return
    st["music_path"] = ""
    st["step"]       = "baking"
    _rs_save(st)
    _send("⏳ No music — baking voice only…")
    threading.Thread(target=_rs_bake, args=(st,), daemon=True).start()


def _rs_set_trim_and_bake(trim_sec: int):
    st = _rs_load()
    if not st or st.get("step") != "awaiting_trim":
        _send("⚠️ Not in trim step.")
        return
    st["trim_seconds"] = trim_sec
    st["step"]         = "baking"
    _rs_save(st)
    slot = st.get("slot", 2)
    _send(f"⏳ Baking Slot {slot} — voice + music ({trim_sec}s)… ~30 seconds")
    threading.Thread(target=_rs_bake, args=(st,), daemon=True).start()


def _rs_skip_studio():
    _rs_clear()
    _send("⏭ Studio session ended.")


# ── Standalone music swap ─────────────────────────────────────────────────────

def do_swapmusic(slot: int):
    """Swap background music on all 3 V2 platform variants without re-recording voice."""
    base  = _find_latest_v2_base(slot)
    label = _SLOT_LABELS.get(slot, f"Slot {slot}")
    if not base:
        _send(f"❌ No V2 video found for Slot {slot}. Run /rerun {slot} first.")
        return
    SWAPMUSIC_SESSION.write_text(json.dumps({
        "slot": slot, "base": base, "expires": time.time() + 1800,
    }), encoding="utf-8")
    total = len(_list_music_tracks())
    _send(
        f"🎵 <b>Music Swap — {label}</b> ({total} tracks)\n"
        f"Tap ▶️ on any track to hear a 30s preview before picking.",
        reply_markup=_ms_keyboard(0),
    )


def _ms_keyboard(page: int = 0) -> dict:
    return _music_page_keyboard(page, "ms")


def _ms_pick(idx: int):
    try:
        sess = json.loads(SWAPMUSIC_SESSION.read_text(encoding="utf-8"))
    except Exception:
        _send("⚠️ No active swap session. Use /swapmusic again."); return
    if time.time() > sess.get("expires", 0):
        _send("⚠️ Session expired. Use /swapmusic again."); return
    tracks = _list_music_tracks(4)
    if idx >= len(tracks):
        _send("⚠️ Track not found."); return
    _ms_do_swap(sess["slot"], sess["base"], tracks[idx])


def _ms_do_swap(slot: int, base: str, track: Path):
    label = _SLOT_LABELS.get(slot, f"Slot {slot}")
    _send(f"⏳ Swapping music on {label}…")
    ok_count = 0
    for platform in ["tiktok", "instagram", "youtube"]:
        vid = OUTPUT / f"{base}_{platform}.mp4"
        if not vid.exists():
            continue
        probe = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", str(vid)],
            capture_output=True, text=True,
        )
        try:
            dur = float(json.loads(probe.stdout).get("format", {}).get("duration", 15))
        except Exception:
            dur = 15.0
        fade_out = max(0.0, dur - 1.0)
        tmp = vid.with_suffix(".swaptmp.mp4")
        r = subprocess.run(
            [FFMPEG, "-y", "-i", str(vid), "-stream_loop", "-1", "-i", str(track),
             "-filter_complex",
             f"[1:a]volume=0.13,afade=t=in:st=0:d=0.5,"
             f"afade=t=out:st={fade_out:.2f}:d=0.8[mus]",
             "-map", "0:v", "-map", "[mus]",
             "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
             "-t", str(dur), "-movflags", "+faststart", str(tmp)],
            capture_output=True, timeout=60,
        )
        if tmp.exists() and tmp.stat().st_size > 50_000:
            tmp.replace(vid)
            ok_count += 1
        else:
            tmp.unlink(missing_ok=True)
    try:
        SWAPMUSIC_SESSION.unlink(missing_ok=True)
    except Exception:
        pass
    if ok_count:
        _send(f"✅ Music swapped on {ok_count}/3 {label} variants\n🎵 {track.stem}")
    else:
        _send("❌ Music swap failed — check that the V2 files still exist in output/")


# ── Kling ad text editor ──────────────────────────────────────────────────────

_KLING_TEXTS_FILE = DATA / "kling_custom_texts.json"
_KLINGTEXT_POOLS  = ("opening", "how", "cta")


def _load_kling_texts() -> dict:
    try:
        if _KLING_TEXTS_FILE.exists():
            return json.loads(_KLING_TEXTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_kling_texts(d: dict):
    _KLING_TEXTS_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def do_klingtext(args: str = ""):
    """
    /klingtext            — show all current ad texts
    /klingtext opening    — show only opening pool
    /klingtext how        — show only how-it-works pool
    /klingtext cta        — show only CTA pool
    /klingtext add opening <text>   — add a line to the opening pool
    /klingtext add how <text>       — add a line to how-it-works pool
    /klingtext add cta <text>       — add a line to CTA pool
    /klingtext clear opening        — reset pool to default
    /klingtext clear all            — reset all pools to default
    """
    from config import DATA as _DATA
    parts = args.strip().split(None, 2)
    texts = _load_kling_texts()

    # ── add opening/how/cta <text> ────────────────────────────────────────────
    if parts and parts[0] == "add" and len(parts) >= 3:
        pool, new_line = parts[1].lower(), parts[2].strip()
        if pool not in _KLINGTEXT_POOLS:
            _send(f"⚠️ Unknown pool '{pool}'. Use: opening / how / cta")
            return
        texts.setdefault(pool, []).append(new_line)
        _save_kling_texts(texts)
        _send(f"✅ Added to <b>{pool}</b>:\n<i>{new_line}</i>")
        return

    # ── clear pool ────────────────────────────────────────────────────────────
    if parts and parts[0] == "clear":
        target = parts[1].lower() if len(parts) > 1 else "all"
        if target == "all":
            _KLING_TEXTS_FILE.unlink(missing_ok=True)
            _send("✅ All ad text pools reset to defaults.")
        elif target in _KLINGTEXT_POOLS:
            texts.pop(target, None)
            if texts:
                _save_kling_texts(texts)
            else:
                _KLING_TEXTS_FILE.unlink(missing_ok=True)
            _send(f"✅ <b>{target}</b> pool reset to defaults.")
        else:
            _send(f"⚠️ Unknown pool '{target}'.")
        return

    # ── show pools ────────────────────────────────────────────────────────────
    _DEFAULT_OPENING = [
        "Already flying to Nigeria? Earn from it.",
        "Why pay £60 when a traveller charges £15?",
        "Your spare luggage space is worth money.",
        "Sending something home? There is a smarter way.",
        "Real travellers. Real savings. Real fast.",
        "The app that turns flights into deliveries.",
        "Same flight. Extra income. Zero effort.",
        "Senders meet travellers. Everyone wins.",
    ]
    _DEFAULT_HOW = [
        "Match a traveller going your way.",
        "They carry your parcel. You save 70%.",
        "Peer-to-peer delivery — UK to Nigeria.",
        "One match. Same-day agreement. Done.",
        "Already going. Already earning.",
    ]
    _DEFAULT_CTA = [
        "Download free — boothop.com",
        "Sign up today — boothop.com",
        "iOS and Android — boothop.com",
        "Join free at boothop.com",
        "Get started — boothop.com",
    ]

    show_pool = parts[0].lower() if parts else "all"

    def _fmt_pool(name: str, default: list) -> str:
        custom = texts.get(name)
        items  = custom if custom else default
        tag    = " <i>(custom)</i>" if custom else " <i>(default)</i>"
        lines  = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(items))
        return f"<b>{name.upper()}{tag}</b>\n{lines}"

    if show_pool in _KLINGTEXT_POOLS:
        defaults = {"opening": _DEFAULT_OPENING, "how": _DEFAULT_HOW, "cta": _DEFAULT_CTA}
        _send(_fmt_pool(show_pool, defaults[show_pool]))
    else:
        msg = (
            "📝 <b>Kling Ad Text Pools</b>\n\n"
            + _fmt_pool("opening", _DEFAULT_OPENING) + "\n\n"
            + _fmt_pool("how",     _DEFAULT_HOW)     + "\n\n"
            + _fmt_pool("cta",     _DEFAULT_CTA)     + "\n\n"
            "<b>Commands:</b>\n"
            "<code>/klingtext add opening Your new hook text here</code>\n"
            "<code>/klingtext add how How it works text</code>\n"
            "<code>/klingtext add cta Sign up — boothop.com</code>\n"
            "<code>/klingtext clear opening</code> — reset to defaults\n"
            "<code>/klingtext clear all</code> — reset everything"
        )
        _send(msg)


# ── Blog post from commander ──────────────────────────────────────────────────

def do_blog(slot: int):
    """Generate + post a blog article from the latest content for this slot."""
    _, data = _find_latest_video(slot)
    if not data:
        base = _find_latest_v2_base(slot)
        if base:
            try:
                data = json.loads((OUTPUT / f"{base}.json").read_text(encoding="utf-8"))
            except Exception:
                data = {}
    if not data:
        _send(f"⚠️ No content found for Slot {slot}. Run /rerun {slot} first.")
        return
    label = _SLOT_LABELS.get(slot, f"Slot {slot}")
    _send(f"📝 Generating blog post for {label}…  (~20 seconds)")
    try:
        sys.path.insert(0, str(BASE / "scripts"))
        from post_blog import post_blog
        ok = post_blog(data, slot)
        if ok:
            _send(f"✅ Blog post published!\n<i>Check your Blogger dashboard.</i>")
        else:
            _send(f"⚠️ Blog generated but Blogger post failed — HTML saved to <code>blog/pending/</code>")
    except Exception as e:
        _send(f"❌ Blog error: {e}")


def _post_revoiced(slot: int, platform: str = "tiktok"):
    if not LATEST_REVOICED.exists():
        _send("⚠️ No revoiced video found. Use Re-voice from /menu first.")
        return
    try:
        info = json.loads(LATEST_REVOICED.read_text(encoding="utf-8"))
    except Exception:
        _send("⚠️ Could not read revoiced info.")
        return
    path = Path(info.get("path", ""))
    if not path.exists():
        _send(f"❌ Revoiced file not found: <code>{path.name}</code>")
        return

    plat_name = "TikTok" if platform == "tiktok" else "Instagram"
    hook      = info.get("hook", "")
    content   = {
        "hook":               hook,
        "caption_tiktok":     hook[:300],
        "caption_instagram":  hook[:300],
        "pillar":             "revoice",
        "lesson":             "",
        "stakes":             "",
    }
    _send(f"🚀 Posting revoiced Slot {slot} to {plat_name}…")
    try:
        sys.path.insert(0, str(BASE / "scripts"))
        if platform == "tiktok":
            from post_tiktok import post_video
            result = post_video(str(path), content, slot)
            _send(f"✅ Posted to TikTok! {result or ''}")
        else:
            from post_instagram import post_video as post_ig
            result = post_ig(str(path), content, slot)
            _send(f"✅ Posted to Instagram! {result or ''}")
    except Exception as e:
        _send(f"❌ Post error: {e}")


# ── Pending queue: newspaper / story / LinkedIn ───────────────────────────────

def _do_newspaper(dest: str):
    if not PENDING_NEWSPAPER.exists():
        _send("⚠️ No pending newspaper found.")
        return
    try:
        info = json.loads(PENDING_NEWSPAPER.read_text(encoding="utf-8"))
    except Exception:
        _send("⚠️ Could not read newspaper pending file.")
        return

    edition  = info.get("edition", "?")
    sent, failed = [], []

    for flag, label, arg in [
        (dest in ("ig", "both"),  "Instagram", "--post-ig"),
        (dest in ("tt", "both"),  "TikTok",    "--post-tt"),
    ]:
        if not flag:
            continue
        _send(f"📰 Posting Newspaper Ed.{edition} to {label}…")
        result = subprocess.run(
            [PYTHON, str(BASE / "scripts" / "post_newspaper.py"), arg],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            sent.append(label)
        else:
            failed.append(f"{label}: <code>{result.stderr[-150:]}</code>")

    if sent:
        _send(f"✅ Newspaper Ed.{edition} posted to {' + '.join(sent)}!")
    for err in failed:
        _send(f"❌ Post failed — {err}")
    if not failed:
        PENDING_NEWSPAPER.unlink(missing_ok=True)


def _skip_newspaper():
    PENDING_NEWSPAPER.unlink(missing_ok=True)
    _send("⏭ Newspaper skipped.")


def _do_story_post():
    if not PENDING_STORY.exists():
        _send("⚠️ No pending story found.")
        return
    try:
        info = json.loads(PENDING_STORY.read_text(encoding="utf-8"))
    except Exception:
        _send("⚠️ Could not read story pending file.")
        return
    slot = info.get("slot", "story")
    _send(f"📱 Posting {slot.title()} Story to Instagram…")
    result = subprocess.run(
        [PYTHON, str(BASE / "scripts" / "post_stories.py"), "--post-ig"],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode == 0:
        _send("✅ Story posted to Instagram!")
        PENDING_STORY.unlink(missing_ok=True)
    else:
        _send(f"❌ Story failed:\n<code>{result.stderr[-200:]}</code>")


def _skip_story():
    PENDING_STORY.unlink(missing_ok=True)
    _send("⏭ Story skipped.")


def _do_linkedin_post():
    if not PENDING_LINKEDIN.exists():
        _send("⚠️ No pending LinkedIn post found.")
        return
    try:
        info = json.loads(PENDING_LINKEDIN.read_text(encoding="utf-8"))
    except Exception:
        _send("⚠️ Could not read LinkedIn pending file.")
        return
    video_path   = info.get("video_path", "")
    caption_file = info.get("caption_file", "")
    _send("🚀 Posting to LinkedIn…")
    result = subprocess.run(
        [PYTHON, str(BASE / "scripts" / "post_linkedin.py"),
         "--video", video_path, "--caption-file", caption_file],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode == 0:
        _send("✅ Posted to LinkedIn!")
        PENDING_LINKEDIN.unlink(missing_ok=True)
    else:
        _send(f"❌ LinkedIn failed:\n<code>{result.stderr[-200:]}</code>")


def _skip_linkedin():
    PENDING_LINKEDIN.unlink(missing_ok=True)
    _send("⏭ LinkedIn post skipped.")


# ── Pause / Resume ────────────────────────────────────────────────────────────

_PIPELINES = {
    "boothop": {
        "label":         "BootHop",
        "local_profile": BASE / "client_profile.json",
        "oracle_profile": "/opt/otb_pipeline/client_profile.json",
        "tasks":         [],
    },
    "g_inspired": {
        "label":         "G-Inspired",
        "local_profile": BASE.parent / "g_inspired" / "client_profile.json",
        "oracle_profile": "/opt/g_inspired/client_profile.json",
        "tasks":         [],
    },
    "newsflash": {
        "label":         "NewsFlash",
        "local_profile": None,
        "oracle_profile": None,
        "tasks":         ["OTB-NewsFlash"],
    },
    "d818": {
        "label":         "D818",
        "local_profile": None,
        "oracle_profile": None,
        "tasks":         ["D818-Morning", "D818-Afternoon", "D818-Evening",
                          "D818-Weekend", "D818-Weekly", "D818-ApprovalCheck"],
    },
}
_NEWSFLASH_TASK = "OTB-NewsFlash"


def _set_profile_active(path, active: bool):
    if path is None or not Path(path).exists():
        return
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    p.setdefault("schedule", {})["active"] = active
    Path(path).write_text(json.dumps(p, indent=2), encoding="utf-8")


def _set_oracle_profile_active(oracle_path: str, active: bool) -> str:
    if not oracle_path:
        return "skipped"
    val = "true" if active else "false"
    cmd = [
        "ssh", "-i", str(ORACLE_KEY), "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10", f"{ORACLE_USER}@{ORACLE_IP}",
        f"python3 -c \"import json; p=json.load(open('{oracle_path}')); "
        f"p.setdefault('schedule', {{}})['active']={val}; "
        f"json.dump(p, open('{oracle_path}','w'), indent=2); print('ok')\""
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return "ok" if r.returncode == 0 else r.stderr.strip()[:80]
    except Exception as e:
        return str(e)[:80]


def _set_tasks(task_names: list, enable: bool):
    action = "Enable" if enable else "Disable"
    for name in task_names:
        try:
            subprocess.run(
                ["powershell", "-Command",
                 f"{action}-ScheduledTask -TaskName '{name}'"],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass


def _pause_resume_pipeline(pipeline_key: str, active: bool):
    done  = "resumed" if active else "paused"
    icon  = "▶️" if active else "⏸"
    keys  = list(_PIPELINES.keys()) if pipeline_key == "all" else [pipeline_key]
    lines = [f"<b>{icon} {done.capitalize()}…</b>"]

    for key in keys:
        cfg   = _PIPELINES[key]
        label = cfg["label"]
        if cfg["tasks"]:
            _set_tasks(cfg["tasks"], active)
            lines.append(f"• {label} tasks — {done}")
        else:
            _set_profile_active(cfg["local_profile"], active)
            lines.append(f"• {label} local — {done}")
            ores  = _set_oracle_profile_active(cfg["oracle_profile"], active)
            ostat = "✅" if ores == "ok" else f"⚠️ {ores}"
            lines.append(f"• {label} Oracle — {ostat}")

    hint = "Send <b>resume</b> or tap ▶️ Resume to restart." if not active else "Next run at the next scheduled slot."
    lines.append(f"\n{hint}")
    _send("\n".join(lines), reply_markup=_control_panel_keyboard())


def _pause_picker_keyboard(action: str) -> dict:
    icon = "⏸" if action == "pause" else "▶️"
    return {
        "inline_keyboard": [
            [
                {"text": f"{icon} BootHop",    "callback_data": f"cmd_{action}_boothop"},
                {"text": f"{icon} G-Inspired", "callback_data": f"cmd_{action}_g_inspired"},
            ],
            [
                {"text": f"{icon} NewsFlash",  "callback_data": f"cmd_{action}_newsflash"},
                {"text": f"{icon} D818",       "callback_data": f"cmd_{action}_d818"},
            ],
            [
                {"text": f"{icon} All",        "callback_data": f"cmd_{action}_all"},
            ],
        ]
    }


def do_pause_picker():
    _send("Which pipeline to pause?", reply_markup=_pause_picker_keyboard("pause"))


def do_resume_picker():
    _send("Which pipeline to resume?", reply_markup=_pause_picker_keyboard("resume"))


def do_pause(pipeline: str = "all"):
    _pause_resume_pipeline(pipeline, False)


def do_resume(pipeline: str = "all"):
    _pause_resume_pipeline(pipeline, True)


# ── Main commands ─────────────────────────────────────────────────────────────


def do_menu():
    _send(
        "<b>OTB Control Panel</b>\n\nTap a button:",
        reply_markup=_control_panel_keyboard(),
    )


def do_status():
    log_path   = DATA / "post_log.json"
    crash_path = DATA / "pipeline_crash.log"
    step_path  = DATA / "pipeline_step.txt"
    today      = datetime.now().strftime("%Y-%m-%d")

    posts_today = []
    try:
        log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
        posts_today = [e for e in log if e.get("posted_at", "").startswith(today)]
    except Exception:
        pass

    last_log = ""
    try:
        lines = crash_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        for line in reversed(lines):
            if line.strip():
                last_log = line.strip()
                break
    except Exception:
        last_log = "unavailable"

    step = ""
    try:
        if step_path.exists():
            step = step_path.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    platforms = [f"{e['platform']}:{e.get('slot','?')}" for e in posts_today]

    # Query bank stats
    bank_line = ""
    try:
        sys.path.insert(0, str(BASE / "scripts"))
        from query_learner import bank_stats
        bank_line = "\n\n" + bank_stats()
    except Exception:
        pass

    lines = [
        f"<b>OTB Status</b>  {datetime.now().strftime('%H:%M')}",
        f"<i>Instance: {INSTANCE}</i>",
        f"",
        f"Posts today: {len(posts_today)}",
        f"{', '.join(platforms) or 'none yet'}",
        f"Last log: <code>{last_log[-80:]}</code>",
    ]
    if step:
        lines.append(f"Current step: <code>{step[-60:]}</code>")
    if bank_line:
        lines.append(bank_line)

    _send("\n".join(lines), reply_markup=_control_panel_keyboard())


def do_rerun(slot: int = None, version: str = None):
    if slot is None:
        _send(
            "Which slot to rerun?",
            reply_markup={"inline_keyboard": [[
                {"text": "S1 — 7am",  "callback_data": "cmd_rerun_1"},
                {"text": "S2 — 9am",  "callback_data": "cmd_rerun_2"},
                {"text": "S3 — 6pm",  "callback_data": "cmd_rerun_3"},
                {"text": "S4 — 9pm",  "callback_data": "cmd_rerun_4"},
            ]]},
        )
        return
    ver_label = f" ({version.upper()})" if version else ""
    _send(f"🔄 Rerunning Slot {slot}{ver_label}…\nThis takes ~10 minutes. Watch for the preview.")
    try:
        cmd = [PYTHON, str(BASE / "pipeline.py"), "--slot", str(slot), "--force"]
        if version:
            cmd += ["--version", version]
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        # Launch Claude Code monitor in background — watches for errors and auto-fixes
        monitor = Path(__file__).parent / "_rerun_monitor.py"
        subprocess.Popen(
            [PYTHON, str(monitor), str(slot), str(proc.pid)],
            cwd=str(BASE),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        _send(f"❌ Failed to start pipeline: {e}")


def do_force_version(slot: int, version: str):
    """Force a specific version (v1 or v2) for the next slot run."""
    from pathlib import Path as _P
    state_path = BASE / "data" / "version_state.json"
    try:
        state = {}
        if state_path.exists():
            import json as _j
            state = _j.loads(state_path.read_text(encoding="utf-8"))
        state[f"slot{slot}"] = {
            "last_version":   "v1" if version == "v2" else "v2",
            "last_posted_at": "2000-01-01T00:00:00",  # force grace window to be expired
            "next_version":   version,
        }
        state_path.write_text(__import__("json").dumps(state, indent=2), encoding="utf-8")
        _send(f"✅ Slot {slot} forced to {version.upper()} for next run.\nSend /rerun {slot} to run it now.")
    except Exception as e:
        _send(f"❌ Could not update version state: {e}")


def do_story(slot_label: str = "pm"):
    label = "afternoon" if "pm" in slot_label or "1pm" in slot_label else "evening"
    _send(f"📱 Generating {label} story…")
    try:
        result = subprocess.run(
            [PYTHON, str(BASE / "scripts" / "post_stories.py"), "--slot", label],
            cwd=str(BASE), capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0:
            _send(f"✅ {label.title()} story sent to Instagram.")
        else:
            _send(f"❌ Story failed:\n<code>{result.stderr[-300:]}</code>")
    except Exception as e:
        _send(f"❌ Story error: {e}")


def _normalise_music_query(raw: str) -> str:
    """
    Convert a freetext music request into a yt-dlp target.
    Accepts: URLs, song names, artist names, songwriter credit, lyrics snippets.
    """
    raw = raw.strip()
    if not raw:
        return ""
    if raw.lower().startswith("http"):
        return raw
    low = raw.lower()
    # Strip intent prefixes — keep the meaningful part
    for prefix in (
        "lyrics: ", "lyrics:", "lyrics ",
        "written by ", "songwriter: ", "songwriter ",
        "by ", "artist: ", "artist ",
        "song: ", "song ", "track: ", "track ",
        "singer: ", "singer ",
    ):
        if low.startswith(prefix):
            raw = raw[len(prefix):].strip()
            low = raw.lower()
            break
    # Add "official audio" if the query has no music-specific qualifier,
    # so yt-dlp returns a proper music result rather than a random video.
    if not any(w in low for w in (
        "music", "official", "lyrics", "audio", "song", "feat", "ft.", "remix", "mix"
    )):
        raw = raw + " official audio"
    return f"ytsearch1:{raw}"


def do_music(query: str):
    if not query.strip():
        _send(
            "🎵 <b>Music download</b>\n\n"
            "Search by <b>anything</b> — all of these work:\n"
            "  <code>/music Shape of You</code>\n"
            "  <code>/music by Ed Sheeran</code>\n"
            "  <code>/music written by Pharrell Williams</code>\n"
            "  <code>/music we found love in a hopeless place</code>\n"
            "  <code>/music lofi chill hip hop</code>\n"
            "  <code>/music https://youtu.be/...</code>\n\n"
            "Track is trimmed to 60s and saved to your music library."
        )
        return

    import re as _re
    target   = _normalise_music_query(query)
    display  = query if query.startswith("http") else f'"{query}"'
    _send(f"⬇️ Searching: <i>{display}</i>  (~15–30 seconds…)")

    try:
        dl_dir = BASE / "music" / "yt_downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        safe     = _re.sub(r"[^\w\-]", "_", query[:38]).strip("_") or "yt_track"
        raw_tmpl = str(dl_dir / f"{safe}_raw.%(ext)s")
        final    = dl_dir / f"{safe}_0s.mp3"

        r = subprocess.run(
            ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3",
             "--audio-quality", "0", "--output", raw_tmpl, "--no-warnings", target],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            _send(f"❌ yt-dlp failed:\n<code>{r.stderr[-300:]}</code>")
            return

        raws = sorted(dl_dir.glob(f"{safe}_raw.*"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not raws:
            _send("❌ Download completed but no file found.")
            return

        import shutil as _sh
        _sh.which("ffmpeg") or "ffmpeg"
        subprocess.run(
            [FFMPEG, "-y", "-i", str(raws[0]), "-ss", "0", "-t", "60",
             "-c:a", "libmp3lame", "-q:a", "2", "-ar", "48000", "-ac", "2", str(final)],
            check=True, capture_output=True, timeout=60,
        )
        try:
            raws[0].unlink(missing_ok=True)
        except Exception:
            pass

        # Update pending revoice session's music if one is active
        updated = False
        if PENDING_REVOICE.exists():
            try:
                pending = json.loads(PENDING_REVOICE.read_text(encoding="utf-8"))
                if pending.get("expires", 0) > time.time():
                    pending["music_path"] = str(final)
                    PENDING_REVOICE.write_text(json.dumps(pending), encoding="utf-8")
                    updated = True
            except Exception:
                pass

        extra = "🎵 Updated pending revoice session!" if updated else "💾 Saved to music/yt_downloads/"
        _send(f"✅ <b>Downloaded:</b> <code>{final.name}</code>\n\n{extra}\n\nUse /revoice to start a bake session.")

    except Exception as e:
        _send(f"❌ Music download error: {e}")


def _load_edit_session() -> dict:
    try:
        if EDIT_SESSION_FILE.exists():
            d = json.loads(EDIT_SESSION_FILE.read_text(encoding="utf-8"))
            if time.time() < d.get("expires", 0):
                return d
            EDIT_SESSION_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return {}


def _save_edit_session(session: dict):
    session.setdefault("expires", time.time() + 1800)
    EDIT_SESSION_FILE.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")


def do_edit(slot: int):
    """Show current beats for this slot and open an edit session."""
    _, data = _find_latest_video(slot)
    if not data:
        _send(f"⚠️ No rendered content found for Slot {slot}. Run /rerun {slot} first.")
        return

    hook       = data.get("hook",       "(not available)")
    problem    = data.get("problem",    "(not available)")
    stakes     = data.get("stakes",     "(not available)")
    resolution = data.get("resolution", "(not available)")
    lesson     = data.get("lesson",     "(not available)")

    _save_edit_session({"slot": slot, "content": data, "expires": time.time() + 1800})

    _send(
        f"✏️ <b>Edit Slot {slot} — current beats</b>\n\n"
        f"<b>HOOK</b>\n<i>{hook}</i>\n\n"
        f"<b>PROBLEM</b>\n<i>{problem}</i>\n\n"
        f"<b>STAKES</b>\n<i>{stakes}</i>\n\n"
        f"<b>RESOLUTION</b>\n<i>{resolution}</i>\n\n"
        f"<b>LESSON</b>\n<i>{lesson}</i>\n\n"
        f"Reply with the field name and your text:\n"
        f"<code>hook: The wedding was on Saturday. The dress was still in Birmingham.</code>\n"
        f"<code>lesson: The flight was already going. The parcel just needed a seat.</code>\n\n"
        f"One field at a time. Tap <b>Done — Re-render</b> when finished.",
        reply_markup={"inline_keyboard": [[
            {"text": "✅ Done — Re-render", "callback_data": f"edit_done_{slot}"},
            {"text": "❌ Cancel",           "callback_data": f"edit_cancel_{slot}"},
        ]]},
    )


def _apply_edit_field(field: str, value: str, slot: int, session: dict):
    """Apply one field edit to the active session and confirm."""
    _FIELD_LABELS = {
        "hook": "HOOK", "problem": "PROBLEM", "stakes": "STAKES",
        "resolution": "RESOLUTION", "lesson": "LESSON",
        "caption_tiktok": "TIKTOK CAPTION", "caption_instagram": "IG CAPTION",
    }
    session.setdefault("content", {})[field] = value
    session["expires"] = time.time() + 1800
    _save_edit_session(session)
    label = _FIELD_LABELS.get(field, field.upper())
    _send(
        f"✅ <b>{label}</b> updated:\n<i>{value}</i>\n\n"
        f"Edit another field or tap <b>Done — Re-render</b>."
    )


def _edit_done(slot: int):
    """Write pending_edit file so poll_for_decision picks it up and triggers re-render."""
    session = _load_edit_session()
    if not session or session.get("slot") != slot:
        _send(f"⚠️ No active edit session for Slot {slot}. Tap ✏️ Edit from the preview first.")
        return

    content = session.get("content", {})
    pending = DATA / f"pending_edit_{slot}.json"
    pending.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    EDIT_SESSION_FILE.unlink(missing_ok=True)
    _send(
        f"✏️ <b>Slot {slot} — edits saved.</b>\n\n"
        f"Re-rendering now — skip the AI stages so this takes ~5 minutes.\n"
        f"Watch for the updated preview."
    )


def _edit_cancel(slot: int):
    EDIT_SESSION_FILE.unlink(missing_ok=True)
    _send(f"❌ Edit cancelled — original content unchanged.")


def _check_and_rerun():
    today   = datetime.now().strftime("%Y-%m-%d")
    ran_log = DATA / "pipeline_ran_today.json"
    try:
        ran = json.loads(ran_log.read_text()) if ran_log.exists() else {}
        slots_ran = ran.get(today, [])
    except Exception:
        slots_ran = []

    if slots_ran:
        _send(
            f"✅ Pipeline ran today — slots: {slots_ran}\n\nSend /rerun to force a fresh run.",
            reply_markup=_control_panel_keyboard(),
        )
    else:
        _send("⚠️ No slots ran today. Which one should I start?",
              reply_markup=_slot_picker_keyboard("cmd_rerun"))


# ── Approval flow (called by pipeline.py during slot run) ────────────────────

def send_video_preview(video_path: str, caption: str, slot: int, content: dict,
                       v2_path: str | None = None) -> int | None:
    """Send V1 + V2 video previews to Telegram with Post / Skip / Regen buttons."""
    pillar   = content.get("pillar", "")
    tags_311 = content.get("hashtags_311", [])
    hashtag_line = " ".join(tags_311) if tags_311 else content.get("hashtags_tiktok", "")[:80]

    # Send V1 video (no buttons — just the video + label)
    v1_caption = (
        f"<b>OTB Slot {slot} — V1</b>  {pillar.upper()}\n"
        f"<b>Hook:</b> {content.get('hook', '')}\n"
        f"<b>Lesson:</b> {content.get('lesson', '')}\n"
        f"<i>Gold palette — TikTok V1 + Instagram V1</i>"
    )
    try:
        with open(video_path, "rb") as vf:
            r1 = requests.post(
                f"{BASE_URL}/sendVideo",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": v1_caption,
                      "parse_mode": "HTML", "supports_streaming": "true"},
                files={"video": vf}, timeout=120,
            )
        if r1.ok:
            _log_message(r1.json().get("result", {}).get("message_id", 0))
    except Exception as e:
        print(f"[Cmdr] V1 preview failed: {e}")

    # Send V2 video if available (also no buttons)
    if v2_path:
        v2_caption = (
            f"<b>OTB Slot {slot} — V2</b>  {pillar.upper()}\n"
            f"<b>Hook:</b> {content.get('hook_v2', content.get('hook', ''))}\n"
            f"<b>Lesson:</b> {content.get('lesson_v2', content.get('lesson', ''))}\n"
            f"<i>Cyan palette — TikTok V2 + Instagram V2</i>"
        )
        try:
            with open(v2_path, "rb") as vf:
                r2 = requests.post(
                    f"{BASE_URL}/sendVideo",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": v2_caption,
                          "parse_mode": "HTML", "supports_streaming": "true"},
                    files={"video": vf}, timeout=120,
                )
            if r2.ok:
                _log_message(r2.json().get("result", {}).get("message_id", 0))
        except Exception as e:
            print(f"[Cmdr] V2 preview failed: {e}")

    # Approval message with buttons — sent as a text message after both videos
    v2_note = "V1 (gold) + V2 (cyan) ready." if v2_path else "V1 only (V2 render failed)."
    approval_text = (
        f"<b>OTB Slot {slot}</b> — {v2_note}\n\n"
        f"<b>Hashtags (3-1-1):</b>\n<code>{hashtag_line}</code>\n\n"
        f"<i>Auto-posts in 30 min — tap Post Now to go live immediately, or Skip/Regen.</i>"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Post Now",  "callback_data": f"post_{slot}"},
                {"text": "⏭ Skip",      "callback_data": f"skip_{slot}"},
            ],
            [
                {"text": "🔄 Regen",    "callback_data": f"regen_{slot}"},
                {"text": "✏️ Edit text", "callback_data": f"edit_pick_{slot}"},
            ],
        ]
    }
    msg = _send(approval_text, keyboard)
    return msg.get("result", {}).get("message_id")


def poll_for_decision(slot: int, timeout_sec: int = 20 * 60) -> str:
    """
    Poll for Post / Skip / Regen decision on this slot.
    Returns "post" | "skip" | "regen" | "timeout"

    If the commander process is running, it owns the Telegram update queue — we
    must NOT poll Telegram here or we race it and steal callbacks it needs.
    Instead we write a pending_approval file and the commander writes
    web_approval_{slot}.json when it receives the button tap.
    """
    start             = time.time()
    offset            = _load_offset()
    cmdr_running      = _is_commander_running()
    print(
        f"[Cmdr] Polling for Slot {slot} decision ({timeout_sec//60}min window) "
        f"— commander {'RUNNING (file mode)' if cmdr_running else 'not running (TG mode)'}…"
    )
    _pa = DATA / f"pending_approval_{slot}.json"
    _pa.write_text(json.dumps({"slot": slot, "since": datetime.now().isoformat()}),
                   encoding="utf-8")

    while time.time() - start < timeout_sec:
        # File-based edit signal — set by _edit_done() or web dashboard
        pending_edit = DATA / f"pending_edit_{slot}.json"
        if pending_edit.exists():
            _pa.unlink(missing_ok=True)
            print(f"[Cmdr] Edit file detected for Slot {slot} — triggering re-render")
            return "edit"

        # Web dashboard approval signal — written by /api/pipeline/approve
        web_approval = DATA / f"web_approval_{slot}.json"
        if web_approval.exists():
            try:
                d = json.loads(web_approval.read_text(encoding="utf-8"))
                decision = d.get("decision", "")
                web_approval.unlink(missing_ok=True)
                if decision in ("post", "skip", "regen", "edit"):
                    _pa.unlink(missing_ok=True)
                    print(f"[Cmdr] Web dashboard decision: {decision} (Slot {slot})")
                    _send(f"🌐 Slot {slot} — web dashboard: {decision}")
                    return decision
            except Exception:
                web_approval.unlink(missing_ok=True)

        # Supabase cloud command — from web dashboard or Commander portal
        try:
            from push_pipeline_state import poll_pending_commands, mark_command_done, clear_slot_pending
            cmds = poll_pending_commands(slot)
            for cmd in cmds:
                decision = cmd.get("command", "")
                cmd_id   = cmd.get("id")
                if decision in ("post", "skip", "regen", "edit"):
                    if decision == "edit":
                        edit_fields = cmd.get("edit_fields") or {}
                        if edit_fields:
                            p = DATA / f"pending_edit_{slot}.json"
                            existing: dict = {}
                            if p.exists():
                                try:
                                    existing = json.loads(p.read_text(encoding="utf-8"))
                                except Exception:
                                    pass
                            existing.update(edit_fields)
                            p.write_text(json.dumps(existing, indent=2), encoding="utf-8")
                    mark_command_done(cmd_id)
                    clear_slot_pending(slot)
                    _pa.unlink(missing_ok=True)
                    print(f"[Cmdr] Supabase command: {decision} (Slot {slot}, id={cmd_id})")
                    _send(f"🌐 Slot {slot} — web commander: {decision}")
                    return decision
        except ImportError:
            pass
        except Exception as _se:
            print(f"[Cmdr] Supabase poll error: {_se}")

        # Only poll Telegram directly if the commander is NOT running.
        # If it IS running, it owns the update queue — let it write web_approval files.
        if cmdr_running:
            time.sleep(5)
            continue

        try:
            r = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"offset": offset, "timeout": 20, "allowed_updates": ["callback_query"]},
                timeout=30,
            )
            updates = r.json().get("result", [])
        except Exception as e:
            print(f"[Cmdr] Poll error: {e}")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            _save_offset(offset)
            cb   = upd.get("callback_query", {})
            data = cb.get("data", "")
            try:
                requests.post(f"{BASE_URL}/answerCallbackQuery",
                              json={"callback_query_id": cb.get("id", "")}, timeout=5)
            except Exception:
                pass

            if data == f"post_{slot}":
                _pa.unlink(missing_ok=True)
                _send(f"✅ Slot {slot} — posting now!")
                return "post"
            elif data == f"skip_{slot}":
                _pa.unlink(missing_ok=True)
                _send(f"⏭ Slot {slot} — skipped.")
                return "skip"
            elif data == f"regen_{slot}":
                _pa.unlink(missing_ok=True)
                _send(f"🔄 Slot {slot} — regenerating…")
                return "regen"

    _pa.unlink(missing_ok=True)
    print(f"[Cmdr] Slot {slot} — 30 min elapsed, auto-posting.")
    _send(f"⏱ Slot {slot} — 30 min window passed, posting V1 + V2 now.")
    return "timeout"


_RESULT_LABELS = {
    "tiktok_v1":       "TikTok V1",
    "tiktok_v2":       "TikTok V2",
    "instagram_v1":    "Instagram V1",
    "instagram_v2":    "Instagram V2",
    "youtube":         "YouTube Shorts",
    "linkedin":        "LinkedIn",
    "instagram_story": "IG Story",
    "newspaper":       "Newspaper",
    "blog":            "Blog",
}


def send_result(slot: int, results: dict, content: dict = None):
    """Send post-slot results summary to Telegram."""
    lines = [f"<b>OTB Slot {slot} — Results</b>"]
    if content:
        hook = content.get("hook", "")[:120]
        if hook:
            lines.append(f"🎯 <i>{hook}</i>")
        lines.append("")
    for platform, result in results.items():
        icon  = "✅" if result else "❌"
        label = _RESULT_LABELS.get(platform, platform.replace("_", " ").title())
        if result and result not in ("posted", "failed"):
            lines.append(f"{icon} {label}: <code>{result}</code>")
        else:
            lines.append(f"{icon} {label}: {'posted' if result else 'failed'}")
    _send("\n".join(lines))


# ── Control panel keyboard ────────────────────────────────────────────────────

def _control_panel_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "⏸ Pause…",            "callback_data": "cmd_pause_pick"},
                {"text": "▶️ Resume…",           "callback_data": "cmd_resume_pick"},
            ],
            [
                {"text": "📊 Status",          "callback_data": "cmd_status"},
                {"text": "🔄 Re-run Slot…",    "callback_data": "cmd_rerun_pick"},
            ],
            [
                {"text": "🎤 Re-voice S1",     "callback_data": "cmd_revoice_1"},
                {"text": "🎤 Re-voice S3",     "callback_data": "cmd_revoice_3"},
                {"text": "🎤 Re-voice S4",     "callback_data": "cmd_revoice_4"},
            ],
            [
                {"text": "📱 Story (1pm)",     "callback_data": "cmd_story_pm"},
                {"text": "📱 Story (8:30pm)",  "callback_data": "cmd_story_eve"},
            ],
            [
                {"text": "🎵 Swap Music S1",  "callback_data": "cmd_swapmusic_1"},
                {"text": "🎵 Swap Music S3",  "callback_data": "cmd_swapmusic_3"},
                {"text": "🎵 Swap Music S4",  "callback_data": "cmd_swapmusic_4"},
            ],
            [
                {"text": "📝 Blog S1",         "callback_data": "cmd_blog_1"},
                {"text": "📝 Blog S4",         "callback_data": "cmd_blog_4"},
                {"text": "🎵 Get Music (YT)",  "callback_data": "cmd_music_prompt"},
            ],
            [
                {"text": "📈 Weekly Report",   "callback_data": "cmd_report"},
            ],
        ]
    }


# ── Command map (static callbacks) ────────────────────────────────────────────

_CMD_MAP = {
    "cmd_pause_pick":           lambda: do_pause_picker(),
    "cmd_resume_pick":          lambda: do_resume_picker(),
    "cmd_pause_boothop":        lambda: do_pause("boothop"),
    "cmd_pause_g_inspired":     lambda: do_pause("g_inspired"),
    "cmd_pause_newsflash":      lambda: do_pause("newsflash"),
    "cmd_pause_d818":           lambda: do_pause("d818"),
    "cmd_pause_all":            lambda: do_pause("all"),
    "cmd_resume_boothop":       lambda: do_resume("boothop"),
    "cmd_resume_g_inspired":    lambda: do_resume("g_inspired"),
    "cmd_resume_newsflash":     lambda: do_resume("newsflash"),
    "cmd_resume_d818":          lambda: do_resume("d818"),
    "cmd_resume_all":           lambda: do_resume("all"),
    "cmd_status":               lambda: do_status(),
    "cmd_rerun_pick":    lambda: do_rerun(None),
    "cmd_rerun_1":       lambda: do_rerun(1),
    "cmd_rerun_2":       lambda: do_rerun(2),
    "cmd_rerun_3":       lambda: do_rerun(3),
    "cmd_rerun_4":       lambda: do_rerun(4),
    # V1 / V2 version override buttons
    "cmd_v1_1":  lambda: (do_force_version(1, "v1"), do_rerun(1, version="v1")),
    "cmd_v1_2":  lambda: (do_force_version(2, "v1"), do_rerun(2, version="v1")),
    "cmd_v1_3":  lambda: (do_force_version(3, "v1"), do_rerun(3, version="v1")),
    "cmd_v2_1":  lambda: (do_force_version(1, "v2"), do_rerun(1, version="v2")),
    "cmd_v2_2":  lambda: (do_force_version(2, "v2"), do_rerun(2, version="v2")),
    "cmd_v2_3":  lambda: (do_force_version(3, "v2"), do_rerun(3, version="v2")),
    "cmd_story_pm":      lambda: do_story("pm"),
    "cmd_story_eve":     lambda: do_story("evening"),
    "cmd_music_prompt":  lambda: do_music(""),
    "cmd_report":        lambda: _do_weekly_report(),
    # Newspaper approval
    "news_ig":           lambda: _do_newspaper("ig"),
    "news_tt":           lambda: _do_newspaper("tt"),
    "news_both":         lambda: _do_newspaper("both"),
    "news_skip":         lambda: _skip_newspaper(),
    # Story approval
    "story_post":        lambda: _do_story_post(),
    "story_skip":        lambda: _skip_story(),
    # LinkedIn approval
    "li_post":           lambda: _do_linkedin_post(),
    "li_skip":           lambda: _skip_linkedin(),
    # Revoice Studio
    "rs_record":         lambda: _rs_set_record(),
    "rs_keep":           lambda: _rs_keep(),
    "rs_record_again":   lambda: _rs_record_again(),
    "rs_music_yt":       lambda: _rs_music_yt(),
    "rs_music_none":     lambda: _rs_music_none(),
    "rs_trim_15":        lambda: _rs_set_trim_and_bake(15),
    "rs_trim_30":        lambda: _rs_set_trim_and_bake(30),
    "rs_trim_45":        lambda: _rs_set_trim_and_bake(45),
    "rs_skip_studio":    lambda: _rs_skip_studio(),
    "rs_noop":           lambda: None,
    # Music swap
    "ms_music_yt":   lambda: do_music(""),
    "ms_music_none": lambda: (SWAPMUSIC_SESSION.unlink(missing_ok=True), _send("❌ No music — swap cancelled.")),
    "ms_cancel":     lambda: (SWAPMUSIC_SESSION.unlink(missing_ok=True), _send("❌ Swap cancelled.")),
}


def _do_weekly_report():
    try:
        sys.path.insert(0, str(BASE / "scripts"))
        from performance_tracker import weekly_report_text
        _send(weekly_report_text())
    except Exception as e:
        _send(f"❌ Report error: {e}")


# ── Text + callback dispatcher ────────────────────────────────────────────────

def dispatch(text_lower: str):
    if text_lower.startswith("/menu") or any(w in text_lower for w in ("menu", "help", "commands", "options")):
        do_menu()

    elif text_lower.startswith("/pause") or any(w in text_lower for w in ("pause", "stop pipeline", "halt pipeline", "pause pipeline", "pause all", "stop all", "pause everything")):
        do_pause_picker()

    elif text_lower.startswith("/resume") or any(w in text_lower for w in ("resume", "start pipeline", "resume pipeline", "resume all", "unpause", "turn on pipeline", "restart pipeline")):
        do_resume_picker()

    elif text_lower.startswith("/status") or any(w in text_lower for w in ("status", "what's running", "whats running", "how's it", "hows it")):
        do_status()

    elif text_lower.startswith("/rerun"):
        parts = text_lower.split()
        slot  = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
        if slot and slot not in (1, 2, 3, 4):
            _send("Usage: /rerun 1|2|3|4")
            return
        do_rerun(slot)

    elif text_lower.startswith("/v1") or text_lower.startswith("/v2"):
        # /v1 [slot]  or  /v2 [slot]  — force a version for the next run
        ver   = "v1" if text_lower.startswith("/v1") else "v2"
        parts = text_lower.split()
        slot  = None
        for p in parts[1:]:
            if p.isdigit() and int(p) in (1, 2, 3):
                slot = int(p)
                break
        if slot is None:
            _send(
                f"Which slot should run as {ver.upper()}?",
                reply_markup={"inline_keyboard": [[
                    {"text": "Slot 1", "callback_data": f"cmd_{ver}_1"},
                    {"text": "Slot 2", "callback_data": f"cmd_{ver}_2"},
                    {"text": "Slot 3", "callback_data": f"cmd_{ver}_3"},
                ]]},
            )
        else:
            do_force_version(slot, ver)
            do_rerun(slot, version=ver)

    elif any(w in text_lower for w in ("run pipeline", "run it", "start pipeline", "restart", "rerun", "re run", "run today")):
        do_rerun(None)

    elif any(w in text_lower for w in ("didn't run", "did not run", "not run", "hasn't run", "hasnt run",
                                        "pipeline fail", "nothing ran", "check pipeline", "check today")):
        _check_and_rerun()

    elif text_lower.startswith("/revoice"):
        parts = text_lower.split()
        slot  = None
        for p in parts[1:]:
            if p.isdigit() and int(p) in (1, 2, 3, 4):
                slot = int(p)
                break
        if slot is None:
            # Auto-detect: pick slot with the most recent V2 video
            best, best_slot = None, 3
            for s in [1, 2, 3, 4]:
                sids = sorted(OUTPUT.glob(f"otb_v2_slot{s}_*.json"),
                              key=lambda f: f.stat().st_mtime, reverse=True)
                if sids and (best is None or sids[0].stat().st_mtime > best):
                    best, best_slot = sids[0].stat().st_mtime, s
            slot = best_slot
        do_revoice(slot)

    elif text_lower.startswith("/story"):
        parts = text_lower.split()
        label = parts[1] if len(parts) > 1 else "pm"
        do_story(label)

    elif text_lower.startswith("/music"):
        parts = text_lower.split(None, 1)
        query = parts[1].strip() if len(parts) > 1 else ""
        do_music(query)

    elif any(w in text_lower for w in ("get music", "find song", "find music", "download song",
                                        "download music", "youtube music", "yt music")):
        do_music("")

    elif text_lower.startswith("/swapmusic") or any(w in text_lower for w in ("swap music", "change music", "music swap")):
        parts = text_lower.split()
        slot  = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
        if slot:
            do_swapmusic(slot)
        else:
            _send(
                "Which slot to swap music on?",
                reply_markup={"inline_keyboard": [[
                    {"text": "Slot 2", "callback_data": "cmd_swapmusic_2"},
                    {"text": "Slot 3", "callback_data": "cmd_swapmusic_3"},
                    {"text": "Slot 4", "callback_data": "cmd_swapmusic_4"},
                ]]},
            )

    elif text_lower.startswith("/blog") or any(w in text_lower for w in ("post blog", "blog post", "generate blog", "write blog")):
        parts = text_lower.split()
        slot  = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
        if slot:
            do_blog(slot)
        else:
            _send(
                "Which slot to generate a blog post from?",
                reply_markup={"inline_keyboard": [[
                    {"text": "Slot 1", "callback_data": "cmd_blog_1"},
                    {"text": "Slot 4", "callback_data": "cmd_blog_4"},
                ]]},
            )

    elif text_lower.startswith("/block"):
        parts    = text_lower.split()
        is_photo = "photo" in text_lower
        if len(parts) >= 2 and parts[1].isdigit():
            pid = int(parts[1])
            try:
                sys.path.insert(0, str(BASE / "scripts"))
                from media_blocklist import block_id
                block_id(pid, is_video=not is_photo, note="blocked via Telegram")
                kind = "photo" if is_photo else "video"
                _send(f"🚫 Pexels {kind} ID <code>{pid}</code> added to blocklist.")
            except Exception as e:
                _send(f"❌ Block failed: {e}")
        else:
            _send("Usage: <code>/block &lt;pexels_id&gt;</code> or <code>/block &lt;id&gt; photo</code>")


# ── Main poll loop ────────────────────────────────────────────────────────────

_PID_FILE = DATA / "commander.pid"


def _write_pid():
    try:
        _PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass


def _clear_pid():
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _poll_once(offset: int) -> int:
    try:
        r = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 30,
                    "allowed_updates": json.dumps(["message", "callback_query"])},
            timeout=45,
        )
        resp = r.json()
    except Exception as e:
        print(f"[Cmdr] Poll error: {e}")
        time.sleep(5)
        return offset

    if not resp.get("ok"):
        err_code = resp.get("error_code", 0)
        if err_code == 409:
            print("[Cmdr] 409 Conflict — another instance polling; backing off 30s")
            time.sleep(30)
        else:
            print(f"[Cmdr] API error {err_code}: {resp.get('description', '')}")
            time.sleep(5)
        return offset

    for upd in resp.get("result", []):
        offset = upd["update_id"] + 1

        # Inline button callback
        cb = upd.get("callback_query")
        if cb:
            data = cb.get("data", "")
            _ack(cb["id"])

            if data in _CMD_MAP:
                print(f"[Cmdr] Callback: {data}")
                _CMD_MAP[data]()

            # Dynamic: cmd_revoice_2, cmd_revoice_3, cmd_revoice_4
            elif data.startswith("cmd_revoice_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    do_revoice(int(part))

            # Dynamic: cmd_autorevoice_2, cmd_autorevoice_3 etc.
            elif data.startswith("cmd_autorevoice_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    do_autorevoice(int(part))

            # Dynamic: cmd_swapmusic_1, cmd_swapmusic_3 etc.
            elif data.startswith("cmd_swapmusic_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    do_swapmusic(int(part))

            # Dynamic: cmd_blog_1, cmd_blog_4
            elif data.startswith("cmd_blog_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    do_blog(int(part))

            # ── Revoice Studio music browser ──────────────────────────────────
            # rs_mpreview_12  → preview track 12 (30s clip)
            elif data.startswith("rs_mpreview_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _rs_preview_music(int(part))

            # rs_mpick_12  → pick track 12 after preview
            elif data.startswith("rs_mpick_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _rs_confirm_music(int(part))

            # rs_mpage_2  → navigate to page 2
            elif data.startswith("rs_mpage_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _rs_show_music_page(int(part))

            # rs_mshow_0  → back to music browser page 0
            elif data.startswith("rs_mshow_"):
                part = data.split("_")[-1]
                page = int(part) if part.isdigit() else 0
                _rs_show_music_page(page)

            # ── Auto TTS confirm / voice retry ───────────────────────────────
            # rs_tts_confirm_3  → bake the TTS that was previewed
            elif data.startswith("rs_tts_confirm_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    st = _rs_load()
                    base = st.get("v2_base", _find_latest_v2_base(int(part)) or "")
                    voice = st.get("voice", "nova")
                    if base:
                        _do_bake_autorevoice(int(part), base, voice)
                    else:
                        _send("⚠️ No V2 base found — run /rerun first.")

            # rs_tts_voice_3_alloy  → retry TTS with a different voice
            elif data.startswith("rs_tts_voice_"):
                parts = data.split("_")  # ["rs","tts","voice","3","alloy"]
                if len(parts) >= 5 and parts[3].isdigit():
                    do_autorevoice(int(parts[3]), parts[4])

            # ── Swap Music browser ────────────────────────────────────────────
            # ms_mpreview_12  → preview track 12 for music swap
            elif data.startswith("ms_mpreview_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _ms_preview_music(int(part))

            # ms_pick_12  → pick track 12 for swap (after preview)
            elif data.startswith("ms_pick_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _ms_pick(int(part))

            # ms_mpage_2  → swap music browser page 2
            elif data.startswith("ms_mpage_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _ms_show_page(int(part))

            # ms_mshow_0  → back to swap music browser
            elif data.startswith("ms_mshow_"):
                part = data.split("_")[-1]
                page = int(part) if part.isdigit() else 0
                _ms_show_page(page)

            # Dynamic: post_revoiced_2_tiktok, post_revoiced_3_ig
            elif data.startswith("post_revoiced_"):
                parts = data.split("_")  # ["post","revoiced","2","tiktok"]
                slot  = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 2
                plat  = parts[3] if len(parts) > 3 else "tiktok"
                _post_revoiced(slot, plat)

            # Dynamic: edit_pick_2, edit_done_2, edit_cancel_2
            elif data.startswith("edit_pick_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    do_edit(int(part))
            elif data.startswith("edit_done_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _edit_done(int(part))
            elif data.startswith("edit_cancel_"):
                part = data.split("_")[-1]
                if part.isdigit():
                    _edit_cancel(int(part))

            # Approval buttons from send_video_preview (post_N, skip_N, regen_N).
            # Write to file so poll_for_decision picks it up without competing with us.
            elif not data.startswith("post_revoiced_") and (
                data.startswith("post_") or data.startswith("skip_") or data.startswith("regen_")
            ):
                _decision = data.split("_")[0]
                _slot_str = data.split("_")[1] if "_" in data else ""
                if _slot_str.isdigit():
                    _write_web_approval(int(_slot_str), _decision)
                    _msgs = {
                        "post":  f"✅ Slot {_slot_str} — posting now!",
                        "skip":  f"⏭ Slot {_slot_str} — skipped.",
                        "regen": f"🔄 Slot {_slot_str} — regenerating…",
                    }
                    _send(_msgs.get(_decision, f"OK: {data}"))

            continue

        # Text or voice message
        msg  = upd.get("message", {})
        chat = str(msg.get("chat", {}).get("id", ""))
        if chat != str(TELEGRAM_CHAT_ID):
            continue

        text  = msg.get("text", "").strip()
        voice = msg.get("voice") or msg.get("audio")

        if text:
            low = text.lower()
            print(f"[Cmdr] Message: {low[:60]}")

            # Check for active edit session — "field: new value" format
            _edit_fields = ("hook", "problem", "stakes", "resolution", "lesson",
                            "caption_tiktok", "caption_instagram")
            _edit_session = _load_edit_session()
            if _edit_session:
                _matched = False
                for _field in _edit_fields:
                    if low.startswith(f"{_field}:"):
                        _value = text[len(_field) + 1:].strip()
                        if _value:
                            _apply_edit_field(_field, _value, _edit_session.get("slot", 0), _edit_session)
                            _matched = True
                            break
                if _matched:
                    continue  # handled — don't run dispatch

            # Approval flow callbacks piggyback on text format from poll_for_decision
            # — those are handled via callback_query, not text. Just dispatch.
            dispatch(low)

        elif voice:
            file_id = voice.get("file_id", "")
            print(f"[Cmdr] Voice received: {file_id[:20]}…")
            # Check if Revoice Studio is expecting a recording
            st = _rs_load()
            if st and st.get("step") == "awaiting_record":
                _rs_handle_voice_received(file_id, st)
            else:
                _send(
                    "⚠️ Got your voice note, but no active studio session.\n\n"
                    "Use /menu → Re-voice S2/S3/S4 first, then tap 🎤 Record, then send your note."
                )

        # ── User clip / photo upload ───────────────────────────────────────────
        # When you send a video or photo to the bot, it's saved to assets/user_clips/
        # and used as priority footage in the next render.
        #
        # Naming tip — add a caption to tag the beat position:
        #   "hook"       → used for hook scenes (0-1)
        #   "problem"    → used for problem scenes (2-3)
        #   "stakes"     → used for stakes scene (4)
        #   "resolution" → used for resolution scenes (5-6)
        #   "lesson"     → used for lesson scene (7)
        #   (no caption) → used for any scene that needs a clip
        else:
            vid_obj  = msg.get("video") or msg.get("animation")
            photo_arr = msg.get("photo")
            doc_obj  = msg.get("document")

            file_id  = None
            ext      = ".mp4"
            if vid_obj:
                file_id = vid_obj.get("file_id", "")
            elif photo_arr:
                # photo is an array of sizes — take the largest
                file_id = photo_arr[-1].get("file_id", "")
                ext = ".jpg"
            elif doc_obj:
                mime = (doc_obj.get("mime_type") or "").lower()
                if mime.startswith("video/") or mime.startswith("image/"):
                    file_id = doc_obj.get("file_id", "")
                    ext = ".mp4" if mime.startswith("video/") else ".jpg"

            if file_id:
                caption  = (msg.get("caption") or "").strip().lower()
                # Determine beat tag from caption
                beat_tag = ""
                for _bt in ("hook", "problem", "stakes", "resolution", "lesson", "airport"):
                    if _bt in caption:
                        beat_tag = _bt + "_"
                        break

                ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{beat_tag}user_{ts}{ext}"

                clips_dir = BASE / "assets" / "user_clips"
                clips_dir.mkdir(parents=True, exist_ok=True)
                dest_path = clips_dir / filename

                try:
                    # Get download URL from Telegram
                    fi_resp = requests.get(f"{BASE_URL}/getFile",
                                           params={"file_id": file_id}, timeout=15).json()
                    file_path_tg = fi_resp.get("result", {}).get("file_path", "")
                    if not file_path_tg:
                        _send("❌ Could not get file info from Telegram.")
                    else:
                        dl_url = (f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/"
                                  f"{file_path_tg}")
                        data   = requests.get(dl_url, timeout=60).content
                        dest_path.write_bytes(data)
                        size_kb = len(data) // 1024
                        beat_label = beat_tag.rstrip("_") if beat_tag else "any beat"
                        _send(
                            f"✅ Saved to user_clips: {filename} ({size_kb}KB)\n"
                            f"📍 Beat tag: {beat_label}\n\n"
                            f"This clip will be used in the next render as priority footage.\n"
                            f"Tip: send with caption 'hook', 'problem', 'resolution', etc. to pin it to a specific scene."
                        )
                        print(f"[Cmdr] Saved user clip: {filename} ({size_kb}KB)")
                except Exception as _ue:
                    _send(f"❌ Failed to save clip: {_ue}")
                    print(f"[Cmdr] User clip save error: {_ue}")

    _save_offset(offset)
    return offset


def run_commander():
    """Long-running commander loop — called from __main__ or Task Scheduler."""
    _write_pid()
    print(f"[Cmdr] OTB Commander started (pid {os.getpid()}) — {INSTANCE} — {datetime.now().strftime('%A %d %b %H:%M')}", flush=True)
    offset     = _load_offset()
    last_clean = datetime.utcnow() - timedelta(hours=49)

    try:
        while True:
            if (datetime.utcnow() - last_clean).total_seconds() >= 48 * 3600:
                clean_old_messages()
                last_clean = datetime.utcnow()
            try:
                offset = _poll_once(offset)
            except KeyboardInterrupt:
                print("[Cmdr] Shutting down.", flush=True)
                break
            except Exception as e:
                print(f"[Cmdr] Loop error: {e}", flush=True)
                time.sleep(5)
    finally:
        _clear_pid()


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    run_commander()
