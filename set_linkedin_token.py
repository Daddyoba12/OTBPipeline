"""
Paste a LinkedIn access token manually (from linkedin.com/developers/tools/oauth/token-generator).
Usage: python set_linkedin_token.py
"""
import json, sys, tkinter as tk
from tkinter import simpledialog
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CREDS_PATH

root = tk.Tk(); root.withdraw()
token = simpledialog.askstring(
    "LinkedIn Token",
    "Paste your LinkedIn access token from\nlinkedin.com/developers/tools/oauth/token-generator",
    parent=root
)
if not token or not token.strip():
    print("No token entered — cancelled."); sys.exit(0)

token = token.strip()

creds = json.loads(Path(CREDS_PATH).read_text())
li    = creds.get("linkedin", {})
li["access_token"] = token
li["issued_at"]    = datetime.now().isoformat()
li["expires_in"]   = 5184000  # 60 days
creds["linkedin"]  = li
Path(CREDS_PATH).write_text(json.dumps(creds, indent=2, ensure_ascii=False))

expiry = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
print(f"Token saved. Valid until ~{expiry}")
print("LinkedIn will post again at next Tue/Fri slot 4.")
