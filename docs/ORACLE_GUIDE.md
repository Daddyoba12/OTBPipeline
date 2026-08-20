# OTB Oracle Cloud — Complete Operations Guide

**Server:** Oracle Cloud Free Tier (Amsterdam region)
**IP:** `140.238.73.32`
**User:** `ubuntu`
**SSH Key:** `C:\Users\babso\.ssh\oracle_boothop.pem` (laptop) — keep this file safe
**Last verified:** August 2026

---

## What Oracle Does

Oracle is a 24/7 Linux server that runs independently of your laptop. It:

- Runs the full content pipeline for every client (video generation, AI content, social posting)
- Hosts the Telegram commander bot (always on — never misses a message)
- Posts to TikTok, Instagram, YouTube, LinkedIn even when your laptop is off
- Runs as a **backup** for the laptop: if the laptop runs first, Oracle skips that slot automatically
- Runs G-Inspired and any new client independently on their own schedule
- Handles the weekly intelligence run every Monday
- Runs the engagement bot every 2 hours

If your laptop is off for a week, Oracle keeps posting on schedule for all clients.

---

## How to Connect from Anywhere

### From any Windows laptop (with the SSH key)

Copy `oracle_boothop.pem` to your new laptop at `C:\Users\<yourname>\.ssh\oracle_boothop.pem`, then:

```powershell
ssh -i C:\Users\babso\.ssh\oracle_boothop.pem ubuntu@140.238.73.32
```

### From Mac or Linux

```bash
chmod 400 ~/oracle_boothop.pem
ssh -i ~/oracle_boothop.pem ubuntu@140.238.73.32
```

### From your phone / any browser (no SSH key needed)

Go to **https://boothop.com/commander** and log in. This gives you:
- Pipeline status for all clients
- Post approval / skip / regen
- Rerun any slot
- View recent posts and errors

### Via Telegram (from anywhere)

Open Telegram and send commands to the OTB bot. Works from any phone or device:
- `/menu` — full control panel
- `/status` — see what ran today
- `/rerun 2` — trigger a pipeline run
- `/pause boothop` — pause a client
- `/revoice 3` — revoice a slot video

---

## Super User (Admin Access)

There is one super user for the entire system:

| Detail | Value |
|--------|-------|
| **Telegram account** | The account that owns chat ID `8641867751` |
| **Telegram bot** | Token in `social_credentials.json` → `telegram.bot_token` |
| **SSH access** | `ubuntu@140.238.73.32` with `oracle_boothop.pem` |
| **Web dashboard** | `boothop.com/commander` (Supabase login) |
| **GitHub repo** | `Daddyoba12/OTBPipeline` — all code lives here |

The super user can control ALL clients from one Telegram chat. The bot listens on one chat ID and the commander handles routing by client slug.

> **Security rule:** Never share `oracle_boothop.pem` or `social_credentials.json`. If a token is leaked, rotate it at the issuing platform and update the file on both laptop and Oracle.

---

## Client Directory

### BootHop (primary client)

| Detail | Value |
|--------|-------|
| **Slug** | `otb_midas` |
| **Oracle path** | `/opt/otb_pipeline` |
| **Laptop path** | `C:\users\babso\desktop\otb_pipeline` |
| **TikTok** | `boothop.com` account (production API pending; sandbox active) |
| **Instagram** | `boothop.com1` (username), App ID `1310582383924280` |
| **YouTube** | API key in `social_credentials.json` → `youtube` |
| **LinkedIn** | Titi Olufeko personal page |
| **Social creds file** | `/opt/otb_pipeline/scripts/social_credentials.json` |
| **Config** | `/opt/otb_pipeline/config.py` |
| **Log** | `/home/ubuntu/otb_pipeline.log` |

**BootHop daily schedule on Oracle (UTC):**

| UTC time | What runs |
|----------|-----------|
| 08:00 | Slot 1 (TikTok + IG + YouTube + Newspaper) |
| 14:00 | Slot 2 (TikTok + IG + YouTube) |
| 21:00 | Slot 3 (TikTok + IG + YouTube) |
| 08:00 Tue/Fri | Slot 4 (TikTok + YouTube — weekend boost) |
| Every 2h | Engagement bot (likes, comments) |
| Mon 05:30 | Weekly intelligence (trend scout + review) |

Each slot checks `data/pipeline_ran_today.json` — if the laptop already ran that slot, Oracle skips it.

---

### G-Inspired Automall (client 2)

| Detail | Value |
|--------|-------|
| **Slug** | `g-inspired` |
| **Brand** | G-Inspired Automall LLC |
| **Niche** | Used car dealership, Washington IL |
| **Website** | `ginspiredautomall.com` |
| **Contact** | Ebube — `info@kreativerock.com` |
| **Oracle path** | `/opt/g_inspired` |
| **Config** | `/opt/g_inspired/client_profile.json` |
| **Credentials** | `/opt/g_inspired/keys.env` |
| **Log** | `/home/ubuntu/g_inspired.log` |

