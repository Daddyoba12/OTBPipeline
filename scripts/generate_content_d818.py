"""
D818 Catering — AI content generator
Generates a viral 5-beat video script for D818's catering brand (weddings, parties,
anniversaries — UK). Returns a content dict fully compatible with render_video.py,
in the same shape as generate_content.generate_content(slot, pillar, bucket) and
g_inspired_content.generate_content().

Self-contained on purpose: BootHop's scripts/generate_content.py bans food/dining/
restaurant terms from its visual-query safety filter (irrelevant to parcel delivery),
which would break a catering brand's content. D818 needs its own generator rather
than reusing BootHop's engine or its filters.
"""

import json, random, re, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY
import requests

CLIENT_PROFILE = Path(__file__).parent.parent / "client_profiles" / "d818.json"


def _load_profile() -> dict:
    try:
        return json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Claude call (same shape as generate_content._call_claude) ─────────────────

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


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in response: {raw[:200]}")
    return json.loads(m.group())


# ── Pillar / bucket rotation ────────────────────────────────────────────────────
# D818's own content pillars (from client_profiles/d818.json), cycled deterministically
# across slots and days so the daily slots never repeat the same pillar back to back.
# Kept in sync with client_profiles/d818.json — used only if that file is unreadable.

_FALLBACK_PILLARS = [
    "Jollof rice & party rice showcases",
    "Suya & grilled specialties",
    "Small chops & party finger food",
    "Traditional soups (egusi, efo riro, ogbono) for events",
    "Puff-puff & West African desserts",
    "Behind-the-scenes West African event prep",
]


def get_pillar_for_slot(slot: int) -> str:
    profile = _load_profile()
    pillars = profile.get("content_pillars") or _FALLBACK_PILLARS
    idx = (date.today().toordinal() + slot) % len(pillars)
    return pillars[idx]


def get_bucket() -> str:
    return ["weekday", "weekday", "weekday", "weekday", "weekday",
            "weekend", "weekend"][date.today().weekday()]


# ── Visual query bank (Pexels/Pixabay-friendly, West African cuisine domain) ───
# food_origin_rule (client_profiles/d818.json): every dish shown must be West
# African cuisine — jollof, suya, egusi, efo riro, ogbono, puff-puff, plantain,
# small chops, pounded yam. Never generic/European dishes. Naming the actual
# dish also naturally avoids tripping the generic-food-ban query guard, since
# these are specific terms rather than the word "food"/"dining" etc.

_PILLAR_QUERY_HINTS = {
    "Jollof rice & party rice showcases": [
        "jollof rice party platter", "party jollof rice closeup",
        "jollof rice serving dish", "Nigerian jollof rice plate",
    ],
    "Suya & grilled specialties": [
        "suya skewers grilling", "grilled suya closeup",
        "suya spice meat skewer", "African grilled meat platter",
    ],
    "Small chops & party finger food": [
        "small chops platter", "party finger food African",
        "spring rolls samosa platter", "small chops closeup tray",
    ],
    "Traditional soups (egusi, efo riro, ogbono) for events": [
        "egusi soup closeup", "efo riro soup pot",
        "ogbono soup pounded yam", "West African soup bowl",
    ],
    "Puff-puff & West African desserts": [
        "puff puff dessert plate", "puff puff closeup fried",
        "West African dessert platter", "fried dough dessert African",
    ],
    "Behind-the-scenes West African event prep": [
        "chef preparing jollof rice", "catering staff West African event",
        "kitchen prep African cuisine", "chef garnishing African dish",
    ],
}

_NEUTRAL_QUERIES = [
    "jollof rice party platter", "suya skewers grilling",
    "puff puff dessert plate", "party jollof rice closeup",
    "African party food spread", "West African wedding buffet table",
]

# Process/ingredient close-ups — variety alongside finished-dish photography.
# Mixed in occasionally for every pillar, more heavily for the behind-the-scenes
# pillar. Same sourcing path as any other beat (Pexels/Pixabay -> DALL-E/user-clips
# fallback), subject to the same query guard.
_PROCESS_QUERIES = [
    "jollof rice being stirred pot",
    "suya being seasoned spice rub",
    "peppers tomatoes jollof sauce",
    "plantain being fried closeup",
    "egusi seeds being ground",
    "puff puff dough being fried",
]


