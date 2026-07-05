"""
OTB_Pipeline — News Editor (Agent 1)

Searches the web every morning using Perplexity's sonar model for today's
most relevant stories across 13+ categories that matter to BootHop's audience
(UK/Nigeria diaspora, parcel delivery, travel, logistics).

Each story is scored 0-100 on BootHop relevance.
Only stories scoring >= 90 are passed to the Story Writer.
If nothing hits the threshold, returns None and Story Writer works from
its own knowledge base.

Categories searched:
  - Cheapest London → Lagos / Lagos → London flights
  - UK airport disruptions (Heathrow, Gatwick, Stansted)
  - Nigeria customs rule changes
  - UK visa / immigration news affecting diaspora
  - Parcel & courier price changes (UK → Nigeria)
  - Airline baggage policy changes
  - Diaspora remittance / money transfer news
  - UK cost of living updates (diaspora spending)
  - Nigeria inflation / naira news
  - Last-mile delivery disruptions Nigeria
  - Viral travel / logistics stories (UK/Africa)
  - Supply chain disruptions affecting UK-Nigeria trade
  - UK-Nigeria business / trade news
"""

import json, re, sys, requests
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import PERPLEXITY_KEY

RELEVANCE_THRESHOLD = 90
_MODEL = "sonar"  # Perplexity sonar = real-time web search

# Topics grouped by BootHop content pillar
PILLAR_TOPICS = {
    "airport": [
        "Heathrow Gatwick Stansted airport disruption cancellations today UK",
        "London Lagos Lagos London flight cheapest price today",
        "Nigerian airline news today",
    ],
    "family": [
        "UK Nigeria parcel delivery price news today",
        "courier service UK to Nigeria cost changes",
        "UK Nigerian diaspora family news today",
    ],
    "smart": [
        "cheapest flights London Lagos today {month}",
        "UK Nigeria travel deals today",
        "airline baggage allowance changes UK Nigeria",
    ],
    "travel_hacks": [
        "UK Nigeria travel tips news today",
        "Nigeria UK airport customs tips today",
        "hand luggage rules changes UK airlines today",
    ],
    "community": [
        "Nigerian community UK news today",
        "UK Nigerian diaspora news this week",
        "UK Nigeria remittance transfer news today",
    ],
    "logistics_stories": [
        "logistics supply chain disruption UK Nigeria today",
        "last-mile delivery Nigeria news today",
        "courier industry UK news today",
    ],
    "airport_deliveries": [
        "Nigeria customs rules changes today",
        "UK to Nigeria parcel seized customs news",
        "Nigerian airports cargo news today",
    ],
    "supply_chain": [
        "UK Nigeria trade supply chain news today",
        "Nigeria import export news today",
        "Africa UK trade disruption news today",
    ],
}

# Generic fallback if pillar has no specific topics
_DEFAULT_TOPICS = [
    "UK Nigeria travel news today",
    "London Lagos cheapest flight today",
    "Nigerian diaspora UK news today",
]


def _search(query: str) -> str:
    """Single Perplexity search call — returns raw response text."""
    resp = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {PERPLEXITY_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": _MODEL,
            "messages": [{"role": "user", "content": query}],
            "max_tokens": 600,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _score_stories(stories_text: str, pillar: str) -> list[dict]:
    """
    Send the raw Perplexity results to Claude/GPT for structured extraction
    and relevance scoring. Returns list of scored story dicts.
    """
    prompt = f"""You are the News Editor for BootHop — a UK/Nigeria peer-to-peer parcel delivery app.

Today is {date.today().isoformat()}.
Content pillar: {pillar}

Below are news summaries from the web. Extract every CONCRETE, VERIFIABLE story that is relevant to BootHop's audience (UK/Nigeria diaspora, travel, parcel delivery, logistics). For each story score it 0-100 on BootHop relevance:

SCORING GUIDE:
- 90-100: Breaking news directly about UK-Nigeria travel, parcel prices, airport disruptions, customs rules, flight prices — audience will IMMEDIATELY relate to it. Story Writer can use this as the basis for today's video.
- 70-89: Useful background (logistics trends, airline news, diaspora updates) — gives context but not urgent.
- Below 70: Too generic, not specific enough, or unrelated.

RAW NEWS TEXT:
{stories_text[:3000]}

Return ONLY valid JSON — a list of stories, sorted by relevance descending:
[
  {{
    "headline": "One sentence summary of the story",
    "summary": "2-3 sentences with the key facts and numbers",
    "category": "flights | customs | courier | diaspora | logistics | travel | other",
    "country_focus": "UK | Nigeria | Both",
    "relevance_score": 0,
    "why_relevant": "One sentence explaining why BootHop audience cares",
    "story_angle": "Suggested BootHop content angle — how could this story become a video?"
  }}
]
If no stories are worth extracting, return []."""

    try:
        from config import OPENAI_API_KEY, ANTHROPIC_API_KEY, QA_MODEL

        if QA_MODEL == "openai":
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o",
                    "max_tokens": 900,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
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
                    "max_tokens": 900,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"]

        m = re.search(r"\[[\s\S]*\]", raw)
        if m:
            return json.loads(m.group())
        return []

    except Exception as e:
        print(f"  [NewsEditor] Scoring failed: {e}")
        return []


def find_top_story(pillar: str) -> dict | None:
    """
    Main entry point. Searches Perplexity for today's top relevant news
    for the given pillar. Returns a single story dict if relevance >= 90,
    otherwise returns None.

    The returned dict is passed as `news_context` to the Story Writer prompt
    so it can anchor the script to a real event.

    Returns dict with keys:
      headline, summary, category, country_focus,
      relevance_score, why_relevant, story_angle
    Or None if no high-relevance story found.
    """
    if not PERPLEXITY_KEY or not PERPLEXITY_KEY.startswith("pplx-"):
        print("  [NewsEditor] No Perplexity key — skipping news search")
        return None

    today_month = date.today().strftime("%B %Y")
    topics = PILLAR_TOPICS.get(pillar, _DEFAULT_TOPICS)

    print(f"  [NewsEditor] Searching {len(topics)} topics for pillar '{pillar}'...")

    combined_text = ""
    for topic in topics:
        query = topic.replace("{month}", today_month)
        try:
            result = _search(query)
            combined_text += f"\n\n--- SEARCH: {query} ---\n{result}"
        except Exception as e:
            print(f"  [NewsEditor] Search failed for '{query}': {e}")

    if not combined_text.strip():
        print("  [NewsEditor] No search results — Story Writer will use AI knowledge")
        return None

    stories = _score_stories(combined_text, pillar)

    if not stories:
        print("  [NewsEditor] No stories extracted")
        return None

    top = stories[0]
    score = top.get("relevance_score", 0)

    print(f"  [NewsEditor] Top story score: {score}/100")
    print(f"  [NewsEditor] Headline: {top.get('headline', '')[:80]}")

    if score < RELEVANCE_THRESHOLD:
        print(f"  [NewsEditor] Score {score} < {RELEVANCE_THRESHOLD} — Story Writer uses AI knowledge")
        return None

    print(f"  [NewsEditor] Story approved ({score}/100) — passing to Story Writer")
    return top


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run News Editor standalone")
    parser.add_argument("--pillar", default="airport", help="Content pillar to search")
    args = parser.parse_args()

    story = find_top_story(args.pillar)
    if story:
        print("\n=== TOP STORY ===")
        print(json.dumps(story, indent=2))
    else:
        print("\nNo high-relevance story found today — Story Writer will create from knowledge")
