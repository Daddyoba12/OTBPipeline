"""
OTB_Pipeline — Daily trending music fetcher

Priority chain per slot:
  1. SoundCloud genre search  (direct search — no YouTube, no cookies, no auth)
  2. Archive fallback         (music/archive/ — royalty-free library)

SoundCloud via yt-dlp scsearch: requires no authentication.
YouTube downloads removed — they require browser cookies since mid-2026.

Output:
  music/daily/track_1.mp3 -> Slot 1  08:00 morning
  music/daily/track_2.mp3 -> Slot 2  14:00 afternoon
  music/daily/track_3.mp3 -> Slot 3  21:00 evening

14-day no-repeat: tracks logged to data/music_log.json (90-day rolling).
"""

import json, subprocess, shutil, sys, os, platform as _platform, re
from datetime import datetime, timedelta, date
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Ensure FFmpeg is on PATH so yt-dlp postprocessors work
if _platform.system() == "Windows":
    for _fp in [r"C:\ffmpeg\bin", r"C:\ffmpeg", r"C:\Program Files\ffmpeg\bin"]:
        if Path(_fp).exists() and _fp not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _fp + os.pathsep + os.environ.get("PATH", "")

from config import (DATA, MUSIC_ARCHIVE, G_INSPIRED_MUSIC_DIR, G_INSPIRED_MUSIC_ARCHIVE,
                    D818_MUSIC_DIR, D818_MUSIC_ARCHIVE, PERPLEXITY_KEY)

DAILY_DIR = BASE / "music" / "daily"
ARCHIVE   = MUSIC_ARCHIVE
TMP_DIR   = DAILY_DIR / "_tmp"
MUSIC_LOG = DATA / "music_log.json"
INFO_FILE = DAILY_DIR / "daily_info.json"

# G-Inspired Automall — separate music dirs and log
GI_DAILY_DIR = G_INSPIRED_MUSIC_DIR
GI_ARCHIVE   = G_INSPIRED_MUSIC_ARCHIVE
GI_MUSIC_LOG = DATA / "gi_music_log.json"
GI_INFO_FILE = GI_DAILY_DIR / "daily_info.json"

# D818 Catering — separate music dirs and log (never mixes with BootHop's picks,
# even though both draw from the same broader Afrobeats/West African genre pool —
# see _used_recently_cross() below for the cross-brand duplicate guard).
D818_DAILY_DIR = D818_MUSIC_DIR
D818_ARCHIVE   = D818_MUSIC_ARCHIVE
D818_MUSIC_LOG = DATA / "d818_music_log.json"
D818_INFO_FILE = D818_DAILY_DIR / "daily_info.json"

DAILY_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
GI_DAILY_DIR.mkdir(parents=True, exist_ok=True)
GI_ARCHIVE.mkdir(parents=True, exist_ok=True)
D818_DAILY_DIR.mkdir(parents=True, exist_ok=True)
D818_ARCHIVE.mkdir(parents=True, exist_ok=True)


# ── Priority artists per slot ──────────────────────────────────────────────────
# Queries are built dynamically — current month backward — so no hardcoded titles.

_SLOT_ARTISTS = {
    1: ["Wizkid", "Asake", "Burna Boy", "Davido", "Omah Lay", "Mavo",
        "Victony", "Rema", "Ayra Starr", "Tems", "Fireboy DML", "Tyla",
        "Oxlade", "Khaid", "Adekunle Gold", "Ckay", "Pheelz"],
    2: ["Davido", "Burna Boy", "Wizkid", "Omah Lay", "Asake", "Mavo",
        "Ruger", "Fave", "Simi", "Mr Eazi", "Yemi Alade",
        "Tiwa Savage", "Black Sherif", "Joeboy"],
    3: ["Burna Boy", "Wizkid", "Asake", "Omah Lay", "Davido", "Mavo",
        "Focalistic", "Kabza De Small", "DJ Maphorisa",
        "Zinoleesky", "Kizz Daniel", "Blaqbonez"],
}

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _build_slot_queries(slot: int) -> list[str]:
    """
    Build queries: for each priority artist, try current month → previous months
    going back 6 months, then year-only as final fallback per artist.
    e.g. "Wizkid September 2026", "Wizkid August 2026", ..., "Wizkid 2026"
    """
    today     = date.today()
    queries: list[str] = []
    artists   = _SLOT_ARTISTS.get(slot, _SLOT_ARTISTS[1])

    # Build 6-month window working backwards from this month
    month_labels: list[str] = []
    for offset in range(6):
        m = today.month - offset
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        month_labels.append(f"{_MONTHS[m - 1]} {y}")

    # For each artist: current-month query first, then step back, then year-only
    for artist in artists:
        for label in month_labels:
            queries.append(f"{artist} {label}")
        queries.append(f"{artist} {today.year}")

    return queries


