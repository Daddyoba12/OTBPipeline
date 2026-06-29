"""
OTB_Pipeline — Hashtag engine  (3-1-1 strategy)

Formula per post:
  #BootHop                    — always (brand anchor)
  3 × topic hashtags          — from the pillar's category pool, 7-day no-repeat rotation
  1 × trending hashtag        — from today's Nigerian/African news, only if brand-safe

For onboarded clients: pass client_config dict with 'niche', 'brand_tag', and optional
'custom_hashtags' list — the engine merges these into the pool automatically.

Output returned as a list of 5 strings, e.g.:
  ["#BootHop", "#TravelCourier", "#NigeriaDiaspora", "#PackageDelivery", "#NigeriaFootball"]
"""

import json, re, sys, time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, DATA

HASHTAG_FILE  = DATA / "trending_hashtags.json"   # today's trending tag cache (1 per day)
USED_LOG      = DATA / "hashtag_used_log.json"     # 7-day per-tag rotation log
LIBRARY_FILE  = DATA / "hashtag_library.json"

_BLOCKED = {
    "sex", "porn", "nude", "xxx", "gambling", "casino", "bet9ja", "sportybet",
    "crypto", "bitcoin", "ponzi", "nft", "drug", "scam",
}

_NEWS_FEEDS = {
    "nigeria": ["https://www.vanguardngr.com/feed/", "https://punchng.com/feed/"],
    "africa":  ["http://feeds.bbci.co.uk/news/world/africa/rss.xml"],
    "global":  ["http://feeds.bbci.co.uk/news/world/rss.xml",
                "http://feeds.bbci.co.uk/news/business/rss.xml"],
}
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OTBBot/1.0)"}


# ── Library loader ─────────────────────────────────────────────────────────────

def _load_library() -> dict:
    try:
        return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── 7-day rotation log ─────────────────────────────────────────────────────────

def _load_used(days: int = 7) -> set:
    """Return set of hashtags used in the last N days."""
    if not USED_LOG.exists():
        return set()
    try:
        log = json.loads(USED_LOG.read_text(encoding="utf-8"))
        cutoff = date.today() - timedelta(days=days)
        return {
            e["tag"] for e in log
            if date.fromisoformat(e.get("date", "2000-01-01")) >= cutoff
        }
    except Exception:
        return set()


def _save_used(tags: list):
    """Append used tags to the 7-day log, pruning entries older than 7 days."""
    try:
        log = json.loads(USED_LOG.read_text(encoding="utf-8")) if USED_LOG.exists() else []
    except Exception:
        log = []
    today_str = str(date.today())
    cutoff = date.today() - timedelta(days=7)
    log = [e for e in log if date.fromisoformat(e.get("date", "2000-01-01")) >= cutoff]
    for tag in tags:
        log.append({"tag": tag, "date": today_str})
    USED_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


# ── Trending tag (1 per day, cached) ─────────────────────────────────────────

def _rss_headlines(url: str, limit: int = 12) -> list:
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
        print(f"  [Hashtags] Feed {url}: {e}")
        return []


def _fetch_news() -> dict:
    out = {"nigeria": [], "africa": [], "global": []}
    for bucket, feeds in _NEWS_FEEDS.items():
        for url in feeds:
            time.sleep(0.3)
            out[bucket].extend(_rss_headlines(url))
        seen, deduped = set(), []
        for t in out[bucket]:
            if t.lower() not in seen:
                seen.add(t.lower())
                deduped.append(t)
        out[bucket] = deduped[:12]
    return out


