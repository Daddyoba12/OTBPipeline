"""
G-Inspired Automall — inventory scraper.
Fetches current listings from the dealership's OWN website (ginspiredautomall.com)
and writes g_inspired_inventory.json. Called automatically by g_inspired_content.py
if inventory is >24h old.

Was cars.com before — switched because cars.com blocks scraping outright (403,
regardless of IP/headers — confirmed bot-detection, not a header/UA problem) and
never had real photos anyway, only specs. The dealer's own site:
  - isn't bot-protected (robots.txt explicitly allows "User-agent: *" on these paths,
    it only blocks AI-training crawlers and some SEO tools by name)
  - has real photos of the actual car (not generic stock footage)
  - exposes exterior colour, which cars.com's scrape never had
  - is fresher (updated directly by the dealer, not a third-party aggregator)

Detail URLs come from /sitemap.xml, which lists every vehicle detail page with a
lastmod timestamp — far more reliable than crawling the "Load More" JS-paginated
listing page or guessing brand-category URLs.
"""

import json, re, sys, os, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

SITE_BASE   = "https://www.ginspiredautomall.com"
SITEMAP_URL = f"{SITE_BASE}/sitemap.xml"
DEALER_URL  = f"{SITE_BASE}/pre-owned-cars"  # kept for the inventory.json "source" field

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

REQUEST_DELAY = 0.4  # seconds between detail-page fetches — small site, be polite
MAX_PHOTOS    = 12

_DETAIL_URL_RE = re.compile(
    r"<loc>(https://www\.ginspiredautomall\.com/pre-owned-cars/detail/[^<]+)</loc>"
    r"(?:\s*<lastmod>([^<]*)</lastmod>)?",
)

_ITEMPROP_RE = re.compile(r'itemprop="([a-zA-Z]+)"\s+content="([^"]*)"')
_TRIM_RE     = re.compile(r'class="ds-vdp-vehicle-sub-title"[^>]+data-value="([^"]*)"')
_PHOTO_RE    = re.compile(r'data-src="(//images\.dealersync\.com/[^"]+/Photos/[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', re.I)


def _get(session: requests.Session, url: str, timeout: int = 20):
    return session.get(url, headers=HEADERS, timeout=timeout)


def _list_detail_urls(session: requests.Session) -> list[tuple[str, str]]:
    """Returns [(detail_url, lastmod_or_empty), ...] from the sitemap."""
    r = _get(session, SITEMAP_URL)
    r.raise_for_status()
    return [(m.group(1), m.group(2) or "") for m in _DETAIL_URL_RE.finditer(r.text)]


def _parse_detail_page(html: str, url: str) -> dict | None:
    props = _ITEMPROP_RE.findall(html)
    if not props:
        return None

    # "name" appears twice: first = full vehicle title, second = make (nested
    # inside the brand sub-block). Everything else is a single clean lookup.
    names  = [v for k, v in props if k == "name"]
    lookup = {k: v for k, v in props if k != "name"}

    title = names[0] if names else ""
    make  = names[1] if len(names) > 1 else ""
    model = lookup.get("model", "")
    year_raw = lookup.get("vehicleModelDate", "")
    try:
        year = int(year_raw)
    except ValueError:
        year = 0

    try:
        mileage = int(lookup.get("value", "0") or 0)
    except ValueError:
        mileage = 0
    try:
        price = int(float(lookup.get("price", "0") or 0))
    except ValueError:
        price = 0

    trim_m = _TRIM_RE.search(html)
    trim   = trim_m.group(1).strip() if trim_m else ""
    # Trim sub-title often repeats the model name (e.g. "4dr I4 Auto SE") — keep
    # as-is, downstream code only uses it for flavour text, not exact matching.

    photos = []
    for m in _PHOTO_RE.finditer(html):
        src = m.group(1)
        if src.startswith("//"):
            src = "https:" + src
        if src not in photos:
            photos.append(src)
        if len(photos) >= MAX_PHOTOS:
            break

    if not (year and make and model):
        return None

    return {
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "price": price,
        "mileage": mileage,
        "color": lookup.get("color", ""),
        "vin": lookup.get("vehicleIdentificationNumber", ""),
        "stock": lookup.get("sku", ""),
        "detail_url": lookup.get("url", url),
        "photos": photos,
        "title": title,
    }


