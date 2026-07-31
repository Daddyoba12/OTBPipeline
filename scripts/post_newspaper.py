"""
OTB_Pipeline — Newspaper post renderer + Instagram feed poster

Three rotating newspaper templates — parody front pages that look like real news:
  0. Boot Hop Times       — classic black/red newsprint
  1. Daily Logistics Mail — Daily Mail parody, red/white, big headline
  2. Global Logistics Times — professional trade paper, dark header

Key design principles learned from high-performing examples:
- White/cream background (not dark photo bleed) — feels like a real paper
- ONE inset portrait photo (professional Black person, Pexels) — not stock airports
- BIG impactful headline from the hook — "BRITONS PAY £145 TO SEND A £20 GIFT"
- Routes table (London→Lagos etc.) — useful + visually distinctive
- Price comparison block (£145 courier vs £15-30 traveller)
- Real Stories icons at bottom
- Rotates daily so feed never looks repetitive
"""

import json, os, re, sys, time, random
from datetime import datetime, date
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CREDS_PATH, DATA, ASSETS, LOGO_PATH, PEXELS_KEY

import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

NP_W = 1080
NP_H = 1350   # 4:5 ratio — maximum vertical feed coverage


# ── Brand constants ────────────────────────────────────────────────────────────
UK_ROUTES = [
    ("LONDON", "LAGOS"),
    ("MANCHESTER", "LONDON"),
    ("SCOTLAND", "BRISTOL"),
    ("BIRMINGHAM", "LONDON"),
    ("LONDON", "EUROPE"),
    ("GLASGOW", "LONDON"),
    ("EDINBURGH", "LONDON"),
    ("LONDON", "ABUJA"),
]

AFRICA_ROUTES = [
    ("LAGOS", "ACCRA"),
    ("ABUJA", "DAKAR"),
    ("LAGOS", "KANO"),
    ("PHC", "LAGOS"),
    ("ACCRA", "ABUJA"),
    ("LAGOS", "ABUJA"),
]

REAL_STORIES = [
    ("LEFT BEHIND\nLUGGAGE", "A suitcase missed the flight. Reunited same day."),
    ("URGENT\nDOCUMENTS", "Legal papers needed in Lagos before a deal closed."),
    ("BIRTHDAY\nGIFT", "The gift arrived 5 days late. Priceless disappointment."),
    ("ESSENTIAL\nMEDS DELAYED", "Medication from Accra to Lagos, delayed by weeks."),
]

HASHTAGS = (
    "#BootHop #Logistics #DiasporaDelivery #UKNigeria #LondonToLagos "
    "#AfricanDiaspora #SameDayDelivery #PeerToPeer #TrustedTraveller #ShipFromUK "
    "#NigerianInUK #LagosDelivery #DiasporaLife #SendParcelNigeria #AfricaLogistics"
)

# Portrait queries — professional Black people, not airports
PORTRAIT_QUERIES = {
    "community":          "professional Black man confident business",
    "family":             "black woman professional smiling portrait",
    "airport":            "black businessman airport professional",
    "smart":              "black entrepreneur business suit portrait",
    "travel_hacks":       "professional african woman confident",
    "logistics_stories":  "black logistics professional portrait",
    "airport_deliveries": "confident black man professional photo",
    "urgent_medical":     "black doctor professional portrait",
    "cost_pain":          "black businessman serious portrait",
    "courier_business":   "black delivery entrepreneur portrait",
    "personal_shopper":   "black woman professional shopper",
    "cultural_earn":      "black creative professional portrait",
    "faith_friday":       "confident black man professional portrait",
}


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Newspaper] {msg}")


def _creds() -> tuple[str, str]:
    try:
        c = json.loads(Path(CREDS_PATH).read_text())
        ig = c.get("instagram", {})
        return ig.get("access_token", "").strip(), ig.get("ig_user_id", "").strip()
    except Exception as e:
        _log(f"Creds error: {e}"); return "", ""


# ── Font helpers ────────────────────────────────────────────────────────────────

