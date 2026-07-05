"""
OTB_Pipeline — Scene Planner (Stage 2)

Converts a story narrative into 8 scene-specific Pexels search queries.
Each pillar has a fixed blueprint that enforces the correct narrative scene order.

Scene positions:
  0-1  HOOK:       Protagonist's world — who they are and where they are
  2-3  PROBLEM:    The specific obstacle they face (pharmacy, courier price, customs)
  4    STAKES:     Why it matters emotionally (worried call, waiting, upset)
  5-6  RESOLUTION: BootHop in action — parcel handover + traveller on journey
  7    LESSON:     Happy ending — delivery, smiling recipient, or confident cityscape
"""

import json, re, sys, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY

# ── Pillar blueprints — fixed narrative scene order per content pillar ─────────
# Each list entry describes what the clip at that position MUST show.
# The Scene Planner AI uses these as hard constraints when writing search queries.
PILLAR_BLUEPRINTS = {
    "supply_chain": [
        "Woman in UK home, kitchen, bedroom, office, bus, or train — looks worried, holds a small item to send",
        "Phone or laptop screen showing an expensive courier price quote",
        "Woman on phone call looking frustrated or shocked at a high price",
        "Person at airport, train station, or bus stop handing small parcel to a traveller",
        "Traveller seated on a train or flight — relaxed, parcel with them",
        "Traveller arriving in Lagos — airport arrivals hall or Lagos city street",
        "Smiling person at door receiving small parcel — friendly handover",
        "Wide London or Lagos cityscape — confident and aspirational",
    ],
    "family": [
        "Woman in UK home or shop — holds small gift, cream, birthday card, or medicine for family in Nigeria",
        "Person at post office or courier counter reacting to an expensive price — shocked",
        "Woman upset or worried at home or on the phone",
        "Person at train station or airport handing small parcel to traveller — friendly exchange",
        "Traveller on flight or train heading to Nigeria — window seat, relaxed",
        "Traveller arriving at a home doorstep in Nigeria — warm family reunion",
        "Family member smiling and receiving a small gift or parcel — warm and happy",
        "Wide London residential street or Lagos neighbourhood",
    ],
    "airport": [
        "Wide shot busy airport departures hall — travellers moving through with luggage",
        "Customs or security checkpoint — bags and luggage being checked by officer",
        "Person looking stressed at airport counter or service desk",
        "Departure gate — traveller with cabin luggage and small parcel",
        "Wide shot airplane taking off from runway — dramatic",
        "Airport arrivals hall — travellers walking out through doors",
        "Friendly parcel handover at airport arrivals — smiling recipient",
        "Wide aerial or ground shot international airport or Lagos skyline",
    ],
    "airport_deliveries": [
        "Pharmacy or chemist shop interior — person collecting prescription at counter",
        "Person holding small medicine box or prescription packet",
        "Person on phone call looking worried — explaining a problem",
        "Traveller at airport or train station receiving small parcel from sender — wide shot",
        "Traveller on flight — window seat, plane in air, medium shot",
        "Customs or arrivals hall — traveller walking through confidently",
        "Person smiling at door receiving medication or parcel",
        "Wide establishing London or Lagos city street — positive ending",
    ],
    "community": [
        "Nigerian man or woman in London — street, office, or apartment — medium shot",
        "Two people talking warmly — community meeting or cafe conversation",
        "Person using phone app in public — cafe, bus, or street",
        "Wide shot traveller at train station receiving parcel from community member",
        "Traveller on train or at airport gate heading out",
        "Person arriving home with parcel — front door",
        "Happy handover at door — smiling recipient receives parcel",
        "Wide London street or community space — warm and welcoming",
    ],
    "smart": [
        "Professional person at London airport check-in or departure lounge",
        "Person on phone or laptop checking app — looking pleased at earnings",
        "Wide airport departure gate — traveller with cabin luggage, confident",
        "Wide shot person handing small parcel to traveller at train station",
        "Traveller on flight — relaxed, looking out window",
        "Wide arrival in Lagos — confident traveller exiting airport",
        "Person receiving parcel payment — mutual benefit — both smiling",
        "Wide Lagos or London skyline — successful and aspirational",
    ],
    "travel_hacks": [
        "Person neatly packing suitcase — organised smart traveller",
        "Airport departures board showing Nigeria destination — wide shot",
        "Person comparing prices on phone — saving money, looking satisfied",
        "Wide train station platform — traveller collecting parcel from sender",
        "Plane window view — traveller in flight, relaxed",
        "Wide arrivals hall — confident traveller exiting customs",
        "Friendly parcel handover at destination — both people smiling",
        "Wide international airport exterior or London street",
    ],
    "logistics_stories": [
        "Wide cargo ship at sea or shipping containers stacked at port",
        "Person at post office or courier counter looking at price — surprised",
        "Person on phone looking frustrated — logistics problem",
        "Wide traveller at airport or train station handing parcel to recipient",
        "Traveller on flight or train — parcel safely with them",
        "Wide arrivals hall — traveller walking through",
        "Person smiling receiving parcel at door or office lobby",
        "Wide busy port cargo facility or London Lagos cityscape",
    ],
}

