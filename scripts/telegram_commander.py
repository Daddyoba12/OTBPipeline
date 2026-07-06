"""
OTB_Pipeline — Telegram commander (Full Edition)
Ported from BootHopPipeline commander, adapted for OTB slot-based pipeline.

Approval flow:   send_video_preview / poll_for_decision / send_result  (called by pipeline.py)
Revoice Studio:  /revoice [2|3|4] → record voice → pick music → bake → post
Commands:        /menu  /status  /rerun [slot]  /revoice [slot]  /story  /music  /block
Natural lang:    "rerun", "status", "what's running", "get music", etc.
Pending queue:   pending_newspaper.json / pending_story.json / pending_linkedin.json
Cleanup:         48-hour message deletion (runs automatically on startup)
"""

import json, os, subprocess, sys, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DATA, BASE, OUTPUT,
    MUSIC_DIR, MUSIC_ARCHIVE,
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

def _list_music_tracks(max_tracks: int = 4) -> list:
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


def _music_keyboard() -> dict:
    tracks = _list_music_tracks(4)
    rows = []
    for i, t in enumerate(tracks):
        rows.append([{"text": f"🎵 {t.stem[:28]}", "callback_data": f"rs_music_{i}"}])
    rows.append([
        {"text": "📺 YouTube",   "callback_data": "rs_music_yt"},
        {"text": "🔇 No music",  "callback_data": "rs_music_none"},
    ])
    return {"inline_keyboard": rows}


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


# ── Revoice Studio flow ───────────────────────────────────────────────────────

