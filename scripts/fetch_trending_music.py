"""
OTB_Pipeline — Daily trending music fetcher
Downloads 4 slot-specific music tracks every morning before Slot 1 runs.

Priority chain per slot:
  1. Nigeria YouTube trending     (Afrobeats / Naija chart — primary audience)
  2. UK Grime / Afroswing         (UK diaspora second audience)
  3. US R&B / Neo Soul            (Slot 1 + 4 only — broad appeal)
  4. Amapiano                     (Slot 3 — evening energy)
  5. Archive fallback             (music/archive/ — royalty-free library)

Output (4 slot-specific files):
  music/daily/track_1.mp3 -> Slot 1  7:00am  morning commute
  music/daily/track_2.mp3 -> Slot 2  12:00pm lunch scroll
  music/daily/track_3.mp3 -> Slot 3  17:30   evening peak
  music/daily/track_4.mp3 -> Slot 4  20:30   night scroll

Hook extraction: librosa finds the highest-energy 30-second window (the drop/chorus).
Falls back to ffmpeg trim from 30s if librosa unavailable.

7-day no-repeat: tracks logged to data/music_log.json (90-day rolling).
Scheduled: daily at 06:00 via Task Scheduler (OTB-MusicRefresh), before Slot 1.
"""

import json, subprocess, shutil, sys
from datetime import datetime, timedelta
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(r"C:\Users\babso\Desktop\OTB_Pipeline")
BHP  = Path(r"C:\Users\babso\Desktop\BootHopPipeline")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BHP))

from config import DATA
try:
    from config import YOUTUBE_API_KEY
except ImportError:
    from BootHopPipeline_config_shim import YOUTUBE_API_KEY  # fallback
    YOUTUBE_API_KEY = ""

# Try importing YOUTUBE_API_KEY from BHP config if OTB config doesn't export it
if not YOUTUBE_API_KEY:
    try:
        import importlib.util, sys as _sys
        spec = importlib.util.spec_from_file_location("bhp_config", str(BHP / "config.py"))
        bhp_cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bhp_cfg)
        YOUTUBE_API_KEY = getattr(bhp_cfg, "YOUTUBE_API_KEY", "")
    except Exception:
        pass

import requests as _req

DAILY_DIR = BASE / "music" / "daily"
ARCHIVE   = BHP  / "music" / "archive"   # shared royalty-free library
TMP_DIR   = DAILY_DIR / "_tmp"
MUSIC_LOG = DATA / "music_log.json"
INFO_FILE = DAILY_DIR / "daily_info.json"

DAILY_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)

UK_GRIND_KW = [
    "drill", "grind", "urban", "grime", "afroswing", "afrobeats uk",
    "central cee", "stormzy", "dave ", "skepta", "headie",
    "little simz", "pa salieu", "ghetts", "russ millions",
]
US_RNB_KW = [
    "rnb", "r&b", "neo soul", "usher", "sza", "frank ocean",
    "h.e.r.", "summer walker", "brent faiyaz", "giveon", "jhene aiko",
    "anderson paak", "daniel caesar", "khalid", "lucky daye",
]
AMAPIANO_KW = [
    "amapiano", "log drum", "piano afro", "amapiano 2025", "amapiano 2026",
    "kabza", "dj maphorisa", "focalistic", "daliwonga",
]


# ── Music log helpers ──────────────────────────────────────────────────────────
def _load_log():
    if MUSIC_LOG.exists():
        try:
            return json.loads(MUSIC_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _save_log(entry):
    log = _load_log()
    log.append(entry)
    MUSIC_LOG.write_text(json.dumps(log[-90:], indent=2, ensure_ascii=False), encoding="utf-8")

def _used_recently(title, days=7):
    log    = _load_log()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return any(
        e.get("logged_at", "") > cutoff and e.get("title", "").lower() == title.lower()
        for e in log
    )


# ── YouTube helpers ────────────────────────────────────────────────────────────
def _yt_trending(region="NG", max_results=15):
    if not YOUTUBE_API_KEY:
        return []
    try:
        r = _req.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet", "chart": "mostPopular",
                    "regionCode": region, "videoCategoryId": "10",
                    "maxResults": max_results, "key": YOUTUBE_API_KEY},
            timeout=10,
        )
        if r.ok:
            return [{"title": i["snippet"]["title"],
                     "channel": i["snippet"]["channelTitle"],
                     "video_id": i["id"]}
                    for i in r.json().get("items", [])]
    except Exception as e:
        print(f"  [Music] YT trending error ({region}): {e}")
    return []

