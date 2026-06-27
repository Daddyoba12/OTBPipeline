"""
OTB_Pipeline — Newspaper post renderer + Instagram feed poster (algo-optimized)

Newspaper post Instagram algorithm signals applied:
1. CONTENT VARIETY SIGNAL: Instagram explicitly rewards accounts that use multiple
   content formats (Reels + feed images + Stories). A newspaper-style IMAGE post on the
   same day as a Reel tells the algo this account is a "multi-format creator" and unlocks
   a separate distribution queue for feed content.
2. SAVE RATE = strongest feed post signal: Newspaper-style posts are highly shareable and
   saveable (people screenshot them). Save rate is weighted higher than likes on feed images.
3. 4:5 RATIO (1080x1350): Fills maximum vertical feed space on mobile — 20% more screen
   real estate than square, proven to increase impressions by 15-20% vs 1:1.
4. CAPTION HOOK: First 2 lines of caption are what users see before "more" — must be
   compelling enough to tap, which counts as an engagement signal even without a like.
5. ROTATING MASTHEADS: 5 rotating newspaper names prevent the page looking repetitive,
   which lowers unfollow rate (IG algo penalises high unfollow events).
6. PILLAR CONSISTENCY: Pillar-matched photo background + headline colour — builds visual
   brand identity, which improves follow rate from new visitors (IG tracks this).
7. POST FREQUENCY PAIRING: We post newspaper on Slots 1 and 3 (same days as YouTube)
   so the account always has at least 2 content pieces active in the same 24h window —
   IG rewards accounts that post 2+ pieces/day with a reach multiplier.
8. HASHTAGS: 15 hashtags — IG 2026 sweet spot. Under 5 = weak signal. Over 20 = treated
   as spam. Mix: 3 mega (5M+ posts), 6 mid (100K-1M), 6 micro/niche (under 100K).
"""

import json, os, sys, time, random
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA, ASSETS, LOGO_PATH, PEXELS_KEY

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

NP_W = 1080
NP_H = 1350   # 4:5 — maximum vertical feed coverage

MASTHEADS = [
    "Daily Logistics Times",
    "Global Logistics Times",
    "The BootHop Times",
    "West Africa Express",
    "The Diaspora Dispatch",
]

PILLAR_PHOTOS = {
    "community":          ["diaspora community city", "african community london", "people airport"],
    "family":             ["family reunion airport", "mother son hug", "family celebration"],
    "airport":            ["airport terminal busy", "airplane departure gate", "luggage carousel"],
    "smart":              ["business person laptop travel", "smart traveller airport", "professional airport"],
    "travel_hacks":       ["travel packing tips", "suitcase luggage", "airport departure lounge"],
    "logistics_stories":  ["delivery package city", "courier street", "parcel boxes"],
    "airport_deliveries": ["airport meeting greeting", "arrivals hall people", "luggage claim belt"],
    "supply_chain":       ["warehouse logistics", "shipping containers", "cargo freight"],
}

PILLAR_ACCENT = {
    "community":          (30,  58, 138),
    "family":             (124, 45,  18),
    "airport":            (21,  128,  61),
    "smart":              (67,  20,  140),
    "travel_hacks":       (14, 116, 144),
    "logistics_stories":  (30,  58, 138),
    "airport_deliveries": (21,  128,  61),
    "supply_chain":       (15,  23,  42),
}

HASHTAGS_BASE = "#BootHop #Logistics #DiasporaDelivery #UKNigeria #LondonToLagos"
HASHTAGS_MID  = "#AfricanDiaspora #SameDayDelivery #PeerToPeer #TrustedTraveller #ShipFromUK"
HASHTAGS_NICHE= "#NigerianInUK #LagosDelivery #DiasporaLife #SendParcelNigeria #AfricaLogistics"


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Newspaper] {msg}")


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
        r"C:\Windows\Fonts\arial.ttf",
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


def _fetch_pexels_photo(query: str) -> Image.Image | None:
    if not PEXELS_KEY:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "per_page": 5, "orientation": "portrait"},
            timeout=20,
        )
        photos = r.json().get("photos", [])
        if not photos: return None
        photo = random.choice(photos[:3])
        img_url = photo["src"].get("large", photo["src"]["original"])
        resp = requests.get(img_url, timeout=30)
        from io import BytesIO
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        return img
    except Exception as e:
        _log(f"Pexels fetch failed: {e}"); return None


