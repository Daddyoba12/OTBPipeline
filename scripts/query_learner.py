"""
OTB_Pipeline — Query Bank Auto-Learner

The transport query bank is a living database. Every slot run teaches it something new.

HOW IT LEARNS:
1. SEED       — 71 curated transport queries defined here (starting point, always protected)
2. TRIAL      — any novel Claude query that passes the banned-term filter gets added here.
                Trials are used but flagged as unproven.
3. PROMOTE    — trial query gets 2+ real VIDEO hits (not photo fallback) -> status: "active"
                Active queries join the main rotation pool.
4. DEMOTE     — active query has < 25% video hit rate over 5+ uses -> status: "weak"
                Weak queries are removed from the fallback pool (they keep returning photos
                instead of video clips, wasting render time).
5. ARCHIVE    — weak query gets 10+ uses with no improvement -> status: "archived"
                Never used again.
6. WEEKLY REFRESH — every 7 days, Claude is asked for 20 new transport queries
                    (5 per beat role). Novel ones are added as trial automatically.

DATA FILES:
  data/query_bank.json    — the live growing bank (seed + trial + active + weak)
  data/query_hits.json    — per-query hit log (video/photo/placeholder + date)
  data/query_refresh.json — timestamp of last Claude weekly refresh
"""

import json, random, re
from datetime import date, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA, ANTHROPIC_API_KEY

import requests

BANK_FILE    = DATA / "query_bank.json"
HITS_FILE    = DATA / "query_hits.json"
REFRESH_FILE = DATA / "query_refresh.json"

# Minimum video hits before trial -> active
PROMOTE_THRESHOLD = 2
# Max video hit rate before demotion (active -> weak)
DEMOTE_MIN_USES = 5
DEMOTE_MAX_RATE = 0.25  # less than 25% video hits = weak
# Uses after which a weak query is archived
ARCHIVE_THRESHOLD = 10

BEAT_ROLES = ["hook", "problem", "stakes", "resolution", "lesson_pre"]

BANNED_TERMS = {
    "animal","animals","dog","dogs","cat","cats","horse","horses","pet","pets",
    "puppy","puppies","kitten","kittens","bird","birds","lion","tiger","elephant",
    "monkey","fish","rabbit","wildlife","farm","zoo","livestock","parrot",
    "sheep","cow","goat","duck","chicken","pig","hamster","turtle","snake","insect",
    "food","food delivery","uber eats","ubereats","deliveroo","just eat","doordash",
    "grubhub","restaurant","takeaway","takeout","pizza delivery","meal delivery",
    "grocery delivery","grocery","meal","cooking","chef","kitchen","cafe","diner",
    "burger","bakery","supermarket","fast food","dining","breakfast",
    "christmas","xmas","santa","reindeer","baubles","nativity","tinsel","advent",
    "carol","festive","halloween","pumpkin","easter","thanksgiving","fireworks",
    "new year party","valentine","bonfire",
    "handshake","trophy","medal","piggy bank","cartoon","illustration",
}

