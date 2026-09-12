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

import json, subprocess, shutil, sys, os, platform as _platform
from datetime import datetime, timedelta
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

from config import DATA, MUSIC_ARCHIVE, G_INSPIRED_MUSIC_DIR, G_INSPIRED_MUSIC_ARCHIVE

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

DAILY_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
GI_DAILY_DIR.mkdir(parents=True, exist_ok=True)
GI_ARCHIVE.mkdir(parents=True, exist_ok=True)


# ── Per-slot SoundCloud search queries ────────────────────────────────────────
# Multiple queries per slot → tried in order until one downloads successfully.
# Queries are genre/vibe based — no YouTube dependency, no cookies needed.

SLOT_QUERIES = {
    # IMPORTANT: Use artist-name or song-title searches, not genre searches.
    # Genre searches ("afrobeats 2026") return long mixes filtered by duration < 600.
    # Artist or title searches return single tracks (2-4 min).
    # Keep list large — DRM blocks and 14-day log need many fallback options.

    1: [  # Morning 08:00 — Afrobeats energy
        "Victony Soweto",
        "Rema Calm Down",
        "Asake Organise",
        "Ayra Starr Rush",
        "Ckay Love Nwantiti",
        "Fireboy Peru",
        "Tems Free Mind",
        "Gyakie Forever",
        "Omah Lay Understand",
        "Pheelz Finesse",
        "Portable Zazu",
        "Benson Boone Beautiful Things",
        "Tyla Water official",
        "Oxlade Kulosa",
        "Khaid With You",
        "Olamide Infinity",
        "Wande Coal Again",
        "Seun Kuti",
        "Lojay Monalisa",
        "Adekunle Gold Mercy",
    ],
    2: [  # Afternoon 14:00 — Naija / Afroswing
        "Wizkid Essence",
        "Burna Boy Last Last",
        "Davido Fall",
        "Omah Lay Bad Influence",
        "Fave Baby Riddim",
        "Ruger Dior",
        "Simi Duduke",
        "Flavour Nwa Baby",
        "Tekno Yur Luv",
        "Naira Marley Soapy",
        "Zlatan Zanku",
        "Mr Eazi Pour Me Water",
        "Yemi Alade Johnny",
        "Tiwa Savage Somebody Son",
        "Afro B Drogba",
        "Not3s My Lover",
        "Maleek Berry Feel Like",
        "Kida Kudz Buga remix",
        "Black Sherif Kwaku the Traveller",
        "Joeboy Beginning",
    ],
    3: [  # Evening 21:00 — Amapiano / chill Afrobeats
        "Focalistic Ke Star",
        "Kabza De Small Sponono",
        "DJ Maphorisa Izolo",
        "Blaqbonez Miss Understood",
        "Zinoleesky Loving You",
        "Kizz Daniel Buga",
        "Shan'L Belo",
        "Amaroto Bango",
        "Felo Le Tee Ke Kho",
        "Daliwonga Tshwala Bam",
        "Young Stunna Adiwele",
        "Reece Madlisa Siyathandana",
        "Myztro John Vuli Gate",
        "DJ Buckz Woza",
        "Mas Musiq Vula Vula",
        "Mnqobi Yazo Ngeke Balunge",
        "Shasha Akulaleki",
        "Samthing Soweto Akulaleki",
        "De Mthuda Nana Thula",
        "Msaki Ungowam",
    ],
}

# G-Inspired Automall — US R&B / Hip-Hop / Pop (car dealership vibes)
GI_SLOT_QUERIES = {
    1: [  # Morning — upbeat R&B / pop energy for car promo
        "SZA 2026 official",
        "Bruno Mars 2026 official",
        "The Weeknd 2026 official",
        "Khalid 2026 official",
        "Benson Boone 2026",
        "Sabrina Carpenter 2026 official",
        "Doja Cat 2026 official",
    ],
}


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
    Uses yt-dlp scsearch — no cookies, no YouTube, no auth required.
    Returns metadata dict on success, None on failure.
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for f in TMP_DIR.iterdir():
        try: f.unlink()
        except Exception: pass

    tmp_out = str(TMP_DIR / "sc_track.%(ext)s")
    try:
        res = subprocess.run(
            [r"C:\Python314\Scripts\yt-dlp.exe",
             "--no-playlist",
             "--extract-audio", "--audio-format", "mp3", "--audio-quality", "192K",
             "--max-filesize", "12m",         # skip albums/mixes (>12MB raw)
             "--match-filter", "duration < 600",  # skip anything over 10 min
             "--print", "%(title)s|||%(uploader)s",  # print metadata before downloading
             "--no-simulate",                 # --print implies simulate in newer yt-dlp; force actual download
             "-o", tmp_out,
             "--quiet", "--no-warnings",
             f"scsearch1:{query}"],
            timeout=120, capture_output=True, text=True,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"    [SC] Timeout/missing yt-dlp: {e}")
        return None

    # Extract printed title/uploader from stdout
    title, artist = query, "SoundCloud"
    if res.stdout:
        for line in res.stdout.strip().splitlines():
            if "|||" in line:
                parts = line.split("|||", 1)
                title  = parts[0].strip() or query
                artist = parts[1].strip() or "SoundCloud"
                break

    # Find downloaded mp3
    mp3 = TMP_DIR / "sc_track.mp3"
    if not mp3.exists():
        mp3s = [f for f in TMP_DIR.glob("*.mp3") if f.stat().st_size > 50_000]
        if not mp3s:
            if res.returncode != 0 and res.stderr:
                print(f"    [SC] yt-dlp error: {res.stderr.strip()[:120]}")
            else:
                print(f"    [SC] No mp3 found after download (returncode={res.returncode})")
            return None
        mp3 = mp3s[0]

    if mp3.stat().st_size < 50_000:
        return None

    if _used_recently(title, days=7, log_file=log_file):
        print(f"    [SC] Skip (used recently): {title[:55]}")
        mp3.unlink(missing_ok=True)
        return None

    try:
        shutil.copy2(str(mp3), str(raw_out))
        mp3.unlink(missing_ok=True)
        return {"title": title, "artist": artist, "source": "soundcloud"}
    except Exception as e:
        print(f"    [SC] Copy failed: {e}")
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
    elif "--skip-if-fresh" in sys.argv and _already_fresh_today():
        print("[Music] Fresh tracks already downloaded today — skipping.")
    else:
        fetch_trending_music(archive_only=_archive_only)

    if _client != "g_inspired":
        # Pre-warm trending hashtags (BootHop only)
        print("\n[Hashtags] Pre-warming trending hashtags...")
        try:
            from fetch_trending_hashtags import fetch_today as _fth
            _fth()
        except Exception as e:
            print(f"[Hashtags] Pre-warm failed: {e}")