def _font(size: int, style: str = "body") -> ImageFont.FreeTypeFont:
    """style: 'headline' (Bebas), 'bold' (Montserrat ExtraBold), 'body' (Montserrat)"""
    candidates = {
        "headline": [
            str(ASSETS / "fonts" / "BebasNeue-Regular.ttf"),
            r"C:\Windows\Fonts\impact.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "bold": [
            str(ASSETS / "fonts" / "Montserrat-ExtraBold.ttf"),
            r"C:\Windows\Fonts\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "body": [
            str(ASSETS / "fonts" / "Montserrat-ExtraBold.ttf"),
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
    }
    for fp in candidates.get(style, candidates["body"]):
        if os.path.isfile(fp):
            try: return ImageFont.truetype(fp, size)
            except Exception: pass
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.getbbox(test)[2] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines


def _draw_text_wrapped(draw, text, font, x, y, max_w, fill, line_gap=6):
    """Draw wrapped text, return y after last line."""
    for line in _wrap(text, font, max_w):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.getbbox(line)[3] + line_gap
    return y


def _text_w(text: str, font) -> int:
    return font.getbbox(text)[2] - font.getbbox(text)[0]


def _make_headline(hook: str) -> str:
    """Convert AI hook into dramatic newspaper headline."""
    h = re.sub(r'^pov:?\s*', '', hook, flags=re.IGNORECASE).strip()
    h = re.sub(r'^nobody told us\s+(that\s+)?', '', h, flags=re.IGNORECASE).strip()
    h = h.rstrip('?!').strip()
    # Flip second-person to third
    h = re.sub(r"^you('re|'ve|'ll)?\s+", "FAMILIES ", h, flags=re.IGNORECASE)
    h = re.sub(r"^your\s+", "THEIR ", h, flags=re.IGNORECASE)
    # Truncate to reasonable headline length
    return h[:100]


# ── Portrait photo (Pexels) ────────────────────────────────────────────────────

def _fetch_portrait(pillar: str) -> Image.Image | None:
    if not PEXELS_KEY:
        return None
    query = PORTRAIT_QUERIES.get(pillar, "black professional portrait confident")
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "per_page": 8, "orientation": "portrait"},
            timeout=20,
        )
        photos = r.json().get("photos", [])
        if not photos: return None
        photo = random.choice(photos[:5])
        img_url = photo["src"].get("large2x", photo["src"].get("large", photo["src"]["original"]))
        resp = requests.get(img_url, timeout=30)
        return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        _log(f"Portrait fetch failed: {e}"); return None