def _make_masthead_index() -> int:
    return date.today().toordinal() % len(MASTHEADS)


def _make_newspaper_image(content: dict, dest: str) -> bool:
    hook    = content.get("hook", "")
    problem = content.get("problem", "")
    lesson  = content.get("lesson", "")
    pillar  = content.get("pillar", "community")

    masthead = MASTHEADS[_make_masthead_index()]
    accent   = PILLAR_ACCENT.get(pillar, (30, 58, 138))

    # Background: Pexels photo or solid colour fallback
    queries = PILLAR_PHOTOS.get(pillar, ["city logistics"])
    bg_photo = None
    for q in queries:
        bg_photo = _fetch_pexels_photo(q)
        if bg_photo: break

    if bg_photo:
        # Crop to 4:5 and desaturate for newsprint look
        bg = bg_photo.resize((NP_W, int(bg_photo.height * NP_W / bg_photo.width)), Image.LANCZOS)
        if bg.height < NP_H:
            bg = bg.resize((int(bg.width * NP_H / bg.height), NP_H), Image.LANCZOS)
        left = (bg.width - NP_W) // 2
        top  = (bg.height - NP_H) // 2
        bg   = bg.crop((left, top, left + NP_W, top + NP_H))
        bg   = ImageEnhance.Color(bg).enhance(0.25)       # near-greyscale newsprint
        bg   = ImageEnhance.Brightness(bg).enhance(0.55)  # darken for text contrast
        canvas = bg.convert("RGB")
    else:
        canvas = Image.new("RGB", (NP_W, NP_H), (240, 235, 220))  # cream fallback

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Cream overlay for newsprint texture
    draw.rectangle([(0, 0), (NP_W, NP_H)], fill=(240, 235, 220, 120))

    # ── Masthead bar ──
    mh = 110
    draw.rectangle([(0, 0), (NP_W, mh)], fill=(*accent, 255))
    mf = _font(56, bold=True)
    mb = mf.getbbox(masthead)
    mx = (NP_W - (mb[2] - mb[0])) // 2
    draw.text((mx + 2, 22 + 2), masthead, font=mf, fill=(0, 0, 0, 120))
    draw.text((mx, 22), masthead, font=mf, fill=(255, 255, 255))

    # Issue line
    issue_font = _font(24)
    issue_text = f"Today's Edition  ·  {datetime.now().strftime('%d %B %Y')}  ·  Logistics & Diaspora"
    ib = issue_font.getbbox(issue_text)
    draw.text(((NP_W - (ib[2]-ib[0])) // 2, mh + 12), issue_text, font=issue_font, fill=(60, 60, 60))

    # Divider
    draw.rectangle([(40, mh + 48), (NP_W - 40, mh + 51)], fill=(*accent, 220))
    draw.rectangle([(40, mh + 55), (NP_W - 40, mh + 57)], fill=(*accent, 120))

    # ── Headline ──
    hf     = _font(62, bold=True)
    # Convert hook into headline format (uppercase first 6 words, then title case)
    words  = hook.split()
    headline = " ".join(w.upper() if i < 4 else w.title() for i, w in enumerate(words))
    if len(headline) > 90: headline = headline[:87] + "..."

    hy = mh + 70
    for line in _wrap(headline, hf, NP_W - 80)[:3]:
        hb = hf.getbbox(line)
        draw.text((40, hy), line, font=hf, fill=(10, 10, 10))
        hy += (hb[3] - hb[1]) + 8

    # Byline
    draw.rectangle([(40, hy + 10), (NP_W - 40, hy + 12)], fill=(120, 120, 120))
    bf = _font(26)
    byline = f"Staff Reporter  |  BootHop Logistics  |  {datetime.now().strftime('%H:%M')} GMT"
    draw.text((40, hy + 18), byline, font=bf, fill=(80, 80, 80))
    hy += 55

    # ── Article columns ──
    body_text = f"{problem}  {lesson}".strip()
    col_font  = _font(32)
    col_w     = (NP_W - 100) // 2   # 2 columns
    gap       = 20
    col1_x    = 40
    col2_x    = 40 + col_w + gap
    col_y     = hy + 10

    words_body = body_text.split()
    all_lines  = _wrap(body_text, col_font, col_w)
    mid        = len(all_lines) // 2

    y = col_y
    for line in all_lines[:mid]:
        lb = col_font.getbbox(line)
        draw.text((col1_x, y), line, font=col_font, fill=(20, 20, 20))
        y += lb[3] - lb[1] + 6

    y = col_y
    for line in all_lines[mid:mid + 14]:
        lb = col_font.getbbox(line)
        draw.text((col2_x, y), line, font=col_font, fill=(20, 20, 20))
        y += lb[3] - lb[1] + 6

    col_bottom = max(col_y + len(all_lines[:mid]) * 40, col_y + 300)

    # ── Pull quote box ──
    pq_y = min(col_bottom + 20, NP_H - 280)
    draw.rectangle([(40, pq_y), (NP_W - 40, pq_y + 4)], fill=(*accent, 255))
    qf     = _font(38, bold=True)
    quote  = f"“{lesson[:90]}”"
    for i, line in enumerate(_wrap(quote, qf, NP_W - 100)[:3]):
        draw.text((50, pq_y + 14 + i * 50), line, font=qf, fill=accent)

    # ── Footer band ──
    draw.rectangle([(0, NP_H - 100), (NP_W, NP_H)], fill=(*accent, 255))

    # Logo
    try:
        logo = Image.open(str(LOGO_PATH)).convert("RGBA")
        logo_w = 140
        logo   = logo.resize((logo_w, int(logo.height * logo_w / logo.width)), Image.LANCZOS)
        canvas.paste(logo, (30, NP_H - 80), logo)
    except Exception:
        pass

    url_font = _font(30, bold=True)
    draw.text((200, NP_H - 65), "www.boothop.com", font=url_font, fill=(255, 255, 255))

    canvas.save(dest, "JPEG", quality=94)
    return True


def _upload_to_catbox(image_path: str) -> str | None:
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": ("newspaper.jpg", f, "image/jpeg")},
                timeout=30,
            )
        if r.status_code == 200 and r.text.strip().startswith("https://"):
            return r.text.strip()
    except Exception as e:
        _log(f"catbox upload failed: {e}")
    return None


def _build_caption(content: dict) -> str:
    hook    = content.get("hook", "")
    lesson  = content.get("lesson", "")
    pillar  = content.get("pillar", "")
    caption = (
        f"\U0001f4f0 BREAKING: {hook}\n\n"
        f"Read today's full report below.\n\n"
        f"\U0001f4a1 {lesson}\n\n"
        f"Same-day delivery by trusted travellers already on the route.\n\n"
        f"{HASHTAGS_BASE}\n{HASHTAGS_MID}\n{HASHTAGS_NICHE}"
    )
    return caption[:2200]


def _log_post(slot: int, media_id: str):
    log_path = DATA / "post_log.json"
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    log.append({"platform": "instagram_newspaper", "slot": slot, "media_id": media_id,
                 "posted_at": datetime.utcnow().isoformat()})
    log_path.write_text(json.dumps(log, indent=2))


def post_newspaper(content: dict, slot: int = 0) -> str | None:
    """
    Render a newspaper-style image and post to Instagram feed (not Reel).
    Content variety signal — tells IG this is a multi-format creator.
    Returns media_id on success, None on failure.
    """
    access_token, ig_user_id = _creds()
    if not access_token or not ig_user_id:
        _log("No Instagram credentials — skipping"); return None

    np_path = str(DATA / f"newspaper_s{slot}_{datetime.now().strftime('%H%M%S')}.jpg")
    _log(f"Rendering newspaper image | masthead: {MASTHEADS[_make_masthead_index()]}")
    if not _make_newspaper_image(content, np_path):
        _log("Newspaper render failed"); return None

    _log("Uploading to temp host...")
    image_url = _upload_to_catbox(np_path)
    if not image_url:
        _log("Temp host failed"); return None
    _log(f"Hosted: {image_url}")

    caption = _build_caption(content)

    # Create IG feed IMAGE container (not REELS, not STORIES)
    try:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media",
            data={
                "image_url":    image_url,
                "caption":      caption,
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
                f"https://graph.facebook.com/v21.0/{container_id}",
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
            f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=20,
        )
        media_id = r.json().get("id", "")
    except Exception as e:
        _log(f"Publish failed: {e}"); return None

    if media_id:
        _log(f"Newspaper post published! media_id={media_id}")
        _log_post(slot, media_id)
        try: os.remove(np_path)
        except Exception: pass
        return media_id

    _log("Publish returned no media_id")
    return None