def _yt_search(query, max_results=6):
    if not YOUTUBE_API_KEY:
        return []
    try:
        r = _req.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "q": query, "type": "video",
                    "videoCategoryId": "10", "order": "relevance",
                    "maxResults": max_results, "key": YOUTUBE_API_KEY},
            timeout=10,
        )
        if r.ok:
            return [{"title": i["snippet"]["title"],
                     "channel": i["snippet"]["channelTitle"],
                     "video_id": i["id"]["videoId"]}
                    for i in r.json().get("items", [])]
    except Exception as e:
        print(f"  [Music] YT search error: {e}")
    return []


# ── Hook extraction ────────────────────────────────────────────────────────────
def _extract_hook(src_path: Path, out_path: Path, duration_s: int = 30) -> bool:
    """Find highest-energy 30s window. Falls back to ffmpeg trim if librosa absent."""
    try:
        import librosa
        import numpy as np
        from pydub import AudioSegment

        y, sr    = librosa.load(str(src_path), duration=210, mono=True)
        rms      = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        # Smooth over ~3s
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
        # ffmpeg fallback — trim from 30s into track with dynamic fade
        try:
            fade_out_st = max(0, duration_s - 1.5)
            res = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src_path),
                 "-ss", "30", "-t", str(duration_s),
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


# ── Downloader ─────────────────────────────────────────────────────────────────
def _download_soundcloud(query: str, raw_out: Path) -> bool:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for f in TMP_DIR.iterdir():
        try: f.unlink()
        except Exception: pass

    try:
        import yt_dlp
        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(TMP_DIR / "track.%(ext)s"),
            "quiet": True, "no_warnings": True,
            "default_search": "scsearch1",
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3", "preferredquality": "192"}],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"scsearch1:{query}"])
    except Exception as e:
        if "WinError 32" not in str(e) and "being used by another process" not in str(e):
            print(f"    [SC] {str(e)[:80]}")

    mp3 = TMP_DIR / "track.mp3"
    if mp3.exists() and mp3.stat().st_size > 50_000:
        try:
            mp3.rename(raw_out); return True
        except Exception:
            shutil.copy2(str(mp3), str(raw_out)); return True
    mp3s = [f for f in TMP_DIR.glob("*.mp3") if f.stat().st_size > 50_000]
    if mp3s:
        try: mp3s[0].rename(raw_out)
        except Exception: shutil.copy2(str(mp3s[0]), str(raw_out))
        return True
    return False

def _download_youtube(video_id: str, raw_out: Path) -> bool:
    tmp = str(raw_out).replace(".mp3", "_ytdl")
    url = (f"https://www.youtube.com/watch?v={video_id}"
           if not video_id.startswith("ytsearch") else video_id)
    try:
        res = subprocess.run(
            ["yt-dlp", "--no-playlist", "--extract-audio", "--audio-format", "mp3",
             "--audio-quality", "192K", "-o", f"{tmp}.%(ext)s",
             "--quiet", "--no-warnings", url],
            timeout=120, capture_output=True, text=True,
        )
        tmp_mp3 = Path(f"{tmp}.mp3")
        if res.returncode == 0 and tmp_mp3.exists():
            tmp_mp3.rename(raw_out); return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


def _try_track(item: dict, source_label: str, slot_out: Path, used_titles: set):
    title = item.get("title", "")
    if _used_recently(title) or title in used_titles:
        print(f"    Skip (recent/used): {title[:55]}")
        return None
    vid   = item.get("video_id", "")
    query = f"{item.get('channel', '')} {title}"
    raw   = TMP_DIR / "raw_download.mp3"
    print(f"    Trying: {title[:60]}")
    ok = _download_soundcloud(query, raw) or _download_youtube(vid, raw)
    if not ok:
        return None
    hooked = _extract_hook(raw, slot_out, duration_s=60)
    raw.unlink(missing_ok=True)
    if hooked or slot_out.exists():
        return {"title": title, "artist": item.get("channel", "?"),
                "source": source_label, "logged_at": datetime.now().isoformat()}
    return None


def _archive_fallback(slot_out: Path, slot_num: int, used_titles: set):
    tracks = sorted(list(ARCHIVE.glob("*.mp3")) + list(ARCHIVE.glob("*.m4a")))
    if not tracks:
        return None
    day = datetime.now().timetuple().tm_yday
    for offset in range(len(tracks)):
        t = tracks[(day * 4 + slot_num + offset) % len(tracks)]
        if not _used_recently(t.stem) and t.stem not in used_titles:
            shutil.copy2(str(t), str(slot_out))
            return {"title": t.stem, "artist": "archive",
                    "source": "archive", "logged_at": datetime.now().isoformat()}
    t = tracks[(day * 4 + slot_num) % len(tracks)]
    shutil.copy2(str(t), str(slot_out))
    return {"title": t.stem, "artist": "archive",
            "source": "archive", "logged_at": datetime.now().isoformat()}