def _visual_queries_for_pillar(pillar: str) -> list[str]:
    hints = _PILLAR_QUERY_HINTS.get(pillar, [])
    pool  = list(dict.fromkeys(hints + _NEUTRAL_QUERIES))  # dedupe, preserve order

    # Sometimes mix in process/ingredient shots for variety — weighted higher for
    # the behind-the-scenes pillar, occasional elsewhere.
    is_bts    = pillar == "Behind-the-scenes West African event prep"
    n_process = random.randint(2, 4) if is_bts else (random.randint(1, 2) if random.random() < 0.4 else 0)
    if n_process:
        pool = list(dict.fromkeys(pool + random.sample(_PROCESS_QUERIES, min(n_process, len(_PROCESS_QUERIES)))))

    random.shuffle(pool)
    queries = pool[:8]
    while len(queries) < 8:
        queries.append(random.choice(_NEUTRAL_QUERIES))
    return queries


# ── Weighted primary CTA/brand-line pick ────────────────────────────────────────
# The user wants brand_lines[0]/cta_phrases[0] (the "African plug in Nottingham"
# line) to be the recognizable recurring hook, not just one of several equally-
# likely options. Weighted primary pick: item 0 most of the time, occasional
# variation from the rest.

def _weighted_primary(items: list[str], primary_weight: float = 0.7) -> str:
    if not items:
        return ""
    if len(items) == 1 or random.random() < primary_weight:
        return items[0]
    return random.choice(items[1:])


# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_prompt(pillar: str, profile: dict) -> str:
    brand      = profile.get("brand_name", "D818 Catering")
    niche      = profile.get("niche", "authentic West African restaurant and catering across the UK")
    location   = profile.get("area_covered", "UK-wide")
    tone       = profile.get("content_tone", "elegant")
    voice      = profile.get("brand_voice", "Warm, sophisticated, celebratory, proudly West African.")
    lines      = profile.get("brand_lines") or [
        "D818 — your African plug in Nottingham. Visit our website, call us, or email your order and we'll get it to you."
    ]
    brand_line = _weighted_primary(lines)
    website    = profile.get("website", "https://d818.co.uk").replace("https://", "").replace("www.", "")
    food_rule  = profile.get("food_origin_rule",
        "Every dish shown or described must be West African cuisine (Nigerian, Ghanaian, "
        "or wider West African) — jollof rice, suya, egusi, efo riro, ogbono, puff-puff, "
        "plantain, small chops, pounded yam. Never generic/European/other-cuisine dishes.")
    visual_kw  = profile.get("visual_keywords",
        "jollof rice, suya, plantain, egusi soup, efo riro, ogbono soup, party rice, "
        "small chops, puff puff, pounded yam")

    return f"""You write viral short-form video scripts for {brand} — a {niche}, covering {location}.
Brand voice: {voice}
Tone: {tone}
Website: {website}

TODAY'S CONTENT PILLAR: {pillar}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD CONSTRAINT — CUISINE (non-negotiable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{food_rule}
Every dish you name, describe, or write a visual query for must be one of these or a
close West African relative: {visual_kw}.
Do NOT invent or reference generic/European/other-cuisine dishes (no pasta, no roast
dinners, no generic "fine dining" plates) — always name the actual West African dish.

RECURRING BRAND HOOK (use often, in spirit or verbatim in the resolution/lesson beats
or captions — this is D818's recognizable recurring line):
"{brand_line}"
The CTA is always: visit the website, call, or email — in that order. Never say
"DM us" or "link in bio" — this brand's contact channels are website / phone / email.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NARRATIVE FORMULA — follow exactly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. HOOK       A scroll-stopping line about a specific West African dish, celebration,
              or the pillar's theme.
2. PROBLEM    The struggle of planning a wedding/party/anniversary — bland catering,
              stressful logistics, food that doesn't match the occasion or the culture.
3. STAKES     Why the food matters — it's what guests remember, what makes or breaks the event.
4. RESOLUTION {brand} — authentic West African menus, flawless execution, food guests talk about.
5. LESSON     One warm, confident closing line in the brand voice.

BEAT RULES (these appear as on-screen text — SHORT):
  hook:       max 12 words. Sensory or emotional pull — imagine, picture, ever noticed.
              Name a specific dish where natural (e.g. "that jollof rice aroma").
  problem:    max 12 words. Specific event-catering frustration.
  stakes:     max 10 words. What's at stake if the food falls flat.
  resolution: max 12 words. {brand}. Authentic West African. Flawless. Done.
  lesson:     max 10 words. One warm brand line — elegant and confident.

top_caption: max 9 words. Conversational scene-setter for top of screen.
             Start with: Imagine, What if, Picture this, Ever wondered.
             Do NOT mention the brand name. Feel like a real person typing.

VISUAL QUERIES — 8 Pexels/Pixabay search terms, West African dish/event domain ONLY.
Short queries (2-5 words), no years, no camera-shot jargon (no "wide shot" etc).
Name the actual dish. Mix finished-dish shots with a couple of process/ingredient
close-ups for variety (e.g. "suya being seasoned", "jollof rice being stirred pot",
"plantain being fried") — not every query needs to be a plated final dish.
Examples: "jollof rice party platter", "suya skewers grilling",
"puff puff dessert plate", "egusi soup closeup", "West African wedding buffet table".

caption_tiktok    (max 150 chars): Warm, elegant brand-statement energy, proudly West
                  African. Max 1 emoji. No hashtags. No "DM us"/"link in bio".
caption_instagram (max 200 chars): Same energy, slightly expanded. End with a website/
                  call/email CTA and {website}. No "DM us"/"link in bio".

Return ONLY valid JSON:
{{
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
  "engagement": "..."
}}"""


