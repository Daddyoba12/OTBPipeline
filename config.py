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

_ON_WINDOWS = platform.system() == "Windows"
MAIN_BASE   = BASE   # everything now lives in OTB_Pipeline

ASSETS        = BASE / "assets"
MUSIC_DIR     = BASE / "music" / "daily"
MUSIC_ARCHIVE = BASE / "music" / "archive"
CREDS_PATH    = BASE / "scripts" / "social_credentials.json"
YOUTUBE_TOKEN = BASE / "scripts" / "youtube_token.json"
YOUTUBE_CREDS = BASE / "scripts" / "youtube_credentials.json"

# FFmpeg / font paths
FONT_TITLE    = str(ASSETS / "fonts" / "BebasNeue-Regular.ttf")
FONT_BODY     = str(ASSETS / "fonts" / "Montserrat-ExtraBold.ttf")
FONT_TITLE_FB = r"C\:/Windows/Fonts/impact.ttf" if _ON_WINDOWS else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_BODY_FB  = r"C\:/Windows/Fonts/arialbd.ttf" if _ON_WINDOWS else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

LOGO_PATH   = ASSETS / "mainlogo.png"
FIG_END     = ASSETS / "FIG4End.png"

# ── API Keys — loaded from keys.env on both Windows and Oracle ────────────────
import os as _os
if True:
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
        PERPLEXITY_KEY    = _env_pairs.get("PERPLEXITY_KEY",    os.environ.get("PERPLEXITY_KEY",    ""))
        ZERNIO_API_KEY        = _env_pairs.get("ZERNIO_API_KEY",         os.environ.get("ZERNIO_API_KEY",         ""))
        ZERNIO_ACCOUNT_ID     = _env_pairs.get("ZERNIO_ACCOUNT_ID",      os.environ.get("ZERNIO_ACCOUNT_ID",      ""))
        INSTAGRAM_ACCESS_TOKEN= _env_pairs.get("INSTAGRAM_ACCESS_TOKEN",  os.environ.get("INSTAGRAM_ACCESS_TOKEN",  ""))
        INSTAGRAM_ACCOUNT_ID  = _env_pairs.get("INSTAGRAM_ACCOUNT_ID",   os.environ.get("INSTAGRAM_ACCOUNT_ID",   ""))
        GMAIL_USER            = _env_pairs.get("GMAIL_USER",              os.environ.get("GMAIL_USER",             ""))
        GMAIL_APP_PASSWORD= _env_pairs.get("GMAIL_APP_PASSWORD",os.environ.get("GMAIL_APP_PASSWORD",""))
        KLING_API_KEY         = _env_pairs.get("KLING_API_KEY",            os.environ.get("KLING_API_KEY",           ""))
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
            PERPLEXITY_KEY    = ""
            ZERNIO_API_KEY         = os.environ.get("ZERNIO_API_KEY",         "")
            ZERNIO_ACCOUNT_ID      = os.environ.get("ZERNIO_ACCOUNT_ID",      "")
            INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN",  "")
            INSTAGRAM_ACCOUNT_ID   = os.environ.get("INSTAGRAM_ACCOUNT_ID",   "")
            KLING_API_KEY          = os.environ.get("KLING_API_KEY",           "")
        except Exception:
            ANTHROPIC_API_KEY      = os.environ.get("ANTHROPIC_API_KEY",      "")
            PEXELS_KEY             = os.environ.get("PEXELS_KEY",             "")
            PIXABAY_KEY            = os.environ.get("PIXABAY_KEY",            "")
            GEMINI_API_KEY         = os.environ.get("GEMINI_API_KEY",         "")
            YOUTUBE_API_KEY        = os.environ.get("YOUTUBE_API_KEY",        "")
            OPENAI_API_KEY         = os.environ.get("OPENAI_API_KEY",         "")
            PERPLEXITY_KEY         = os.environ.get("PERPLEXITY_KEY",         "")
            ZERNIO_API_KEY         = os.environ.get("ZERNIO_API_KEY",         "")
            ZERNIO_ACCOUNT_ID      = os.environ.get("ZERNIO_ACCOUNT_ID",      "")
            INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN",  "")
            INSTAGRAM_ACCOUNT_ID   = os.environ.get("INSTAGRAM_ACCOUNT_ID",   "")
            KLING_API_KEY          = os.environ.get("KLING_API_KEY",           "")

