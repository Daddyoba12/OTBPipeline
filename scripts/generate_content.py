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
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_openai(prompt: str, model: str = "gpt-4o", max_tokens: int = 1200) -> str:
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
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_gemini(prompt: str, model: str = "gemini-2.0-flash", max_tokens: int = 1200) -> str:
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
        },
        timeout=30,
    )
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
    news_block = ""
    if news_context:
        news_block = f"""
TODAY'S NEWS HOOK (use this as the factual basis for the story — make the video feel timely and real):
  Headline: {news_context.get('headline', '')}
  Summary: {news_context.get('summary', '')}
  Category: {news_context.get('category', '')}
  Suggested angle: {news_context.get('story_angle', '')}
  WHY IT MATTERS: {news_context.get('why_relevant', '')}

IMPORTANT: Base the story on this real event. The hook should reflect this specific situation.
Do not invent fake prices or facts — use the numbers from the news summary if available.
"""
    return f"""You write viral content for OTB — BootHop's content engine targeting UK/Nigeria diaspora on TikTok, Instagram, and YouTube.

LANGUAGE RULE — CRITICAL: Write EVERYTHING in British English only. No Yoruba, Pidgin, Igbo, Hausa, or any other language — not even single words or phrases. The audience speaks English; diaspora content performs better in English on these platforms.

CONTEXT:
- Slot: {slot} ({["","7am morning commute","12pm lunch scroll","6pm evening unwind","9pm night scroll"][slot]})
- Content Pillar: {pillar_label}
- Day: {day_name}, {month_name}
- Platform bucket tone: {bucket}
{f"- CONTENT ANGLE FOR THIS PILLAR: {pillar_angle}" if pillar_angle else ""}
{news_block}

ABOUT BOOTHOP:
BootHop is a peer-to-peer parcel delivery app. Travellers already flying between UK and Nigeria carry parcels for senders and earn money. Senders pay less than courier services and get same-day delivery.
- TRAVELLER = earns money carrying a stranger's parcel on a trip they were already making
- SENDER = pays a traveller to carry their parcel
These are ALWAYS two different people.

COURIER BRAND RULE — CRITICAL:
NEVER name specific courier companies (DHL, FedEx, Royal Mail, Hermes, Parcelforce, UPS) anywhere in the script.
ALWAYS write "a reputable courier" or "a traditional courier service" instead.

PRICE REALITY — only use figures within these real ranges:
- A reputable courier UK to Nigeria: £35-75 for a small parcel (0.5-2kg)
- BootHop peer-to-peer: £8-25 for a typical parcel on the same route
- Traveller earnings: £20-85 per trip, depending on parcel size

STORY ANCHOR — define this FIRST before writing any beat:
Pick ONE character, ONE specific item, ONE obstacle that links ALL 5 beats.
Every beat must stay inside this same situation — no jumping to new problems or new characters.

Good anchor example:
  CHARACTER: Yemi, a student in London
  ITEM: her mum's blood pressure tablets
  OBSTACLE: a reputable courier quoted £55 — more than the tablets cost
  TIME PRESSURE: mum runs out in 4 days

Bad anchor example:
  CHARACTER: "a woman" (too vague)
  ITEM: "a package" (too vague)
  OBSTACLE: "courier was expensive AND customs delays AND mum was sick" (too many problems)

SCRIPT FORMULA — 5 beats, ONE continuous story:
IMPORTANT: beats appear as on-screen text at 4 seconds each. SHORT = readable. LONG = cut off.
Every beat must logically continue from the previous one — same character, same item, same situation.

HOOK: max 15 words total. Stop the scroll in 2 seconds.
  Line 1 (3-6 words): The sharp punch — a specific number, item, or emotion.
  Line 2 (optional, up to 9 words): The mini-story setup — who, what situation.
  NEVER start with "BootHop". Use the specific item and character from your anchor.
  GOOD: "£55 for tablets. Her mum runs out in 4 days."
  BAD: "This woman had a really difficult situation sending something home."

PROBLEM: max 12 words. One tight sentence about the EXACT obstacle from your anchor.
  Must directly continue from the hook. Mention the specific price or obstacle.
  GOOD: "A reputable courier quoted £55. More than the tablets cost."
  BAD: "She tried everything. Customs delays made it worse." ← introduces NEW problem not in hook

STAKES: max 10 words. Why it MUST be solved RIGHT NOW. Use the time pressure from your anchor.
  Must reference the same character and situation — not a general statement.
  GOOD: "Four days until mum ran out. No time."
  BAD: "This happens to thousands of diaspora people every day." ← generic, drifted from anchor

RESOLUTION: max 12 words. BootHop appears HERE for the first time. Close the loop on the HOOK.
  Must directly solve the specific obstacle set up in HOOK and PROBLEM.
  GOOD: "She found a BootHop traveller flying to Lagos. £12. Done."
  BAD: "BootHop helps connect senders with travellers across the world." ← too generic, closes nothing

LESSON: max 10 words. One line the viewer will screenshot. Universal truth from THIS story.
  Must feel like the logical conclusion of this exact story — not a generic travel tip.
  GOOD: "The flight was going anyway. She just needed someone on it."
  BAD: "Always plan ahead when sending packages internationally." ← generic, could be from any story

THEN generate platform-specific outputs (these can be longer — they go in captions, not on screen):

TIKTOK:
- caption_tiktok: First 90 chars = hook reworded. Then 2 line breaks. Then 2-3 sentences. Then engagement question. Max 300 chars.

INSTAGRAM:
- caption_instagram: First 125 chars = strong hook. Full story 3-4 sentences. CTA. Max 400 chars.

YOUTUBE:
- youtube_title: Max 60 chars. Question or number format. Keyword-first. No "BootHop" in title.
- youtube_description: 2-3 sentences, first 100 chars keyword-rich. Include "BootHop.com" at end.

ENGAGEMENT: One short question (under 10 words) that invites real comments.

Return ONLY valid JSON (no markdown):
{{
  "story_anchor": {{
    "character": "one specific person",
    "item": "the exact item being sent or situation",
    "obstacle": "the single specific obstacle",
    "time_pressure": "why it must be resolved now"
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


# Pillar-specific content angle (for educational/documentary pillars)
_PILLAR_ANGLES = {
    "supply_chain": (
        "Write this as a mini-documentary about how global supply chains work — "
        "a realistic story about a UK-Nigeria logistics gap. Hook with a surprising fact or price. "
        "BootHop appears in RESOLUTION only — as the smart peer-to-peer alternative."
    ),
    "logistics_stories": (
        "Write this as an interesting logistics story — a surprising fact about how parcels move "
        "around the world, a customs challenge, or a last-mile delivery gap in Nigeria. "
        "Make it genuinely educational. BootHop appears in RESOLUTION only."
    ),
    "airport_deliveries": (
        "Write a dramatic realistic airport/customs story — a seized parcel, a last-minute save, "
        "or a traveller who carried something important like medication. "
        "Make the viewer feel the tension. BootHop appears in RESOLUTION as the smarter way."
    ),
}


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

    prompt = f"""You write a SECOND VERSION of a viral BootHop video for the same content pillar.

V1 already uses this hook: "{v1_hook}"
V1 lesson: "{v1_lesson}"

Your job: write V2 — a COMPLETELY DIFFERENT angle on the same pillar ({pillar_label}).
Different story. Different hook format. Different emotion. Different lesson.
Same quality, same punch — just a fresh take.

COURIER BRAND RULE: NEVER name DHL, FedEx, Royal Mail, Hermes, or any courier brand.
Always write "a reputable courier" or "a traditional courier service" instead.

BEAT LENGTH RULES (text appears on screen — keep it short):
- hook_v2: 1-2 sentences, max 15 words, completely different from V1 hook
- lesson_v2: max 10 words, fresh insight (not a rewording of V1 lesson)

Return ONLY valid JSON:
{{
  "hook_v2": "...",
  "lesson_v2": "..."
}}"""

    try:
        raw = _call_story_ai(prompt, v2=True)
        v2_data = _parse_json(raw)

        v1_content["hook_v2"]   = v2_data.get("hook_v2", v1_hook)
        v1_content["lesson_v2"] = v2_data.get("lesson_v2", v1_lesson)
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
    from datetime import date as _date
    day_idx = _date.today().timetuple().tm_yday % 4
    return SLOT_PILLARS[slot][day_idx]


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