# ── Hashtags ─────────────────────────────────────────────────────────────────

def _build_hashtags(profile: dict) -> tuple[str, str]:
    tags = profile.get("hashtags") or ["#D818Catering", "#UKCatering", "#WeddingCatering"]
    chosen = tags[:8]
    tag_str = " ".join(chosen)
    return tag_str, tag_str


# ── Main public API ───────────────────────────────────────────────────────────

def generate_content(slot: int, pillar: str, bucket: str = "") -> dict:
    """
    Generate a full content dict for one D818 slot.
    Same output contract as generate_content.generate_content(slot, pillar, bucket).
    """
    profile = _load_profile()
    if not profile:
        raise RuntimeError("client_profiles/d818.json missing or unreadable — cannot generate D818 content.")

    print(f"  [D818] Slot {slot} | Pillar: {pillar}")

    raw  = _call_claude(_build_prompt(pillar, profile))
    data = _parse_json(raw)

    # Normalise fields render_video.py expects
    data["pillar"]  = pillar
    data["slot"]    = slot
    data["date"]    = date.today().isoformat()
    data["client"]  = "d818"
    data["top_caption"] = data.get("top_caption", "")

    # Visual queries — prefer Claude's, backfill/override with the catering query bank
    # so every slot has 8 solid, on-domain Pexels/Pixabay terms even if Claude under-delivers.
    claude_queries = [q for q in data.get("visual_queries", []) if isinstance(q, str) and q.strip()]
    bank_queries   = _visual_queries_for_pillar(pillar)
    queries = (claude_queries + bank_queries)[:8]
    while len(queries) < 8:
        queries.append(random.choice(_NEUTRAL_QUERIES))
    data["visual_queries"] = queries

    hashtags_tiktok, hashtags_instagram = _build_hashtags(profile)
    data["hashtags_tiktok"]    = data.get("hashtags_tiktok", hashtags_tiktok) or hashtags_tiktok
    data["hashtags_instagram"] = data.get("hashtags_instagram", hashtags_instagram) or hashtags_instagram

    return data


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="D818 content generator (manual test)")
    p.add_argument("--slot", type=int, default=1)
    args = p.parse_args()

    pillar  = get_pillar_for_slot(args.slot)
    content = generate_content(args.slot, pillar, get_bucket())
    print(f"\nPillar     : {pillar}")
    print(f"Hook       : {content.get('hook')}")
    print(f"Problem    : {content.get('problem')}")
    print(f"Stakes     : {content.get('stakes')}")
    print(f"Resolution : {content.get('resolution')}")
    print(f"Lesson     : {content.get('lesson')}")
    print(f"Top caption: {content.get('top_caption')}")
    print(f"TikTok cap : {content.get('caption_tiktok')}")
    print(f"Queries    : {content.get('visual_queries')}")
