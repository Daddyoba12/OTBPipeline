"""
OTB_Pipeline Dashboard — Multi-tenant client portal
Ported from BootHopPipeline dashboard/main.py

Routes:
  /onboard         — new client self-registration
  /login           — company login
  /dashboard       — client revoice studio + bake history
  /admin           — admin overview of all clients
  /api/bake        — background FFmpeg bake job
  /api/youtube-music — yt-dlp audio download
"""

import hashlib, json, os, re, secrets, shutil, sqlite3, subprocess, sys, tempfile, threading, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, UploadFile, File, Form, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

BASE_DIR    = Path(__file__).parent
PIPELINE    = Path(os.environ.get("PIPELINE_ROOT", str(Path(__file__).parent.parent)))
MUSIC_DIR   = PIPELINE / "music"
DATA        = PIPELINE / "data"
OUTPUT_DIR  = PIPELINE / "output"
CO_DIR      = BASE_DIR / "companies"
DB_PATH     = BASE_DIR / "otb.db"
CO_DIR.mkdir(exist_ok=True)

ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "otb-admin-2026")
PIPELINE_SECRET = os.environ.get("PIPELINE_SECRET", "")  # shared secret for server-to-server calls from web commander

# ── Supabase constants ─────────────────────────────────────────────────────────
_SB_URL = "https://zwgngbzbdvnrdnanjded.supabase.co"
_SB_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp3Z25nYnpiZHZucmRuYW5qZGVkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5NTA0NSwiZXhwIjoyMDkwODcxMDQ1fQ"
    ".jP_Ukh4Dwlxfiei5tyHblJ0psgCXntDwnnZBRQch9zw"
)
_SB_HDR = {
    "apikey":        _SB_KEY,
    "Authorization": f"Bearer {_SB_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates",
}

# Maps file stem → human-readable label shown in the Revoice Studio video picker
_VIDEO_LABELS = {
    "tiktok_v1":    "TikTok v1 — 12pm",
    "tiktok_v2":    "TikTok v2 — 6pm",
    "tiktok_v3":    "TikTok v3 — 9pm",
    "instagram_v1": "Instagram v1 — 12pm",
    "instagram_v2": "Instagram v2 — 6pm",
    "youtube":      "YouTube — 9pm",
    "linkedin":     "LinkedIn — 7am",
    "story_am":     "IG Story — 7am",
    "story_pm":     "IG Story — 6pm",
}

# Preferred display order in the picker
_VIDEO_ORDER = [
    "tiktok_v1", "instagram_v1",
    "tiktok_v2", "instagram_v2", "story_pm",
    "tiktok_v3", "youtube",
    "linkedin", "story_am",
]
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
FFMPEG         = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE        = shutil.which("ffprobe") or "ffprobe"
ADMIN_PREFIX   = os.environ.get("ADMIN_PREFIX", "/admin")   # /onboard/admin when behind Vercel proxy

