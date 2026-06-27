"""
OTB_Pipeline — Blog generator + Blogger poster (SEO-optimized)

Blog / Google Blogger 2026 SEO algorithm signals applied:
1. KEYWORD-FIRST H1: Title must lead with the primary longtail keyword — Google indexes
   the first 65 chars of title as the primary relevance signal.
   Example: "Send Parcels from UK to Nigeria Cheap: BootHop Guide 2026" not "The BootHop Story"
2. FEATURED SNIPPET BAIT: FAQ section at bottom with question <h3> + direct answer <p>
   — structured Q&A is Google's #1 source for featured snippets (position zero).
3. H2/H3 STRUCTURE: 4-6 H2 headings, each containing the secondary keyword naturally.
   Google uses heading hierarchy as a content structure signal (skimmability = lower bounce rate).
4. LONGTAIL FOCUS: Targeting "send parcel from UK to Nigeria cheap", "peer to peer delivery
   London Lagos", "how does BootHop work UK diaspora" — less competition, higher conversion intent.
5. INTERNAL LOGIC: 800-1500 words. Under 800 = thin content (demoted). Over 2000 = reader dropout
   spike, which increases bounce rate and hurts SERP ranking.
6. META DESCRIPTION: 150-160 chars, includes primary keyword and a CTA — influences click-through
   rate (CTR), which Google uses as a secondary ranking signal.
7. SEMANTIC KEYWORDS: Variations of the main keyword woven into body naturally —
   "diaspora delivery", "peer-to-peer courier", "send abroad from UK", "traveller delivery service".
8. CTA LINK: One clear call-to-action link to boothop.com/register — external click signals
   to Google that the page provides value beyond reading (lowers effective bounce rate).
9. PILLAR CONTENT CONSISTENCY: Each post is tied to one of BootHop's 8 content pillars,
   building topical authority for the BootHop Blogger domain over time.
10. POSTING ON SLOT 1 DAILY: Publishing at 7am means Google crawls it during peak UK indexing
    window (Google UK crawlers are most active 6am-10am BST).
"""

import json, os, sys, subprocess, time, re
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, DATA

import anthropic

BLOG_BASE   = Path(r"C:\Users\babso\Desktop\BootHopPipeline\blog")
PENDING_DIR = BLOG_BASE / "pending"
POSTER_PY   = BLOG_BASE / "post_to_blogger.py"
PYTHON      = sys.executable

LONGTAIL_KEYWORDS = {
    "community":          ["diaspora community UK Nigeria", "Nigerian community London", "send gifts Nigeria from UK"],
    "family":             ["send package from UK to family in Nigeria", "care package UK to Nigeria", "send food from UK to Nigeria"],
    "airport":            ["UK airport parcel delivery", "carry parcel on flight to Nigeria", "hand carry delivery London Lagos"],
    "smart":              ["cheapest way to send parcel Nigeria", "save money sending abroad UK", "budget international delivery"],
    "travel_hacks":       ["travel tips UK Nigeria flights", "excess luggage delivery", "peer to peer delivery London Lagos"],
    "logistics_stories":  ["BootHop how it works", "UK Nigeria delivery service review", "trusted traveller delivery UK"],
    "airport_deliveries": ["airport pickup delivery Nigeria", "collect parcel at Lagos airport", "same day delivery UK to Nigeria"],
    "supply_chain":       ["UK Nigeria supply chain", "small business import Nigeria from UK", "send business goods UK to Nigeria"],
}


def _log(msg: str):
    print(f"[{datetime.utcnow():%H:%M:%S}] [Blog] {msg}")