# ── Seed transport query bank — 71 curated queries by beat role ───────────────
# This is the single source of truth for the starting bank.
# generate_content.py and render_video.py import from here — never define it elsewhere.
TRANSPORT_QUERIES = {
    "hook": [
        "airplane takeoff runway sunrise",
        "london black cab night city",
        "heathrow airport departure gate",
        "train departing station platform",
        "cargo plane loading airport freight",
        "taxi cab london street rain",
        "eurostar train platform london",
        "airport runway plane taxiing",
        "ocean cargo ship harbour port",
        "london underground tube commuter",
        "gatwick airport departure lounge",
        "commercial aircraft boarding passengers",
        "night flight airplane window city lights",
        "container ship open sea horizon",
        "black cab picking up passenger london",
    ],
    "problem": [
        "airport queue long waiting customs",
        "stressed traveller missed flight gate",
        "heavy suitcase luggage overweight check",
        "airport customs officer inspection",
        "delayed flight departure board",
        "commuter waiting train platform stressed",
        "crowded airport terminal busy",
        "immigration passport queue airport",
        "overweight baggage airline counter",
        "man woman stressing airport phone",
        "missed train station platform run",
        "taxi waiting traffic jam city",
        "cargo delay shipping port container",
        "person rushing airport escalator",
        "train delay announcement platform",
    ],
    "stakes": [
        "woman phone call airport emotional",
        "family farewell airport departure terminal",
        "man sitting airport gate alone",
        "traveller looking at passport nervous",
        "person hugging goodbye airport",
        "young woman crying airport goodbye",
        "professional traveller briefcase airport",
        "african man airport departure lounge",
        "diaspora traveller london heathrow",
        "woman waiting taxi night rain",
        "man at train window thinking",
        "business traveller boarding plane",
    ],
    "resolution": [
        "parcel package handover smiling",
        "luggage claim belt passengers happy",
        "traveller delivery doorstep smile",
        "taxi arriving destination passenger happy",
        "plane landing runway arrival",
        "package delivered door receiver happy",
        "train arrival platform people smiling",
        "cargo ship docking port workers",
        "traveller handing parcel airport",
        "person receiving package doorstep",
        "woman opening delivery box happy",
        "successful flight arrival terminal",
        "freight unloading truck warehouse",
        "passenger taxi arrival smiling",
    ],
    "lesson_pre": [
        "professional business person london city",
        "confident woman airport professional",
        "london skyline cityscape evening",
        "lagos nigeria city skyline aerial",
        "black cab london professional driver",
        "business traveller lounge airport",
        "cargo ship horizon open ocean",
        "london bridge city professional",
        "entrepreneur phone london street",
        "freight terminal logistics professional",
        "airline pilot cockpit professional",
        "train passenger business class working",
        "london heathrow terminal modern",
        "shipping container port aerial view",
        "professional driver london street night",
    ],
}

# Flat list of every seed query (used as absolute last-resort fallback)
ALL_TRANSPORT = [q for pool in TRANSPORT_QUERIES.values() for q in pool]


def _norm(q: str) -> str:
    return q.strip().lower()


def _is_banned(q: str) -> bool:
    n = _norm(q)
    return any(term in n for term in BANNED_TERMS)


# ── Bank I/O ──────────────────────────────────────────────────────────────────

