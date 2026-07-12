"""
BootHop PDF Drop → Blog Auto-Poster
====================================
Drop any PDF into blog/drop/ and this script will:
  1. Extract the text from the PDF
  2. Convert it to clean HTML
  3. Post it to Blogger via the Blogger API v3
  4. Move the PDF to blog/posted/pdfs/ with a timestamp
  5. Log everything to blog/blog_log.txt

Schedule: run daily via Windows Task Scheduler (BootHop-BlogDrop)
Manual:   python pdf_drop_to_blog.py

PDF naming convention (optional but helpful):
  YYYY-MM-DD_your-post-title.pdf
  → Title becomes "Your Post Title"

If no date prefix, today's date is used.
"""

import os, re, shutil, json, requests
from pathlib import Path
from datetime import datetime, timezone

try:
    import pypdf
    def extract_pdf_text(path: Path) -> str:
        reader = pypdf.PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages)
except ImportError:
    try:
        import PyPDF2
        def extract_pdf_text(path: Path) -> str:
            reader = PyPDF2.PdfReader(str(path))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
            return "\n\n".join(pages)
    except ImportError:
        def extract_pdf_text(path: Path) -> str:
            raise RuntimeError(
                "No PDF library found. Install one:\n"
                "  pip install pypdf\n"
                "or\n"
                "  pip install PyPDF2"
            )

BASE        = Path(__file__).parent
DROP        = BASE / "drop"
POSTED_PDFS = BASE / "posted" / "pdfs"
CONFIG_FILE = BASE / "config.json"
LOG_FILE    = BASE / "blog_log.txt"

def log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_config():
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"config.json not found at {CONFIG_FILE}")
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

def title_from_filename(stem: str) -> str:
    parts = stem.split("_", 1)
    raw   = parts[1] if len(parts) > 1 else parts[0]
    return raw.replace("-", " ").title()

def text_to_html(text: str) -> str:
    lines  = text.splitlines()
    html   = []
    in_ul  = False

    for raw in lines:
        line = raw.strip()
        if not line:
            if in_ul:
                html.append("</ul>")
                in_ul = False
            html.append("")
            continue

        is_heading = (
            len(line) < 80
            and not line.endswith((".", ",", ";", ":"))
            and not line[0].isdigit()
            and sum(1 for c in line if c.isupper()) > len(line) * 0.4
        )

        if re.match(r'^[•\-\*]\s+', line):
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            content = re.sub(r'^[•\-\*]\s+', '', line)
            content = re.sub(r'^([^:]+:)', r'<strong>\1</strong>', content)
            html.append(f"  <li>{content}</li>")
            continue

        if re.match(r'^\d+\.\s+', line):
            if in_ul:
                html.append("</ul>")
                in_ul = False
            content = re.sub(r'^\d+\.\s+', '', line)
            content = re.sub(r'^([^:]+:)', r'<strong>\1</strong>', content)
            html.append(f"<p>{content}</p>")
            continue

        if in_ul:
            html.append("</ul>")
            in_ul = False

        if is_heading:
            tag = "h2" if len(line) < 50 else "h3"
            html.append(f"<{tag}>{line}</{tag}>")
        else:
            html.append(f"<p>{line}</p>")

    if in_ul:
        html.append("</ul>")

    result = "\n".join(html)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

def post_to_blogger(cfg, access_token, title, html_content):
    url  = f"https://www.googleapis.com/blogger/v3/blogs/{cfg['blog_id']}/posts/"
    html_with_cta = (
        html_content +
        '\n\n<p><strong>Ready to move something?</strong> '
        '<a href="https://www.boothop.com">Visit BootHop.com</a> — '
        'compliance-first same-day and cross-border logistics.</p>'
    )
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
        },
        json={
            "kind":    "blogger#post",
            "title":   title,
            "content": html_with_cta,
        },
    )
    if r.ok:
        post_url = r.json().get("url", "")
        log(f"  Posted via API: {post_url}")
        return True
    log(f"  API error {r.status_code}: {r.text}")
    return False

def main():
    DROP.mkdir(parents=True, exist_ok=True)
    POSTED_PDFS.mkdir(parents=True, exist_ok=True)

    log("=" * 55)
    log("BootHop PDF Drop -> Blog starting")

    cfg   = load_config()
    pdfs  = sorted(DROP.glob("*.pdf"))

    if not pdfs:
        log("No PDFs found in blog/drop/ — nothing to post.")
        log("=" * 55)
        return

    log(f"Found {len(pdfs)} PDF(s) to post")

    access_token = get_access_token(cfg)

    for pdf_path in pdfs:
        log(f"Processing: {pdf_path.name}")
        try:
            title = title_from_filename(pdf_path.stem)
            log(f"  Title: {title}")

            raw_text = extract_pdf_text(pdf_path)
            if not raw_text.strip():
                log(f"  WARNING: Could not extract text from {pdf_path.name} — skipping")
                continue

            html = text_to_html(raw_text)
            ok   = post_to_blogger(cfg, access_token, title, html)

            if ok:
                dest = POSTED_PDFS / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{pdf_path.name}"
                shutil.move(str(pdf_path), dest)
                log(f"  Posted & moved to posted/pdfs/")
            else:
                log(f"  FAILED — PDF stays in drop/")

        except Exception as e:
            log(f"  ERROR processing {pdf_path.name}: {e}")

    log("All done.")
    log("=" * 55)

if __name__ == "__main__":
    main()