**G-Inspired schedule on Oracle (UTC):**

| UTC time | What runs |
|----------|-----------|
| 15:00 daily | Slot 1 |
| 19:00 daily | Slot 1 (second daily post) |
| 10:00 Tue/Fri | Slot 4 |

Content uses live inventory from `cars.com` dealer feed. Videos rendered with G-Inspired branding. Posts delivered via email to Ebube if social posting is not configured.

---

## How to Onboard a New Client

### Step 1 — Create the client folder on Oracle

```bash
ssh -i oracle_boothop.pem ubuntu@140.238.73.32
sudo mkdir -p /opt/<client_slug>/{data,output,temp,assets/fonts,music/daily}
sudo chown -R ubuntu:ubuntu /opt/<client_slug>
```

### Step 2 — Create `client_profile.json`

Copy from G-Inspired as a template:
```bash
cp /opt/g_inspired/client_profile.json /opt/<client_slug>/client_profile.json
nano /opt/<client_slug>/client_profile.json
```

Fill in: `slug`, `brand_name`, `niche`, `website`, `industry`, `contact_email`, social handles.

### Step 3 — Add credentials

Create `/opt/<client_slug>/keys.env`:
```
TIKTOK_ACCESS_TOKEN=...
INSTAGRAM_ACCESS_TOKEN=...
INSTAGRAM_ACCOUNT_ID=...
YOUTUBE_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

Or add a new section to `/opt/otb_pipeline/scripts/social_credentials.json`.

### Step 4 — Add cron jobs

```bash
crontab -e
```

Add:
```
0 9 * * * cd /opt/otb_pipeline && OTB_CLIENT_BASE=/opt/<client_slug> python3 pipeline.py --slot 1 >> /home/ubuntu/<client>.log 2>&1
0 18 * * * cd /opt/otb_pipeline && OTB_CLIENT_BASE=/opt/<client_slug> python3 pipeline.py --slot 2 >> /home/ubuntu/<client>.log 2>&1
```

### Step 5 — Add to commander

In `scripts/telegram_commander.py`, add the client to the `_PIPELINES` dict:
```python
"<slug>": {
    "label":          "<Brand Name>",
    "local_profile":  None,
    "oracle_profile": "/opt/<client_slug>/client_profile.json",
    "tasks":          [],
},
```

The super user can then pause/resume it from Telegram with `/pause <slug>`.

---

## Commander Bot — How It Connects to Oracle

The Telegram commander runs on Oracle as a **systemd service** (`otb-commander.service`). It is always on, even when the laptop is off.

```
Status:  active (running) since Aug 2026
PID:     lives in /opt/otb_pipeline/data/commander.pid
Restart: automatic (RestartSec=10s)
Log:     journalctl -u otb-commander -n 50
```

### Commander service commands (from Oracle SSH)

```bash
# Check status
sudo systemctl status otb-commander

# Restart (after code change)
sudo systemctl restart otb-commander

# View live logs
sudo journalctl -u otb-commander -f

# Stop / Start
sudo systemctl stop otb-commander
sudo systemctl start otb-commander
```

### What the commander handles

| Trigger | Action |
|---------|--------|
| `/menu` | Shows full control panel with inline buttons |
| `/status` | Today's posts, last error, current step |
| `/rerun 1` | Runs pipeline slot 1 right now |
| `/pause boothop` | Pauses BootHop pipeline (sets `active: false` in profile) |
| `/pause g-inspired` | Pauses G-Inspired pipeline on Oracle |
| `/pause all` | Pauses everything |
| `/revoice 3` | Opens revoice studio for slot 3 (record voice or auto TTS) |
| `/v2 3` | Forces V2 Kling video for slot 3 next run |
| `/music <query>` | Downloads music from YouTube |
| Send voice note | Saved as revoice recording |
| Send video/photo | Saved to `user_clips/` as priority footage |

The laptop's pipeline (`pipeline.py`) checks for a running commander before polling Telegram — it uses file-based approval (`web_approval_{slot}.json`) to avoid conflicts. Oracle and laptop never fight over the Telegram queue.

---

## How Posting Works End-to-End

```
                          ┌─────────────────────┐
                          │   Oracle Cloud VM   │
                          │  140.238.73.32       │
                          │                     │
  Cron fires (e.g. 08:00) │                     │
  ─────────────────────── ▶  pipeline.py runs   │
                          │   ↓                 │
                          │  Check pipeline_    │
                          │  ran_today.json     │
                          │  (if laptop ran →   │
                          │   skip this slot)   │
                          │   ↓                 │
                          │  Generate content   │◀─ Claude API
                          │  (AI hooks, beats)  │◀─ Perplexity
                          │   ↓                 │
                          │  Render video       │◀─ FFmpeg
                          │  (Pexels + clips)   │◀─ Kling API
                          │   ↓                 │
                          │  Send to Telegram   │──▶ You see preview
                          │  for approval       │
                          │   ↓ (30 min window) │
                          │  Post to platforms  │──▶ TikTok API
                          │                     │──▶ Instagram API
                          │                     │──▶ YouTube API
                          │                     │──▶ LinkedIn API
                          └─────────────────────┘
