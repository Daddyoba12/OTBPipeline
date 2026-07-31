"""
Re-authorize LinkedIn access token (run every ~55 days before it expires).
Usage: python auth_linkedin.py

Opens browser → you approve → you paste the redirect URL back → done.
No need to register a redirect URI — uses LinkedIn's own redirect tool URL.
"""

import json, sys, webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from config import CREDS_PATH

import requests

# Must be registered in LinkedIn Developer Portal → App → Auth → Authorized redirect URLs
REDIRECT_URI = "http://localhost:8080"
SCOPES       = "r_liteprofile w_member_social"

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

print("\n" + "="*60)
print("LINKEDIN RE-AUTHORIZATION")
print("="*60)
print("\nBrowser opening... Approve in LinkedIn then come back here.")
print("(Script catches the redirect automatically — no copy/paste needed)\n")

webbrowser.open(auth_url)

# ── Local server catches the OAuth callback automatically ───────────────────────
code = None

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global code
        qs   = parse_qs(urlparse(self.path).query)
        code = (qs.get("code") or [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if code:
            self.wfile.write(b"<h2 style='font-family:sans-serif;color:green'>"
                             b"LinkedIn authorized! You can close this tab.</h2>")
        else:
            self.wfile.write(b"<h2 style='font-family:sans-serif;color:red'>"
                             b"Error: no code received.</h2>")
    def log_message(self, *a): pass

print("Waiting for you to approve in the browser...")
server = HTTPServer(("localhost", 8080), _Handler)
server.handle_request()  # blocks until LinkedIn redirects back

if not code:
    print("ERROR: No auth code received — did you approve in LinkedIn?")
    sys.exit(1)

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
    headers={
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
    },
    timeout=15,
).json()

person_id  = me.get("id", "")
first_name = me.get("localizedFirstName", "")
last_name  = me.get("localizedLastName", "")
person_urn = f"urn:li:person:{person_id}" if person_id else li.get("person_urn", "")

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
