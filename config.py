"""
OTB_Pipeline — config
All API keys, paths, and constants in one place.
Works on both Windows (laptop) and Linux (Oracle server).
"""

import sys, platform
from pathlib import Path

# ── Paths — auto-detect whether we're on Windows or Oracle ────────────────────
# BASE derives from this file's location so it works on both machines without changes.
BASE        = Path(__file__).resolve().parent
DATA        = BASE / "data"
OUTPUT      = BASE / "output"
TEMP        = BASE / "temp"
SCRIPTS     = BASE / "scripts"

# BootHopPipeline — only exists on Windows laptop (assets, credentials, music archive)
_ON_WINDOWS = platform.system() == "Windows"
MAIN_BASE   = (Path(r"C:\Users\babso\Desktop\BootHopPipeline")
               if _ON_WINDOWS else BASE)

ASSETS        = MAIN_BASE / "assets"
MUSIC_DIR     = BASE / "music" / "daily"          # OTB slot-specific tracks (fetch_trending_music.py)
MUSIC_ARCHIVE = MAIN_BASE / "music" / "archive"   # shared royalty-free fallback library
CREDS_PATH    = MAIN_BASE / "scripts" / "social_credentials.json"
YOUTUBE_TOKEN = MAIN_BASE / "scripts" / "youtube_token.json"
YOUTUBE_CREDS = MAIN_BASE / "scripts" / "youtube_credentials.json"

# FFmpeg / font paths
FONT_TITLE    = str(ASSETS / "fonts" / "Oswald-Bold.ttf")
FONT_BODY     = str(ASSETS / "fonts" / "Montserrat-ExtraBold.ttf")
FONT_TITLE_FB = r"C\:/Windows/Fonts/impact.ttf" if _ON_WINDOWS else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_BODY_FB  = r"C\:/Windows/Fonts/arialbd.ttf" if _ON_WINDOWS else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

LOGO_PATH   = ASSETS / "mainlogo.png"
FIG_END     = ASSETS / "FIG4End.png"

# ── API Keys ───────────────────────────────────────────────────────────────────
# On Windows: inherit from BootHopPipeline config.py
# On Oracle:  read from environment variables (set in /etc/environment or systemd service)
if _ON_WINDOWS:
    # Load by file path to avoid circular import (importing by name re-imports this file)
    import importlib.util as _ilu
    _bhp_cfg = MAIN_BASE / "config.py"
    try:
        _spec = _ilu.spec_from_file_location("bhp_config", str(_bhp_cfg))
        _bhp  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_bhp)
        ANTHROPIC_API_KEY = getattr(_bhp, "ANTHROPIC_API_KEY", "")
        PEXELS_KEY        = getattr(_bhp, "PEXELS_API_KEY",    "") or getattr(_bhp, "PEXELS_KEY", "")
        PIXABAY_KEY       = getattr(_bhp, "PIXABAY_KEY",       "")
        GEMINI_API_KEY    = getattr(_bhp, "GEMINI_API_KEY",    "")
        YOUTUBE_API_KEY   = getattr(_bhp, "YOUTUBE_API_KEY",   "")
        OPENAI_API_KEY    = getattr(_bhp, "OPENAI_API_KEY",    "")
    except Exception as _e:
        print(f"[Config] Warning: could not load BHP keys: {_e}")
        ANTHROPIC_API_KEY = ""
        PEXELS_KEY        = ""
        PIXABAY_KEY       = ""
        GEMINI_API_KEY    = ""
        YOUTUBE_API_KEY   = ""
        OPENAI_API_KEY    = ""