# Injected by _perplexity_refresh() weekly — real current track names at top
CURRENT_TRACKS_FILE = DATA / "current_tracks.json"

SLOT_QUERIES: dict[int, list[str]] = {}  # built at runtime below


def _perplexity_refresh() -> bool:
    """
    Call Perplexity to find each priority artist's latest single right now.
    Writes results to data/current_tracks.json. Runs once per week (Monday).
    Returns True if refresh ran, False if skipped or failed.
    """
    if date.today().weekday() != 0:  # Monday only
        return False
    if CURRENT_TRACKS_FILE.exists():
        try:
            saved = json.loads(CURRENT_TRACKS_FILE.read_text(encoding="utf-8"))
            if saved.get("week") == date.today().isocalendar()[1]:
                return False  # already refreshed this week
        except Exception:
            pass

    if not PERPLEXITY_KEY:
        print("  [Music] Perplexity key missing — skipping weekly refresh")
        return False

    import urllib.request
    artists = ["Wizkid", "Asake", "Omah Lay", "Burna Boy", "Davido", "Mavo"]
    prompt = (
        "What is each of these Nigerian/Afrobeats artist's most recently released single or song "
        "as of today? Give ONLY the song title for each, no explanations. "
        "Format: Artist: Song Title\n"
        + "\n".join(artists)
    )
    try:
        body = json.dumps({
            "model": "sonar",
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.perplexity.ai/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {PERPLEXITY_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        tracks = {}
        for line in text.splitlines():
            m = re.match(r"(\w[\w\s]+):\s*(.+)", line.strip())
            if m:
                artist = m.group(1).strip()
                title  = m.group(2).strip().strip('"').strip("'")
                tracks[artist] = title
        if tracks:
            CURRENT_TRACKS_FILE.write_text(
                json.dumps({"week": date.today().isocalendar()[1], "tracks": tracks},
                           indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"  [Music] Perplexity refresh: {tracks}")
            return True
    except Exception as e:
        print(f"  [Music] Perplexity refresh failed: {e}")
    return False


def _load_current_tracks():
    """
    Prepend Perplexity-discovered current titles to each slot's query list.
    Each slot starts from a different artist so slots 1/2/3 never lead with
    the same track — prevents the same song playing across all three slots.
    Slot 1 → artist[0], Slot 2 → artist[1], Slot 3 → artist[2], then wrap.
    """
    if not CURRENT_TRACKS_FILE.exists():
        return
    try:
        saved = json.loads(CURRENT_TRACKS_FILE.read_text(encoding="utf-8"))
        tracks = saved.get("tracks", {})
        if not tracks:
            return
        artists_in_order = list(tracks.keys())
        n = len(artists_in_order)
        for slot_num in SLOT_QUERIES:
            # Rotate starting artist per slot
            start = (slot_num - 1) % n
            rotated = artists_in_order[start:] + artists_in_order[:start]
            injected = [f"{a} {tracks[a]}" for a in rotated]
            covered  = {a.lower() for a in artists_in_order}
            deduped  = [q for q in SLOT_QUERIES[slot_num]
                        if q.split()[0].lower() not in covered]
            SLOT_QUERIES[slot_num] = injected + deduped
    except Exception as e:
        print(f"  [Music] Could not load current tracks: {e}")


# Build dynamic month-backward queries at startup, then optionally prepend Perplexity titles
for _s in (1, 2, 3):
    SLOT_QUERIES[_s] = _build_slot_queries(_s)

_perplexity_refresh()
_load_current_tracks()

# G-Inspired Automall — US R&B / Hip-Hop / Pop (car dealership vibes)
_GI_ARTISTS = ["SZA", "Bruno Mars", "The Weeknd", "Benson Boone",
                "Sabrina Carpenter", "Doja Cat", "Khalid", "Post Malone", "Harry Styles"]

_SLOT_ARTISTS[4] = _GI_ARTISTS  # reuse _build_slot_queries with slot 4
GI_SLOT_QUERIES = {1: _build_slot_queries(4)}

# D818 Catering — West African wedding/party/highlife-leaning Afrobeats.
# Deliberately a different mix from BootHop's club-Afrobeats list (slots 1-3)
# even though it's the same broader genre/diaspora audience — plus the
# cross-brand check in _used_recently_cross() below guards against the two
# brands ever posting the identical track on the same day.
_D818_ARTISTS_SLOT1 = ["Flavour", "Chike", "Waje", "Yemi Alade", "Simi",
                       "Adekunle Gold", "Made Kuti", "Teni", "Ayra Starr"]
_D818_ARTISTS_SLOT2 = ["Kizz Daniel", "Tems", "CKay", "Flavour", "Simi",
                       "Yemi Alade", "Chike", "Waje", "Ayra Starr"]

_SLOT_ARTISTS[5] = _D818_ARTISTS_SLOT1  # D818 slot 1 — lunch (12:30 UK)
_SLOT_ARTISTS[6] = _D818_ARTISTS_SLOT2  # D818 slot 2 — evening (20:00 UK)
D818_SLOT_QUERIES = {1: _build_slot_queries(5), 2: _build_slot_queries(6)}


def _used_recently_cross(title: str, days: int = 1) -> bool:
    """D818-only guard: also skip a title if BootHop already used it today/
    yesterday, so the two brands never post the identical track same-day."""
    return _used_yesterday(title, log_file=MUSIC_LOG)


# ── Music log helpers ──────────────────────────────────────────────────────────

def _load_log(log_file: Path | None = None) -> list:
    f = log_file or MUSIC_LOG
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_log(entry: dict, log_file: Path | None = None):
    f   = log_file or MUSIC_LOG
    log = _load_log(f)
    log.append(entry)
    f.write_text(json.dumps(log[-90:], indent=2, ensure_ascii=False), encoding="utf-8")


def _used_recently(title: str, days: int = 14, log_file: Path | None = None) -> bool:
    log    = _load_log(log_file)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return any(
        e.get("logged_at", "") > cutoff and e.get("title", "").lower() == title.lower()
        for e in log
    )


def _used_yesterday(title: str, log_file: Path | None = None) -> bool:
    log    = _load_log(log_file)
    cutoff = (datetime.now() - timedelta(days=2)).isoformat()
    return any(
        e.get("logged_at", "") > cutoff and e.get("title", "").lower() == title.lower()
        for e in log
    )


# ── Hook extraction ────────────────────────────────────────────────────────────

def _extract_hook(src_path: Path, out_path: Path, duration_s: int = 30) -> bool:
    """Find highest-energy window. Falls back to ffmpeg trim if librosa absent."""
    try:
        import librosa
        import numpy as np
        from pydub import AudioSegment

        y, sr    = librosa.load(str(src_path), duration=210, mono=True)
        rms      = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        from scipy.ndimage import uniform_filter1d
        smoothed = uniform_filter1d(rms, size=60)
        s_start  = int(len(smoothed) * 0.20)
        s_end    = int(len(smoothed) * 0.75)
        peak_idx = s_start + int(np.argmax(smoothed[s_start:s_end]))
        peak_ms  = int(peak_idx * 512 / sr * 1000)

        audio    = AudioSegment.from_mp3(str(src_path))
        hook_ms  = duration_s * 1000
        start_ms = max(0, peak_ms - hook_ms // 2)
        end_ms   = min(len(audio), start_ms + hook_ms)
        start_ms = max(0, end_ms - hook_ms)

        hook = audio[start_ms:end_ms].fade_in(500).fade_out(1200)
        hook = hook.set_channels(2).set_frame_rate(44100)
        hook.export(str(out_path), format="mp3", bitrate="192k")
        print(f"    [Hook] Peak at {start_ms//1000}s, saved {out_path.stat().st_size//1024}KB")
        return True

    except ImportError:
        try:
            src_dur = _get_duration(src_path)
            trim_start = max(0, min(30, src_dur - duration_s - 1)) if src_dur > duration_s else 0
            fade_out_st = max(0, duration_s - 1.5)
            res = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src_path),
                 "-ss", str(trim_start), "-t", str(duration_s),
                 "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out_st}:d=1.5",
                 "-b:a", "192k", str(out_path)],
                capture_output=True, timeout=60,
            )
            return out_path.exists() and out_path.stat().st_size > 5000
        except Exception as e:
            print(f"    [Hook] ffmpeg trim failed: {e}")
            return False
    except Exception as e:
        print(f"    [Hook] Extraction failed: {e}")
        return False


def _get_duration(path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 60))
    except Exception:
        return 60.0


# ── Volume guard ───────────────────────────────────────────────────────────────

def _has_audio(path: Path, min_db: float = -60.0) -> bool:
    try:
        res = subprocess.run(
            ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null",
             "NUL" if _platform.system() == "Windows" else "/dev/null"],
            capture_output=True, text=True, timeout=30,
        )
        for line in res.stderr.splitlines():
            if "mean_volume" in line:
                val = float(line.split("mean_volume:")[1].strip().split()[0])
                return val > min_db
    except Exception:
        pass
    return True


