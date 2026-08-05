"""
OTB_Pipeline — Trend Scout (Weekly Intelligence)
==================================================
Pulls what's ACTUALLY winning in our niche from three sources:

  YouTube     → Top Shorts by keyword search (YouTube Data API)
  Instagram   → Top posts for our niche hashtags (Graph API)
  TikTok      → AI synthesis via Perplexity (real-time web search)

Then uses GPT-4o-mini to extract patterns: hook openers, winning formats,
visual styles, emotional triggers.

Writes: data/trend_report.json
Exports:
  get_trend_context()       → story AI prompt injection (hook/format trends)
  get_scene_trend_context() → scene planner prompt injection (visual trends)

Run:    python scripts/trend_scout.py
Best scheduled: Monday 05:30 UK (before weekly_review.py at 06:00)
"""

import json, re, sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from config import (
    DATA, CREDS_PATH, YOUTUBE_API_KEY,
    PERPLEXITY_KEY, OPENAI_API_KEY, GEMINI_API_KEY,
)

TREND_REPORT = DATA / "trend_report.json"
REPORT_MAX_AGE_HOURS = 200   # ~8 days; stale beyond this

# ── Niche definition ──────────────────────────────────────────────────────────

YOUTUBE_QUERIES = [
    "uk nigeria delivery cheap 2024",
    "send package nigeria from uk",
    "diaspora delivery hack africa",
    "peer to peer delivery uk earn money",
    "cheap courier nigeria",
    "african diaspora uk send parcel",
]

INSTAGRAM_HASHTAGS = [
    "uknigeriadelivery",
    "africandiaspora",
    "naijainuk",
    "diasporadelivery",
    "ukafricandelivery",
    "sendpackagenigeria",
    "nigeriansinuk",
]

NICHE_DESCRIPTION = (
    "UK-Nigeria peer-to-peer delivery service for the African diaspora. "
    "Content angle: travellers already flying UK↔Nigeria carry parcels and earn money (Booters); "
    "senders avoid expensive couriers by using trusted travellers (Hoopers). "
    "Pillars: cost savings, community trust, airport logistics, urgent medical, cultural gifts, "
    "earning as a traveller. Target: Nigerians and West Africans living in the UK."
)


# ── Credential loader ─────────────────────────────────────────────────────────

def _ig_creds() -> tuple[str, str]:
    try:
        c = json.loads(Path(CREDS_PATH).read_text(encoding="utf-8")).get("instagram", {})
        return c.get("access_token", ""), c.get("ig_user_id", "")
    except Exception:
        return "", ""


# ── YouTube — top Shorts in niche ─────────────────────────────────────────────

def _scout_youtube() -> list[dict]:
    api_key = YOUTUBE_API_KEY
    if not api_key:
        print("  [TrendScout/YouTube] No API key — skipping")
        return []

    raw_videos: list[dict] = []
    for query in YOUTUBE_QUERIES:
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "key":            api_key,
                    "q":              query,
                    "type":           "video",
                    "videoDuration":  "short",
                    "order":          "viewCount",
                    "maxResults":     8,
                    "part":           "snippet",
                    "publishedAfter": (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("items", []):
                raw_videos.append({
                    "id":          item["id"].get("videoId", ""),
                    "title":       item["snippet"].get("title", ""),
                    "channel":     item["snippet"].get("channelTitle", ""),
                    "description": item["snippet"].get("description", "")[:200],
                    "query":       query,
                })
        except Exception as e:
            print(f"  [TrendScout/YouTube] '{query}': {e}")

    if not raw_videos:
        return []

    # Enrich with view counts (batch, 50 at a time)
    ids = [v["id"] for v in raw_videos if v["id"]]
    stats: dict[str, int] = {}
    for start in range(0, len(ids), 50):
        chunk = ",".join(ids[start:start + 50])
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "key":    api_key,
                    "id":     chunk,
                    "part":   "statistics",
                    "fields": "items(id,statistics(viewCount))",
                },
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("items", []):
                stats[item["id"]] = int(item["statistics"].get("viewCount", 0))
        except Exception as e:
            print(f"  [TrendScout/YouTube] Stats batch error: {e}")

    for v in raw_videos:
        v["views"] = stats.get(v["id"], 0)

    top = sorted(raw_videos, key=lambda x: x["views"], reverse=True)[:20]
    print(f"  [TrendScout/YouTube] {len(top)} top videos found, "
          f"top views: {top[0]['views']:,}" if top else "  [TrendScout/YouTube] No videos")
    return top


