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
from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, STORY_MODEL
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
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 1600, "temperature": 0.6},
            },
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    else:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1600,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in Photographer response: {raw[:200]}")
    return json.loads(m.group())


# ── Character cast rotation ───────────────────────────────────────────────────
# Rotates by day so the same visual archetype never dominates the grid.
# PAUSED: shocked woman / hand-over-mouth / wide-eyes / phone-staring pose.
_CHARACTER_CAST = [
    "40-year-old Nigerian man, business professional, sharp suit, calm confident expression",
    "28-year-old British-Nigerian woman, casual smart, natural smile, relaxed",
    "55-year-old Nigerian woman, warm maternal energy, modest clothing, gentle expression",
    "32-year-old Black British man, streetwear, laughing or mid-conversation",
    "22-year-old Nigerian female student, university setting, curious attentive look",
    "48-year-old Nigerian man, slightly tired but relieved expression, everyday clothing",
    "35-year-old mixed-heritage woman, airport smart-casual, purposeful stride",
    "60-year-old Nigerian grandfather, dignified, proud expression, traditional or neat dress",
    "26-year-old Black British couple (man and woman), laughing together, casual",
    "38-year-old Nigerian woman, entrepreneur energy, blazer, focused expression",
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
   Include: character description + location + action + shot type
   Example: "40-year-old nigerian man airport departure confident medium shot"
   NOT: "woman apartment medium shot"

2. ai_image_prompt (max 60 words): A detailed prompt for AI image generation.
   Include: age, ethnicity, gender, exact location, specific prop or action,
   lighting, shot type, emotion, format.
   Example: "Photorealistic. 40-year-old Nigerian man in a business suit at Heathrow departures.
   He checks his phone with a calm, confident expression. Warm terminal lighting. Medium shot.
   No text. No logos. Vertical 9:16 portrait."
   NOT: "woman in apartment"

RULES FOR BOTH:
- Medium shot or wide shot ONLY — no close-ups
- No animals, no food, no Christmas, no Halloween
- No courier brand names (DHL, FedEx, Royal Mail, Hermes)
- Characters must be consistent across scenes (same person as cast above, same story)
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
