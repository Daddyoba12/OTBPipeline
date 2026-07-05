"""
OTB_Pipeline — Reviewer (Stage 6 / Agent 7)

The final quality gate. Reviews the COMPLETE package — story, scenes,
and image prompts together — and scores the full content on 7 dimensions.

Threshold: 90/100. Anything below triggers a targeted rewrite of weak areas.

This is separate from the QA Director (which reviews raw story text at Stage 2).
The Reviewer sees the complete picture: story + scenes + how they connect.

Scores:
  1. Hook virality      — will it stop the scroll in 2 seconds?
  2. Story coherence    — does the full arc make sense start to finish?
  3. Emotional journey  — frustration → relief → inspiration
  4. Visual relevance   — do the scenes actually match the story?
  5. Engagement bait    — will people comment, share, or save?
  6. Brand integration  — is BootHop positioned correctly?
  7. Lesson shareability — will people screenshot or quote the lesson?
"""

import json, re, sys, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, QA_MODEL

PASS_THRESHOLD = 90


def _call_ai(prompt: str) -> str:
    if QA_MODEL == "openai":
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o",
                "max_tokens": 1600,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=40,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    elif QA_MODEL == "gemini":
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 1600, "temperature": 0.4},
            },
            timeout=40,
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
            timeout=40,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in Reviewer response: {raw[:200]}")
    return json.loads(m.group())


def _build_review_prompt(story: dict, pexels_queries: list[str], pillar: str) -> str:
    scenes_text = "\n".join(f"  Scene {i}: {q}" for i, q in enumerate(pexels_queries))

    return f"""You are the Reviewer for BootHop's social media video pipeline. You see the complete content package and score it against 7 dimensions. Threshold for approval is {PASS_THRESHOLD}/100.

COMPLETE CONTENT PACKAGE:
  Pillar: {pillar}
  Hook: {story.get('hook', '')}
  Problem: {story.get('problem', '')}
  Stakes: {story.get('stakes', '')}
  Resolution: {story.get('resolution', '')}
  Lesson: {story.get('lesson', '')}

PLANNED VIDEO SCENES:
{scenes_text}

SCORE EACH DIMENSION 0-10:

1. hook_virality
   - 10: Viewer stops scrolling instantly. Specific person, item, emotion, or number. Under 15 words.
   - 5: Decent hook but slightly generic or too long.
   - 0: Boring, vague, starts with "BootHop", or over 20 words.

2. story_coherence
   - 10: One clear character. Linear logical journey. Hook → Problem → Stakes → Resolution → Lesson all connect perfectly.
   - 5: Story works but has minor gaps or a small jump in logic.
   - 0: Character changes mid-story, two unrelated stories mixed, or scenes contradict the narrative.

3. emotional_journey
   - 10: Viewer feels genuine frustration in Problem, real suspense in Stakes, clear relief in Resolution, and inspiration from Lesson.
   - 5: Some emotion present but could be stronger.
   - 0: Cold, factual, reads like a product description.

4. visual_relevance
   - 10: Every planned scene directly matches the story beat. Scene 0 shows the protagonist, scenes 2-3 show the specific problem, scenes 5-6 show the BootHop solution clearly.
   - 5: Most scenes match but one or two feel disconnected.
   - 0: Random scenes — farm, motorbike, plane when story is about a pharmacy, etc.

5. engagement_potential
   - 10: Viewer will comment their own story, tag a friend, or save the video. Story is universally relatable to UK/Nigeria diaspora.
   - 5: Interesting but not strongly shareable.
   - 0: Niche, irrelevant to the audience, or no emotional reason to engage.

6. brand_integration
   - 10: BootHop appears ONLY in Resolution. Positioned as the smart, peer-to-peer alternative. No courier brand names anywhere.
   - 5: BootHop mentioned but slightly clunky or appears too early.
   - 0: BootHop appears in Hook or Problem, or a courier brand (DHL, FedEx) is named.

7. lesson_shareability
   - 10: One punchy line under 10 words. Viewer will screenshot or quote it. Universal truth.
   - 5: OK lesson but a bit long or generic.
   - 0: Too long, preachy, or weak ending.

OVERALL = (sum of all 7 scores / 7) × 10. Round to nearest integer.

IF OVERALL < {PASS_THRESHOLD}:
  - Identify every weak dimension (score < 8)
  - Rewrite only the weak beats — keep strong beats unchanged
  - The new story must fix ALL identified issues

IF OVERALL >= {PASS_THRESHOLD}:
  - Set rewritten to false
  - Do not change any beats

Return ONLY valid JSON, no markdown:
{{
  "scores": {{
    "hook_virality": 0,
    "story_coherence": 0,
    "emotional_journey": 0,
    "visual_relevance": 0,
    "engagement_potential": 0,
    "brand_integration": 0,
    "lesson_shareability": 0,
    "overall": 0
  }},
  "verdict": "APPROVED or REWRITTEN",
  "issues": ["list of specific problems"],
  "rewritten": false,
  "hook": "unchanged or improved",
  "problem": "unchanged or improved",
  "stakes": "unchanged or improved",
  "resolution": "unchanged or improved",
  "lesson": "unchanged or improved"
}}"""


def final_review(story: dict, photo_result: dict, pillar: str) -> dict:
    """
    Stage 6 — Reviewer: scores the complete content package.
    Rewrites weak beats if overall score < 90.
    Returns the story dict (original or improved) with review_scores attached.
    """
    pexels_queries = photo_result.get("pexels_queries", [])

    try:
        prompt = _build_review_prompt(story, pexels_queries, pillar)
        raw = _call_ai(prompt)
        result = _parse_json(raw)

        scores  = result.get("scores", {})
        overall = scores.get("overall", 0)
        verdict = result.get("verdict", "UNKNOWN")
        issues  = result.get("issues", [])
        rewritten = result.get("rewritten", False)

        print(f"  [Reviewer] Verdict: {verdict} | Score: {overall}/100")
        for dim, score in scores.items():
            if dim != "overall":
                flag = " ⚠" if score < 8 else ""
                print(f"    {dim}: {score}/10{flag}")

        if issues:
            for issue in issues:
                print(f"    Issue: {issue}")

        if rewritten:
            print(f"  [Reviewer] Score {overall} < {PASS_THRESHOLD} — improvements applied")
            for field in ("hook", "problem", "stakes", "resolution", "lesson"):
                if result.get(field):
                    story[field] = result[field]
        else:
            print(f"  [Reviewer] Score {overall} >= {PASS_THRESHOLD} — content approved")

        story["review_scores"] = scores

    except Exception as e:
        print(f"  [Reviewer] Review failed: {e} — passing content as-is")

    return story
