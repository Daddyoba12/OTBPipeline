"""
BootHop Blogger Auto-Poster (API Method)
=========================================
- Reads HTML files from blog/pending/
- Posts each one to Blogger via the Blogger API v3
- Moves file to blog/posted/ with metadata
- Archives posts older than 7 days to blog/archive/

File naming:
  YYYY-MM-DD_your-post-title.html

File format:
  <!-- title: Your Post Title -->
  <!-- labels: logistics, diaspora -->
  <p>Your HTML content here...</p>
"""

import os, json, re, shutil, requests
from pathlib import Path
from datetime import datetime, timedelta, timezone

BASE        = Path(__file__).parent
PENDING     = BASE / "pending"
POSTED      = BASE / "posted"
ARCHIVE     = BASE / "archive"
CONFIG_FILE = BASE / "config.json"
LOG_FILE    = BASE / "blog_log.txt"

ARCHIVE_AFTER_DAYS = 7

def log(msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_config():
    if not CONFIG_FILE.exists():
        log("ERROR: config.json not found.")
        raise SystemExit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

def get_access_token(cfg):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": cfg["refresh_token"],
        "grant_type":    "refresh_token",
    })
    if not r.ok:
        raise RuntimeError(f"Failed to get access token: {r.text}")
    return r.json()["access_token"]

def upload_image(image_path: Path) -> str | None:
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                "https://api.imgur.com/3/image",
                headers={"Authorization": "Client-ID 546c25a59c58ad7"},
                files={"image": f},
                timeout=60,
            )
        if r.ok:
            url = r.json()["data"]["link"]
            log(f"  Image uploaded: {image_path.name} → {url}")
            return url
        log(f"  Image upload failed: {image_path.name}")
    except Exception as e:
        log(f"  Image upload error: {e}")
    return None

def resolve_images(html: str, post_file: Path) -> str:
    post_dir = post_file.parent

    def replace(match):
        src = match.group(1)
        if src.startswith("http://") or src.startswith("https://"):
            return match.group(0)
        img_path = Path(src) if Path(src).is_absolute() else (post_dir / src)
        if img_path.exists():
            url = upload_image(img_path)
            if url:
                return match.group(0).replace(src, url)
        log(f"  WARNING: image not found — {src}")
        return match.group(0)

    return re.sub(r'<img[^>]+src=["\']([^"\']+)["\']', replace, html, flags=re.IGNORECASE)

def parse_file(path: Path):
    content = path.read_text(encoding="utf-8")

    m = re.search(r'<!--\s*title:\s*(.+?)\s*-->', content)
    if m:
        title   = m.group(1).strip()
        content = content.replace(m.group(0), "").strip()
    else:
        stem  = path.stem
        parts = stem.split("_", 1)
        title = parts[1].replace("-", " ").title() if len(parts) > 1 else stem

    labels = []
    m2 = re.search(r'<!--\s*labels:\s*(.+?)\s*-->', content)
    if m2:
        labels  = [l.strip() for l in m2.group(1).split(",") if l.strip()]
        content = content.replace(m2.group(0), "").strip()

    content = resolve_images(content, path)
    return title, labels, content

def post_to_blogger(cfg, access_token, title, labels, html_content):
    url  = f"https://www.googleapis.com/blogger/v3/blogs/{cfg['blog_id']}/posts/"
    body = {
        "kind":    "blogger#post",
        "title":   title,
        "content": html_content,
        "labels":  labels,
    }
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
        },
        json=body,
    )
    if r.ok:
        post_url = r.json().get("url", "")
        log(f"  Posted via API: {post_url}")
        return True
    log(f"  API error {r.status_code}: {r.text}")
    return False

def archive_old():
    cutoff   = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_AFTER_DAYS)
    archived = 0
    for meta_file in POSTED.glob("*.json"):
        try:
            meta      = json.loads(meta_file.read_text(encoding="utf-8"))
            posted_at = datetime.fromisoformat(meta["posted_at"])
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)
            if posted_at < cutoff:
                html_file = POSTED / meta["filename"]
                if html_file.exists():
                    shutil.move(str(html_file), ARCHIVE / meta["filename"])
                shutil.move(str(meta_file), ARCHIVE / meta_file.name)
                log(f"Archived: {meta['filename']}")
                archived += 1
        except Exception as e:
            log(f"Archive error {meta_file.name}: {e}")
    if archived:
        log(f"Archived {archived} old post(s)")

def main():
    log("=" * 55)
    log("BootHop Blog Auto-Poster starting")

    cfg   = load_config()
    files = sorted(PENDING.glob("*.html"))

    archive_old()

    if not files:
        log("No pending posts found in blog/pending/")
        log("=" * 55)
        return

    log(f"Found {len(files)} pending post(s)")

    try:
        access_token = get_access_token(cfg)
    except Exception as e:
        log(f"ERROR: Could not get access token — {e}")
        log("Run: python blog/setup_blogger.py  to re-authenticate")
        log("=" * 55)
        return

    for html_path in files:
        log(f"Processing: {html_path.name}")
        try:
            title, labels, content = parse_file(html_path)
            log(f"  Title:  {title}")
            log(f"  Labels: {labels or 'none'}")

            ok = post_to_blogger(cfg, access_token, title, labels, content)

            if ok:
                meta = {
                    "filename":  html_path.name,
                    "title":     title,
                    "labels":    labels,
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                }
                (POSTED / (html_path.stem + ".json")).write_text(
                    json.dumps(meta, indent=2), encoding="utf-8"
                )
                shutil.move(str(html_path), POSTED / html_path.name)
                log(f"  Done — moved to posted/")
            else:
                log(f"  FAILED — stays in pending/")

        except Exception as e:
            log(f"  ERROR: {e}")

    log("All done.")
    log("=" * 55)

if __name__ == "__main__":
    main()
