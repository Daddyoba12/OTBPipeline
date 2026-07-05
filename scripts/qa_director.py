"""
OTB_Pipeline — QA Director (Stage 2)

Acts as the Movie Director. After the Story Writer produces the narrative,
the QA Director reviews it against 7 quality dimensions and rewrites any
weak beat automatically. Nothing below 80/100 reaches the Scene Planner.

Quality dimensions scored 0-10 each:
  1. Hook strength     — stops the scroll, specific, under 15 words
  2. Story coherence   — one clear character, one logical arc, no contradictions
  3. Beat length       — each beat fits the video overlay (12 words max)
  4. Brand safety      — no courier brand names (DHL, FedEx, Royal Mail, etc.)
  5. Emotional impact  — viewer feels the pain, relief, and lesson
  6. BootHop fit       — BootHop appears only in resolution, positioned correctly
  7. Lesson quality    — punchy, screenshot-worthy, under 10 words

Overall = average × 10. If overall < 80, the Director rewrites the full story.
"""

import json, re, sys, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, QA_MODEL


def _call_claude_qa(prompt: str) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1400,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=35,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_openai_qa(prompt: str) -> str:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
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


def _call_gemini_qa(prompt: str) -> str:
    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 1400, "temperature": 0.5},
        },
        timeout=35,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_qa_ai(prompt: str) -> str:
    if QA_MODEL == "openai":
        print("  [QADirector] Reviewing with OpenAI GPT-4o")
        return _call_openai_qa(prompt)
    elif QA_MODEL == "gemini":
        print("  [QADirector] Reviewing with Google Gemini")
        return _call_gemini_qa(prompt)
    print("  [QADirector] Reviewing with Claude Sonnet")
    return _call_claude_qa(prompt)


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in QA response: {raw[:200]}")
    return json.loads(m.group())


def _build_qa_prompt(story: dict, pillar: str) -> str:
    return f"""You are the QA Director for BootHop's social media video pipeline.
Your job: review this story, score it on 7 dimensions, and rewrite any weak beats.

STORY TO REVIEW:
  Pillar: {pillar}
  Hook: {story.get('hook', '')}
  Problem: {story.get('problem', '')}
  Stakes: {story.get('stakes', '')}
  Resolution: {story.get('resolution', '')}
  Lesson: {story.get('lesson', '')}

ABOUT BOOTHOP (context for scoring):
BootHop is a peer-to-peer parcel delivery app. Travellers already flying between UK and Nigeria carry parcels for senders and earn money. BootHop should appear ONLY in the Resolution beat — never earlier.

SCORE EACH DIMENSION 0-10:

1. hook_strength
   - 10: Stops the scroll instantly. Specific item/person/number. Under 15 words. Emotional.
   - 5: OK but generic or too long.
   - 0: Vague, starts with "BootHop", or over 15 words.

2. story_coherence
   - 10: One clear character. One logical arc. Scenes connect naturally. No contradictions.
   - 5: Minor gaps or slightly unclear character.
   - 0: Random scenes, two different stories mixed, or character changes mid-story.

3. beat_length
   - 10: Every beat is 12 words or fewer (these appear as on-screen video text).
   - 5: One or two beats are slightly over.
   - 0: Multiple beats are long sentences that will be cut off on screen.

4. brand_safety
   - 10: No courier company named anywhere (no DHL, FedEx, Royal Mail, Hermes, Parcelforce, UPS).
   - 0: Any courier brand name appears anywhere in the story.

5. emotional_impact
   - 10: Viewer feels the frustration in problem, relief in resolution, and inspired by lesson.
   - 5: Story is logical but flat — no emotional pull.
   - 0: Cold, factual, no emotion.

6. boothop_fit
   - 10: BootHop appears only in Resolution, positioned as the clever peer-to-peer solution.
   - 5: BootHop mentioned but not clearly explained as the solution.
   - 0: BootHop appears in Hook or Problem, or doesn't appear at all.

7. lesson_quality
   - 10: One punchy line under 10 words. Screenshot-worthy. Viewer will share it.
   - 5: OK but could be sharper.
   - 0: Too long, preachy, or doesn't land.

OVERALL SCORE = (sum of all 7 scores / 7) × 10. Round to nearest integer.

IF OVERALL < 80: Rewrite the full story. Fix every weak beat.
IF OVERALL >= 80: Pass through as-is (set rewritten to false).

REWRITE RULES (if rewriting):
- Courier brand rule: NEVER name DHL, FedEx, Royal Mail, Hermes — always "a reputable courier"
- Beat length rule: EVERY beat max 12 words (it appears on screen as video text)
- Hook: must be specific, emotional, under 15 words, never start with "BootHop"
- Problem: max 12 words — short punchy lines, viewer must feel the pain
- Stakes: max 10 words — one sharp line about why it matters
- Resolution: max 12 words — BootHop appears here for the first time
- Lesson: max 10 words — punchy, screenshot-worthy takeaway
- Keep the SAME character and SAME story — just improve the writing quality

Return ONLY valid JSON, no markdown:
{{
  "scores": {{
    "hook_strength": 0,
    "story_coherence": 0,
    "beat_length": 0,
    "brand_safety": 0,
    "emotional_impact": 0,
    "boothop_fit": 0,
    "lesson_quality": 0,
    "overall": 0
  }},
  "issues": ["list of specific problems found"],
  "rewritten": true,
  "hook": "...",
  "problem": "...",
  "stakes": "...",
  "resolution": "...",
  "lesson": "..."
}}"""


def review_and_improve(story: dict, pillar: str) -> dict:
    """
    QA Director: review the story, score it, rewrite if needed.
    Returns the story dict (original or improved) with QA scores attached.
    Falls back to the original story if the QA call fails.
    """
    try:
        prompt = _build_qa_prompt(story, pillar)
        raw = _call_qa_ai(prompt)
        result = _parse_json(raw)

        scores = result.get("scores", {})
        overall = scores.get("overall", 0)
        issues = result.get("issues", [])
        rewritten = result.get("rewritten", False)

        print(f"  [QADirector] Overall score: {overall}/100")
        for dim, score in scores.items():
            if dim != "overall":
                flag = " ⚠" if score < 7 else ""
                print(f"    {dim}: {score}/10{flag}")

        if issues:
            for issue in issues:
                print(f"    Issue: {issue}")

        if rewritten:
            print("  [QADirector] Story rewritten — improvements applied")
            # Replace weak beats with improved versions
            for field in ("hook", "problem", "stakes", "resolution", "lesson"):
                if result.get(field):
                    story[field] = result[field]
        else:
            print("  [QADirector] Story passed QA — no rewrite needed")

        # Attach scores for logging/Telegram preview
        story["qa_scores"] = scores

    except Exception as e:
        print(f"  [QADirector] QA failed: {e} — using original story")

    return story
