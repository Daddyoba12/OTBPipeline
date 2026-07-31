"""
Re-authorize YouTube with comment scope added.
Run once on Windows laptop (opens a browser tab):
    python auth_youtube.py

Creates a new youtube_token.json with both upload + comment scopes.
Then SCP the new token to Oracle:
    scp -i %USERPROFILE%\.ssh\oracle_boothop.pem scripts\youtube_token.json ubuntu@140.238.73.32:/opt/otb_pipeline/scripts/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import YOUTUBE_TOKEN, YOUTUBE_CREDS

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # needed for comment posting
]

if not YOUTUBE_CREDS.exists():
    print(f"ERROR: {YOUTUBE_CREDS} not found")
    sys.exit(1)

from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(str(YOUTUBE_CREDS), SCOPES)
creds = flow.run_local_server(port=0)

YOUTUBE_TOKEN.write_text(creds.to_json())
print(f"\nToken saved to {YOUTUBE_TOKEN}")
print(f"Scopes: {creds.scopes}")
print("\nNow copy to Oracle:")
print(f'  scp -i %USERPROFILE%\\.ssh\\oracle_boothop.pem scripts\\youtube_token.json ubuntu@140.238.73.32:/opt/otb_pipeline/scripts/')