def _to_hashtag(term: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", term)
    return "#" + "".join(w.capitalize() for w in words) if words else ""


def _get_trending_tag(force: bool = False) -> str:
    """Return one trending hashtag for today, Claude-picked from Nigerian news. Cached per day."""
    today = str(date.today())

    if not force and HASHTAG_FILE.exists():
        try:
            cached = json.loads(HASHTAG_FILE.read_text(encoding="utf-8"))
            if cached.get("date") == today and cached.get("trending"):
                return cached["trending"]
        except Exception:
            pass

    print("  [Hashtags] Fetching news for trending tag...")
    sources = _fetch_news()
    total = sum(len(v) for v in sources.values())

    if total > 0:
        all_terms = (
            [f"[Nigeria] {t}" for t in sources.get("nigeria", [])] +
            [f"[Africa] {t}"  for t in sources.get("africa",  [])] +
            [f"[Global] {t}"  for t in sources.get("global",  [])]
        )
        prompt = (
            "BootHop is a UK-to-Nigeria peer-to-peer parcel delivery service. "
            "Audience: UK-based Nigerian diaspora (25-45), small business owners, travellers.\n\n"
            "From these today's news headlines, pick ONE hashtag that:\n"
            "1. Is brand-safe (no gambling, crypto, violence, explicit content)\n"
            "2. Would resonate with Nigerian diaspora in the UK\n"
            "3. Is genuinely trending — football, music, diaspora, economy, travel are ideal\n"
            "4. Prefer Nigerian/African headlines over global\n\n"
            "Headlines:\n" + "\n".join(all_terms) +
            "\n\nReply with ONLY ONE hashtag in CamelCase with # prefix. Example: #NigeriaVsEngland"
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=20,
                messages=[{"role": "user", "content": prompt}],
            )
            tag = msg.content[0].text.strip().split()[0]
            if tag.startswith("#") and len(tag) > 2 and not any(b in tag.lower() for b in _BLOCKED):
                HASHTAG_FILE.write_text(
                    json.dumps({"date": today, "trending": tag, "sources": {k: v[:3] for k, v in sources.items()}}),
                    encoding="utf-8"
                )
                print(f"  [Hashtags] Trending tag: {tag}")
                return tag
        except Exception as e:
            print(f"  [Hashtags] Claude trending pick failed: {e}")

    # Fallback if news fetch or Claude fails
    fallback = "#DiasporaLife"
    HASHTAG_FILE.write_text(json.dumps({"date": today, "trending": fallback}), encoding="utf-8")
    return fallback


# ── 3-1-1 topic picker ─────────────────────────────────────────────────────────

def _pick_topic_tags(pillar: str, lib: dict, used: set, n: int = 3,
                     client_config: dict = None) -> list:
    """
    Pick N non-recently-used topic hashtags for this pillar.
    client_config can add custom_hashtags and niche overrides.
    """
    pillar_map = lib.get("pillar_map", {})
    all_pillars = lib.get("pillars", {})

    # Determine which category pools to pull from
    categories = pillar_map.get(pillar, ["community", "diaspora"])

    # Build candidate pool from matched categories
    pool = []
    for cat in categories:
        pool.extend(all_pillars.get(cat, []))

    # Inject client's own custom hashtags at the front (priority)
    if client_config:
        custom = client_config.get("custom_hashtags", [])
        pool = [f"#{t.lstrip('#')}" for t in custom] + pool

    # Remove recently used and deduplicate
    seen = set()
    candidates = []
    for tag in pool:
        norm = tag.lower()
        if norm not in used and norm not in seen:
            seen.add(norm)
            candidates.append(tag)

    # If not enough fresh tags, allow reuse from the full pool
    if len(candidates) < n:
        for tag in pool:
            norm = tag.lower()
            if norm not in seen:
                seen.add(norm)
                candidates.append(tag)

    return candidates[:n]


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_today(pillar: str = "community", force: bool = False,
                client_config: dict = None) -> list:
    """
    Return 5 hashtags using 3-1-1 strategy for the given content pillar.

    Args:
        pillar:        content pillar slug (community, airport, smart, etc.)
        force:         re-fetch trending tag even if cached today
        client_config: optional dict for onboarded clients:
                         {
                           "brand_tag":       "#ClientBrand",
                           "custom_hashtags": ["#Niche1", "#Niche2", ...],
                           "niche":           "logistics"
                         }
    Returns:
        list of 5 hashtag strings
    """
    lib  = _load_library()
    used = _load_used(days=7)

    # 1 — brand anchor
    if client_config and client_config.get("brand_tag"):
        brand = f"#{client_config['brand_tag'].lstrip('#')}"
    else:
        brand = "#BootHop"

    # 3 — topic hashtags rotated by pillar
    topic_tags = _pick_topic_tags(pillar, lib, used, n=3, client_config=client_config)

    # 1 — trending tag from today's news
    trending = _get_trending_tag(force=force)

    final = [brand] + topic_tags + [trending]

    # Deduplicate while preserving order (brand always first)
    seen, deduped = set(), []
    for tag in final:
        norm = tag.lower()
        if norm not in seen:
            seen.add(norm)
            deduped.append(tag)

    # Pad to 5 if dedup removed something
    if len(deduped) < 5:
        extras = ["#TravelTok", "#NaijaUK", "#DiasporaMagic", "#AfricanDiaspora", "#TravelLife"]
        for e in extras:
            if e.lower() not in seen and len(deduped) < 5:
                deduped.append(e)

    result = deduped[:5]

    # Save to used log so these won't repeat for 7 days
    _save_used(result[1:4])   # only log the 3 topic tags (brand + trending are always fresh)

    print(f"  [Hashtags] 3-1-1 ({pillar}): {result}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pillar", default="community")
    ap.add_argument("--force",  action="store_true")
    args = ap.parse_args()
    tags = fetch_today(pillar=args.pillar, force=args.force)
    print("Result:", tags)
