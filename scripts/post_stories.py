"""
OTB_Pipeline — Instagram Stories poster (algo-optimized)

Instagram Stories 2026 algorithm signals applied:
1. DOUBLE-TAP BOOST: Posting a Story immediately after a Reel is the strongest single
   signal you can send — IG reads it as "this creator is fully active" and re-distributes
   the preceding Reel to an additional non-follower audience batch.
2. VISUAL POLL: Poll sticker is the highest-weight single engagement action on Stories
   (heavier than taps, replies, or DMs). API-level poll requires Meta advanced permissions,
   so we bake a YES/NOT YET visual into the image — same psychological trigger, zero API penalty.
3. DWELL TIME: We keep the image text-heavy (hook + lesson + poll) so people read and hold
   the screen, inflating dwell time which Stories algorithm uses as the primary ranking signal.
4. CTA CONSISTENCY: Story hook matches Reel hook — consistency drives "watch more" profile
   visits, which is the #1 Explore ranking signal.
5. IMAGE FORMAT: 1080x1920 (9:16) — only accepted size for Stories. JPEG quality 95 keeps
   IG from re-compressing and degrading text legibility.
6. POST TIMING: Called immediately after Reel post in pipeline — IG timestamps within 2-min
   window triggers the "creator activity spike" boost.
"""

import json, os, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA, LOGO_PATH, ASSETS

import requests
from PIL import Image, ImageDraw, ImageFont

STORY_W = 1080
STORY_H = 1920

PILLAR_COLORS = {
    "community":          (30,  58, 138),
    "family":             (124, 45,  18),
    "airport":            (21,  128,  61),
    "smart":              (67,  20,  140),
    "travel_hacks":       (14, 116, 144),
    "logistics_stories":  (30,  58, 138),
    "airport_deliveries": (21,  128,  61),
    "supply_chain":       (15,  23,  42),
}


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Stories] {msg}")


def _creds() -> tuple[str, str]:
    try:
        c = json.loads(Path(CREDS_PATH).read_text())
        ig = c.get("instagram", {})
        return ig.get("access_token", "").strip(), ig.get("ig_user_id", "").strip()
    except Exception as e:
        _log(f"Creds error: {e}"); return "", ""


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        str(ASSETS / "fonts" / ("Oswald-Bold.ttf" if bold else "Montserrat-ExtraBold.ttf")),
        r"C:\Windows\Fonts\impact.ttf" if bold else r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ]
    for fp in candidates:
        if os.path.isfile(fp):
            try: return ImageFont.truetype(fp, size)
            except Exception: pass
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bb = font.getbbox(test)
        if bb[2] - bb[0] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines


def _draw_center(draw: ImageDraw.ImageDraw, y: int, text: str,
                 font: ImageFont.FreeTypeFont, fill, shadow: bool = True):
    bb = font.getbbox(text)
    x = (STORY_W - (bb[2] - bb[0])) // 2
    if shadow:
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)
    return bb[3] - bb[1]


