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

# Load keys.env into environment if variables aren't already set
_keys_env = PIPELINE / "keys.env"
if _keys_env.exists():
    for _line in _keys_env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            if _k.strip() and _k.strip() not in os.environ:
                os.environ[_k.strip()] = _v.strip()

ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "otb-admin-2026")
PIPELINE_SECRET = os.environ.get("PIPELINE_SECRET", "")
BASE_PATH       = os.environ.get("BASE_PATH", "")

# ── Oracle SSH ─────────────────────────────────────────────────────────────────
_ORACLE_IP   = "140.238.73.32"
_ORACLE_USER = "ubuntu"
_ORACLE_KEY  = Path.home() / ".ssh" / "oracle_boothop.pem"
_G_INS_LOCAL = PIPELINE.parent / "g_inspired" / "client_profile.json"

_D818_TASKS = ["D818-Morning", "D818-Afternoon", "D818-Evening",
               "D818-Weekend", "D818-Weekly", "D818-ApprovalCheck"]

_SCHEDULE_PIPELINES = {
    "boothop": {
        "label":         "BootHop",
        "local_profile": PIPELINE / "client_profile.json",
        "oracle_profile": "/opt/otb_pipeline/client_profile.json",
        "tasks":         [],
    },
    "g_inspired": {
        "label":         "G-Inspired",
        "local_profile": _G_INS_LOCAL,
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
        "tasks":         _D818_TASKS,
    },
}


def _profile_active(path) -> bool | None:
    try:
        if path and Path(path).exists():
            return json.loads(Path(path).read_text())["schedule"]["active"]
    except Exception:
        pass
    return None


def _set_profile_active(path, active: bool):
    if not path or not Path(path).exists():
        return
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    p.setdefault("schedule", {})["active"] = active
    Path(path).write_text(json.dumps(p, indent=2), encoding="utf-8")


def _oracle_set_active(oracle_path: str, active: bool) -> str:
    val = "true" if active else "false"
    cmd = [
        "ssh", "-i", str(_ORACLE_KEY), "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10", f"{_ORACLE_USER}@{_ORACLE_IP}",
        f"python3 -c \"import json; p=json.load(open('{oracle_path}')); "
        f"p.setdefault('schedule', {{}})['active']={val}; "
        f"json.dump(p, open('{oracle_path}','w'), indent=2); print('ok')\""
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return "ok" if r.returncode == 0 else r.stderr.strip()[:120]
    except Exception as e:
        return str(e)[:120]


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


def _tasks_enabled(task_names: list) -> bool:
    if not task_names:
        return False
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             f"(Get-ScheduledTask -TaskName '{task_names[0]}').State"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() == "Ready"
    except Exception:
        return False

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
# Fall back to config.py constants when not in environment
_TELEGRAM_TOKEN_FALLBACK = ""
_TELEGRAM_CHAT_FALLBACK  = ""
try:
    import importlib.util as _ilu
    _cspec = _ilu.spec_from_file_location("_cfg", str(PIPELINE / "config.py"))
    _cfg   = _ilu.module_from_spec(_cspec)
    _cspec.loader.exec_module(_cfg)
    _TELEGRAM_TOKEN_FALLBACK = getattr(_cfg, "TELEGRAM_TOKEN", "")
    _TELEGRAM_CHAT_FALLBACK  = getattr(_cfg, "TELEGRAM_CHAT_ID", "")
except Exception:
    pass

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", _TELEGRAM_TOKEN_FALLBACK)
FFMPEG         = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE        = shutil.which("ffprobe") or "ffprobe"
ADMIN_PREFIX   = os.environ.get("ADMIN_PREFIX", "/admin")   # /onboard/admin when behind Vercel proxy

app       = FastAPI(title="OTB Pipeline")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["bp"] = BASE_PATH   # prefix for all internal links when behind proxy

# ── Database ───────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            slug               TEXT UNIQUE NOT NULL,
            name               TEXT NOT NULL,
            email              TEXT DEFAULT '',
            contact            TEXT DEFAULT '',
            plan               TEXT DEFAULT 'basic',
            password_h         TEXT NOT NULL,
            api_key            TEXT UNIQUE,
            tg_chat_id         TEXT DEFAULT '',
            whatsapp           TEXT DEFAULT '',
            created_at         TEXT DEFAULT (datetime('now')),
            active             INTEGER DEFAULT 1,
            platforms_enabled  TEXT DEFAULT '[]',
            credentials_json   TEXT DEFAULT '{}',
            digest_email       TEXT DEFAULT '',
            digest_frequency   TEXT DEFAULT ''
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

def _migrate_db():
    """Add new columns to existing databases without dropping data."""
    migrations = [
        "ALTER TABLE companies ADD COLUMN platforms_enabled TEXT DEFAULT '[]'",
        "ALTER TABLE companies ADD COLUMN credentials_json  TEXT DEFAULT '{}'",
        "ALTER TABLE companies ADD COLUMN digest_email      TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN digest_frequency  TEXT DEFAULT ''",
        # Business profile
        "ALTER TABLE companies ADD COLUMN website_url      TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN youtube_url      TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN linkedin_url     TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN facebook_url     TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN tt_handle        TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN ig_handle        TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN business_type    TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN business_bio     TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN location         TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN area_covered     TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN target_audience  TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN marketing_focus  TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN content_tone     TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN visual_keywords  TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN brand_voice      TEXT DEFAULT ''",
        "ALTER TABLE companies ADD COLUMN logo_path        TEXT DEFAULT ''",
        # Pipeline schedule
        "ALTER TABLE companies ADD COLUMN schedule_json    TEXT DEFAULT '{}'",
        # Intake workflow
        "ALTER TABLE companies ADD COLUMN intake_status    TEXT DEFAULT 'active'",
        "ALTER TABLE companies ADD COLUMN intake_submitted TEXT DEFAULT ''",
    ]
    with _db() as c:
        for sql in migrations:
            try:
                c.execute(sql)
            except Exception:
                pass  # column already exists

_migrate_db()

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
            "SELECT s.*,co.slug,co.name,co.tg_chat_id,co.whatsapp,co.email,co.plan,co.intake_status "
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
    """Resolve a music path — accepts absolute, relative, or https:// Supabase Storage URLs."""
    if not music:
        return None
    # Supabase Storage URL — download to local cache
    if music.startswith("http://") or music.startswith("https://"):
        fname = music.split("/")[-1].split("?")[0]
        cache = MUSIC_DIR / "_cache"
        cache.mkdir(parents=True, exist_ok=True)
        dest = cache / fname
        if not dest.exists():
            try:
                import requests as _r
                r = _r.get(music, timeout=60)
                if r.ok:
                    dest.write_bytes(r.content)
                else:
                    return None
            except Exception:
                return None
        return str(dest)
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
    effective_chat = chat_id or _TELEGRAM_CHAT_FALLBACK
    if not TELEGRAM_TOKEN or not effective_chat:
        return
    chat_id = effective_chat
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
    return RedirectResponse("/get-started", status_code=301)


_FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "hotmail.co.uk",
    "outlook.com", "outlook.co.uk", "icloud.com", "me.com", "aol.com",
    "protonmail.com", "proton.me", "mail.com", "ymail.com", "live.com",
}

