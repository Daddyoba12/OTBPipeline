"""
OTB_Pipeline — AI content generator (Story-First Pipeline v2)

Six-stage architecture:
  Stage 1 — Story Writer   : Claude / OpenAI / Gemini writes the narrative
  Stage 2 — QA Director    : Reviews story, scores 0-100, rewrites if < 80
  Stage 3 — Scene Planner  : Claude Haiku maps story to 8 scene-specific queries
  Stage 4 — Photographer   : Upgrades queries + generates AI image prompts
  Stage 5 — Cinematographer: Converts image prompts to video prompts (Kling/Veo/Runway ready)
  Stage 6 — Reviewer       : Final quality gate, scores 0-100, rewrites if < 90. Saves to memory DB.

Visual query safety — 3 layers applied after Stage 4:
  1. scene_planner + photographer prompts — medium/wide shots, pillar blueprint
  2. _sanitize_queries()                 — banned term check
  3. _dedup_14day()                      — 14-day no-repeat log
"""

import json, re, sys, random
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, STORY_MODEL, QA_MODEL,
    SLOT_PILLARS, PILLAR_LABELS, DAY_BUCKETS, DATA,
)
from fetch_trending_hashtags import fetch_today as _fetch_trending_tags
from scene_planner import plan_scenes, plan_scenes_v2
from qa_director import review_and_improve
from photographer import generate_image_prompts
from cinematographer import generate_video_prompts
from reviewer import final_review
import memory_db
from news_editor import find_top_story

import requests
from query_learner import (
    seed_bank_if_empty, promote_demote, maybe_weekly_refresh,
    register_novel_queries, get_best_for_role,
    TRANSPORT_QUERIES, ALL_TRANSPORT,
)

# ── Banned query terms (hard block — any query containing these gets replaced) ──
BANNED_QUERY_TERMS = {
    "animal", "animals", "dog", "dogs", "cat", "cats", "horse", "horses",
    "pet", "pets", "puppy", "puppies", "kitten", "kittens", "bird", "birds",
    "lion", "tiger", "elephant", "monkey", "fish", "rabbit", "wildlife",
    "farm", "zoo", "livestock", "parrot", "sheep", "cow", "goat", "duck",
    "chicken", "pig", "hamster", "turtle", "snake", "gecko", "insect",
    "food", "food delivery", "uber eats", "ubereats", "deliveroo", "just eat",
    "doordash", "grubhub", "restaurant", "takeaway", "takeout", "pizza delivery",
    "meal delivery", "grocery delivery", "grocery", "meal", "cooking", "chef",
    "kitchen", "cafe", "diner", "burger", "sandwich", "bakery", "supermarket",
    "fast food", "drive through", "drive-through", "dining", "breakfast",
    "christmas", "xmas", "santa", "reindeer", "christmas tree", "holiday season",
    "baubles", "nativity", "elf", "tinsel", "advent", "carol", "festive",
    "holiday shopping", "black friday", "cyber monday",
    "halloween", "pumpkin", "easter", "egg hunt", "thanksgiving", "fireworks",
    "new year party", "valentine", "bonfire night",
    "teamwork handshake", "success mountain", "cartoon", "illustration",
    "trophy", "medal", "piggy bank", "light bulb idea",
}

# ── 14-day query log ──────────────────────────────────────────────────────────
QUERY_LOG = DATA / "query_log.json"


def _load_recent_queries(days: int = 14) -> set:
    if not QUERY_LOG.exists():
        return set()
    try:
        log = json.loads(QUERY_LOG.read_text(encoding="utf-8"))
        cutoff = date.today() - timedelta(days=days)
        recent = set()
        for entry in log:
            try:
                if date.fromisoformat(entry["date"]) >= cutoff:
                    recent.add(entry["query"].strip().lower())
            except Exception:
                pass
        return recent
    except Exception:
        return set()


def _save_used_queries(queries: list, slot: int):
    try:
        log = json.loads(QUERY_LOG.read_text(encoding="utf-8")) if QUERY_LOG.exists() else []
    except Exception:
        log = []
    today_str = date.today().isoformat()
    cutoff = date.today() - timedelta(days=14)
    log = [e for e in log if date.fromisoformat(e.get("date", "2000-01-01")) >= cutoff]
    for q in queries:
        log.append({"query": q.strip().lower(), "date": today_str, "slot": slot})
    QUERY_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


# ── Sanitizer: banned term check ──────────────────────────────────────────────
def _sanitize_queries(queries: list, beat_roles: list) -> list:
    cleaned = []
    for i, q in enumerate(queries):
        if any(term in q.lower() for term in BANNED_QUERY_TERMS):
            role = beat_roles[i] if i < len(beat_roles) else "hook"
            fallback = random.choice(TRANSPORT_QUERIES.get(role, TRANSPORT_QUERIES["hook"]))
            print(f"    [QueryFilter] Banned: '{q}' -> '{fallback}'")
            cleaned.append(fallback)
        else:
            cleaned.append(q)
    return cleaned


# ── 14-day deduplicator ───────────────────────────────────────────────────────
def _dedup_14day(queries: list, beat_roles: list) -> list:
    recent = _load_recent_queries(14)
    result = []
    used_this_run = set()

    for i, q in enumerate(queries):
        norm = q.strip().lower()
        if norm in recent or norm in used_this_run:
            role = beat_roles[i] if i < len(beat_roles) else "hook"
            exclude = recent | used_this_run
            candidates = get_best_for_role(role, exclude, n=15)
            if not candidates:
                candidates = [q for q in ALL_TRANSPORT if q.lower() not in exclude]
            replacement = candidates[0] if candidates else random.choice(ALL_TRANSPORT)
            print(f"    [14dayDedup] Recent: '{q}' -> '{replacement}'")
            result.append(replacement)
            used_this_run.add(replacement.lower())
        else:
            result.append(q)
            used_this_run.add(norm)

    return result


# Beat role mapping (same order as CLIP_BEAT in render_video.py)
_BEAT_ROLES = [
    "hook", "hook",
    "problem", "problem",
    "stakes",
    "resolution", "resolution",
    "lesson_pre",
]

# ── Platform hashtag pools ────────────────────────────────────────────────────

CORE_TAGS = ["#BootHop", "#LondonToLagos", "#DiasporaMagic", "#SameDayDelivery", "#TravelHack"]

