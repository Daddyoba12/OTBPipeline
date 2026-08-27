"""
OTB_Pipeline — Digital Product & Sales Funnel (Steps 5 & 6)

Auto-detects whether to run based on client_profile.json at the project root.
The content pipeline (Steps 1-4) always runs regardless.

HOW IT WORKS:
  1. Pipeline reads client_profile.json on every slot-1 run.
  2. If product.enabled = true AND the product is new or changed → funnel runs automatically.
  3. If product.enabled = false → nothing happens, pipeline continues as normal.

TO ACTIVATE FOR A CLIENT:
  Edit client_profile.json (or update it via Commander Portal /onboard):
    "product": {
      "enabled": true,
      "name": "The Car Buyer Cheat Sheet",
      "price": 27,
      "currency": "GBP",
      "description": "A practical guide to buying used cars without getting ripped off"
    }

  The next slot-1 run will detect the change and build the product + funnel automatically.

DESIGNED FOR ANY NICHE:
  All inputs (niche, brand, price, product name) come from client_profile.json.
  No code changes needed when switching clients.
"""

import json, sys, requests
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA, BASE, OPENAI_API_KEY, PERPLEXITY_KEY

FUNNEL_OUTPUT   = DATA / "product_funnel"
FUNNEL_LOG      = DATA / "product_funnel_log.json"
CLIENT_PROFILE  = BASE / "client_profile.json"


# ── Client profile ────────────────────────────────────────────────────────────

def load_client_profile() -> dict:
    """Load client_profile.json. Returns empty dict if missing."""
    try:
        return json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _product_config(profile: dict | None = None) -> dict:
    """Return the product section of client_profile. Always returns a dict."""
    p = profile or load_client_profile()
    return p.get("product") or {}


def is_product_enabled(profile: dict | None = None) -> bool:
    """Return True if this client has a product configured and enabled."""
    return bool(_product_config(profile).get("enabled", False))


# ── Run-gate — only runs when product is new or changed ──────────────────────

def _should_run(product_cfg: dict) -> bool:
    """
    Return True if the funnel has never run for this product,
    or if the product name/price has changed since the last run.
    Prevents re-running the full research every week for an unchanged product.
    """
    if not FUNNEL_LOG.exists():
        return True
    try:
        log = json.loads(FUNNEL_LOG.read_text(encoding="utf-8"))
        return (
            log.get("product_name") != product_cfg.get("name", "")
            or log.get("product_price") != product_cfg.get("price", 0)
        )
    except Exception:
        return True


