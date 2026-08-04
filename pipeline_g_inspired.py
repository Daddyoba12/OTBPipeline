"""
G-Inspired Automall — Pipeline Orchestrator

Slot 1 (daily):  Pick car → Generate script → Render video → Email to Ebube
Slot 4 (Tue/Fri): LinkedIn article + SEO blog post → Email blog to Ebube → Post LinkedIn

Architecture: laptop is primary; Oracle fires 1 hour later as failsafe.
After laptop runs, pipeline pushes ran_today signal to Oracle so Oracle skips.

Run manually:
  python pipeline_g_inspired.py --slot 1
  python pipeline_g_inspired.py --slot 4
  python pipeline_g_inspired.py --slot 1 --force
"""

import sys, json, os, subprocess, time
from datetime import datetime, date
from pathlib import Path

import platform as _plat_detect
BASE = (Path(r"C:\Users\babso\Desktop\OTB_Pipeline")
        if _plat_detect.system() == "Windows"
        else Path(__file__).resolve().parent)

sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

for _p in [r"C:\ffmpeg\bin", r"C:\Python314", r"C:\Python314\Scripts"]:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import DATA as _DATA, OUTPUT as _OUTPUT, TEMP as _TEMP

_client_base = os.environ.get("OTB_CLIENT_BASE")
if _client_base:
    _cb    = Path(_client_base)
    DATA   = _cb / "data"
    OUTPUT = _cb / "output"
    TEMP   = _cb / "temp"
    CLIENT_PROFILE = _cb / "client_profile.json"
else:
    DATA   = _DATA
    OUTPUT = _OUTPUT
    TEMP   = _TEMP
    CLIENT_PROFILE = BASE / "client_profiles" / "g-inspired.json"

for _d in [DATA, OUTPUT, TEMP]:
    _d.mkdir(exist_ok=True)

RAN_TODAY_S1 = DATA / "g_inspired_ran_today.json"
RAN_TODAY_S4 = DATA / "g_inspired_ran_today_s4.json"


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def _already_ran_today(slot: int) -> bool:
    f = RAN_TODAY_S4 if slot == 4 else RAN_TODAY_S1
    if not f.exists():
        return False
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d.get("date") == datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False


def _mark_ran_today(slot: int):
    f = RAN_TODAY_S4 if slot == 4 else RAN_TODAY_S1
    f.write_text(
        json.dumps({"date": datetime.now().strftime("%Y-%m-%d"),
                    "ran_at": datetime.now().isoformat(), "slot": slot}),
        encoding="utf-8",
    )


def _push_ran_signal_to_oracle(slot: int):
    """Push the ran-today file to Oracle so the 1-hour backup cron skips."""
    if os.name != "nt":
        return  # only push from Windows laptop
    key = Path.home() / ".ssh" / "oracle_boothop.pem"
    f   = RAN_TODAY_S4 if slot == 4 else RAN_TODAY_S1
    if not key.exists() or not f.exists():
        return
    try:
        subprocess.run(
            ["scp", "-i", str(key), "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
             str(f),
             f"ubuntu@140.238.73.32:/opt/g_inspired/data/{f.name}"],
            timeout=12, capture_output=True,
        )
    except Exception:
        pass