app       = FastAPI(title="OTB Pipeline")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ── Database ───────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            slug       TEXT UNIQUE NOT NULL,
            name       TEXT NOT NULL,
            email      TEXT DEFAULT '',
            contact    TEXT DEFAULT '',
            plan       TEXT DEFAULT 'basic',
            password_h TEXT NOT NULL,
            api_key    TEXT UNIQUE,
            tg_chat_id TEXT DEFAULT '',
            whatsapp   TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            active     INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            company_id INTEGER NOT NULL,
            is_admin   INTEGER DEFAULT 0,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bakes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER NOT NULL,
            video_path  TEXT DEFAULT '',
            voice_path  TEXT DEFAULT '',
            music_path  TEXT DEFAULT '',
            output_path TEXT DEFAULT '',
            hook        TEXT DEFAULT '',
            status      TEXT DEFAULT 'pending',
            created_at  TEXT DEFAULT (datetime('now'))
        );
        INSERT OR IGNORE INTO companies (id,slug,name,password_h,plan,api_key)
            VALUES (-1,'__admin__','Admin','','admin','');
        """)


_init_db()

# ── Auth ───────────────────────────────────────────────────────────────────────

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _make_session(company_id: int, is_admin: bool = False) -> str:
    token   = secrets.token_hex(32)
    expires = (datetime.now() + timedelta(days=7)).isoformat()
    with _db() as c:
        c.execute("INSERT INTO sessions (token,company_id,is_admin,expires_at) VALUES (?,?,?,?)",
                  (token, company_id, 1 if is_admin else 0, expires))
    return token


def _get_sess(token: str | None) -> dict | None:
    if not token:
        return None
    with _db() as c:
        row = c.execute(
            "SELECT s.*,co.slug,co.name,co.tg_chat_id,co.whatsapp,co.email,co.plan "
            "FROM sessions s JOIN companies co ON co.id=s.company_id "
            "WHERE s.token=? AND s.expires_at > datetime('now')", (token,)
        ).fetchone()
    return dict(row) if row else None

# ── Music helpers ──────────────────────────────────────────────────────────────

def _music_list() -> list[dict]:
    tracks = []
    for folder, label in [
        (MUSIC_DIR / "daily",        "Daily"),
        (MUSIC_DIR / "archive",      "Archive"),
        (MUSIC_DIR / "yt_downloads", "YouTube"),
    ]:
        if folder.exists():
            for f in sorted(folder.glob("*.mp3")):
                tracks.append({"label": f"[{label}] {f.name}", "path": str(f)})
    return tracks


def _co_dir(slug: str) -> Path:
    d = CO_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d

def _resolve_music(music: str | None) -> str | None:
    """Resolve a music path — accepts absolute paths or relative like 'archive/track.mp3'."""
    if not music:
        return None
    p = Path(music)
    if p.is_absolute():
        return str(p) if p.exists() else None
    abs_p = MUSIC_DIR / music
    return str(abs_p) if abs_p.exists() else None

def _auth_or_secret(session_token: str | None, request: Request) -> dict | None:
    """Accept local session cookie OR x-pipeline-secret header (server-to-server)."""
    sess = _get_sess(session_token)
    if sess:
        return sess
    if PIPELINE_SECRET and request.headers.get("x-pipeline-secret") == PIPELINE_SECRET:
        slug = request.headers.get("x-commander-slug", "boothop")
        return {"slug": slug, "company_id": -1, "tg_chat_id": "", "is_admin": 0}
    return None


# ── Supabase helpers ───────────────────────────────────────────────────────────

def _sb(method: str, path: str, **kwargs):
    import requests as _r
    try:
        r = _r.request(method, f"{_SB_URL}/rest/v1/{path}", headers=_SB_HDR, timeout=15, **kwargs)
        return r
    except Exception as e:
        print(f"[SB] {e}")
        return None


def _sb_pipeline_slots(slug: str = "boothop") -> dict:
    r = _sb("GET", "otb_pipeline_state",
            params={"company_slug": f"eq.{slug}", "slot": "gte.1", "order": "slot.asc"})
    if not r or not r.ok:
        return {}
    rows = r.json()
    result = {}
    for row in rows:
        s = str(row.get("slot", 0))
        result[s] = {
            "v1":                row.get("v1_url") or None,
            "v2":                row.get("v2_url") or None,
            "hook":              row.get("hook", ""),
            "hook_v2":           row.get("hook_v2", ""),
            "lesson":            row.get("lesson", ""),
            "lesson_v2":         row.get("lesson_v2", ""),
            "problem":           row.get("problem", ""),
            "stakes":            row.get("stakes", ""),
            "resolution":        row.get("resolution", ""),
            "rendered_at":       row.get("rendered_at", ""),
            "caption_tiktok":    row.get("caption_tiktok", ""),
            "caption_instagram": row.get("caption_instagram", ""),
            "pending_approval":  row.get("pending_approval", False),
        }
    return result


def _sb_pipeline_status(slug: str = "boothop") -> dict | None:
    r = _sb("GET", "otb_pipeline_state",
            params={"company_slug": f"eq.{slug}", "slot": "eq.0", "limit": "1"})
    if not r or not r.ok:
        return None
    rows = r.json()
    if not rows:
        return None
    row = rows[0]
    return {
        "available":     True,
        "today":         _today_str(),
        "posts_today":   0,
        "ran_slots":     json.loads(row.get("ran_slots_json", "[]") or "[]"),
        "current_step":  row.get("current_step", ""),
        "crash_log":     "",
        "pending_slots": json.loads(row.get("pending_slots_json", "[]") or "[]"),
        "active_jobs":   0,
        "recent_posts":  [],
    }


def _sb_push_command(slug: str, slot: int, command: str, params: dict = None):
    _sb("POST", "otb_pipeline_commands", json={
        "company_slug": slug,
        "slot":         slot,
        "command":      command,
        "params_json":  json.dumps(params or {}),
        "status":       "pending",
        "created_at":   datetime.now().isoformat(),
    })

# ── FFmpeg helpers ─────────────────────────────────────────────────────────────

def _duration(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 30.0

# ── Telegram send ──────────────────────────────────────────────────────────────

def _tg_send_video(chat_id: str, path: str, caption: str = ""):
    if not TELEGRAM_TOKEN or not chat_id:
        return
    try:
        import requests as _r
        with open(path, "rb") as f:
            _r.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "supports_streaming": "true"},
                files={"video": f}, timeout=180,
            )
    except Exception as e:
        print(f"[TG send] {e}")

# ── Background bake ────────────────────────────────────────────────────────────

_jobs: dict  = {}
_jlock       = threading.Lock()


def _bake_worker(job_id: str, bake_id: int, video: str, voice: str,
                 music: str | None, tg_chat: str, co_dir: Path):
    out = str(co_dir / f"baked_{int(time.time())}.mp4")
    try:
        dur   = _duration(video)
        fade  = max(0, dur - 2.0)
        ts    = tempfile.mktemp(suffix="_s.mp4")
        ta    = tempfile.mktemp(suffix="_a.aac")

        subprocess.run([FFMPEG, "-y", "-i", video, "-c:v", "copy", "-an", ts],
                       check=True, capture_output=True)

        music_abs = _resolve_music(music)
        if music_abs:
            subprocess.run([
                FFMPEG, "-y", "-i", voice, "-stream_loop", "-1", "-i", music_abs,
                "-filter_complex",
                f"[1:a]volume=0.18[m];[0:a][m]amix=inputs=2:duration=longest:normalize=0[mx];"
                f"[mx]afade=t=out:st={fade}:d=2[out]",
                "-map", "[out]", "-t", str(dur),
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", ta,
            ], check=True, capture_output=True)
        else:
            subprocess.run([
                FFMPEG, "-y", "-i", voice,
                "-filter_complex", f"afade=t=out:st={fade}:d=2",
                "-t", str(dur), "-c:a", "aac", "-b:a", "192k", ta,
            ], check=True, capture_output=True)

        subprocess.run([FFMPEG, "-y", "-i", ts, "-i", ta,
                        "-c:v", "copy", "-c:a", "copy", "-t", str(dur),
                        "-movflags", "+faststart", out],
                       check=True, capture_output=True)

        for f in [ts, ta]:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass

        with _db() as c:
            c.execute("UPDATE bakes SET output_path=?,status='done' WHERE id=?", (out, bake_id))

        if tg_chat:
            _tg_send_video(tg_chat, out, "✅ Your re-voiced video is ready!")

        with _jlock:
            _jobs[job_id] = {"status": "done", "output_path": out, "bake_id": bake_id}

    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode(errors="replace")[-300:]
        with _db() as c:
            c.execute("UPDATE bakes SET status='failed' WHERE id=?", (bake_id,))
        with _jlock:
            _jobs[job_id] = {"status": "failed", "error": err}
    except Exception as e:
        with _db() as c:
            c.execute("UPDATE bakes SET status='failed' WHERE id=?", (bake_id,))
        with _jlock:
            _jobs[job_id] = {"status": "failed", "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, session_token: str | None = Cookie(None)):
    sess = _get_sess(session_token)
    if sess:
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/onboard", status_code=303)


@app.get("/onboard", response_class=HTMLResponse)
async def onboard_page(request: Request):
    return templates.TemplateResponse("onboard.html",
        {"request": request, "success": False, "slug": "", "error": ""})


@app.post("/onboard", response_class=HTMLResponse)
async def onboard_submit(
    request:      Request,
    company_name: str = Form(...),
    contact_name: str = Form(""),
    email:        str = Form(""),
    password:     str = Form(...),
    tg_chat_id:   str = Form(""),
    whatsapp:     str = Form(""),
    plan:         str = Form("basic"),
):
    raw  = re.sub(r"[^\w\s-]", "", company_name.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", raw)[:30]
    if not slug:
        return templates.TemplateResponse("onboard.html",
            {"request": request, "success": False, "slug": "", "error": "Invalid company name."})
    try:
        with _db() as c:
            c.execute(
                "INSERT INTO companies (slug,name,email,contact,plan,password_h,api_key,tg_chat_id,whatsapp) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (slug, company_name, email, contact_name, plan,
                 _hash(password), secrets.token_hex(16), tg_chat_id, whatsapp)
            )
        _co_dir(slug)
        return templates.TemplateResponse("onboard.html",
            {"request": request, "success": True, "slug": slug, "error": ""})
    except sqlite3.IntegrityError:
        return templates.TemplateResponse("onboard.html",
            {"request": request, "success": False, "slug": "",
             "error": f"'{company_name}' is already registered. Try a different name."})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
async def login_submit(
    request:  Request,
    slug:     str = Form(...),
    password: str = Form(...),
):
    with _db() as c:
        row = c.execute(
            "SELECT * FROM companies WHERE slug=? AND password_h=? AND active=1 AND id!=-1",
            (slug.strip().lower(), _hash(password))
        ).fetchone()
    if not row:
        return templates.TemplateResponse("login.html",
            {"request": request, "error": "Wrong company ID or password."})
    token = _make_session(row["id"])
    resp  = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("session_token", token, httponly=True, max_age=604800)
    return resp


@app.get("/logout")
async def logout(session_token: str | None = Cookie(None)):
    if session_token:
        with _db() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (session_token,))
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session_token")
    return resp


# ── Client onboarding wizard (admin-facing, no auth required) ─────────────────

@app.get("/client-onboarding", response_class=HTMLResponse)
async def client_onboarding_page(request: Request):
    return templates.TemplateResponse("client_onboarding.html", {"request": request})


@app.post("/api/onboard")
async def api_onboard(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    slug    = payload.get("slug", "").strip().lower()
    company = payload.get("company", "").strip()
    if not slug or not company:
        return JSONResponse({"success": False, "error": "slug and company are required"})

    profile_dir = BASE_DIR / "clients" / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "pipeline_profile.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (profile_dir / "config.env").write_text(
        payload.get("raw_config", ""), encoding="utf-8"
    )
    return JSONResponse({"success": True, "slug": slug})


# ══════════════════════════════════════════════════════════════════════════════
#  COMPANY DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session_token: str | None = Cookie(None)):
    sess = _get_sess(session_token)
    if not sess:
        return RedirectResponse("/login", status_code=303)
    if sess["is_admin"]:
        return RedirectResponse("/admin", status_code=303)

    cdir  = _co_dir(sess["slug"])
    music = _music_list()

    with _db() as c:
        bakes = c.execute(
            "SELECT * FROM bakes WHERE company_id=? ORDER BY created_at DESC LIMIT 8",
            (sess["company_id"],)
        ).fetchall()

    all_mp4 = sorted(cdir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)

    def _sort_key(f: Path) -> int:
        return _VIDEO_ORDER.index(f.stem) if f.stem in _VIDEO_ORDER else 99

    videos = [
        {
            "path":  str(f),
            "name":  f.name,
            "label": _VIDEO_LABELS.get(f.stem, f.stem.replace("_", " ").title()),
        }
        for f in sorted(all_mp4, key=_sort_key)
    ]

    return templates.TemplateResponse("dashboard.html", {
        "request":      request,
        "company":      sess,
        "music_tracks": music,
        "bakes":        [dict(b) for b in bakes],
        "videos":       videos,
    })


@app.get("/api/video-file")
async def serve_video_file(path: str, session_token: str | None = Cookie(None)):
    """Serve a pipeline video by absolute path — restricted to this company's directory."""
    sess = _get_sess(session_token)
    if not sess:
        raise HTTPException(401)
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(404)
    try:
        file_path.relative_to(CO_DIR)
    except ValueError:
        raise HTTPException(403, "Access outside company directory denied")
    return FileResponse(str(file_path), media_type="video/mp4")


