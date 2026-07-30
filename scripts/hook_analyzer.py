"""
OTB_Pipeline — Hook Analyzer
Runs weekly (triggered automatically by slot 1). Reads the top-scoring hooks
from memory.json, asks Claude to extract what psychological patterns and
structures make them work, then saves those insights to data/hook_patterns.json.

generate_content.py reads hook_patterns.json and injects the findings into
the Story Writer prompt so every new script benefits from what's already worked.

Works for any niche — the analysis is based purely on YOUR data, not hardcoded rules.
"""

import json, sys, requests
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA, ANTHROPIC_API_KEY

HOOK_PATTERNS_FILE     = DATA / "hook_patterns.json"
HOOK_ANALYSIS_LOG      = DATA / "hook_analysis_log.json"
MEMORY_FILE            = DATA / "memory.json"

ANALYSIS_INTERVAL_DAYS = 7
MIN_HOOKS_NEEDED       = 5
TOP_N_HOOKS            = 30


# ── Run-gate ──────────────────────────────────────────────────────────────────

def _should_run() -> bool:
    """Return True if 7+ days have passed since the last successful run."""
    if not HOOK_ANALYSIS_LOG.exists():
        return True
    try:
        log = json.loads(HOOK_ANALYSIS_LOG.read_text(encoding="utf-8"))
        last = date.fromisoformat(log.get("last_run", "2000-01-01"))
        return (date.today() - last).days >= ANALYSIS_INTERVAL_DAYS
    except Exception:
        return True


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_top_hooks(n: int = TOP_N_HOOKS) -> list:
    """Return up to n top-scoring hooks from memory.json."""
    if not MEMORY_FILE.exists():
        return []
    try:
        entries = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    scored = []
    for e in entries:
        hook = (e.get("hook") or "").strip()
        if not hook or len(hook) < 10:
            continue
        qa = e.get("qa_scores") or {}
        rv = e.get("review_scores") or {}
        # Composite score: hook_strength (QA) + hook_virality + engagement_potential (Reviewer)
        hook_score = (
            qa.get("hook_strength", 0) * 10
            + rv.get("hook_virality", 0) * 10
            + rv.get("engagement_potential", 0) * 10
        )
        scored.append({
            "hook":   hook,
            "pillar": e.get("pillar", ""),
            "score":  hook_score,
            "date":   e.get("date", ""),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:n]


# ── Claude call ───────────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":           ANTHROPIC_API_KEY,
            "anthropic-version":   "2023-06-01",
            "content-type":        "application/json",
        },
        json={
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 1800,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_prompt(hooks: list, brand_context: str = "") -> str:
    hook_lines = "\n".join(
        f"{i+1}. [{h['pillar']}] {h['hook']}"
        for i, h in enumerate(hooks)
    )
    brand_note = f"\nBrand context: {brand_context}" if brand_context else ""
    return f"""You are a viral short-form video strategist.{brand_note}

Below are the {len(hooks)} highest-scoring hooks from this brand's content library,
ranked by internal quality scores (hook strength + virality potential + engagement potential).

HOOKS:
{hook_lines}

Analyse these hooks and return a JSON object with this exact structure — no other text:
{{
  "top_patterns": [
    {{
      "trigger": "one of: fear | urgency | ego | surprise | desire | curiosity | empathy",
      "structure": "reusable sentence template, e.g. 'Would you [verb] a stranger with [possessive] [noun]?'",
      "why_it_works": "1-2 sentences on the psychological mechanism behind this pattern",
      "strength_score": 1-10
    }}
  ],
  "avoid": [
    "pattern or phrase that appears weak or overused in this set — keep list to max 5 items"
  ],
  "suggested_hooks": [
    "5 brand-new hook examples using the top patterns — must be original, not copies of the input hooks"
  ],
  "summary": "2-sentence insight: what makes hooks land in this niche and what the brand should double down on"
}}

Return ONLY the JSON object. No markdown fences, no explanation."""


# ── Main public API ───────────────────────────────────────────────────────────

def analyze_and_save(brand_context: str = "", force: bool = False) -> dict | None:
    """
    Run weekly hook analysis and save results to data/hook_patterns.json.
    Returns the patterns dict on success, None if skipped or failed.

    brand_context: optional short description of the brand/niche to guide analysis.
                   Auto-populated with generic BootHop context if blank.
    force:         skip the 7-day gate and run immediately.
    """
    if not force and not _should_run():
        print("[HookAnalyzer] Already ran this week — skipping.")
        return None

    if not brand_context:
        brand_context = (
            "BootHop — peer-to-peer parcel delivery between UK and Nigeria "
            "via travellers already making the journey. TikTok + Instagram Reels."
        )

    hooks = _load_top_hooks()
    if len(hooks) < MIN_HOOKS_NEEDED:
        print(f"[HookAnalyzer] Only {len(hooks)} hooks in memory (need {MIN_HOOKS_NEEDED}) — skipping.")
        return None

    print(f"[HookAnalyzer] Analysing top {len(hooks)} hooks via Claude Haiku...")
    try:
        raw = _call_claude(_build_prompt(hooks, brand_context))
        # Strip markdown fences if model adds them
        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        patterns = json.loads(raw)
    except Exception as e:
        print(f"[HookAnalyzer] Failed: {e}")
        return None

    output = {
        "last_updated":    date.today().isoformat(),
        "hooks_analysed":  len(hooks),
        "brand_context":   brand_context,
        **patterns,
    }
    HOOK_PATTERNS_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    HOOK_ANALYSIS_LOG.write_text(
        json.dumps({"last_run": date.today().isoformat(), "hooks_analysed": len(hooks)}),
        encoding="utf-8",
    )

    count = len(patterns.get("top_patterns", []))
    print(f"[HookAnalyzer] Done — {count} patterns extracted and saved to hook_patterns.json")
    return output


def load_patterns() -> dict | None:
    """
    Load saved hook patterns if they are fresh (updated within the last 7 days).
    Returns None if the file doesn't exist or is stale.
    Called by generate_content._build_story_prompt() on every run.
    """
    if not HOOK_PATTERNS_FILE.exists():
        return None
    try:
        data = json.loads(HOOK_PATTERNS_FILE.read_text(encoding="utf-8"))
        last = date.fromisoformat(data.get("last_updated", "2000-01-01"))
        if (date.today() - last).days > ANALYSIS_INTERVAL_DAYS:
            return None
        return data
    except Exception:
        return None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Run weekly hook analysis")
    p.add_argument("--force", action="store_true", help="Ignore 7-day gate and run now")
    p.add_argument("--brand", default="", help="Short brand/niche description for Claude")
    args = p.parse_args()
    result = analyze_and_save(brand_context=args.brand, force=args.force)
    if result:
        print("\n── Top patterns ─────────────────────────────────")
        for pt in result.get("top_patterns", []):
            print(f"  [{pt['trigger'].upper()}] {pt['structure']} (score: {pt['strength_score']}/10)")
        print("\n── Suggested new hooks ──────────────────────────")
        for h in result.get("suggested_hooks", []):
            print(f"  • {h}")
        print(f"\n── Summary ──────────────────────────────────────\n  {result.get('summary', '')}")
