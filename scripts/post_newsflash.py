"""
OTB_Pipeline — Flight News Flash (daily 06:30)

Selects Deal of Day from live flight data, generates dual-audience content
(sender + traveller), validates framing, renders video, posts to platform.

Platform routing by weekday:
  Monday           → LinkedIn  (B2B — "earn on your trip" angle)
  Tue / Thu / Sat  → TikTok
  Wed / Fri / Sun  → Instagram Reel

Framing contract (hard-wired, validated on output):
  1. Flight price = PROOF OF MOVEMENT, never the offer
  2. Dual landing: sender CTA + traveller CTA in every post
  3. NEVER "book now" / "grab this deal" / "don't miss this fare" as primary CTA
  4. Movement pivot phrase required: "already flying / going / booked / making the journey"

Data files:
  data/flight_deals.json   — deal list (populated here via Perplexity, or by website)
  data/newsflash_log.json  — post history, route repeat controls, rotation state
"""

import json, re, sys, time, random
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    ANTHROPIC_API_KEY, PERPLEXITY_KEY, DATA, OUTPUT, TEMP,
    CREDS_PATH,
)

import requests

# ── Constants ─────────────────────────────────────────────────────────────────

_LOG_PATH   = DATA / "newsflash_log.json"
_DEALS_PATH = DATA / "flight_deals.json"

# Corridor priority score (higher = preferred Deal of Day)
_CORRIDOR_PRIORITY = {
    ("LHR", "LOS"): 10,  # London Heathrow → Lagos (Murtala)
    ("LGW", "LOS"): 9,
    ("MAN", "LOS"): 9,   # Manchester → Lagos
    ("LHR", "ABV"): 8,   # London → Abuja
    ("MAN", "ABV"): 7,
    ("LHR", "PHC"): 7,   # London → Port Harcourt
    ("LGW", "ABV"): 6,
    ("LHR", "ACC"): 5,   # London → Accra (diaspora adjacent)
}

# Human-readable route labels
_ROUTE_LABELS = {
    ("LHR", "LOS"): "London to Lagos",
    ("LGW", "LOS"): "London Gatwick to Lagos",
    ("MAN", "LOS"): "Manchester to Lagos",
    ("LHR", "ABV"): "London to Abuja",
    ("MAN", "ABV"): "Manchester to Abuja",
    ("LHR", "PHC"): "London to Port Harcourt",
    ("LGW", "ABV"): "London Gatwick to Abuja",
    ("LHR", "ACC"): "London to Accra",
}

# Earn estimate per corridor (realistic BootHop traveller earnings)
_CORRIDOR_EARN = {
    ("LHR", "LOS"): "up to £85",
    ("LGW", "LOS"): "up to £80",
    ("MAN", "LOS"): "up to £75",
    ("LHR", "ABV"): "up to £80",
    ("MAN", "ABV"): "up to £70",
    ("LHR", "PHC"): "up to £75",
    ("LGW", "ABV"): "up to £70",
    ("LHR", "ACC"): "up to £65",
}

# Curated fallback deals when Perplexity and the JSON are both unavailable
_FALLBACK_DEALS = [
    {"route": "London → Lagos",      "origin": "LHR", "destination": "LOS", "price_gbp": 338, "airline": "British Airways"},
    {"route": "Manchester → Lagos",  "origin": "MAN", "destination": "LOS", "price_gbp": 312, "airline": "Air France"},
    {"route": "London → Abuja",      "origin": "LHR", "destination": "ABV", "price_gbp": 355, "airline": "Ethiopian Airlines"},
    {"route": "London → Lagos",      "origin": "LGW", "destination": "LOS", "price_gbp": 289, "airline": "Turkish Airlines"},
    {"route": "London → Port Harcourt", "origin": "LHR", "destination": "PHC", "price_gbp": 379, "airline": "Kenya Airways"},
]