TELEGRAM_TOKEN   = "8717698733:AAF7GI9Yw1DhdYVv_TK35fYQcwaGdk4caeA"
TELEGRAM_CHAT_ID = "8641867751"

# "zernio" = managed OAuth via Zernio API (current)
# "direct" = TikTok Content Posting API v2 (legacy, kept in post_tiktok.py)
TIKTOK_POSTER = "zernio"

# ── Kling AI video production ──────────────────────────────────────────────────
# One 30-40s Kling video per day, alternating morning/afternoon slots.
# Client gate: only slugs in this list get Kling videos.
KLING_API_BASE        = "https://api.klingai.com"
KLING_ENABLED_SLUGS   = ["otb_midas", "boothop"]
# slot 1 = morning run (Mon, Wed, Fri…), slot 2 = afternoon run (Tue, Thu, Sat…)
# Weekday 0=Mon,1=Tue,… — even weekdays get slot 1, odd get slot 2
KLING_SLOT_BY_WEEKDAY = {0: 1, 1: 2, 2: 1, 3: 2, 4: 1, 5: 2, 6: 1}
BOOTHOP_JOURNEYS_API  = "https://boothop.com/api/journeys"

# ── AI model selection ─────────────────────────────────────────────────────────
# STORY_MODEL: which AI writes the narrative (Stage 1 — Story Writer)
#   "claude"  → Claude Sonnet 4.6 (V1) / Claude Haiku 4.5 (V2)
#   "openai"  → GPT-4o (V1) / GPT-4o-mini (V2)
#   "gemini"  → Gemini 2.0 Flash (V1 and V2)
# Scene planning (Stage 3) always uses Claude Haiku regardless of this setting.
STORY_MODEL = "claude"

# QA_MODEL: which AI reviews and improves the story (Stage 2 — QA Director)
#   "openai"  → GPT-4o  (recommended — strong at structured critique)
#   "claude"  → Claude Sonnet 4.6
#   "gemini"  → Gemini 2.0 Flash (good secondary opinion)
QA_MODEL = "claude"

# ── Slot schedule ──────────────────────────────────────────────────────────────
# Task Scheduler calls: python pipeline.py --slot 1|2|3|4
# Slot 1: 09:00 UK → posts ~10:00  morning peak (UK commute / Nigeria late morning / 4am EST)
# Slot 2: 15:00 UK → posts ~15:30  afternoon (UK / 10am EST / Nigeria evening)
# Slot 3: 22:00 UK → posts ~22:30  US prime time (5-6pm EST / Nigeria night / UK late)
# Slot 4: 09:00 Tue+Fri → LinkedIn + Blog  (Telegram-reviewed, not fully auto)
SLOT_TIMES = {1: "08:00", 2: "14:00", 3: "21:00", 4: "08:00"}

SLOT_PLATFORMS = {
    1: ["tiktok", "instagram", "youtube", "newspaper"],  # 09:00 — video + newspaper image
    2: ["tiktok", "instagram", "youtube"],               # 15:00 — video only
    3: ["tiktok", "instagram", "youtube"],               # 22:00 — video only
    4: ["linkedin", "blog"],                             # Tue+Fri 09:00 — Telegram-gated
}

# ── Content pillars per slot — 7-day rotation (indexed by weekday: 0=Mon … 6=Sun)
# No pillar appears twice on the same day. Each angle repeats once per week per slot.
SLOT_PILLARS = {
    #              Mon                   Tue                   Wed                   Thu                   Fri (alternates weekly)            Sat                    Sun
    1: ["family",           "travel_hacks",     "airport",          "cost_pain",        ["community",        "faith_friday"],     "humans_of_boothop",   "founder_story"],
    2: ["courier_business", "airport_deliveries","personal_shopper","community",         "multi_courier",     "airport",           "family"],
    3: ["urgent_medical",   "travel_hacks",     "cultural_earn",    "airport_deliveries","smart",             "cost_pain",         "family"],
    4: "brand_authority",   # LinkedIn/blog — consistent thought-leadership angle
}

# Pillars that only post to Instagram — never TikTok or YouTube
# These are B2B content pillars (courier recruitment, personal shopper, multi-courier platform)
INSTAGRAM_ONLY_PILLARS = {"courier_business", "multi_courier"}

# Wildcard pillars — injected randomly (~1 in 10 slot runs) regardless of scheduled pillar.
# These are secondary angles that shouldn't dominate the schedule but appear occasionally.
WILDCARD_PILLARS = ["flight_discovery"]