# ── Instagram — top posts for niche hashtags ──────────────────────────────────

def _scout_instagram() -> list[dict]:
    token, user_id = _ig_creds()
    if not token or not user_id:
        print("  [TrendScout/Instagram] No credentials — skipping")
        return []

    results: list[dict] = []
    for tag in INSTAGRAM_HASHTAGS:
        try:
            # Step 1: get hashtag ID
            r = requests.get(
                "https://graph.facebook.com/v18.0/ig-hashtag-search",
                params={"user_id": user_id, "q": tag, "access_token": token},
                timeout=15,
            )
            if not r.ok:
                continue
            hashtag_id = r.json().get("data", [{}])[0].get("id", "")
            if not hashtag_id:
                continue

            # Step 2: get top media for this hashtag
            r2 = requests.get(
                f"https://graph.facebook.com/v18.0/{hashtag_id}/top_media",
                params={
                    "user_id":      user_id,
                    "access_token": token,
                    "fields":       "id,media_type,timestamp,caption,like_count,comments_count",
                    "limit":        8,
                },
                timeout=15,
            )
            if not r2.ok:
                continue
            for post in r2.json().get("data", []):
                caption = post.get("caption", "") or ""
                results.append({
                    "hashtag":   tag,
                    "media_id":  post.get("id", ""),
                    "caption":   caption[:300],
                    "likes":     int(post.get("like_count",     0)),
                    "comments":  int(post.get("comments_count", 0)),
                    "type":      post.get("media_type", ""),
                })
        except Exception as e:
            print(f"  [TrendScout/Instagram] #{tag}: {e}")

    top = sorted(results, key=lambda x: x["likes"] + x["comments"] * 3, reverse=True)[:20]
    print(f"  [TrendScout/Instagram] {len(top)} top posts across {len(INSTAGRAM_HASHTAGS)} hashtags")
    return top


# ── TikTok — Perplexity AI synthesis ─────────────────────────────────────────

def _scout_tiktok_via_perplexity() -> str:
    if not PERPLEXITY_KEY:
        print("  [TrendScout/TikTok] No Perplexity key — skipping")
        return ""

    prompt = f"""You are a TikTok trend analyst. Search TikTok right now and tell me:

NICHE: {NICHE_DESCRIPTION}

I need specific, actionable intelligence (not generic advice):

1. What are the TOP 8 hook formats (first 3-5 seconds) that are getting the most views in 2025-2026 for UK diaspora / African community / delivery / travel content on TikTok? Give me the EXACT opening words or patterns, e.g. "POV: You just found out...", "Nobody told me that...", etc.

2. What VIDEO FORMAT is winning right now — text-card openers, close-up face reaction, voiceover-only, split screen, storytime walking, etc.? Which is getting the most views for small creator accounts?

3. What EMOTIONAL TRIGGERS in hooks are getting the highest retention? e.g. price shock, community pride, FOMO, relatability, aspiration?

4. What VISUAL STYLES are trending for this audience? e.g. dark moody with text, bright candid phone-camera, text-heavy cards, dramatic slow-mo face close-ups?

5. Any SPECIFIC accounts or video examples in the UK-Nigeria / African diaspora space that are growing fast right now — what are they doing right?

Give me real, specific, current intelligence. Today's date: {datetime.now().strftime('%B %Y')}."""

    try:
        r = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":    "sonar-pro",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1200,
            },
            timeout=40,
        )
        r.raise_for_status()
        result = r.json()["choices"][0]["message"]["content"]
        print(f"  [TrendScout/TikTok] Perplexity synthesis: {len(result)} chars")
        return result
    except Exception as e:
        print(f"  [TrendScout/TikTok] Perplexity error: {e}")
        return ""


# ── Pattern extraction — GPT-4o-mini ─────────────────────────────────────────