@app.post("/api/upload-video")
async def upload_video(
    request:       Request,
    file:          UploadFile = File(...),
    session_token: str | None = Cookie(None),
):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    cdir = _co_dir(sess["slug"])
    dest = cdir / f"video_{int(time.time())}.mp4"
    dest.write_bytes(await file.read())
    return {"path": str(dest), "name": dest.name}


@app.post("/api/bake")
async def bake(
    request:       Request,
    background:    BackgroundTasks,
    voice:         UploadFile = File(...),
    video_path:    str = Form(...),
    music_path:    str = Form(""),
    session_token: str | None = Cookie(None),
):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    if not Path(video_path).exists():
        raise HTTPException(400, "Video file not found on server")

    cdir       = _co_dir(sess["slug"])
    voice_dest = cdir / f"voice_{int(time.time())}.ogg"
    voice_dest.write_bytes(await voice.read())

    with _db() as c:
        cur     = c.execute(
            "INSERT INTO bakes (company_id,video_path,voice_path,music_path,status) "
            "VALUES (?,?,?,?,'processing')",
            (sess["company_id"], video_path, str(voice_dest), music_path or "")
        )
        bake_id = cur.lastrowid

    job_id = f"bake_{bake_id}"
    with _jlock:
        _jobs[job_id] = {"status": "processing"}

    background.add_task(
        _bake_worker, job_id, bake_id, video_path, str(voice_dest),
        music_path or None, sess.get("tg_chat_id", ""), cdir
    )
    return {"job_id": job_id, "bake_id": bake_id}


