"""
Generic AI content generator — serves any client whose profile has
"pipeline_type": "generic" (see client_profiles/<slug>.json). Same output
contract as generate_content.generate_content()/generate_content_d818.py's
generate_content()/g_inspired_content.generate_content().

Modeled directly on generate_content_d818.py (the most profile-driven of the
3 existing generators) but with D818's hardcoded catering-domain logic
(food_origin_rule, _PILLAR_QUERY_HINTS, _ANIMAL_TERMS/_DISH_QUALIFIERS)
replaced by the equivalent fields compiled once at onboarding time by
scripts/profile_compiler.py: hard_constraints, visual_terms_allowlist,
visual_query_qualifiers, visual_query_fallback_bank.

Does NOT touch generate_content.py / generate_content_d818.py /
g_inspired_content.py — new code only, zero risk to the 4 existing clients.
Part of the dynamic provisioning plan — see
.claude/plans/fluttering-singing-perlis.md Phase 3.
"""

import json, random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from ai_providers import call_structured
from profile_compiler import _BANNED_FETCH_TERMS

PIPELINE_ROOT = Path(__file__).parent.parent


def _load_profile(client_slug: str) -> dict:
    path = PIPELINE_ROOT / "client_profiles" / f"{client_slug}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_bucket() -> str:
    return ["weekday", "weekday", "weekday", "weekday", "weekday",
            "weekend", "weekend"][date.today().weekday()]


def get_pillar_for_slot(slot: int, client_slug: str) -> str:
    profile = _load_profile(client_slug)
    pillars = profile.get("content_pillars") or ["Behind the scenes", "Customer stories"]
    idx = (date.today().toordinal() + slot) % len(pillars)
    return pillars[idx]


# ── Visual query safety net ─────────────────────────────────────────────────
# Mirrors generate_content_d818.py's _sanitize_visual_query exactly, but the
# allowlist/qualifiers come from this specific client's profile (compiled
# once by profile_compiler.py) instead of a hardcoded catering-domain set.

def _sanitize_visual_query(query: str, profile: dict) -> str:
    """Checks against the FULL universal banned set, not a reduced one —
    allowlisting a term does NOT fully unblock it everywhere, it only means
    the term CAN appear when paired with a qualifier (mirrors D818's real
    _ANIMAL_TERMS+_DISH_QUALIFIERS exactly: "chicken" is only safe alongside
    "grilled"/"suya"/etc, never unconditionally). A banned word that isn't
    even in this client's allowlist can never pass, qualifier or not."""
    allowlist  = set(profile.get("visual_terms_allowlist") or [])
    qualifiers = set(w.lower() for w in (profile.get("visual_query_qualifiers") or []))

    words = set(query.lower().split())
    hit = words & _BANNED_FETCH_TERMS
    if hit and (not hit.issubset(allowlist) or not (words & qualifiers)):
        fallback_bank = profile.get("visual_query_fallback_bank") or ["brand lifestyle shot"]
        return random.choice(fallback_bank)
    return query


def _visual_queries_for_pillar(pillar: str, profile: dict) -> list[str]:
    fallback_bank = profile.get("visual_query_fallback_bank") or ["brand lifestyle shot wide angle"]
    pool = list(dict.fromkeys([pillar] + fallback_bank))
    random.shuffle(pool)
    queries = pool[:8]
    while len(queries) < 8:
        queries.append(random.choice(fallback_bank))
    return queries


def _weighted_primary(items: list[str], primary_weight: float = 0.7) -> str:
    """Same recurring-hook weighting as D818's — item 0 is the brand's
    recognizable recurring line most of the time, occasional variation."""
    if not items:
        return ""
    if len(items) == 1 or random.random() < primary_weight:
        return items[0]
    return random.choice(items[1:])


