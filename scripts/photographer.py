"""
OTB_Pipeline — Photographer (Stage 4)

Takes the approved story and basic scene queries, then produces:
  1. Highly specific Pexels search queries (used NOW for video clip search)
  2. AI image generation prompts (stored for future GPT Image / Flux / Imagen use)

The difference this makes:
  Basic query:      "woman apartment medium shot"
  Photographer:     "35-year-old Nigerian woman London apartment holding phone charger worried medium shot"

The AI image prompt goes further:
  "Photorealistic. 35-year-old Nigerian woman sitting on a grey sofa in a modern London
   apartment. She holds a small USB phone charger and looks worried. Warm natural window
   light from the left. Medium shot. No text. No logos. Vertical 9:16 portrait format."
"""

import json, re, sys, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OPENAI_API_KEY, GEMINI_API_KEY, STORY_MODEL
from scene_planner import PILLAR_BLUEPRINTS


def _call_ai(prompt: str) -> str:
    """Use the same model as the story writer for consistency."""
    if STORY_MODEL == "openai":
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o",
                "max_tokens": 1600,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    elif STORY_MODEL == "gemini":
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 1600, "temperature": 0.6, "thinkingConfig": {"thinkingBudget": 0}},
            },
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    else:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o",
                "max_tokens": 1600,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in Photographer response: {raw[:200]}")
    return json.loads(m.group())


# ── Character cast rotation ───────────────────────────────────────────────────
# Rotates by day so the same visual archetype never dominates the grid.
# PAUSED: shocked woman / hand-over-mouth / wide-eyes / phone-staring pose.
_CHARACTER_CAST = [
    # BootHop is a UK/Europe logistics marketplace — this cast should look like its
    # actual customer base, not one ethnicity. Rotates daily via day_index; keep a
    # real mix rather than any one background dominating.
    "40-year-old Nigerian man, business professional, sharp suit, calm confident expression",
    "28-year-old white British woman, casual smart, natural smile, relaxed",
    "55-year-old Nigerian woman, warm maternal energy, modest clothing, gentle expression",
    "32-year-old Black British man, streetwear, laughing or mid-conversation",
    "22-year-old British Asian female student, university setting, curious attentive look",
    "48-year-old white British man, slightly tired but relieved expression, everyday clothing",
    "35-year-old European woman, business smart-casual, purposeful stride",
    "60-year-old white British grandfather, dignified, proud expression, neat casual dress",
    "26-year-old British Asian couple (man and woman), laughing together, casual",
    "38-year-old Nigerian woman, entrepreneur energy, blazer, focused expression",
    "45-year-old white British tradesman, workwear, warehouse or van setting, practical",
    "30-year-old European man, smart-casual, train station or office setting",
    "50-year-old British Asian businessman, suit, office setting, confident",
    "27-year-old mixed-heritage woman, casual, city street, relaxed energy",
    "33-year-old white British woman, business professional, office setting, focused",
]

_VISUAL_BANNED = (
    "BANNED visual poses (never generate these):\n"
    "- Shocked woman with hand over mouth\n"
    "- Extreme wide eyes staring at phone\n"
    "- Open-mouth surprise expressions\n"
    "- Any character repeated from a previous video\n"
    "Use natural, subtle reactions: a quiet smile, a raised eyebrow, a nod, relief, pride."
)


