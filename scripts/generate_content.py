"""
OTB_Pipeline — AI content generator
5-beat formula: Hook -> Problem -> Stakes -> Resolution -> Lesson
Produces platform-specific captions, hashtags, and visual queries in one call.

Visual query rules (enforced at 3 layers):
  1. Claude prompt — explicit forbidden list + transport-only instruction
  2. _sanitize_queries() — post-process banned term check
  3. _dedup_14day() — 14-day no-repeat log so the same clip never appears twice
"""

import json, re, sys, random
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, SLOT_PILLARS, PILLAR_LABELS, DAY_BUCKETS, DATA
from fetch_trending_hashtags import fetch_today as _fetch_trending_tags

import requests
from query_learner import (
    seed_bank_if_empty, promote_demote, maybe_weekly_refresh,
    register_novel_queries, get_best_for_role,
    TRANSPORT_QUERIES, ALL_TRANSPORT,
)

# ── Banned query terms (hard block — any query containing these gets replaced) ──
BANNED_QUERY_TERMS = {
    # Animals (all varieties)
    "animal", "animals", "dog", "dogs", "cat", "cats", "horse", "horses",
    "pet", "pets", "puppy", "puppies", "kitten", "kittens", "bird", "birds",
    "lion", "tiger", "elephant", "monkey", "fish", "rabbit", "wildlife",
    "farm", "zoo", "livestock", "parrot", "sheep", "cow", "goat", "duck",
    "chicken", "pig", "hamster", "turtle", "snake", "gecko", "insect",
    # Food & food delivery brands — explicit ban
    "food", "food delivery", "uber eats", "ubereats", "deliveroo", "just eat",
    "doordash", "grubhub", "restaurant", "takeaway", "takeout", "pizza delivery",
    "meal delivery", "grocery delivery", "grocery", "meal", "cooking", "chef",
    "kitchen", "cafe", "diner", "burger", "sandwich", "bakery", "supermarket",
    "fast food", "drive through", "drive-through", "dining", "breakfast",
    # Christmas / holidays (always banned — BootHop is year-round, not seasonal)
    "christmas", "xmas", "santa", "reindeer", "christmas tree", "holiday season",
    "baubles", "nativity", "elf", "tinsel", "advent", "carol", "festive",
    "holiday shopping", "black friday", "cyber monday",
    # Other seasonal
    "halloween", "pumpkin", "easter", "egg hunt", "thanksgiving", "fireworks",
    "new year party", "valentine", "bonfire night",
    # Generic stock clichés that never match BootHop
    "teamwork handshake", "success mountain", "cartoon", "illustration",
    "trophy", "medal", "piggy bank", "light bulb idea",
}

# TRANSPORT_QUERIES and ALL_TRANSPORT are imported from query_learner (single source of truth)

# ── 14-day query log ──────────────────────────────────────────────────────────
QUERY_LOG = DATA / "query_log.json"


def _load_recent_queries(days: int = 14) -> set:
    """Return set of queries used in the last N days (normalised to lowercase)."""
    if not QUERY_LOG.exists():
        return set()
    try:
        log = json.loads(QUERY_LOG.read_text(encoding="utf-8"))
        cutoff = date.today() - timedelta(days=days)
        recent = set()
        for entry in log:
            try:
                entry_date = date.fromisoformat(entry["date"])
                if entry_date >= cutoff:
                    recent.add(entry["query"].strip().lower())
            except Exception:
                pass
        return recent
    except Exception:
        return set()


def _save_used_queries(queries: list, slot: int):
    """Append today's queries to the 14-day log, pruning entries older than 14 days."""
    try:
        log = json.loads(QUERY_LOG.read_text(encoding="utf-8")) if QUERY_LOG.exists() else []
    except Exception:
        log = []
    today_str = date.today().isoformat()
    cutoff = date.today() - timedelta(days=14)
    # Prune old entries
    log = [e for e in log if date.fromisoformat(e.get("date","2000-01-01")) >= cutoff]
    # Append new ones
    for q in queries:
        log.append({"query": q.strip().lower(), "date": today_str, "slot": slot})
    QUERY_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