# Framing validation patterns
_BOOKING_PATTERNS = [
    r"\bbook now\b", r"\bgrab this deal\b", r"\bdon'?t miss this fare\b",
    r"\bbook your (flight|ticket|seat)\b", r"\bbuy (a |your )?ticket\b",
    r"\bthis (flight )?deal\b", r"\bbook (it|this|today)\b",
    r"\bfares? (from|starting)\b(?!.*already)",  # "fare from £X" without movement pivot
]
_MOVEMENT_PIVOTS = [
    "already flying", "already going", "already booked",
    "already making the journey", "already on their way",
    "journey already", "flight already", "someone was already",
    "someone is already", "that's someone already",
]

# Rotating story lines (human moment lines used as STORY beat)
_STORY_LINES = [
    "Her mum hadn't seen her in two years. She sent something real instead.",
    "He found out a colleague was flying home that weekend. The laptop went with her.",
    "The package left Birmingham on a Tuesday. It arrived in Lagos on Wednesday.",
    "She didn't book a courier. She found someone already booked.",
    "His daughter's birthday was on Saturday. Someone was flying Thursday.",
    "She was already packed. The parcel just needed a seat.",
    "The journey existed before the parcel did. BootHop connected the two.",
    "He earned on a trip he was already making. Empty bag space, full wallet.",
    "A nurse flying home for Christmas. A stranger's stethoscope went with her.",
    "A student going back for his sister's graduation. A gift went too.",
]

# Brand closing lines — lesson MUST use one of these exactly
_CLOSING_LINES = [
    "The flight was already going. The parcel just needed a seat.",
    "Movement already exists. BootHop makes it useful.",
    "Someone was already flying. BootHop connected the dots.",
    "The journey already existed. The parcel just joined it.",
    "Every journey has value.",
]

# Engagement questions rotation
_ENGAGEMENT_QUESTIONS = [
    "Flying to Nigeria soon? You could earn carrying a parcel. Drop ✈️ below.",
    "What would you send if someone was already making that journey?",
    "Have you ever sent something home through a traveller? How did it go?",
    "Are you flying UK → Nigeria soon? Your bag space could earn. Comment below.",
    "Tag someone who's always sending packages home.",
]

# Platform routing by weekday (Mon=0 ... Sun=6)
_PLATFORM_BY_DAY = {
    0: "linkedin",    # Monday
    1: "tiktok",      # Tuesday
    2: "instagram",   # Wednesday
    3: "tiktok",      # Thursday
    4: "instagram",   # Friday
    5: "tiktok",      # Saturday
    6: "instagram",   # Sunday
}

_NEWSFLASH_SLOT = 5  # synthetic slot number for logging — won't clash with slots 1-4


# ── Logging helpers ───────────────────────────────────────────────────────────

def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [NewsFlash] {msg}")


def _load_log() -> dict:
    try:
        if _LOG_PATH.exists():
            return json.loads(_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "route_history": {},
        "next_story_index": 0,
        "next_closing_index": 0,
        "next_engagement_index": 0,
        "posts": [],
    }


def _save_log(log: dict):
    _LOG_PATH.parent.mkdir(exist_ok=True)
    _LOG_PATH.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Flight data ───────────────────────────────────────────────────────────────

def _load_deals() -> list[dict]:
    """Load deals from data/flight_deals.json if fresh (<24h). Else return []."""
    try:
        if _DEALS_PATH.exists():
            deals = json.loads(_DEALS_PATH.read_text(encoding="utf-8"))
            if isinstance(deals, list) and deals:
                fetched = deals[0].get("fetched_at", "")
                if fetched:
                    age = datetime.utcnow() - datetime.fromisoformat(fetched.replace("Z", ""))
                    if age.total_seconds() < 86400:
                        _log(f"Loaded {len(deals)} deals from cache ({age.seconds//3600}h old)")
                        return deals
    except Exception as e:
        _log(f"Deal cache read failed: {e}")
    return []


