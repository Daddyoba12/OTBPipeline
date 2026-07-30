"""
G-Inspired Automall — inventory scraper.
Fetches current listings from cars.com and writes g_inspired_inventory.json.
Called automatically by g_inspired_content.py if inventory is >24h old.
"""

import json, re, sys, os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

DEALER_URL = "https://www.cars.com/dealers/5386080/g-inspired-automall-llc/inventory/"
HEADERS    = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_cars(html: str) -> list[dict]:
    cars = []

    # cars.com embeds listing data as JSON-LD or in data attributes.
    # Primary: JSON-LD ItemList
    ld_blocks = re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                           html, re.DOTALL)
    for block in ld_blocks:
        try:
            data = json.loads(block)
            items = []
            if data.get("@type") == "ItemList":
                items = data.get("itemListElement", [])
            elif isinstance(data, list):
                items = [x for x in data if x.get("@type") in ("Car", "Vehicle")]
            for item in items:
                thing = item.get("item", item)
                name  = thing.get("name", "")
                price = thing.get("offers", {}).get("price", 0)
                mileage_raw = thing.get("mileageFromOdometer", {})
                mileage = mileage_raw.get("value", 0) if isinstance(mileage_raw, dict) else 0
                parts   = name.split()
                year    = int(parts[0]) if parts and parts[0].isdigit() else 0
                make    = parts[1] if len(parts) > 1 else ""
                model   = " ".join(parts[2:]) if len(parts) > 2 else ""
                if year >= 2000 and make:
                    cars.append({
                        "year": year, "make": make, "model": model, "trim": "",
                        "price": int(float(str(price).replace(",", "").replace("$", "") or 0)),
                        "mileage": int(mileage),
                    })
        except Exception:
            pass

    if cars:
        return cars

    # Fallback: regex scrape visible listing cards
    # Pattern: "2018 Honda CR-V" + "$16,995" + "45,123 mi."
    titles   = re.findall(r'"vehicleYear":(\d{4}).*?"vehicleMake":"([^"]+)".*?"vehicleModel":"([^"]+)"', html)
    prices   = re.findall(r'"price":\s*"?\$?([\d,]+)"?', html)
    mileages = re.findall(r'"mileage":\s*"?([\d,]+)"?', html)

    for i, (yr, mk, mdl) in enumerate(titles):
        price   = int(prices[i].replace(",", ""))   if i < len(prices)   else 0
        mileage = int(mileages[i].replace(",", "")) if i < len(mileages) else 0
        cars.append({
            "year": int(yr), "make": mk, "model": mdl, "trim": "",
            "price": price, "mileage": mileage,
        })

    return cars


def scrape(data_dir: Path) -> list[dict]:
    """Scrape inventory and save to data_dir/g_inspired_inventory.json. Returns car list."""
    print("[Inventory] Scraping G-Inspired Automall from cars.com...")
    try:
        r = requests.get(DEALER_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[Inventory] Fetch failed: {e} — will retry next run")
        # Touch scraped_at so we don't retry every single pipeline run
        inv = data_dir / "g_inspired_inventory.json"
        if inv.exists():
            try:
                d = json.loads(inv.read_text(encoding="utf-8"))
                d["scraped_at"] = datetime.now().isoformat()
                inv.write_text(json.dumps(d, indent=2), encoding="utf-8")
            except Exception:
                pass
        return []

    cars = _parse_cars(r.text)

    if not cars:
        print("[Inventory] No cars parsed — HTML structure may have changed.")
        # Touch the scraped_at so we don't hammer cars.com on every run
        inv = data_dir / "g_inspired_inventory.json"
        if inv.exists():
            try:
                d = json.loads(inv.read_text(encoding="utf-8"))
                d["scraped_at"] = datetime.now().isoformat()
                inv.write_text(json.dumps(d, indent=2), encoding="utf-8")
            except Exception:
                pass
        return []

    # Deduplicate by year+make+model
    seen = set()
    unique = []
    for c in cars:
        key = f"{c['year']}-{c['make']}-{c['model']}"
        if key not in seen:
            seen.add(key)
            unique.append(c)

    out = {
        "scraped_at": datetime.now().isoformat(),
        "source": DEALER_URL,
        "count": len(unique),
        "cars": unique,
    }
    dest = data_dir / "g_inspired_inventory.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[Inventory] Saved {len(unique)} cars → {dest}")
    return unique


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