def _is_business_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.strip().lower().split("@")[-1]
    return domain not in _FREE_EMAIL_DOMAINS


@app.post("/onboard", response_class=HTMLResponse)
async def onboard_submit(
    request:           Request,
    company_name:      str = Form(...),
    contact_name:      str = Form(""),
    email:             str = Form(""),
    password:          str = Form(...),
    tg_chat_id:        str = Form(""),
    whatsapp:          str = Form(""),
    plan:              str = Form("basic"),
    # Platform toggles
    platform_tiktok:   str = Form(""),
    platform_instagram:str = Form(""),
    platform_youtube:  str = Form(""),
    platform_linkedin: str = Form(""),
    platform_blog:     str = Form(""),
    platform_email:    str = Form(""),
    # TikTok
    tt_handle:         str = Form(""),
    tt_client_key:     str = Form(""),
    tt_client_secret:  str = Form(""),
    # Instagram
    ig_username:       str = Form(""),
    ig_app_id:         str = Form(""),
    ig_app_secret:     str = Form(""),
    ig_access_token:   str = Form(""),
    ig_user_id:        str = Form(""),
    # YouTube
    yt_channel_url:    str = Form(""),
    yt_api_key:        str = Form(""),
    # LinkedIn
    li_profile_url:    str = Form(""),
    li_client_id:      str = Form(""),
    li_client_secret:  str = Form(""),
    li_access_token:   str = Form(""),
    # Blog
    blog_platform:     str = Form(""),
    blog_url:          str = Form(""),
    blog_id:           str = Form(""),
    blog_refresh_token:str = Form(""),
    # Digest
    digest_email:      str = Form(""),
    digest_frequency:  str = Form("daily"),
):
    raw  = re.sub(r"[^\w\s-]", "", company_name.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", raw)[:30]
    if not slug:
        return templates.TemplateResponse("onboard.html",
            {"request": request, "success": False, "slug": "", "error": "Invalid company name."})

    # Validate digest email must be official business domain
    if digest_email.strip() and not _is_business_email(digest_email.strip()):
        return templates.TemplateResponse("onboard.html",
            {"request": request, "success": False, "slug": "",
             "error": "Daily digest email must be an official business email (no Gmail, Yahoo, Hotmail, etc.)."})

    # Build platforms list
    platforms = [p for p, v in [
        ("tiktok", platform_tiktok), ("instagram", platform_instagram),
        ("youtube", platform_youtube), ("linkedin", platform_linkedin),
        ("blog", platform_blog), ("email", platform_email),
    ] if v]

    # Build credentials object — never logged, stored separately
    credentials = {}
    if "tiktok" in platforms:
        credentials["tiktok"] = {
            "handle":        tt_handle.strip(),
            "client_key":    tt_client_key.strip(),
            "client_secret": tt_client_secret.strip(),
            "access_token":  "",
        }
    if "instagram" in platforms:
        credentials["instagram"] = {
            "username":     ig_username.strip(),
            "app_id":       ig_app_id.strip(),
            "app_secret":   ig_app_secret.strip(),
            "access_token": ig_access_token.strip(),
            "ig_user_id":   ig_user_id.strip(),
        }
    if "youtube" in platforms:
        credentials["youtube"] = {
            "channel_url": yt_channel_url.strip(),
            "api_key":     yt_api_key.strip(),
        }
    if "linkedin" in platforms:
        credentials["linkedin"] = {
            "profile_url":   li_profile_url.strip(),
            "client_id":     li_client_id.strip(),
            "client_secret": li_client_secret.strip(),
            "access_token":  li_access_token.strip(),
        }
    if "blog" in platforms:
        credentials["blog"] = {
            "platform":      blog_platform.strip(),
            "blog_url":      blog_url.strip(),
            "blog_id":       blog_id.strip(),
            "refresh_token": blog_refresh_token.strip(),
        }

    try:
        with _db() as c:
            c.execute(
                "INSERT INTO companies "
                "(slug,name,email,contact,plan,password_h,api_key,tg_chat_id,whatsapp,"
                " platforms_enabled,credentials_json,digest_email,digest_frequency) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (slug, company_name, email, contact_name, plan,
                 _hash(password), secrets.token_hex(16), tg_chat_id, whatsapp,
                 json.dumps(platforms), json.dumps(credentials),
                 digest_email.strip(), digest_frequency.strip()),
            )
        _co_dir(slug)
        return templates.TemplateResponse("onboard.html",
            {"request": request, "success": True, "slug": slug,
             "platforms": platforms, "has_digest": bool(digest_email), "error": ""})
    except sqlite3.IntegrityError:
        return templates.TemplateResponse("onboard.html",
            {"request": request, "success": False, "slug": "",
             "error": f"'{company_name}' is already registered. Try a different name.", "platforms": []})


