"""
LinkedIn access token re-authorization.
Usage: python auth_linkedin.py

Browser opens → approve → token saved automatically.
Requires http://localhost:8080 to be registered in your LinkedIn app:
  linkedin.com/developers/apps → your app → Auth → Authorized redirect URLs
"""

import json, sys, webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from config import CREDS_PATH

import requests

REDIRECT_URI = "http://localhost:8080"
# Only request w_member_social — person_urn is already saved in credentials
SCOPES = "w_member_social"

# ── Load credentials ─────────────────────────────────────────────────────────
try:
    creds = json.loads(Path(CREDS_PATH).read_text())
    li    = creds.get("linkedin", {})
    CLIENT_ID     = li.get("client_id", "").strip()
    CLIENT_SECRET = li.get("client_secret", "").strip()
    PERSON_URN    = li.get("person_urn", "").strip()
except Exception as e:
    print(f"ERROR reading credentials: {e}"); sys.exit(1)

if not CLIENT_ID or not CLIENT_SECRET:
    print("ERROR: client_id or client_secret missing from social_credentials.json")
    sys.exit(1)

# ── Step 1: Build auth URL ───────────────────────────────────────────────────
auth_url = (
    f"https://www.linkedin.com/oauth/v2/authorization"
    f"?response_type=code"
    f"&client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&scope={SCOPES}"
)

print("\n" + "="*60)
print("LINKEDIN RE-AUTHORIZATION")
print("="*60)
print(f"\nScope requested: {SCOPES}")
print(f"person_urn on file: {PERSON_URN}")
print("\nOpening browser — approve in LinkedIn then wait here...")
webbrowser.open(auth_url)

# ── Step 2: Local server catches callback ────────────────────────────────────
captured = {"code": None, "error": None, "full_path": None}

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        captured["full_path"] = self.path
        captured["code"]  = (qs.get("code")  or [None])[0]
        captured["error"] = (qs.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if captured["code"]:
            self.wfile.write(b"<h2 style='font-family:sans-serif;color:green'>"
                             b"Authorized! You can close this tab.</h2>")
        else:
            msg = f"LinkedIn error: {captured['error']}".encode()
            self.wfile.write(b"<h2 style='font-family:sans-serif;color:red'>" + msg + b"</h2>")
    def log_message(self, *a): pass

print("Waiting for LinkedIn callback on localhost:8080 ...")
HTTPServer(("localhost", 8080), _Handler).handle_request()

# ── Show exactly what came back ───────────────────────────────────────────────
print(f"\nCallback received: {captured['full_path']}")

if captured["error"]:
    print(f"\nLinkedIn returned an error: {captured['error']}")
    print("This usually means the app is missing a required product.")
    print("\nTo fix:")
    print("  1. Go to linkedin.com/developers/apps → your app → Products tab")
    print("  2. Add 'Share on LinkedIn' (enables w_member_social)")
    print("  3. Wait for approval (usually instant for development)")
    print("  4. Run this script again")
    sys.exit(1)

code = captured["code"]
if not code:
    print("ERROR: No code and no error — unexpected response"); sys.exit(1)

print(f"Auth code: {code[:20]}...")

# ── Step 3: Exchange code for token ─────────────────────────────────────────
r = requests.post(
    "https://www.linkedin.com/oauth/v2/accessToken",
    data={
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": REDIRECT_URI,
        "client_id":    CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    },
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    timeout=20,
)
token_data   = r.json()
access_token = token_data.get("access_token", "")
expires_in   = token_data.get("expires_in", 5184000)

if not access_token:
    print(f"ERROR: Token exchange failed: {token_data}"); sys.exit(1)

print(f"Token received — valid for {expires_in // 86400} days")

# ── Step 4: Keep existing person_urn (no extra API call needed) ──────────────
if not PERSON_URN:
    # Only fetch if not already on file
    try:
        me = requests.get(
            "https://api.linkedin.com/v2/me",
            headers={"Authorization": f"Bearer {access_token}",
                     "X-Restli-Protocol-Version": "2.0.0"},
            timeout=15,
        ).json()
        pid = me.get("id", "")
        PERSON_URN = f"urn:li:person:{pid}" if pid else ""
        print(f"person_urn fetched: {PERSON_URN}")
    except Exception as e:
        print(f"Could not fetch person_urn: {e}")

# ── Step 5: Save ─────────────────────────────────────────────────────────────
li["access_token"] = access_token
li["person_urn"]   = PERSON_URN
li["expires_in"]   = expires_in
li["issued_at"]    = datetime.now().isoformat()
li.pop("refresh_token", None)

creds["linkedin"] = li
Path(CREDS_PATH).write_text(json.dumps(creds, indent=2, ensure_ascii=False))

expiry = (datetime.now() + timedelta(seconds=expires_in)).strftime("%Y-%m-%d")
print(f"\nSaved to {CREDS_PATH}")
print(f"Token valid until: {expiry}")
print("LinkedIn re-authorized. Next Tue/Fri slot 4 will post again.")