def _slug(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s[:60]


def _generate_blog_html(content: dict) -> tuple[str, str, str]:
    """
    Use Claude to generate a full SEO blog post (800-1500 words) from slot content.
    Returns (title, labels, html_body).
    """
    hook    = content.get("hook", "")
    problem = content.get("problem", "")
    stakes  = content.get("stakes", "")
    res     = content.get("resolution", "")
    lesson  = content.get("lesson", "")
    pillar  = content.get("pillar", "community")
    kws     = LONGTAIL_KEYWORDS.get(pillar, ["BootHop UK Nigeria delivery"])

    primary_kw = kws[0] if kws else "UK Nigeria delivery"

    prompt = f"""Write a complete SEO-optimised blog post for BootHop (boothop.com).

CONTEXT:
- Hook: {hook}
- Problem: {problem}
- Stakes: {stakes}
- Resolution: {res}
- Lesson: {lesson}
- Primary keyword: "{primary_kw}"
- Related keywords: {', '.join(kws[1:3])}
- Pillar: {pillar}

REQUIREMENTS:
1. Return ONLY valid HTML — no markdown, no commentary outside the HTML
2. Format:
   <!-- title: YOUR POST TITLE (keyword-first, 60 chars max, year 2026 in title) -->
   <!-- labels: {pillar}, logistics, diaspora, BootHop -->
   <p>Intro paragraph...</p>
   <h2>First section...</h2>
   ...
   <h2>Frequently Asked Questions</h2>
   <h3>Question 1?</h3><p>Direct answer...</p>
   <h3>Question 2?</h3><p>Direct answer...</p>
   ...CTA div...

3. Structure:
   - Intro paragraph (hook, primary keyword in first sentence)
   - 4-5 H2 sections (each 2-3 paragraphs)
   - FAQ section (3-4 Q&A pairs, each targeting a specific search query)
   - CTA box with link to https://www.boothop.com/register

4. SEO rules:
   - Include "{primary_kw}" in first paragraph, at least one H2, and meta area
   - 800-1200 words total
   - NO keyword stuffing — natural prose
   - Bold 2-3 key facts (wrap in <strong>)
   - One hyperlink to https://www.boothop.com (anchor text = "same-day delivery by trusted travellers")

5. Tone: helpful, authoritative, Nigerian diaspora audience, UK-based sender perspective

CTA box HTML template:
<div style="background:linear-gradient(135deg,#1e3a8a,#2563eb);border-radius:16px;padding:32px;margin-top:40px;text-align:center;">
  <h3 style="color:#fff;margin:0 0 12px;font-size:20px;">Ready to Send?</h3>
  <a href="https://www.boothop.com/register" style="display:inline-block;background:#22d3ee;color:#0f172a;font-weight:700;font-size:15px;padding:14px 32px;border-radius:10px;text-decoration:none;margin-top:8px;">Get Started Free →</a>
</div>"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()

    # Extract title and labels from HTML comments
    title_match  = re.search(r'<!-- title:\s*(.+?)\s*-->', raw)
    labels_match = re.search(r'<!-- labels:\s*(.+?)\s*-->', raw)
    title  = title_match.group(1).strip()  if title_match  else hook[:60]
    labels = labels_match.group(1).strip() if labels_match else pillar

    # Strip comment lines from body
    body = re.sub(r'<!--.*?-->', '', raw, flags=re.DOTALL).strip()
    return title, labels, body


def _save_to_pending(title: str, labels: str, body: str) -> Path:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    today  = date.today().isoformat()
    slug   = _slug(title)
    fname  = f"{today}_{slug}.html"
    fpath  = PENDING_DIR / fname
    html   = f"<!-- title: {title} -->\n<!-- labels: {labels} -->\n{body}"
    fpath.write_text(html, encoding="utf-8")
    _log(f"Saved: {fpath.name}")
    return fpath


def _post_to_blogger() -> bool:
    """Call the existing BootHopPipeline Blogger poster as subprocess."""
    if not POSTER_PY.exists():
        _log(f"Blogger poster not found: {POSTER_PY}"); return False
    try:
        result = subprocess.run(
            [PYTHON, str(POSTER_PY)],
            cwd=str(BLOG_BASE),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout: _log(result.stdout.strip()[:500])
        if result.returncode != 0:
            _log(f"Blogger poster exit {result.returncode}: {result.stderr[:300]}")
            return False
        return True
    except Exception as e:
        _log(f"Blogger poster error: {e}"); return False


def post_blog(content: dict, slot: int = 0) -> bool:
    """
    Generate an SEO blog post from slot content and publish to Blogger.
    Only runs from Slot 1 (daily 7am) to build consistent crawl schedule.
    Returns True on success.
    """
    _log(f"Generating blog post for pillar: {content.get('pillar','?')}")
    try:
        title, labels, body = _generate_blog_html(content)
    except Exception as e:
        _log(f"Claude generation failed: {e}"); return False

    _log(f"Title: {title[:70]}")
    _save_to_pending(title, labels, body)

    _log("Posting to Blogger...")
    ok = _post_to_blogger()
    if ok:
        _log("Blog post published ✅")
    else:
        _log("Blogger post failed (HTML saved in pending — will retry next run)")
    return ok