TIKTOK_DISCOVERY = [
    "#UKNigeria", "#NaijaUK", "#AfricanDiaspora", "#UKtoNigeria", "#FamilyAbroad",
    "#AbroadLife", "#UrgentDelivery", "#HumanLogistics", "#DiasporaLife", "#UKAfrica",
]
TIKTOK_BROAD = [
    "#logistics", "#shipping", "#travel", "#delivery", "#diaspora",
    "#fyp", "#viral", "#trending", "#storytime", "#lifehack",
]
TIKTOK_PILLAR = {
    "community":          ["#NaijaUK", "#NigerianDiaspora", "#CommunityFirst", "#PeerToPeer", "#UKNigeria"],
    "family":             ["#FamilyAbroad", "#CarePackage", "#SendingLove", "#FamilyFirst", "#HomeCountry"],
    "airport":            ["#AirportStories", "#TravelDrama", "#AirportLife", "#Customs", "#TravelStress"],
    "smart":              ["#TravelHacks", "#SmartTravel", "#SaveMoney", "#TravelTips", "#SideIncome"],
    "travel_hacks":       ["#TravelHacks", "#TravelTips", "#PackingTips", "#SaveMoney", "#TravelSmart"],
    "logistics_stories":  ["#LogisticsLife", "#SupplyChain", "#DeliveryStories", "#CourierLife", "#LastMile"],
    "airport_deliveries": ["#AirportDelivery", "#CustomsLife", "#AirportDrama", "#FreightLife", "#Airside"],
    "supply_chain":       ["#SupplyChain", "#Logistics", "#BusinessTips", "#OperationsLife", "#TradeRoutes"],
}

INSTAGRAM_TAGS = {
    "community":          "#BootHop #LondonToLagos #DiasporaMagic #SameDayDelivery #NaijaUK #AfricanDiaspora #UKNigeria #CommunityFirst #AbroadLife #FamilyAbroad #DiasporaLife #NigerianUK #HumanLogistics #TrustPeople #UKtoNigeria #PeerDelivery #NaijaCommunity #SendingLove #Londoner #UKAfrica",
    "family":             "#BootHop #LondonToLagos #DiasporaMagic #SameDayDelivery #FamilyAbroad #CarePackage #SendingLove #HomeCountry #FamilyFirst #MumAbroad #NaijaUK #AfricanFamily #DiasporaFamily #UrgentDelivery #UKtoNigeria #MissingHome #FamilyLove #LondonLife #NigerianDiaspora #AfricanDiaspora",
    "airport":            "#BootHop #LondonToLagos #AirportLife #TravelDrama #Customs #AirportStories #TravelStress #AirportVibes #TravelUK #DiasporaMagic #UKNigeria #SameDayDelivery #AirportDelivery #LagosLife #NaijaUK #TravelHack #FamilyAbroad #UrgentDelivery #FreightLife #LogisticsLife",
    "smart":              "#BootHop #LondonToLagos #TravelHacks #SmartTravel #SaveMoney #SideIncome #TravelTips #PackingTips #EarnWhileTravel #TravelSmart #DiasporaMagic #UKNigeria #SameDayDelivery #NaijaUK #AbroadLife #HumanLogistics #TravelLife #FreelanceUK #SideHustle #MakeMoneyTravel",
    "travel_hacks":       "#BootHop #TravelHacks #TravelTips #PackingTips #SaveMoney #TravelSmart #SameDayDelivery #DiasporaMagic #LondonToLagos #UKNigeria #AbroadLife #NaijaUK #UrgentDelivery #TravelLife #HumanLogistics #SmartTravel #DiasporaLife #AfricanDiaspora #UKtoNigeria #TravelInspo",
    "logistics_stories":  "#BootHop #LogisticsLife #SupplyChain #DeliveryStories #CourierLife #LastMile #FreightLife #ShippingLogistics #LogisticsUK #DiasporaMagic #LondonToLagos #SameDayDelivery #Logistics2024 #TradingLife #NaijaUK #HumanLogistics #BusinessUK #UrgentDelivery #TradeUK #GlobalLogistics",
    "airport_deliveries": "#BootHop #AirportDelivery #CustomsLife #AirportDrama #FreightLife #AirsideLife #CargoLife #AirportLogistics #DiasporaMagic #LondonToLagos #SameDayDelivery #NaijaUK #UrgentDelivery #AirportStories #DeliveryLife #ShippingUK #LogisticsLife #CourierUK #TravelHack #UKNigeria",
    "supply_chain":       "#BootHop #SupplyChain #Logistics #BusinessTips #OperationsLife #TradeRoutes #GlobalTrade #BusinessUK #LogisticsLife #FreightLife #ShippingIndustry #DiasporaMagic #LondonToLagos #SameDayDelivery #BusinessOwner #SME #StartupUK #HumanLogistics #TradeUK #LogisticsUK",
}

YOUTUBE_CATEGORIES = {
    "community": 22, "family": 22, "airport": 19,
    "smart": 26, "travel_hacks": 19, "logistics_stories": 22,
    "airport_deliveries": 19, "supply_chain": 22,
}


def _tiktok_hashtags(pillar: str, tags_311: list[str]) -> str:
    return " ".join(tags_311[:5])


def _instagram_hashtags(pillar: str, tags_311: list[str]) -> str:
    static = INSTAGRAM_TAGS.get(pillar, INSTAGRAM_TAGS["community"])
    static_tags = static.split()
    core_lower = {t.lower() for t in tags_311}
    extra = [t for t in static_tags if t.lower() not in core_lower]
    combined = tags_311 + extra
    seen, unique = set(), []
    for t in combined:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    return " ".join(unique[:25])


def _youtube_tags(pillar: str, hook: str) -> list:
    base = ["BootHop", "London to Lagos", "diaspora delivery", "same day delivery", "peer to peer delivery"]
    pillar_map = {
        "community":          ["nigerian diaspora uk", "uk nigeria community", "diaspora life uk"],
        "family":             ["care package abroad", "sending parcel home", "family abroad uk"],
        "airport":            ["airport delivery uk", "travel logistics uk", "airport stories"],
        "smart":              ["travel hacks uk", "earn money travelling", "side income travel"],
        "travel_hacks":       ["travel hacks", "packing tips uk", "smart travel tips"],
        "logistics_stories":  ["logistics uk", "delivery stories", "courier alternatives"],
        "airport_deliveries": ["airport delivery", "customs uk", "freight stories"],
        "supply_chain":       ["supply chain uk", "logistics business", "trade routes uk"],
    }
    extra = pillar_map.get(pillar, [])
    all_tags = base + extra
    for word in hook.lower().split():
        if len(word) > 5 and word.isalpha():
            all_tags.append(word)
    return list(dict.fromkeys(all_tags))[:15]


# ── AI caller helpers ─────────────────────────────────────────────────────────

