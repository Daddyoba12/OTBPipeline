"""
OTB_Pipeline — Cinematographer (Stage 5)

Takes the Photographer's image prompts and converts each one into a
full cinematic video prompt ready for Kling, Veo, or Runway.

Each video prompt adds:
  - Camera movement (slow zoom, pan, dolly, static)
  - Duration (4 seconds for content clips)
  - Lighting direction
  - Emotion arc
  - Action/motion within the scene

These prompts are stored in the output JSON now and will be used
when Kling / Veo / Runway API integration is added.
"""

import json, re, sys, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, STORY_MODEL

CLIP_DUR = 4  # seconds per content clip

# Beat-specific camera directions — guide the cinematographer per beat type
BEAT_CAMERA = {
    "hook":       "Start with a slow push-in. Build tension in 4 seconds.",
    "problem":    "Static or very slow zoom. Show the weight of the situation.",
    "stakes":     "Gentle pull-back to reveal the emotional context.",
    "resolution": "Warm, smooth dolly forward. Optimistic energy.",
    "lesson":     "Wide establishing shot. Confident, aspirational feel.",
}


def _call_ai(prompt: str) -> str:
    if STORY_MODEL == "openai":
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o",
                "max_tokens": 1400,
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
                "generationConfig": {"maxOutputTokens": 1400, "temperature": 0.6},
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
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in Cinematographer response: {raw[:200]}")
    return json.loads(m.group())


def generate_video_prompts(story: dict, photo_result: dict) -> dict:
    """
    Stage 5: Cinematographer agent.
    Converts image prompts into cinematic video prompts for Kling/Veo/Runway.
    Returns a dict with a list of 8 video prompt dicts.
    Falls back to a simple version of the image prompts if the API call fails.
    """
    image_prompts = photo_result.get("image_prompts", [])
    if not image_prompts:
        return {"video_prompts": []}

    beats = ["hook", "hook", "problem", "problem", "stakes", "resolution", "resolution", "lesson"]
    scenes_text = "\n".join(
        f"  Scene {i} [{beats[i]}]: {img}"
        for i, img in enumerate(image_prompts[:8])
    )
    beat_camera_text = "\n".join(f"  {beat}: {direction}" for beat, direction in BEAT_CAMERA.items())

    prompt = f"""You are the Cinematographer for BootHop's video pipeline. Convert these image descriptions into video prompts for AI video generators (Kling, Veo, Runway).

STORY CONTEXT:
  Hook: {story.get('hook', '')}
  Lesson: {story.get('lesson', '')}

IMAGE SCENES TO CONVERT:
{scenes_text}

CAMERA DIRECTION GUIDE BY BEAT:
{beat_camera_text}

For each scene produce a complete video prompt that includes:
- The scene description (from the image prompt)
- Camera movement: one of [slow zoom in, slow zoom out, gentle pan left, gentle pan right, static, slow dolly forward, slow pull back]
- Lighting: describe the light quality and direction
- Duration: always 4 seconds
- Motion: what moves within the frame (person walking, looking up, hands moving, etc.)
- Emotion: the feeling this clip should convey

RULES:
- Medium or wide shots ONLY
- No close-ups, no extreme face shots
- Keep characters consistent with the story (same person, same location)
- Each clip must visually advance the story

Return ONLY valid JSON:
{{
  "video_prompts": [
    {{
      "scene": 0,
      "beat": "hook",
      "camera_move": "slow zoom in",
      "duration": 4,
      "emotion": "worry",
      "full_prompt": "..."
    }},
    {{
      "scene": 1,
      "beat": "hook",
      "camera_move": "static",
      "duration": 4,
      "emotion": "tension",
      "full_prompt": "..."
    }},
    {{
      "scene": 2,
      "beat": "problem",
      "camera_move": "static",
      "duration": 4,
      "emotion": "frustration",
      "full_prompt": "..."
    }},
    {{
      "scene": 3,
      "beat": "problem",
      "camera_move": "gentle pan left",
      "duration": 4,
      "emotion": "stress",
      "full_prompt": "..."
    }},
    {{
      "scene": 4,
      "beat": "stakes",
      "camera_move": "slow pull back",
      "duration": 4,
      "emotion": "sadness",
      "full_prompt": "..."
    }},
    {{
      "scene": 5,
      "beat": "resolution",
      "camera_move": "slow dolly forward",
      "duration": 4,
      "emotion": "relief",
      "full_prompt": "..."
    }},
    {{
      "scene": 6,
      "beat": "resolution",
      "camera_move": "slow zoom out",
      "duration": 4,
      "emotion": "happiness",
      "full_prompt": "..."
    }},
    {{
      "scene": 7,
      "beat": "lesson",
      "camera_move": "slow pan right",
      "duration": 4,
      "emotion": "confidence",
      "full_prompt": "..."
    }}
  ]
}}"""

    try:
        raw = _call_ai(prompt)
        result = _parse_json(raw)
        prompts = result.get("video_prompts", [])

        if len(prompts) == 8:
            print(f"  [Cinematographer] Generated {len(prompts)} video prompts")
            return {"video_prompts": prompts}

        print(f"  [Cinematographer] Expected 8 prompts, got {len(prompts)} — using simple fallback")

    except Exception as e:
        print(f"  [Cinematographer] Failed: {e} — using simple fallback")

    # Simple fallback: wrap image prompts with basic camera direction
    beats = ["hook", "hook", "problem", "problem", "stakes", "resolution", "resolution", "lesson"]
    moves = ["slow zoom in", "static", "static", "gentle pan left",
             "slow pull back", "slow dolly forward", "slow zoom out", "slow pan right"]
    emotions = ["worry", "tension", "frustration", "stress",
                "sadness", "relief", "happiness", "confidence"]

    fallback = []
    for i, img in enumerate(image_prompts[:8]):
        fallback.append({
            "scene": i,
            "beat": beats[i],
            "camera_move": moves[i],
            "duration": CLIP_DUR,
            "emotion": emotions[i],
            "full_prompt": f"{img} Camera: {moves[i]}. Duration: {CLIP_DUR} seconds. Emotion: {emotions[i]}.",
        })

    return {"video_prompts": fallback}
