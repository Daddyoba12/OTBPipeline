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
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, STORY_MODEL, QA_MODEL,
    SLOT_PILLARS, PILLAR_LABELS, DAY_BUCKETS, DATA,
)
from fetch_trending_hashtags import fetch_today as _fetch_trending_tags
from scene_planner import plan_scenes, plan_scenes_v2
try:
    from trend_scout import get_trend_context as _get_trend_context
except ImportError:
    def _get_trend_context(): return ""
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
    "courier_business":   ["#CourierBusiness", "#LogisticsJobs", "#DeliveryBusiness", "#CourierUK", "#FreightUK"],
    "personal_shopper":   ["#PersonalShopper", "#ShopForMe", "#DubaiToLagos", "#LondonToLagos", "#ShoppingHaul"],
    "multi_courier":          ["#BusinessLogistics", "#CourierOptions", "#SMEUk", "#ShippingBusiness", "#BootHopBusiness"],
    "faith_friday":           ["#FaithFriday", "#WayMaker", "#GodProvides", "#PrayerLine", "#SundayBlessings"],
    "celebration_weekend":    ["#WeekendVibes", "#CelebrationSzn", "#AfrobeatsUK", "#NigerianWedding", "#PartyHard"],
    "flight_discovery":       ["#CheapFlights", "#FlightDeals", "#UKToNigeria", "#LagosFlights", "#BootHopFlights"],
    "supply_chain":           ["#SupplyChain", "#Logistics", "#BusinessTips", "#OperationsLife", "#TradeRoutes"],
}