def _make_story_image(content: dict, dest: str) -> bool:
    hook    = content.get("hook", "")[:90]
    lesson  = content.get("lesson", "")[:130]
    pillar  = content.get("pillar", "community")
    base    = PILLAR_COLORS.get(pillar, (30, 58, 138))

    img  = Image.new("RGB", (STORY_W, STORY_H), base)
    draw = ImageDraw.Draw(img, "RGBA")

    # Gradient: darken toward bottom
    for y in range(STORY_H):
        alpha = min(200, int(y / STORY_H * 210))
        draw.rectangle([(0, y), (STORY_W, y + 1)], fill=(0, 0, 0, alpha))

    # Logo
    try:
        logo = Image.open(str(LOGO_PATH)).convert("RGBA")
        logo_w = 180
        logo = logo.resize((logo_w, int(logo.height * logo_w / logo.width)), Image.LANCZOS)
        img.paste(logo, ((STORY_W - logo_w) // 2, 80), logo)
    except Exception:
        pass

    # Hook text
    hf  = _font(54, bold=True)
    y   = 350
    for line in _wrap(hook, hf, STORY_W - 100)[:3]:
        h = _draw_center(draw, y, line, hf, (255, 255, 255))
        y += h + 14

    # Divider
    draw.rectangle([(120, y + 20), (STORY_W - 120, y + 23)], fill=(255, 255, 255, 80))
    y += 50

    # Lesson
    lf = _font(44)
    for line in _wrap(f"Lesson: {lesson}", lf, STORY_W - 120)[:4]:
        h = _draw_center(draw, y, line, lf, (255, 230, 100))
        y += h + 12

    # Visual poll
    poll_y = STORY_H - 480
    qf = _font(36)
    _draw_center(draw, poll_y, "Does this match your experience?", qf, (210, 210, 210), shadow=False)

    bf = _font(40, bold=True)
    draw.rounded_rectangle([80, poll_y + 56, 480, poll_y + 138], radius=18, fill=(37, 99, 235))
    _draw_center_in_box(draw, 80, 480, poll_y + 56, poll_y + 138, "YES  \U0001f44d", bf, (255, 255, 255))

    draw.rounded_rectangle([600, poll_y + 56, 1000, poll_y + 138], radius=18, fill=(71, 85, 105))
    _draw_center_in_box(draw, 600, 1000, poll_y + 56, poll_y + 138, "NOT YET", bf, (255, 255, 255))

    # CTA
    cf = _font(38, bold=True)
    _draw_center(draw, STORY_H - 120, "Watch our latest video  ↑", cf, (100, 220, 255))

    img.save(dest, "JPEG", quality=95)
    return True


def _draw_center_in_box(draw, x1, x2, y1, y2, text, font, fill):
    bb = font.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    bx = (x1 + x2) // 2 - tw // 2
    by = (y1 + y2) // 2 - th // 2
    draw.text((bx, by), text, font=font, fill=fill)


def _upload_to_catbox(image_path: str) -> str | None:
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "72h"},
                files={"fileToUpload": ("story.jpg", f, "image/jpeg")},
                timeout=30,
            )
        if r.status_code == 200 and r.text.strip().startswith("https://"):
            return r.text.strip()
    except Exception as e:
        _log(f"litterbox upload failed: {e}")
    return None


def _log_post(slot: int, media_id: str):
    log_path = DATA / "post_log.json"
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    log.append({"platform": "instagram_story", "slot": slot, "media_id": media_id,
                 "posted_at": datetime.utcnow().isoformat()})
    log_path.write_text(json.dumps(log, indent=2))


def post_story(content: dict, slot: int = 0) -> str | None:
    """
    Create a branded Story image and post it to Instagram Stories.
    Designed to run immediately after Reel post for maximum algo double-tap boost.
    Returns media_id on success, None on failure.
    """
    access_token, ig_user_id = _creds()
    if not access_token or not ig_user_id:
        _log("No Instagram credentials — skipping"); return None

    story_path = str(DATA / f"story_s{slot}_{datetime.now().strftime('%H%M%S')}.jpg")
    _log("Rendering story image...")
    if not _make_story_image(content, story_path):
        _log("Story render failed"); return None

    _log("Uploading to temp host...")
    image_url = _upload_to_catbox(story_path)
    if not image_url:
        _log("Temp hosting failed"); return None
    _log(f"Hosted: {image_url}")

    # Create Story container
    try:
        r = requests.post(
            f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
            data={
                "image_url":    image_url,
                "media_type":   "IMAGE",
                "is_stories":   "true",
                "access_token": access_token,
            },
            timeout=30,
        )
        d = r.json()
        if "error" in d:
            _log(f"Container error: {d['error'].get('message','')}"); return None
        container_id = d.get("id", "")
    except Exception as e:
        _log(f"Container create failed: {e}"); return None

    if not container_id:
        _log("No container ID"); return None

    # Wait for FINISHED
    for _ in range(12):
        time.sleep(5)
        try:
            st = requests.get(
                f"https://graph.instagram.com/v21.0/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
                timeout=15,
            ).json()
            sc = st.get("status_code", "")
            if sc == "FINISHED": break
            if sc in ("ERROR", "EXPIRED"):
                _log(f"Container failed: {sc}"); return None
        except Exception:
            pass

    # Publish
    try:
        r = requests.post(
            f"https://graph.instagram.com/v21.0/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=20,
        )
        media_id = r.json().get("id", "")
    except Exception as e:
        _log(f"Publish failed: {e}"); return None

    if media_id:
        _log(f"Story posted! media_id={media_id}")
        _log_post(slot, media_id)
        try: os.remove(story_path)
        except Exception: pass
        return media_id

    _log("Publish returned no media_id")
    return None
