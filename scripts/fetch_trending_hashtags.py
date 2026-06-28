"""
OTB_Pipeline — Daily trending hashtag fetcher

Priority order per run:
  1. Nigeria  — top 10 Google Trends real-time searches
  2. Africa   — Kenya + South Africa trending (combined)
  3. Global   — US + UK trending (worldwide proxy)
  4. Niche    — Claude picks the best subset safe for BootHop's diaspora audience

Output: data/trending_hashtags.json
{
  "date": "2026-06-28",
  "tags": ["#NaijaVibes", "#AfricanBusiness", "#GlobalTrade", "#DiasporaMagic", "#BootHop"],
  "sources": {"nigeria": [...], "africa": [...], "global": [...]}
}

Re-fetches once per day. If Google Trends is blocked/rate-limited, falls back to niche statics.
"""

import json, re, sys, time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, DATA

HASHTAG_FILE = DATA / "trending_hashtags.json"

# Niche fallbacks — used when Google Trends returns nothing or Claude can't pick
_NICHE_FALLBACKS = [
    "#BootHop", "#DiasporaMagic", "#LondonToLagos",
    "#NaijaUK", "#AfricanDiaspora", "#UKNigeria",
]

# Terms we never want as hashtags regardless of trending status
_BLOCKED = {
    "sex", "porn", "nude", "xxx", "gambling", "casino", "bet9ja", "sportybet",
    "crypto", "bitcoin", "ponzi", "nft", "drug", "scam",
}


def _to_hashtag(term: str) -> str:
    """'Burna Boy Concert' -> '#BurnaBoyCouncert'  (drop non-alphanum, TitleCase join)."""
    words = re.findall(r"[A-Za-z0-9]+", term)
    return "#" + "".join(w.capitalize() for w in words) if words else ""


def _clean(terms: list[str]) -> list[str]:
    """Convert terms to valid hashtags and drop blocked ones."""
    out = []
    for t in terms:
        tag = _to_hashtag(t)
        if len(tag) < 3:
            continue
        if any(b in t.lower() for b in _BLOCKED):
            continue
        out.append(tag)
    return out


_NEWS_FEEDS = {
    "nigeria": [
        "https://www.vanguardngr.com/feed/",
        "https://punchng.com/feed/",
    ],
    "africa": [
        "http://feeds.bbci.co.uk/news/world/africa/rss.xml",
    ],
    "global": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "http://feeds.bbci.co.uk/news/business/rss.xml",
    ],
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OTBBot/1.0)"}


def _rss_headlines(url: str, limit: int = 12) -> list[str]:
    """Fetch article headlines from an RSS feed."""
    import xml.etree.ElementTree as ET
    import requests as _req
    try:
        r = _req.get(url, timeout=12, headers=_HEADERS)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        titles = []
        for item in root.iter("item"):
            t = item.findtext("title", "").strip()
            if t and len(t) > 5:
                titles.append(t)
            if len(titles) >= limit:
                break
        return titles
    except Exception as e:
        print(f"  [Hashtags] Feed {url} failed: {e}")
        return []


def _google_trends() -> dict:
    """Pull trending topics from Nigerian + African + Global news RSS feeds."""
    out = {"nigeria": [], "africa": [], "global": []}
    for bucket, feeds in _NEWS_FEEDS.items():
        for url in feeds:
            time.sleep(0.3)
            out[bucket].extend(_rss_headlines(url))
        # deduplicate within bucket
        seen, deduped = set(), []
        for t in out[bucket]:
            tl = t.lower()
            if tl not in seen:
                seen.add(tl)
                deduped.append(t)
        out[bucket] = deduped[:12]
    return out