def scrape(data_dir: Path) -> list[dict]:
    """Scrape inventory from ginspiredautomall.com and save to
    data_dir/g_inspired_inventory.json. Returns the car list."""
    print("[Inventory] Scraping G-Inspired Automall from ginspiredautomall.com...")
    session = requests.Session()

    try:
        detail_entries = _list_detail_urls(session)
    except Exception as e:
        print(f"[Inventory] Sitemap fetch failed: {e} — will retry next run")
        _touch_scraped_at(data_dir)
        return []

    if not detail_entries:
        print("[Inventory] No vehicle URLs found in sitemap — site structure may have changed.")
        _touch_scraped_at(data_dir)
        return []

    cars = []
    for i, (url, lastmod) in enumerate(detail_entries):
        try:
            r = _get(session, url)
            r.raise_for_status()
            car = _parse_detail_page(r.text, url)
            if car:
                car["lastmod"] = lastmod
                cars.append(car)
        except Exception as e:
            print(f"  [Inventory] Skipped {url}: {e}")
        if i < len(detail_entries) - 1:
            time.sleep(REQUEST_DELAY)

    if not cars:
        print("[Inventory] No cars parsed — HTML structure may have changed.")
        _touch_scraped_at(data_dir)
        return []

    # Deduplicate by year+make+model+stock (stock # distinguishes same-model cars)
    seen = set()
    unique = []
    for c in cars:
        key = f"{c['year']}-{c['make']}-{c['model']}-{c.get('stock', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(c)

    out = {
        "scraped_at": datetime.now().isoformat(),
        "last_updated": datetime.now().date().isoformat(),
        "source": DEALER_URL,
        "count": len(unique),
        "cars": unique,
    }
    dest = data_dir / "g_inspired_inventory.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[Inventory] Saved {len(unique)} cars (with photos + colour) -> {dest}")
    return unique


def _touch_scraped_at(data_dir: Path):
    """Touch scraped_at on failure so we don't retry every single pipeline run."""
    inv = data_dir / "g_inspired_inventory.json"
    if not inv.exists():
        return
    try:
        d = json.loads(inv.read_text(encoding="utf-8"))
        d["scraped_at"] = datetime.now().isoformat()
        inv.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def is_stale(data_dir: Path, max_age_hours: int = 24) -> bool:
    inv = data_dir / "g_inspired_inventory.json"
    if not inv.exists():
        return True
    try:
        data = json.loads(inv.read_text(encoding="utf-8"))
        scraped_at = datetime.fromisoformat(data.get("scraped_at", "2000-01-01"))
        age_hours  = (datetime.now() - scraped_at).total_seconds() / 3600
        return age_hours >= max_age_hours
    except Exception:
        return True


def _load_existing(data_dir: Path) -> list[dict]:
    inv = data_dir / "g_inspired_inventory.json"
    if inv.exists():
        try:
            return json.loads(inv.read_text(encoding="utf-8")).get("cars", [])
        except Exception:
            pass
    return []


def refresh_if_stale(data_dir: Path) -> list[dict]:
    """Refresh inventory if >24h old. Falls back to existing data if scrape fails."""
    if is_stale(data_dir):
        fresh = scrape(data_dir)
        if fresh:
            return fresh
        print("[Inventory] Scrape returned nothing — keeping existing inventory.")
        return _load_existing(data_dir)
    return _load_existing(data_dir)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=None)
    args = p.parse_args()

    _dd = Path(args.data_dir) if args.data_dir else Path(__file__).parent.parent / "data"
    cars = scrape(_dd)
    print(f"Scraped {len(cars)} cars.")