def _update_log(product_cfg: dict):
    FUNNEL_LOG.write_text(
        json.dumps({
            "last_run":     date.today().isoformat(),
            "product_name": product_cfg.get("name", ""),
            "product_price": product_cfg.get("price", 0),
        }, indent=2),
        encoding="utf-8",
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _claude(prompt: str, max_tokens: int = 2000) -> str:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model":      "gpt-4o",
            "max_tokens": max_tokens,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _perplexity(query: str) -> str:
    resp = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {PERPLEXITY_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model": "sonar",
            "messages": [
                {"role": "system", "content": "Return factual research. Be concise and specific."},
                {"role": "user",   "content": query},
            ],
            "max_tokens": 1200,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _strip_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
    return raw


# ── Stage 5a: Research pain points ───────────────────────────────────────────

def research_pain_points(niche: str, brand_name: str) -> dict:
    """Find the 5 strongest audience pain points in the niche via Perplexity + Claude."""
    print(f"[ProductFunnel] Stage 5a — Researching pain points for: {niche}")

    raw_research = _perplexity(
        f"What are the most common pain points, complaints, and unmet needs that people in the "
        f"'{niche}' niche discuss on Reddit, YouTube, and online communities? "
        f"Include specific quotes or examples. Focus on problems people actively want to pay to fix."
    )

    raw = _claude(f"""You are a digital product strategist.

NICHE: {niche}
BRAND: {brand_name}

RESEARCH:
{raw_research}

Identify the 5 strongest pain points that are:
1. Felt by a large segment of the audience
2. Specific — not vague like "they want to save money"
3. Something people would pay to solve
4. Not perfectly solved by existing free content

Return JSON only:
{{
  "pain_points": [
    {{
      "title": "Short pain point name",
      "description": "2 sentences on the specific problem",
      "urgency": "low | medium | high",
      "monetizable": true,
      "evidence": "1-2 examples from the research"
    }}
  ],
  "strongest_gap": "The single biggest unmet need in one sentence"
}}""")

    result = json.loads(_strip_json(raw))
    result["raw_research"] = raw_research
    return result


# ── Stage 5b: Create product outline ─────────────────────────────────────────

def create_product_outline(pain_points: dict, niche: str, brand_name: str,
                           price: int = 27, product_name: str = "") -> dict:
    """Build a digital product idea and full outline based on proven pain points."""
    print(f"[ProductFunnel] Stage 5b — Creating product outline...")

    points_block = "\n".join(
        f"{i+1}. {p['title']}: {p['description']}"
        for i, p in enumerate(pain_points.get("pain_points", []))
    )
    name_hint = f'\nPREFERRED PRODUCT NAME (use this if it fits): "{product_name}"' if product_name else ""

    raw = _claude(f"""You are a digital product creator specialising in high-converting info products.

NICHE: {niche}
BRAND: {brand_name}
PRICE POINT: £{price}{name_hint}
STRONGEST GAP: {pain_points.get("strongest_gap", "")}

TOP PAIN POINTS:
{points_block}

Design the strongest possible digital product. It must:
- Solve the most urgent and monetizable pain point
- Be deliverable as a PDF guide, template kit, video course, or email sequence
- Be completeable in a weekend — buyers want quick wins, not textbooks
- Be priced at or near £{price}

Return JSON only:
{{
  "product_name": "Catchy, benefit-driven title",
  "tagline": "One-line promise (max 10 words)",
  "format": "pdf_guide | template_kit | video_course | email_sequence | checklist",
  "solves": "Which pain point this primarily solves",
  "modules": [
    {{
      "number": 1,
      "title": "Module/section title",
      "content": "2 sentences on what the buyer learns or gets"
    }}
  ],
  "bonuses": ["Optional bonus 1", "Optional bonus 2"],
  "transformation": "Before → After: one sentence on what changes for the buyer",
  "positioning": "Why this product and not a competitor free content"
}}""", max_tokens=2500)

    return json.loads(_strip_json(raw))


# ── Stage 6: Build sales funnel ───────────────────────────────────────────────

def build_sales_funnel(product: dict, niche: str, brand_name: str,
                       price: int = 27, website: str = "") -> dict:
    """Generate mobile-optimised sales page copy + checkout flow structure."""
    print(f"[ProductFunnel] Stage 6 — Building sales funnel copy...")

    website_line = f"\nWEBSITE: {website}" if website else ""

    raw = _claude(f"""You are a high-converting sales page copywriter.

PRODUCT: {product.get("product_name", "")}
TAGLINE: {product.get("tagline", "")}
TRANSFORMATION: {product.get("transformation", "")}
PRICE: £{price}
NICHE: {niche}
BRAND: {brand_name}{website_line}

Write a mobile-optimised, conversion-focused sales page selling this product at £{price}.

Return JSON only:
{{
  "headline": "Above-the-fold headline — bold, benefit-driven, stops the scroll",
  "subheadline": "1 sentence confirming the promise and addressing the main objection",
  "pain_section": {{
    "header": "Section header",
    "bullets": ["3-5 pain points the reader recognises in themselves"]
  }},
  "solution_intro": "2 sentences introducing the product as the solution",
  "what_you_get": [
    {{"item": "Specific deliverable or module", "benefit": "What it does for them"}}
  ],
  "social_proof_placeholder": "Placeholder for where testimonials will go",
  "price_block": {{
    "anchor_text": "What this is worth vs the £{price} price",
    "cta_button": "Button text (max 6 words)",
    "urgency_line": "Optional scarcity or urgency line"
  }},
  "faq": [
    {{"q": "Common objection", "a": "Direct answer"}}
  ],
  "footer_cta": "Final call to action sentence before buy button",
  "confirmation_page_message": "Thank-you message shown after purchase (max 3 sentences)",
  "checkout_note": "Recommended checkout tool (Gumroad / Stripe / ThriveCart) and why"
}}""", max_tokens=3000)

    return json.loads(_strip_json(raw))


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_full_funnel(profile: dict | None = None, force: bool = False) -> dict | None:
    """
    Auto-detect from client_profile.json and run all three funnel stages if appropriate.

    Called by pipeline.py on every slot-1 run. Does nothing if:
      - product.enabled = false in client_profile.json
      - The same product has already been processed (name + price unchanged)

    Re-runs automatically when:
      - product.enabled flips to true for the first time
      - product.name or product.price changes (new product or price update)

    force=True skips the change-detection gate and rebuilds regardless.
    """
    p = profile or load_client_profile()

    if not is_product_enabled(p):
        print("[ProductFunnel] No product configured for this client — skipping.")
        return None

    product_cfg = _product_config(p)
    niche       = p.get("niche", "")
    brand_name  = p.get("brand_name", "")
    website     = p.get("website", "")
    price       = int(product_cfg.get("price", 27))
    product_name = product_cfg.get("name", "")

    if not force and not _should_run(product_cfg):
        print(f"[ProductFunnel] Product unchanged since last run — skipping. (force=True to rebuild)")
        return None

    if not niche or not brand_name:
        print("[ProductFunnel] client_profile.json missing niche or brand_name — cannot run.")
        return None

    print(f"[ProductFunnel] Product detected for {brand_name} — running funnel pipeline...")
    FUNNEL_OUTPUT.mkdir(parents=True, exist_ok=True)
    slug = p.get("slug", "client")

    # Stage 5a
    pain_data = research_pain_points(niche, brand_name)
    (FUNNEL_OUTPUT / f"{slug}_pain_points.json").write_text(
        json.dumps(pain_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Stage 5b
    product = create_product_outline(pain_data, niche, brand_name,
                                     price=price, product_name=product_name)
    (FUNNEL_OUTPUT / f"{slug}_product_outline.json").write_text(
        json.dumps(product, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Stage 6
    funnel = build_sales_funnel(product, niche, brand_name, price=price, website=website)
    (FUNNEL_OUTPUT / f"{slug}_sales_funnel.json").write_text(
        json.dumps(funnel, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    full_result = {
        "slug":        slug,
        "niche":       niche,
        "brand_name":  brand_name,
        "price":       price,
        "pain_points": pain_data,
        "product":     product,
        "funnel":      funnel,
        "built_on":    date.today().isoformat(),
    }
    (FUNNEL_OUTPUT / f"{slug}_full.json").write_text(
        json.dumps(full_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    _update_log(product_cfg)
    print(f"[ProductFunnel] Done — product: '{product.get('product_name','')}' | funnel saved to {FUNNEL_OUTPUT}/")
    return full_result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run product + funnel builder from client_profile.json")
    ap.add_argument("--force", action="store_true", help="Rebuild even if product hasn't changed")
    ap.add_argument("--profile", default="", help="Path to a different client_profile.json (optional)")
    args = ap.parse_args()

    profile = None
    if args.profile:
        try:
            profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Could not load profile: {e}")

    result = run_full_funnel(profile=profile, force=args.force)
    if result:
        print(f"\nProduct  : {result['product'].get('product_name', '')}")
        print(f"Tagline  : {result['product'].get('tagline', '')}")
        print(f"Headline : {result['funnel'].get('headline', '')}")
    elif not is_product_enabled(profile or load_client_profile()):
        print("\nTo activate: set product.enabled = true in client_profile.json")