def _claude_pick(sources: dict) -> list[str]:
    """Ask Claude Haiku to pick 4 trending tags safe and relevant for BootHop's audience."""
    all_terms = (
        [f"[Nigeria] {t}"      for t in sources.get("nigeria", [])] +
        [f"[Africa] {t}"       for t in sources.get("africa",  [])] +
        [f"[Global] {t}"       for t in sources.get("global",  [])]
    )
    if not all_terms:
        return []

    prompt = (
        "BootHop is a UK-to-Nigeria peer-to-peer parcel delivery app. "
        "Our audience is UK-based Nigerian diaspora (25-45 yo), small business owners, "
        "and travellers who earn money by carrying parcels on trips they already planned.\n\n"
        "Below are today's real news headlines from Nigerian and African outlets. "
        "Extract the key topic from each headline and convert to a trending-style hashtag. "
        "Then pick exactly 4 that:\n"
        "1. Are brand-safe (no explicit content, gambling, crypto scams, or violent politics)\n"
        "2. Would resonate with our Nigerian diaspora audience in the UK\n"
        "3. Boost reach if used as hashtags on a logistics/delivery video in 2026\n"
        "4. Prefer Nigeria headlines first, then Africa, then Global\n"
        "5. Topics like football, music, diaspora, economy, travel, business are ideal\n"
        "6. Avoid purely party-political or divisive topics\n\n"
        "Today's headlines:\n"
        + "\n".join(all_terms)
        + "\n\nReply with ONLY 4 hashtags, one per line. "
        "CamelCase the topic, no spaces, include # prefix.\n"
        "Example:\n#AfricanFootball\n#NaijaEconomy\n#DiasporaLife\n#UKNigeriaTravel"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        lines = msg.content[0].text.strip().split("\n")
        tags = []
        for line in lines:
            line = line.strip()
            if line.startswith("#") and len(line) > 2:
                tag = "#" + re.sub(r"\s+", "", line[1:])
                if any(b in tag.lower() for b in _BLOCKED):
                    continue
                tags.append(tag)
        return tags[:4]
    except Exception as e:
        print(f"  [Hashtags] Claude pick failed: {e}")
        return []


def fetch_today(force: bool = False) -> list[str]:
    """
    Return today's 5 trending hashtags (cached per day).
    Order: [Nigeria_trend, Africa_trend, Global_trend, Niche_trend, #BootHop_anchor]
    Falls back to niche statics if Google Trends or Claude fail.
    """
    today = str(date.today())

    # ── cache hit ──────────────────────────────────────────────────────────────
    if not force and HASHTAG_FILE.exists():
        try:
            cached = json.loads(HASHTAG_FILE.read_text(encoding="utf-8"))
            if cached.get("date") == today and len(cached.get("tags", [])) >= 4:
                print(f"  [Hashtags] Cached: {cached['tags']}")
                return cached["tags"]
        except Exception:
            pass

    # ── fetch ──────────────────────────────────────────────────────────────────
    print("  [Hashtags] Fetching Google Trends (Nigeria > Africa > Global)...")
    sources = _google_trends()

    total = sum(len(v) for v in sources.values())
    if total > 0:
        print(f"  [Hashtags] Got {len(sources['nigeria'])} NG / "
              f"{len(sources['africa'])} AF / {len(sources['global'])} GL terms")
        selected = _claude_pick(sources)
    else:
        print("  [Hashtags] Google Trends returned nothing — using niche fallbacks")
        selected = []

    # ── build final 5 ─────────────────────────────────────────────────────────
    # Fill any gaps (Claude gave <4 or Trends failed) with niche fallbacks
    final = list(selected)
    for fb in _NICHE_FALLBACKS:
        if len(final) >= 5:
            break
        if fb not in final:
            final.append(fb)

    final = final[:5]

    # ── save ───────────────────────────────────────────────────────────────────
    HASHTAG_FILE.write_text(
        json.dumps({
            "date": today,
            "tags": final,
            "sources": {k: v[:5] for k, v in sources.items()},
        }, indent=2),
        encoding="utf-8",
    )
    print(f"  [Hashtags] Today's 5 tags: {final}")
    return final


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Fetch today's trending hashtags")
    ap.add_argument("--force", action="store_true", help="Re-fetch even if cached today")
    args = ap.parse_args()
    tags = fetch_today(force=args.force)
    print("Result:", tags)