def _crop_portrait(img: Image.Image, w: int, h: int) -> Image.Image:
    """Crop image to exact size, center-cropping."""
    ratio = max(w / img.width, h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top  = max(0, (new_h - h) // 4)  # bias toward top (face usually upper portion)
    return img.crop((left, top, left + w, top + h))


def _daily_routes(n: int = 4) -> list[tuple[str, str]]:
    """Pick n routes for today, rotating from the full list."""
    seed = date.today().toordinal()
    rng  = random.Random(seed)
    pool = UK_ROUTES.copy()
    rng.shuffle(pool)
    return pool[:n]


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE 0: BOOT HOP TIMES — classic black/red/white newsprint
# ══════════════════════════════════════════════════════════════════════════════

def _template_boothoptimes(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                            content: dict, portrait: Image.Image | None):
    W, H = NP_W, NP_H
    BLACK  = (0, 0, 0)
    WHITE  = (255, 255, 255)
    RED    = (185, 28, 28)
    CREAM  = (249, 245, 235)
    DGREY  = (40, 40, 40)
    MGREY  = (120, 120, 120)

    hook      = content.get("hook", "")
    problem   = content.get("problem", "")
    lesson    = content.get("lesson", "")
    pillar    = content.get("pillar", "community")
    headline  = _make_headline(hook).upper()
    issue_num = date.today().toordinal() % 52 + 1
    today_str = datetime.now().strftime("%B %d, %Y").upper()

    # ── Header bar (black, y=0-95) ──────────────────────────────────────────
    draw.rectangle([(0, 0), (W, 95)], fill=BLACK)

    # SPECIAL EDITION corner boxes
    se_font = _font(18, "bold")
    for bx, tx in [(10, 12), (W - 130, W - 10)]:
        draw.rectangle([(bx, 8), (bx + 120, 88)], outline=RED, width=2)
        draw.text((bx + 8, 15), "SPECIAL", font=se_font, fill=RED)
        draw.text((bx + 8, 38), "EDITION", font=se_font, fill=RED)
        dot_y = 62
        for _ in range(3):
            draw.ellipse([(bx + 10, dot_y), (bx + 16, dot_y + 6)], fill=RED)
            dot_y += 10

    # Masthead
    mf = _font(60, "headline")
    mtext = "* Boot Hop Times *"
    mw = _text_w(mtext, mf)
    draw.text(((W - mw) // 2, 18), mtext, font=mf, fill=WHITE)

    # ── Info bar (y=95-130) ─────────────────────────────────────────────────
    draw.rectangle([(0, 95), (W, 130)], fill=CREAM)
    if_font = _font(20, "body")
    info = f"VOL. 01  •  ISSUE {issue_num:02d}    CONNECTING PEOPLE. DELIVERING TRUST.    {today_str}"
    iw = _text_w(info, if_font)
    draw.text(((W - iw) // 2, 105), info, font=if_font, fill=MGREY)

    # Double rule
    draw.rectangle([(0, 130), (W, 134)], fill=BLACK)
    draw.rectangle([(0, 137), (W, 140)], fill=BLACK)

    # ── BREAKING NEWS bar (y=140-205) ───────────────────────────────────────
    draw.rectangle([(0, 140), (W, 205)], fill=RED)
    bn_font = _font(72, "headline")
    bn_text = "BREAKING NEWS"
    bnw = _text_w(bn_text, bn_font)
    draw.text(((W - bnw) // 2, 140), bn_text, font=bn_font, fill=WHITE)
    draw.rectangle([(0, 205), (W, 209)], fill=BLACK)

    # ── Headline + portrait (y=215-620) ────────────────────────────────────
    # Portrait on RIGHT side
    PHOTO_W, PHOTO_H = 360, 380
    PHOTO_X = W - PHOTO_W - 25
    PHOTO_Y = 218

    if portrait:
        ph = _crop_portrait(portrait, PHOTO_W, PHOTO_H)
        # Thin black border
        draw.rectangle([(PHOTO_X - 3, PHOTO_Y - 3), (PHOTO_X + PHOTO_W + 3, PHOTO_Y + PHOTO_H + 3)], fill=BLACK)
        canvas.paste(ph, (PHOTO_X, PHOTO_Y))

    # Headline on LEFT of photo
    hf    = _font(72, "headline")
    hf_sm = _font(58, "headline")
    max_hw = PHOTO_X - 50  # left of photo
    y = 218
    lines = _wrap(headline, hf, max_hw)
    if len(lines) > 4:
        lines = _wrap(headline, hf_sm, max_hw)
        hf_use = hf_sm
    else:
        hf_use = hf

    for i, line in enumerate(lines[:4]):
        draw.text((40, y), line, font=hf_use, fill=BLACK)
        y += hf_use.getbbox(line)[3] + 4

    # Subheadline + body text
    draw.rectangle([(40, y + 10), (max_hw if portrait else W - 40, y + 13)], fill=MGREY)
    sf  = _font(26, "bold")
    sub = problem[:150] if problem else ""
    if sub:
        y = _draw_text_wrapped(draw, sub, sf, 40, y + 18, max_hw if portrait else W - 80, DGREY, 5)

    if not portrait:
        # Fill with resolution text to avoid whitespace
        body = content.get("resolution", content.get("lesson", ""))[:280]
        if body:
            y += 10
            draw.rectangle([(40, y), (W - 40, y + 2)], fill=MGREY)
            y += 10
            bf = _font(24, "body")
            y = _draw_text_wrapped(draw, body, bf, 40, y, W - 80, DGREY, 5)

        # Also Available routes (West Africa)
        y += 14
        draw.rectangle([(40, y), (W - 40, y + 2)], fill=MGREY)
        y += 10
        draw.text((40, y), "ALSO AVAILABLE:", font=_font(22, "bold"), fill=MGREY)
        y += 30
        rng2 = random.Random(date.today().toordinal() + 1)
        pool2 = AFRICA_ROUTES.copy()
        rng2.shuffle(pool2)
        for frm, to in pool2[:3]:
            draw.ellipse([(40, y + 5), (54, y + 19)], fill=MGREY)
            draw.text((62, y), f"{frm}  →  {to}", font=_font(28, "headline"), fill=DGREY)
            y += 38
        y += 8

    # ── Divider ─────────────────────────────────────────────────────────────
    sec_y = (max(PHOTO_Y + PHOTO_H + 18, y + 18) if portrait else y + 18)
    draw.rectangle([(0, sec_y), (W, sec_y + 3)], fill=BLACK)
    draw.rectangle([(0, sec_y + 6), (W, sec_y + 8)], fill=BLACK)
    sec_y += 16

    # ── Routes table ────────────────────────────────────────────────────────
    rt_font  = _font(28, "headline")
    rtl_font = _font(22, "bold")
    routes   = _daily_routes(4)

    draw.text((40, sec_y), "TRAVELLERS NEEDED THIS WEEK", font=_font(24, "bold"), fill=MGREY)
    sec_y += 34

    for i, (frm, to) in enumerate(routes):
        row_y = sec_y + i * 52
        col_w = (W - 80) // 2
        x_off = (i % 2) * col_w + 40
        row_y = sec_y + (i // 2) * 56

        draw.ellipse([(x_off, row_y + 4), (x_off + 18, row_y + 22)], fill=RED)
        rt_text = f"{frm}  →  {to}"
        draw.text((x_off + 26, row_y), rt_text, font=rt_font, fill=BLACK)

    sec_y += (len(routes) // 2 + len(routes) % 2) * 56 + 10

    draw.rectangle([(40, sec_y), (W - 40, sec_y + 2)], fill=MGREY)
    sec_y += 12

    # ── Two info boxes ───────────────────────────────────────────────────────
    box_h   = 200
    box_y   = sec_y
    mid_x   = W // 2 - 8

    # LEFT: Monthly Gift Raffle
    draw.rectangle([(30, box_y), (mid_x, box_y + box_h)], outline=BLACK, width=2)
    draw.rectangle([(30, box_y), (mid_x, box_y + 36)], fill=BLACK)
    rf = _font(20, "bold")
    draw.text((38, box_y + 8), "MONTHLY GIFT RAFFLE", font=rf, fill=WHITE)
    gf = _font(19, "body")
    raffle_items = [
        "+  Shopping Vouchers",
        "+  Travel Accessories",
        "+  Exclusive BootHop Rewards",
    ]
    gy = box_y + 46
    for item in raffle_items:
        draw.text((40, gy), item, font=gf, fill=DGREY)
        gy += 34
    draw.text((40, gy + 4), "Every booking this month enters", font=_font(17, "body"), fill=MGREY)
    draw.text((40, gy + 22), "our FREE prize draw.", font=_font(17, "body"), fill=MGREY)

    # RIGHT: People Powered Network
    draw.rectangle([(mid_x + 16, box_y), (W - 30, box_y + box_h)], outline=BLACK, width=2)
    draw.rectangle([(mid_x + 16, box_y), (W - 30, box_y + 36)], fill=BLACK)
    draw.text((mid_x + 24, box_y + 8), "PEOPLE POWERED NETWORK", font=rf, fill=WHITE)
    pf  = _font(19, "body")
    ppn = [
        ">  NOT REPLACING LOGISTICS",
        ">  MAKING MOVEMENT SMARTER",
        ">  FAST. TRUSTED. VERIFIED.",
    ]
    py = box_y + 46
    for item in ppn:
        draw.text((mid_x + 24, py), item, font=pf, fill=DGREY)
        py += 34

    sec_y = box_y + box_h + 16

    # ── Bottom black footer ──────────────────────────────────────────────────
    foot_y = H - 170
    draw.rectangle([(0, foot_y), (W, H)], fill=BLACK)

    # Logo
    try:
        logo = Image.open(str(LOGO_PATH)).convert("RGBA")
        lw = 130
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        canvas.paste(logo, (25, foot_y + 12), logo)
    except Exception:
        pass

    url_f = _font(34, "headline")
    draw.text((175, foot_y + 10), "BOOTHOP.COM", font=url_f, fill=WHITE)

    # Service icons row
    icons = ["SAME-DAY\nDELIVERY", "AIRPORT\nTO-AIRPORT", "ROAD\nROUTES", "UK &\nINTL"]
    icon_f = _font(17, "bold")
    icon_x = 40
    for label in icons:
        draw.rectangle([(icon_x, foot_y + 58), (icon_x + 118, foot_y + 105)], outline=WHITE, width=1)
        for il, line in enumerate(label.split("\n")):
            draw.text((icon_x + 6, foot_y + 62 + il * 20), line, font=icon_f, fill=WHITE)
        icon_x += 130

    # Quote strip
    qf  = _font(22, "bold")
    qtext = '"SOMEONE IS ALREADY GOING YOUR WAY. WHY NOT SEND IT WITH THEM?"'
    qw   = _text_w(qtext, qf)
    if qw > W - 60:
        qtext = '"SOMEONE IS ALREADY GOING YOUR WAY. WHY NOT SEND WITH THEM?"'
    draw.text(((W - min(qw, W - 60)) // 2, foot_y + 118),
              qtext[:75] if qw > W - 60 else qtext, font=qf, fill=WHITE)

    # Safe/Secure footer strip
    sf2 = _font(18, "body")
    draw.text((40,  foot_y + 148), "✔ SAFE & SECURE", font=sf2, fill=MGREY)
    draw.text((300, foot_y + 148), "❤ VERIFIED TRAVELLERS", font=sf2, fill=MGREY)
    draw.text((620, foot_y + 148), "★ 24/7 SUPPORT", font=sf2, fill=MGREY)


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE 1: DAILY LOGISTICS MAIL — Daily Mail parody
# ══════════════════════════════════════════════════════════════════════════════

def _template_dailymail(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                         content: dict, portrait: Image.Image | None):
    W, H = NP_W, NP_H
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    RED   = (185, 28, 28)
    LGREY = (245, 245, 245)
    DGREY = (30, 30, 30)
    MGREY = (100, 100, 100)

    hook      = content.get("hook", "")
    problem   = content.get("problem", "")
    lesson    = content.get("lesson", "")
    headline  = _make_headline(hook).upper()
    today_str = datetime.now().strftime("%A, %d %B %Y").upper()

    # ── Masthead (y=0-75) ──────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, 75)], fill=WHITE)

    # DM-style logo box
    draw.rectangle([(10, 8), (85, 68)], fill=BLACK)
    draw.text((18, 12), "DLM", font=_font(36, "headline"), fill=WHITE)

    mf = _font(50, "headline")
    mt = "Daily Logistics Mail"
    draw.text((100, 14), mt, font=mf, fill=BLACK)

    # Scan box (right side)
    draw.rectangle([(W - 90, 8), (W - 10, 68)], outline=BLACK, width=2)
    sf = _font(13, "bold")
    draw.text((W - 82, 12), "SCAN", font=sf, fill=BLACK)
    draw.text((W - 82, 28), "TO READ", font=sf, fill=BLACK)
    draw.text((W - 82, 44), "MORE", font=sf, fill=BLACK)

    # Date bar
    draw.rectangle([(0, 75), (W, 100)], fill=LGREY)
    df = _font(18, "body")
    draw.text((10, 80), today_str, font=df, fill=MGREY)
    draw.text((W - 200, 80), "dailylogisticsmail.com  £1.10", font=df, fill=MGREY)

    draw.rectangle([(0, 100), (W, 103)], fill=BLACK)

    # ── Exclusive banner (y=103-140) ───────────────────────────────────────
    draw.rectangle([(0, 103), (W, 140)], fill=RED)
    ef  = _font(26, "bold")
    etext = "EXCLUSIVE: FAMILIES HIT BY SKY-HIGH DELIVERY COSTS"
    ew   = _text_w(etext, ef)
    draw.text(((W - ew) // 2, 109), etext, font=ef, fill=WHITE)
    draw.rectangle([(0, 140), (W, 142)], fill=BLACK)

    # ── Main content: left headline + right sidebar ─────────────────────────
    # RIGHT sidebar (x=680-1050): travellers needed + routes + raffle
    SB_X = 675
    SB_Y = 150

    draw.rectangle([(SB_X, SB_Y), (W - 20, SB_Y + 36)], fill=BLACK)
    draw.text((SB_X + 8, SB_Y + 6), "TRAVELLERS NEEDED", font=_font(22, "bold"), fill=WHITE)
    draw.text((SB_X + 8, SB_Y + 24), "THIS WEEK", font=_font(22, "bold"), fill=RED)

    routes = _daily_routes(4)
    ry = SB_Y + 45
    for frm, to in routes:
        draw.ellipse([(SB_X + 5, ry + 4), (SB_X + 19, ry + 18)], fill=RED)
        draw.text((SB_X + 25, ry), f"{frm} → {to}", font=_font(22, "headline"), fill=BLACK)
        rf2 = _font(16, "body")
        draw.text((SB_X + 25, ry + 26), "Frequent travellers needed", font=rf2, fill=MGREY)
        ry += 55

    draw.rectangle([(SB_X, ry + 5), (W - 20, ry + 7)], fill=MGREY)
    ry += 16

    # Free Gift Raffle in sidebar
    draw.rectangle([(SB_X, ry), (W - 20, ry + 28)], fill=RED)
    draw.text((SB_X + 8, ry + 4), "FREE GIFT RAFFLE", font=_font(22, "bold"), fill=WHITE)
    gf = _font(18, "body")
    gy = ry + 35
    for item in ["+  Shopping Vouchers", "+  Travel Accessories", "+  Exciting Rewards"]:
        draw.text((SB_X + 10, gy), item, font=gf, fill=DGREY)
        gy += 28
    draw.text((SB_X + 10, gy + 4),
              "Every verified traveller", font=_font(17, "body"), fill=MGREY)
    draw.text((SB_X + 10, gy + 22),
              "completes a journey this month.", font=_font(17, "body"), fill=MGREY)

    # LEFT column: big headline + portrait + article
    LCOL_W = SB_X - 55
    y = 150

    # Big headline
    hf = _font(80, "headline")
    hf2 = _font(64, "headline")
    lines = _wrap(headline, hf, LCOL_W)
    if len(lines) > 5:
        lines = _wrap(headline, hf2, LCOL_W)
        hf_use = hf2
    else:
        hf_use = hf

    for line in lines[:5]:
        draw.text((40, y), line, font=hf_use, fill=BLACK)
        y += hf_use.getbbox(line)[3] + 3

    # Subheadline
    draw.rectangle([(40, y + 8), (LCOL_W + 20, y + 10)], fill=MGREY)
    sf2 = _font(24, "bold")
    sub = f"Soaring costs and slow delivery leave families frustrated and out of pocket"
    y = _draw_text_wrapped(draw, sub, sf2, 40, y + 16, LCOL_W, DGREY, 4)

    # Price comparison box
    y += 12
    draw.rectangle([(40, y), (LCOL_W + 20, y + 95)], outline=RED, width=3)
    draw.rectangle([(40, y), (LCOL_W + 20, y + 30)], fill=RED)
    draw.text((50, y + 5), "THE REAL COST OF SENDING", font=_font(20, "bold"), fill=WHITE)
    cf = _font(22, "bold")
    pf2 = _font(18, "body")
    draw.text((55, y + 38), "COURIER QUOTE", font=pf2, fill=MGREY)
    draw.text((55, y + 57), "£145", font=_font(36, "headline"), fill=BLACK)
    draw.text((55, y + 82), "7-14 days", font=pf2, fill=MGREY)

    mid_box = LCOL_W // 2 + 20
    draw.text((mid_box, y + 38), "SAME DAY WITH", font=pf2, fill=MGREY)
    draw.text((mid_box, y + 52), "A TRAVELLER", font=pf2, fill=MGREY)
    draw.text((mid_box, y + 68), "£15-£30", font=_font(32, "headline"), fill=RED)
    draw.text((mid_box, y + 82), "Next Day", font=pf2, fill=MGREY)

    y += 105

    # Portrait photo (if space allows, below headline)
    if portrait and y < 680:
        ph_h = min(220, 680 - y)
        ph = _crop_portrait(portrait, LCOL_W - 20, ph_h)
        draw.rectangle([(38, y - 2), (38 + LCOL_W - 20 + 4, y + ph_h + 2)], fill=BLACK)
        canvas.paste(ph, (40, y))
        y += ph_h + 14

    # Article text
    af = _font(21, "body")
    article = problem[:300] if problem else hook
    y = _draw_text_wrapped(draw, article, af, 40, y + 4, LCOL_W, DGREY, 5)

    # ── Divider ─────────────────────────────────────────────────────────────
    sec_y = max(y + 12, 860)
    draw.rectangle([(0, sec_y), (W, sec_y + 3)], fill=BLACK)
    sec_y += 6

    # ── Real Problems. Real People. ─────────────────────────────────────────
    draw.rectangle([(0, sec_y), (W, sec_y + 32)], fill=BLACK)
    rph = _font(24, "bold")
    draw.text((W // 2 - _text_w("REAL PROBLEMS. REAL PEOPLE.", rph) // 2, sec_y + 5),
              "REAL PROBLEMS. REAL PEOPLE.", font=rph, fill=WHITE)
    sec_y += 38

    box_w = (W - 50) // 4
    for i, (label, desc) in enumerate(REAL_STORIES):
        bx = 10 + i * (box_w + 10)
        draw.rectangle([(bx, sec_y), (bx + box_w, sec_y + 100)], outline=MGREY, width=1)
        lf = _font(17, "bold")
        df2 = _font(15, "body")
        ly = sec_y + 6
        for ln in label.split("\n"):
            draw.text((bx + 6, ly), ln, font=lf, fill=BLACK)
            ly += 20
        _draw_text_wrapped(draw, desc[:60], df2, bx + 6, ly + 4, box_w - 10, MGREY, 4)

    sec_y += 110

    # ── Footer ─────────────────────────────────────────────────────────────
    foot_top = max(sec_y + 10, H - 190)
    draw.rectangle([(0, foot_top), (W, H)], fill=LGREY)
    draw.rectangle([(0, foot_top), (W, foot_top + 3)], fill=RED)

    draw.text((40, foot_top + 12), "THERE'S A SMARTER WAY", font=_font(44, "headline"), fill=BLACK)
    draw.text((40, foot_top + 60),
              "Why pay more and wait longer when someone is already going your way?",
              font=_font(21, "body"), fill=DGREY)

    # Logo + details
    try:
        logo = Image.open(str(LOGO_PATH)).convert("RGBA")
        lw   = 110
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        canvas.paste(logo, (40, foot_top + 100), logo)
    except Exception:
        pass

    draw.text((165, foot_top + 105), "BootHop.com", font=_font(36, "headline"), fill=BLACK)
    draw.text((165, foot_top + 148),
              "The People Powered Network  |  Verified Travellers  |  Same Day Delivery",
              font=_font(18, "body"), fill=MGREY)


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE 2: GLOBAL LOGISTICS TIMES — trade paper, dark olive header
# ══════════════════════════════════════════════════════════════════════════════

def _template_logistics(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                         content: dict, portrait: Image.Image | None):
    W, H = NP_W, NP_H
    OLIVE  = (22, 55, 40)
    GOLD   = (251, 191, 36)
    WHITE  = (255, 255, 255)
    CREAM  = (248, 244, 234)
    BLACK  = (0, 0, 0)
    DGREY  = (30, 30, 30)
    MGREY  = (110, 110, 110)
    RED    = (185, 28, 28)

    hook      = content.get("hook", "")
    problem   = content.get("problem", "")
    resolution= content.get("resolution", "")
    lesson    = content.get("lesson", "")
    headline  = _make_headline(hook).upper()
    today_str = datetime.now().strftime("%A, %d %B %Y").upper()

    # ── Header (y=0-85) ────────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, 85)], fill=OLIVE)

    # GLT logo box
    draw.rectangle([(10, 8), (75, 78)], fill=GOLD)
    draw.text((16, 16), "GLT", font=_font(40, "headline"), fill=OLIVE)

    mf = _font(52, "headline")
    draw.text((90, 16), "Global Logistics Times", font=mf, fill=WHITE)

    # QR box
    draw.rectangle([(W - 88, 8), (W - 10, 78)], outline=GOLD, width=2)
    qf = _font(13, "bold")
    for il, ln in enumerate(["SCAN TO", "READ MORE"]):
        draw.text((W - 80, 20 + il * 18), ln, font=qf, fill=GOLD)

    # Date bar
    draw.rectangle([(0, 85), (W, 110)], fill=GOLD)
    df = _font(18, "bold")
    draw.text((10, 90), today_str, font=df, fill=OLIVE)
    draw.text((W - 380, 90), "THE VOICE OF LOGISTICS IN WEST AFRICA", font=df, fill=OLIVE)
    draw.rectangle([(0, 110), (W, 113)], fill=OLIVE)

    # ── Exclusive banner (y=113-155) ───────────────────────────────────────
    draw.rectangle([(0, 113), (W, 155)], fill=CREAM)
    draw.rectangle([(10, 118), (W - 10, 150)], outline=OLIVE, width=2)
    ef  = _font(26, "bold")
    etxt = "EXCLUSIVE REPORT:  THE PEOPLE MOVING WEST AFRICA'S DELIVERIES"
    ew   = _text_w(etxt, ef)
    if ew > W - 40:
        ef = _font(22, "bold")
        ew = _text_w(etxt, ef)
    draw.text(((W - ew) // 2, 123), etxt, font=ef, fill=OLIVE)
    draw.rectangle([(0, 155), (W, 158)], fill=OLIVE)

    # ── Main content ────────────────────────────────────────────────────────
    # Right sidebar: routes + BootHop solution
    SB_X = 700
    sb_y = 165

    draw.rectangle([(SB_X, sb_y), (W - 15, sb_y + 30)], fill=OLIVE)
    draw.text((SB_X + 8, sb_y + 5), "ROUTES IN HIGH DEMAND", font=_font(20, "bold"), fill=GOLD)
    sb_y += 38

    routes = _daily_routes(5)
    for frm, to in routes:
        draw.ellipse([(SB_X + 6, sb_y + 5), (SB_X + 20, sb_y + 19)], fill=GOLD)
        draw.text((SB_X + 28, sb_y + 1), f"{frm} → {to}", font=_font(24, "headline"), fill=BLACK)
        draw.text((SB_X + 28, sb_y + 26), "Travellers available", font=_font(16, "body"), fill=MGREY)
        sb_y += 52

    draw.rectangle([(SB_X, sb_y + 5), (W - 15, sb_y + 7)], fill=MGREY)
    sb_y += 18

    # BootHop solution box
    draw.rectangle([(SB_X, sb_y), (W - 15, sb_y + 30)], fill=OLIVE)
    draw.text((SB_X + 8, sb_y + 5), "THE BOOTHOP SOLUTION", font=_font(20, "bold"), fill=GOLD)
    sb_y += 38
    sol_items = [">  People Powered", ">  Secure & Verified", ">  Airport to Airport", ">  Real-Time Updates"]
    for item in sol_items:
        draw.text((SB_X + 10, sb_y), item, font=_font(19, "bold"), fill=DGREY)
        sb_y += 30

    # Left main column
    LCOL_W = SB_X - 50
    y = 165

    # Headline
    hf  = _font(68, "headline")
    hf2 = _font(54, "headline")
    lines = _wrap(headline, hf, LCOL_W)
    if len(lines) > 4:
        lines = _wrap(headline, hf2, LCOL_W)
        hf_use = hf2
    else:
        hf_use = hf

    for line in lines[:4]:
        draw.text((30, y), line, font=hf_use, fill=BLACK)
        y += hf_use.getbbox(line)[3] + 4

    # Portrait photo
    if portrait and y < 620:
        ph_h = min(260, 640 - y)
        ph_w = min(LCOL_W - 20, 420)
        ph   = _crop_portrait(portrait, ph_w, ph_h)
        draw.rectangle([(28, y + 6), (28 + ph_w + 4, y + ph_h + 10)], fill=BLACK)
        canvas.paste(ph, (30, y + 8))
        # Caption
        draw.text((30, y + ph_h + 14),
                  "BootHop Co-Founder  |  Beyond Delivery",
                  font=_font(18, "body"), fill=MGREY)
        y += ph_h + 40

    # Sub text
    draw.rectangle([(30, y + 6), (LCOL_W, y + 8)], fill=MGREY)
    bdf = _font(23, "body")
    y   = _draw_text_wrapped(draw, problem[:300] if problem else hook, bdf, 30, y + 14, LCOL_W, DGREY, 5)

    # ── Quote bar ─────────────────────────────────────────────────────────
    sec_y = max(y + 20, 860)
    draw.rectangle([(0, sec_y), (W, sec_y + 5)], fill=OLIVE)
    qf2   = _font(34, "headline")
    quote = "“MOVEMENT ALREADY EXISTS. WE MAKE IT WORK SMARTER.”"
    qw    = _text_w(quote, qf2)
    if qw > W - 60:
        qf2  = _font(28, "headline")
    draw.text(((W - min(_text_w(quote, qf2), W - 40)) // 2, sec_y + 12),
              quote, font=qf2, fill=OLIVE)
    sec_y += 62

    # ── Real Stories bottom ────────────────────────────────────────────────
    draw.rectangle([(0, sec_y), (W, sec_y + 32)], fill=OLIVE)
    rsh = _font(24, "bold")
    draw.text(((W - _text_w("REAL STORIES. REAL IMPACT.", rsh)) // 2, sec_y + 5),
              "REAL STORIES. REAL IMPACT.", font=rsh, fill=GOLD)
    sec_y += 40

    box_w4 = (W - 50) // 4
    for i, (label, desc) in enumerate(REAL_STORIES):
        bx = 10 + i * (box_w4 + 10)
        draw.rectangle([(bx, sec_y), (bx + box_w4, sec_y + 105)], outline=OLIVE, width=1)
        draw.rectangle([(bx, sec_y), (bx + box_w4, sec_y + 28)], fill=OLIVE)
        lf = _font(15, "bold")
        ly = sec_y + 4
        for ln in label.split("\n"):
            draw.text((bx + 4, ly), ln, font=lf, fill=GOLD)
            ly += 17
        _draw_text_wrapped(draw, desc[:65], _font(14, "body"), bx + 4, sec_y + 33, box_w4 - 8, DGREY, 4)

    sec_y += 120

    # ── Footer ─────────────────────────────────────────────────────────────
    foot_y = max(sec_y + 8, H - 145)
    draw.rectangle([(0, foot_y), (W, H)], fill=OLIVE)

    draw.text((30, foot_y + 10), "A NEW NARRATIVE. A BETTER WAY FORWARD.", font=_font(36, "headline"), fill=GOLD)
    draw.text((30, foot_y + 56), "People Powered. Purpose Driven. West Africa Focused.", font=_font(22, "bold"), fill=WHITE)

    try:
        logo = Image.open(str(LOGO_PATH)).convert("RGBA")
        lw = 100
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        canvas.paste(logo, (30, foot_y + 90), logo)
    except Exception:
        pass

    draw.text((145, foot_y + 95), "BootHop.com", font=_font(30, "headline"), fill=WHITE)

    icons_x = W - 340
    for label in ["VERIFIED\nTRAVELLERS", "SAME-DAY\nDELIVERY", "UK &\nINTERNATL"]:
        draw.rectangle([(icons_x, foot_y + 90), (icons_x + 100, foot_y + 138)], outline=GOLD, width=1)
        for il, ln in enumerate(label.split("\n")):
            draw.text((icons_x + 6, foot_y + 95 + il * 20), ln, font=_font(15, "bold"), fill=WHITE)
        icons_x += 112


# ══════════════════════════════════════════════════════════════════════════════
# MAIN IMAGE BUILDER
# ══════════════════════════════════════════════════════════════════════════════

TEMPLATES = [_template_boothoptimes, _template_dailymail, _template_logistics]
TEMPLATE_NAMES = ["Boot Hop Times", "Daily Logistics Mail", "Global Logistics Times"]


def _make_newspaper_image(content: dict, dest: str) -> bool:
    pillar   = content.get("pillar", "community")
    tmpl_idx = date.today().toordinal() % len(TEMPLATES)

    _log(f"Template: {TEMPLATE_NAMES[tmpl_idx]}")

    # Fetch portrait photo (professional Black person from Pexels)
    portrait = _fetch_portrait(pillar)
    if portrait:
        _log("Portrait fetched from Pexels")
    else:
        _log("No portrait (Pexels unavailable) — text-only layout")

    # White canvas base
    canvas = Image.new("RGB", (NP_W, NP_H), (255, 255, 255))
    draw   = ImageDraw.Draw(canvas)

    try:
        TEMPLATES[tmpl_idx](canvas, draw, content, portrait)
    except Exception as e:
        _log(f"Template render error: {e}")
        import traceback; traceback.print_exc()
        return False

    canvas.save(dest, "JPEG", quality=95)
    return True


# ══════════════════════════════════════════════════════════════════════════════
# POSTING (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def _upload_image_host(image_path: str) -> str | None:
    """Upload to Litterbox first, fall back to Catbox."""
    for name, url, field in [
        ("Litterbox", "https://litterbox.catbox.moe/resources/internals/api.php", "fileToUpload"),
        ("Catbox",    "https://catbox.moe/user/api.php", "fileToUpload"),
    ]:
        try:
            data = {"reqtype": "fileupload"}
            if name == "Litterbox": data["time"] = "72h"
            with open(image_path, "rb") as f:
                r = requests.post(url, data=data,
                                  files={field: ("newspaper.jpg", f, "image/jpeg")},
                                  timeout=30)
            if r.status_code == 200 and r.text.strip().startswith("https://"):
                _log(f"Hosted via {name}")
                return r.text.strip()
        except Exception as e:
            _log(f"{name} upload failed: {e}")
    return None


def _build_caption(content: dict) -> str:
    hook   = content.get("hook", "")
    lesson = content.get("lesson", "")
    return (
        f"\U0001f4f0 BREAKING: {hook}\n\n"
        f"\U0001f4a1 {lesson}\n\n"
        f"Same-day delivery by trusted travellers already on the route.\n"
        f"Visit boothop.com to book or list your next trip.\n\n"
        f"{HASHTAGS}"
    )[:2200]


def _log_post(slot: int, media_id: str):
    log_path = DATA / "post_log.json"
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        log = []
    log.append({"platform": "instagram_newspaper", "slot": slot,
                 "media_id": media_id, "posted_at": datetime.utcnow().isoformat()})
    log_path.write_text(json.dumps(log, indent=2))


def post_newspaper(content: dict, slot: int = 0) -> str | None:
    """
    Render a newspaper front page and post to Instagram feed.
    Returns media_id on success, None on failure.
    """
    access_token, ig_user_id = _creds()
    if not access_token or not ig_user_id:
        _log("No Instagram credentials — skipping"); return None

    np_path = str(DATA / f"newspaper_s{slot}_{datetime.now().strftime('%H%M%S')}.jpg")
    if not _make_newspaper_image(content, np_path):
        _log("Newspaper render failed"); return None

    image_url = _upload_image_host(np_path)
    if not image_url:
        _log("Image host failed"); return None
    _log(f"Hosted: {image_url}")

    caption = _build_caption(content)

    try:
        r = requests.post(
            f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
            data={"image_url": image_url, "caption": caption, "access_token": access_token},
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
        _log(f"Newspaper published! media_id={media_id}")
        _log_post(slot, media_id)
        try: os.remove(np_path)
        except Exception: pass
        return media_id

    _log("Publish returned no media_id")
    return None