def _fetch_deals_perplexity() -> list[dict]:
    """Query Perplexity for current cheap UK→Nigeria flight deals."""
    if not PERPLEXITY_KEY:
        _log("No Perplexity key — using fallback deals")
        return []

    today_str = date.today().strftime("%B %d, %Y")
    prompt = f"""Search for the cheapest available flights from UK airports to Nigerian airports for the week of {today_str}.
Focus on London Heathrow, London Gatwick, and Manchester departures to Lagos, Abuja, and Port Harcourt.

Return ONLY a valid JSON array of up to 6 deals. Use this exact format:
[
  {{"route": "London → Lagos", "origin": "LHR", "destination": "LOS", "price_gbp": 338, "airline": "British Airways", "valid_until": "2026-07-12"}}
]

Rules:
- price_gbp must be a number (integer), not a string
- origin and destination must be 3-letter IATA codes
- If you cannot confirm real prices, return an empty array []
- Return ONLY the JSON array, no other text"""

    try:
        _log("Fetching flight deals from Perplexity...")
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"},
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            _log("No JSON array in Perplexity response")
            return []
        deals = json.loads(m.group())
        if not isinstance(deals, list):
            return []
        now_str = datetime.utcnow().isoformat() + "Z"
        for d in deals:
            d["fetched_at"] = now_str
        # Cache for next run
        _DEALS_PATH.parent.mkdir(exist_ok=True)
        _DEALS_PATH.write_text(json.dumps(deals, indent=2, ensure_ascii=False), encoding="utf-8")
        _log(f"Perplexity returned {len(deals)} deals — cached to {_DEALS_PATH.name}")
        return deals
    except Exception as e:
        _log(f"Perplexity fetch failed: {e}")
        return []


def _get_deals() -> list[dict]:
    """Load from cache → Perplexity → fallback (in that order)."""
    deals = _load_deals()
    if not deals:
        deals = _fetch_deals_perplexity()
    if not deals:
        _log("Using static fallback deals")
        now_str = datetime.utcnow().isoformat() + "Z"
        deals = [{**d, "fetched_at": now_str} for d in _FALLBACK_DEALS]
    return deals


# ── Deal scoring + selection ──────────────────────────────────────────────────

def _score_deal(deal: dict, route_history: dict) -> int:
    route_key = (deal.get("origin", ""), deal.get("destination", ""))
    route_id  = f"{route_key[0]}-{route_key[1]}"

    # Skip if same route posted within 7 days
    last_str = route_history.get(route_id)
    if last_str:
        try:
            last_date = date.fromisoformat(last_str)
            if (date.today() - last_date).days < 7:
                return -999
        except Exception:
            pass

    score = _CORRIDOR_PRIORITY.get(route_key, 3)

    # Freshness bonus
    fetched = deal.get("fetched_at", "")
    if fetched:
        try:
            age_h = (datetime.utcnow() - datetime.fromisoformat(fetched.replace("Z", ""))).total_seconds() / 3600
            if age_h < 6:   score += 5
            elif age_h < 12: score += 3
            elif age_h < 24: score += 1
        except Exception:
            pass

    # Price attractiveness (lower = better)
    price = deal.get("price_gbp", 999)
    if price < 300:   score += 5
    elif price < 380: score += 3
    elif price < 450: score += 1

    return score


def _select_deal(deals: list[dict], route_history: dict) -> dict | None:
    scored = [(d, _score_deal(d, route_history)) for d in deals]
    scored = [(d, s) for d, s in scored if s > -999]
    if not scored:
        # All routes recently posted — force the best corridor anyway
        _log("All routes recently posted — overriding repeat control for today")
        scored = [(d, _score_deal({**d, "fetched_at": ""}, {})) for d in deals]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored else None


# ── Content generation ────────────────────────────────────────────────────────

def _next_rotation(log: dict, key: str, bank: list) -> tuple[str, dict]:
    idx = log.get(key, 0) % len(bank)
    log[key] = idx + 1
    return bank[idx], log


