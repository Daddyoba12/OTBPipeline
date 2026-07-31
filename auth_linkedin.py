"""
Re-authorize LinkedIn access token (run every ~55 days before it expires).
Usage: python auth_linkedin.py

Opens browser → you approve → you paste the redirect URL back → done.
No need to register a redirect URI — uses LinkedIn's own redirect tool URL.
"""

import json, sys, webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from config import CREDS_PATH

import requests

# LinkedIn's own OAuth redirect page (always pre-approved, no registration needed)
REDIRECT_URI = "https://www.linkedin.com/developers/tools/oauth/redirect"
SCOPES       = "openid profile w_member_social"

# ── Load credentials ────────────────────────────────────────────────────────────
try:
    creds = json.loads(Path(CREDS_PATH).read_text())
    li    = creds.get("linkedin", {})
    CLIENT_ID     = li.get("client_id", "").strip()
    CLIENT_SECRET = li.get("client_secret", "").strip()
except Exception as e:
    print(f"ERROR reading credentials: {e}"); sys.exit(1)

if not CLIENT_ID or not CLIENT_SECRET:
    print("ERROR: LinkedIn client_id or client_secret missing from social_credentials.json")
    sys.exit(1)

# ── Step 1: Build auth URL and open browser ─────────────────────────────────────
auth_url = (
    f"https://www.linkedin.com/oauth/v2/authorization"
    f"?response_type=code"
    f"&client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&scope={SCOPES.replace(' ', '%20')}"
)

webbrowser.open(auth_url)

# ── Popup dialog for URL paste (works regardless of how script is launched) ─────
import tkinter as tk
from tkinter import messagebox

root = tk.Tk()
root.title("LinkedIn Re-Authorization")
root.geometry("640x320")
root.resizable(False, False)
root.lift()
root.attributes("-topmost", True)

tk.Label(root, text="LinkedIn Authorization", font=("Arial", 14, "bold")).pack(pady=(16, 4))
tk.Label(root, text="1. Approve in the browser tab that just opened", font=("Arial", 11)).pack()
tk.Label(root, text="2. Copy the FULL URL from your browser address bar", font=("Arial", 11)).pack()
tk.Label(root, text="3. Paste it below and click OK", font=("Arial", 11)).pack(pady=(0, 10))

url_var = tk.StringVar()
entry = tk.Entry(root, textvariable=url_var, width=72, font=("Courier", 9))
entry.pack(padx=20, pady=6)
entry.focus_set()

result = {"url": ""}

def on_ok():
    result["url"] = url_var.get().strip()
    root.destroy()

def on_cancel():
    root.destroy()

btn_frame = tk.Frame(root)
btn_frame.pack(pady=10)
tk.Button(btn_frame, text="OK", width=12, command=on_ok, bg="#0077B5", fg="white",
          font=("Arial", 11, "bold")).pack(side="left", padx=8)
tk.Button(btn_frame, text="Cancel", width=12, command=on_cancel,
          font=("Arial", 11)).pack(side="left", padx=8)

tk.Label(root, text="(If browser didn't open, the URL was printed in the terminal)",
         font=("Arial", 9), fg="gray").pack()
tk.Label(root, text=auth_url[:80] + "...", font=("Courier", 7), fg="gray", wraplength=600).pack()

root.mainloop()

redirect_url = result["url"]
if not redirect_url:
    print("Cancelled."); sys.exit(0)

# ── Step 2: Extract code from URL ───────────────────────────────────────────────
try:
    parsed = urlparse(redirect_url)
    qs     = parse_qs(parsed.query)
    code   = (qs.get("code") or qs.get("authorization_code") or [""])[0]
    if not code and "code=" in redirect_url:
        code = redirect_url.split("code=")[1].split("&")[0]
except Exception:
    code = ""

if not code:
    # Last resort: maybe they pasted just the code itself
    code = redirect_url.strip()

if not code:
    print("ERROR: No auth code found — aborting"); sys.exit(1)

print(f"\nAuth code received ({code[:20]}...). Exchanging for token...")

# ── Step 3: Exchange code for access token ──────────────────────────────────────
r = requests.post(
    "https://www.linkedin.com/oauth/v2/accessToken",
    data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    },
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    timeout=20,
)
token_data = r.json()
access_token = token_data.get("access_token", "")
expires_in   = token_data.get("expires_in", 5184000)

if not access_token:
    print(f"ERROR: Token exchange failed: {token_data}")
    sys.exit(1)

print(f"Token received (valid for {expires_in // 86400} days)")

# ── Step 4: Get person URN ──────────────────────────────────────────────────────
me = requests.get(
    "https://api.linkedin.com/v2/me",
    headers={"Authorization": f"Bearer {access_token}"},
    timeout=15,
).json()

person_id  = me.get("id", "")
first_name = me.get("localizedFirstName", "")
last_name  = me.get("localizedLastName", "")
person_urn = f"urn:li:person:{person_id}" if person_id else li.get("person_urn", "")

if not person_id:
    # Try OpenID userinfo endpoint
    try:
        ui = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        ).json()
        person_id  = ui.get("sub", "")
        first_name = ui.get("given_name", "")
        last_name  = ui.get("family_name", "")
        person_urn = f"urn:li:person:{person_id}" if person_id else person_urn
    except Exception:
        pass

print(f"Logged in as: {first_name} {last_name} ({person_urn})")

# ── Step 5: Save ────────────────────────────────────────────────────────────────
li["access_token"] = access_token
li["person_urn"]   = person_urn
li["expires_in"]   = expires_in
li["issued_at"]    = datetime.now().isoformat()
li.pop("refresh_token", None)

creds["linkedin"] = li
Path(CREDS_PATH).write_text(json.dumps(creds, indent=2, ensure_ascii=False))

from datetime import timedelta
expiry_date = (datetime.now() + timedelta(seconds=expires_in)).strftime('%Y-%m-%d')
print(f"\nSaved to {CREDS_PATH}")
print(f"Valid until: {expiry_date}")
print("\nLinkedIn re-authorized. Pipeline will post at next slot 4 run (Tue/Fri 08:00).")