INSTAGRAM_TAGS = {
    "community":          "#BootHop #LondonToLagos #DiasporaMagic #SameDayDelivery #NaijaUK #AfricanDiaspora #UKNigeria #CommunityFirst #AbroadLife #FamilyAbroad #DiasporaLife #NigerianUK #HumanLogistics #TrustPeople #UKtoNigeria #PeerDelivery #NaijaCommunity #SendingLove #Londoner #UKAfrica",
    "family":             "#BootHop #LondonToLagos #DiasporaMagic #SameDayDelivery #FamilyAbroad #CarePackage #SendingLove #HomeCountry #FamilyFirst #MumAbroad #NaijaUK #AfricanFamily #DiasporaFamily #UrgentDelivery #UKtoNigeria #MissingHome #FamilyLove #LondonLife #NigerianDiaspora #AfricanDiaspora",
    "airport":            "#BootHop #LondonToLagos #AirportLife #TravelDrama #Customs #AirportStories #TravelStress #AirportVibes #TravelUK #DiasporaMagic #UKNigeria #SameDayDelivery #AirportDelivery #LagosLife #NaijaUK #TravelHack #FamilyAbroad #UrgentDelivery #FreightLife #LogisticsLife",
    "smart":              "#BootHop #LondonToLagos #TravelHacks #SmartTravel #SaveMoney #SideIncome #TravelTips #PackingTips #EarnWhileTravel #TravelSmart #DiasporaMagic #UKNigeria #SameDayDelivery #NaijaUK #AbroadLife #HumanLogistics #TravelLife #FreelanceUK #SideHustle #MakeMoneyTravel",
    "travel_hacks":       "#BootHop #TravelHacks #TravelTips #PackingTips #SaveMoney #TravelSmart #SameDayDelivery #DiasporaMagic #LondonToLagos #UKNigeria #AbroadLife #NaijaUK #UrgentDelivery #TravelLife #HumanLogistics #SmartTravel #DiasporaLife #AfricanDiaspora #UKtoNigeria #TravelInspo",
    "logistics_stories":  "#BootHop #LogisticsLife #SupplyChain #DeliveryStories #CourierLife #LastMile #FreightLife #ShippingLogistics #LogisticsUK #DiasporaMagic #LondonToLagos #SameDayDelivery #Logistics2024 #TradingLife #NaijaUK #HumanLogistics #BusinessUK #UrgentDelivery #TradeUK #GlobalLogistics",
    "airport_deliveries": "#BootHop #AirportDelivery #CustomsLife #AirportDrama #FreightLife #AirsideLife #CargoLife #AirportLogistics #DiasporaMagic #LondonToLagos #SameDayDelivery #NaijaUK #UrgentDelivery #AirportStories #DeliveryLife #ShippingUK #LogisticsLife #CourierUK #TravelHack #UKNigeria",
    "courier_business":   "#BootHop #BootHopBusiness #CourierBusiness #LogisticsUK #DeliveryBusiness #CourierUK #FreightUK #CourierLife #LogisticsJobs #DeliveryJobs #SmallBusiness #UKLogistics #SideHustleUK #CourierNetwork #ParcelDelivery #LastMile #LogisticsNetwork #ShippingUK #FreelanceCourier #BusinessGrowthUK",
    "personal_shopper":   "#BootHop #PersonalShopper #ShopForMe #DubaiToLagos #LondonToLagos #UKToNigeria #ShoppingHaul #LagosLife #CustomsHandled #NigerianShopper #AfricanShopper #LuxuryShopping #ShippingToNigeria #NaijaUK #AbujaShopping #PortHarcourtLife #DeliveryToNigeria #InternationalShopping #DiasporaLife #ShopAndShip",
    "multi_courier":          "#BootHop #BootHopBusiness #MultiCourier #BusinessLogistics #SMEuk #ShippingBusiness #CourierOptions #LogisticsPlatform #UKBusiness #BusinessGrowth #ExportUK #ImportExport #CourierComparison #SmallBusinessUK #AfricanBusiness #DiasporaBusinessUK #ShippingRates #FreightOptions #LogisticsNetwork #BusinessTips",
    "faith_friday":           "#BootHop #FaithFriday #WayMaker #GodProvides #PrayerLine #SundayBlessings #ChristianTikTok #NigerianChristians #DiasporaFaith #UKChurch #MercyChinwo #NathanielBassey #Sinach #MaverickCityMusic #KirkFranklin #DunsinOyekan #GospelUK #ChristianCommunity #FaithAndLogistics #TravelMercies",
    "celebration_weekend":    "#BootHop #WeekendVibes #CelebrationSzn #AfrobeatsUK #NigerianWedding #NamingCeremony #NaijaParty #UKNigeria #AfricanWedding #GraduationParty #PartyHard #DanceChallenge #AfrobeatsLife #LagosToUK #NaijaUK #DiasporaLife #CelebrationVibes #WeekendMood #AfricanCelebration #JoyfulDelivery",
    "flight_discovery":       "#BootHop #CheapFlights #FlightDeals #UKToNigeria #LagosFlights #AbujFlights #CheapFlightsToNigeria #NigeriaTravel #AfricaFlights #FlightComparison #TravelDeals #NaijaUK #DiasporaTravel #UKNigeria #AfricaTravel #BudgetTravel #CheapFlightsUK #TravelTips #FlightHack #BootHopFlights",
    "supply_chain":           "#BootHop #SupplyChain #Logistics #BusinessTips #OperationsLife #TradeRoutes #GlobalTrade #BusinessUK #LogisticsLife #FreightLife #ShippingIndustry #DiasporaMagic #LondonToLagos #SameDayDelivery #BusinessOwner #SME #StartupUK #HumanLogistics #TradeUK #LogisticsUK",
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

def _hook_intelligence_block() -> str:
    """Return a prompt section with hook patterns if analysis data exists."""
    try:
        from hook_analyzer import load_patterns
        patterns = load_patterns()
        if not patterns:
            return ""
        top = patterns.get("top_patterns", [])[:3]
        suggested = patterns.get("suggested_hooks", [])[:5]
        avoid = patterns.get("avoid", [])[:3]
        if not top and not suggested:
            return ""
        lines = ["━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                 "HOOK INTELLIGENCE — from our best-performing hooks this week",
                 "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                 "These patterns consistently produce high hook-strength and virality scores."]
        if top:
            lines.append("TOP PATTERNS (use these structures as inspiration, not copy-paste):")
            for pt in top:
                lines.append(f"  [{pt.get('trigger','').upper()}] {pt.get('structure','')}  — {pt.get('why_it_works','')}")
        if suggested:
            lines.append("EXAMPLE HOOKS GENERATED FROM THESE PATTERNS (for inspiration only — write something fresh):")
            for h in suggested:
                lines.append(f"  ✓ {h}")
        if avoid:
            lines.append("AVOID (overused or weak in this niche):")
            for a in avoid:
                lines.append(f"  ✗ {a}")
        lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""


def _recent_hooks_block(days: int = 14) -> str:
    """Inject hooks used in the last N days as explicit avoids so patterns don't repeat."""
    try:
        mem_file = DATA / "memory.json"
        if not mem_file.exists():
            return ""
        mem = json.loads(mem_file.read_text(encoding="utf-8"))
    except Exception:
        return ""

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent_hooks = [
        e.get("hook", "").strip()
        for e in mem
        if e.get("date", "") >= cutoff and e.get("hook", "").strip()
    ]
    if not recent_hooks:
        return ""

    # Detect overused openers so the AI gets an explicit structural warning
    openers: dict[str, int] = {}
    for h in recent_hooks:
        first_words = " ".join(h.lower().split()[:4])
        openers[first_words] = openers.get(first_words, 0) + 1
    overused = [opener for opener, count in openers.items() if count >= 2]

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"HOOKS USED IN THE LAST {days} DAYS — DO NOT reuse these phrasings or structures",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for h in recent_hooks[-14:]:
        lines.append(f"  ✗ {h}")
    if overused:
        lines.append("")
        lines.append("OVERUSED OPENERS — never start a hook with any of these this week:")
        for opener in overused:
            lines.append(f"  ✗ '{opener}...'")
    lines.append("")
    lines.append(
        "Your hook must open with a DIFFERENT structure from everything above. "
        "Rotate: lead with a specific person and a specific problem, or a time-bound crisis, "
        "or a striking number, or a question that names the item/stakes before asking. "
        "Avoid 'Would you trust a stranger' unless it appears zero times above."
    )
    lines.append("")
    return "\n".join(lines)


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

ABSOLUTE BAN — NO ANIMALS: Do not include any animal, pet, wildlife, or creature of any kind in any scene, story beat, character description, or visual suggestion. No dogs, cats, birds, horses, fish, livestock, or any other animal. Any story that references an animal in any context is immediately rejected.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND PHILOSOPHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BootHop doesn't sell delivery. BootHop unlocks unused human movement.
Every day, millions of people are already travelling between UK and Nigeria.
BootHop gives those journeys a second purpose.

BootHop doesn't just deliver parcels. It rescues moments.
The real competitor isn't DHL — it's a WhatsApp message: "Is anyone going to Lagos?"
BootHop gives that informal network a platform, a price, and a guarantee.

When time matters more than distance, BootHop finds another way.

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
1. PERSON     A specific named person with real context (not "a woman" — "Sade, a nurse in Wolverhampton").
              Names can be Nigerian/African (Emeka, Sade, Amara, Tunde) OR Western/UK (Sarah, James, Emma, Daniel).
              BootHop serves all UK residents — mix it up across videos.
              ROTATE the lead character type: men, women, couples, students, parents, business owners, grandparents.
              BANNED visual archetype: do NOT write a story where the main character's defining moment is a shocked
              expression — hand over mouth, wide eyes, staring at phone in disbelief. Write calm, purposeful people
              with real emotional range (relief, pride, determination, joy, laughter).
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
HOOK — THREE PROVEN FORMATS (rotate, never repeat the same format twice in a row)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pick ONE format per video. Rotate through all three — variety drives discovery.

FORMAT 1 — POV QUESTION (puts viewer inside the situation):
  "Would you let a stranger carry your mum's framed photo to Lagos?"
  "What if the only person flying tomorrow is someone you've never met?"
  "Would you risk it — a stranger, a flight, your dad's gift — to save £60?"
  Rule: must feel personal. Story immediately answers through one named character.

FORMAT 2 — NOBODY TOLD US (community discovery / insider reveal — TRENDING):
  "Nobody told me Nigerians in the UK could earn £200 just for flying home."
  "Nobody told us there was a cheaper way to send things to Naija."
  "Nobody told her there was a traveller already booked on that flight."
  Rule: opens with discovery energy. Creates FOMO. Best for traveller-earns stories.

FORMAT 3 — CINEMATIC STATEMENT (specific moment or number, immediate tension):
  "She posted at midnight. By 6am the parcel was on a plane to Lagos."
  "He nearly left £200 on the table. He almost didn't check the app."
  "The ceremony was Saturday. The parcel was still in Leeds on Thursday night."
  Rule: opens with a concrete moment or number. No brand name. Pure tension.

FORMAT 4 — THIS ALMOST DIDN'T ARRIVE (series format — zero setup, pure crisis):
  "This almost missed the graduation."
  "This almost didn't make the wedding."
  "Three days before the ceremony. Still in Birmingham."
  "His visa interview was tomorrow. The parcel hadn't left London."
  Rule: drop the viewer into the crisis immediately. No "Imagine". No setup. Works best for
  wedding dresses, graduation certificates, visa documents, medication, birthday gifts arriving
  on the day itself. The story immediately answers: what almost didn't arrive, and who rescued it.

HOOK TIMING RULE: the hook must do its job in 0-2 seconds.
  ✗ WRONG: "Imagine you needed to send something urgent to Lagos…"
  ✓ RIGHT: "The courier said 10 days. She had 3."
  ✓ RIGHT: "Her graduation was on Saturday."
  ✓ RIGHT: "He almost didn't open the app."
  Immediacy is the hook. Every word earns its place or gets cut.

Then IMMEDIATELY continue with the named character (Emeka, Sade, Sarah, James, Tunde, Emma etc.)

✗ NEVER start with "Imagine" — it signals a slow hook
✗ NEVER start with a BootHop name or price in the hook
✗ NEVER reuse an opener from the HOOKS USED IN LAST 14 DAYS list below
✗ "Would you trust a stranger" is OVERUSED — avoid unless it genuinely fits best

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ITEMS — use variety, NEVER default to tablets or medication
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gifts:        birthday gift, graduation gift, wedding present, baby shower hamper, anniversary gift
Clothing:     aso-oke fabric, agbada, jordans/trainers, nursing scrubs, school uniform, wedding dress fabric, used clothes
Electronics:  laptop, phone charger, tablet, headphones, smart watch, gaming controller
Professional: medical stethoscope, exam certificate, portfolio prints, visa documents, university acceptance letter
School:       textbooks, school shoes, stationery pack, school uniform, WAEC result certificate
Keepsakes:    framed family photo, handmade jewellery, signed sports shirt, handwritten letter
Baby items:   baby clothes, baby shoes, toys, formula tin
Food (sealed only): Nigerian spices, jollof rice spice mix, stockfish, Indomie noodles, shea butter
Emergency:    prescription medication, hospital discharge paperwork, legal documents, passport copy

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RELATIONSHIP VARIETY — never default to dad/mum
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stories MUST rotate through different relationships and discovery scenarios.
Do NOT always use "his dad" or "her mum" — that becomes a formula viewers tune out.

RELATIONSHIP OPTIONS (pick one, rotate across days):
- A complete stranger who posted in a Nigerian WhatsApp group
- A colleague at work who mentioned BootHop in passing
- A friend of a friend who needed something sent urgently
- Someone the sender has never met — just a name and a delivery address
- A business owner sending product samples to a Lagos stockist
- A student sending exam certificates home before a family ceremony
- A church member who heard about BootHop at Sunday service
- Someone who Googled "send parcel to Nigeria cheap" at midnight and found BootHop
- A neighbour who knocked on the door because they saw a BootHop sticker
- An old flatmate in Lagos who needs something from the UK

DISCOVERY SCENARIOS — how they found BootHop (rotate these too):
- Typed "cheap parcel to Nigeria" at 11pm and found BootHop on the third result
- Someone in their WhatsApp group posted the link — they signed up the same night
- A traveller on the same flight told them about it at check-in
- They saw a BootHop post on TikTok and opened the app that same evening
- Their sister mentioned it had saved her £55 — they tried it the next day
- A colleague had used it twice — they logged in on their lunch break

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
6. "When time matters more than distance, BootHop finds another way."

SOCIAL PROOF — add one specific verifiable fact in RESOLUTION or LESSON when it fits naturally:
  Timing: "Matched in 18 minutes." / "Delivered in 41 hours." / "She replied in eight seconds."
  Price:  "She paid £14." / "£11 total." / "A fraction of what the courier wanted."
  Scale:  "Thousands of travellers make this route every week."
  One fact makes the story feel real. Do not stack multiple stats — one lands harder than three.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEAT RULES (on-screen video text / voice over — SHORT is essential, text gets cut off if too long)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
These 5 beats ARE the video. They appear as text overlays or voice over on the clips.
Each beat must be ONE clear sentence. Simple. Direct. The viewer reads it in 2 seconds and moves on.

HOOK:       max 15 words. A POV question to the viewer ("Would you trust a stranger with your dad's parcel?")
            Immediately follow in PROBLEM with the character's name and situation.
PROBLEM:    max 12 words. [Character name] + the specific item + the specific deadline. One sentence.
            Example: "Emeka had a framed photo and letter ready in Leeds. The ceremony was Saturday."
STAKES:     max 10 words. What fails if it doesn't arrive. Concrete. No vague emotion.
RESOLUTION: max 12 words. BootHop matched them. Traveller was ALREADY going. Item arrived. Simple.
            Example: "A BootHopper flying from Manchester picked it up. Delivered before the ceremony."
LESSON:     max 10 words. Use ONE closing line from the brand language bank above, EXACTLY.

THE STORY MUST PASS THIS TEST: read all 5 beats in order. Does it tell the WHOLE story in 10 seconds?
Can a 10-year-old understand it? If yes, it's ready. If not, simplify.

VIDEO TIMING GUIDE (30-second TikTok/Reels format — write to these windows):
  0-2s   HOOK reads. Viewer decides to keep watching. Immediate crisis or specific fact.
  2-8s   PROBLEM + STAKES combined. Tension is locked in. Viewer is now invested.
  8-15s  MOVEMENT beat. Someone was already going. Hope appears.
  15-25s RESOLUTION + unexpected moment. Relief, surprise, emotion.
  Last 5s LESSON. Viewer should want to comment.

RESOLUTION — add a verifiable, specific fact here whenever possible:
  "Matched in 18 minutes." / "Delivered in 41 hours." / "She paid £14 total."
  "The parcel arrived before the courier had even sent a confirmation email."
  A concrete number in the resolution makes the whole story feel true.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLATFORM CAPTIONS (go in the app caption field — NOT on the video screen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The caption is NOT a story summary and NOT a repeat of the hook.
The video tells the story. The caption drives the NEXT ACTION.

CAPTION STYLE — pick the correct style based on SLOT (defined below).
DO NOT copy the examples verbatim. Write a FRESH, ORIGINAL line each time.

SLOT 2 (afternoon, 14:00) — ALWAYS use BOOKING CTA style. No exceptions.
ALL OTHER SLOTS — rotate through the four brand styles below (never use Booking CTA).

━━ BOOKING CTA STYLE (SLOT 2 ONLY) ━━
  Goal: get someone with a parcel RIGHT NOW to post a job at boothop.com.
  Tone: direct, specific, urgent. Talks to someone who has a problem today.
  Rules:
    - Name the action ("Post your parcel", "List your job", "Post it free")
    - Name the destination or route ("to Nigeria", "Lagos or Abuja", "to Naija")
    - Include "boothop.com" — not as a brand mention, as the destination of the action
    - Give a reason to do it NOW (free, fast, takes 60 seconds, someone already flying)
    - Max 130 chars. No hashtags.
  Examples (write something NEW — do not copy):
    "Got something to send to Nigeria this week? Post it free at boothop.com — someone's already flying."
    "Stop refreshing courier sites. Post your parcel to Lagos free → boothop.com"
    "Sending to Naija? Takes 60 seconds. Post your job free at boothop.com and let us match you."
    "Someone flies London→Lagos every single day. Your parcel should be on that flight. boothop.com"
    "£12 to Lagos. Not £75. Post your parcel free at boothop.com and we'll find your traveller."

━━ BRAND STYLES (all other slots — rotate, never repeat same style twice in a row) ━━

  BRAND IDENTITY (tone: confident, owning the space):
    Ref: "BootHop. Your courier plug." / "The Rolls Royce of cargo." /
         "The new face of shipping." / "New household name in logistics." /
         "Different breed of shipping." / "Built different. Ships different."
    → Write a fresh 1-line brand statement that positions BootHop as THE name.

  CULTURAL FLEX (tone: swagger, community pride, word-of-mouth energy):
    Ref: "Chilling with the big names now." / "The brand everyone is talking about." /
         "BootHop understood the assignment." / "We're in our BootHop era." /
         "The diaspora's best kept secret. (Not anymore.)" / "Your mum knows now."
    → Write a fresh 1-line that gives BootHop cultural credibility and heat.

  CONFIDENCE / AUTHORITY (tone: results-first, no fluff, business assured):
    Ref: "We matched. We delivered. End of story." / "The plug your shipment needed." /
         "First class logistics from the UK." / "We run the logistics game different." /
         "Your parcel. Our mission." / "UK's favourite parcel connection."
    → Write a fresh 1-line that leads with the outcome — no hype, just results.

  POV / SCROLL-STOP (tone: relatable, discovery moment, share-worthy):
    Ref: "POV: you just found the shipping cheat code." / "POV: your parcel is already in Lagos." /
         "Before BootHop vs after BootHop." / "Tell a friend. Then tell another." /
         "The moment you realised BootHop existed."
    → Write a fresh 1-line that puts the viewer in the moment of discovering BootHop.

caption_tiktok  (max 150 chars): ONE original line in the correct style for this slot. No story. Max 1 emoji.
                                 No hashtags — keep it clean and confident.
caption_instagram (max 200 chars): Same original line, slightly expanded if it adds impact. ALWAYS end with "boothop.com".
                                   If slot 2, the booking CTA already has the URL — make it land harder.
                                   Max 2 hashtags. Nothing else.
youtube_title   (max 60 chars): The POV question from the hook. Human, no BootHop name.
youtube_description: 2 sentences max. First: the story in one line. Second: "boothop.com"
engagement      (max 10 words): One question that triggers comments. Best openers:
                               "What would you have done?" / "Would you trust a verified traveller?"
                               "Has this happened to you?" / "Tell me you've done this."
                               Never repeat the same opener two days in a row.
top_caption     (max 9 words): A conversational scene-setter shown at the very top of the
                               video screen throughout every clip — like a TikTok thought bubble.
                               It draws the viewer into the feeling BEFORE the story begins.
                               Openers: "What if", "Picture this", "Ever wondered", "POV:", or a
                               single crisis statement like "When time runs out." or "This almost didn't arrive."
                               Do NOT use "Imagine" — it signals a slow hook.
                               Do NOT mention BootHop or prices. Must feel like a real person typed it.
                               Examples:
                                 "What if your parcel beat the courier to Lagos?"
                                 "Picture this — a stranger carries your mums birthday gift."
                                 "Ever sent something home and wished it could go tonight?"
                                 "POV: you just found the cheapest way to send home."
                                 "This almost didn't make it in time."

{_get_trend_context()}
{_hook_intelligence_block()}
{_recent_hooks_block()}
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
  "top_caption": "...",
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
    (  # 3 — Thursday: Sender's long frustration solved / lighter discovery moment
        "THE SENDER — Years of Overpaying, Now Solved (or: Funny Discovery Moment)",
        "Tell this from the sender's perspective. Two options — pick the tone that fits the pillar:\n"
        "\n"
        "OPTION A — EMOTIONAL ARC (heavier pillar like family, logistics_stories):\n"
        "They've been sending things the expensive way for years — accepting it as the cost of diaspora life.\n"
        "HOOK: opens with a past moment of frustration — 'Every year at this time, the same problem.'\n"
        "PROBLEM: years of overpaying hits differently when they calculate the total they've wasted.\n"
        "RESOLUTION: BootHop doesn't just solve today's problem — it changes how they'll think about this forever.\n"
        "LESSON: they'll never go back. And they told everyone they know.\n"
        "\n"
        "OPTION B — LIGHTER / RELATABLE (works on any pillar, best for Thursday when humour travels):\n"
        "Lean into the absurdity — the ridiculous price, the unnecessary panic, the 'why did nobody tell me' moment.\n"
        "HOOK: something they actually said in the courier queue, or the look on their face when they saw the price.\n"
        "PROBLEM: the exact number they were quoted — and their actual physical reaction.\n"
        "RESOLUTION: they found BootHop, it cost a fraction, and they laughed about it for a week.\n"
        "LESSON: light, self-aware. They're part of the community now.\n"
        "Thursday content that makes someone laugh or share is more valuable than content that makes them nod.",
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

    # ── B2B Instagram pillars — always end with LOG YOUR NEEDS / LOG YOUR INTENTIONS ──
    "courier_business": (
        "B2B recruitment content targeting couriers, dispatch riders, and small logistics operators.\n"
        "Hook (POV question): 'Are you a courier? Do you know how many more shipments you could be handling?'\n"
        "Tell the story of a courier or small delivery business who joined BootHop's network.\n"
        "PROBLEM: they were operating alone — chasing clients, empty return trips, no consistent income.\n"
        "RESOLUTION: BootHop opened them to a verified pool of senders. More bookings, better earnings, no cold calls.\n"
        "LESSON: 'You move parcels. BootHop fills your schedule.'\n"
        "\n"
        "MANDATORY B2B CTA — must appear in BOTH the lesson beat AND the caption:\n"
        "Direct couriers to LOG THEIR ROUTE AND AVAILABILITY on BootHop.\n"
        "Example lesson: 'Register your courier business. Log your routes. We send the clients to you.'\n"
        "Example caption: 'Are you a courier or delivery business? Log your routes and availability at boothop.com/business — we connect you to verified senders every day.'\n"
        "The action is SPECIFIC: log routes, log vehicle type, log availability. Not just 'sign up'.\n"
        "Tone: professional, direct, B2B. No family story. This is business to business."
    ),

    "personal_shopper": (
        "Personal shopping and international forwarding content — target Nigerians and Africans who\n"
        "want items from Dubai, UK, USA that aren't available locally or are overpriced.\n"
        "Hook (POV question): 'Want something from Dubai? From London? Log your request — we shop it, clear customs, and deliver to your door.'\n"
        "Tell the story of a customer in Lagos who wanted something specific from Dubai or London.\n"
        "PROBLEM: shipping costs were high, customs were confusing, they didn't know who to trust.\n"
        "RESOLUTION: BootHop's personal shopper sourced it, handled customs duty, used a reputable courier. Delivered to their door.\n"
        "LESSON: 'You find it. Log your request. We shop it, clear it, deliver it.'\n"
        "\n"
        "MANDATORY B2B CTA — must appear in BOTH the lesson beat AND the caption:\n"
        "Direct the viewer to LOG THEIR SHOPPING REQUEST / NEEDS on BootHop.\n"
        "Example lesson: 'Log what you need. Where from. When you need it. BootHop handles the rest.'\n"
        "Example caption: 'Need something from Dubai, London, or New York delivered to Lagos? Log your request at boothop.com — we shop it, pay the customs, and deliver to your door.'\n"
        "The action is SPECIFIC: log the item, the origin city, the destination, the deadline.\n"
        "Destinations: Lagos, Abuja, Port Harcourt, Accra, Nairobi.\n"
        "Origins: Dubai, London, Manchester, New York, Toronto.\n"
        "Tone: aspirational, service-focused. Show ease and trust."
    ),

    "multi_courier": (
        "Business logistics platform content — target UK-based African SMEs, importers/exporters,\n"
        "and couriers who want more control and better options.\n"
        "Hook (POV question): 'As a business, why are you still locked into one courier?'\n"
        "\n"
        "TELL EITHER THIS STORY (alternate perspective each time):\n"
        "\n"
        "VERSION A — Business Sender:\n"
        "  PROBLEM: locked into one courier — premium rates, no alternatives when it failed, no control.\n"
        "  RESOLUTION (ACCURATE — this is exactly how BootHop works):\n"
        "    They went to BootHop. Listed what they needed to ship — item, size, destination, deadline.\n"
        "    Set a reasonable price. The system auto-matched them with multiple couriers in that price range.\n"
        "    They picked the best fit. No phone calls. No quotes. Just matched and shipped.\n"
        "  LESSON: 'Log your shipping need. Set your budget. BootHop finds your match.'\n"
        "\n"
        "VERSION B — Courier:\n"
        "  PROBLEM: courier was running empty returns, chasing clients, undercutting their own rates.\n"
        "  RESOLUTION (ACCURATE — this is exactly how BootHop works):\n"
        "    They listed on BootHop what they can carry — route, dates, vehicle, item types accepted.\n"
        "    Set their price. The system auto-matched them with senders in that price range.\n"
        "    Bookings came in. No cold calls. No empty runs.\n"
        "  LESSON: 'List what you carry. Set your price. BootHop sends the right senders to you.'\n"
        "\n"
        "MANDATORY B2B CTA — must appear in BOTH the lesson beat AND the caption:\n"
        "Direct businesses AND couriers to LOG THEIR NEEDS / LIST THEIR CAPACITY on BootHop.\n"
        "Example caption (sender): 'Running a business? Log your shipment needs at boothop.com/business — set your price and let the system match you to the right courier. No calls needed.'\n"
        "Example caption (courier): 'Are you a courier with spare capacity? List your route and price at boothop.com/business — BootHop auto-matches you with senders in your range.'\n"
        "The action is SPECIFIC: list the items, set the price, let the system match. Not just 'sign up'.\n"
        "Tone: confident, empowering, business-smart. The viewer should feel fully in control."
    ),

    # ── Faith & Prayer pillars (Friday / Sunday rotation) ─────────────────────
    "faith_friday": (
        "Faith-infused brand content for the Nigerian and African Christian diaspora in the UK and USA.\n"
        "Runs on Fridays and Sundays as part of a weekly alternating rotation.\n"
        "\n"
        "TONE: Warm, spiritual, uplifting. Community prayer energy. Not preachy — celebratory.\n"
        "\n"
        "CONTENT OPTIONS — pick one per run, rotate across these formats:\n"
        "\n"
        "FORMAT A — PRAYER LINE + BRAND:\n"
        "  Hook: A short, sincere prayer line relevant to the diaspora — travel mercies, family connections,\n"
        "        provision, answered prayers, safe arrivals.\n"
        "  Bridge: Connect the prayer to BootHop in one line. The link must feel natural, not forced.\n"
        "  Example hook: 'May everything you sent ahead of you arrive before you do.'\n"
        "  Example bridge: 'BootHop makes sure it does. 📦'\n"
        "  Example hook: 'This Friday, may your connections be strong — in faith and in delivery.'\n"
        "  Example hook: 'God puts the right people in the right place. BootHop connects them.'\n"
        "\n"
        "FORMAT B — CHRISTIAN TRENDING SONG REFERENCE:\n"
        "  Reference a trending Nigerian or US gospel song. Do not quote lyrics (copyright) — reference the\n"
        "  SPIRIT or TITLE only.\n"
        "  Nigerian gospel artists to reference: Sinach (Way Maker), Mercy Chinwo, Nathaniel Bassey,\n"
        "  Tim Godfrey, Dunsin Oyekan, Tope Alabi, Frank Edwards, Prospa Ochimana.\n"
        "  US gospel artists: Maverick City Music, Kirk Franklin, Elevation Worship, Tasha Cobbs Leonard.\n"
        "  Example: 'Way Maker energy this Friday. Things are moving. Your parcel is on its way. 📦'\n"
        "  Example: 'Nathaniel Bassey said hallelujah. We said your parcel landed. Same energy. BootHop.'\n"
        "\n"
        "FORMAT C — FRIDAY / SUNDAY BLESSING:\n"
        "  A short diaspora-relevant blessing that ends with a BootHop brand line.\n"
        "  Example: 'This weekend, may what you sent reach who needs it most. BootHop. 📦'\n"
        "  Example: 'Sunday blessings from the UK to Lagos. Your love always arrives. BootHop.'\n"
        "\n"
        "BEAT RULES for faith_friday:\n"
        "  HOOK:       max 12 words. A prayer line, blessing, or faith statement.\n"
        "  PROBLEM:    Skip traditional problem beat — use a TRANSITION instead.\n"
        "              max 10 words. Connect faith/prayer to real logistics need.\n"
        "              Example: 'But prayer alone can't carry a parcel across the ocean.'\n"
        "  STAKES:     max 8 words. What's at stake emotionally — not commercially.\n"
        "  RESOLUTION: max 10 words. BootHop is the answer — the physical arm of the blessing.\n"
        "  LESSON:     max 10 words. A warm brand line. End with BootHop.\n"
        "\n"
        "Caption style: warm, faith-community energy. Can use 🙏 or 📦 emoji.\n"
        "  TikTok example: 'Travel mercies for your parcel too. BootHop. 🙏📦'\n"
        "  Instagram example: 'Friday blessings to every parcel in transit. boothop.com 🙏 #BootHop #FaithFriday'\n"
        "Tone: inclusive — spiritual but not exclusive. Speaks to anyone who prays."
    ),

    # ── Weekend Celebration pillar (Saturday rotation) ─────────────────────────
    "celebration_weekend": (
        "Weekend celebration content — joyful, high-energy, culturally rich.\n"
        "Runs on Saturdays in alternating weeks.\n"
        "\n"
        "TONE: Upbeat, celebratory, Afrobeats energy. People dancing. People celebrating together.\n"
        "\n"
        "VISUAL DIRECTION — tell the scene director to source:\n"
        "  Free stock videos of: people dancing in a hall, Nigerian party, wedding reception,\n"
        "  Afrobeats dance, graduation celebration, African church celebration, people clapping.\n"
        "  Pexels/Pixabay search terms: 'people dancing celebration', 'african wedding hall',\n"
        "  'graduation party', 'afrobeats dance', 'nigerian celebration', 'hall party'.\n"
        "\n"
        "IMPORTANT: The celebration is NOT always about a physical parcel.\n"
        "BootHop creates value in two ways — choose either angle per run:\n"
        "\n"
        "ANGLE A — THE PARCEL THAT MADE THE MOMENT:\n"
        "  Something sent through BootHop arrived just in time for the celebration.\n"
        "  The gift, the outfit, the certificate — it made the moment possible.\n"
        "  Hook example: 'Would the aso-ebi arrive before the wedding started?'\n"
        "  Hook example: 'The party was tonight. The parcel was still in Leeds.'\n"
        "  Lesson: 'Every celebration deserves a BootHop moment.'\n"
        "\n"
        "ANGLE B — THE MONEY THAT MADE THE MOMENT:\n"
        "  Someone is celebrating because of MONEY EARNED through BootHop.\n"
        "  A traveller who made £150–£300 carrying parcels on a flight they were already taking.\n"
        "  A courier whose schedule filled up through BootHop — extra income every week.\n"
        "  A sender who saved £80 vs another service — and spent that saving on the celebration itself.\n"
        "  Hook example: 'Would you celebrate £200 made on a flight you were already on?'\n"
        "  Hook example: 'She flew to Lagos anyway. BootHop paid for the party.'\n"
        "  Hook example: 'He carried two parcels. Made £180. The weekend sorted itself.'\n"
        "  Lesson: 'You were already going. BootHop just made it pay.'\n"
        "  OR: 'BootHop earnings. Real money. Real celebrations.'\n"
        "\n"
        "OCCASION OPTIONS (rotate across both angles):\n"
        "  - Nigerian wedding in Birmingham — aso-ebi arrived OR traveller paid for the aso-ebi with BootHop earnings\n"
        "  - Naming ceremony in Manchester — gift reached the family OR courier earned enough for the gift\n"
        "  - Graduation in Leeds — certificate sent from Lagos OR the grad made money delivering for BootHop\n"
        "  - Church harvest in London — donations sent to Abuja branch via BootHop\n"
        "  - Birthday party in Peckham — birthday dress from Lagos OR savings used on the party\n"
        "  - New Year party — last-minute delivery OR extra BootHop income made the night possible\n"
        "\n"
        "Caption: upbeat, celebratory, emoji-friendly.\n"
        "  TikTok example (parcel): 'The party was waiting. BootHop delivered. Weekend sorted. 🎉📦'\n"
        "  TikTok example (money): 'She carried two parcels on her flight. Came back £200 richer. 🎉 BootHop.'\n"
        "  Instagram example: 'Every celebration has a BootHop story behind it. boothop.com 🎉 #BootHop #WeekendVibes'\n"
        "Tone: joyful, high energy. This is the feel-good post of the week."
    ),

    # ── Flight Discovery — wildcard pillar, fires randomly ~once per 10 days ──
    "flight_discovery": (
        "════════════════════════════════════════\n"
        "FLIGHT DISCOVERY PILLAR — READ BEFORE WRITING\n"
        "════════════════════════════════════════\n"
        "\n"
        "WHAT BOOTHOP IS: A peer-to-peer parcel delivery platform. Travellers carry parcels for senders.\n"
        "WHAT BOOTHOP IS NOT: A flight booking site. It does NOT sell or book flights.\n"
        "\n"
        "THE FLIGHT TICKER: BootHop.com has a scrolling price ticker showing live cheap flight\n"
        "prices to Nigeria and other destinations — powered by an affiliate partner. It is a\n"
        "DISCOVERY TOOL only. People see the price, then click through to book elsewhere.\n"
        "The story is about DISCOVERY — not about BootHop booking the flight.\n"
        "\n"
        "THE EMOTIONAL HOOK IS THE PRICE GAP. This is what stops the scroll:\n"
        "  Someone is desperate to get home. Everywhere they look: £600, £700, £800.\n"
        "  Then they're on BootHop (for parcels), notice the ticker, see £189.\n"
        "  That gap — £680 down to £189 — is the story. Build everything around it.\n"
        "\n"
        "OVERRIDE THE STANDARD NARRATIVE FORMULA FOR THIS PILLAR.\n"
        "Use this structure instead:\n"
        "\n"
        "  HOOK (max 12 words): Open with the PRICE GAP or the emotional desperation — not the solution.\n"
        "    RIGHT: 'Six weeks in the UK. Every flight home: £680. Her first pay cheque hadn't arrived.'\n"
        "    RIGHT: 'He'd checked 11 sites. Cheapest to Lagos: £743. Then he opened BootHop.'\n"
        "    WRONG: 'She checked BootHop to send a parcel. She ended up booking a £189 flight.' (gives away everything)\n"
        "    WRONG: Starting with BootHop's name in the first sentence.\n"
        "    The hook must create tension. Do NOT resolve it. Let the story do that.\n"
        "\n"
        "  PROBLEM (2 sentences max): The person is stuck. Flights are too expensive. They're about\n"
        "    to give up, delay the trip, or miss something important. Use a specific price from the\n"
        "    pool below and a specific reason the trip matters (mum's health, job start, wedding, baby).\n"
        "\n"
        "  STAKES (1–2 sentences): What they will miss if they don't find a cheaper fare. Specific.\n"
        "    WRONG: 'Start date looming. Budget already gone.' (meaningless fragments)\n"
        "    RIGHT: 'Her mum's procedure was on Friday. The only quote she'd found was £810. She had £300.'\n"
        "\n"
        "  RESOLUTION (2 sentences): They were already on BootHop — checking parcel rates, or a friend\n"
        "    sent the link. They noticed the flight ticker. They saw the price. The gap hit them.\n"
        "    Include the UNEXPECTED MOMENT: e.g. they almost didn't scroll down. Or they compared it three\n"
        "    times because they didn't believe it. Or they sent the screenshot to five people immediately.\n"
        "\n"
        "  LESSON (max 10 words, MANDATORY FORMAT): Must reinforce what BootHop actually is.\n"
        "    USE ONE OF THESE:\n"
        "      'BootHop. Parcels AND flights. One place.'\n"
        "      'Deliveries. Cheap flights. One site. Most people don't know.'\n"
        "      'The flight ticker is the secret most BootHop users never find.'\n"
        "    BANNED: any lesson that says BootHop 'finds flights', 'books flights', or 'is a flight site'.\n"
        "\n"
        "CHARACTER (pick one — give them a name and a UK city):\n"
        "  Tola, nurse, Manchester | Emeka, developer, London | Amara, care worker, Nottingham\n"
        "  James, market trader, Peckham | Sade, recent graduate, Liverpool | Bisi, NHS worker, Bristol\n"
        "  Funmi, pharmacy student, Birmingham | Daniel, business owner, East London\n"
        "\n"
        "PRICE & DESTINATION POOL:\n"
        "  What they'd been quoted elsewhere: £680, £743, £810 ('everywhere else', 'another site')\n"
        "  What the ticker showed: £189 to Lagos, £210 to Abuja, £175 to Port Harcourt\n"
        "  Never name a competitor. Never name an airline.\n"
        "\n"
        "CAPTION — curiosity-driving, insider energy, 3–4 sentences, strong CTA:\n"
        "  TikTok tone: 'Most people find BootHop through parcels. Then they see the flight ticker and everything changes. Check it. boothop.com 🛫'\n"
        "  Instagram tone: 'The flight ticker is the part of BootHop nobody talks about. One click — and the price gap will surprise you. boothop.com 🛫'\n"
        "  Write something original in that spirit. Never copy these exactly.\n"
        "\n"
        "TIKTOK HASHTAGS: must include exactly 20, mix of flight + diaspora + delivery tags.\n"
        "  Always include: #BootHop #CheapFlightsToNigeria #UKToNigeria #DiasporaTravel\n"
        "  Add from: #CheapFlights #FlightDeals #LagosFlights #NaijaUK #AfricaTravel\n"
        "  #BudgetTravel #TravelHack #FlightComparison #NigeriaTravel #AfricanDiaspora\n"
        "  #LondonToLagos #DiasporaLife #UKNigeria #AbroadLife #FamilyAbroad #TravelTips"
    ),

    # ── Saturday — Humans of BootHop (Format 5, documentary style, does not sell) ─
    "humans_of_boothop": "__DYNAMIC__",  # prompt built by _build_humans_of_boothop_prompt()

    # ── Sunday — Founder Story (Format 6, first-person, fictionalized, does not sell) ─
    "founder_story": "__DYNAMIC__",     # prompt built by _build_founder_story_prompt()
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
    # UK / Western names — BootHop also serves diverse UK residents
    ("Sarah",   "project manager",          "Manchester",   "sender"),
    ("James",   "civil engineer",           "Leeds",        "traveller"),
    ("Emma",    "community midwife",        "Birmingham",   "sender"),
    ("Michael", "IT analyst",               "Nottingham",   "traveller"),
    ("Chloe",   "solicitor",                "London",       "sender"),
    ("Daniel",  "secondary school teacher", "Bristol",      "traveller"),
    ("Grace",   "social worker",            "Liverpool",    "sender"),
    ("Ryan",    "warehouse supervisor",     "Leicester",    "traveller"),
    ("Diane",   "NHS physiotherapist",      "Sheffield",    "sender"),
    ("Jordan",  "software engineer",        "Cambridge",    "traveller"),
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
    ("visa application documents",      "needed at the embassy in Lagos within 72 hours"),
    ("a wedding dress",                 "sewn in Manchester, the ceremony was on Saturday"),
    ("a jollof rice spice kit",         "her mother had been asking for it since Christmas"),
    ("graduation photographs",          "printed in London, needed for the family ceremony album"),
    ("prescription heart medication",   "her grandmother was running low and couldn't get the same formula locally"),
    ("a university scholarship letter", "original document required for enrolment on Monday"),
    ("an interview outfit",             "bought at Marks and Spencer, the interview was on Thursday"),
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
    "The courier said {days} days. She had three.",
    "His visa interview was tomorrow. A reputable courier quoted {days} business days.",
    "The ceremony was Saturday. The item was still in Birmingham on Wednesday night.",
    "She found out 48 hours before. Every courier she called was either fully booked or too slow.",
    "He almost left it behind entirely — the flight was in four hours when he remembered.",
    "The sender had been quoted £{price} before. She had accepted it as the cost of caring from a distance.",
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


# ── Humans of BootHop — Saturday documentary format data seed ─────────────────
# Each tuple: (name, context/action, human_detail_that_isn't_logistics)
_HUMANS_OF_BOOTHOP = [
    ("Sade",  "sent a wedding dress to Lagos with three days to spare",
              "her mum cried when she opened the door and saw the dress inside"),
    ("Tunde", "carried a parcel on a flight he'd already booked to see his family",
              "he earned £190 without changing a single one of his plans"),
    ("Grace", "needed her son's inhaler delivered the same day",
              "the traveller waited by the gate to hand it over in person — not just to a doorstep"),
    ("Emeka", "was flying home for his sister's celebration and had space in his case",
              "he was matched with someone sending aso-oke fabric within 20 minutes of posting"),
    ("Amara", "sent her grandmother's heart medication when the pharmacy ran out locally",
              "her grandmother sent back a voice note just saying thank you — nothing else"),
    ("James", "needed his graduation gown delivered before the ceremony started",
              "the traveller was already at the airport and detoured to drop it at the venue"),
    ("Funmi", "sent her son's football boots before a trial he almost missed",
              "he made the trial, and the boots arrived with an hour to spare"),
    ("Dami",  "sent her father's chieftaincy outfit from Birmingham to Lagos",
              "her father wore it the same day it arrived — he didn't tell anyone it had nearly not made it"),
    ("Kola",  "was flying home and took a parcel for a stranger he'd never met",
              "the stranger turned out to live two streets away from his family in Ibadan"),
    ("Yemi",  "sent her daughter's university acceptance letter by hand",
              "her daughter called from the registrar's office in tears — she'd been accepted, the letter confirmed it"),
]


# ── Founder Story — Sunday first-person format data seed ─────────────────────
# FICTIONALIZED/COMPOSITE founder stories for Sunday content.
# These are NOT the founder's real biography. They are believable, human-scale
# composite scenarios written to feel authentic. Keep them specific and small-scale.
# Each tuple: (the_moment, the_realisation, the_decision)
_FOUNDER_MOMENTS = [
    ("I once paid £70 to send a phone charger to Lagos.",
     "Meanwhile someone I knew was flying that exact route with an empty suitcase.",
     "So I built the thing I wished had existed already."),
    ("A family friend missed her own sister's traditional wedding because a parcel took nine days to clear.",
     "Everyone on that flight had spare luggage space. Nobody had a way to connect it to her.",
     "I realised the movement already existed — it just had no structure around it."),
    ("Someone once asked in a family WhatsApp group, 'is anyone travelling to Lagos this week?' — and got seven replies.",
     "That's when it hit me: people already trust strangers with their parcels every day, informally.",
     "I just gave that trust a platform, a price, and a guarantee."),
    ("I had no idea if anyone would actually agree to carry something for a stranger.",
     "Turns out people already did — they just needed somewhere safer to do it than a group chat.",
     "That doubt is gone now. It happens every day."),
    ("I watched my cousin refresh a courier tracking page for four days straight.",
     "The parcel was sitting in a sorting centre twenty miles from the airport. Someone was flying that route that morning.",
     "I kept thinking: there has to be a better way than this."),
    ("Someone once told me the real competition wasn't DHL. It was a WhatsApp message: 'Is anyone going to Lagos?'",
     "They were right. The informal network already existed. It just had no safety, no price, no guarantee.",
     "BootHop is what that WhatsApp message looks like with a platform built around it."),
]


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


def _build_humans_of_boothop_prompt() -> str:
    """Build a Humans of BootHop (Format 5 — Saturday) prompt. Does NOT sell."""
    name, context, human_detail = random.choice(_HUMANS_OF_BOOTHOP)
    return f"""You write a single "Humans of BootHop" video — a weekly documentary-style piece that builds brand recognition, not sales.

BootHop = peer-to-peer parcel delivery. Travellers ALREADY flying between UK and Nigeria carry parcels for senders.
LANGUAGE RULE: British English only.

TODAY'S STORY SEED:
  Name: {name}
  What they did: {name} {context}
  Human detail (the beat that makes people share): {human_detail}

FORMAT 5 — HUMANS OF BOOTHOP (does NOT sell — no prices, no CTAs, no "sign up today"):

This format breaks every rule the other formats follow, deliberately.
It is not trying to convert. Its job is brand memory — the one video each week that feels like a mini-documentary.

FIXED STRUCTURE (follow exactly):
  HOOK (0-3s)     → NAME CARD. Real name + one-line context. No BootHop branding yet. No music swell. Just the fact.
                    Write it like a caption on a photograph: "{name}. [brief specific action in 5-7 words]."
                    Max 10 words total.
  PROBLEM (3-10s) → THEIR VOICE. Paraphrased first-person — must sound like something a real person said, not marketing.
                    Express doubt, surprise, or quiet emotion — NOT urgency. Max 18 words.
  STAKES (10-20s) → WHAT HAPPENED. The match, the handover, the outcome. Told plainly.
                    No countdown language. No "urgent." This already happened — tell it to a friend. Max 22 words.
  RESOLUTION      → THE HUMAN DETAIL. One moment with nothing to do with logistics.
                    Use this seed: "{human_detail}"
                    This is the beat that makes people share or screenshot. It must feel earned. Max 20 words.
  LESSON          → SERIES STAMP. Write EXACTLY: "Humans of BootHop." — no variation, no additions, no CTA.

RULES:
- NEVER include a price, a stat, or a call to action anywhere in any beat
- NEVER use the words "urgent," "courier," or "delivery" in the HOOK, PROBLEM, or STAKES
- BootHop appears naturally in STAKES — it connected them — but is NOT the subject of the story
- The LESSON field must contain exactly: "Humans of BootHop."

CAPTIONS:
- caption_tiktok: warm, quietly confident. No hashtags. No price. Feel: "Every delivery carries a story. This one's {name}'s." Max 120 chars.
- caption_instagram: same line, slightly expanded. End with "boothop.com". Max 180 chars.
- youtube_title: episode title format — "{name}. [2-3 word summary]." Max 60 chars.
- youtube_description: one sentence, no sell. "A story about {name}, a traveller, and the moment in between. boothop.com"
- top_caption: quiet, cinematic. Max 8 words. No "Imagine." No prices. Feel: "Some deliveries carry more than a parcel."
- engagement: return "" — this format does NOT end with a question.

Return ONLY valid JSON (no markdown):
{{
  "story_anchor": {{
    "character": "{name}",
    "item": "{context}",
    "moment": "the human moment at the heart of this story",
    "obstacle": "",
    "movement": "how BootHop connected them"
  }},
  "hook": "...",
  "problem": "...",
  "stakes": "...",
  "resolution": "...",
  "lesson": "Humans of BootHop.",
  "top_caption": "...",
  "caption_tiktok": "...",
  "caption_instagram": "...",
  "youtube_title": "...",
  "youtube_description": "...",
  "engagement": ""
}}"""


def _build_founder_story_prompt() -> str:
    """Build a Founder Story (Format 6 — Sunday) prompt. First-person, fictionalized, no sell."""
    moment, realisation, decision = random.choice(_FOUNDER_MOMENTS)
    return f"""You write a single "Founder Story" video — a weekly first-person piece from BootHop's founder that builds trust through honesty, not sales.

BootHop = peer-to-peer parcel delivery. Travellers ALREADY flying between UK and Nigeria carry parcels for senders.
LANGUAGE RULE: British English only.

TODAY'S FOUNDER MEMORY (composite/fictionalized — treat as true for storytelling purposes):
  The moment: "{moment}"
  The realisation: "{realisation}"
  The decision: "{decision}"

FORMAT 6 — FOUNDER STORY (does NOT sell — no CTAs, no "sign up," no pitch-deck language):

FIXED STRUCTURE (follow exactly):
  HOOK (0-3s)     → THE MOMENT. A single specific memory. Must be a concrete moment, not a mission statement.
                    NEVER open with "I believe..." or "I started BootHop because I'm passionate about..."
                    Use the seed moment as your foundation. First person. Vivid. Max 15 words.
  PROBLEM (3-12s) → THE REALISATION. What that moment made obvious.
                    This is where "unlocking unused human movement" lives — the founder noticing the
                    movement already existed, it just had no structure around it. Max 22 words.
  STAKES (12-20s) → THE DECISION. Plain, undramatic. No "hustle story" language.
                    One honest admission of doubt if possible — this is what separates founder content from a pitch.
                    Use the seed decision. Max 20 words.
  RESOLUTION      → WHERE IT IS NOW. One grounded, human-scale, current fact.
                    Not hype. Not metrics. A directional truth: "Now people use it every single day for exactly what I built it for." Max 15 words.
  LESSON          → CLOSING LINE. Reflective — never a CTA.
                    Options: "This is why BootHop exists." / "That's the whole idea, really." /
                    "The movement already existed. I just gave it a home." — pick the one that fits the memory.

RULES:
- NEVER use: "disrupt," "scale," "solve a massive problem," "market opportunity," "passionate about"
- Keep it personal-scale. One memory → one realisation → one decision. That is the whole video.
- No CTA, no question ending, no "sign up" — this format earns trust by NOT selling
- BootHop is the thing the founder built, not the subject of a pitch

CAPTIONS:
- caption_tiktok: reflective, no sell. "The reason I built BootHop was simpler than you'd think." Feel. Max 120 chars.
- caption_instagram: same, slightly expanded. End with "boothop.com". Max 180 chars.
- youtube_title: "Why I built BootHop." or a variation using the memory as the hook. Max 60 chars.
- youtube_description: one sentence. "The moment that started BootHop. boothop.com"
- top_caption: quiet and cinematic. Max 8 words. No "Imagine." Feel: "This is why it exists."
- engagement: return "" — this format does NOT end with a question.

Return ONLY valid JSON (no markdown):
{{
  "story_anchor": {{
    "character": "BootHop founder",
    "item": "the moment that started it all",
    "moment": "founding realisation",
    "obstacle": "the gap that needed a platform",
    "movement": "human movement that already existed"
  }},
  "hook": "...",
  "problem": "...",
  "stakes": "...",
  "resolution": "...",
  "lesson": "...",
  "top_caption": "...",
  "caption_tiktok": "...",
  "caption_instagram": "...",
  "youtube_title": "...",
  "youtube_description": "...",
  "engagement": ""
}}"""


class ContentDuplicateError(Exception):
    """Raised when a generated hook is too similar to content posted in the last 14 days."""


_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "of",
    "in", "on", "at", "for", "with", "and", "or", "but", "your", "you",
    "his", "her", "their", "its", "our", "my", "this", "that", "if", "what",
    "would", "could", "should", "do", "did", "have", "has", "had", "not",
    "just", "still", "as", "by", "from", "how", "when", "where", "who",
    "which", "while", "s", "t",
}


def _check_hook_duplicate(hook: str, days: int = 14):
    """
    Hard gate: raise ContentDuplicateError if the hook is too similar to any
    hook already in memory.json from the last N days.
    Called after Stage 2 (QA) so we abort before expensive image/video stages.

    Thresholds:
      Yesterday/today : ≥ 30% significant-word overlap → reject  (strict)
      2-14 days ago   : ≥ 65% significant-word overlap → reject  (normal)
    """
    try:
        mem_file = DATA / "memory.json"
        if not mem_file.exists():
            return
        mem = json.loads(mem_file.read_text(encoding="utf-8"))
    except Exception:
        return

    cutoff    = (date.today() - timedelta(days=days)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    hook_lower = hook.lower().strip()
    hook_start = " ".join(hook_lower.split()[:5])
    new_sig    = {w.strip(".,?!\"'") for w in hook_lower.split()} - _STOP_WORDS

    if not new_sig:
        return

    for entry in mem:
        entry_date = entry.get("date", "")
        if entry_date < cutoff:
            continue
        old = entry.get("hook", "").strip()
        if not old:
            continue
        old_lower = old.lower()

        # Exact match — always reject
        if old_lower == hook_lower:
            raise ContentDuplicateError(
                f"Exact hook reuse from {entry_date}: \"{old[:80]}\""
            )

        # Same opening 5 words — always reject (catches "Would you trust a stranger…")
        old_start = " ".join(old_lower.split()[:5])
        if hook_start == old_start:
            raise ContentDuplicateError(
                f"Hook opener repeated from {entry_date}: \"{hook_start}…\""
            )

        # Word-overlap threshold — stricter for yesterday/today
        old_sig = {w.strip(".,?!\"'") for w in old_lower.split()} - _STOP_WORDS
        if old_sig:
            overlap   = len(new_sig & old_sig) / min(len(new_sig), len(old_sig))
            threshold = 0.30 if entry_date >= yesterday else 0.65
            if overlap >= threshold:
                raise ContentDuplicateError(
                    f"Hook {int(overlap*100)}% similar to {'yesterday' if entry_date >= yesterday else entry_date} entry "
                    f"(threshold {'30' if entry_date >= yesterday else '65'}%): \"{old[:80]}\""
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

    # ── Stage 0: News Editor — skipped for documentary/founder formats ─────────
    news_context = None
    if pillar not in ("humans_of_boothop", "founder_story"):
        print("  [NewsEditor] Searching for today's top story...")
        try:
            news_context = find_top_story(pillar)
        except Exception as _ne:
            print(f"  [NewsEditor] Failed: {_ne} — continuing without news context")

    # ── Stage 1: Story Writer ─────────────────────────────────────────────────
    if pillar == "humans_of_boothop":
        print("  [StoryWriter] Format 5 — Humans of BootHop")
        story_prompt = _build_humans_of_boothop_prompt()
    elif pillar == "founder_story":
        print("  [StoryWriter] Format 6 — Founder Story")
        story_prompt = _build_founder_story_prompt()
    else:
        story_prompt = _build_story_prompt(
            slot, pillar, bucket, pillar_label, pillar_angle, day_name, month_name,
            news_context=news_context,
        )
    raw = _call_story_ai(story_prompt, v2=False)
    data = _parse_json(raw)

    # ── Stage 2: QA Director — review and improve the story ──────────────────
    data = review_and_improve(data, pillar)

    # ── 14-day duplicate gate — abort before expensive stages run ─────────────
    _check_hook_duplicate(data.get("hook", ""), days=14)
    print(f"  [DupCheck] Hook cleared 14-day window: {data.get('hook','')[:70]}")

    # ── Stage 3: Scene Planner ────────────────────────────────────────────────
    scene_queries = plan_scenes(data, pillar)

    # ── Stage 4: Photographer — upgrade queries + generate image prompts ──────
    from datetime import date as _d
    _day_idx = _d.today().toordinal()
    photo_result = generate_image_prompts(data, scene_queries, pillar, day_index=_day_idx)
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

    # Metadata — set BEFORE saving to memory so pillar/slot/date are recorded
    data["pillar"] = pillar
    data["slot"]   = slot
    data["date"]   = today

    tags_311 = _fetch_trending_tags(pillar=pillar)
    data["hashtags_tiktok"]    = _tiktok_hashtags(pillar, tags_311)
    data["hashtags_instagram"] = _instagram_hashtags(pillar, tags_311)
    data["hashtags_311"]       = tags_311
    data["youtube_tags"]       = _youtube_tags(pillar, data.get("hook", ""))
    data["youtube_category"]   = YOUTUBE_CATEGORIES.get(pillar, 22)

    # ── Memory DB — save the complete content package ─────────────────────────
    memory_db.save_entry(data, slot, version="v1")

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
    "When time matters more than distance, BootHop finds another way."
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
    from datetime import date as _date
    import hashlib as _hashlib
    today = _date.today()

    # ── Wildcard injection — fires ~1 in 10 days, date-deterministic (no true random)
    # Same date always gives same result so Oracle and laptop agree.
    try:
        from config import WILDCARD_PILLARS as _wildcards
        if _wildcards:
            _date_key = f"{today.isoformat()}-slot{slot}"
            _h = int(_hashlib.md5(_date_key.encode()).hexdigest(), 16)
            if _h % 10 == 0:          # ~10% of slot runs → roughly once per 10 days per slot
                return _wildcards[_h % len(_wildcards)]
    except Exception:
        pass

    val = SLOT_PILLARS[slot]
    if isinstance(val, list):
        day_val = val[today.weekday()]  # 0=Mon … 6=Sun
        # If the day entry is itself a list, alternate by ISO week number
        # e.g. ["urgent_medical", "faith_friday"] → week 1 = urgent_medical, week 2 = faith_friday
        if isinstance(day_val, list):
            # Use weekly performance data to pick the better-performing option
            _wf = DATA / "pillar_weights.json"
            if _wf.exists():
                try:
                    _weights = json.loads(_wf.read_text(encoding="utf-8"))
                    best = max(day_val, key=lambda p: _weights.get(p, 0.5))
                    print(f"  [Pillar] Weights used — picked '{best}' from {day_val}")
                    return best
                except Exception:
                    pass
            # Fallback: alternate by ISO week number
            week_num = today.isocalendar()[1]
            return day_val[week_num % len(day_val)]
        return day_val
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