def _build_content_prompt(deal: dict, platform: str, story_line: str,
                           closing_line: str, engagement_q: str) -> str:
    route_key = (deal.get("origin", ""), deal.get("destination", ""))
    route_label = _ROUTE_LABELS.get(route_key, deal.get("route", "UK to Nigeria"))
    earn_est   = _CORRIDOR_EARN.get(route_key, "up to £80")
    price      = deal.get("price_gbp", "")
    airline    = deal.get("airline", "a major airline")
    price_str  = f"£{price}" if price else "under £400"

    return f"""You write a Flight News Flash post for BootHop — a peer-to-peer delivery app.

ABOUT BOOTHOP: Travellers already flying between UK and Nigeria carry parcels for senders and earn money. BootHop connects them. The traveller was going ANYWAY.

TODAY'S FLIGHT DEAL:
  Route:    {route_label}
  Price:    {price_str} per person (return)
  Airline:  {airline}
  Earn est: Travellers carrying a parcel on this route earn {earn_est}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FRAMING CONTRACT — NON-NEGOTIABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. The flight price is PROOF THAT MOVEMENT EXISTS — it is NOT the offer.
   Every post MUST include one of these phrases (or a natural variant):
   "someone is already flying", "that's someone already going",
   "someone was already making that journey", "someone is already booked on that route"

2. DUAL AUDIENCE LANDING — every post must contain BOTH:
   - SENDER line: something like "your parcel could go with them" / "send something home"
   - TRAVELLER line: "earn {earn_est} carrying a parcel" (use the earn figure above)

3. NEVER use these phrases as the primary CTA: "book now", "grab this deal",
   "don't miss this fare", "book your flight", "buy a ticket", "flight deal"
   The CTA is always about BootHop (send / earn) — not about booking the flight.

4. LANGUAGE: British English only — no Yoruba, Pidgin, or any other language.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5-BEAT VIDEO SCRIPT (on-screen text — KEEP SHORT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use the flight deal as proof of movement. Use this story line as the human moment:
"{story_line}"

HOOK (max 15 words): The flight price as proof — {price_str} shows someone is already going.
  Start with the route and price, then pivot immediately to movement.
  GOOD: "{price_str} {route_label}. That's someone already making the journey."
  BAD:  "Cheap flights to Nigeria this week — grab this deal!"

PROBLEM (max 12 words): What senders usually face — courier cost, wait time, or uncertainty.
  Do NOT introduce the flight again here — focus on the sender's frustration.

STAKES (max 10 words): Why it matters — the item, the person, the deadline.
  Use the story line above as inspiration for a specific human moment.

RESOLUTION (max 12 words): BootHop connected them. The traveller was already going.
  Must include the movement pivot and BOTH the sender outcome + traveller earn figure.

LESSON (max 10 words): Use EXACTLY this closing line:
  "{closing_line}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLATFORM CAPTIONS (longer — go in caption, not on screen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
caption_tiktok (max 300 chars):
  Line 1: price + route + movement pivot (first 90 chars — visible before "more")
  Lines 2-3: sender benefit + traveller earn figure
  End with: {engagement_q}

caption_instagram (max 400 chars):
  First 125 chars: price + route + human moment (visible before "more")
  Body: sender story (2 sentences) + traveller earn line
  Include "someone was already making that journey"
  End with: {engagement_q}

caption_linkedin (max 600 chars, formal B2B tone):
  Open with the earn figure — appeal to the professional traveller
  Frame BootHop as smart logistics: "monetise empty bag space"
  Include: sender saving (vs courier cost) + traveller earn figure
  Close with a professional question — no emojis, no slang
  End with: {engagement_q}

Return ONLY valid JSON (no markdown):
{{
  "hook": "...",
  "problem": "...",
  "stakes": "...",
  "resolution": "...",
  "lesson": "...",
  "caption_tiktok": "...",
  "caption_instagram": "...",
  "caption_linkedin": "...",
  "engagement": "..."
}}"""


def _call_ai(prompt: str) -> str:
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
        timeout=40,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in response: {raw[:200]}")
    return json.loads(m.group())


# ── Framing validation ────────────────────────────────────────────────────────