@app.get("/pipeline-login", response_class=HTMLResponse)
async def pipeline_login_page(request: Request):
    return templates.TemplateResponse("pipeline_login.html", {"request": request, "error": ""})


@app.post("/pipeline-login")
async def pipeline_login_submit(
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
        return templates.TemplateResponse("pipeline_login.html",
            {"request": request, "error": "Wrong company ID or password."})
    token = _make_session(row["id"])
    resp  = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("session_token", token, httponly=True, max_age=604800)
    return resp


@app.get("/pipeline-logout")
async def pipeline_logout(session_token: str | None = Cookie(None)):
    if session_token:
        with _db() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (session_token,))
    resp = RedirectResponse("/pipeline-login", status_code=303)
    resp.delete_cookie("session_token")
    return resp


# Keep /login as an alias so existing bookmarks still work
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return RedirectResponse("/pipeline-login", status_code=301)


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
        return templates.TemplateResponse("pipeline_login.html",
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
    resp = RedirectResponse("/pipeline-login", status_code=303)
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

    slug    = re.sub(r"[^\w-]", "", payload.get("slug", "").strip().lower())[:30]
    company = payload.get("company", "").strip()
    if not slug or not company:
        return JSONResponse({"success": False, "error": "slug and company are required"})

    # Save profile files
    profile_dir = BASE_DIR / "clients" / slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "pipeline_profile.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (profile_dir / "config.env").write_text(
        payload.get("raw_config", ""), encoding="utf-8"
    )

    # Register company in DB so client can log in
    temp_pw    = secrets.token_urlsafe(10)
    tg_chat_id = payload.get("tg_chat_id", "")
    email      = payload.get("email", "")
    contact    = payload.get("contact", "")
    plan       = payload.get("plan", "basic")
    platforms  = payload.get("platforms", {})
    plat_list  = [p for p, v in platforms.items() if v]

    try:
        with _db() as c:
            c.execute(
                "INSERT INTO companies "
                "(slug,name,email,contact,plan,password_h,api_key,tg_chat_id,platforms_enabled,credentials_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (slug, company, email, contact, plan,
                 _hash(temp_pw), secrets.token_hex(16), tg_chat_id,
                 json.dumps(plat_list), json.dumps({}))
            )
        _co_dir(slug)
        return JSONResponse({"success": True, "slug": slug, "temp_password": temp_pw})
    except sqlite3.IntegrityError:
        # Already registered — just update the profile files
        return JSONResponse({"success": True, "slug": slug, "temp_password": None,
                             "note": "Company already registered — profile files updated."})


# ══════════════════════════════════════════════════════════════════════════════
#  COMPANY DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session_token: str | None = Cookie(None)):
    sess = _get_sess(session_token)
    if not sess:
        return RedirectResponse("/pipeline-login", status_code=303)
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

    # Prepend latest pipeline output videos (Slot 1/2/3 V1 + V2)
    _SLOT_NAMES = {1: "Slot 1 · Morning", 2: "Slot 2 · Afternoon",
                   3: "Slot 3 · Evening",  4: "Slot 4 · Weekly"}
    if OUTPUT_DIR.exists():
        seen: set = set()
        pipeline_vids: list = []
        for f in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True):
            m1 = _V1_STEM_RE.match(f.stem)
            m2 = _V2_TIKTOK_RE.match(f.stem)
            if m1:
                key = f"v1_{m1.group(1)}"
                if key not in seen:
                    seen.add(key)
                    sn = _SLOT_NAMES.get(int(m1.group(1)), f"Slot {m1.group(1)}")
                    pipeline_vids.append({"path": str(f), "name": f.name,
                                          "label": f"▶ {sn} — V1"})
            elif m2:
                key = f"v2_{m2.group(1)}"
                if key not in seen:
                    seen.add(key)
                    sn = _SLOT_NAMES.get(int(m2.group(1)), f"Slot {m2.group(1)}")
                    pipeline_vids.append({"path": str(f), "name": f.name,
                                          "label": f"▶ {sn} — V2"})
        videos = pipeline_vids + videos

    return templates.TemplateResponse("dashboard.html", {
        "request":        request,
        "company":        sess,
        "music_tracks":   music,
        "bakes":          [dict(b) for b in bakes],
        "videos":         videos,
        "intake_status":  sess.get("intake_status", "active"),
    })