@app.get("/api/job/{job_id}")
async def job_status(request: Request, job_id: str, session_token: str | None = Cookie(None)):
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    with _jlock:
        return _jobs.get(job_id, {"status": "unknown"})


@app.post("/api/youtube-music")
async def yt_music(
    request:       Request,
    query:         str = Form(...),
    session_token: str | None = Cookie(None),
):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    dl_dir = MUSIC_DIR / "yt_downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    safe   = re.sub(r"[^\w\-]", "_", query[:38]).strip("_") or "yt_track"
    target = query if query.startswith("http") else f"ytsearch1:{query}"
    raw_t  = str(dl_dir / f"{safe}_raw.%(ext)s")
    final  = dl_dir / f"{safe}_0s.mp3"

    r = subprocess.run(
        ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3",
         "--audio-quality", "0", "--output", raw_t, "--no-warnings", target],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        raise HTTPException(400, r.stderr[-300:] or "yt-dlp failed")

    raws = sorted(dl_dir.glob(f"{safe}_raw.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not raws:
        raise HTTPException(400, "No file downloaded")

    subprocess.run(
        [FFMPEG, "-y", "-i", str(raws[0]), "-ss", "0", "-t", "60",
         "-c:a", "libmp3lame", "-q:a", "2", str(final)],
        check=True, capture_output=True, timeout=60,
    )
    raws[0].unlink(missing_ok=True)
    return {"label": f"[YouTube] {final.name}", "path": str(final)}


@app.get("/api/download-bake/{bake_id}")
async def download_bake(request: Request, bake_id: int, session_token: str | None = Cookie(None)):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    with _db() as c:
        if sess["company_id"] == -1:
            row = c.execute("SELECT * FROM bakes WHERE id=?", (bake_id,)).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM bakes WHERE id=? AND company_id=?",
                (bake_id, sess["company_id"])
            ).fetchone()
    if not row or not row["output_path"] or not Path(row["output_path"]).exists():
        raise HTTPException(404)
    return FileResponse(row["output_path"], media_type="video/mp4",
                        filename=f"revoiced_{bake_id}.mp4")


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": ""})


@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        return templates.TemplateResponse("admin_login.html",
            {"request": request, "error": "Wrong password."})
    token   = secrets.token_hex(32)
    expires = (datetime.now() + timedelta(hours=24)).isoformat()
    with _db() as c:
        c.execute("INSERT INTO sessions (token,company_id,is_admin,expires_at) VALUES (?,?,1,?)",
                  (token, -1, expires))
    resp = RedirectResponse(f"{ADMIN_PREFIX}", status_code=303)
    resp.set_cookie("session_token", token, httponly=True, max_age=86400)
    return resp


@app.get("/admin/logout")
async def admin_logout(session_token: str | None = Cookie(None)):
    if session_token:
        with _db() as c:
            c.execute("DELETE FROM sessions WHERE token=? AND is_admin=1", (session_token,))
    resp = RedirectResponse(f"{ADMIN_PREFIX}/login", status_code=303)
    resp.delete_cookie("session_token")
    return resp


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session_token: str | None = Cookie(None)):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        return RedirectResponse(f"{ADMIN_PREFIX}/login", status_code=303)

    with _db() as c:
        companies = c.execute(
            "SELECT co.*, COUNT(b.id) AS bake_count, MAX(b.created_at) AS last_activity "
            "FROM companies co LEFT JOIN bakes b ON b.company_id=co.id "
            "WHERE co.id != -1 GROUP BY co.id ORDER BY co.created_at DESC"
        ).fetchall()
        total_bakes  = c.execute("SELECT COUNT(*) FROM bakes").fetchone()[0]
        today        = datetime.now().strftime("%Y-%m-%d")
        active_today = c.execute(
            "SELECT COUNT(DISTINCT company_id) FROM bakes WHERE created_at >= ?", (today,)
        ).fetchone()[0]

    return templates.TemplateResponse("admin.html", {
        "request":      request,
        "companies":    [dict(c) for c in companies],
        "total_bakes":  total_bakes,
        "active_today": active_today,
    })