def _build_prompt(pillar: str, profile: dict) -> str:
    brand    = profile.get("brand_name", "This business")
    niche    = profile.get("niche", "")
    location = profile.get("area_covered") or profile.get("location", "")
    tone     = profile.get("content_tone", "professional")
    voice    = profile.get("brand_voice", "")
    lines    = profile.get("brand_lines") or [f"{brand} — quality you can trust."]
    brand_line = _weighted_primary(lines)
    website  = (profile.get("website") or "").replace("https://", "").replace("www.", "")

    constraints = profile.get("hard_constraints") or []
    constraints_block = (
        "\n".join(f"- {c}" for c in constraints)
        if constraints else "- (none for this client)"
    )

    return f"""You write viral short-form video scripts for {brand} — {niche}, covering {location}.
Brand voice: {voice}
Tone: {tone}
Website: {website}

TODAY'S CONTENT PILLAR: {pillar}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD CONSTRAINTS (non-negotiable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{constraints_block}

RECURRING BRAND HOOK (use often, in spirit or verbatim in the resolution/lesson beats
or captions — this is {brand}'s recognizable recurring line):
"{brand_line}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NARRATIVE FORMULA — follow exactly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. HOOK       A scroll-stopping line related to today's pillar.
2. PROBLEM    A real frustration or gap this business's customers face.
3. STAKES     Why it matters — what's lost if this problem isn't solved.
4. RESOLUTION {brand} solves it — specific, confident, credible.
5. LESSON     One warm, confident closing line in the brand voice.

BEAT RULES (these appear as on-screen text — SHORT):
  hook:       max 12 words. Sensory or emotional pull.
  problem:    max 12 words. Specific, relatable frustration.
  stakes:     max 10 words. What's at stake if unresolved.
  resolution: max 12 words. {brand}. Confident. Done.
  lesson:     max 10 words. One warm brand line.

top_caption: max 9 words. Conversational scene-setter for top of screen.
             Start with: Imagine, What if, Picture this, Ever wondered.
             Do NOT mention the brand name. Feel like a real person typing.

VISUAL QUERIES — 8 Pexels/Pixabay search terms relevant to this business and pillar.
Short queries (2-5 words), no years, no camera-shot jargon (no "wide shot" etc).
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


def _build_hashtags(profile: dict) -> tuple[str, str]:
    tags = profile.get("hashtags") or ["#SmallBusiness"]
    tag_str = " ".join(tags[:8])
    return tag_str, tag_str


def generate_content(slot: int, pillar: str, bucket: str = "", *, client_slug: str) -> dict:
    """Generate a full content dict for one generic-pipeline client's slot.
    Same output contract as the other 3 generators."""
    profile = _load_profile(client_slug)
    if not profile:
        raise RuntimeError(f"client_profiles/{client_slug}.json missing or unreadable.")

    print(f"  [Generic:{client_slug}] Slot {slot} | Pillar: {pillar}")

    raw = call_structured(_build_prompt(pillar, profile), max_tokens=1500)

    raw["pillar"] = pillar
    raw["slot"]   = slot
    raw["date"]   = date.today().isoformat()
    raw["client"] = client_slug
    raw["top_caption"] = raw.get("top_caption", "")

    ai_queries   = [q for q in raw.get("visual_queries", []) if isinstance(q, str) and q.strip()]
    bank_queries = _visual_queries_for_pillar(pillar, profile)
    queries = (ai_queries + bank_queries)[:8]
    while len(queries) < 8:
        queries.append(random.choice(profile.get("visual_query_fallback_bank") or ["brand lifestyle shot"]))
    raw["visual_queries"] = [_sanitize_visual_query(q, profile) for q in queries]

    hashtags_tiktok, hashtags_instagram = _build_hashtags(profile)
    raw["hashtags_tiktok"]    = raw.get("hashtags_tiktok", hashtags_tiktok) or hashtags_tiktok
    raw["hashtags_instagram"] = raw.get("hashtags_instagram", hashtags_instagram) or hashtags_instagram

    return raw


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Generic content generator (manual test)")
    p.add_argument("--client", required=True)
    p.add_argument("--slot", type=int, default=1)
    args = p.parse_args()

    pillar  = get_pillar_for_slot(args.slot, args.client)
    content = generate_content(args.slot, pillar, get_bucket(), client_slug=args.client)
    print(f"\nPillar     : {pillar}")
    print(f"Hook       : {content.get('hook')}")
    print(f"Problem    : {content.get('problem')}")
    print(f"Stakes     : {content.get('stakes')}")
    print(f"Resolution : {content.get('resolution')}")
    print(f"Lesson     : {content.get('lesson')}")
    print(f"Top caption: {content.get('top_caption')}")
    print(f"TikTok cap : {content.get('caption_tiktok')}")
    print(f"Queries    : {content.get('visual_queries')}")
