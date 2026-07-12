"""
BootHop Blogger Re-Auth — run when your refresh token expires.
Reads client_id/client_secret from blog/config.json automatically.
Usage:  python blog/setup_blogger.py
"""

import json, secrets, webbrowser, urllib.parse, threading, sys
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

BASE        = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
REDIRECT    = "http://localhost:8080/callback"
SCOPES      = "https://www.googleapis.com/auth/blogger"

if not CONFIG_FILE.exists():
    print("ERROR: blog/config.json not found.")
    print("Create it with: {\"client_id\": \"...\", \"client_secret\": \"...\", \"refresh_token\": \"\", \"blog_id\": \"...\"}")
    sys.exit(1)

cfg           = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
CLIENT_ID     = cfg["client_id"]
CLIENT_SECRET = cfg["client_secret"]

_result = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if "error" in params:
            _result["error"] = params.get("error_description", params["error"])[0]
            self.wfile.write(b"<h2>Google error. Close this tab.</h2>")
        elif "code" in params:
            _result["code"] = params["code"][0]
            self.wfile.write(b"<h2>Authorised! You can close this tab.</h2>")
        else:
            _result["error"] = "No code received"
            self.wfile.write(b"<h2>No code received.</h2>")

        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):
        pass


def run():
    state    = secrets.token_urlsafe(16)
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id":     CLIENT_ID,
            "redirect_uri":  REDIRECT,
            "response_type": "code",
            "scope":         SCOPES,
            "state":         state,
            "access_type":   "offline",
            "prompt":        "consent",
        })
    )

    print("\n" + "=" * 60)
    print("  BootHop Blogger Re-Auth")
    print("=" * 60)
    print(f"\n  Opening browser — sign in with the Google account")
    print(f"  that owns your Blogger blog, then click Allow...\n")
    print(f"  URL:\n  {auth_url}\n")
    print("  Waiting for Google redirect to localhost:8080...")

    webbrowser.open(auth_url)

    try:
        server = HTTPServer(("localhost", 8080), CallbackHandler)
        server.serve_forever()
    except OSError as e:
        print(f"\n  ERROR: Port 8080 in use. Close other apps and retry.\n  {e}")
        return

    if "error" in _result:
        print(f"\n  ERROR: {_result['error']}")
        return

    code = _result.get("code")
    if not code:
        print("\n  ERROR: No code received.")
        return

    print(f"\n  Code received. Exchanging for tokens...")

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code":          code,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri":  REDIRECT,
        "grant_type":    "authorization_code",
    }, timeout=30)

    if not r.ok:
        print(f"\n  ERROR: {r.text}")
        return

    tokens        = r.json()
    refresh_token = tokens.get("refresh_token", "")
    access_token  = tokens.get("access_token", "")

    if not refresh_token:
        print("\n  ERROR: No refresh_token returned. Try revoking app access at")
        print("  https://myaccount.google.com/permissions then re-run.")
        return

    # Update config.json with new refresh token (keep blog_id)
    cfg["refresh_token"] = refresh_token
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Verify by listing blogs
    blogs_r = requests.get(
        "https://www.googleapis.com/blogger/v3/users/self/blogs",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    blogs = blogs_r.json().get("items", []) if blogs_r.ok else []

    print(f"\n  SUCCESS!")
    print(f"  Refresh token saved to blog/config.json")
    if blogs:
        print(f"  Blogs found:")
        for b in blogs:
            marker = " <- active" if b["id"] == cfg.get("blog_id") else ""
            print(f"    {b['name']}  (ID: {b['id']}){marker}")
    print("=" * 60)


if __name__ == "__main__":
    run()