@app.post("/admin/add-company")
async def admin_add_company(
    company_name:  str = Form(...),
    contact_name:  str = Form(""),
    password:      str = Form(...),
    email:         str = Form(""),
    tg_chat_id:    str = Form(""),
    plan:          str = Form("basic"),
    session_token: str | None = Cookie(None),
):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        raise HTTPException(403)
    raw  = re.sub(r"[^\w\s-]", "", company_name.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", raw)[:30]
    try:
        with _db() as c:
            c.execute(
                "INSERT INTO companies (slug,name,email,contact,plan,password_h,api_key,tg_chat_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (slug, company_name, email, contact_name, plan,
                 _hash(password), secrets.token_hex(16), tg_chat_id)
            )
        _co_dir(slug)
    except sqlite3.IntegrityError:
        pass
    return RedirectResponse(f"{ADMIN_PREFIX}", status_code=303)


@app.post("/admin/delete-company/{company_id}")
async def admin_delete(company_id: int, session_token: str | None = Cookie(None)):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        raise HTTPException(403)
    with _db() as c:
        c.execute("UPDATE companies SET active=0 WHERE id=?", (company_id,))
    return RedirectResponse(f"{ADMIN_PREFIX}", status_code=303)


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE CONTROL
# ══════════════════════════════════════════════════════════════════════════════

_pipeline_jobs: dict = {}
_pjlock = threading.Lock()


