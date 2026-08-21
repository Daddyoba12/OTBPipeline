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
| `/revoice 3` | Opens Revoice Studio for slot 3 (record voice or auto TTS) |
| `/v2 3` | Forces V2 Kling video for slot 3 next run |
| `/music <query>` | Downloads music from YouTube by any query type |
| `/swapmusic 2` | Swaps music on an existing V2 video (no re-recording needed) |
| `/blog 1` | Generates and publishes a blog post for slot 1 content |
| Send voice note | Saved as revoice recording for the active session |
| Send video/photo | Saved to `user_clips/` as priority footage |

The laptop's pipeline (`pipeline.py`) checks for a running commander before polling Telegram — it uses file-based approval (`web_approval_{slot}.json`) to avoid conflicts. Oracle and laptop never fight over the Telegram queue.

---

## Revoice Studio — How It Works

Revoice Studio is the tool for replacing the AI voice on any generated video with your own recording or a new auto TTS narration.

### Starting a session

```
/revoice 3
```

This opens an interactive session for Slot 3. You can also tap **🎙 Revoice S1/S2/S3** buttons in the `/menu` control panel.

### Session flow

```
You tap /revoice 3
    ↓
Bot shows the video for slot 3 (30-second preview)
    ↓
Choose: 🎤 Record Voice  OR  🤖 Auto TTS
    ↓  (if Record Voice)                        ↓  (if Auto TTS)
Send a voice note to Telegram            Bot reads the script aloud
    ↓                                          using OpenAI nova TTS
Choose music duration: 15s / 30s / 45s         (falls back to gTTS)
    ↓
Pick a background music track
    ↓
Bot bakes: voice + music trimmed to duration + fade-out
    ↓
Previews the result — you choose: Post TikTok / Post IG / Swap Music / Post Blog / Done
```

### Music trim selector

When recording your own voice, you pick how long the background music plays: **15s / 30s / 45s**. The music is trimmed to that duration with a fade-out in the final 1.5s. The voice track always plays for the full video length.

### After revoice preview — action buttons

After a successful bake, four action buttons appear under the preview video:

| Button | What it does |
|--------|-------------|
| 🚀 Post TikTok | Posts the revoiced video directly to TikTok |
| 📸 Post IG | Posts to Instagram |
| 🎵 Swap Music | Replaces the background music without re-recording |
| 📝 Post Blog | Generates a blog post from this slot's content |
| ⏭ Done | Exits the studio |

---

## Music Swap — Standalone Track Replacement

Music Swap lets you replace the background music on any existing V2 video without recording a new voice. It replaces the track on all 3 platform variants (TikTok, Instagram, YouTube) at once.

### Via Telegram command

```
/swapmusic 2
```

Or tap **🎵 Swap Music S2 / S3 / S4** buttons in the `/menu` control panel.

### How it works

1. Bot finds the latest V2 base for that slot
2. Shows a music picker with your saved library tracks
3. You pick a track (or choose YouTube search)
4. FFmpeg strips the original audio and layers in the new track at 13% volume with fade in/out
5. All 3 platform variants are overwritten in-place
6. Original video stream is re-used without re-encoding (fast — ~10 seconds)

The swap session expires after 30 minutes. If no V2 video exists for the slot, the bot tells you to `/rerun` first.

---

## Blog Post Command

The pipeline can publish a blog post to your configured Blogger account using the content from any slot.

### Via Telegram

```
/blog 1
```

Or tap **📝 Blog S1 / S4** in the `/menu` control panel. After revoice, the **📝 Post Blog** button appears directly in the preview.

### How it works

1. Reads the slot's content data (hook, script, topic)
2. Calls `scripts/post_blog.py` which generates a full HTML blog article using Claude
3. Publishes directly to Blogger via the Google API
4. If Blogger posting fails, the HTML is saved to `blog/pending/` for manual upload

### What you need configured