@app.get("/api/video-file")
async def serve_video_file(path: str, session_token: str | None = Cookie(None)):
    """Serve a video — allowed from company directory or pipeline output directory."""
    sess = _get_sess(session_token)
    if not sess:
        raise HTTPException(401)
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(404)
    in_co  = False
    in_out = False
    try:
        file_path.relative_to(CO_DIR);  in_co  = True
    except ValueError:
        pass
    try:
        file_path.relative_to(OUTPUT_DIR); in_out = True
    except ValueError:
        pass
    if not in_co and not in_out:
        raise HTTPException(403, "Access denied")
    return FileResponse(str(file_path), media_type="video/mp4",
                        headers={"Accept-Ranges": "bytes"})


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

    cdir = _co_dir(sess["slug"])

    # Resolve video — accept local path (company dir or pipeline output) or HTTP URL
    video_local = video_path
    if video_path.startswith("http://") or video_path.startswith("https://"):
        import requests as _r
        tmp_vid = cdir / f"video_{int(time.time())}.mp4"
        try:
            resp = _r.get(video_path, stream=True, timeout=120)
            resp.raise_for_status()
            with open(tmp_vid, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
            video_local = str(tmp_vid)
        except Exception as e:
            raise HTTPException(400, f"Failed to download video: {e}")
    elif not Path(video_local).exists():
        raise HTTPException(400, "Video file not found on server")

    voice_dest = cdir / f"voice_{int(time.time())}.ogg"
    voice_dest.write_bytes(await voice.read())

    tg_chat = sess.get("tg_chat_id", "")
    if not tg_chat:
        with _db() as c:
            row = c.execute("SELECT tg_chat_id FROM companies WHERE slug=?",
                            (sess.get("slug", ""),)).fetchone()
            if row:
                tg_chat = row["tg_chat_id"] or ""

    with _db() as c:
        cur     = c.execute(
            "INSERT INTO bakes (company_id,video_path,voice_path,music_path,status) "
            "VALUES (?,?,?,?,'processing')",
            (sess.get("company_id", -1), video_local, str(voice_dest), music_path or "")
        )
        bake_id = cur.lastrowid

    job_id = f"bake_{bake_id}"
    with _jlock:
        _jobs[job_id] = {"status": "processing"}

    background.add_task(
        _bake_worker, job_id, bake_id, video_local, str(voice_dest),
        _resolve_music(music_path) if music_path else None, tg_chat, cdir
    )
    return {"job_id": job_id, "bake_id": bake_id}


@app.get("/api/job/{job_id}")
async def job_status(request: Request, job_id: str, session_token: str | None = Cookie(None)):
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    with _jlock:
        return _jobs.get(job_id, {"status": "unknown"})


def _smart_music_query(raw: str) -> str:
    """Normalise any freetext music query to a yt-dlp search target."""
    raw = raw.strip()
    if not raw:
        return ""
    if raw.lower().startswith("http"):
        return raw
    low = raw.lower()
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
    if not any(w in low for w in ("music", "official", "lyrics", "audio", "song", "feat", "ft.", "remix")):
        raw = raw + " official audio"
    return f"ytsearch1:{raw}"


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

_TTS_VOICES = ["nova", "alloy", "echo", "fable", "onyx", "shimmer"]


@app.post("/api/tts")
async def generate_tts(
    request:       Request,
    text:          str = Form(...),
    voice:         str = Form("nova"),
    session_token: str | None = Cookie(None),
):
    """Generate TTS MP3 from text and return it as audio/mpeg."""
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    if not text.strip():
        raise HTTPException(400, "text is required")
    voice = voice if voice in _TTS_VOICES else "nova"
    if not OPENAI_API_KEY:
        raise HTTPException(503, "OpenAI API key not configured")
    import requests as _r
    try:
        resp = _r.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "tts-1", "input": text.strip(), "voice": voice},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"TTS generation failed: {e}")
    from fastapi.responses import Response
    return Response(content=resp.content, media_type="audio/mpeg",
                    headers={"Content-Disposition": f"inline; filename=tts_{voice}.mp3"})


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
    target = _smart_music_query(query)
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


# ── Client intake (Get Started) ────────────────────────────────────────────────

@app.get("/get-started", response_class=HTMLResponse)
async def get_started_page(request: Request):
    return templates.TemplateResponse("get_started.html", {"request": request, "success": False, "error": ""})


