"""
BootHop Gmail-to-Blog Auto-Publisher
Runs daily via BootHop-GmailBlog task (09:00-13:00, every 30 min).
Reads Gmail via IMAP using App Password — no OAuth needed.
Looks for emails with subject: "New BotHop Blog Draft"
Posts body to Blogger via post-by-email (SMTP).
Deduplication via processed_emails.json.
"""
import sys, json, imaplib, email, smtplib, re
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
from datetime import datetime

MIN_WORD_COUNT  = 150   # posts below this are rejected as thin content
QUALITY_KEYWORDS = [
    "boothop", "delivery", "traveller", "logistics", "package", "shipment",
    "nigeria", "london", "lagos", "diaspora", "courier", "same-day", "same day",
]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE            = Path(__file__).parent
CONFIG_FILE     = BASE / "config.json"
LOG_FILE        = BASE / "gmail_blog_log.txt"
PROCESSED       = BASE / "processed_emails.json"
SUBJECT_TRIGGER = "New BotHop Blog Draft"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_config():
    if not CONFIG_FILE.exists():
        log("ERROR: config.json not found")
        raise SystemExit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

def load_processed():
    if PROCESSED.exists():
        return set(json.loads(PROCESSED.read_text(encoding="utf-8")))
    return set()

def save_processed(ids):
    PROCESSED.write_text(json.dumps(list(ids)), encoding="utf-8")

def decode_str(s):
    parts = decode_header(s)
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="replace")
        else:
            result += part
    return result

def get_body(msg):
    """Extract HTML body (preferred) or plain text from email."""
    html = ""
    plain = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ct == "text/html":
                html = text
            elif ct == "text/plain":
                plain = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html = text
            else:
                plain = text

    if html:
        return html
    if plain:
        # Wrap plain text in basic paragraphs
        paras = [f"<p>{line.strip()}</p>" for line in plain.split("\n") if line.strip()]
        return "\n".join(paras)
    return ""

def quality_check(html_body: str, title: str) -> tuple[bool, str]:
    """
    Return (pass: bool, reason: str).
    Rejects thin posts to protect Blogger SEO ranking.
    """
    plain = re.sub(r"<[^>]+>", " ", html_body)
    plain = re.sub(r"\s+", " ", plain).strip()
    words = len(plain.split())

    if words < MIN_WORD_COUNT:
        return False, f"Too short: {words} words (minimum {MIN_WORD_COUNT})"

    low = (plain + " " + title).lower()
    if not any(kw in low for kw in QUALITY_KEYWORDS):
        return False, "No BootHop-relevant keywords found — possible spam/off-topic"

    return True, "OK"


def post_to_blogger(cfg, title, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"]    = cfg["gmail_address"]
    msg["To"]      = cfg["blogger_email"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(cfg["gmail_address"], cfg["gmail_app_password"])
        server.sendmail(cfg["gmail_address"], cfg["blogger_email"], msg.as_string())
    log(f"  Posted to Blogger: {title}")
    return True

def main():
    log("=" * 55)
    log("Gmail-to-Blog checker starting (IMAP)")
    log(f"Looking for subject: '{SUBJECT_TRIGGER}'")

    cfg       = load_config()
    processed = load_processed()

    # Connect via IMAP using App Password
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        imap.login(cfg["gmail_address"], cfg["gmail_app_password"])
    except Exception as e:
        log(f"ERROR: IMAP login failed — {e}")
        return

    imap.select("INBOX")

    # Search for matching subject (today only)
    today = datetime.now().strftime("%d-%b-%Y")
    status, data = imap.search(None, f'(SUBJECT "{SUBJECT_TRIGGER}" SINCE "{today}")')
    if status != "OK":
        log("IMAP search failed")
        imap.logout()
        return

    msg_ids = data[0].split() if data[0] else []
    log(f"Found {len(msg_ids)} email(s) matching today")

    if not msg_ids:
        log("No new blog drafts today.")
        log("=" * 55)
        imap.logout()
        return

    posted = 0
    for uid in msg_ids:
        uid_str = uid.decode()
        if uid_str in processed:
            log(f"  Skipping already-processed UID: {uid_str}")
            continue

        _, msg_data = imap.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = decode_str(msg.get("Subject", SUBJECT_TRIGGER))
        title   = subject.replace(SUBJECT_TRIGGER, "").strip(" :-|")
        if not title:
            title = f"BootHop Update — {datetime.now().strftime('%d %b %Y')}"

        log(f"  Subject: {subject}")
        log(f"  Title:   {title}")

        body = get_body(msg)
        if not body or len(body.strip()) < 20:
            log("  WARNING: Empty body — skipping")
            continue

        passed, reason = quality_check(body, title)
        if not passed:
            log(f"  QUALITY GATE FAIL: {reason} — skipping post")
            continue
        log(f"  Quality check: PASS")

        try:
            post_to_blogger(cfg, title, body)
            processed.add(uid_str)
            posted += 1
        except Exception as e:
            log(f"  ERROR posting: {e}")

    imap.logout()
    save_processed(processed)
    log(f"Done. Posted {posted} new blog entry/entries.")
    log("=" * 55)

if __name__ == "__main__":
    main()