| Setting | Where |
|---------|-------|
| Blogger Blog ID | `config.py` → `BLOGGER_BLOG_ID` |
| Google refresh token | `config.py` → `BLOGGER_REFRESH_TOKEN` |
| Google client ID/secret | `config.py` → `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |

---

## Music Search — Smart Query

The `/music` command accepts any form of music description. You do not need to type a specific format.

### Accepted formats

```
/music Savage by Megan Thee Stallion
/music written by Pharrell Williams
/music lyrics: started from the bottom
/music artist: Burna Boy
/music Drake official audio
/music https://www.youtube.com/watch?v=...
```

All these are normalised to the best YouTube search automatically. The normaliser:
- Strips prefixes like `by`, `written by`, `lyrics:`, `artist:`, `song:`, `singer:`, etc.
- Adds "official audio" if no audio-type keyword is present
- Passes URLs through directly without modification

The same normalisation applies to music searches from the web dashboard at `/commander`.

---

## 48h Activity Feed

A live read-only feed showing everything posted in the last 48 hours.

### Access

- **URL:** `https://boothop.com/feed`
- **From admin dashboard:** Click the **📡 48h Feed** button in the top nav bar
- **API:** `GET /api/feed?hours=48` (requires auth cookie or `X-Secret` header)

### What it shows

- **Stats bar:** posts today, total 48h count, platform count, slots that ran
- **Platform pills:** per-platform post counts (TikTok, Instagram, YouTube, LinkedIn, Blog, Newsflash)
- **Timeline:** every post in reverse-chronological order with platform icon, slot badge, hook text, and a link to the live post if available
- **Music section:** tracks used recently with timestamps
- Auto-refreshes every 120 seconds

### Data sources

| Source | File |
|--------|------|
| Social posts | `data/post_log.json` (list of dicts) |
| Newsflash posts | `data/newsflash_log.json` (dict with `"posts"` key) |
| Music used | `data/music_log.json` (list) |
| Blog posts | `blog/posted/*.json` (individual metadata files) |

---

## Client Onboarding — boothop.com/onboard

New clients self-onboard at `https://boothop.com/onboard`. The form collects everything needed to configure a client in one session.

### What the form collects

**Account basics**
- Company / business name (becomes the login slug)
- Contact name + email
- Password
- Telegram Chat ID (optional — for Telegram notifications)
- WhatsApp number (optional)
- Plan (Basic / Pro)

**Platform selection** — client ticks which platforms they post to:

| Platform | Credentials collected |
|----------|--------------------|
| TikTok | Handle, Client Key, Client Secret |
| Instagram | Username, Facebook App ID, App Secret, Long-lived Access Token, IG Business Account ID |
| YouTube | Channel URL, API Key (OAuth set up post-onboard) |
| LinkedIn | Profile URL, Client ID, Client Secret, Access Token |
| Blog | Platform (Blogger / WordPress), Blog URL, Blog ID, Refresh Token |
| Email Digest | Business email address, frequency (daily / weekly / both) |

Credential sections are hidden by default and appear only when the platform is ticked. All credentials are stored in the `credentials_json` column and never logged.

**Business email validation**

The Daily Email Digest field requires an official business email. Free providers are rejected server-side (Gmail, Yahoo, Hotmail, Outlook, iCloud, ProtonMail, AOL, etc.). The form also validates this live in the browser as you type.

### After onboarding

Credentials are stored in the database and associated with the company slug. The admin can view all companies at `/admin`. Platform-specific posting is activated as each credential set is verified.

---

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
| Revoice Studio (voice bake) | ✅ | ✅ |
| Auto TTS revoice | ✅ | ✅ |
| Music swap (/swapmusic) | ✅ | ✅ |
| Blog post (/blog) | ✅ | ✅ |
| 48h feed dashboard | ✅ boothop.com/feed | ✅ localhost |
| Dynamic music search | ✅ | ✅ |
| Local video preview | ❌ | ✅ |
| Code development | ❌ | ✅ |
| Git push / deploy | ❌ | ✅ Primary |
| Emergency manual run | ✅ `--force` flag | ✅ |
| Multi-client support | ✅ All clients | ✅ BootHop only |
| Client self-onboarding | ✅ boothop.com/onboard | ❌ |