def do_revoice(slot: int):
    video, data = _find_latest_video(slot)
    if not video:
        _send(f"❌ No Slot {slot} video found in output. Run /rerun {slot} first.")
        return
    hook     = data.get("hook", "(hook not available — record freely)")
    caption  = data.get("caption", hook)

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

    label = _SLOT_LABELS.get(slot, f"Slot {slot}")
    _send(
        f"🎬 <b>Re-voice — {label}</b>\n\n"
        f"<b>Script to read:</b>\n<i>{hook[:300]}</i>\n\n"
        f"Tap Record, then send a voice note:",
        reply_markup={"inline_keyboard": [[
            {"text": "🎤 Record", "callback_data": "rs_record"},
            {"text": "⏭ Skip",   "callback_data": "rs_skip_studio"},
        ]]},
    )


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
    recorded_path = Path(st.get("recorded_path", ""))
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
            subprocess.run(
                [FFMPEG, "-y", "-i", music_path, "-ss", "0", "-t", str(trim_sec),
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(tmp_music)],
                check=True, capture_output=True,
            )
            subprocess.run(
                [FFMPEG, "-y",
                 "-i", str(recorded_path), "-i", str(tmp_music),
                 "-filter_complex",
                 f"[1:a]volume=0.18[m];[0:a][m]amix=inputs=2:duration=longest:normalize=0[mx];"
                 f"[mx]afade=t=out:st={fade_st}:d=2[out]",
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
    st["step"] = "awaiting_record"
    _rs_save(st)
    _send("🎤 Ready — send your voice note now.")


def _rs_keep():
    st = _rs_load()
    if not st or st.get("step") != "reviewing_record":
        _send("⚠️ Record a voice note first.")
        return
    st["step"] = "awaiting_music"
    _rs_save(st)
    _send("🎵 Choose your music track:", reply_markup=_music_keyboard())


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


def _rs_pick_music(idx: int):
    st = _rs_load()
    if not st or st.get("step") != "awaiting_music":
        _send("⚠️ Not in music selection step.")
        return
    tracks = _list_music_tracks(4)
    if idx >= len(tracks):
        _send("⚠️ Track not found — try again.")
        return
    st["music_path"] = str(tracks[idx])
    st["step"]       = "awaiting_trim"
    _rs_save(st)
    _send(
        f"🎵 Selected: <i>{tracks[idx].stem}</i>\n\nHow long should the music run?",
        reply_markup=_trim_keyboard(),
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
    _rs_bake(st)


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
    _rs_bake(st)


def _rs_skip_studio():
    _rs_clear()
    _send("⏭ Studio session ended.")


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


def do_rerun(slot: int = None):
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
    _send(f"🔄 Rerunning Slot {slot}…\nThis takes ~10 minutes. Watch for the preview.")
    try:
        subprocess.Popen(
            [PYTHON, str(BASE / "pipeline.py"), "--slot", str(slot), "--force"],
            cwd=str(BASE),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        _send(f"❌ Failed to start pipeline: {e}")


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


def do_music(query: str):
    if not query.strip():
        _send(
            "🎵 <b>Music download</b>\n\n"
            "Send a YouTube URL or search term:\n"
            "  <code>/music lofi chill hip hop</code>\n"
            "  <code>/music https://youtu.be/...</code>\n\n"
            "Track is trimmed to 60s and saved for your next revoice bake."
        )
        return

    _send(f"⬇️ Downloading: <i>{query}</i>  (~15–30 seconds…)")

    import re as _re
    try:
        dl_dir = BASE / "music" / "yt_downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        target   = query if query.startswith("http") else f"ytsearch1:{query}"
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
    Poll Telegram for Post / Skip / Regen callback on this slot.
    Returns "post" | "skip" | "regen" | "timeout"
    """
    start  = time.time()
    offset = _load_offset()
    print(f"[Cmdr] Polling for Slot {slot} decision ({timeout_sec//60}min window)…")

    while time.time() - start < timeout_sec:
        # File-based edit signal — set by _edit_done() when operator finishes editing
        pending_edit = DATA / f"pending_edit_{slot}.json"
        if pending_edit.exists():
            print(f"[Cmdr] Edit file detected for Slot {slot} — triggering re-render")
            return "edit"

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
                _send(f"✅ Slot {slot} — posting now!")
                return "post"
            elif data == f"skip_{slot}":
                _send(f"⏭ Slot {slot} — skipped.")
                return "skip"
            elif data == f"regen_{slot}":
                _send(f"🔄 Slot {slot} — regenerating…")
                return "regen"

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
                {"text": "📊 Status",          "callback_data": "cmd_status"},
                {"text": "🔄 Re-run Slot…",    "callback_data": "cmd_rerun_pick"},
            ],
            [
                {"text": "🎤 Re-voice S2",     "callback_data": "cmd_revoice_2"},
                {"text": "🎤 Re-voice S3",     "callback_data": "cmd_revoice_3"},
                {"text": "🎤 Re-voice S4",     "callback_data": "cmd_revoice_4"},
            ],
            [
                {"text": "📱 Story (1pm)",     "callback_data": "cmd_story_pm"},
                {"text": "📱 Story (8:30pm)",  "callback_data": "cmd_story_eve"},
            ],
            [
                {"text": "🎵 Get Music (YT)",  "callback_data": "cmd_music_prompt"},
                {"text": "📈 Weekly Report",   "callback_data": "cmd_report"},
            ],
        ]
    }


# ── Command map (static callbacks) ────────────────────────────────────────────

_CMD_MAP = {
    "cmd_status":        lambda: do_status(),
    "cmd_rerun_pick":    lambda: do_rerun(None),
    "cmd_rerun_1":       lambda: do_rerun(1),
    "cmd_rerun_2":       lambda: do_rerun(2),
    "cmd_rerun_3":       lambda: do_rerun(3),
    "cmd_rerun_4":       lambda: do_rerun(4),
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
    "rs_music_0":        lambda: _rs_pick_music(0),
    "rs_music_1":        lambda: _rs_pick_music(1),
    "rs_music_2":        lambda: _rs_pick_music(2),
    "rs_music_3":        lambda: _rs_pick_music(3),
    "rs_music_yt":       lambda: _rs_music_yt(),
    "rs_music_none":     lambda: _rs_music_none(),
    "rs_trim_15":        lambda: _rs_set_trim_and_bake(15),
    "rs_trim_30":        lambda: _rs_set_trim_and_bake(30),
    "rs_trim_45":        lambda: _rs_set_trim_and_bake(45),
    "rs_skip_studio":    lambda: _rs_skip_studio(),
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

    elif text_lower.startswith("/status") or any(w in text_lower for w in ("status", "what's running", "whats running", "how's it", "hows it")):
        do_status()

    elif text_lower.startswith("/rerun"):
        parts = text_lower.split()
        slot  = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
        if slot and slot not in (1, 2, 3, 4):
            _send("Usage: /rerun 1|2|3|4")
            return
        do_rerun(slot)

    elif any(w in text_lower for w in ("run pipeline", "run it", "start pipeline", "restart", "rerun", "re run", "run today")):
        do_rerun(None)

    elif any(w in text_lower for w in ("didn't run", "did not run", "not run", "hasn't run", "hasnt run",
                                        "pipeline fail", "nothing ran", "check pipeline", "check today")):
        _check_and_rerun()

    elif text_lower.startswith("/revoice"):
        parts = text_lower.split()
        slot  = 2
        for p in parts[1:]:
            if p.isdigit() and int(p) in (1, 2, 3, 4):
                slot = int(p)
                break
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