# Safe fallback queries — used when the API call fails
_FALLBACK_QUERIES = [
    "woman london apartment worried medium shot",
    "airport departures hall travellers walking wide",
    "person post office counter shocked medium shot",
    "traveller train station luggage wide shot",
    "woman sitting phone call worried medium shot",
    "parcel handover train station smiling wide shot",
    "plane window seat flight medium shot",
    "london city street wide establishing shot",
]


def plan_scenes(story: dict, pillar: str) -> list[str]:
    """
    Stage 2: convert a story narrative into 8 scene-specific Pexels search queries.
    Always uses Claude Haiku (fast, cheap) regardless of the STORY_MODEL setting.
    Returns a list of 8 query strings. Falls back to safe defaults if the API fails.
    """
    blueprint = PILLAR_BLUEPRINTS.get(pillar, PILLAR_BLUEPRINTS["supply_chain"])
    blueprint_lines = "\n".join(f"  Scene {i}: {desc}" for i, desc in enumerate(blueprint))

    prompt = f"""You are a Scene Planner for a short social media video. Convert this story into 8 Pexels video search queries.

STORY:
  Hook: {story.get('hook', '')}
  Problem: {story.get('problem', '')}
  Stakes: {story.get('stakes', '')}
  Resolution: {story.get('resolution', '')}
  Lesson: {story.get('lesson', '')}

SCENE BLUEPRINT — follow this order EXACTLY. Each query must visually match its scene:
{blueprint_lines}

RULES FOR EVERY QUERY (non-negotiable):
- Maximum 6 words per query
- ALWAYS use "medium shot" OR "wide shot" in the query — no exceptions
- NEVER use "close up", "close-up", "extreme", or "face only"
- NEVER use animals: dog, cat, horse, farm, zoo, bird, wildlife, livestock
- NEVER use food: restaurant, kitchen, grocery, meal, cooking, cafe
- NEVER use Christmas, Halloween, pumpkin, Santa
- NEVER name courier companies: DHL, FedEx, Royal Mail, Hermes, UPS

CORRECT examples:
  "woman london flat worried medium shot"
  "pharmacy counter prescription wide shot"
  "traveller train station parcel wide shot"
  "plane window seat flight medium shot"
  "person door smiling parcel medium shot"
  "london city street wide shot"

WRONG — never do this:
  "woman close up face shocked"
  "DHL courier tracking parcel"
  "farm green field landscape"
  "airport crowd far away wide"

Return ONLY valid JSON with no markdown:
{{"visual_queries": ["q0","q1","q2","q3","q4","q5","q6","q7"]}}"""

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
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group())
            queries = data.get("visual_queries", [])
            if len(queries) == 8:
                print(f"  [ScenePlanner] Planned {len(queries)} scenes for pillar: {pillar}")
                for i, q in enumerate(queries):
                    print(f"    Scene {i}: {q}")
                return queries
            print(f"  [ScenePlanner] Expected 8 queries, got {len(queries)} — using fallback")
    except Exception as e:
        print(f"  [ScenePlanner] Failed: {e} — using fallback queries")

    return list(_FALLBACK_QUERIES)


def plan_scenes_v2(story: dict, pillar: str, v1_queries: list[str]) -> list[str]:
    """
    Scene Planner for V2 — generates a fresh set of 8 queries for the same pillar
    but avoids repeating V1's queries. Rotates blueprint perspective slightly.
    """
    blueprint = PILLAR_BLUEPRINTS.get(pillar, PILLAR_BLUEPRINTS["supply_chain"])
    blueprint_lines = "\n".join(f"  Scene {i}: {desc}" for i, desc in enumerate(blueprint))
    v1_str = "\n".join(f"  - {q}" for q in v1_queries[:8])

    prompt = f"""You are a Scene Planner for a social media video. Generate a SECOND SET of 8 Pexels search queries for the same story.

STORY:
  Hook: {story.get('hook_v2', story.get('hook', ''))}
  Problem: {story.get('problem', '')}
  Resolution: {story.get('resolution', '')}
  Lesson: {story.get('lesson_v2', story.get('lesson', ''))}

SCENE BLUEPRINT (same structure as V1 — follow this order):
{blueprint_lines}

V1 already used these queries — do NOT repeat them, find fresh alternatives:
{v1_str}

RULES: same as V1 — medium/wide shots only, no close-ups, no animals, no food, no courier brand names.

Return ONLY valid JSON:
{{"visual_queries": ["q0","q1","q2","q3","q4","q5","q6","q7"]}}"""

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
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group())
            queries = data.get("visual_queries", [])
            if len(queries) == 8:
                print(f"  [ScenePlanner-V2] Planned {len(queries)} fresh scenes for pillar: {pillar}")
                return queries
    except Exception as e:
        print(f"  [ScenePlanner-V2] Failed: {e} — rotating V1 queries")

    # Fallback: rotate V1 queries by 4
    return v1_queries[4:] + v1_queries[:4]