def _load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _list_slot_videos() -> dict:
    result = {}
    for slot in (1, 2, 3, 4):
        v1 = v2 = None
        data: dict = {}
        for f in sorted(OUTPUT_DIR.glob(f"otb_slot{slot}_v1_*.mp4"),
                        key=lambda f: f.stat().st_mtime, reverse=True):
            sidecar = f.with_suffix(".json")
            if sidecar.exists():
                v1 = f
                try:
                    data = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    pass
                break
        if v1:
            ts = "_".join(v1.stem.split("_")[-2:])
            v2c = OUTPUT_DIR / f"otb_slot{slot}_v2_{ts}.mp4"
            if v2c.exists():
                v2 = v2c
        pa_file = DATA / f"pending_approval_{slot}.json"
        is_pending = False
        if pa_file.exists():
            try:
                age = time.time() - pa_file.stat().st_mtime
                if age < 35 * 60:
                    is_pending = True
                else:
                    pa_file.unlink(missing_ok=True)
            except Exception:
                pass
        result[str(slot)] = {
            "v1":                str(v1) if v1 else None,
            "v2":                str(v2) if v2 else None,
            "hook":              data.get("hook", ""),
            "hook_v2":           data.get("hook_v2", ""),
            "lesson":            data.get("lesson", ""),
            "lesson_v2":         data.get("lesson_v2", ""),
            "problem":           data.get("problem", ""),
            "stakes":            data.get("stakes", ""),
            "resolution":        data.get("resolution", ""),
            "rendered_at":       data.get("rendered_at", ""),
            "caption_tiktok":    data.get("caption_tiktok", ""),
            "caption_instagram": data.get("caption_instagram", ""),
            "pending_approval":  is_pending,
        }
    return result


def _run_slot_bg(slot: int, job_id: str):
    with _pjlock:
        _pipeline_jobs[job_id] = {"status": "running", "slot": slot, "output": ""}
    try:
        proc = subprocess.Popen(
            [sys.executable, str(PIPELINE / "pipeline.py"), "--slot", str(slot), "--force"],
            cwd=str(PIPELINE),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        buf: list[str] = []
        for line in proc.stdout:
            buf.append(line.rstrip())
            if len(buf) > 80:
                buf = buf[-80:]
            with _pjlock:
                _pipeline_jobs[job_id]["output"] = "\n".join(buf)
        proc.wait()
        ok = proc.returncode == 0
        with _pjlock:
            _pipeline_jobs[job_id]["status"] = "done" if ok else "failed"
            _pipeline_jobs[job_id]["returncode"] = proc.returncode
    except Exception as e:
        with _pjlock:
            _pipeline_jobs[job_id] = {"status": "failed", "error": str(e), "slot": slot}


@app.get("/api/pipeline/status")
async def pipeline_status(request: Request, session_token: str | None = Cookie(None)):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    if not OUTPUT_DIR.exists():
        sb_status = _sb_pipeline_status(sess.get("slug", "boothop"))
        return sb_status if sb_status else {"available": False}
    today         = _today_str()
    post_log      = _load_json(DATA / "post_log.json", [])
    ran_today_raw = _load_json(DATA / "pipeline_ran_today.json", {})
    step_file     = DATA / "pipeline_step.txt"
    crash_file    = DATA / "pipeline_crash.log"
    ran_slots = ran_today_raw.get(today, [])
    if isinstance(ran_slots, int):
        ran_slots = [ran_slots]
    today_posts = [e for e in post_log if e.get("posted_at", "").startswith(today)]
    step  = step_file.read_text(encoding="utf-8").strip() if step_file.exists() else ""
    crash = ("\n".join(crash_file.read_text(encoding="utf-8").splitlines()[-20:])
             if crash_file.exists() else "")
    pending = []
    for f in DATA.glob("pending_approval_*.json"):
        try:
            n = int(f.stem.split("_")[-1])
            if time.time() - f.stat().st_mtime < 35 * 60:
                pending.append(n)
        except Exception:
            pass
    with _pjlock:
        active = len([v for v in _pipeline_jobs.values() if v.get("status") == "running"])
    return {
        "available":     True,
        "today":         today,
        "posts_today":   len(today_posts),
        "ran_slots":     ran_slots,
        "current_step":  step,
        "crash_log":     crash,
        "pending_slots": pending,
        "active_jobs":   active,
        "recent_posts":  today_posts[-12:],
    }


@app.get("/api/pipeline/slots")
async def pipeline_slots(request: Request, session_token: str | None = Cookie(None)):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    if OUTPUT_DIR.exists():
        local = _list_slot_videos()
        if any(v.get("v1") or v.get("hook") for v in local.values()):
            return local
    sb_slots = _sb_pipeline_slots(sess.get("slug", "boothop"))
    if sb_slots:
        return sb_slots
    if not OUTPUT_DIR.exists():
        raise HTTPException(503, "Pipeline output not available")
    return _list_slot_videos()


@app.get("/api/pipeline/video")
async def serve_pipeline_video(request: Request, path: str, session_token: str | None = Cookie(None)):
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    if path.startswith("http://") or path.startswith("https://"):
        return RedirectResponse(path)
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404)
    try:
        p.relative_to(OUTPUT_DIR)
    except ValueError:
        raise HTTPException(403)
    return FileResponse(str(p), media_type="video/mp4",
                        headers={"Accept-Ranges": "bytes"})