@app.post("/get-started", response_class=HTMLResponse)
async def get_started_submit(
    request:         Request,
    company_name:    str = Form(...),
    contact_name:    str = Form(""),
    email:           str = Form(""),
    password:        str = Form(...),
    website_url:     str = Form(""),
    business_type:   str = Form(""),
    business_bio:    str = Form(""),
    location:        str = Form(""),
    area_covered:    str = Form(""),
    target_audience: str = Form(""),
    marketing_focus: str = Form("awareness_and_sales"),
    content_tone:    str = Form("inspirational"),
    visual_keywords: str = Form(""),
    brand_voice:     str = Form(""),
    tt_handle:       str = Form(""),
    ig_handle:       str = Form(""),
    youtube_url:     str = Form(""),
    linkedin_url:    str = Form(""),
    facebook_url:    str = Form(""),
    platform_tiktok:    str = Form(""),
    platform_instagram: str = Form(""),
    platform_youtube:   str = Form(""),
    platform_linkedin:  str = Form(""),
    platform_blog:      str = Form(""),
    tg_chat_id:      str = Form(""),
    whatsapp:        str = Form(""),
    plan:            str = Form("basic"),
):
    raw  = re.sub(r"[^\w\s-]", "", company_name.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", raw)[:30]
    if not slug:
        return templates.TemplateResponse("get_started.html",
            {"request": request, "success": False, "error": "Invalid company name."})

    platforms = [p for p, v in [
        ("tiktok", platform_tiktok), ("instagram", platform_instagram),
        ("youtube", platform_youtube), ("linkedin", platform_linkedin),
        ("blog", platform_blog),
    ] if v]

    try:
        with _db() as c:
            c.execute(
                "INSERT INTO companies "
                "(slug,name,email,contact,plan,password_h,api_key,tg_chat_id,whatsapp,"
                " platforms_enabled,credentials_json,website_url,business_type,business_bio,"
                " location,area_covered,target_audience,marketing_focus,content_tone,"
                " visual_keywords,brand_voice,tt_handle,ig_handle,youtube_url,linkedin_url,"
                " facebook_url,intake_status,intake_submitted) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (slug, company_name, email.strip(), contact_name.strip(), plan,
                 _hash(password), secrets.token_hex(16), tg_chat_id.strip(), whatsapp.strip(),
                 json.dumps(platforms), json.dumps({}),
                 website_url.strip(), business_type.strip(), business_bio.strip(),
                 location.strip(), area_covered.strip(), target_audience.strip(),
                 marketing_focus, content_tone, visual_keywords.strip(), brand_voice.strip(),
                 tt_handle.strip(), ig_handle.strip(), youtube_url.strip(),
                 linkedin_url.strip(), facebook_url.strip(),
                 "submitted", datetime.now().isoformat())
            )
        _co_dir(slug)
        # Notify admin via Telegram
        _notify_admin_new_intake(company_name, slug, email, platforms)
        return templates.TemplateResponse("get_started.html",
            {"request": request, "success": True, "slug": slug, "error": ""})
    except sqlite3.IntegrityError:
        return templates.TemplateResponse("get_started.html",
            {"request": request, "success": False,
             "error": f"'{company_name}' is already registered. Try a different company name."})


def _notify_admin_new_intake(company: str, slug: str, email: str, platforms: list):
    try:
        import requests as _r
        msg = (f"New pipeline intake submitted!\n\n"
               f"Company: {company}\nSlug: {slug}\nEmail: {email or 'not provided'}\n"
               f"Platforms: {', '.join(platforms) or 'none selected'}\n\n"
               f"Review at: boothop.com/admin")
        _r.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=8,
        )
    except Exception:
        pass


# ── Logo upload / serve ────────────────────────────────────────────────────────

@app.post("/api/upload-logo/{slug}")
async def upload_logo(slug: str, file: UploadFile = File(...)):
    co_dir = _co_dir(slug)
    ext    = (file.filename or "logo.jpg").rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "webp", "gif"}:
        ext = "jpg"
    logo_path = co_dir / f"logo.{ext}"
    content   = await file.read()
    logo_path.write_bytes(content)
    with _db() as c:
        c.execute("UPDATE companies SET logo_path=? WHERE slug=?", (str(logo_path), slug))
    return JSONResponse({"success": True, "url": f"/api/logo/{slug}"})


@app.get("/api/logo/{slug}")
async def serve_logo(slug: str):
    co_dir = _co_dir(slug)
    for ext in ("png", "jpg", "jpeg", "webp", "gif"):
        p = co_dir / f"logo.{ext}"
        if p.exists():
            return FileResponse(str(p))
    raise HTTPException(404, "No logo uploaded")


# ── Admin — schedule + stage 2 + activate ─────────────────────────────────────

@app.post("/admin/set-schedule/{company_id}")
async def admin_set_schedule(
    company_id: int,
    slot1_time: str = Form(""),
    slot2_time: str = Form(""),
    slot3_time: str = Form(""),
    slot4_time: str = Form(""),
    active_days: list[str] = Form([]),
    timezone:   str = Form("Europe/London"),
    session_token: str | None = Cookie(None),
):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        raise HTTPException(403)
    schedule = {
        "slot1": slot1_time, "slot2": slot2_time,
        "slot3": slot3_time, "slot4": slot4_time,
        "days": active_days, "timezone": timezone,
    }
    with _db() as c:
        c.execute("UPDATE companies SET schedule_json=? WHERE id=?",
                  (json.dumps(schedule), company_id))
    return RedirectResponse(f"/admin/company/{company_id}?tab=schedule", status_code=303)


@app.post("/admin/complete-intake/{company_id}")
async def admin_complete_intake(
    company_id: int,
    request:    Request,
    session_token: str | None = Cookie(None),
):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        raise HTTPException(403)
    body = await request.form()
    creds = {}
    for key, val in body.items():
        if key != "session_token" and val:
            creds[key] = val
    with _db() as c:
        row = c.execute("SELECT credentials_json FROM companies WHERE id=?", (company_id,)).fetchone()
        existing = json.loads(row["credentials_json"] or "{}") if row else {}
        existing.update(creds)
        c.execute("UPDATE companies SET credentials_json=?, intake_status=? WHERE id=?",
                  (json.dumps(existing), "stage2", company_id))
    return RedirectResponse(f"/admin/company/{company_id}?tab=credentials", status_code=303)