def _validate_framing(content: dict) -> tuple[bool, list[str]]:
    """
    Returns (is_valid, list_of_violations).
    Fails if booking-CTA language appears in any field without a movement pivot.
    """
    all_text = " ".join(str(v) for v in content.values() if isinstance(v, str)).lower()
    violations = []

    has_movement = any(p in all_text for p in _MOVEMENT_PIVOTS)
    has_booking  = any(re.search(p, all_text) for p in _BOOKING_PATTERNS)

    if has_booking and not has_movement:
        violations.append("Booking-CTA language detected without movement pivot phrase")

    if not has_movement:
        violations.append("Missing movement pivot phrase — required in every newsflash post")

    # Check dual audience
    has_sender_cta   = any(p in all_text for p in ["send with", "parcel could go", "send something", "send a parcel"])
    has_traveller_cta = any(p in all_text for p in ["earn", "carrying a parcel", "bag space"])
    if not has_sender_cta:
        violations.append("Missing sender CTA (send with them / parcel could go with them)")
    if not has_traveller_cta:
        violations.append("Missing traveller CTA (earn / carrying a parcel)")

    return len(violations) == 0, violations


def _generate_content(deal: dict, platform: str, log: dict) -> tuple[dict, dict]:
    """Generate content with framing validation. Up to 2 attempts."""
    story_line,   log = _next_rotation(log, "next_story_index",    _STORY_LINES)
    closing_line, log = _next_rotation(log, "next_closing_index",   _CLOSING_LINES)
    engagement_q, log = _next_rotation(log, "next_engagement_index", _ENGAGEMENT_QUESTIONS)

    for attempt in range(1, 3):
        try:
            prompt = _build_content_prompt(deal, platform, story_line, closing_line, engagement_q)
            raw    = _call_ai(prompt)
            result = _parse_json(raw)

            is_valid, violations = _validate_framing(result)
            if is_valid:
                _log(f"Content passed framing validation (attempt {attempt})")
                result["story_line"]   = story_line
                result["closing_line"] = closing_line
                result["pillar"]       = "airport"   # reuse airport pillar for render colours
                result["hashtags_tiktok"] = (
                    "#BootHop #LondonToLagos #DiasporaDelivery #NigeriaUK #TravelAndEarn "
                    "#PeerDelivery #UKNigeria #FlightNews #LagosLife #DiasporaLife "
                    "#SendHome #NigeriaUKDiaspora #TravelHacks #EarnWhileYouTravel #BootHopApp"
                )
                result["hashtags_instagram"] = result["hashtags_tiktok"]
                return result, log
            else:
                _log(f"Framing violation (attempt {attempt}): {violations}")
        except Exception as e:
            _log(f"Content generation failed (attempt {attempt}): {e}")

    # Fallback: build minimal safe content manually
    _log("Using minimal fallback content after 2 failed attempts")
    route_key  = (deal.get("origin", ""), deal.get("destination", ""))
    route_lbl  = _ROUTE_LABELS.get(route_key, deal.get("route", "UK to Nigeria"))
    earn_est   = _CORRIDOR_EARN.get(route_key, "up to £80")
    price_str  = f"£{deal.get('price_gbp', '')}" if deal.get('price_gbp') else ""
    content = {
        "hook":       f"{price_str} {route_lbl}. Someone is already making this journey.",
        "problem":    "A reputable courier would cost £55 and take a week.",
        "stakes":     "The parcel needed to arrive before the weekend.",
        "resolution": f"BootHop found a traveller already going. {earn_est} earned.",
        "lesson":     closing_line,
        "caption_tiktok":   f"{price_str} {route_lbl} — that's someone already flying this route. Your parcel could go with them. Travellers earn {earn_est} carrying a parcel. {engagement_q}",
        "caption_instagram": f"{price_str} {route_lbl}. Someone is already making that journey. Your parcel could go with them via BootHop. Travellers earn {earn_est} on a trip they were already taking. {engagement_q}",
        "caption_linkedin":  f"Travellers flying {route_lbl} this week could earn {earn_est} carrying a parcel on BootHop — monetising bag space on a journey they were already making. Senders pay a fraction of courier cost. {engagement_q}",
        "engagement":    engagement_q,
        "story_line":    story_line,
        "closing_line":  closing_line,
        "pillar":        "airport",
        "hashtags_tiktok":    "#BootHop #LondonToLagos #DiasporaDelivery #NigeriaUK #TravelAndEarn",
        "hashtags_instagram": "#BootHop #LondonToLagos #DiasporaDelivery #NigeriaUK #TravelAndEarn",
    }
    return content, log


# ── Video render ──────────────────────────────────────────────────────────────