def _call_claude(prompt: str, model: str = "claude-sonnet-4-6", max_tokens: int = 1200) -> str:
    from quota_alert import alert as _qa
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    if resp.status_code in (429, 402, 529):
        _qa("Claude", resp.status_code, model)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_openai(prompt: str, model: str = "gpt-4o", max_tokens: int = 1200) -> str:
    from quota_alert import alert as _qa
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    if resp.status_code in (429, 402):
        _qa("OpenAI", resp.status_code, model)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_gemini(prompt: str, model: str = "gemini-2.0-flash", max_tokens: int = 1200) -> str:
    from quota_alert import alert as _qa
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
        },
        timeout=30,
    )
    if resp.status_code in (429, 402, 403):
        _qa("Gemini", resp.status_code, model)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_story_ai(prompt: str, v2: bool = False) -> str:
    """Route to Claude, OpenAI, or Gemini based on STORY_MODEL config."""
    if STORY_MODEL == "openai":
        model = "gpt-4o-mini" if v2 else "gpt-4o"
        print(f"  [StoryWriter] Using OpenAI {model}")
        return _call_openai(prompt, model=model)
    elif STORY_MODEL == "gemini":
        model = "gemini-2.0-flash" if v2 else "gemini-2.0-flash"
        print(f"  [StoryWriter] Using Gemini {model}")
        return _call_gemini(prompt, model=model)
    else:
        model = "claude-haiku-4-5-20251001" if v2 else "claude-sonnet-4-6"
        print(f"  [StoryWriter] Using Claude {model}")
        return _call_claude(prompt, model=model)


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in response: {raw[:200]}")
    return json.loads(m.group())


# ── Story Writer prompt builder ───────────────────────────────────────────────

def _build_story_prompt(
    slot: int, pillar: str, bucket: str,
    pillar_label: str, pillar_angle: str,
    day_name: str, month_name: str,
    news_context: dict | None = None,
) -> str:
    from datetime import date as _date
    news_block = ""
    if news_context:
        news_block = f"""
TODAY'S REAL-WORLD CONTEXT (weave in naturally if it fits — never force it):
  Headline: {news_context.get('headline', '')}
  Angle: {news_context.get('story_angle', '')}
"""

    # POV block — travel_hacks angles embed their own POV in pillar_angle
    pov_block = ""
    if pillar != "travel_hacks":
        pov_label, pov_instructions = _DAILY_POV[_date.today().weekday()]
        pov_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TODAY'S POINT OF VIEW: {pov_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{pov_instructions}

Lock into this POV from hook to lesson — never switch perspectives mid-story.
"""

    return f"""You write viral short-form content for BootHop — a peer-to-peer delivery platform connecting UK and Nigeria through travellers already making the journey.

LANGUAGE RULE — CRITICAL: British English only. No Yoruba, Pidgin, Igbo, Hausa, or any other language — not even single words or phrases.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND PHILOSOPHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BootHop doesn't sell delivery. BootHop unlocks unused human movement.
Every day, millions of people are already travelling between UK and Nigeria.
BootHop gives those journeys a second purpose.