@app.post("/admin/activate/{company_id}")
async def admin_activate(company_id: int, session_token: str | None = Cookie(None)):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        raise HTTPException(403)
    with _db() as c:
        c.execute("UPDATE companies SET intake_status='active', active=1 WHERE id=?", (company_id,))
        co = c.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    if co:
        _notify_client_activated(dict(co))
    return RedirectResponse(f"/admin/company/{company_id}?msg=activated", status_code=303)


def _notify_client_activated(co: dict):
    tg = co.get("tg_chat_id", "")
    if not tg:
        return
    try:
        import requests as _r
        schedule = json.loads(co.get("schedule_json") or "{}")
        slots = []
        labels = {1: "Morning", 2: "Midday", 3: "Evening", 4: "Weekly"}
        for i in range(1, 5):
            t = schedule.get(f"slot{i}")
            if t:
                slots.append(f"  Slot {i} ({labels[i]}): {t}")
        days = schedule.get("days", [])
        days_str = ", ".join(d.capitalize() for d in days) if days else "Daily"
        tz = schedule.get("timezone", "Europe/London")
        sched_block = "\n".join(slots) if slots else "  Schedule not yet set — check with BootHop"
        msg = (
            f"Your BootHop pipeline is now LIVE!\n\n"
            f"Welcome, {co.get('name', 'there')}.\n\n"
            f"Your content schedule:\n{sched_block}\n"
            f"Active: {days_str} ({tz})\n\n"
            f"You will receive a Telegram video preview each time a slot runs. "
            f"Reply to approve or use Revoice Studio to change the voiceover before it posts.\n\n"
            f"Log in to your dashboard:\n"
            f"boothop.com/pipeline-login\n"
            f"Company ID: {co.get('slug', '')}"
        )
        _r.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": tg, "text": msg},
            timeout=10,
        )
    except Exception:
        pass


@app.post("/admin/pause/{company_id}")
async def admin_pause(company_id: int, session_token: str | None = Cookie(None)):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        raise HTTPException(403)
    with _db() as c:
        row = c.execute("SELECT active FROM companies WHERE id=?", (company_id,)).fetchone()
        new_active = 0 if row and row["active"] else 1
        c.execute("UPDATE companies SET active=? WHERE id=?", (new_active, company_id))
    return RedirectResponse(f"/admin/company/{company_id}", status_code=303)


@app.post("/admin/reset-password/{company_id}")
async def admin_reset_password(
    company_id: int,
    new_password: str = Form(...),
    session_token: str | None = Cookie(None),
):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        raise HTTPException(403)
    with _db() as c:
        c.execute("UPDATE companies SET password_h=? WHERE id=?",
                  (_hash(new_password), company_id))
    return RedirectResponse(f"/admin/company/{company_id}?msg=password_reset", status_code=303)


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
        intake_pending = c.execute(
            "SELECT COUNT(*) FROM companies WHERE intake_status IN ('submitted','stage2') AND id != -1"
        ).fetchone()[0]

    return templates.TemplateResponse("admin.html", {
        "request":        request,
        "companies":      [dict(c) for c in companies],
        "total_bakes":    total_bakes,
        "active_today":   active_today,
        "intake_pending": intake_pending,
        "msg":            request.query_params.get("msg", ""),
        "error":          request.query_params.get("error", ""),
    })