def _load_profile() -> dict:
    try:
        return json.loads(CLIENT_PROFILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── LinkedIn (text-only post) ──────────────────────────────────────────────────

def _post_gi_linkedin(weekly: dict, profile: dict) -> str | None:
    """Post a text-only LinkedIn article for G-Inspired. Returns post URN or None."""
    import requests as _req

    # Creds from G-Inspired client folder's social_credentials.json
    gi_creds_path = CLIENT_PROFILE.parent / "social_credentials.json"
    try:
        creds_data = json.loads(gi_creds_path.read_text(encoding="utf-8"))
        li_creds   = creds_data.get("linkedin", {})
        token      = li_creds.get("access_token", "").strip()
        person_urn = li_creds.get("person_urn", "").strip()
    except Exception as e:
        _log(f"[LinkedIn] Creds load failed: {e}")
        return None

    if not token or not person_urn:
        _log("[LinkedIn] No G-Inspired LinkedIn credentials — skipping")
        return None

    # Weekdays only
    if date.today().weekday() >= 5:
        _log("[LinkedIn] Weekend — skipping")
        return None

    text    = weekly.get("linkedin_text", "")
    website = profile.get("website", "https://www.ginspiredautomall.com")

    auth_h = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    _log(f"[LinkedIn] Posting text article ({len(text)} chars)...")
    try:
        r = _req.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=auth_h,
            json={
                "author": person_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
            timeout=30,
        )
        r.raise_for_status()
        post_urn = r.json().get("id", "")
    except Exception as e:
        _log(f"[LinkedIn] Post failed: {e}")
        return None

    if not post_urn:
        _log("[LinkedIn] No URN returned")
        return None

    _log(f"[LinkedIn] Posted ✓ URN: {post_urn}")

    # First comment = website link (avoids algo demotion for link-in-body)
    time.sleep(3)
    try:
        _req.post(
            "https://api.linkedin.com/v2/socialActions/{}/comments".format(
                __import__("requests").utils.quote(post_urn, safe="")
            ),
            headers=auth_h,
            json={"actor": person_urn,
                  "message": {"text": f"🚗 Browse our inventory with zero hidden fees → {website}"}},
            timeout=15,
        )
    except Exception:
        pass

    return post_urn


# ── Blog email ─────────────────────────────────────────────────────────────────

def _email_gi_blog(weekly: dict, profile: dict) -> bool:
    """Email the generated blog post HTML to Ebube."""
    try:
        from email_video import send_email_raw
    except ImportError:
        _log("[Blog] email_video.send_email_raw not available — saving locally only")
        return _save_blog_locally(weekly)

    delivery   = profile.get("delivery", {})
    to_email   = delivery.get("to", "info@kreativerock.com")
    title      = weekly.get("blog_title", "G-Inspired Blog Post")
    html_body  = weekly.get("blog_html", "")
    today      = date.today().strftime("%B %d, %Y")
    website    = profile.get("website", "https://www.ginspiredautomall.com")

    email_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;">

<div style="background:#1D3A6E;color:#fff;padding:20px;border-radius:8px;margin-bottom:24px;">
  <h2 style="margin:0;font-size:18px;">📝 G-Inspired Automall — Blog Post Ready</h2>
  <p style="margin:8px 0 0;opacity:.8;font-size:14px;">{today} · Copy and paste this into your website</p>
</div>

<h1 style="color:#1D3A6E;font-size:24px;">{title}</h1>
<p style="color:#666;font-size:13px;">Labels: {weekly.get('blog_labels','')}</p>
<hr style="border:1px solid #eee;margin:20px 0;">

{html_body}

<hr style="border:1px solid #eee;margin:32px 0 16px;">
<p style="color:#999;font-size:12px;text-align:center;">
  Generated by G-Inspired Automall Pipeline · <a href="{website}">{website}</a>
</p>
</body>
</html>"""

    try:
        ok = send_email_raw(
            to=to_email,
            subject=f"[G-Inspired Blog] {title}",
            html_body=email_html,
            cc=delivery.get("cc", ""),
        )
        if ok:
            _log(f"[Blog] Email sent to {to_email} ✓")
        else:
            _log(f"[Blog] Email failed — saving locally")
            _save_blog_locally(weekly)
        return ok
    except Exception as e:
        _log(f"[Blog] Email error: {e} — saving locally")
        return _save_blog_locally(weekly)


def _save_blog_locally(weekly: dict) -> bool:
    """Save blog HTML to a pending folder as fallback."""
    try:
        pending = CLIENT_PROFILE.parent / "blog" / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        slug  = weekly.get("angle", "post").replace(" ", "-")
        fname = pending / f"{today}_{slug}.html"
        title = weekly.get("blog_title", "")
        labels = weekly.get("blog_labels", "")
        body  = weekly.get("blog_html", "")
        fname.write_text(f"<!-- title: {title} -->\n<!-- labels: {labels} -->\n{body}",
                         encoding="utf-8")
        _log(f"[Blog] Saved locally: {fname.name}")
        return True
    except Exception as e:
        _log(f"[Blog] Local save failed: {e}")
        return False


# ── Slot runners ───────────────────────────────────────────────────────────────

def _run_slot1(profile: dict):
    """Daily video: Pick car → Generate script → Render → Upload → Email."""
    delivery = profile.get("delivery", {})
    to_email = delivery.get("to", "info@kreativerock.com")

    _log("Step 1: Picking car and generating content...")
    try:
        from g_inspired_content import generate_content
        content = generate_content()
    except Exception as e:
        _log(f"Content generation failed: {e}")
        return False

    car = content.get("car", {})
    _log(f"Car: {car.get('year')} {car.get('make')} {car.get('model')} — ${car.get('price', 0):,}")
    _log(f"Hook: {content.get('hook', '')}")

    _log("Step 2: Rendering video...")
    ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_file = OUTPUT / f"g_inspired_{ts}.mp4"

    try:
        from render_video import render_video
        ok, used_ids = render_video(content, slot=1, output_path=str(video_file), version="v1")
    except Exception as e:
        _log(f"Render failed: {e}")
        return False

    if not ok or not video_file.exists():
        _log("Render produced no output — aborting.")
        return False

    size_mb = video_file.stat().st_size / 1_048_576
    _log(f"Video ready: {video_file.name} ({size_mb:.1f} MB)")

    slug      = profile.get("slug", "g-inspired")
    video_url = ""
    try:
        from push_pipeline_state import _upload_video
        store_key = f"pipeline/{slug}/daily_{ts}.mp4"
        video_url = _upload_video(str(video_file), store_key)
        if video_url:
            _log(f"Uploaded → {video_url[:80]}")
    except Exception as e:
        _log(f"Supabase upload skipped: {e}")

    # Push slot state so Commander shows today's video
    try:
        from push_pipeline_state import push_slot_state
        content["rendered_at"] = datetime.now().isoformat()
        push_slot_state(1, content, v1_path=str(video_file), company_slug=slug)
        _log("Slot state synced to Supabase ✓")
    except Exception as e:
        _log(f"Supabase slot push skipped: {e}")

    # Append to shared post_log.json so Commander history works for this client
    try:
        shared_log = BASE / "data" / "post_log.json"
        shared_log.parent.mkdir(exist_ok=True)
        log = json.loads(shared_log.read_text(encoding="utf-8")) if shared_log.exists() else []
        log.append({
            "company_slug": slug,
            "platform":     "email",
            "slot":         1,
            "hook":         content.get("hook", ""),
            "video_url":    video_url,
            "date":         datetime.now().strftime("%Y-%m-%d"),
            "posted_at":    datetime.now().isoformat(),
        })
        shared_log.write_text(json.dumps(log[-200:], indent=2), encoding="utf-8")
        _log("Post log updated ✓")
    except Exception as e:
        _log(f"Post log update skipped: {e}")

    _log(f"Step 3: Emailing video to {to_email}...")
    try:
        from email_video import send_video_email
        sent = send_video_email(
            to=to_email,
            content=content,
            video_path=str(video_file),
            video_url=video_url,
            cc=delivery.get("cc", ""),
        )
        if sent:
            _log("Email delivered ✓")
        else:
            _log("Email failed — video saved locally at: " + str(video_file))
    except Exception as e:
        _log(f"Email step failed: {e} — video saved at: {video_file}")

    try:
        record = {
            "date":       datetime.now().isoformat(),
            "car":        content.get("car_featured", ""),
            "hook":       content.get("hook", ""),
            "video_file": str(video_file),
            "video_url":  video_url,
            "emailed_to": to_email,
        }
        log_file = DATA / "g_inspired_run_log.json"
        log = json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else []
        log.append(record)
        log_file.write_text(json.dumps(log[-30:], indent=2), encoding="utf-8")
    except Exception:
        pass

    return True


def _run_slot4(profile: dict):
    """Tue/Fri: Generate LinkedIn article + Blog post → Post + Email."""
    _log("Step 1: Generating weekly LinkedIn + blog content...")
    try:
        from g_inspired_content import generate_weekly_content
        weekly = generate_weekly_content(profile=profile)
    except Exception as e:
        _log(f"Weekly content generation failed: {e}")
        return False

    _log(f"Topic: {weekly.get('topic')}")

    # Post LinkedIn
    _log("Step 2: Posting to LinkedIn...")
    li_urn = _post_gi_linkedin(weekly, profile)
    if li_urn:
        _log(f"LinkedIn posted ✓ ({li_urn})")
    else:
        _log("LinkedIn post skipped (no creds or weekend)")

    # Email blog
    _log("Step 3: Emailing blog post to client...")
    blog_ok = _email_gi_blog(weekly, profile)

    try:
        record = {
            "date":         datetime.now().isoformat(),
            "topic":        weekly.get("topic", ""),
            "linkedin_urn": li_urn or "",
            "blog_emailed": blog_ok,
        }
        log_file = DATA / "g_inspired_weekly_log.json"
        log = json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else []
        log.append(record)
        log_file.write_text(json.dumps(log[-30:], indent=2), encoding="utf-8")
    except Exception:
        pass

    return True


# ── Main ───────────────────────────────────────────────────────────────────────

def run(slot: int = 1, force: bool = False):
    _log("=" * 56)
    _log(f"G-Inspired Automall Pipeline — Slot {slot}")
    _log("=" * 56)

    if not force and _already_ran_today(slot):
        _log(f"Slot {slot} already ran today — skipping. (use --force to override)")
        return

    DATA.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    TEMP.mkdir(exist_ok=True)

    profile = _load_profile()

    if slot == 1:
        ok = _run_slot1(profile)
    elif slot == 4:
        ok = _run_slot4(profile)
    else:
        _log(f"Slot {slot} not implemented for G-Inspired (use 1 or 4)")
        return

    if ok:
        _mark_ran_today(slot)
        _push_ran_signal_to_oracle(slot)
        _log(f"G-Inspired Slot {slot} complete ✓")
    else:
        _log(f"G-Inspired Slot {slot} finished with errors")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="G-Inspired Automall pipeline")
    p.add_argument("--slot",  type=int, default=1, choices=[1, 4],
                   help="1=daily video  4=LinkedIn+Blog (Tue/Fri)")
    p.add_argument("--force", action="store_true", help="Run even if already ran today")
    args = p.parse_args()
    run(slot=args.slot, force=args.force)