# ── Sanitizer: banned term check ──────────────────────────────────────────────
def _sanitize_queries(queries: list, beat_roles: list) -> list:
    """Replace any query containing a banned term with a transport fallback."""
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
    """
    Replace any query used in the last 14 days with a fresh transport alternative.
    Pulls replacements from the live query bank (active > seed > trial),
    so the bank's quality improvements directly benefit dedup rotation.
    """
    recent = _load_recent_queries(14)
    result = []
    used_this_run = set()

    for i, q in enumerate(queries):
        norm = q.strip().lower()
        if norm in recent or norm in used_this_run:
            role = beat_roles[i] if i < len(beat_roles) else "hook"
            exclude = recent | used_this_run
            # Pull best available from the live bank for this role
            candidates = get_best_for_role(role, exclude, n=15)
            if not candidates:
                # Absolute fallback: any transport query not recently used
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
    # 3-1-1 strategy: exactly 5 rotating hashtags — #Brand + 3 topic + 1 trending
    # Never the same 5 twice — topic tags rotate on 7-day no-repeat cycle
    return " ".join(tags_311[:5])


def _instagram_hashtags(pillar: str, tags_311: list[str]) -> str:
    # Core 5 from 3-1-1 engine + up to 15 more pillar-specific tags for IG reach
    # IG algo sweet spot: 20-30 hashtags, but core 5 are the freshest/most relevant
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