# ── SoundCloud downloader ──────────────────────────────────────────────────────

def _download_soundcloud(query: str, raw_out: Path, log_file: Path | None = None) -> dict | None:
    """
    Search SoundCloud for a track matching query and download it.
    Uses scsearch5 to get 5 candidates — official DRM-locked uploads are always
    first, so iterating past them reaches fan/unofficial uploads that download.
    Returns metadata dict on success, None on failure.
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: collect up to 5 candidate URLs without downloading ──────────────
    try:
        list_res = subprocess.run(
            [r"C:\Python314\Scripts\yt-dlp.exe",
             "--flat-playlist",
             "--print", "%(url)s|||%(title)s|||%(uploader)s",
             "--match-filter", "duration < 600",
             "--quiet", "--no-warnings",
             f"scsearch5:{query}"],
            timeout=60, capture_output=True, text=True,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"    [SC] Timeout/missing yt-dlp: {e}")
        return None

    candidates = []
    for line in list_res.stdout.strip().splitlines():
        parts = line.split("|||", 2)
        if len(parts) >= 1 and parts[0].startswith("http"):
            url    = parts[0].strip()
            title  = parts[1].strip() if len(parts) > 1 else query
            uploader = parts[2].strip() if len(parts) > 2 else "SoundCloud"
            candidates.append((url, title, uploader))

    if not candidates:
        print(f"    [SC] No candidates found for: {query}")
        return None

    # ── Step 2: try each candidate until one downloads (skip DRM/used) ──────────
    for url, title, uploader in candidates:
        if _used_recently(title, days=7, log_file=log_file):
            print(f"    [SC] Skip (used recently): {title[:55]}")
            continue

        for f in TMP_DIR.iterdir():
            try: f.unlink()
            except Exception: pass

        tmp_out = str(TMP_DIR / "sc_track.%(ext)s")
        try:
            dl_res = subprocess.run(
                [r"C:\Python314\Scripts\yt-dlp.exe",
                 "--no-playlist",
                 "--extract-audio", "--audio-format", "mp3", "--audio-quality", "192K",
                 "--max-filesize", "12m",
                 "--quiet", "--no-warnings",
                 "-o", tmp_out,
                 url],
                timeout=120, capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            print(f"    [SC] Timeout downloading: {title[:50]}")
            continue

        if dl_res.returncode != 0:
            err = dl_res.stderr.strip()[:80]
            if "DRM" in err:
                print(f"    [SC] DRM — skip: {title[:50]}")
            else:
                print(f"    [SC] Failed ({err}): {title[:50]}")
            continue

        mp3s = [f for f in TMP_DIR.glob("*.mp3") if f.stat().st_size > 50_000]
        if not mp3s:
            continue
        mp3 = mp3s[0]

        try:
            shutil.copy2(str(mp3), str(raw_out))
            mp3.unlink(missing_ok=True)
            return {"title": title, "artist": uploader, "source": "soundcloud"}
        except Exception as e:
            print(f"    [SC] Copy failed: {e}")
            continue

    return None


# ── Archive fallback ───────────────────────────────────────────────────────────

def _archive_fallback(slot_out: Path, slot_num: int, used_titles: set,
                      archive_dir: Path | None = None, log_file: Path | None = None) -> dict | None:
    ar = archive_dir or ARCHIVE
    tracks = sorted(list(ar.glob("*.mp3")) + list(ar.glob("*.m4a")))
    if not tracks:
        return None
    day = datetime.now().timetuple().tm_yday
    # Strict 14-day gap — never loosen this rule regardless of archive size
    for offset in range(len(tracks)):
        t = tracks[(day * 4 + slot_num + offset) % len(tracks)]
        if not _used_recently(t.stem, log_file=log_file) and t.stem not in used_titles:
            if not _has_audio(t):
                continue
            shutil.copy2(str(t), str(slot_out))
            return {"title": t.stem, "artist": "archive", "source": "archive"}
    # All archive tracks used within 14 days — caller raises RuntimeError
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_trending_music(archive_only: bool = False) -> dict:
    """
    Download 3 daily tracks (one per slot).

    archive_only=True  — skip SoundCloud entirely, pull from local archive only.
                         Used by Oracle cron so the laptop remains the sole SoundCloud
                         downloader. Oracle never tries SoundCloud; it only draws from
                         the archive library with the full 14-day gap enforced.
    archive_only=False — SoundCloud primary, archive 14-day fallback (laptop default).
    """
    mode = "archive-only" if archive_only else "SoundCloud+archive"
    print(f"\n[Music] Selecting today's tracks ({mode})...")

    SLOT_LABELS = {1: "Morning 08:00", 2: "Afternoon 14:00", 3: "Evening 21:00"}
    info = {"date": datetime.now().strftime("%Y-%m-%d"), "tracks": []}
    used_titles: set = set()

    for slot_num in (1, 2, 3):
        slot_out = DAILY_DIR / f"track_{slot_num}.mp3"
        print(f"\n  [Slot {slot_num}] {SLOT_LABELS[slot_num]}")

        result = None

        # ── SoundCloud download (laptop only) ───────────────────────────────────
        if not archive_only:
            queries = SLOT_QUERIES.get(slot_num, SLOT_QUERIES[1])
            for query in queries:
                print(f"    Trying SoundCloud: {query}")
                raw = TMP_DIR / "raw_download.mp3"
                meta = _download_soundcloud(query, raw, log_file=MUSIC_LOG)
                if not meta:
                    continue

                hooked = _extract_hook(raw, slot_out, duration_s=30)
                raw.unlink(missing_ok=True)

                if hooked and slot_out.exists() and _has_audio(slot_out):
                    result = {**meta, "logged_at": datetime.now().isoformat()}
                    used_titles.add(meta["title"])
                    _save_log(result)
                    size = slot_out.stat().st_size // 1024
                    print(f"  [Slot {slot_num}] OK [soundcloud] {meta['title'][:50]} ({size}KB)")
                    break
                else:
                    slot_out.unlink(missing_ok=True)

        # ── Archive fallback (strict 14-day gap) ────────────────────────────────
        if not result:
            src = "archive-only" if archive_only else "SoundCloud failed"
            print(f"  [Slot {slot_num}] {src} — trying archive (14-day gap enforced)")
            archive_result = _archive_fallback(slot_out, slot_num, used_titles,
                                              archive_dir=ARCHIVE, log_file=MUSIC_LOG)
            if archive_result is None:
                msg = (
                    f"[Music] CRITICAL: Slot {slot_num} — no non-repeat track available "
                    f"within 14-day gap. Add more tracks to music/archive/."
                )
                print(msg)
                raise RuntimeError(msg)
            result = archive_result
            result["logged_at"] = datetime.now().isoformat()
            used_titles.add(result.get("title", ""))
            _save_log(result)

        info["tracks"].append({
            "slot":   slot_num,
            "title":  result.get("title", "?"),
            "artist": result.get("artist", "?"),
            "source": result.get("source", "?"),
        })

    INFO_FILE.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n  [Music] Summary:")
    for t in info["tracks"]:
        flag = "SC" if t["source"] == "soundcloud" else "A"
        print(f"    [{flag}] track_{t['slot']}.mp3 — {t['title'][:50]}")

    return info


def _already_fresh_today() -> bool:
    if not INFO_FILE.exists():
        return False
    try:
        info = json.loads(INFO_FILE.read_text(encoding="utf-8"))
        if info.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return False
        return len(info.get("tracks", [])) >= 3
    except Exception:
        return False


def fetch_gi_music(archive_only: bool = False) -> dict:
    """
    Download 1 daily track for G-Inspired Automall slot 1.
    Uses US R&B/hip-hop/pop queries. Writes to g_inspired_music/daily/track_1.mp3.
    Separate 14-day log (gi_music_log.json) — never mixes with BootHop music log.
    """
    mode = "archive-only" if archive_only else "SoundCloud+archive"
    print(f"\n[GI Music] Selecting G-Inspired track ({mode})...")

    GI_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    GI_ARCHIVE.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    info        = {"date": datetime.now().strftime("%Y-%m-%d"), "tracks": []}
    used_titles: set = set()
    slot_num    = 1
    slot_out    = GI_DAILY_DIR / "track_1.mp3"

    result = None

    if not archive_only:
        queries = GI_SLOT_QUERIES.get(slot_num, GI_SLOT_QUERIES[1])
        for query in queries:
            print(f"    Trying SoundCloud: {query}")
            raw  = TMP_DIR / "gi_raw.mp3"
            meta = _download_soundcloud(query, raw, log_file=GI_MUSIC_LOG)
            if not meta:
                continue
            hooked = _extract_hook(raw, slot_out, duration_s=30)
            raw.unlink(missing_ok=True)
            if hooked and slot_out.exists() and _has_audio(slot_out):
                result = {**meta, "logged_at": datetime.now().isoformat()}
                used_titles.add(meta["title"])
                _save_log(result, log_file=GI_MUSIC_LOG)
                size = slot_out.stat().st_size // 1024
                print(f"  [GI Slot 1] OK [soundcloud] {meta['title'][:50]} ({size}KB)")
                break
            else:
                slot_out.unlink(missing_ok=True)

    if not result:
        src = "archive-only" if archive_only else "SoundCloud failed"
        print(f"  [GI Slot 1] {src} — trying G-Inspired archive (14-day gap)")
        archive_result = _archive_fallback(slot_out, slot_num, used_titles,
                                           archive_dir=GI_ARCHIVE, log_file=GI_MUSIC_LOG)
        if archive_result is None:
            msg = ("[GI Music] CRITICAL: No non-repeat track available. "
                   "Add tracks to g_inspired_music/archive/.")
            print(msg)
            raise RuntimeError(msg)
        result = archive_result
        result["logged_at"] = datetime.now().isoformat()
        _save_log(result, log_file=GI_MUSIC_LOG)

    info["tracks"].append({
        "slot": 1, "title": result.get("title", "?"),
        "artist": result.get("artist", "?"), "source": result.get("source", "?"),
    })
    GI_INFO_FILE.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [GI Music] track_1.mp3 — {result.get('title', '?')[:50]}")
    return info


def fetch_d818_music(archive_only: bool = False) -> dict:
    """
    Download 2 daily tracks for D818 Catering (slot 1 lunch, slot 2 evening).
    Own artist pool + own 14-day log (d818_music_log.json) — separate from
    BootHop's, plus a cross-brand same-day check so the two never post the
    identical track even when an artist overlaps both pools.
    """
    mode = "archive-only" if archive_only else "SoundCloud+archive"
    print(f"\n[D818 Music] Selecting today's tracks ({mode})...")

    SLOT_LABELS = {1: "Lunch 12:30", 2: "Evening 20:00"}
    info = {"date": datetime.now().strftime("%Y-%m-%d"), "tracks": []}
    used_titles: set = set()

    for slot_num in (1, 2):
        slot_out = D818_DAILY_DIR / f"track_{slot_num}.mp3"
        print(f"\n  [D818 Slot {slot_num}] {SLOT_LABELS[slot_num]}")

        result = None

        if not archive_only:
            queries = D818_SLOT_QUERIES.get(slot_num, D818_SLOT_QUERIES[1])
            for query in queries:
                print(f"    Trying SoundCloud: {query}")
                raw  = TMP_DIR / f"d818_raw_{slot_num}.mp3"
                meta = _download_soundcloud(query, raw, log_file=D818_MUSIC_LOG)
                if not meta:
                    continue

                if meta["title"] in used_titles or _used_recently_cross(meta["title"]):
                    print(f"    [D818] Skip (used today, incl. BootHop's list): {meta['title'][:50]}")
                    raw.unlink(missing_ok=True)
                    continue

                hooked = _extract_hook(raw, slot_out, duration_s=30)
                raw.unlink(missing_ok=True)

                if hooked and slot_out.exists() and _has_audio(slot_out):
                    result = {**meta, "logged_at": datetime.now().isoformat()}
                    used_titles.add(meta["title"])
                    _save_log(result, log_file=D818_MUSIC_LOG)
                    size = slot_out.stat().st_size // 1024
                    print(f"  [D818 Slot {slot_num}] OK [soundcloud] {meta['title'][:50]} ({size}KB)")
                    break
                else:
                    slot_out.unlink(missing_ok=True)

        if not result:
            src = "archive-only" if archive_only else "SoundCloud failed"
            print(f"  [D818 Slot {slot_num}] {src} — trying D818 archive (14-day gap)")
            archive_result = _archive_fallback(slot_out, slot_num, used_titles,
                                              archive_dir=D818_ARCHIVE, log_file=D818_MUSIC_LOG)
            if archive_result is None:
                msg = ("[D818 Music] CRITICAL: No non-repeat track available. "
                       "Add tracks to music_d818/archive/.")
                print(msg)
                raise RuntimeError(msg)
            result = archive_result
            result["logged_at"] = datetime.now().isoformat()
            used_titles.add(result.get("title", ""))
            _save_log(result, log_file=D818_MUSIC_LOG)

        info["tracks"].append({
            "slot": slot_num, "title": result.get("title", "?"),
            "artist": result.get("artist", "?"), "source": result.get("source", "?"),
        })

    D818_INFO_FILE.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  [D818 Music] Summary:")
    for t in info["tracks"]:
        flag = "SC" if t["source"] == "soundcloud" else "A"
        print(f"    [{flag}] track_{t['slot']}.mp3 — {t['title'][:50]}")
    return info


def _d818_already_fresh_today() -> bool:
    if not D818_INFO_FILE.exists():
        return False
    try:
        info = json.loads(D818_INFO_FILE.read_text(encoding="utf-8"))
        if info.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return False
        return len(info.get("tracks", [])) >= 2
    except Exception:
        return False


if __name__ == "__main__":
    _archive_only = "--archive-only" in sys.argv
    _client       = None
    for _arg in sys.argv:
        if _arg.startswith("--client="):
            _client = _arg.split("=", 1)[1].strip()
        elif _arg == "--client" and sys.argv.index(_arg) + 1 < len(sys.argv):
            _client = sys.argv[sys.argv.index(_arg) + 1]

    if _client == "g_inspired":
        fetch_gi_music(archive_only=_archive_only)
    elif _client == "d818":
        if "--skip-if-fresh" in sys.argv and _d818_already_fresh_today():
            print("[D818 Music] Fresh tracks already downloaded today — skipping.")
        else:
            fetch_d818_music(archive_only=_archive_only)
    elif "--skip-if-fresh" in sys.argv and _already_fresh_today():
        print("[Music] Fresh tracks already downloaded today — skipping.")
    else:
        fetch_trending_music(archive_only=_archive_only)

    if _client not in ("g_inspired", "d818"):
        # Pre-warm trending hashtags (BootHop only)
        print("\n[Hashtags] Pre-warming trending hashtags...")
        try:
            from fetch_trending_hashtags import fetch_today as _fth
            _fth()
        except Exception as e:
            print(f"[Hashtags] Pre-warm failed: {e}")