else:
    # On Oracle: load keys from keys.env file (created by fix_oracle.ps1, never in git)
    import os, importlib.util
    _keys_env = BASE / "keys.env"
    if _keys_env.exists():
        _env_pairs: dict = {}
        for _ln in _keys_env.read_text(encoding="utf-8").splitlines():
            _ln = _ln.strip()
            if "=" in _ln and not _ln.startswith("#"):
                _ek, _, _ev = _ln.partition("=")
                _env_pairs[_ek.strip()] = _ev.strip().strip('"').strip("'")
        ANTHROPIC_API_KEY = _env_pairs.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
        PEXELS_KEY        = _env_pairs.get("PEXELS_KEY",        os.environ.get("PEXELS_KEY",        ""))
        PIXABAY_KEY       = _env_pairs.get("PIXABAY_KEY",       os.environ.get("PIXABAY_KEY",       ""))
        GEMINI_API_KEY    = _env_pairs.get("GEMINI_API_KEY",    os.environ.get("GEMINI_API_KEY",    ""))
        YOUTUBE_API_KEY   = _env_pairs.get("YOUTUBE_API_KEY",   os.environ.get("YOUTUBE_API_KEY",   ""))
        OPENAI_API_KEY    = _env_pairs.get("OPENAI_API_KEY",    os.environ.get("OPENAI_API_KEY",    ""))
    else:
        # Fallback: try legacy BHP config path, then environment variables
        _bhp_path = Path("/opt/boothop/config.py")
        try:
            _spec = importlib.util.spec_from_file_location("bhp_config", str(_bhp_path))
            _bhp  = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_bhp)
            ANTHROPIC_API_KEY = getattr(_bhp, "ANTHROPIC_API_KEY", "")
            PEXELS_KEY        = getattr(_bhp, "PEXELS_API_KEY",    "")
            PIXABAY_KEY       = getattr(_bhp, "PIXABAY_KEY",       "")
            GEMINI_API_KEY    = getattr(_bhp, "GEMINI_API_KEY",    "")
            YOUTUBE_API_KEY   = getattr(_bhp, "YOUTUBE_API_KEY",   "")
            OPENAI_API_KEY    = ""
        except Exception:
            ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
            PEXELS_KEY        = os.environ.get("PEXELS_KEY",        "")
            PIXABAY_KEY       = os.environ.get("PIXABAY_KEY",       "")
            GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY",    "")
            YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY",   "")
            OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY",    "")

TELEGRAM_TOKEN   = "8717698733:AAF7GI9Yw1DhdYVv_TK35fYQcwaGdk4caeA"
TELEGRAM_CHAT_ID = "8641867751"

# ── Slot schedule ──────────────────────────────────────────────────────────────
# Task Scheduler calls: python pipeline.py --slot 1|2|3|4
# Times chosen so the video lands on platform DURING the peak window,
# accounting for ~10min generation+render before the actual post goes live.
# Slot 1: starts 7:00am  -> posts ~7:10am  (TikTok/IG morning commute peak: 7-9am)
# Slot 2: starts 12:00pm -> posts ~12:10pm (TikTok/IG lunch scroll peak: 12-2pm)
# Slot 3: starts 17:30   -> posts ~17:40pm (TikTok/IG evening peak: 6-8pm UK — 17:40 arrives early in window)
# Slot 4: starts 20:30   -> posts ~20:40pm (TikTok/IG night scroll: 8-10pm UK, 9-11pm WAT Nigeria)
SLOT_TIMES = {1: "07:00", 2: "12:00", 3: "17:30", 4: "20:30"}

# Platform targets per slot — every platform has its own algorithm logic
#
# Slot 1  7am  — TikTok + Instagram Reel + YouTube + LinkedIn + Blog + Newspaper + IG Story
# Redesigned to match timing grid (timing.docx):
#
# Slot 1  07:00 — IG Story + Blog + Newspaper + LinkedIn (Mon/Wed/Fri)
#           Morning "soft" content: story, blog, newspaper land at 7am
#           LinkedIn B2B post fires early for morning inbox
#
# Slot 2  09:00 — TikTok V1 + Instagram Reel
#           Premium morning slot — best hook of the day
#           No LinkedIn (already fired), no YouTube (too early)
#
# Slot 3  18:00 — TikTok V2 + Instagram Reel + IG Story
#           Evening peak slot — diaspora scroll window
#           Second IG Story for double-tap algo boost
#
# Slot 4  20:30 — TikTok + YouTube
#           Night TikTok + late YouTube (21:30 in doc — 20:30 fire lands ~20:40)
#           YouTube late watch-time window (Nigeria prime time)
SLOT_PLATFORMS = {
    1: ["instagram_story", "blog", "newspaper", "linkedin"],
    2: ["tiktok", "instagram"],
    3: ["tiktok", "instagram", "instagram_story"],
    4: ["tiktok", "youtube"],
}

