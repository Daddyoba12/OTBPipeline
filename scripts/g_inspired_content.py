"""
G-Inspired Automall — AI content generator
Picks a random car from inventory and generates a viral 5-beat video script.
Returns a content dict fully compatible with render_video.py.
"""

import json, random, sys, re
from datetime import date, timedelta
from pathlib import Path

import os, re as _re
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA as _DATA, OPENAI_API_KEY
import requests

# Respect OTB_CLIENT_BASE so data stays in the client folder
_client_base = os.environ.get("OTB_CLIENT_BASE")
_data_dir    = Path(_client_base) / "data" if _client_base else _DATA

INVENTORY_FILE  = _data_dir / "g_inspired_inventory.json"
USED_CARS_LOG   = _data_dir / "g_inspired_used_cars.json"
USED_COOLDOWN   = 14

# Client profile: prefer client folder's copy, fall back to OTB shared copy
_profile_local  = Path(_client_base) / "client_profile.json" if _client_base else None
CLIENT_PROFILE  = (_profile_local if _profile_local and _profile_local.exists()
                   else Path(__file__).parent.parent / "client_profiles" / "g-inspired.json")


# ── Inventory helpers ─────────────────────────────────────────────────────────

def _load_inventory() -> list:
    try:
        return json.loads(INVENTORY_FILE.read_text(encoding="utf-8")).get("cars", [])
    except Exception:
        return []


def _recently_used_cars(days: int = USED_COOLDOWN) -> set:
    if not USED_CARS_LOG.exists():
        return set()
    try:
        log    = json.loads(USED_CARS_LOG.read_text(encoding="utf-8"))
        cutoff = date.today() - timedelta(days=days)
        return {e["key"] for e in log if date.fromisoformat(e["date"]) >= cutoff}
    except Exception:
        return set()


