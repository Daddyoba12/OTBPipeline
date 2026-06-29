"""
Send all OUTPUT videos to Telegram with platform labels.
Run after pipeline to make videos available for manual posting.
"""
import sys, subprocess, requests, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, OUTPUT

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def tg_text(msg):
    try:
        requests.post(f"{BASE_URL}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                      timeout=20)
    except Exception as e:
        print(f"[TG text] {e}")


def tg_video(path: Path, caption: str):
    size_mb = round(path.stat().st_size / 1_048_576, 1)
    print(f"Sending {path.name} ({size_mb}MB)...")
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/sendVideo",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption,
                      "supports_streaming": "true"},
                files={"video": (path.name, f, "video/mp4")},
                timeout=180,
            )
        ok = r.json().get("ok")
        print(f"  -> {'OK' if ok else r.json()}")
        return ok
    except Exception as e:
        print(f"  -> ERROR: {e}")
        return False


def make_ig_grade(src: Path) -> Path:
    dest = OUTPUT / (src.stem + "_ig.mp4")
    if dest.exists():
        return dest
    print(f"Creating IG warm grade from {src.name}...")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", "eq=brightness=0.03:saturation=1.12:contrast=1.02",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-c:a", "copy", str(dest)
    ], capture_output=True, timeout=180)
    return dest if dest.exists() else None


# ── Collect all base videos (no _ig / _li suffix) ─────────────────────────
all_videos = sorted(
    [f for f in OUTPUT.glob("otb_slot*.mp4")
     if "_ig" not in f.name and "_li" not in f.name],
    key=lambda f: f.stat().st_mtime
)

if not all_videos:
    print("No videos found in OUTPUT/")
    sys.exit(1)

tg_text(
    f"OTB Pipeline — {len(all_videos)} video(s) ready for posting\n"
    "Each slot sent as 3 versions: TikTok, Instagram, YouTube\n"
    "Reply to post or re-voice any of them."
)
time.sleep(1)

for vid in all_videos:
    # Read sidecar for hook text
    sidecar = vid.with_suffix(".json")
    hook = ""
    pillar = ""
    try:
        import json
        d = json.loads(sidecar.read_text(encoding="utf-8"))
        hook   = d.get("hook", "")
        pillar = d.get("pillar", "").replace("_", " ").title()
    except Exception:
        pass

    slot_num = "?"
    for part in vid.stem.split("_"):
        if part.startswith("slot"):
            slot_num = part.replace("slot", "")

    label_base = f"SLOT {slot_num} — {pillar}\n\"{hook[:80]}\""

    # TikTok / YouTube — base video
    tg_video(vid, f"{label_base}\n\nTikTok / YouTube version")
    time.sleep(2)

    # Instagram — warm-graded
    ig = make_ig_grade(vid)
    if ig:
        tg_video(ig, f"{label_base}\n\nInstagram Reel version (warm grade)")
        time.sleep(2)
    else:
        tg_text(f"Slot {slot_num} — IG grade failed, use TikTok version for IG manually.")

tg_text("All done. Post directly from here or forward to WhatsApp.")
print("All videos sent.")
