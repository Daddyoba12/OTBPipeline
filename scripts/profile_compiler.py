"""
AI profile compiler — turns a company's onboarding data into the "creative"
fields a client_profiles/<slug>.json needs, in one AI call made ONCE at
provisioning time (not per-post). Part of the dynamic client provisioning
work — see .claude/plans/fluttering-singing-perlis.md Phase 2.

Does NOT touch any of the 4 existing clients' files or logic. New code only.
"""

import json, re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from ai_providers import call_structured

# Mirrors render_video.py's _BANNED_FETCH_TERMS exactly (kept as a local copy,
# not an import, to avoid pulling in render_video.py's heavy ffmpeg/PIL
# dependencies just for one constant — this module may run inside a web
# request). If render_video.py's list changes, update this one to match.
_BANNED_FETCH_TERMS = {
    "animal","animals","dog","dogs","cat","cats","horse","horses","pet","pets",
    "puppy","puppies","kitten","kittens","bird","birds","lion","tiger","elephant",
    "monkey","fish","rabbit","wildlife","farm","zoo","livestock","parrot",
    "sheep","cow","cows","goat","goats","duck","chicken","pig","hamster","turtle",
    "snake","insect","cattle","bull","deer","donkey","camel","rooster","hen",
    "calf","lamb","oxen","mule","pony","mare","stallion","swine","fowl",
    "plantation","plantations","farmland","farmhouse","barn","pasture","grazing",
    "countryside","rural","orchard","crops","harvest","field","meadow","savanna",
    "ranch","stable","kennel","pen","paddock","corral","silo","trough",
    "food","food delivery","uber eats","ubereats","deliveroo","just eat","doordash",
    "grubhub","restaurant","takeaway","takeout","pizza delivery","meal delivery",
    "grocery delivery","grocery","meal","cooking","chef","kitchen","cafe","diner",
    "burger","bakery","supermarket","fast food","dining","breakfast",
    "christmas","xmas","santa","reindeer","baubles","nativity","tinsel","advent",
    "carol","festive","halloween","pumpkin","easter","thanksgiving","fireworks",
    "new year party","valentine","bonfire",
    "handshake","trophy","medal","piggy bank","cartoon","illustration",
}

_SAFE_DEFAULT_PALETTE = {"bg": "1A1A1A", "title": "FFD700", "body": "FFFFFF"}

_HEX_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


def _build_prompt(company: dict) -> str:
    banned_list = ", ".join(sorted(_BANNED_FETCH_TERMS))
    return f"""You are compiling a content-creation profile for a new client of a short-form
video marketing pipeline. You will be shown their business details and must
return ONLY a JSON object with specific creative fields — no prose, no
markdown, just the JSON object.

BUSINESS DETAILS
Name: {company.get('name', '')}
Industry/type: {company.get('business_type', '')}
Bio (their own words): {company.get('business_bio', '')}
Location: {company.get('location', '')}
Area covered: {company.get('area_covered', '')}
Target audience: {company.get('target_audience', '')}
Content tone (chosen by client): {company.get('content_tone', '')}
Brand voice notes: {company.get('brand_voice', '')}
Visual keywords (chosen by client): {company.get('visual_keywords', '')}
Platforms: {', '.join(company.get('platforms_enabled') or [])}

REFERENCE EXAMPLE — an existing client in a similarly specific niche (a West
African catering business), showing the shape and quality level expected.
Do NOT copy this content — it is only to show you the FORMAT and DEPTH:
{{
  "content_pillars": ["Jollof rice & party rice showcases", "Suya & grilled specialties", "Small chops & party finger food", "Traditional soups for events", "West African desserts", "Behind-the-scenes event prep"],
  "brand_lines": ["Your celebration. Our kitchen. West African excellence.", "Nottingham's African plug for every party."],
  "cta_phrases": ["Order your jollof today — website, phone, or email.", "Craving West African? D818 delivers."],
  "hashtags": ["#Jollof", "#WestAfricanFood", "#NottinghamFood", "#AfricanCatering"],
  "end_card_palettes": [{{"bg": "1A1310", "title": "D4AF37", "body": "F5E9DA"}}],
  "hard_constraints": ["Every dish shown or described must be West African cuisine — never show or describe generic/European/other-cuisine dishes."],
  "visual_terms_allowlist": ["food", "restaurant", "cooking", "chef", "kitchen", "chicken", "goat", "fish", "cow", "cattle", "lamb"],
  "visual_query_qualifiers": ["West African", "jollof", "suya", "catering"],
  "visual_query_fallback_bank": ["jollof rice party platter close up", "suya skewers grilling wide shot", "small chops party platter closeup", "egusi soup pot closeup", "West African wedding buffet table", "catering staff serving jollof rice event", "puff puff dessert plate closeup", "party jollof rice table decor"]
}}

FIELD RULES

- content_pillars: 5 to 8 recurring content angles/themes for this specific
  business. Specific to their actual niche, not generic marketing speak.
- brand_lines: 4 to 6 short recurring brand taglines, in the client's tone.
- cta_phrases: 4 to 6 short calls-to-action, natural for this business.
- hashtags: 8 to 12 hashtags, each starting with #, relevant to the niche and
  location.
- end_card_palettes: 3 to 4 colour sets, each with "bg"/"title"/"body" as
  6-character hex strings (no # prefix), fitting the brand's mood/industry.
- hard_constraints: 0 to 3 plain-English rules content must always follow for
  this specific business (e.g. a halal butcher might require "never show pork
  products"; many businesses need none — an empty list is fine and correct).
- visual_terms_allowlist: THIS IS THE MOST IMPORTANT FIELD TO GET RIGHT. Stock
  photo searches for this client are blocked from using a fixed list of
  banned words (listed below) unless specifically allowed. You must choose
  ONLY from the exact words in that banned list — copy them verbatim, do not
  invent new words — which ones are actually PART OF this business's normal,
  everyday visual content and should be unblocked. Most businesses need very
  few or zero of these unblocked. Only unblock a word if this business
  would routinely and appropriately show it (e.g. a pet groomer needs "dog"/
  "cat"/"pet" unblocked; a logistics company needs none of them). If you are
  unsure, leave it blocked — an empty list is a safe and often correct answer.
  The full banned list to choose from: {banned_list}
- visual_query_qualifiers: 3 to 6 words that, when combined with an allowlisted
  term, make it a safe and on-brand stock-photo search (e.g. pairing "chicken"
  with "West African" keeps the search food-focused, not live-animal-focused).
  Only needed if visual_terms_allowlist is non-empty.
- visual_query_fallback_bank: EXACTLY 8 short visual search phrases (3-6 words
  each) used as a last-resort fallback when live stock-photo search fails for
  this slot. Should span a mix of generic brand/location shots and specific
  niche visuals, in a sensible rough story order (opening hook, problem,
  resolution, closing) but this is a loose fallback bank, not a strict script.

Return ONLY the JSON object with these 9 keys: content_pillars, brand_lines,
cta_phrases, hashtags, end_card_palettes, hard_constraints,
visual_terms_allowlist, visual_query_qualifiers, visual_query_fallback_bank."""


