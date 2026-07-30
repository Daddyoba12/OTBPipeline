"""
OTB Pipeline — Email video delivery
Sends the rendered video (or a Supabase link) to the client via Gmail SMTP.
Used when a client has no social media credentials yet.

Requires in keys.env:
  GMAIL_USER         = your.gmail@gmail.com
  GMAIL_APP_PASSWORD = xxxx xxxx xxxx xxxx   (Google App Password — not your regular password)
  Get one at: myaccount.google.com/apppasswords
"""

import os, sys, smtplib, json
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.mime.base      import MIMEBase
from email               import encoders
from pathlib              import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import BASE

# ── Credentials from keys.env ─────────────────────────────────────────────────

def _load_gmail_creds() -> tuple[str, str]:
    keys_env = BASE / "keys.env"
    gmail_user = gmail_pass = ""
    if keys_env.exists():
        for ln in keys_env.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if "=" in ln and not ln.startswith("#"):
                k, _, v = ln.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k == "GMAIL_USER":
                    gmail_user = v
                elif k == "GMAIL_APP_PASSWORD":
                    gmail_pass = v
    return gmail_user, gmail_pass


# ── Email builder ─────────────────────────────────────────────────────────────

def _build_body(content: dict, video_url: str = "") -> str:
    car         = content.get("car", {})
    brand       = content.get("brand_name", "G-Inspired Automall")
    contact     = content.get("contact_name", "")
    car_name    = f"{car.get('year','')} {car.get('make','')} {car.get('model','')}"
    price       = f"${car.get('price', 0):,}" if car.get("price") else ""
    hook        = content.get("hook", "")
    caption_tt  = content.get("caption_tiktok", "")
    caption_ig  = content.get("caption_instagram", "")
    engagement  = content.get("engagement", "")

    video_line = (
        f"\n📹 VIDEO LINK (download or share directly):\n{video_url}\n"
        if video_url else ""
    )

    return f"""Hi {contact or 'there'},

Your daily video is ready for {brand}!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEATURED CAR: {car_name} — {price}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{video_line}
VIDEO SCRIPT:
  Hook       : {hook}
  Caption TT : {caption_tt}
  Caption IG : {caption_ig}
  Engagement : {engagement}

HOW TO POST:
  1. Download the video from the link above (or see attachment)
  2. Post to TikTok, Instagram Reels, or Facebook
  3. Copy the caption above into the post
  4. Tag the car in the comments with price + mileage

Once you have TikTok/Instagram/WhatsApp details ready, we can automate posting directly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
G-Inspired Automall Pipeline | Powered by OTB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


# ── Send ──────────────────────────────────────────────────────────────────────

def send_video_email(
    to: str,
    content: dict,
    video_path: str = "",
    video_url: str = "",
    cc: str = "",
) -> bool:
    """
    Send rendered video to client via Gmail.

    to:         recipient email (from client_profile delivery.to)
    content:    content dict from g_inspired_content.generate_content()
    video_path: local path to .mp4 — attached if under 20MB, otherwise link only
    video_url:  Supabase URL — included in body if provided
    cc:         optional CC address
    """
    gmail_user, gmail_pass = _load_gmail_creds()
    if not gmail_user or not gmail_pass:
        print("[EmailVideo] GMAIL_USER or GMAIL_APP_PASSWORD missing from keys.env — skipping email.")
        print("  Add them at: myaccount.google.com/apppasswords")
        return False

    car      = content.get("car", {})
    brand    = content.get("brand_name", "G-Inspired Automall")
    car_name = f"{car.get('year','')} {car.get('make','')} {car.get('model','')}"
    subject  = f"{brand} — Video Ready: {car_name} | {datetime.now().strftime('%d %b %Y')}"

    msg = MIMEMultipart()
    msg["From"]    = gmail_user
    msg["To"]      = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc

    msg.attach(MIMEText(_build_body(content, video_url), "plain"))

    # Attach video if under 20MB
    if video_path and Path(video_path).exists():
        size_mb = Path(video_path).stat().st_size / 1_048_576
        if size_mb <= 20:
            print(f"[EmailVideo] Attaching video ({size_mb:.1f} MB)...")
            with open(video_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            fname = Path(video_path).name
            part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
            msg.attach(part)
        else:
            print(f"[EmailVideo] Video too large to attach ({size_mb:.1f} MB) — link only.")

    recipients = [to] + ([cc] if cc else [])

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipients, msg.as_string())
        print(f"[EmailVideo] Sent to {to} ✓")
        return True
    except Exception as e:
        print(f"[EmailVideo] Failed: {e}")
        return False


def send_email_raw(
    to: str,
    subject: str,
    html_body: str,
    cc: str = "",
) -> bool:
    """Send a plain HTML email — used for blog post delivery."""
    gmail_user, gmail_pass = _load_gmail_creds()
    if not gmail_user or not gmail_pass:
        print("[Email] GMAIL_USER or GMAIL_APP_PASSWORD missing — skipping.")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"]    = gmail_user
    msg["To"]      = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc

    msg.attach(MIMEText(html_body, "html", "utf-8"))
    recipients = [to] + ([cc] if cc else [])

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipients, msg.as_string())
        print(f"[Email] Sent '{subject[:60]}' to {to} ✓")
        return True
    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--to",    required=True, help="Recipient email")
    p.add_argument("--video", default="",    help="Path to video file")
    p.add_argument("--url",   default="",    help="Supabase video URL")
    args = p.parse_args()
    # Minimal test content
    test_content = {
        "brand_name": "G-Inspired Automall",
        "contact_name": "Ebube",
        "car": {"year": 2018, "make": "Honda", "model": "CR-V", "price": 16995},
        "hook": "Would you drive this CR-V home today for under $17k?",
        "caption_tiktok": "CARFAX clean. Zero fees. Ready today.",
        "caption_instagram": "CARFAX clean. Zero fees. Ready today. ginspiredautomall.com",
        "engagement": "What car are you looking for right now?",
    }
    send_video_email(args.to, test_content, video_path=args.video, video_url=args.url)