def _render(content: dict, deal: dict) -> Path | None:
    try:
        from render_video import render_video
    except ImportError:
        _log("render_video not available")
        return None

    route_key = (deal.get("origin", ""), deal.get("destination", ""))
    route_lbl = _ROUTE_LABELS.get(route_key, deal.get("route", "UK-Nigeria")).replace(" ", "-").lower()

    # Build visual queries: airport scenes for this corridor
    content["visual_queries"] = [
        f"airport departure gate passengers boarding",
        f"London Heathrow airport terminal crowded",
        f"traveller packing bag suitcase home",
        f"Lagos Murtala Mohammed airport arrivals",
        f"parcel wrapped gift delivery handoff",
        f"airport runway plane taking off",
        f"family reunion greeting airport arrivals emotional",
        f"smartphone app booking sending parcel",
    ]

    out_path = OUTPUT / f"newsflash_{route_lbl}_{date.today().isoformat()}.mp4"
    out_path.parent.mkdir(exist_ok=True)

    _log("Rendering newsflash video...")
    success, _ = render_video(content, _NEWSFLASH_SLOT, str(out_path))
    if success and out_path.exists() and out_path.stat().st_size > 100_000:
        _log(f"Render complete: {out_path.name} ({out_path.stat().st_size // 1024}KB)")
        return out_path
    _log("Render failed or output too small")
    return None


# ── Posting ───────────────────────────────────────────────────────────────────

def _post(platform: str, video_path: Path, content: dict) -> bool:
    try:
        if platform == "tiktok":
            from post_tiktok import post_video
            result = post_video(str(video_path), content, slot=_NEWSFLASH_SLOT)
            return bool(result)

        elif platform == "instagram":
            from post_instagram import post_video
            result = post_video(str(video_path), content, slot=_NEWSFLASH_SLOT)
            return bool(result)

        elif platform == "linkedin":
            # LinkedIn caption uses the B2B-focused linkedin caption
            content["caption"] = content.get("caption_linkedin", content.get("caption_instagram", ""))
            from post_linkedin import post_video
            result = post_video(str(video_path), content, slot=_NEWSFLASH_SLOT)
            return bool(result)

        else:
            _log(f"Unknown platform: {platform}")
            return False

    except Exception as e:
        _log(f"Post to {platform} failed: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    _log("=== Flight News Flash starting ===")
    today = date.today()
    platform = _PLATFORM_BY_DAY[today.weekday()]
    _log(f"Today is {today.strftime('%A')} — posting to {platform}")

    log = _load_log()

    # 1. Get deals
    deals = _get_deals()
    if not deals:
        _log("No deals available — aborting")
        return

    # 2. Select Deal of Day
    deal = _select_deal(deals, log.get("route_history", {}))
    if not deal:
        _log("No eligible deal after repeat controls — aborting")
        return

    route_key = (deal.get("origin", ""), deal.get("destination", ""))
    _log(f"Deal of Day: {deal.get('route')} @ £{deal.get('price_gbp')} ({deal.get('airline')})")

    # 3. Generate content
    content, log = _generate_content(deal, platform, log)
    _log(f"Hook: {content.get('hook', '')[:80]}")
    _log(f"Lesson: {content.get('lesson', '')}")

    # 4. Render video
    video_path = _render(content, deal)
    if not video_path:
        _log("Render failed — cannot post without video")
        _save_log(log)
        return

    # 5. Post
    success = _post(platform, video_path, content)
    status  = "posted" if success else "failed"
    _log(f"Post to {platform}: {status}")

    # 6. Update route history + log
    route_id = f"{route_key[0]}-{route_key[1]}"
    if success:
        log.setdefault("route_history", {})[route_id] = today.isoformat()

    log.setdefault("posts", []).append({
        "date":      today.isoformat(),
        "platform":  platform,
        "route":     deal.get("route"),
        "price_gbp": deal.get("price_gbp"),
        "airline":   deal.get("airline"),
        "hook":      content.get("hook", ""),
        "status":    status,
    })
    _save_log(log)
    _log(f"=== News Flash complete ({status}) ===")


if __name__ == "__main__":
    run()