@app.post("/api/pipeline/run-slot")
async def run_slot_api(
    background:    BackgroundTasks,
    slot:          int = Form(...),
    session_token: str | None = Cookie(None),
):
    if not _get_sess(session_token):
        raise HTTPException(401)
    if slot not in (1, 2, 3, 4):
        raise HTTPException(400, "slot must be 1-4")
    job_id = f"pipe_{slot}_{int(time.time())}"
    background.add_task(_run_slot_bg, slot, job_id)
    return {"job_id": job_id, "slot": slot}


@app.get("/api/pipeline/job/{job_id}")
async def pipeline_job_status(job_id: str, session_token: str | None = Cookie(None)):
    if not _get_sess(session_token):
        raise HTTPException(401)
    with _pjlock:
        return _pipeline_jobs.get(job_id, {"status": "unknown"})


@app.post("/api/pipeline/approve")
async def approve_slot(
    request:       Request,
    slot:          int = Form(...),
    decision:      str = Form(...),
    session_token: str | None = Cookie(None),
):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    if decision not in ("post", "skip", "regen"):
        raise HTTPException(400, "decision must be post/skip/regen")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"web_approval_{slot}.json").write_text(
        json.dumps({"decision": decision, "slot": slot,
                    "ts": datetime.now().isoformat()}),
        encoding="utf-8",
    )
    _sb_push_command(sess.get("slug", "boothop"), slot, decision)
    return {"ok": True}


@app.post("/api/pipeline/edit-field")
async def edit_field_api(
    slot:          int = Form(...),
    field:         str = Form(...),
    value:         str = Form(...),
    session_token: str | None = Cookie(None),
):
    if not _get_sess(session_token):
        raise HTTPException(401)
    valid = {"hook", "problem", "stakes", "resolution", "lesson",
             "caption_tiktok", "caption_instagram"}
    if field not in valid:
        raise HTTPException(400, f"field must be one of {valid}")
    p = DATA / f"pending_edit_{slot}.json"
    existing: dict = {}
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing[field] = value.strip()
    p.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return {"ok": True}


@app.post("/api/pipeline/submit-edit")
async def submit_edit_api(
    slot:          int = Form(...),
    session_token: str | None = Cookie(None),
):
    if not _get_sess(session_token):
        raise HTTPException(401)
    (DATA / f"web_approval_{slot}.json").write_text(
        json.dumps({"decision": "edit", "slot": slot,
                    "ts": datetime.now().isoformat()}),
        encoding="utf-8",
    )
    return {"ok": True}


@app.post("/api/pipeline/block-media")
async def block_media_api(
    media_id:      int = Form(...),
    media_type:    str = Form("video"),
    session_token: str | None = Cookie(None),
):
    if not _get_sess(session_token):
        raise HTTPException(401)
    bl_path = DATA / "media_blocklist.json"
    bl = _load_json(bl_path, {"videos": [], "photos": []})
    key = "videos" if media_type != "photo" else "photos"
    if media_id not in bl.get(key, []):
        bl.setdefault(key, []).append(media_id)
        bl_path.write_text(json.dumps(bl, indent=2), encoding="utf-8")
    return {"ok": True, "blocked": media_id}


@app.get("/api/pipeline/report")
async def weekly_report_api(session_token: str | None = Cookie(None)):
    if not _get_sess(session_token):
        raise HTTPException(401)
    post_log      = _load_json(DATA / "post_log.json", [])
    newsflash_log = _load_json(DATA / "newsflash_log.json", [])
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week = [e for e in post_log if e.get("posted_at", "") >= cutoff]
    by_platform: dict[str, int] = {}
    by_slot:     dict[str, int] = {}
    for e in week:
        pl = e.get("platform", "unknown")
        sl = str(e.get("slot", 0))
        by_platform[pl] = by_platform.get(pl, 0) + 1
        by_slot[sl]     = by_slot.get(sl, 0) + 1
    nf_week = [n for n in newsflash_log if n.get("posted_at", "") >= cutoff]
    return {
        "week_total":     len(week),
        "by_platform":    by_platform,
        "by_slot":        by_slot,
        "newsflash_week": len(nf_week),
    }


@app.get("/api/post-log")
async def api_post_log(request: Request, days: int = 14):
    """Server-to-server endpoint for web Commander to read post history."""
    if PIPELINE_SECRET:
        if request.headers.get("x-pipeline-secret") != PIPELINE_SECRET:
            raise HTTPException(401)
    log_path = DATA / "post_log.json"
    if not log_path.exists():
        return []
    all_entries = _load_json(log_path, [])
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [e for e in all_entries if e.get("posted_at", "") >= cutoff]
    recent.sort(key=lambda e: e.get("posted_at", ""), reverse=True)
    return recent[:100]