def _log_used_car(car: dict):
    key = f"{car['year']}_{car['make']}_{car['model']}"
    log = []
    if USED_CARS_LOG.exists():
        try:
            log = json.loads(USED_CARS_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    log.append({"key": key, "date": date.today().isoformat(), "car": car})
    USED_CARS_LOG.write_text(json.dumps(log[-100:], indent=2, ensure_ascii=False), encoding="utf-8")


def _refresh_inventory() -> list:
    """Auto-refresh inventory if >24h old, then return car list."""
    try:
        from scrape_ginspired_inventory import refresh_if_stale
        return refresh_if_stale(_data_dir)
    except Exception as e:
        print(f"  [Inventory] Refresh skipped: {e}")
        return _load_inventory()


def pick_car() -> dict | None:
    """Auto-refresh inventory if stale, then pick a random unfeatured car."""
    cars     = _refresh_inventory()
    used     = _recently_used_cars()
    eligible = [c for c in cars
                if f"{c['year']}_{c['make']}_{c['model']}" not in used]
    if not eligible:
        eligible = cars   # all used → reset
    if not eligible:
        return None
    return random.choice(eligible)


# ── Claude call ───────────────────────────────────────────────────────────────

def _call_claude(prompt: str, max_tokens: int = 1400) -> str:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model":      "gpt-4o",
            "max_tokens": max_tokens,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("No JSON found in Claude response")
    return json.loads(m.group())


# ── Actor variety — rotated every run so faces/clothes never repeat ───────────
# Each entry: (customer_desc, driver_desc, confident_desc)
# Used to customise clips 2, 5, 6, 7 so Pexels returns different people each run.
_ACTOR_VARIANTS = [
    ("African American man",        "Black man",               "Black man confident"),
    ("young Black woman",           "African American woman",  "Black woman professional"),
    ("Hispanic couple",             "Hispanic man",            "Hispanic man confident"),
    ("mixed race couple",           "young woman",             "woman stylish confident"),
    ("African American couple",     "Black couple",            "Black professional"),
    ("young Black man",             "young man",               "young man stylish"),
    ("diverse couple",              "woman casual",            "woman confident car"),
    ("older African American man",  "older man",               "mature man suit"),
    ("Black family",                "Black woman",             "African American woman confident"),
    ("professional Black woman",    "professional woman",      "businesswoman confident"),
]

_STYLE_TAGS = [
    "casual jeans", "business casual", "streetwear", "summer dress",
    "polo shirt", "blazer", "athleisure", "smart casual",
]


def _pick_actor() -> dict:
    """Pick a random actor descriptor set for this run."""
    customer, driver, confident = random.choice(_ACTOR_VARIANTS)
    style = random.choice(_STYLE_TAGS)
    return {"customer": customer, "driver": driver, "confident": confident, "style": style}


# ── Pexels-proven query builder ───────────────────────────────────────────────

# Models/makes with enough stock footage to search by name
_ICONIC_MAKES  = {"BMW", "Mercedes", "Mercedes-Benz", "Porsche", "Ferrari", "Lamborghini",
                  "Jaguar", "Audi", "Land Rover", "Range Rover", "Lexus", "Cadillac",
                  "Bentley", "Rolls-Royce", "Maserati", "Alfa Romeo"}
_MODEL_QUERIES = {
    "Mustang":      "Ford Mustang sports car",
    "Camaro":       "Chevrolet Camaro muscle car",
    "Corvette":     "Corvette sports car",
    "Charger":      "Dodge Charger muscle car",
    "Challenger":   "Dodge Challenger muscle car",
    "F-150":        "Ford F-150 pickup truck",
    "F150":         "Ford F-150 pickup truck",
    "Silverado":    "Chevrolet Silverado pickup",
    "Ram":          "Ram pickup truck",
    "Tacoma":       "Toyota Tacoma truck",
    "Tundra":       "Toyota Tundra pickup",
    "Wrangler":     "Jeep Wrangler",
    "Bronco":       "Ford Bronco SUV",
    "Range Rover":  "Range Rover luxury SUV",
    "Discovery":    "Land Rover Discovery",
    "Grand Cherokee":"Jeep Grand Cherokee",
    "Explorer":     "Ford Explorer SUV",
    "4Runner":      "Toyota 4Runner SUV",
    "Highlander":   "Toyota Highlander SUV",
    "Durango":      "Dodge Durango SUV",
    "Suburban":     "Chevrolet Suburban SUV",
    "Navigator":    "Lincoln Navigator luxury SUV",
    "Escalade":     "Cadillac Escalade",
    "Telluride":    "Kia Telluride SUV",
    "Pilot":        "Honda Pilot SUV",
}

def _car_pexels_queries(make: str, model: str, category: str) -> tuple[str, str]:
    """Return (clip0_query, clip1_query) guaranteed to find automotive footage on Pexels."""
    if model in _MODEL_QUERIES:
        q0 = _MODEL_QUERIES[model]
    elif make in _ICONIC_MAKES:
        q0 = f"{make} {category}"
    elif category == "truck":
        q0 = f"{make} truck"
    elif category == "SUV":
        q0 = f"{make} SUV"
    else:
        q0 = f"{make} sedan"

    if category == "truck":
        q1 = "pickup truck highway driving"
    elif category == "SUV":
        q1 = "SUV driving road scenic"
    else:
        q1 = "luxury sedan driving highway"

    return q0, q1


# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_prompt(car: dict, profile: dict) -> str:
    brand      = profile.get("brand_name", "G-Inspired Automall")
    location   = profile.get("location", "Washington, IL")
    phone      = profile.get("phone", "(309) 713-1020")
    website    = profile.get("website", "ginspiredautomall.com").replace("https://www.", "")
    lines      = profile.get("brand_lines", ["Good cars. Real prices."])
    brand_line = random.choice(lines)

    year    = car["year"]
    make    = car["make"]
    model   = car["model"]
    trim    = car.get("trim", "")
    price   = car["price"]
    miles   = car["mileage"]
    price_f = f"${price:,}"
    miles_f = f"{miles:,}"

    # Car category for visual context
    trucks   = ["F-150", "Silverado", "Colorado", "Tacoma", "Ram", "Tundra", "Sierra", "Ranger",
                "F150", "Canyon", "Ridgeline", "Titan", "Frontier"]
    suvs     = ["CR-V", "RAV4", "Rogue", "Explorer", "Equinox", "Traverse", "Suburban",
                "Forester", "Outback", "Acadia", "Escape", "Cherokee", "Grand Cherokee",
                "Discovery", "Captiva Sport", "Santa Fe Sport", "Odyssey", "Town & Country",
                "GL-Class", "RX 450h", "Outlander Sport", "Encore", "Pilot", "Highlander",
                "4Runner", "Durango", "Atlas", "Tiguan", "Tucson", "Kona", "CX-5",
                "Terrain", "Compass", "Wrangler", "Bronco", "Blazer", "Trailblazer",
                "Envoy", "Pathfinder", "Murano", "Armada", "QX60", "MDX", "RDX",
                "Sorento", "Telluride", "Sportage", "Santa Fe"]
    category = "truck" if model in trucks else ("SUV" if model in suvs else "car")

    return f"""You write viral short-form video scripts for {brand} — a used car dealership in {location}.
They offer quality pre-owned vehicles with ZERO hidden fees, ZERO processing fees, CARFAX checked.
Website: {website} | Phone: {phone}

TODAY'S FEATURED CAR:
  {year} {make} {model} {trim}
  Price: {price_f}
  Mileage: {miles_f} miles
  Category: {category}

BRAND PHILOSOPHY:
  {brand} does things differently. No hidden fees. No dealer prep charges. No surprises.
  Every car is CARFAX checked. What you see is what you pay.
  Tagline options: "{brand_line}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NARRATIVE FORMULA — follow exactly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. HOOK     A question that stops the scroll and puts the viewer in the driver's seat.
2. PROBLEM  The car-buying struggle — overpriced dealers, hidden fees, sketchy lots, bad experiences.
3. STAKES   Who needs this car and why — commute, family, work, reliability, budget pressure.
4. RESOLUTION  Found it at {brand}. Specific price. Zero fees. CARFAX clean. Ready to drive.
5. LESSON   One brand closing line — honest, confident, no hype.

HOOK RULES:
  Open with a 2-3 line mini-story about this specific car — its reputation, what it's known for,
  why people love it, what kind of driver it attracts. Make it feel like a car enthusiast talking.
  Then pull the viewer in with a question or POV that puts THEM in the driver's seat.
  Examples (write something NEW — never copy these):
    "The {year} {make} {model} has one of the most loyal fanbases of any {category} ever built.
     Over {miles_f} miles and still turns heads. And right now one is sitting at G-Inspired for {price_f}."
    "Truck guys don't just want any truck. They want THIS one. The {year} {make} {model}
     — known for reliability, towing power, and zero drama. We have one. Zero fees."
    "People who own a {make} {model} never go back. {year} model. {miles_f} miles. {price_f}. No fees. Today."
  Start with the car's story/reputation. End with the pull. Never start with the dealership name.

SHOW DON'T TELL — every beat needs ONE specific detail:
  WRONG: "She needed a reliable car."
  RIGHT: "Her old car failed inspection for the third time. She had $15k and three kids to drop at school."
  Use real numbers, real moments, real feelings.

BEAT RULES (these appear as on-screen text — SHORT):
  hook:       max 12 words. Question or POV.
  problem:    max 12 words. Specific struggle. Named character optional.
  stakes:     max 10 words. What's at stake if they don't find a car.
  resolution: max 12 words. {brand}. Price. Zero fees. Done.
  lesson:     max 10 words. One brand line — honest and confident.

top_caption: max 9 words. Conversational scene-setter for top of screen.
             Start with: Imagine, What if, Picture this, Ever wondered.
             Do NOT mention the brand or price. Feel like a real person typing.
             Example: "Imagine driving this home today for under {price_f}."

VISUAL QUERIES — 8 Pexels/Pixabay automotive search terms.

CRITICAL RULES — Pexels has NO year-specific clips. Short queries (2-5 words) find the most results.
DO NOT add years (e.g. "2015"), DO NOT add "wide shot" or "medium shot" — Pexels ignores those.
ALL queries MUST be automotive or dealership. Never: farm, crowd, nature, sport arena, food.

I will AUTOMATICALLY override clips 0 and 1 with car-specific queries. Write clips 2-7 only:

  Clip 2 (problem — car buying frustration):
    Examples: "car dealership stressed customer", "used car lot pressure salesman",
              "auto dealer overpriced fees", "car shopping overwhelmed couple"

  Clip 3 (problem — specific struggle):
    Examples: "car inspection failure mechanic", "old car broken road",
              "couple car budget stress", "repair shop expensive bill"

  Clip 4 (stakes — commute / family need):
    Examples: "highway traffic commute", "family road trip SUV", "school run morning rush",
              "commuter car daily drive"

  Clip 5 (resolution — G-Inspired moment):
    Examples: "car key handover dealer smiling", "couple signing car contract happy",
              "car salesman handshake deal", "auto dealership satisfied customer"

  Clip 6 (resolution — driving away happy):
    Examples: "happy couple driving new car", "man driving highway confident",
              "woman driving car smiling", "new car exit dealership"

  Clip 7 (lesson — clean car confidence):
    Examples: "businessman entering luxury car", "corporate man car door",
              "clean {make} parked exterior", "confident driver luxury sedan"

For clips 2-7 write the actual queries, NOT the descriptions above.

caption_tiktok   (max 150 chars): Bold, brand-statement energy. No story summary. Max 1 emoji. No hashtags.
caption_instagram (max 200 chars): Same energy, slightly expanded. Add ginspiredautomall.com at the end.

Return ONLY valid JSON:
{{
  "car_featured": "{year} {make} {model}",
  "hook": "...",
  "problem": "...",
  "stakes": "...",
  "resolution": "...",
  "lesson": "...",
  "top_caption": "...",
  "visual_queries": [
    "query 1", "query 2", "query 3", "query 4",
    "query 5", "query 6", "query 7", "query 8"
  ],
  "caption_tiktok": "...",
  "caption_instagram": "...",
  "youtube_title": "...",
  "engagement": "..."
}}"""


# ── Main public API ───────────────────────────────────────────────────────────

def generate_content(car: dict | None = None) -> dict:
    """
    Generate a full content dict for one car listing.
    Picks a random car from inventory if none provided.
    Returns a dict compatible with render_video.py.
    """
    try:
        profile = json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
    except Exception:
        profile = {}

    if car is None:
        car = pick_car()
    if car is None:
        raise RuntimeError("G-Inspired inventory is empty — cannot generate content.")

    print(f"  [G-Inspired] Featuring: {car['year']} {car['make']} {car['model']} — ${car['price']:,}")

    raw  = _call_claude(_build_prompt(car, profile))
    data = _parse_json(raw)

    # Normalise fields render_video.py expects
    data["pillar"]         = "car_feature"
    data["client"]         = "g-inspired"
    data["car"]            = car
    data["brand_name"]     = profile.get("brand_name", "G-Inspired Automall")
    data["contact_email"]  = profile.get("contact_email", "")
    data["contact_name"]   = profile.get("contact_name", "Ebube")
    data["generated_date"] = date.today().isoformat()

    make     = car["make"]
    model    = car["model"]
    trucks   = ["F-150", "F150", "Silverado", "Colorado", "Tacoma", "Ram", "Tundra",
                "Sierra", "Ranger", "Canyon", "Ridgeline", "Titan", "Frontier"]
    suvs_set = ["CR-V", "RAV4", "Rogue", "Explorer", "Equinox", "Traverse", "Suburban",
                "Forester", "Outback", "Acadia", "Escape", "Cherokee", "Grand Cherokee",
                "Discovery", "Pilot", "Highlander", "4Runner", "Durango", "Atlas",
                "Tiguan", "Tucson", "Kona", "CX-5", "Terrain", "Compass", "Wrangler",
                "Bronco", "Blazer", "Telluride", "Sorento", "Sportage", "Santa Fe",
                "Pathfinder", "Murano", "Armada", "QX60", "MDX", "RDX", "Captiva Sport",
                "Santa Fe Sport", "Odyssey", "Town & Country", "GL-Class", "RX 450h",
                "Outlander Sport", "Encore", "Envoy", "Trailblazer", "Acadia"]
    category = "truck" if model in trucks else ("SUV" if model in suvs_set else "car")

    # Guaranteed Pexels-friendly hook queries (clips 0 and 1)
    q0, q1 = _car_pexels_queries(make, model, category)

    # Pick a fresh actor descriptor set — ensures different faces/clothes each run
    actor = _pick_actor()

    # Pre-locked automotive queries per beat position.
    # These replace Claude's attempts for middle/end beats where Pexels content
    # is well-defined but Claude's free-form queries often pull unrelated results.
    # Actor descriptors are injected so Pexels returns different people every run.
    if category == "truck":
        _stakes_q = "pickup truck highway morning commute"
        _res_q0   = f"{actor['customer']} buying pickup truck dealership smiling"
        _res_q1   = f"{actor['driver']} driving pickup truck road"
        _lesson_q = f"{actor['confident']} pickup truck"
    elif category == "SUV":
        _stakes_q = "family SUV highway road trip"
        _res_q0   = f"{actor['customer']} SUV dealership car keys smiling"
        _res_q1   = f"{actor['driver']} driving SUV highway"
        _lesson_q = f"{actor['confident']} luxury SUV"
    else:
        _stakes_q = "highway commute sedan traffic morning"
        _res_q0   = f"{actor['customer']} car dealership signing papers smiling"
        _res_q1   = f"{actor['driver']} driving sedan highway happy"
        _lesson_q = f"{actor['confident']} entering luxury car"

    # Claude's middle queries (2, 3) get sanitised and used; 4-7 are locked
    queries = data.get("visual_queries", [])

    # Problem/frustration fallbacks also rotate the person shown
    _problem_queries = [
        f"{actor['customer']} car dealership stressed price",
        f"{actor['customer']} used car lot frustrated salesman",
        f"{actor['customer']} auto dealer hidden fees upset",
        f"{actor['customer']} car shopping budget stressed",
    ]
    _repair_queries = [
        f"{actor['customer']} car inspection failure mechanic",
        "old car broken roadside repair",
        f"{actor['customer']} repair shop expensive bill shocked",
        "car engine problem mechanic garage",
    ]
    _prob_q   = random.choice(_problem_queries)
    _repair_q = random.choice(_repair_queries)

    # Pad to 8 with neutral fallbacks first, then we'll override
    _neutral_mid = [
        q0, q1,
        _prob_q,
        _repair_q,
        _stakes_q, _res_q0, _res_q1, _lesson_q,
    ]
    while len(queries) < 8:
        queries.append(_neutral_mid[len(queries)])
    queries = queries[:8]

    # Sanitise Claude's queries (positions 2-3): strip years and shot labels
    for idx in range(2, 4):
        q = queries[idx]
        q = _re.sub(r'\b(19|20)\d{2}\b', '', q)
        q = _re.sub(r'\b(wide|medium|close.up|close)\s+shot\b', '', q, flags=_re.IGNORECASE)
        q = _re.sub(r'\s{2,}', ' ', q).strip()
        if q:
            queries[idx] = q

    # Override hook and middle/end beats with locked automotive queries
    queries[0] = q0          # hook 1  — DALL-E will use car-specific prompt instead
    queries[1] = q1          # hook 2  — Pexels fallback if DALL-E unavailable
    queries[4] = _stakes_q   # stakes
    queries[5] = _res_q0     # resolution 1
    queries[6] = _res_q1     # resolution 2
    queries[7] = _lesson_q   # lesson

    data["visual_queries"] = queries

    _log_used_car(car)
    return data


# ── Weekly content (slot 4 — LinkedIn + Blog) ─────────────────────────────────

_WEEKLY_TOPICS = [
    {
        "title":   "The Hidden Fee Trap at Big Dealerships (And How to Avoid It)",
        "angle":   "transparency",
        "kw":      ["used cars Washington IL", "no hidden fees car dealership", "honest car dealer Central Illinois"],
        "li_hook": "Most car buyers walk out of a dealership paying $800–$2,000 more than the sticker price.",
    },
    {
        "title":   "5 Questions to Ask Before You Buy a Used Car in 2026",
        "angle":   "buyer tips",
        "kw":      ["used car buying tips 2026", "pre-owned vehicle checklist", "what to ask car dealer"],
        "li_hook": "The question most car buyers forget to ask — and it costs them thousands.",
    },
    {
        "title":   "Why a CARFAX Report Matters More Than the Price Tag",
        "angle":   "vehicle history",
        "kw":      ["CARFAX report used car", "vehicle history report 2026", "used car accident history"],
        "li_hook": "A $12,000 car with a clean CARFAX is worth more than a $10,000 car without one.",
    },
    {
        "title":   "Pre-Owned vs New: What the Math Actually Says in 2026",
        "angle":   "finance tips",
        "kw":      ["pre-owned vs new car 2026", "used car depreciation savings", "buy used car Illinois"],
        "li_hook": "New cars lose 20% of their value the moment you drive off the lot. Here's the math.",
    },
    {
        "title":   "How to Get Pre-Approved for a Car Loan Before You Shop",
        "angle":   "financing",
        "kw":      ["car loan pre-approval tips", "car financing advice 2026", "used car credit score"],
        "li_hook": "Walking into a dealership without pre-approval puts all the power on their side.",
    },
    {
        "title":   "What Makes a Great Used Car Dealership? 6 Things to Look For",
        "angle":   "dealership selection",
        "kw":      ["best used car dealership Washington IL", "trustworthy car dealer Illinois", "no fee dealership"],
        "li_hook": "The difference between a dealership you trust and one that costs you extra? These 6 things.",
    },
]


def generate_weekly_content(profile: dict | None = None) -> dict:
    """
    Generate LinkedIn post text + SEO blog HTML for G-Inspired slot 4 (Tue/Fri).
    Returns dict with keys: topic, linkedin_text, blog_title, blog_html, kw.
    """
    if profile is None:
        try:
            profile = json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
        except Exception:
            profile = {}

    brand    = profile.get("brand_name",  "G-Inspired Automall")
    location = profile.get("location",    "Washington, IL")
    website  = profile.get("website",     "https://www.ginspiredautomall.com")
    phone    = profile.get("phone",       "(309) 713-1020")

    # Rotate topic by week number to avoid repeating
    week_num = date.today().isocalendar()[1]
    topic    = _WEEKLY_TOPICS[week_num % len(_WEEKLY_TOPICS)]
    primary_kw = topic["kw"][0]

    print(f"  [G-Weekly] Topic: {topic['angle']} | {topic['title']}")

    # ── LinkedIn post ──────────────────────────────────────────────────────────
    li_prompt = f"""You write LinkedIn posts for {brand}, a used car dealership in {location}, IL.
Brand values: zero hidden fees, CARFAX-checked every vehicle, transparent pricing, community-first.
Website: {website} | Phone: {phone}

Topic: {topic['title']}
Opening hook: {topic['li_hook']}

Write a LinkedIn post (200-280 words) that:
1. Opens with that hook as the first line (visible before "see more")
2. Provides 3-4 practical insights or tips related to the topic
3. Positions {brand} as the trustworthy alternative (without being salesy)
4. Ends with a genuine engagement question that invites comments
5. Closes with exactly 4 hashtags: #UsedCars #GInspiredAutomall #HonestyFirst and ONE relevant tag
6. NO links in the body — only the hashtags and the closing question after the body

TONE: knowledgeable dealership owner, straight-talking, community-focused, not salesy.
Return ONLY the post text (no labels, no commentary)."""

    linkedin_text = _call_claude(li_prompt, max_tokens=600)

    # ── Blog HTML ──────────────────────────────────────────────────────────────
    blog_prompt = f"""Write a complete SEO-optimised blog post for {brand} ({website}).
Audience: car buyers in Central Illinois (Washington, Peoria, Bloomington area).
Brand voice: transparent, honest, zero-fee dealership, community trusted.

Title: {topic['title']}
Primary keyword: "{primary_kw}"
Secondary keywords: {', '.join(topic['kw'][1:])}

REQUIREMENTS:
1. Return ONLY valid HTML — no markdown, no commentary outside the HTML
2. Format:
   <!-- title: {topic['title']} -->
   <!-- labels: {topic['angle']}, used cars, G-Inspired Automall, {location} -->
   <p>Intro...</p>
   <h2>First section...</h2>
   ...
   <h2>Frequently Asked Questions</h2>
   <h3>Question?</h3><p>Answer.</p>
   ...

3. Structure: intro + 4 H2 sections (2-3 paragraphs each) + FAQ (3 Q&As) + CTA box
4. SEO: "{primary_kw}" in first paragraph and at least one H2. 800-1100 words total.
5. Tone: helpful, practical, no fluff. Bold 2-3 key stats or facts.
6. One internal link to {website} with anchor text "G-Inspired Automall"
7. Mention {location} at least twice naturally

CTA box template (use this exactly):
<div style="background:linear-gradient(135deg,#1D3A6E,#2563eb);border-radius:16px;padding:32px;margin-top:40px;text-align:center;">
  <h3 style="color:#fff;margin:0 0 12px;font-size:20px;">Ready to Find Your Next Car?</h3>
  <p style="color:#e2e8f0;margin:0 0 16px;">Zero hidden fees. CARFAX checked. Honest prices. That's the G-Inspired difference.</p>
  <a href="{website}" style="display:inline-block;background:#FFE600;color:#1D3A6E;font-weight:700;font-size:15px;padding:14px 32px;border-radius:10px;text-decoration:none;">Browse Inventory →</a>
</div>"""

    blog_html_raw = _call_claude(blog_prompt, max_tokens=3500)

    # Extract title and labels, strip comment lines from body
    title_m  = re.search(r'<!-- title:\s*(.+?)\s*-->', blog_html_raw)
    labels_m = re.search(r'<!-- labels:\s*(.+?)\s*-->', blog_html_raw)
    blog_title  = title_m.group(1).strip()  if title_m  else topic["title"]
    blog_labels = labels_m.group(1).strip() if labels_m else topic["angle"]
    blog_body   = re.sub(r'<!--.*?-->', '', blog_html_raw, flags=re.DOTALL).strip()

    return {
        "topic":         topic["title"],
        "angle":         topic["angle"],
        "kw":            primary_kw,
        "linkedin_text": linkedin_text,
        "blog_title":    blog_title,
        "blog_labels":   blog_labels,
        "blog_html":     blog_body,
        "brand_name":    brand,
        "website":       website,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    content = generate_content()
    print(f"\nHook       : {content.get('hook')}")
    print(f"Problem    : {content.get('problem')}")
    print(f"Stakes     : {content.get('stakes')}")
    print(f"Resolution : {content.get('resolution')}")
    print(f"Lesson     : {content.get('lesson')}")
    print(f"Top caption: {content.get('top_caption')}")
    print(f"TikTok cap : {content.get('caption_tiktok')}")
    print(f"Queries    : {content.get('visual_queries')}")