```

---

## File Locations on Oracle

| File | Path | Purpose |
|------|------|---------|
| Pipeline code | `/opt/otb_pipeline/` | All BootHop scripts |
| G-Inspired | `/opt/g_inspired/` | G-Inspired client data |
| Social credentials | `/opt/otb_pipeline/scripts/social_credentials.json` | TikTok, IG, LinkedIn tokens |
| YouTube token | `/opt/otb_pipeline/scripts/youtube_token.json` | YouTube OAuth token |
| Config | `/opt/otb_pipeline/config.py` | All API keys and paths |
| Pipeline log | `/home/ubuntu/otb_pipeline.log` | BootHop daily run log |
| G-Inspired log | `/home/ubuntu/g_inspired.log` | G-Inspired run log |
| Engagement log | `/home/ubuntu/engage.log` | Comment/like bot log |
| Weekly log | `/home/ubuntu/weekly_run.log` | Monday intelligence run |
| Commander log | `journalctl -u otb-commander` | Telegram bot log |
| SSH key | `C:\Users\babso\.ssh\oracle_boothop.pem` | Your laptop (keep safe) |

---

## Updating Code on Oracle

All code is deployed via Git. After any change on the laptop:

```powershell
# On laptop
cd C:\users\babso\desktop\otb_pipeline
git add <files>
git commit -m "your message"
git push origin main
```

Then Oracle auto-pulls either:
- Automatically on its next cron run (pipeline.py does `git pull` at startup)
- Or manually:

```bash
ssh -i oracle_boothop.pem ubuntu@140.238.73.32
cd /opt/otb_pipeline && git pull origin main
sudo systemctl restart otb-commander
```

---

## Adding a New Laptop (New Machine Setup)

To control Oracle from a brand new laptop:

1. Copy `oracle_boothop.pem` to `C:\Users\<name>\.ssh\oracle_boothop.pem`
2. Clone the pipeline: `git clone https://github.com/Daddyoba12/OTBPipeline.git`
3. Copy `scripts/social_credentials.json` from Oracle:
   ```powershell
   scp -i oracle_boothop.pem ubuntu@140.238.73.32:/opt/otb_pipeline/scripts/social_credentials.json scripts/
   ```
4. Copy the `.env` file (API keys) from Oracle:
   ```powershell
   scp -i oracle_boothop.pem ubuntu@140.238.73.32:/opt/otb_pipeline/.env .
   ```
5. Install Python dependencies: `pip install -r requirements.txt`
6. Done — the new laptop can run the pipeline and Oracle continues as backup

---

## Keeping Tokens Up to Date

Social media tokens expire. When a token expires, posting fails silently. Check monthly:

| Platform | Token lifetime | How to refresh |
|----------|---------------|----------------|
| Instagram | Long-lived (~60 days) | Re-run `scripts/refresh_ig_token.py` |
| TikTok | 24 hours (sandbox) | Run `tiktok_oauth_now.py` to get new token |
| LinkedIn | 60 days | LinkedIn Developer → refresh OAuth |
| YouTube | Does not expire (OAuth file) | Re-run auth flow if `youtube_token.json` is deleted |

After refreshing on the laptop, always re-copy to Oracle:
```powershell
scp -i oracle_boothop.pem scripts/social_credentials.json ubuntu@140.238.73.32:/opt/otb_pipeline/scripts/
```

---

## Troubleshooting on Oracle

### Pipeline not running

```bash
# Check last run
tail -50 /home/ubuntu/otb_pipeline.log

# Check cron is active
crontab -l

# Manually run a slot
cd /opt/otb_pipeline && python3 pipeline.py --slot 1 --force
```

### Commander not responding

```bash
sudo systemctl status otb-commander
sudo systemctl restart otb-commander
sudo journalctl -u otb-commander -n 30
```

### Out of disk space

```bash
df -h /opt
# Clean old output files (keep last 30 days)
find /opt/otb_pipeline/output -name "*.mp4" -mtime +30 -delete
```

### Python package missing

```bash
pip3 install <package_name>
```

### Check if Oracle posted today

From Telegram: `/status`
Or SSH: `grep "posted" /home/ubuntu/otb_pipeline.log | tail -10`

---

## Oracle vs Laptop — Who Does What

| Task | Oracle | Laptop |
|------|--------|--------|
| Always-on Telegram bot | ✅ Primary | ❌ (off when lid closed) |
| Pipeline backup (if laptop off) | ✅ Yes | ❌ |
| Kling review video generation | ❌ Disabled | ✅ Only |
| Local video preview | ❌ | ✅ |
| Code development | ❌ | ✅ |
| Git push / deploy | ❌ | ✅ Primary |
| Emergency manual run | ✅ `--force` flag | ✅ |
| Multi-client support | ✅ All clients | ✅ BootHop only |