def _validate_palette(p: dict) -> dict:
    if not isinstance(p, dict):
        return dict(_SAFE_DEFAULT_PALETTE)
    out = {}
    for key in ("bg", "title", "body"):
        val = str(p.get(key, "")).lstrip("#")
        out[key] = val if _HEX_RE.match(val) else _SAFE_DEFAULT_PALETTE[key]
    return out


def _clamp_list(items, min_n: int, max_n: int, pad_with=None) -> list:
    items = [i for i in (items or []) if i]
    if len(items) > max_n:
        items = items[:max_n]
    if pad_with is not None:
        while len(items) < min_n:
            items.append(pad_with[len(items) % len(pad_with)])
    return items


def _validate(raw: dict) -> dict:
    """Deterministic, no-AI post-validation. Never trust the model's output
    shape directly — this is what actually enforces the safety/size rules."""
    allowed_terms = set(raw.get("visual_terms_allowlist") or [])
    # Hard floor: the AI can only unblock words that are ACTUALLY in the
    # banned list — anything else it hallucinated is silently dropped, not
    # trusted. This is the real enforcement of "exceptions only, never a
    # replacement list" from the plan.
    safe_allowlist = sorted(allowed_terms & _BANNED_FETCH_TERMS)

    hashtags = [h if h.startswith("#") else f"#{h}" for h in (raw.get("hashtags") or [])]

    palettes = [_validate_palette(p) for p in (raw.get("end_card_palettes") or [])]
    if not palettes:
        palettes = [dict(_SAFE_DEFAULT_PALETTE)]
    palettes = palettes[:4]

    fallback_bank = _clamp_list(
        raw.get("visual_query_fallback_bank"), 8, 8,
        pad_with=["brand lifestyle shot wide angle"],
    )

    return {
        "content_pillars": _clamp_list(raw.get("content_pillars"), 5, 8,
                                        pad_with=["Behind the scenes"]),
        "brand_lines": _clamp_list(raw.get("brand_lines"), 4, 6,
                                    pad_with=[raw.get("brand_name", "")] if raw.get("brand_name") else None) or ["Quality you can trust."],
        "cta_phrases": _clamp_list(raw.get("cta_phrases"), 4, 6,
                                    pad_with=None) or ["Get in touch today."],
        "hashtags": _clamp_list(hashtags, 8, 12, pad_with=None) or ["#Business"],
        "end_card_palettes": palettes,
        "hard_constraints": list(raw.get("hard_constraints") or [])[:5],
        "visual_terms_allowlist": safe_allowlist,
        "visual_query_qualifiers": list(raw.get("visual_query_qualifiers") or [])[:8],
        "visual_query_fallback_bank": fallback_bank,
    }


def compile_profile(company: dict) -> dict:
    """company = a companies-table row dict. Returns ONLY the 9 creative
    fields (see _validate). Raises on total AI failure — no silent empty
    profile; the caller (the admin-triggered dashboard route) should surface
    the error, not provision a broken client."""
    prompt = _build_prompt(company)
    raw = call_structured(prompt, max_tokens=2500)
    return _validate(raw)