PILLAR_LABELS = {
    "community":          "Community & Diaspora",
    "family":             "Family & Care",
    "airport":            "Airport Stories",
    "smart":              "Smart Travel",
    "travel_hacks":       "Travel Hacks",
    "logistics_stories":  "Logistics Stories",
    "airport_deliveries": "Airport Deliveries",
    "supply_chain":       "Supply Chain",
    "cost_pain":          "Cost Pain",
    "cultural_earn":      "Cultural & Earn",
    "urgent_medical":     "Urgent & Medical",
    "brand_authority":    "Brand Authority",
    "courier_business":       "Courier Business",
    "personal_shopper":       "Personal Shopper",
    "multi_courier":          "Multi-Courier Business",
    "faith_friday":           "Faith & Prayer",
    "celebration_weekend":    "Weekend Celebration",
    "flight_discovery":       "Flight Discovery",
    "humans_of_boothop":      "Humans of BootHop",
    "founder_story":          "Founder Story",
    "urgent_family":          "Urgent Family",
    "traveller_earnings":     "Traveller Earnings",
    "funny":                  "Relatable & Funny",
}

# Pillars that route to specific platforms only (never TikTok for B2B/business content)
PILLAR_PLATFORM_OVERRIDES = {
    "business":        ["linkedin", "youtube"],
    "courier_business": ["instagram"],           # already in INSTAGRAM_ONLY_PILLARS, kept for clarity
    "multi_courier":   ["instagram"],
}

# Day-of-week content bucket (affects hook tone and visual style)
DAY_BUCKETS = {
    0: "family",     # Monday   — urgent family stories (care packages, last-minute gifts)
    1: "earning",    # Tuesday  — traveller earns (empty luggage allowance, BootHop income)
    2: "airport",    # Wednesday — business/airport movement stories
    3: "viral",      # Thursday — lighter, relatable, humour-forward (price shock, funny discoveries)
    4: "cinematic",  # Friday   — community connection, cinematic feel
    5: "community",  # Saturday — real moments, reviews, word-of-mouth
    6: "community",  # Sunday   — family reunion, recipient POV
}

# ── Video spec ─────────────────────────────────────────────────────────────────
VIDEO_W     = 1080
VIDEO_H     = 1920
VIDEO_FPS   = 30
CLIP_DUR    = 3          # seconds per content clip
N_CLIPS     = 5          # content clips — one per beat (hook/problem/stakes/resolution/lesson)
LESSON_DUR  = 5          # lesson card duration
BRAND_DUR   = 5          # brand end card duration
TOTAL_DUR   = N_CLIPS * CLIP_DUR + LESSON_DUR + BRAND_DUR  # 25 seconds

# ── V2 (Kling) video spec ──────────────────────────────────────────────────────
KLING_LIBRARY      = BASE / "kling_library"          # raw Kling clips folder
KLING_CLIP_COOLDOWN_DAYS = 14                        # same clip not reused within 14 days
V2_TOTAL_DUR       = 15                              # seconds
V2_HOOK_DUR        = 2                               # opening hook card
V2_STORY_DUR       = 9                               # main Kling clips window (0:02–0:11)
V2_BRAND_DUR       = 1.5                             # brand message overlay
V2_CTA_DUR         = 2.5                             # CTA end card
V2_GRACE_MINUTES   = 30                              # after posting, re-runs within this window don't flip version

# Progress bar
PROGRESS_COLOR = "0x4F46E5"   # indigo
PROGRESS_H     = 12            # px height

# ── Telegram approval window ───────────────────────────────────────────────────
# Per-slot Telegram review window (seconds). Slot 1 is longer — more likely you're free.
TELEGRAM_BUFFER_MINUTES = {1: 60, 2: 30, 3: 30, 4: 60}
APPROVAL_TIMEOUT = 30 * 60   # fallback only — pipeline uses TELEGRAM_BUFFER_MINUTES[slot]

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
    1: {"tiktok": "tiktok_am",   "instagram": "instagram_am",  "youtube": "youtube_am",  "newspaper": "newspaper"},
    2: {"tiktok": "tiktok_pm",   "instagram": "instagram_pm",  "youtube": "youtube_pm"},
    3: {"tiktok": "tiktok_night","instagram": "instagram_night","youtube": "youtube_night"},
    4: {"linkedin": "linkedin",  "blog": "blog"},
}