def generate_content(slot: int, pillar: str, bucket: str) -> dict:
    """
    Call Claude to generate full 5-beat content + platform-specific outputs.
    Applies 3-layer query safety: banned-term filter -> 14-day dedup -> fetch-time guard.
    Also runs the auto-learner lifecycle: seed init, promote/demote, weekly refresh.
    Returns a dict with all fields needed for video + posting.
    """
    # Auto-learner lifecycle — runs fast (file reads only, except weekly Claude call)
    seed_bank_if_empty(TRANSPORT_QUERIES)
    promote_demote()
    maybe_weekly_refresh()

    pillar_label = PILLAR_LABELS.get(pillar, pillar)
    today = date.today().isoformat()
    day_name = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][date.today().weekday()]
    current_month = date.today().month
    month_name = ["","January","February","March","April","May","June",
                  "July","August","September","October","November","December"][current_month]

    # Pillar-specific content angle — informational pillars use a documentary/educational tone
    # (proven by BootHopBD: educational content gets 3-5x more shares than pure promo)
    _PILLAR_ANGLES = {
        "supply_chain": (
            "Write this as a mini-documentary about how global supply chains actually work — "
            "a real or realistic story (a port strike, a famous shipping failure, a courier crisis, "
            "or a UK-Nigeria logistics gap). Hook with a surprising fact. BootHop appears in RESOLUTION "
            "only — as the smart peer-to-peer alternative to the broken system you just described."
        ),
        "logistics_stories": (
            "Write this as an interesting logistics story — a real brand, a famous incident, or a "
            "surprising fact about how parcels move around the world (DHL, FedEx, customs, last-mile "
            "delivery gaps in Nigeria, UK postal strikes, etc.). Make it genuinely educational. "
            "BootHop appears in RESOLUTION only — positioned as the solution the big players can't offer."
        ),
        "airport_deliveries": (
            "Write a dramatic real-or-realistic airport/customs story — a missed package, a seized parcel, "
            "a last-minute save at the gate, or a traveller who carried something important. "
            "Make the viewer feel the tension. BootHop appears in RESOLUTION as the smarter, safer way."
        ),
    }
    pillar_angle = _PILLAR_ANGLES.get(pillar, "")

    prompt = f"""You write viral content for OTB — BootHop's content engine targeting UK/Nigeria diaspora on TikTok, Instagram, and YouTube.

CONTEXT:
- Slot: {slot} ({["","7am morning commute","12pm lunch scroll","6pm evening unwind","9pm night scroll"][slot]})
- Content Pillar: {pillar_label}
- Day: {day_name}, {month_name}
- Platform bucket tone: {bucket}
{f"- CONTENT ANGLE FOR THIS PILLAR: {pillar_angle}" if pillar_angle else ""}

ABOUT BOOTHOP:
BootHop is a peer-to-peer parcel delivery app. Travellers already flying between UK and Nigeria (or other routes) carry parcels for senders and earn money. Senders pay less than courier services and get same-day delivery.
- TRAVELLER = earns money carrying a stranger's parcel on a trip they were already making
- SENDER = pays a traveller to carry their parcel
These are ALWAYS two different people.

SCRIPT FORMULA — 5 beats, each crisp and punchy:

HOOK: 1-2 sentences, max 15 words. Must stop the scroll in 2 seconds.
  Structure: SHORT PUNCH (3-6 words) + STORY (rest of hook).
  Best formats: "She/He [specific moment]..." or "[pound-amount] for [weight]?" or "3 people. 1 route. [number] earned."
  NEVER start with "BootHop". NEVER be generic. Use specific numbers, routes, items.
  PRICE REALITY — only use figures within these real-world ranges:
  - DHL/FedEx UK→Nigeria: £35–75 for a small parcel (0.5–2kg). A phone charger (<500g) costs £35–50, NOT £150+.
  - BootHop peer-to-peer: £8–25 for a typical parcel on the same route.
  - Traveller earnings: £20–85 per trip, depending on parcel size.
  NEVER invent prices outside these ranges. If unsure, use a story-based hook instead of a price hook.

PROBLEM: 2-3 sentences. The friction, the pain, the struggle. Make the viewer feel it.

STAKES: 1-2 sentences. Why does this matter personally to the viewer? Emotional bridge.

RESOLUTION: 2-3 sentences. How BootHop solves it. Specific, vivid, real.
  BootHop appears here for the first time as the solution.

LESSON: 1 punchy line. The takeaway they will screenshot or share.

THEN generate platform-specific outputs:

TIKTOK:
- caption_tiktok: First 90 chars = hook reworded. Then 2 line breaks. Then 2-3 sentences. Then engagement question. Max 300 chars.

INSTAGRAM:
- caption_instagram: First 125 chars = strong hook. Full story 3-4 sentences. CTA. Max 400 chars.

YOUTUBE:
- youtube_title: Max 60 chars. Question or number format. Keyword-first. No "BootHop" in title.
- youtube_description: 2-3 sentences, first 100 chars keyword-rich. Include "BootHop.com" at end.

VISUAL QUERIES — 8 Pexels search queries for video clips (max 6 words each).

MANDATORY: Queries MUST show transport scenes — planes, trains, taxis, cargo ships, airports.
Use ONLY: airplanes, airports, departure gates, runways, trains, rail platforms, taxis/cabs,
ocean cargo ships, shipping ports, suitcases, parcels, travellers walking, city streets,
london/lagos cityscapes, professional people at transport hubs.

NEVER USE IN ANY QUERY:
- Animals (dog, cat, horse, bird, pet, wildlife, farm, zoo — ANY animal)
- Food or food delivery (Uber Eats, Deliveroo, restaurant, takeaway, meal, grocery, pizza, chef, kitchen)
- Christmas/Xmas/Santa/reindeer/baubles (it is {month_name} — no holiday imagery)
- Halloween/pumpkin/thanksgiving/easter
- Generic stock clichés (handshake, trophy, success mountain, cartoon, lightbulb)

CORRECT query examples: "airplane takeoff runway sunrise", "woman shocked phone screen close up face",
"traveller stressed queue airport close up reaction", "cargo ship open sea horizon",
"man frustrated phone call close up face", "parcel handover doorstep smile close up"

WRONG (never do this): "food delivery driver", "dog with parcel", "christmas gift shipping",
"wide airport hall crowd far shot", "establishing shot terminal building exterior"

SHOT TYPE RULES — these determine visual quality:
- Clip 0 (hook): CLOSE UP face reaction — "woman shocked face phone close up reaction"
- Clip 1 (hook reinforce): motion/energy transport scene — "airplane wing takeoff dramatic"
- Clip 2 (problem): CLOSE UP or MEDIUM SHOT person stressed — "man frustrated phone call close up face"
- Clip 3 (problem escalate): MEDIUM SHOT stressed person at transport hub — not wide establishing shots
- Clip 4 (stakes): MEDIUM CLOSE emotional moment — face or hands, NOT wide crowd shots
- Clip 5 (resolution): MEDIUM SHOT successful handover/delivery, person visible clearly
- Clip 6 (resolution payoff): CLOSE UP or MEDIUM — happy face, relief expression
- Clip 7 (lesson/brand): WIDE confident city shot OR MEDIUM professional — London or Lagos cityscape

ENGAGEMENT: One short question (under 10 words) that invites real comments.

Return ONLY valid JSON (no markdown):
{{
  "hook": "...",
  "problem": "...",
  "stakes": "...",
  "resolution": "...",
  "lesson": "...",
  "caption_tiktok": "...",
  "caption_instagram": "...",
  "youtube_title": "...",
  "youtube_description": "...",
  "visual_queries": ["q0","q1","q2","q3","q4","q5","q6","q7"],
  "engagement": "..."
}}"""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"].strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"No JSON in Claude response: {raw[:200]}")

    data = json.loads(match.group())

    # Layer 1: banned-term sanitizer
    claude_raw = data.get("visual_queries", [])
    if len(claude_raw) < 8:
        claude_raw += [random.choice(ALL_TRANSPORT)] * (8 - len(claude_raw))
    queries = _sanitize_queries(claude_raw, _BEAT_ROLES)

    # Register any novel Claude queries that survived sanitizer (they become trial entries)
    register_novel_queries(queries, _BEAT_ROLES)

    # Layer 2: 14-day no-repeat deduplicator (uses live bank for smart replacements)
    queries = _dedup_14day(queries, _BEAT_ROLES)

    # Persist the queries we're about to use (feeds the 14-day log)
    _save_used_queries(queries, slot)

    data["visual_queries"] = queries

    # 3-1-1 hashtag engine: #Brand + 3 topic (pillar-matched, 7-day rotation) + 1 trending
    tags_311 = _fetch_trending_tags(pillar=pillar)

    # Platform-specific metadata
    data["hashtags_tiktok"]    = _tiktok_hashtags(pillar, tags_311)
    data["hashtags_instagram"] = _instagram_hashtags(pillar, tags_311)
    data["hashtags_311"]       = tags_311   # raw 5-tag list for Telegram preview
    data["youtube_tags"]       = _youtube_tags(pillar, data.get("hook", ""))
    data["youtube_category"]   = YOUTUBE_CATEGORIES.get(pillar, 22)
    data["pillar"]             = pillar
    data["slot"]               = slot
    data["date"]               = today

    return data