def _extract_patterns(yt_videos: list[dict], ig_posts: list[dict], tiktok_synthesis: str) -> dict:
    if not OPENAI_API_KEY:
        print("  [TrendScout/Patterns] No OpenAI key — using raw data only")
        return _fallback_patterns(yt_videos, ig_posts)

    yt_titles = [f"• {v['title']} ({v['views']:,} views)" for v in yt_videos[:15]]
    ig_captions = [f"• {p['caption'][:120]} (❤️{p['likes']})" for p in ig_posts[:15] if p.get("caption")]

    prompt = f"""You are a viral content strategist analysing top-performing social media posts.

CONTEXT — Brand niche: {NICHE_DESCRIPTION}

TOP YOUTUBE SHORTS IN THIS NICHE (last 90 days):
{chr(10).join(yt_titles) if yt_titles else "No YouTube data this week"}

TOP INSTAGRAM POSTS IN THIS NICHE:
{chr(10).join(ig_captions) if ig_captions else "No Instagram data this week"}

TIKTOK TREND INTELLIGENCE (from live web search):
{tiktok_synthesis[:800] if tiktok_synthesis else "No TikTok data this week"}

Extract and return as JSON ONLY (no markdown):
{{
  "top_10_hook_patterns": [
    "exact hook opener or format e.g. 'POV: you just found...'",
    "another pattern e.g. 'Nobody told me that...'",
    ... (10 total — mix question hooks, POV, statement, emotion)
  ],
  "winning_formats": [
    "text-card opener with face reveal",
    "close-up face reaction + voiceover",
    ... (5 total — most effective for small/mid accounts)
  ],
  "visual_styles": [
    "dark navy card large yellow text",
    "extreme close-up shocked face phone screen",
    ... (5 total — what's actually being clicked right now)
  ],
  "emotional_triggers": [
    "price shock — viewer doesn't expect the low price",
    "community pride — shared experience of diaspora",
    ... (5 total)
  ],
  "recommended_this_week": "One sentence — the single most impactful change to make to our hook/format this week based on all evidence above"
}}"""

    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 800, "temperature": 0.3},
            },
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            patterns = json.loads(m.group())
            print(f"  [TrendScout/Patterns] Extracted {len(patterns.get('top_10_hook_patterns', []))} hook patterns")
            return patterns
    except Exception as e:
        print(f"  [TrendScout/Patterns] Gemini error: {e}")

    return _fallback_patterns(yt_videos, ig_posts)


def _fallback_patterns(yt_videos: list[dict], ig_posts: list[dict]) -> dict:
    """Extract basic patterns from raw data without AI if keys missing."""
    titles = [v["title"] for v in yt_videos[:10]]
    hooks = []
    for t in titles:
        words = t.split()
        if len(words) >= 4:
            hooks.append(" ".join(words[:5]))
    return {
        "top_10_hook_patterns":  hooks[:10] or ["POV: you just found a cheaper way", "Nobody told me this existed"],
        "winning_formats":       ["close-up face reaction", "text-card opener", "voiceover storytime"],
        "visual_styles":         ["extreme close-up shocked face", "dark card large text", "candid phone camera"],
        "emotional_triggers":    ["price shock", "community pride", "FOMO"],
        "recommended_this_week": "Use a close-up face reaction as the hook visual with a POV question overlay.",
    }


# ── Write report ──────────────────────────────────────────────────────────────

def _write_report(yt_videos, ig_posts, tiktok_raw, patterns) -> dict:
    report = {
        "generated_at": datetime.now().isoformat(),
        "week":         datetime.now().strftime("%Y-W%W"),
        "youtube": {
            "top_videos": [
                {k: v for k, v in vid.items() if k != "description"}
                for vid in yt_videos[:10]
            ],
            "hook_openers": list({v["title"].split()[0] for v in yt_videos if v["title"]}),
            "avg_views":    round(sum(v["views"] for v in yt_videos) / len(yt_videos)) if yt_videos else 0,
        },
        "instagram": {
            "top_posts": ig_posts[:10],
            "top_hashtags": list({p["hashtag"] for p in ig_posts}),
        },
        "tiktok": {
            "ai_synthesis": tiktok_raw[:1500] if tiktok_raw else "",
        },
        "combined": patterns,
    }

    TREND_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  [TrendScout] Report written → {TREND_REPORT.name}")
    return report