def generate_image_prompts(story: dict, scene_queries: list[str], pillar: str, day_index: int = 0) -> dict:
    """
    Stage 4: Photographer agent.
    Takes the approved story and basic scene queries.
    Returns improved Pexels queries + AI image generation prompts for all 8 scenes.
    Falls back to the original scene_queries if the API call fails.
    """
    blueprint = PILLAR_BLUEPRINTS.get(pillar, PILLAR_BLUEPRINTS["supply_chain"])
    blueprint_lines = "\n".join(f"  Scene {i}: {desc}" for i, desc in enumerate(blueprint))
    queries_text = "\n".join(f"  Scene {i}: {q}" for i, q in enumerate(scene_queries))

    cast_today = _CHARACTER_CAST[day_index % len(_CHARACTER_CAST)]

    prompt = f"""You are the Photographer for BootHop's video pipeline. Your job is to upgrade basic scene search queries into highly specific descriptions.

STORY:
  Hook: {story.get('hook', '')}
  Problem: {story.get('problem', '')}
  Stakes: {story.get('stakes', '')}
  Resolution: {story.get('resolution', '')}
  Lesson: {story.get('lesson', '')}
  Pillar: {pillar}

TODAY'S LEAD CHARACTER — use this archetype for the main person in this video:
  {cast_today}
  This character must look visually different from a shocked woman staring at a phone.
  Keep this same character consistent across all 8 scenes of THIS video.
  But this archetype rotates daily — tomorrow's video will cast a different person entirely.

{_VISUAL_BANNED}

SCENE BLUEPRINT:
{blueprint_lines}

CURRENT BASIC QUERIES (upgrade these):
{queries_text}

YOUR JOB — for each of the 8 scenes produce TWO things:

1. pexels_query (max 8 words): A highly specific Pexels search query.
   Include: character description (from TODAY'S LEAD CHARACTER above, every time)
   + location + action + shot type.
   Format example (match this STRUCTURE, not the ethnicity — always use today's
   actual cast, never this example's): "40-year-old nigerian man airport
   departure confident medium shot"
   NOT: "woman apartment medium shot"

2. ai_image_prompt (max 60 words): A detailed prompt for AI image generation.
   Include: age, ethnicity, gender, exact location, specific prop or action,
   lighting, shot type, emotion, format — all matching TODAY'S LEAD CHARACTER
   above, every single scene, including scenes 5-7.
   Format example (match this STRUCTURE, not the ethnicity): "Photorealistic.
   40-year-old Nigerian man in a business suit at Heathrow departures. He checks
   his phone with a calm, confident expression. Warm terminal lighting. Medium
   shot. Vertical 9:16 portrait."
   If a parcel, bag, or van appears: describe it with BootHop's orange brand colour
   (a bright orange delivery bag/box/van livery) for natural, visible — but not
   necessarily legible-text — branding. Don't rely on the model to render exact
   logo text; the real BootHop logo is composited separately in post-production.
   NOT: "woman in apartment"

RULES FOR BOTH:
- Medium shot or wide shot ONLY — no close-ups
- No animals, pets, birds, livestock, insects or wildlife of any kind — none held, carried, standing beside a person, in the background, on a table, in a cage, or as decoration, not even incidentally. No food, no Christmas, no Halloween
- No farm or rural scenery (no plantation, farmland, barn, countryside, rural, crops, harvest, ranch, savanna)
- No courier brand names (DHL, FedEx, Royal Mail, Hermes)
- MANDATORY — CHECK THIS FOR EVERY SCENE, INCLUDING 5, 6, AND 7: the character
  in every one of the 8 scenes MUST be TODAY'S LEAD CHARACTER stated above —
  same age, same ethnicity, same gender, same description. Scenes do not drift
  to a different archetype partway through. Re-read TODAY'S LEAD CHARACTER
  before writing scenes 5-7 specifically — these are the scenes most likely to
  drift.
- Location must make sense for the story pillar: {pillar}

Return ONLY valid JSON:
{{
  "scenes": [
    {{
      "scene": 0,
      "beat": "hook",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }},
    {{
      "scene": 1,
      "beat": "hook",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }},
    {{
      "scene": 2,
      "beat": "problem",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }},
    {{
      "scene": 3,
      "beat": "problem",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }},
    {{
      "scene": 4,
      "beat": "stakes",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }},
    {{
      "scene": 5,
      "beat": "resolution",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }},
    {{
      "scene": 6,
      "beat": "resolution",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }},
    {{
      "scene": 7,
      "beat": "lesson",
      "pexels_query": "...",
      "ai_image_prompt": "..."
    }}
  ]
}}"""

    try:
        raw = _call_ai(prompt)
        result = _parse_json(raw)
        scenes = result.get("scenes", [])

        if len(scenes) == 8:
            pexels_queries = [s["pexels_query"] for s in scenes]
            image_prompts  = [s["ai_image_prompt"] for s in scenes]

            print(f"  [Photographer] Generated {len(scenes)} scene prompts")
            for s in scenes:
                print(f"    Scene {s['scene']}: {s['pexels_query']}")

            return {
                "pexels_queries": pexels_queries,
                "image_prompts":  image_prompts,
            }

        print(f"  [Photographer] Expected 8 scenes, got {len(scenes)} — using original queries")

    except Exception as e:
        print(f"  [Photographer] Failed: {e} — using original scene queries")

    # Fallback: return the original scene planner queries unchanged
    return {
        "pexels_queries": scene_queries,
        "image_prompts":  [f"Photorealistic. {q}. Vertical 9:16 portrait. No text." for q in scene_queries],
    }