def load_bank() -> list[dict]:
    """Load the full query bank from disk. Returns list of entry dicts."""
    if not BANK_FILE.exists():
        return []
    try:
        return json.loads(BANK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_bank(bank: list[dict]):
    DATA.mkdir(exist_ok=True)
    BANK_FILE.write_text(json.dumps(bank, indent=2), encoding="utf-8")


def get_bank_set() -> set:
    """Return set of all query strings currently in the bank (normalised)."""
    return {_norm(e["query"]) for e in load_bank()}


def get_active_queries(role: str) -> list[str]:
    """Return active (promoted) queries for a given beat role, best first."""
    bank = load_bank()
    entries = [
        e for e in bank
        if e.get("role") == role
        and e.get("status") in ("active", "seed")
    ]
    # Sort by video hit rate descending
    def hit_rate(e):
        uses = e.get("uses", 0)
        hits = e.get("video_hits", 0)
        return hits / uses if uses > 0 else 0.5  # unknown = neutral
    entries.sort(key=hit_rate, reverse=True)
    return [e["query"] for e in entries]


# ── Add novel queries from Claude output ──────────────────────────────────────

def register_novel_queries(claude_queries: list[str], beat_roles: list[str]):
    """
    Add any queries Claude generated that:
      - passed the banned-term filter
      - are not already in the bank
    as "trial" entries. They will be promoted if they prove themselves.
    """
    bank = load_bank()
    existing = {_norm(e["query"]) for e in bank}
    added = 0
    for q, role in zip(claude_queries, beat_roles):
        if _is_banned(q):
            continue
        if _norm(q) in existing:
            continue
        bank.append({
            "query":      q.strip(),
            "role":       role,
            "source":     "claude",
            "status":     "trial",
            "uses":       0,
            "video_hits": 0,
            "photo_hits": 0,
            "added":      date.today().isoformat(),
        })
        existing.add(_norm(q))
        added += 1
    if added:
        save_bank(bank)
        print(f"    [QueryLearner] {added} novel Claude queries added to trial pool")


def seed_bank_if_empty(seed_queries: dict[str, list[str]]):
    """
    Populate bank from the hardcoded TRANSPORT_QUERIES dict if the bank file
    does not exist yet. Called once on first run.
    """
    if BANK_FILE.exists() and load_bank():
        return
    bank = []
    for role, queries in seed_queries.items():
        for q in queries:
            bank.append({
                "query":      q,
                "role":       role,
                "source":     "seed",
                "status":     "seed",   # seeds are always in rotation, never demoted
                "uses":       0,
                "video_hits": 0,
                "photo_hits": 0,
                "added":      date.today().isoformat(),
            })
    save_bank(bank)
    print(f"    [QueryLearner] Bank initialised with {len(bank)} seed queries")


# ── Hit reporting (called from render_video.py) ───────────────────────────────

def report_hit(query: str, hit_type: str):
    """
    Record the outcome of a Pexels/Pixabay fetch for a query.
    hit_type: "video" | "photo" | "placeholder"
    Called from render_video.py after each clip fetch attempt.
    """
    try:
        hits = json.loads(HITS_FILE.read_text(encoding="utf-8")) if HITS_FILE.exists() else []
    except Exception:
        hits = []
    hits.append({"query": _norm(query), "hit_type": hit_type, "date": date.today().isoformat()})
    # Prune hits older than 30 days
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    hits = [h for h in hits if h.get("date","") >= cutoff]
    HITS_FILE.write_text(json.dumps(hits, indent=2), encoding="utf-8")


# ── Promote / demote cycle (called from generate_content.py each run) ─────────

def promote_demote():
    """
    Read hit data and update bank entry statuses:
      trial  -> active  : 2+ video hits
      active -> weak    : <25% video rate over 5+ uses
      weak   -> archived: 10+ uses with no improvement
    """
    bank = load_bank()
    if not bank:
        return

    # Build hit summary from hits file
    try:
        hits = json.loads(HITS_FILE.read_text(encoding="utf-8")) if HITS_FILE.exists() else []
    except Exception:
        hits = []

    # Aggregate per query
    summary: dict[str, dict] = {}
    for h in hits:
        q = h["query"]
        if q not in summary:
            summary[q] = {"video": 0, "photo": 0, "placeholder": 0}
        ht = h.get("hit_type","placeholder")
        summary[q][ht] = summary[q].get(ht, 0) + 1

    changed = 0
    for entry in bank:
        qn     = _norm(entry["query"])
        status = entry.get("status", "trial")

        if status == "seed":
            # Seeds are always protected — update stats only
            if qn in summary:
                entry["video_hits"]  = summary[qn].get("video", 0)
                entry["photo_hits"]  = summary[qn].get("photo", 0)
                entry["uses"] = sum(summary[qn].values())
            continue

        if qn not in summary:
            continue

        v = summary[qn].get("video", 0)
        p = summary[qn].get("photo", 0)
        ph = summary[qn].get("placeholder", 0)
        total = v + p + ph

        entry["video_hits"]  = v
        entry["photo_hits"]  = p
        entry["uses"]        = total
        rate = v / total if total > 0 else 0

        if status == "trial":
            if v >= PROMOTE_THRESHOLD:
                entry["status"] = "active"
                entry["promoted"] = date.today().isoformat()
                print(f"    [QueryLearner] PROMOTED: '{entry['query']}' ({v} video hits)")
                changed += 1

        elif status == "active":
            if total >= DEMOTE_MIN_USES and rate < DEMOTE_MAX_RATE:
                entry["status"] = "weak"
                entry["demoted"] = date.today().isoformat()
                print(f"    [QueryLearner] DEMOTED: '{entry['query']}' ({rate:.0%} video rate)")
                changed += 1

        elif status == "weak":
            if total >= ARCHIVE_THRESHOLD and rate < DEMOTE_MAX_RATE:
                entry["status"] = "archived"
                print(f"    [QueryLearner] ARCHIVED: '{entry['query']}'")
                changed += 1

    if changed:
        save_bank(bank)
        print(f"    [QueryLearner] Bank updated — {changed} status change(s)")


# ── Weekly Claude refresh ─────────────────────────────────────────────────────

def maybe_weekly_refresh():
    """
    If it has been 7+ days since the last Claude query refresh, ask Claude
    for 20 new transport queries (5 per beat role) and add novel ones as trial.
    Runs silently if no refresh needed.
    """
    try:
        if REFRESH_FILE.exists():
            last = date.fromisoformat(json.loads(REFRESH_FILE.read_text())["last"])
            if (date.today() - last).days < 7:
                return
    except Exception:
        pass

    print("    [QueryLearner] Weekly refresh — asking Claude for new transport queries...")
    _run_claude_refresh()
    REFRESH_FILE.write_text(json.dumps({"last": date.today().isoformat()}))


def _run_claude_refresh():
    """Ask Claude for 20 new transport-only Pexels video search queries."""
    existing = get_bank_set()

    prompt = """You are helping build a Pexels video search query bank for BootHop — a UK-Nigeria peer-to-peer parcel delivery app. Videos in the feed show TRANSPORT scenes only.

Generate 20 NEW Pexels video search queries, 4 per beat role below.
Each query: 3-6 words, describes a real video clip, all lowercase.

Beat roles and what they need:
- hook: dramatic, motion-heavy transport scenes (planes, taxis, trains departing)
- problem: stress and friction at transport hubs (queues, delays, customs, worried travellers)
- stakes: emotional human moments at airports/stations (farewells, worry, waiting alone)
- resolution: successful outcomes (parcel handovers, happy arrivals, taxi pulling up)
- lesson_pre: professional/confident scenes in London or Lagos transport settings

STRICT RULES — never suggest:
- Animals of any kind (dog, cat, horse, bird, fish, pet, wildlife, farm, zoo)
- Food or food delivery (Uber Eats, Deliveroo, restaurant, takeaway, meal, pizza, grocery, chef, kitchen)
- Christmas, Xmas, Santa, halloween, pumpkin, easter, thanksgiving, fireworks
- Generic stock clichés (handshake, trophy, success mountain, cartoon, lightbulb)

Focus on: planes, runways, airports, trains, rail stations, black cabs, taxis, cargo ships,
shipping ports, suitcases, parcels, travellers walking, city streets, London/Lagos skylines.

Return ONLY valid JSON, no commentary:
{
  "hook":       ["query1", "query2", "query3", "query4"],
  "problem":    ["query1", "query2", "query3", "query4"],
  "stakes":     ["query1", "query2", "query3", "query4"],
  "resolution": ["query1", "query2", "query3", "query4"],
  "lesson_pre": ["query1", "query2", "query3", "query4"]
}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            print("    [QueryLearner] Claude returned no JSON"); return
        suggestions = json.loads(match.group())
    except Exception as e:
        print(f"    [QueryLearner] Claude refresh failed: {e}"); return

    bank  = load_bank()
    added = 0
    for role, queries in suggestions.items():
        if role not in BEAT_ROLES:
            continue
        for q in queries:
            q = q.strip().lower()
            if _is_banned(q):
                continue
            if q in existing:
                continue
            bank.append({
                "query":      q,
                "role":       role,
                "source":     "weekly_refresh",
                "status":     "trial",
                "uses":       0,
                "video_hits": 0,
                "photo_hits": 0,
                "added":      date.today().isoformat(),
            })
            existing.add(q)
            added += 1

    if added:
        save_bank(bank)
        print(f"    [QueryLearner] Weekly refresh: {added} new queries added to trial pool")
    else:
        print("    [QueryLearner] Weekly refresh: no novel queries found")


# ── Best-query selector (used by dedup as replacement pool) ──────────────────

def get_best_for_role(role: str, exclude: set, n: int = 10) -> list[str]:
    """
    Return up to n queries for a beat role, ordered by quality:
      active (best video rate first) > seed > trial
    Excludes any query in the `exclude` set (recently used or used this run).
    """
    bank = load_bank()
    entries = [
        e for e in bank
        if e.get("role") == role
        and e.get("status") not in ("weak", "archived")
        and _norm(e["query"]) not in exclude
    ]

    def sort_key(e):
        status_rank = {"active": 0, "seed": 1, "trial": 2}.get(e.get("status","trial"), 3)
        uses = e.get("uses", 0)
        hits = e.get("video_hits", 0)
        rate = hits / uses if uses > 0 else 0.5
        return (status_rank, -rate)

    entries.sort(key=sort_key)
    return [e["query"] for e in entries[:n]]


# ── Bank stats (for Telegram /status command) ─────────────────────────────────

def bank_stats() -> str:
    bank = load_bank()
    by_status = {}
    for e in bank:
        s = e.get("status","?")
        by_status[s] = by_status.get(s, 0) + 1
    lines = [f"Query bank: {len(bank)} total"]
    for s in ("seed","trial","active","weak","archived"):
        if s in by_status:
            lines.append(f"  {s}: {by_status[s]}")
    return "\n".join(lines)