# ── Content pillars per slot — rotating by day ─────────────────────────────────
# 4-day rotation so each slot gets each pillar once every 4 days
# and no two slots on same day share the same pillar
SLOT_PILLARS = {
    1: ["community",    "travel_hacks",        "logistics_stories",  "supply_chain"],
    2: ["family",       "airport_deliveries",  "community",          "travel_hacks"],
    3: ["airport",      "logistics_stories",   "supply_chain",       "community"],
    4: ["smart",        "community",           "travel_hacks",       "airport_deliveries"],
}

PILLAR_LABELS = {
    "community":          "Community & Diaspora",
    "family":             "Family & Care",
    "airport":            "Airport Stories",
    "smart":              "Smart Travel",
    "travel_hacks":       "Travel Hacks",
    "logistics_stories":  "Logistics Stories",
    "airport_deliveries": "Airport Deliveries",
    "supply_chain":       "Supply Chain",
}

# Day-of-week content bucket (affects hook tone and visual style)
DAY_BUCKETS = {
    0: "business",   # Monday
    1: "family",     # Tuesday
    2: "airport",    # Wednesday
    3: "smart",      # Thursday
    4: "cinematic",  # Friday
    5: "community",  # Saturday
    6: "community",  # Sunday
}

# ── Video spec ─────────────────────────────────────────────────────────────────
VIDEO_W     = 1080
VIDEO_H     = 1920
VIDEO_FPS   = 30
CLIP_DUR    = 4          # seconds per content clip
N_CLIPS     = 8          # content clips
LESSON_DUR  = 5          # lesson card duration
BRAND_DUR   = 5          # brand end card duration
TOTAL_DUR   = N_CLIPS * CLIP_DUR + LESSON_DUR + BRAND_DUR  # 42 seconds

# Progress bar
PROGRESS_COLOR = "0x4F46E5"   # indigo
PROGRESS_H     = 12            # px height

# ── Telegram approval window ───────────────────────────────────────────────────
APPROVAL_TIMEOUT = 30 * 60    # 30 minutes approval window before auto-post

# ── Oracle dashboard routing ───────────────────────────────────────────────────
# After each slot, platform videos are copied/SCP'd to companies/{slug}/ so the
# Revoice Studio dashboard can show them with proper human-readable labels.
ORACLE_IP        = "140.238.73.32"
ORACLE_USER      = "ubuntu"
ORACLE_KEY       = (Path(r"C:\Users\babso\.ssh\oracle_boothop.pem")
                    if _ON_WINDOWS else None)
ORACLE_COMPANIES = "/opt/otb_pipeline/dashboard/companies"
PIPELINE_SLUG    = "boothop"   # company slug used in Revoice Studio (set at /onboard)

# Maps (slot, platform) → dashboard filename stem (becomes {stem}.mp4 in companies/{slug}/)
# Also used by send_result() in telegram_commander.py for human-readable labels
SLOT_PLATFORM_LABELS = {
    1: {"linkedin": "linkedin", "instagram_story": "story_am"},
    2: {"tiktok": "tiktok_v1", "instagram": "instagram_v1"},
    3: {"tiktok": "tiktok_v2", "instagram": "instagram_v2", "instagram_story": "story_pm"},
    4: {"tiktok": "tiktok_v3", "youtube": "youtube"},
}