# ── Public API — used by generate_content.py and scene_planner.py ─────────────

def get_trend_context() -> str:
    """
    Returns a formatted trend brief for injection into the story AI prompt.
    Empty string if report is missing or stale (> 8 days).
    """
    if not TREND_REPORT.exists():
        return ""
    try:
        report = json.loads(TREND_REPORT.read_text(encoding="utf-8"))
        age_h  = (datetime.now() - datetime.fromisoformat(report["generated_at"])).total_seconds() / 3600
        if age_h > REPORT_MAX_AGE_HOURS:
            return ""
        c     = report.get("combined", {})
        hooks = c.get("top_10_hook_patterns", [])
        fmts  = c.get("winning_formats", [])
        trigs = c.get("emotional_triggers", [])
        rec   = c.get("recommended_this_week", "")
        if not hooks:
            return ""

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "TREND INTELLIGENCE — WHAT'S WINNING IN YOUR NICHE THIS WEEK",
            f"(Sourced from YouTube Shorts, Instagram, TikTok — {report.get('week', '')})",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "Top hook patterns performing well right now:",
        ]
        for h in hooks[:7]:
            lines.append(f'  • "{h}"')
        if fmts:
            lines.append("\nWinning video formats:")
            for f in fmts[:4]:
                lines.append(f"  • {f}")
        if trigs:
            lines.append("\nEmotional triggers driving shares:")
            for t in trigs[:3]:
                lines.append(f"  • {t}")
        if rec:
            lines.append(f"\nKey recommendation this week: {rec}")
        lines.append("")
        lines.append("Use these as inspiration — your hook should feel native to these patterns, not copied.")
        return "\n".join(lines)
    except Exception:
        return ""


def get_scene_trend_context() -> str:
    """
    Returns visual style trends formatted for the scene planner prompt.
    Empty string if report is missing or stale.
    """
    if not TREND_REPORT.exists():
        return ""
    try:
        report = json.loads(TREND_REPORT.read_text(encoding="utf-8"))
        age_h  = (datetime.now() - datetime.fromisoformat(report["generated_at"])).total_seconds() / 3600
        if age_h > REPORT_MAX_AGE_HOURS:
            return ""
        c       = report.get("combined", {})
        visuals = c.get("visual_styles", [])
        fmts    = c.get("winning_formats", [])
        if not visuals and not fmts:
            return ""
        lines = ["TRENDING VISUAL STYLES (use to inform scene queries where it fits):"]
        for v in visuals[:4]:
            lines.append(f"  • {v}")
        if fmts:
            lines.append("Winning formats for hook scenes (scenes 0-1 especially):")
            for f in fmts[:3]:
                lines.append(f"  • {f}")
        return "\n".join(lines)
    except Exception:
        return ""


# ── Entry point ───────────────────────────────────────────────────────────────

def run_scout() -> dict:
    print(f"\n{'='*60}")
    print(f"  OTB TREND SCOUT")
    print(f"  {datetime.now():%Y-%m-%d %H:%M}   |   Scanning what's winning in your niche")
    print(f"{'='*60}\n")

    print("[YouTube] Searching top Shorts in niche...")
    yt = _scout_youtube()

    print("\n[Instagram] Scanning niche hashtags...")
    ig = _scout_instagram()

    print("\n[TikTok] Perplexity AI trend synthesis...")
    tt = _scout_tiktok_via_perplexity()

    print("\n[Patterns] GPT-4o-mini pattern extraction...")
    patterns = _extract_patterns(yt, ig, tt)

    report = _write_report(yt, ig, tt, patterns)

    # Print summary
    c = patterns
    print(f"\n{'='*60}")
    print("  TREND SUMMARY")
    print(f"{'='*60}")
    print("\nTop hook patterns this week:")
    for h in c.get("top_10_hook_patterns", [])[:5]:
        print(f"  • {h}")
    print(f"\nKey recommendation: {c.get('recommended_this_week', 'N/A')}")
    print(f"\n  Full report → {TREND_REPORT.name}")

    return report


if __name__ == "__main__":
    run_scout()