def generate_v2_content(slot: int, pillar: str, bucket: str, v1_content: dict) -> dict:
    """
    Generate V2 hook, lesson, and visual queries — a completely different angle on the same pillar.
    Shares V1's problem/stakes/resolution beats but uses a fresh hook, lesson, and clip queries.
    """
    pillar_label = PILLAR_LABELS.get(pillar, pillar)
    v1_hook   = v1_content.get("hook", "")
    v1_lesson = v1_content.get("lesson", "")

    prompt = f"""You write a SECOND VERSION of a viral BootHop video for the same content pillar.

V1 already uses this hook: "{v1_hook}"
V1 lesson: "{v1_lesson}"

Your job: write V2 — a COMPLETELY DIFFERENT angle on the same pillar ({pillar_label}).
Different story. Different hook format. Different emotion. Different lesson.
Same quality, same punch — just a fresh take so audiences who saw V1 still engage with V2.

Rules:
- Hook must be totally different from V1 (different story, different format)
- Lesson must be a fresh insight (not a rewording of V1's lesson)
- Visual queries: 8 transport/diaspora Pexels search queries, max 6 words each
- ONLY: planes, airports, trains, taxis, parcels, city streets, professional people at transport hubs
- NEVER: animals, food, holidays, handshakes, cartoons
- Shot types: clips 0-1 close-up face/reaction, 2-3 medium stressed person, 4 emotional close-up,
  5-6 resolution handover/happy face, 7 wide London/Lagos cityscape

Return ONLY valid JSON:
{{
  "hook_v2": "...",
  "lesson_v2": "...",
  "visual_queries_v2": ["q0","q1","q2","q3","q4","q5","q6","q7"]
}}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            v2_data = json.loads(match.group())
            # Sanitize + dedup V2 queries (same 3-layer safety)
            raw_q = v2_data.get("visual_queries_v2", [])
            if len(raw_q) < 8:
                raw_q += [random.choice(ALL_TRANSPORT)] * (8 - len(raw_q))
            q = _sanitize_queries(raw_q, _BEAT_ROLES)
            q = _dedup_14day(q, _BEAT_ROLES)
            _save_used_queries(q, slot)
            v1_content["hook_v2"]           = v2_data.get("hook_v2", v1_content.get("hook", ""))
            v1_content["lesson_v2"]         = v2_data.get("lesson_v2", v1_content.get("lesson", ""))
            v1_content["visual_queries_v2"] = q
            print(f"  [V2] Hook: {v1_content['hook_v2'][:80]}")
    except Exception as e:
        print(f"  [V2] Generation failed, using V1 with shifted queries: {e}")
        # Fallback: shift V1 queries + reuse hook with slight prefix change
        q1 = v1_content.get("visual_queries", [])
        v1_content["hook_v2"]           = v1_hook
        v1_content["lesson_v2"]         = v1_lesson
        v1_content["visual_queries_v2"] = q1[4:] + q1[:4]  # rotate by 4

    return v1_content


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
    args = p.parse_args()
    pillar = get_pillar_for_slot(args.slot)
    bucket = get_bucket()
    print(f"Slot {args.slot} | Pillar: {pillar} | Bucket: {bucket}")
    data = generate_content(args.slot, pillar, bucket)
    print(json.dumps(data, indent=2, ensure_ascii=False))
