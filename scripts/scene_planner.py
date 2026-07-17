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
        "Black British woman in UK home or office — looks worried, holds a small item to send",
        "Phone screen showing an expensive courier price — Nigerian woman reacting shocked",
        "African woman on phone call looking frustrated at a high delivery price",
        "Black man at train station handing small parcel to a traveller — wide shot",
        "African traveller seated on a train or flight — relaxed, parcel with them",
        "Black traveller arriving in Lagos — airport arrivals hall wide shot",
        "Nigerian woman smiling at door receiving small parcel — friendly handover",
        "Wide London or Lagos cityscape — confident aspirational wide shot",
    ],
    "family": [
        "Nigerian woman in UK home — holds small gift cream or medicine for family — medium shot",
        "Black woman at courier counter reacting to expensive price — shocked medium shot",
        "African woman upset or worried on phone at home — medium shot",
        "Black man at train station handing small parcel to traveller — friendly wide shot",
        "African traveller on flight heading to Nigeria — window seat relaxed medium shot",
        "Nigerian traveller arriving at home doorstep — warm family reunion wide shot",
        "Black family member smiling receiving a small gift — warm happy medium shot",
        "Wide London residential street or Lagos neighbourhood — people walking",
    ],
    "airport": [
        "Busy airport departures hall — African and Black travellers moving with luggage wide shot",
        "Customs security checkpoint — Black traveller bags being checked wide shot",
        "Nigerian woman looking stressed at airport counter medium shot",
        "Black traveller at departure gate with cabin luggage and small parcel medium shot",
        "Wide airplane taking off from runway — dramatic wide shot",
        "Airport arrivals hall — Black travellers walking out confidently wide shot",
        "African woman friendly parcel handover at airport arrivals smiling wide shot",
        "Wide aerial international airport or Lagos skyline wide shot",
    ],
    "airport_deliveries": [
        "Black woman at pharmacy counter collecting prescription — medium shot",
        "Nigerian woman holding small medicine box prescription packet — medium shot",
        "African man on phone call looking worried — explaining urgent problem medium shot",
        "Black traveller at train station receiving small medical parcel from sender wide shot",
        "African traveller on flight window seat plane in air medium shot",
        "Nigerian traveller walking through customs arrivals confidently medium shot",
        "Black person smiling at door receiving medication parcel — relief medium shot",
        "Wide London city street — diverse people walking confident wide shot",
    ],
    "community": [
        "Nigerian man or woman in London street or apartment — animated talking medium shot",
        "Two Black people talking warmly — community gathering or cafe wide shot",
        "African woman using phone app in public — smiling satisfied medium shot",
        "Black traveller at train station receiving parcel from Nigerian community member wide shot",
        "African traveller on train or at airport gate heading out medium shot",
        "Nigerian person arriving home with parcel front door medium shot",
        "Black family happy handover at door — smiling recipient receives parcel medium shot",
        "Wide London street or community space — diverse Black people welcoming wide shot",
    ],
    "smart": [
        "Black British professional at London airport departure lounge confident medium shot",
        "African man on phone checking app looking pleased at earnings medium shot",
        "Wide airport departure gate — Black traveller with cabin luggage confident wide shot",
        "Nigerian woman handing small parcel to Black traveller at train station wide shot",
        "African traveller on flight relaxed looking out window medium shot",
        "Black traveller arriving Lagos airport confidently exiting wide shot",
        "Two Black people parcel handover both smiling mutual benefit wide shot",
        "Wide Lagos or London skyline — successful aspirational wide shot",
    ],
    "travel_hacks": [
        "Black British woman neatly packing suitcase — organised smart traveller medium shot",
        "Airport departures board Nigeria destination — African travellers wide shot",
        "Nigerian woman comparing prices on phone saving money satisfied medium shot",
        "Wide train station — Black traveller collecting parcel from Nigerian sender wide shot",
        "African man plane window view in flight relaxed medium shot",
        "Black traveller walking through customs arrivals confidently wide shot",
        "Nigerian couple friendly parcel handover destination both smiling wide shot",
        "Wide international airport exterior or London street diverse people wide shot",
    ],
    "logistics_stories": [
        "Wide cargo ship at sea or shipping containers stacked at port wide shot",
        "Black woman at courier counter reacting to high price surprised medium shot",
        "African man on phone frustrated logistics problem medium shot",
        "Wide Black traveller at airport handing parcel to Nigerian recipient wide shot",
        "African traveller on flight or train — parcel safely with them medium shot",
        "Black traveller walking through arrivals hall confidently wide shot",
        "Nigerian woman smiling receiving parcel at door medium shot",
        "Wide busy port cargo facility or London Lagos cityscape wide shot",
    ],
    "cost_pain": [
        "Nigerian woman in UK home looking shocked holding courier price quote medium shot",
        "Black woman at laptop or phone — expensive courier website shown on screen medium shot",
        "African man at courier counter shocked at high delivery price medium shot",
        "Nigerian woman on phone call upset about delivery cost medium shot",
        "Black traveller and Nigerian sender at train station parcel handover wide shot",
        "African traveller on flight with parcel relaxed window seat medium shot",
        "Black woman on phone smiling — happy with affordable delivery medium shot",
        "Diverse Black people London street confident celebrating wide shot",
    ],
    "cultural_earn": [
        "Black British traveller at Heathrow airport confident departure lounge medium shot",
        "African man at airport check-in with cabin luggage earning money on phone medium shot",
        "Nigerian woman talking animatedly on phone — excited about earning medium shot",
        "Two Black people shaking hands airport or station — traveller and sender wide shot",
        "African traveller on flight smiling relaxed window seat medium shot",
        "Black traveller arriving Lagos airport earning accomplished wide shot",
        "Two African people mutual parcel handover both smiling satisfied wide shot",
        "Wide London or Lagos street — successful Black diaspora people wide shot",
    ],
    "urgent_medical": [
        "Nigerian woman at pharmacy looking worried holding prescription medium shot",
        "Black woman on phone urgently explaining medical situation medium shot",
        "African man at pharmacy counter medication unavailable worried medium shot",
        "Nigerian family member on video call worried urgent expression medium shot",
        "Black traveller at train station receiving small medical parcel from sender wide shot",
        "African traveller on flight with small parcel window seat relaxed medium shot",
        "Nigerian woman at door receiving medication parcel — relief smiling medium shot",
        "Wide London street — diverse Black people community warm wide shot",
    ],
    "brand_authority": [
        "Black British professional confident smiling at London office medium shot",
        "Wide shot diverse Black diaspora people on London high street wide shot",
        "Nigerian woman on phone looking confident and satisfied medium shot",
        "Nigerian man comparing delivery options on phone looking pleased medium shot",
        "African man and Black woman friendly professional parcel handover wide shot",
        "Black traveller at airport confident with luggage departure lounge medium shot",
        "Nigerian couple receiving parcel at door both smiling wide shot",
        "Diverse group Black people celebrating community London wide shot",
    ],
}