@app.get("/admin/company/{company_id}", response_class=HTMLResponse)
async def admin_company_detail(
    company_id: int,
    request:    Request,
    session_token: str | None = Cookie(None),
    tab: str = "profile",
    msg: str = "",
):
    sess = _get_sess(session_token)
    if not sess or not sess["is_admin"]:
        return RedirectResponse(f"{ADMIN_PREFIX}/login", status_code=303)
    with _db() as c:
        co    = c.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        bakes = c.execute(
            "SELECT * FROM bakes WHERE company_id=? ORDER BY created_at DESC LIMIT 20",
            (company_id,)
        ).fetchall()
    if not co:
        raise HTTPException(404)
    co_dict    = dict(co)
    creds      = json.loads(co_dict.get("credentials_json") or "{}")
    schedule   = json.loads(co_dict.get("schedule_json")    or "{}")
    platforms  = json.loads(co_dict.get("platforms_enabled") or "[]")
    return templates.TemplateResponse("admin_company.html", {
        "request":  request,
        "co":       co_dict,
        "creds":    creds,
        "schedule": schedule,
        "platforms": platforms,
        "bakes":    [dict(b) for b in bakes],
        "tab":      tab,
        "msg":      msg or request.query_params.get("msg", ""),
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


_V1_STEM_RE = re.compile(r"^otb_slot(\d+)_\d{8}_\d{6}$")
_V2_TIKTOK_RE = re.compile(r"^otb_v2_slot(\d+)_\d{8}_\d{6}_tiktok$")


def _list_slot_videos() -> dict:
    result = {}
    for slot in (1, 2, 3, 4):
        v1 = v2 = None
        data: dict = {}

        # V1: otb_slot{slot}_YYYYMMDD_HHMMSS.mp4 (no platform suffix)
        v1_cands = sorted(
            [f for f in OUTPUT_DIR.glob(f"otb_slot{slot}_*.mp4")
             if _V1_STEM_RE.match(f.stem)],
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        if v1_cands:
            v1 = v1_cands[0]
            sidecar = v1.with_suffix(".json")
            if sidecar.exists():
                try:
                    data = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    pass

        # V2: otb_v2_slot{slot}_YYYYMMDD_HHMMSS_tiktok.mp4
        v2_cands = sorted(
            [f for f in OUTPUT_DIR.glob(f"otb_v2_slot{slot}_*_tiktok.mp4")
             if _V2_TIKTOK_RE.match(f.stem)],
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        if v2_cands:
            v2 = v2_cands[0]
            # Merge V2 sidecar data if no V1 sidecar yet
            v2_sidecar = v2.parent / (v2.stem.replace("_tiktok", "") + ".json")
            if v2_sidecar.exists() and not data:
                try:
                    data = json.loads(v2_sidecar.read_text(encoding="utf-8"))
                except Exception:
                    pass

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


@app.get("/api/pipeline/schedule-status")
async def schedule_status_api(session_token: str | None = Cookie(None)):
    if not _get_sess(session_token):
        raise HTTPException(401)
    result = {}
    for key, cfg in _SCHEDULE_PIPELINES.items():
        if cfg["tasks"]:
            active = _tasks_enabled(cfg["tasks"])
        else:
            active = _profile_active(cfg["local_profile"])
        result[key] = {"label": cfg["label"], "active": active}
    return result


def _apply_schedule_action(pipeline: str, active: bool) -> dict:
    keys = list(_SCHEDULE_PIPELINES.keys()) if pipeline == "all" else [pipeline]
    results = {}
    for key in keys:
        cfg = _SCHEDULE_PIPELINES[key]
        if cfg["tasks"]:
            _set_tasks(cfg["tasks"], active)
            results[key] = "ok"
        else:
            _set_profile_active(cfg["local_profile"], active)
            ores = _oracle_set_active(cfg["oracle_profile"], active) if cfg["oracle_profile"] else "skipped"
            results[key] = ores
    return results


@app.post("/api/pipeline/pause")
async def pause_pipeline_api(
    pipeline:      str = Form(...),
    session_token: str | None = Cookie(None),
):
    if not _get_sess(session_token):
        raise HTTPException(401)
    keys = list(_SCHEDULE_PIPELINES.keys()) if pipeline == "all" else [pipeline]
    if not all(k in _SCHEDULE_PIPELINES for k in keys):
        raise HTTPException(400, "unknown pipeline")
    return {"ok": True, "results": _apply_schedule_action(pipeline, False)}


@app.post("/api/pipeline/resume")
async def resume_pipeline_api(
    pipeline:      str = Form(...),
    session_token: str | None = Cookie(None),
):
    if not _get_sess(session_token):
        raise HTTPException(401)
    keys = list(_SCHEDULE_PIPELINES.keys()) if pipeline == "all" else [pipeline]
    if not all(k in _SCHEDULE_PIPELINES for k in keys):
        raise HTTPException(400, "unknown pipeline")
    return {"ok": True, "results": _apply_schedule_action(pipeline, True)}


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


@app.get("/feed", response_class=HTMLResponse)
async def feed_page(request: Request, session_token: str | None = Cookie(None)):
    """48-hour activity feed — read-only overview of everything that went out."""
    if not _get_sess(session_token):
        return RedirectResponse("/pipeline-login", status_code=303)
    feed = _build_feed(hours=48)
    return templates.TemplateResponse("feed.html", {"request": request, "feed": feed})


@app.get("/api/feed")
async def api_feed(request: Request, hours: int = 48, session_token: str | None = Cookie(None)):
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    return _build_feed(hours=hours)


def _fmt_ts(ts: str) -> str:
    try:
        dt  = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = now - dt
        mins = int(diff.total_seconds() // 60)
        if mins < 1:   return "just now"
        if mins < 60:  return f"{mins}m ago"
        if mins < 120: return f"{mins // 60}h {mins % 60}m ago"
        if mins < 1440: return f"{mins // 60}h ago"
        return dt.strftime("%-d %b %H:%M")
    except Exception:
        return ts[:16] if ts else ""


_PLATFORM_ICONS = {
    "tiktok":    "🎵",
    "instagram": "📸",
    "youtube":   "▶️",
    "linkedin":  "💼",
    "blog":      "📝",
    "newsflash": "⚡",
    "newspaper": "📰",
}


def _build_feed(hours: int = 48) -> dict:
    cutoff     = datetime.now() - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()
    cutoff_day = cutoff.strftime("%Y-%m-%d")
    events     = []

    # Social posts
    for e in _load_json(DATA / "post_log.json", []):
        ts = e.get("posted_at", "")
        if ts < cutoff_iso:
            continue
        events.append({
            "type":     "post",
            "platform": e.get("platform", "?"),
            "slot":     e.get("slot"),
            "hook":     e.get("hook", "")[:120],
            "url":      e.get("url") or e.get("video_url") or "",
            "ts":       ts,
            "ts_fmt":   _fmt_ts(ts),
            "icon":     _PLATFORM_ICONS.get(e.get("platform", ""), "📤"),
        })

    # Newsflash posts
    nf = _load_json(DATA / "newsflash_log.json", {})
    for e in nf.get("posts", []):
        ts = e.get("date", "")
        if ts < cutoff_day:
            continue
        events.append({
            "type":     "newsflash",
            "platform": "newsflash",
            "slot":     None,
            "hook":     e.get("hook", "")[:120],
            "route":    e.get("route", ""),
            "url":      "",
            "ts":       ts + "T00:00:00",
            "ts_fmt":   ts,
            "icon":     "⚡",
        })

    # Blog posts
    blog_posted = PIPELINE / "blog" / "posted"
    if blog_posted.exists():
        for f in sorted(blog_posted.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                ts   = meta.get("posted_at", "")
                if ts < cutoff_iso:
                    continue
                events.append({
                    "type":     "post",
                    "platform": "blog",
                    "slot":     4,
                    "hook":     meta.get("title", "Blog post")[:120],
                    "url":      "",
                    "ts":       ts,
                    "ts_fmt":   _fmt_ts(ts),
                    "icon":     "📝",
                })
            except Exception:
                pass

    events.sort(key=lambda e: e["ts"], reverse=True)

    # Stats
    by_platform: dict[str, int] = {}
    slots_used: set = set()
    for e in events:
        p = e.get("platform", "?")
        by_platform[p] = by_platform.get(p, 0) + 1
        if e.get("slot"):
            slots_used.add(e["slot"])

    # Music recently used
    music_recent = []
    for m in _load_json(DATA / "music_log.json", []):
        if m.get("logged_at", "") >= cutoff_iso:
            music_recent.append({
                "title":  m.get("title", "?"),
                "artist": m.get("artist", ""),
                "ts_fmt": _fmt_ts(m.get("logged_at", "")),
            })
    music_recent = music_recent[-6:]

    today_str = datetime.now().strftime("%Y-%m-%d")
    posts_today = [e for e in events if e["ts"].startswith(today_str) and e["type"] == "post"]

    return {
        "events":       events,
        "by_platform":  by_platform,
        "slots_used":   sorted(slots_used),
        "music_recent": music_recent,
        "total_48h":    len([e for e in events if e["type"] == "post"]),
        "posts_today":  len(posts_today),
        "hours":        hours,
        "generated_at": datetime.now().strftime("%H:%M, %d %b"),
    }


@app.get("/api/post-log")
async def api_post_log(request: Request, days: int = 14):
    """Server-to-server endpoint for web Commander to read post history."""
    if PIPELINE_SECRET:
        if request.headers.get("x-pipeline-secret") != PIPELINE_SECRET:
            raise HTTPException(401)
    client_slug = request.headers.get("x-commander-slug", "").strip().lower()
    log_path = DATA / "post_log.json"
    if not log_path.exists():
        return []
    all_entries = _load_json(log_path, [])
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [e for e in all_entries if e.get("posted_at", "") >= cutoff]
    # Filter by client — entries without company_slug belong to boothop (the original client)
    if client_slug:
        recent = [e for e in recent if e.get("company_slug", "boothop") == client_slug]
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

    # Look up tg_chat_id for this slug
    tg_chat = sess.get("tg_chat_id", "")
    if not tg_chat and sess.get("slug"):
        with _db() as c:
            row = c.execute("SELECT tg_chat_id FROM companies WHERE slug=?",
                            (sess["slug"],)).fetchone()
            if row:
                tg_chat = row["tg_chat_id"] or ""

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
                        music_resolved, tg_chat, co)
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


_SB_MUSIC_BASE = "https://zwgngbzbdvnrdnanjded.supabase.co/storage/v1/object/public/music-files"

@app.get("/commander/api/music-list")
async def cmdr_music_list(request: Request, session_token: str | None = Cookie(None)):
    """Return all music files — local if present, else Supabase Storage URL."""
    if not _auth_or_secret(session_token, request):
        raise HTTPException(401)
    tracks = []
    for folder, label in [
        ("archive",      "Archive"),
        ("daily",        "Daily"),
        ("yt_downloads", "YouTube"),
        ("clips",        "Clips"),
    ]:
        d = MUSIC_DIR / folder
        if d.exists():
            for f in sorted(d.glob("*.mp3")):
                tracks.append({"label": f"[{label}] {f.stem}", "path": f"{folder}/{f.name}"})
        else:
            # Folder not local — advertise Supabase Storage URLs so bake can download
            import requests as _r
            try:
                r = _sb("GET", "", params={})  # can't list bucket via REST easily
            except Exception:
                pass
    # If no local archive, add well-known tracks from Supabase storage
    if not (MUSIC_DIR / "archive").exists():
        for i in range(1, 68):
            n = f"track_{i:02d}"
            tracks.append({"label": f"[Archive] {n}", "path": f"{_SB_MUSIC_BASE}/archive/{n}.mp3"})
        for n in ["Rora", "WHY_LOVE"]:
            tracks.append({"label": f"[Archive] {n}", "path": f"{_SB_MUSIC_BASE}/archive/{n}.mp3"})
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
    target = _smart_music_query(query)
    # Output template without extension — yt-dlp appends .mp3 after audio extraction
    out_tmpl = str(dl_dir / safe) + ".%(ext)s"
    final    = dl_dir / f"{safe}.mp3"
    result = subprocess.run(
        ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3",
         "--audio-quality", "0", "-o", out_tmpl, target],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error")[-400:]
        raise HTTPException(500, f"yt-dlp error: {detail}")
    if not final.exists():
        # yt-dlp may have written a different extension before conversion
        candidates = sorted(dl_dir.glob(f"{safe}.*"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not candidates:
            raise HTTPException(500, "Download produced no output file")
        final = candidates[0]
    rel_path = f"yt_downloads/{final.name}"
    return {"label": f"[YouTube] {final.stem}", "path": rel_path}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