# ── Per-slot candidate pool ────────────────────────────────────────────────────
def _build_pool(slot_num: int):
    """
    Build ordered candidate list for a slot.
    Slot 1 (7am) morning: Nigeria + UK + US RnB
    Slot 2 (12pm) lunch:  Nigeria pick #2
    Slot 3 (5:30pm) eve:  UK Grind + Amapiano
    Slot 4 (8:30pm) night:Nigeria + US RnB (night energy)
    """
    pool = []

    if slot_num in (1, 2, 4):
        for item in _yt_trending(region="NG", max_results=15):
            pool.append((item, "nigeria"))
        for q in ("Nigeria afrobeats trending 2026", "Naija music trending afrobeats 2025"):
            for item in _yt_search(q, max_results=5):
                pool.append((item, "nigeria_search"))

    if slot_num in (1, 3):
        for item in _yt_trending(region="GB", max_results=12):
            if any(kw in item["title"].lower() for kw in UK_GRIND_KW):
                pool.append((item, "uk_grind"))
        for q in ("UK Drill Grime afroswing 2026", "UK rap grime chart 2025 2026"):
            for item in _yt_search(q, max_results=4):
                pool.append((item, "uk_grind_search"))

    if slot_num in (1, 4):
        for item in _yt_trending(region="US", max_results=10):
            if any(kw in item["title"].lower() for kw in US_RNB_KW):
                pool.append((item, "us_rnb"))
        for q in ("US RnB soul trending 2026", "neo soul smooth RnB 2025 2026"):
            for item in _yt_search(q, max_results=4):
                pool.append((item, "us_rnb_search"))

    if slot_num in (3,):
        for q in ("amapiano 2026 no copyright free", "amapiano log drum 2025 free"):
            for item in _yt_search(q, max_results=5):
                pool.append((item, "amapiano"))

    return pool


# ── Main ──────────────────────────────────────────────────────────────────────
def fetch_trending_music() -> dict:
    """
    Download 4 daily tracks (one per slot) to music/daily/.
    Returns summary dict.
    """
    print("\n[Music] Selecting today's tracks — 4 slots...")

    SLOT_LABELS = {
        1: "Morning  07:00 (commute)",
        2: "Midday   12:00 (lunch)",
        3: "Evening  17:30 (peak)",
        4: "Night    20:30 (scroll)",
    }

    info = {"date": datetime.now().strftime("%Y-%m-%d"), "tracks": []}
    used_titles: set = set()

    for slot_num in (1, 2, 3, 4):
        slot_out = DAILY_DIR / f"track_{slot_num}.mp3"
        print(f"\n  [Slot {slot_num}] {SLOT_LABELS[slot_num]}")

        pool = _build_pool(slot_num)
        # Deduplicate pool by title
        seen, deduped = set(), []
        for (item, src) in pool:
            t = item["title"]
            if t not in seen:
                seen.add(t); deduped.append((item, src))

        result = None
        for (item, src) in deduped:
            result = _try_track(item, src, slot_out, used_titles)
            if result:
                used_titles.add(result["title"])
                _save_log(result)
                size = slot_out.stat().st_size // 1024 if slot_out.exists() else 0
                print(f"  [Slot {slot_num}] OK [{src}] {result['title'][:50]} ({size}KB)")
                break

        if not result:
            print(f"  [Slot {slot_num}] No online track — using archive")
            result = _archive_fallback(slot_out, slot_num, used_titles) or {}
            if result:
                used_titles.add(result.get("title", ""))
                _save_log(result)

        info["tracks"].append({
            "slot":   slot_num,
            "title":  result.get("title", "?"),
            "source": result.get("source", "?"),
        })

    INFO_FILE.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n  [Music] Summary:")
    for t in info["tracks"]:
        flag = ("NG" if "nigeria"  in t["source"] else
                "UK" if "uk"       in t["source"] else
                "US" if "us"       in t["source"] else
                "AP" if "amapiano" in t["source"] else "A")
        print(f"    [{flag}] track_{t['slot']}.mp3 — {t['title'][:50]}")

    return info


def _already_fresh_today() -> bool:
    if not INFO_FILE.exists():
        return False
    try:
        info = json.loads(INFO_FILE.read_text(encoding="utf-8"))
        if info.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return False
        tracks = info.get("tracks", [])
        return len(tracks) == 4 and all(t.get("source", "archive") != "archive" for t in tracks)
    except Exception:
        return False


if __name__ == "__main__":
    if "--skip-if-fresh" in sys.argv and _already_fresh_today():
        print("[Music] Fresh tracks already downloaded today — skipping.")
    else:
        fetch_trending_music()

    # Pre-warm trending hashtags so Slot 1 doesn't pay the fetch cost at 7am
    print("\n[Hashtags] Pre-warming trending hashtags for today...")
    try:
        from fetch_trending_hashtags import fetch_today as _fth
        _fth()
    except Exception as e:
        print(f"[Hashtags] Pre-warm failed (will retry at slot time): {e}")