# ── Commander alias routes (used by web Commander portal via PIPELINE_BASE_URL) ──

@app.post("/commander/api/bake")
async def cmdr_bake_alias(
    request:    Request,
    background: BackgroundTasks,
    video:      str = Form(...),
    voice:      UploadFile = File(None),
    music:      str = Form(""),
    session_token: str | None = Cookie(None),
):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    if not voice or not voice.filename:
        raise HTTPException(400, "voice file required")
    co = _co_dir(sess["slug"])
    vp = co / f"voice_{int(time.time())}.webm"
    with open(vp, "wb") as fh:
        while chunk := await voice.read(1 << 20):
            fh.write(chunk)
    # Download HTTP video URLs to a local temp file
    video_local = video
    if video.startswith("http://") or video.startswith("https://"):
        import requests as _r
        tmp_vid = co / f"video_{int(time.time())}.mp4"
        try:
            resp = _r.get(video, stream=True, timeout=120)
            resp.raise_for_status()
            with open(tmp_vid, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
            video_local = str(tmp_vid)
        except Exception as e:
            raise HTTPException(400, f"Failed to download video: {e}")
    music_resolved = _resolve_music(music) if music else None
    with _db() as c:
        cur = c.execute(
            "INSERT INTO bakes (company_id,video_path,voice_path,music_path,status) "
            "VALUES (?,?,?,?,'pending')",
            (-1, video_local, str(vp), music_resolved or ""),
        )
        bake_id = cur.lastrowid
    job_id = f"cbake_{bake_id}_{int(time.time())}"
    with _jlock:
        _jobs[job_id] = {"status": "pending", "bake_id": bake_id}
    background.add_task(_bake_worker, job_id, bake_id, video_local, str(vp),
                        music_resolved, "", co)
    return {"job_id": job_id, "bake_id": bake_id}


@app.get("/commander/api/job/{job_id}")
async def cmdr_job_alias(request: Request, job_id: str, session_token: str | None = Cookie(None)):
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    with _jlock:
        return _jobs.get(job_id, {"status": "unknown"})


@app.get("/commander/api/download-bake/{bake_id}")
async def cmdr_download_alias(request: Request, bake_id: int, session_token: str | None = Cookie(None)):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    with _db() as c:
        row = c.execute("SELECT * FROM bakes WHERE id=?", (bake_id,)).fetchone()
    if not row or not row["output_path"] or not Path(row["output_path"]).exists():
        raise HTTPException(404)
    return FileResponse(row["output_path"], media_type="video/mp4",
                        filename=f"revoiced_{bake_id}.mp4")


@app.post("/commander/api/upload-video")
async def cmdr_upload_alias(
    request: Request,
    file: UploadFile = File(...),
    session_token: str | None = Cookie(None),
):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    co = _co_dir(sess["slug"])
    dest = co / f"video_{int(time.time())}.mp4"
    dest.write_bytes(await file.read())
    return {"path": str(dest), "name": dest.name}


@app.get("/commander/api/music-list")
async def cmdr_music_list(request: Request, session_token: str | None = Cookie(None)):
    """Return all local music files for the Revoice studio music picker."""
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    tracks = []
    for folder, label in [
        (MUSIC_DIR / "archive",      "Archive"),
        (MUSIC_DIR / "daily",        "Daily"),
        (MUSIC_DIR / "yt_downloads", "YouTube"),
        (MUSIC_DIR / "clips",        "Clips"),
    ]:
        if folder.exists():
            for f in sorted(folder.glob("*.mp3")):
                rel = f"{folder.name}/{f.name}"
                tracks.append({"label": f"[{label}] {f.stem}", "path": rel})
    return tracks


@app.post("/commander/api/youtube-music")
async def cmdr_yt_music_alias(
    request: Request,
    query: str = Form(...),
    session_token: str | None = Cookie(None),
):
    sess = _auth_or_secret(session_token, request)
    if not sess:
        raise HTTPException(401)
    dl_dir = MUSIC_DIR / "yt_downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    safe   = re.sub(r"[^\w\-]", "_", query[:38]).strip("_") or "yt_track"
    target = query if query.startswith("http") else f"ytsearch1:{query}"
    final  = dl_dir / f"{safe}.mp3"
    try:
        subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "192K",
             "-o", str(final), target],
            check=True, capture_output=True, timeout=60,
        )
    except Exception as e:
        raise HTTPException(500, f"yt-dlp error: {e}")
    if not final.exists():
        raise HTTPException(500, "Download failed")
    rel_path = f"yt_downloads/{final.name}"
    return {"label": f"[YouTube] {final.stem}", "path": rel_path}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
