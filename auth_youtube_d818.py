"""
Authorize YouTube uploads for D818's channel.
Run once on the Windows laptop (opens a browser tab):
    python auth_youtube_d818.py

IMPORTANT: log in with the Google account that owns D818's YouTube channel —
NOT the account used for BootHop's youtube_token.json. This writes a
separate token file (youtube_token_d818.json) so the two channels can
never cross-post.

Reuses the same OAuth app (youtube_credentials.json) as BootHop — that's just
the registered app identity, not a channel. Which channel gets authorized
depends entirely on which Google account you log into below.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import YOUTUBE_TOKEN_D818, YOUTUBE_CREDS

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

if not YOUTUBE_CREDS.exists():
    print(f"ERROR: {YOUTUBE_CREDS} not found")
    sys.exit(1)

from google_auth_oauthlib.flow import InstalledAppFlow

print("A browser window will open — log in with D818's YouTube channel account.")
flow = InstalledAppFlow.from_client_secrets_file(str(YOUTUBE_CREDS), SCOPES)
creds = flow.run_local_server(port=0)

YOUTUBE_TOKEN_D818.write_text(creds.to_json())
print(f"\nToken saved to {YOUTUBE_TOKEN_D818}")
print(f"Scopes: {creds.scopes}")
print("\nD818 is now ready to post to YouTube.")