# Safe fallback queries — used when the API call fails
_FALLBACK_QUERIES = [
    "Black British woman london flat worried medium shot",
    "African travellers airport departures wide shot",
    "Nigerian woman post office counter shocked medium shot",
    "Black traveller train station luggage wide shot",
    "African woman phone call worried medium shot",
    "Black man parcel handover train station smiling wide shot",
    "African man plane window seat flight medium shot",
    "diverse Black people london street wide establishing shot",
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

DIVERSITY RULE — MANDATORY:
For all person-focused queries, include ONE of these subject identifiers:
  "Black British woman", "Nigerian woman", "African man", "Black traveller",
  "African couple", "Black man", "Nigerian man", "diverse Black people"
BootHop serves the UK/Nigeria diaspora — all human subjects must reflect this audience.

DYNAMIC CONTENT (prefer for hook scene 0 and lesson scene 7):
  Use active subjects: "woman dancing celebration", "man talking animated",
  "people celebrating street", "woman laughing phone" — not static posed shots.

CORRECT examples:
  "Black British woman london flat worried medium shot"
  "Nigerian woman pharmacy counter shocked medium shot"
  "African man train station parcel handover wide shot"
  "Black traveller plane window seat medium shot"
  "Nigerian woman door smiling parcel medium shot"
  "diverse Black people london street wide shot"
  "African woman dancing celebration wide shot"

WRONG — never do this:
  "woman close up face shocked"   ← no ethnicity, close-up
  "DHL courier tracking parcel"   ← brand name
  "farm green field landscape"    ← no people, banned
  "airport crowd far away wide"   ← vague, no people descriptor

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