Signature line: "Movement already exists. BootHop makes it useful."
{pov_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STORY CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Slot: {slot} ({["","7am","12pm","6pm","9pm"][slot]})
Pillar: {pillar_label}
Day: {day_name}, {month_name}
Tone: {bucket}
{f"Pillar direction: {pillar_angle}" if pillar_angle else ""}
{news_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NARRATIVE FORMULA — follow this structure exactly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. PERSON     A specific named person with real context (not "a woman" — "Sade, a nurse in Wolverhampton")
2. MOMENT     A deadline, event, or celebration that makes this urgent NOW
3. PROBLEM    Why a reputable courier fails — too expensive, too slow, or both
4. MOVEMENT   Someone was ALREADY flying this route — the journey existed before BootHop
5. CONNECTION BootHop matched the sender with that traveller
6. EMOTION    The relief, gratitude, or joy when it arrived
7. PHILOSOPHY A short closing line from the brand language bank

INTERNAL CHECKLIST — before writing any beat, answer these 6:
  WHO?    Named person + context (job, city, relationship)
  WHAT?   Specific item and why it matters emotionally
  WHY?    The event, deadline, or person at risk if it doesn't arrive
  WHO WAS MOVING?  The traveller — already going, not hired for this
  HOW?    BootHop connected them
  FEELING? How did everyone feel when it arrived?

If your story can't answer all 6, rewrite it before returning.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHOW DON'T TELL — every beat needs ONE specific detail
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WRONG: "She was stressed about the cost."
RIGHT: "She'd refreshed the courier site three times. The cheapest: £68, five to seven days. The ceremony was on Friday."

WRONG: "BootHop connected them in time."
RIGHT: "A notification at 11:47pm. A traveller flying to Lagos at 6am had space. She replied in eight seconds."

WRONG: "He was happy it arrived."
RIGHT: "His dad sent a 12-second voice note. He played it twice in the car on the way home."

Use a price, a time, a number, a sound, a word someone actually said. Make it feel lived-in.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE UNEXPECTED MOMENT — mandatory in RESOLUTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every compelling story has one beat the viewer didn't see coming. It goes in RESOLUTION.
Examples of good unexpected moments:
✓ The traveller had made this trip 22 times. This was the first time the luggage allowance earned anything.
✓ The parcel arrived before the courier had even sent a confirmation email.
✓ He was carrying a stranger's parcel. Turned out they lived two streets away in Manchester.
✓ She posted at midnight, not expecting anything. A traveller had already packed and was ready to go.
✓ The recipient's reaction: she didn't open it. She held it for a minute first.
This moment is what makes the video shareable. Don't skip it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOOK STARTERS — start with person, moment, or consequence (NEVER a price)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ "Her mum's retirement ceremony was on Friday."
✓ "He'd been making this trip every three months for two years."
✓ "The wedding was already set. The dress was still in Birmingham."
✓ "Sade hadn't been home in two years. She wanted to send something real."
✗ NEVER start with a price, courier quote, or BootHop name

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ITEMS — use variety, NEVER default to tablets or medication
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gifts:        birthday gift, graduation gift, wedding present, baby shower hamper
Clothing:     aso-oke fabric, agbada, jordans/trainers, nursing scrubs, school uniform, used clothes
Electronics:  laptop, phone charger, tablet, headphones, smart watch, gaming controller
Professional: medical stethoscope, exam certificate, portfolio prints, visa documents
School:       textbooks, school shoes, stationery pack, school uniform
Keepsakes:    framed family photo, handmade jewellery, signed sports shirt, handwritten letter
Baby items:   baby clothes, baby shoes, toys, formula tin
Food (sealed only): Nigerian spices, stockfish, Indomie noodles, shea butter

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABOUT BOOTHOP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRAVELLER = earns money carrying a parcel on a trip they were ALREADY making
SENDER    = pays a traveller — far cheaper than couriers, often next-day
Always two different people. BootHop connects them. The traveller was going ANYWAY.

COURIER RULE: NEVER name DHL, FedEx, Royal Mail, Hermes, Parcelforce, UPS.
Write "a reputable courier" or "a traditional courier service".

PRICE RANGES:
- Reputable courier UK → Nigeria: £35–75 small parcel
- BootHop peer-to-peer: £8–25 same route
- Traveller earnings: £20–85 per trip

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND CLOSING LINES — lesson MUST use one of these EXACTLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. "The flight was already going. The parcel just needed a seat."
2. "Movement already exists. BootHop makes it useful."
3. "Someone was already flying. BootHop connected the dots."
4. "The journey already existed. The parcel just joined it."
5. "Every journey has value."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEAT RULES (on-screen video text — SHORT is essential, text gets cut off if too long)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOOK:       max 15 words. Start with person or moment — NEVER a price or courier quote.
PROBLEM:    max 12 words. The courier failure. One sentence.
STAKES:     max 10 words. Consequence if it doesn't arrive. Same character and item.
RESOLUTION: max 12 words. BootHop appears HERE. Traveller was ALREADY going. Close the loop.
LESSON:     max 10 words. Use ONE closing line from the brand language bank above, EXACTLY.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLATFORM CAPTIONS (go in caption, not on screen — can be longer)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
caption_tiktok  (max 300 chars): Open with human moment. 2 line breaks. 2–3 story sentences. Engagement question at end.
caption_instagram (max 400 chars): First 125 chars = emotional hook + stakes. Full arc 3–4 sentences. Include "someone was already making that journey." CTA + engagement question.
youtube_title   (max 60 chars): Human story or question format. NOT "BootHop does X". No BootHop in title.
youtube_description: 2–3 sentences, keyword-rich first 100 chars. Include "boothop.com" at end.
engagement      (max 10 words): One question that opens a real conversation.

Return ONLY valid JSON (no markdown):
{{
  "story_anchor": {{
    "character": "named person with specific context",
    "item": "exact item being sent",
    "moment": "event or deadline creating urgency",
    "obstacle": "specific courier failure",
    "movement": "who was already travelling, how BootHop connected them"
  }},
  "hook": "...",
  "problem": "...",
  "stakes": "...",
  "resolution": "...",
  "lesson": "...",
  "caption_tiktok": "...",
  "caption_instagram": "...",
  "youtube_title": "...",
  "youtube_description": "...",
  "engagement": "..."
}}"""


# ── Daily POV rotation ────────────────────────────────────────────────────────
# Each weekday locks the story to a specific character's perspective.
# POV makes stories feel intimate and personal — the viewer inhabits one person.
# Index = weekday (0=Mon … 6=Sun)
_DAILY_POV = [
    (  # 0 — Monday: Sender's discovery
        "THE SENDER — Discovery",
        "Tell this story entirely through the eyes of the person in the UK trying to send something.\n"
        "We feel the frustration building: expensive quotes, slow couriers, the late-night search.\n"
        "HOOK: opens with the sender and the emotional weight of what they're trying to get there and why.\n"
        "PROBLEM: show their exact moment of shock — the price on the screen, the delivery window that misses the date.\n"
        "RESOLUTION: the instant BootHop changes everything for them — who messaged, how fast, what they paid.\n"
        "Close with their feeling: not relief alone, but the realisation they've been doing this wrong for years.",
    ),
    (  # 1 — Tuesday: Recipient waiting in Nigeria
        "THE RECIPIENT — Waiting",
        "Tell this story from inside Nigeria, through the person who is waiting for the item to arrive.\n"
        "We see THEIR world first — the occasion, the need, the anticipation.\n"
        "HOOK: opens in Nigeria. What is this person about to celebrate or achieve? What does this item mean to them?\n"
        "PROBLEM: told through their eyes — they're waiting, time is running out, they've started to worry.\n"
        "RESOLUTION: the knock on the door. The parcel in their hands. The first thing they say or do.\n"
        "LESSON: what this moment meant — not just a delivery, but the connection it carried.",
    ),
    (  # 2 — Wednesday: Traveller's accidental discovery
        "THE TRAVELLER — Ordinary Trip, Unexpected Earning",
        "Tell this story from the traveller's perspective — someone who was ALREADY flying this route.\n"
        "This trip was booked months ago. BootHop wasn't in the plan.\n"
        "HOOK: the traveller at the airport, on the train, packing their bag. Normal day. Then something shifts.\n"
        "PROBLEM (reframed): the traveller has always had spare luggage allowance and never earned from it.\n"
        "RESOLUTION: the match on BootHop, the handover, the £XX earned before boarding.\n"
        "LESSON: this journey was going to happen anyway. BootHop made it count twice.",
    ),
    (  # 3 — Thursday: Sender's long frustration solved
        "THE SENDER — Years of Overpaying, Now Solved",
        "Tell this from the sender's perspective, but with a deeper emotional arc: this isn't the first time.\n"
        "They've been sending things the expensive way for years — accepting it as the cost of diaspora life.\n"
        "HOOK: opens with a past moment of frustration — 'Every year at this time, the same problem.'\n"
        "PROBLEM: years of overpaying hits differently when they calculate the total they've wasted.\n"
        "RESOLUTION: BootHop doesn't just solve today's problem — it changes how they'll think about this forever.\n"
        "LESSON: they'll never go back. And they told everyone they know.",
    ),
    (  # 4 — Friday: Cinematic Traveller
        "THE TRAVELLER — Cinematic, Aspirational",
        "Friday = prime content slot. Make this feel like a short film, not a social post.\n"
        "Tell it through the traveller's eyes — confident, purposeful, alive to the moment.\n"
        "HOOK: the traveller in motion — airport, departure lounge, gate. Vivid sensory detail.\n"
        "PROBLEM (reframed): show what their trips used to feel like versus now — unused capacity, wasted earnings.\n"
        "RESOLUTION: cinematic. The handover. The landing. The WhatsApp notification with the earnings.\n"
        "LESSON: delivered with weight — this isn't just logistics. This is what movement is for.",
    ),
    (  # 5 — Saturday: Community spread
        "THE COMMUNITY — Word of Mouth",
        "Tell this as a community ripple story — one person tells another, and suddenly everything changes.\n"
        "Saturday = community content. Warm, connected, collective win.\n"
        "HOOK: a community moment — a gathering, a WhatsApp group, a Sunday lunch, a church porch.\n"
        "Someone mentions BootHop. Another person stops and asks: 'Wait, how does that work?'\n"
        "PROBLEM: the listener has been sending things the expensive way for years, just like everyone else.\n"
        "RESOLUTION: they try it the next week. It works. They tell the next person.\n"
        "LESSON: the community already exists. BootHop just needed a seat in it.",
    ),
    (  # 6 — Sunday: Recipient's reunion
        "THE RECIPIENT — Reunion and Gratitude",
        "Sunday = family. Tell this entirely through the eyes of the Nigerian recipient.\n"
        "We don't start in the UK — we start in Nigeria, in the life that was waiting for this.\n"
        "HOOK: Sunday morning in Lagos, Abuja, or a family home. The person who is waiting. Why today matters.\n"
        "PROBLEM: told as anticipation mixed with worry — will it arrive in time? Has anything gone wrong?\n"
        "RESOLUTION: the delivery. Not just the parcel — the emotion. Voice note. Video call. Tears. Laughter.\n"
        "LESSON: end on gratitude — for the sender, the traveller, and the movement that made it possible.",
    ),
]


# Pillar-specific direction (human movement framing — never supply chain jargon)
_PILLAR_ANGLES = {
    "supply_chain": (
        "Tell a mini-documentary about how global logistics fails real people — a UK-Nigeria gap "
        "story with a specific person at the centre. Hook with the HUMAN MOMENT (deadline, event, "
        "relationship), not a supply chain fact or price. BootHop appears in RESOLUTION as the "
        "human-movement alternative — someone was already going there."
    ),
    "logistics_stories": (
        "Tell a logistics rescue story — a parcel race against time, a customs near-miss, or a "
        "last-mile gap solved by a traveller already making the journey. Open with a person and "
        "the stakes, not logistics terminology. Make the viewer feel the tension."
    ),
    "airport_deliveries": (
        "Tell a dramatic airport story with human stakes — a traveller who carried something "
        "important on an existing trip, a last-minute handoff, or an emotional arrival. Open with "
        "the person and the moment. Make the viewer feel the relief at the end."
    ),
    "travel_hacks": "__DYNAMIC__",  # built at generation time from ingredient pools
    "family": (
        "Tell a care story — someone sending something meaningful to a family member they miss. "
        "The item should carry emotional weight: a gift, clothing, a keepsake. "
        "Open with the relationship and what's at stake, not the price."
    ),
    "community": (
        "Tell a community connection story — BootHop as the thread that keeps diaspora families "
        "and friends connected across miles. The traveller is part of the same community. "
        "Warm, human, and specific. Open with a person and a meaningful moment."
    ),
    "airport": (
        "Tell a story set around the moment of travel — the handoff, the arrival, the relief. "
        "Show the human side of movement: a traveller who became someone's hero on an ordinary trip."
    ),
    "smart": (
        "Tell a cleverness story — the elegant solution the sender didn't expect. "
        "Someone was already going. BootHop connected them. The smart move cost a fraction of the courier. "
        "Open with the problem, let the solution feel like a revelation."
    ),
}


# ── Travel Hacks dynamic story ingredient pools ───────────────────────────────
_TH_PROTAGONISTS = [
    # (name, role, city, travel direction)
    ("Tola",    "nurse",                    "Manchester",   "sender"),
    ("Emeka",   "software developer",       "London",       "traveller"),
    ("Sade",    "accountant",               "Birmingham",   "sender"),
    ("Kunle",   "NHS doctor",               "Bristol",      "traveller"),
    ("Ngozi",   "teacher",                  "Leeds",        "sender"),
    ("Chidi",   "security guard",           "Leicester",    "traveller"),
    ("Amara",   "care worker",              "Nottingham",   "sender"),
    ("Femi",    "pharmacist",               "Croydon",      "traveller"),
    ("Bisi",    "market trader",            "Peckham",      "sender"),
    ("Yemi",    "student at UCL",           "London",       "traveller"),
    ("Dayo",    "chef",                     "Edinburgh",    "traveller"),
    ("Kemi",    "social worker",            "Sheffield",    "sender"),
    ("Uche",    "warehouse manager",        "Coventry",     "traveller"),
    ("Adaeze",  "midwife",                  "Liverpool",    "sender"),
    ("Seun",    "delivery driver",          "Milton Keynes","traveller"),
    ("Funmi",   "architect",               "East London",  "sender"),
    ("Tobi",    "university lecturer",      "Exeter",       "traveller"),
    ("Nkechi",  "retail manager",           "Cardiff",      "sender"),
    ("Ebuka",   "IT consultant",            "Cambridge",    "traveller"),
    ("Lola",    "community nurse",          "Wolverhampton","sender"),
    ("Ade",     "plumber",                  "Luton",        "traveller"),
    ("Chisom",  "finance analyst",          "Canary Wharf", "sender"),
    ("Tunde",   "secondary school teacher", "Hackney",      "traveller"),
    ("Bukola",  "NHS administrator",        "Slough",       "sender"),
    ("Onyeka",  "event photographer",       "Brixton",      "traveller"),
]

_TH_ITEMS = [
    ("a pair of Jordans",               "for his younger brother's graduation ceremony"),
    ("a traditional aso-oke fabric",    "for her auntie's wedding in Lagos"),
    ("a brand-new laptop",              "for her nephew starting university"),
    ("baby clothes and shoes",          "for a newborn cousin she had never met"),
    ("a medical stethoscope",           "for a cousin qualifying as a doctor"),
    ("wireless headphones",             "a birthday gift three weeks overdue"),
    ("a signed football shirt",         "for her father's 65th birthday"),
    ("a framed family photo",           "the first one they'd ever printed together"),
    ("an exam certificate",             "needed for a job application in Abuja"),
    ("school shoes and a uniform",      "for a niece starting secondary school on Monday"),
    ("a gaming controller",             "a Christmas present four months late"),
    ("a smart watch",                   "for her mum's retirement ceremony"),
    ("nursing scrubs",                  "for a cousin starting her first hospital placement"),
    ("a replacement phone",             "after her sister's was stolen at the market"),
    ("a handwritten letter and photos", "from grandchildren who had never met their grandfather"),
    ("a wedding invitation suite",      "printed in London, needed in Abuja in two days"),
    ("a portable power bank",           "her dad depended on CPAP at night"),
    ("a box of Nigerian spices",        "her mum had been asking for since Christmas"),
    ("an agbada for her father",        "tailored in Birmingham, needed for his chieftaincy ceremony"),
    ("a ring box with an engagement ring","bought in Hatton Garden, proposal planned for Saturday"),
    ("a university acceptance letter",  "needed physically for matriculation in three days"),
    ("a breast pump",                   "her sister had just had twins and couldn't afford one locally"),
    ("a driving licence renewal form",  "that had to be submitted in person in Lagos"),
    ("a limited-edition perfume",       "sold out in Nigeria, her grandmother's favourite"),
    ("crutches and a knee brace",       "her brother had torn his ACL and had no physio access"),
]

_TH_COMPLICATIONS = [
    "A reputable courier quoted £{price} and said it would take {days} days.",
    "She had already tried two couriers — both said it would miss the date.",
    "Every courier she called wanted £{price} minimum and couldn't guarantee the date.",
    "The cheapest option she found was £{price}, but delivery would miss {event} by a week.",
    "He had been sending things this way for years — always overpaying, always anxious.",
    "The item was too bulky to post cheaply but small enough to carry in a cabin bag.",
    "She didn't even know BootHop existed — a friend mentioned it at a WhatsApp group.",
    "He almost didn't check. His flight was in 36 hours and he assumed it was too late.",
    "She posted at 11pm, assuming nothing would come of it at that hour.",
    "Two previous couriers had lost her parcels. She had stopped trusting them entirely.",
    "The local postal service had already failed her once this year.",
    "A courier quoted £{price} — more than the item cost to buy.",
    "She needed it there in 48 hours. Every courier wanted 5-7 days.",
    "He was already at the airport when a stranger in the queue told him about BootHop.",
    "The item had been sitting packaged in her hallway for a month — she kept putting it off.",
]

_TH_ANGLES = [
    # (angle_label, pov, narrative_shape)
    ("TRAVELLER EARNS ON AN EXISTING TRIP",
     "traveller",
     "Already had a flight booked. Checked BootHop before packing. Found two senders on the same route. "
     "Carried both parcels, earned £{earn}. Enough to cover the checked bag fee. "
     "HOOK = the traveller and the trip they already had planned. "
     "PROBLEM = empty luggage allowance, wasted earning potential, didn't know BootHop existed. "
     "STAKES = the money they had left on the table on every previous trip. "
     "RESOLUTION = matched with two senders, earned £{earn} before boarding. "
     "LESSON = every journey has value."),

    ("URGENT SENDER FINDS A TRAVELLER IN TIME",
     "sender",
     "Needed {item} to reach Nigeria before {event}. Courier too expensive and too slow. "
     "Posted on BootHop the same evening. A traveller flying the next morning accepted. "
     "Item arrived in Lagos {hours} hours later — £{price} total. "
     "HOOK = the sender and the deadline. "
     "PROBLEM = reputable courier quoted £{courier_price} and {days} days — too slow. "
     "STAKES = {event} happening without the item arriving. "
     "RESOLUTION = BootHop matched them with a traveller leaving next morning. "
     "LESSON = someone was already going."),

    ("LAST-MINUTE AIRPORT DISCOVERY",
     "traveller",
     "Already at the airport departure lounge. A notification on BootHop: two senders nearby needed "
     "someone going to the same city. Accepted both parcels at the gate. Earned £{earn} before boarding. "
     "HOOK = traveller sitting at the gate, casually checking their phone. "
     "PROBLEM = had been making this trip for years and never earned a penny from the luggage allowance. "
     "STAKES = £{earn} sitting there, missed on every previous trip. "
     "RESOLUTION = opened BootHop, matched instantly, parcels delivered same evening in Lagos. "
     "LESSON = every journey has value."),

    ("SOMEONE IN NIGERIA NEEDS IT URGENTLY",
     "recipient",
     "A family member in Nigeria needed {item} urgently — not available locally or priced at triple. "
     "A sibling in the UK heard about it. Couriers wanted £{courier_price} and {days} days. "
     "BootHop found a traveller flying in 24 hours. Item arrived in {hours} hours. "
     "HOOK = the person in Nigeria and what they urgently need and why. "
     "PROBLEM = courier too slow and too expensive, item unavailable locally. "
     "STAKES = ceremony, exam, health, or milestone at risk if it doesn't arrive. "
     "RESOLUTION = BootHop matched the UK sender with a traveller flying next day. "
     "LESSON = the flight was already going. The parcel just needed a seat."),

    ("RETURNING TRAVELLER BRINGS ITEMS BACK",
     "traveller",
     "Coming back from Nigeria to the UK. Checked BootHop before leaving Lagos. "
     "Three diaspora families needed things sent from Nigeria to the UK — local fabric, spices, documents. "
     "Carried all three, earned £{earn} on the return leg. "
     "HOOK = traveller packing in Lagos the night before flying back to the UK. "
     "PROBLEM = diaspora families struggling to get Nigerian items shipped to the UK cheaply. "
     "STAKES = items stuck, high shipping costs, weeks of waiting. "
     "RESOLUTION = traveller took all three parcels, earned £{earn}, items delivered to three homes in the UK. "
     "LESSON = the journey already existed. BootHop made it useful both ways."),

    ("COMMUNITY WORD OF MOUTH DISCOVERY",
     "sender",
     "A friend mentioned BootHop at a Sunday gathering. She had been overpaying couriers for years. "
     "Posted that same evening needing {item} to reach Lagos for {event}. "
     "Matched with a traveller leaving in two days. Saved £{save} compared to what she would have paid. "
     "HOOK = the gathering, the conversation, the realisation. "
     "PROBLEM = had been paying £{courier_price} per parcel every time without knowing there was another way. "
     "STAKES = {event} and the item still stuck in the UK. "
     "RESOLUTION = BootHop matched her within hours, item delivered two days later. "
     "LESSON = movement already exists. BootHop makes it useful."),

    ("LATE NIGHT POST, EARLY MORNING FLIGHT",
     "sender",
     "Posted on BootHop at 11pm, not expecting much. A traveller flying at 6am accepted within the hour. "
     "Item delivered to Lagos that same afternoon. "
     "HOOK = midnight, item packaged, deadline tomorrow, one last attempt. "
     "PROBLEM = every courier had already said it was too late to guarantee the date. "
     "STAKES = the item missing {event} entirely. "
     "RESOLUTION = traveller accepted at 11:47pm, met at 5am, delivered by 3pm Lagos time. "
     "LESSON = someone was already flying. BootHop connected the dots."),

    ("CORPORATE TRAVELLER CARRIES ON A WORK TRIP",
     "traveller",
     "Flying to Lagos for a three-day conference. Checked BootHop on the way to the airport. "
     "Two small parcels for people in Lagos — accepted both. Earned £{earn} on a trip already expensed. "
     "HOOK = business traveller, taxi to Heathrow, opens the app out of curiosity. "
     "PROBLEM = had extra luggage allowance going to waste every single trip. "
     "STAKES = {earn} per trip unclaimed over years of work travel. "
     "RESOLUTION = accepted two parcels, delivered them the next morning, earned £{earn}. "
     "LESSON = the flight was already going. The parcel just needed a seat."),

    ("STUDENT FLYING HOME FOR HOLIDAYS EARNS",
     "traveller",
     "Flying home to Lagos for the summer break. Bags mostly empty. "
     "A flatmate told them about BootHop. Found three senders at their university town going to Lagos. "
     "Earned £{earn} — enough to clear part of the term's rent. "
     "HOOK = student at the end of term, packing light, flying home tomorrow. "
     "PROBLEM = empty bags, tight finances, about to fly with half the luggage allowance unused. "
     "STAKES = rent arrears back home, money stress following them on the holiday. "
     "RESOLUTION = BootHop matched them with three senders, earned £{earn} by the time they boarded. "
     "LESSON = every journey has value."),

    ("TRAVELLER WHO ALMOST DIDN'T CHECK",
     "traveller",
     "Almost didn't open the app. Flight was in four hours. Thought it was too late. "
     "Checked anyway — three senders within 20 minutes of the airport, parcels already packaged. "
     "Earned £{earn}, dropped off two parcels in Lagos that same evening. "
     "HOOK = traveller four hours from departure, doing last-minute checks. "
     "PROBLEM = assumed BootHop needed more time — almost left the money behind. "
     "STAKES = another trip where the luggage allowance earns nothing. "
     "RESOLUTION = matched in 8 minutes, parcels at the airport 90 minutes later, £{earn} earned. "
     "LESSON = the journey already existed. BootHop makes it useful."),
]

_TH_PRICE_PAIRS = [
    (68, 12, 42, "5-7"),
    (75, 14, 61, "7"),
    (55, 10, 45, "5"),
    (80, 16, 64, "6-8"),
    (62, 13, 49, "5"),
    (70, 11, 59, "7-10"),
]

_TH_EARN_AMOUNTS = [45, 55, 65, 72, 80, 85, 48, 60, 90, 38]

_TH_DELIVERY_HOURS = [18, 22, 28, 14, 36, 20, 24]


def _build_travel_hacks_angle() -> str:
    """Build a unique story direction by randomly drawing from ingredient pools."""
    protagonist = random.choice(_TH_PROTAGONISTS)
    item_tuple  = random.choice(_TH_ITEMS)
    comp        = random.choice(_TH_COMPLICATIONS)
    angle       = random.choice(_TH_ANGLES)
    prices      = random.choice(_TH_PRICE_PAIRS)
    earn        = random.choice(_TH_EARN_AMOUNTS)
    hours       = random.choice(_TH_DELIVERY_HOURS)

    name, role, city, _pov = protagonist
    item, item_context     = item_tuple
    courier_price, boothop_price, save, days = prices

    # Fill in templates
    comp_filled = (comp
        .replace("{price}", f"£{courier_price}")
        .replace("{days}", days)
        .replace("{event}", item_context.split("for")[-1].strip().rstrip(")")))

    angle_text = (angle[2]
        .replace("{item}", item)
        .replace("{earn}", str(earn))
        .replace("{hours}", str(hours))
        .replace("{courier_price}", f"£{courier_price}")
        .replace("{boothop_price}", f"£{boothop_price}")
        .replace("{save}", f"£{save}")
        .replace("{days}", days)
        .replace("{event}", item_context.split("for")[-1].strip().rstrip(")")))

    _POV_LABELS = {
        "traveller": "THE TRAVELLER'S POV — tell this entirely from the traveller's perspective",
        "sender":    "THE SENDER'S POV — tell this entirely from the sender's perspective",
        "recipient": "THE RECIPIENT'S POV — begin in Nigeria, with the person who is waiting",
    }
    pov_label = _POV_LABELS.get(angle[1], "")

    return (
        f"TODAY'S STORY INGREDIENTS — use ALL of these. Do not swap them out.\n\n"
        f"POINT OF VIEW: {pov_label}\n"
        f"PROTAGONIST: {name}, a {role} based in {city}\n"
        f"ITEM: {item} — {item_context}\n"
        f"COMPLICATION: {comp_filled}\n"
        f"STORY ANGLE: {angle[0]}\n"
        f"NARRATIVE SHAPE:\n{angle_text}\n\n"
        f"CRAFT RULES:\n"
        f"- Open with {name} and the human moment — NOT the price or BootHop\n"
        f"- Name {name} in the hook. Name the item. Name the event or deadline.\n"
        f"- Stay in {pov_label.split('—')[0].strip()} throughout — never switch perspective\n"
        f"- BootHop appears ONLY in the resolution beat — never earlier\n"
        f"- Every beat must contain one specific detail: a price, a time, a number, a quote\n"
        f"- RESOLUTION must include one unexpected moment that surprises the viewer\n"
        f"- Show the before-emotion (stress, panic, resignation) and after-emotion (relief, joy, pride)\n"
        f"- NEVER write about hotel booking, flight reservations, packing tips, or general travel advice\n"
        f"- This story is about peer-to-peer delivery discovered at exactly the right moment"
    )


def generate_content(slot: int, pillar: str, bucket: str) -> dict:
    """
    Stage 1: Story Writer generates the narrative.
    Stage 2: Scene Planner generates 8 scene-specific video queries.
    Applies 3-layer query safety: banned-term filter -> 14-day dedup -> fetch-time guard.
    """
    seed_bank_if_empty(TRANSPORT_QUERIES)
    promote_demote()
    maybe_weekly_refresh()

    pillar_label = PILLAR_LABELS.get(pillar, pillar)
    today = date.today().isoformat()
    day_name = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][date.today().weekday()]
    current_month = date.today().month
    month_name = ["","January","February","March","April","May","June",
                  "July","August","September","October","November","December"][current_month]

    pillar_angle = _PILLAR_ANGLES.get(pillar, "")

    # travel_hacks: build a fresh unique story direction from randomised ingredient pools
    if pillar == "travel_hacks":
        pillar_angle = _build_travel_hacks_angle()

    # ── Stage 0: News Editor — find today's top story ─────────────────────────
    print("  [NewsEditor] Searching for today's top story...")
    try:
        news_context = find_top_story(pillar)
    except Exception as _ne:
        print(f"  [NewsEditor] Failed: {_ne} — continuing without news context")
        news_context = None

    # ── Stage 1: Story Writer ─────────────────────────────────────────────────
    story_prompt = _build_story_prompt(
        slot, pillar, bucket, pillar_label, pillar_angle, day_name, month_name,
        news_context=news_context,
    )
    raw = _call_story_ai(story_prompt, v2=False)
    data = _parse_json(raw)

    # ── Stage 2: QA Director — review and improve the story ──────────────────
    data = review_and_improve(data, pillar)

    # ── Stage 3: Scene Planner ────────────────────────────────────────────────
    scene_queries = plan_scenes(data, pillar)

    # ── Stage 4: Photographer — upgrade queries + generate image prompts ──────
    photo_result = generate_image_prompts(data, scene_queries, pillar)
    queries = photo_result.get("pexels_queries", scene_queries)
    data["image_prompts"] = photo_result.get("image_prompts", [])

    # ── Stage 5: Cinematographer — generate video prompts for AI video tools ──
    video_result = generate_video_prompts(data, photo_result)
    data["video_prompts"] = video_result.get("video_prompts", [])

    # ── Stage 6: Reviewer — final quality gate ────────────────────────────────
    data = final_review(data, photo_result, pillar)

    # Apply 3-layer query safety to the Photographer's refined queries
    if len(queries) < 8:
        queries += [random.choice(ALL_TRANSPORT)] * (8 - len(queries))

    queries = _sanitize_queries(queries, _BEAT_ROLES)
    register_novel_queries(queries, _BEAT_ROLES)
    queries = _dedup_14day(queries, _BEAT_ROLES)
    _save_used_queries(queries, slot)
    data["visual_queries"] = queries

    # ── Memory DB — save the complete content package ─────────────────────────
    memory_db.save_entry(data, slot, version="v1")

    # Metadata
    tags_311 = _fetch_trending_tags(pillar=pillar)
    data["hashtags_tiktok"]    = _tiktok_hashtags(pillar, tags_311)
    data["hashtags_instagram"] = _instagram_hashtags(pillar, tags_311)
    data["hashtags_311"]       = tags_311
    data["youtube_tags"]       = _youtube_tags(pillar, data.get("hook", ""))
    data["youtube_category"]   = YOUTUBE_CATEGORIES.get(pillar, 22)
    data["pillar"]             = pillar
    data["slot"]               = slot
    data["date"]               = today

    return data


def generate_v2_content(slot: int, pillar: str, bucket: str, v1_content: dict) -> dict:
    """
    Stage 1-V2: Story Writer generates a completely different hook/lesson for V2.
    Stage 2-V2: Scene Planner generates fresh queries avoiding V1's clips.
    """
    pillar_label = PILLAR_LABELS.get(pillar, pillar)
    v1_hook   = v1_content.get("hook", "")
    v1_lesson = v1_content.get("lesson", "")

    prompt = f"""You write a SECOND VERSION of a BootHop video for the same content pillar.

BootHop = peer-to-peer parcel delivery. Travellers ALREADY flying between UK and Nigeria carry parcels for senders. The traveller was going anyway — BootHop connected them. NEVER write about hotels, flights, restaurants, packing tips, or general travel advice.

LANGUAGE RULE: British English only — no Yoruba, Pidgin, or any other language.

V1 already uses:
  Hook: "{v1_hook}"
  Lesson: "{v1_lesson}"

Your job: write V2 — a COMPLETELY DIFFERENT person, item, and emotion on the same pillar ({pillar_label}).

RULES FOR V2:
- Different character (new name, different job/city from V1)
- Different item — pick from: laptop, stethoscope, aso-oke, trainers, baby shoes, scrubs, framed photo, birthday gift, school uniform, signed sports shirt, tablet, wedding dress fabric, handmade jewellery
- Different emotional angle — if V1 was urgent/stressful, make V2 warm/celebratory (or vice versa)
- Hook: max 15 words. Start with person or moment — NOT a price or "BootHop"
- Lesson: max 10 words. Must use EXACTLY one of these closing lines:
    "The flight was already going. The parcel just needed a seat."
    "Movement already exists. BootHop makes it useful."
    "Someone was already flying. BootHop connected the dots."
    "The journey already existed. The parcel just joined it."
    "Every journey has value."
- NEVER use "unchanged", "same", or copy V1 text

COURIER RULE: NEVER name DHL, FedEx, Royal Mail, Hermes, Parcelforce, UPS.
Write "a reputable courier" or "a traditional courier service" instead.

Return ONLY valid JSON:
{{
  "hook_v2": "...",
  "lesson_v2": "..."
}}"""

    try:
        raw = _call_story_ai(prompt, v2=True)
        v2_data = _parse_json(raw)

        _SENTINEL = {"unchanged", "...", "same", "no change", "keep", "n/a", ""}
        hook_v2   = str(v2_data.get("hook_v2", "")).strip()
        lesson_v2 = str(v2_data.get("lesson_v2", "")).strip()
        v1_content["hook_v2"]   = hook_v2   if hook_v2   and hook_v2.lower()   not in _SENTINEL else v1_hook
        v1_content["lesson_v2"] = lesson_v2 if lesson_v2 and lesson_v2.lower() not in _SENTINEL else v1_lesson
        print(f"  [V2] Hook: {v1_content['hook_v2'][:80]}")

        # Stage 2-V2: Scene Planner generates fresh queries
        v1_queries = v1_content.get("visual_queries", [])
        queries = plan_scenes_v2(v1_content, pillar, v1_queries)

        if len(queries) < 8:
            queries += [random.choice(ALL_TRANSPORT)] * (8 - len(queries))

        queries = _sanitize_queries(queries, _BEAT_ROLES)
        queries = _dedup_14day(queries, _BEAT_ROLES)
        _save_used_queries(queries, slot)
        v1_content["visual_queries_v2"] = queries

    except Exception as e:
        print(f"  [V2] Generation failed, using V1 with shifted queries: {e}")
        q1 = v1_content.get("visual_queries", [])
        v1_content["hook_v2"]           = v1_hook
        v1_content["lesson_v2"]         = v1_lesson
        v1_content["visual_queries_v2"] = q1[4:] + q1[:4]

    return v1_content


def get_pillar_for_slot(slot: int) -> str:
    val = SLOT_PILLARS[slot]
    if isinstance(val, list):
        from datetime import date as _date
        return val[_date.today().weekday()]  # 0=Mon … 6=Sun
    return val


def get_bucket() -> str:
    from datetime import date as _date
    return DAY_BUCKETS[_date.today().weekday()]


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--slot", type=int, default=1)
    p.add_argument("--model", choices=["claude", "openai"], default=None,
                   help="Override STORY_MODEL for this run without editing config.py")
    args = p.parse_args()

    if args.model:
        # Patch the module-level constant so _call_story_ai picks it up
        globals()["STORY_MODEL"] = args.model

    pillar = get_pillar_for_slot(args.slot)
    bucket = get_bucket()
    active_model = globals().get("STORY_MODEL", STORY_MODEL)
    print(f"Slot {args.slot} | Pillar: {pillar} | Bucket: {bucket} | Story model: {active_model}")
    data = generate_content(args.slot, pillar, bucket)
    print(json.dumps(data, indent=2, ensure_ascii=False))
