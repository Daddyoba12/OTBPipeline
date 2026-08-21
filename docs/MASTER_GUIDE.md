# OTB Pipeline — Master Guide
*Last updated: 2026-08-21 — authoritative reference, supersedes architecture.md and admin-guide.md*

---

## What This System Does

The OTB Pipeline is a fully automated social media content engine for BootHop. Every day it:

1. Writes a short story (hook, problem, resolution, lesson) based on a content strategy
2. Finds matching video footage and builds a branded video
3. Sends you a preview on Telegram to approve or edit
4. Posts the approved video to TikTok, Instagram, and YouTube at the right time
5. Generates a newspaper image and blog article (certain slots)
6. Learns from what performed well and improves the next week's content automatically

You control it entirely from Telegram. No dashboard logins required for day-to-day use.

---

## The Two Machines

The system runs across two machines that act as primary and backup.

```
┌─────────────────────────────────┐     ┌──────────────────────────────────┐
│         YOUR LAPTOP             │     │       ORACLE CLOUD VM            │
│         (Windows)               │     │       140.238.73.32              │
│                                 │     │                                  │
│  • Runs the pipeline            │     │  • Backup pipeline (1h later)    │
│  • Generates + renders videos   │     │  • Always-on Telegram bot        │
│  • Posts to all platforms       │     │  • Dashboard (boothop.com/...)   │
│  • Task Scheduler controls it   │     │  • Cron controls it              │
│                                 │     │  • Engagement bot runs here      │
└─────────────────────────────────┘     └──────────────────────────────────┘
         PRIMARY                                   BACKUP
```

**When your laptop is on:** The laptop runs everything. After posting, it tells Oracle "I already handled this slot" so Oracle skips it.

**When your laptop is off or asleep:** Oracle runs the pipeline 1 hour after the scheduled time as a fallback. You still get posts — just 1 hour later than normal.

---

## The Daily Schedule

All times are **London (UK) time**. The schedule is defined in `client_profile.json`.

| Slot | London Time | Posts to | Days |
|---|---|---|---|
| **Slot 1 — Morning** | 08:00 | TikTok + Instagram + YouTube + Newspaper | Every day |
| **Slot 2 — Afternoon** | 14:00 | TikTok + Instagram + YouTube | Every day |
| **Slot 3 — Evening** | 21:00 | TikTok + Instagram + YouTube | Every day |
| **Slot 4 — Weekly** | 08:00 | LinkedIn + Blog article | Tuesday + Friday only |

**Oracle backup times (if laptop is off):** 09:00, 15:00, 22:00, 09:00 Tue/Fri.

**Monday 05:30:** Weekly intelligence run — analyses last week's performance, updates what content angles to prioritise this week.

---

## How One Post Gets Made (Step by Step)

When the pipeline fires for a slot, here is exactly what happens in order:

### Step 0 — Slot 1 prep (morning only)
- **Music refresh**: Downloads today's trending tracks from TikTok/YouTube. Used as background music in videos.
- **Hashtag pre-warm**: Fetches today's trending hashtags from Perplexity API. Ready for captions.
- **Hook analysis**: Reads recent post data, identifies which hook patterns got the most views. Feeds this into the AI prompt so hooks improve over time.

### Step 1 — Choose video format: V1 or V2
The pipeline alternates between two video formats per slot. It checks `data/version_state.json`:

- **V1 (25 seconds)** — Built from Pexels/Pixabay stock footage. 5 scenes × 3 seconds + lesson card + brand end card. Classic BootHop gold look.
- **V2 (15 seconds)** — Built from the Kling clip library. Cinematic AI footage. Shorter, more punchy.

If the last run was V1 → this run is V2. If V2 fails for any reason → falls back to V1 automatically.

Slot 4 (LinkedIn/Blog) always uses V1.

### Step 2 — Generate content
The AI writes:
- **Hook** — the first line viewers see. Written to stop the scroll.
- **Problem** → **Stakes** → **Resolution** → **Lesson** — the 5-beat story.
- **TikTok caption** — hook-first, 20 hashtags included.
- **Instagram caption** — 125-character visible hook, 20 hashtags.

Which story angle to write is determined by the **content pillar** for today's slot (see Content Pillars section below). The AI also checks hook similarity — if the new hook is >50% similar to a recent one, it rejects it and tries again.

### Step 3 — Generate hook clip
Tries to find a 2-second cinematic opening clip from Pexels that matches the hook's theme. If found, this plays at the very start of the video. If not found, a styled text card plays instead.

### Step 4 — Render the video
For V1: assembles the 25-second video using FFmpeg:
```
[2s hook clip] → [3s problem clip] → [3s stakes clip] →
[3s resolution clip] → [3s lesson clip] →
[5s lesson text card] → [5s brand end card with BootHop logo + CTA]
```
Clips come from Pexels → Pixabay → local user clips (in that priority order). Every clip has a **14-day cooldown** so the same footage doesn't appear twice in two weeks.

Three platform variants are created:
- **TikTok** — base video (1080×1920)
- **Instagram** — warm colour grade applied
- **YouTube** — same as TikTok

For Slot 1: a **Newspaper image** (1080×1350 Pillow-rendered) is also generated — posted to Instagram as a feed image (not a Reel), for content variety.

### Step 5 — Telegram preview and approval
The rendered video is sent to your Telegram with four buttons:

| Button | What it does |
|---|---|
| **✅ Post Now** | Posts immediately across all platforms |
| **⏭ Skip** | Discards this slot run entirely |
| **🔄 Regen** | Rewrites the content and re-renders (up to 3 attempts) |
| **✏️ Edit text** | Lets you change hook/lesson/captions before posting |

**Approval window per slot:** Slot 1 = 60 minutes. Slots 2 + 3 = 30 minutes. Slot 4 = 60 minutes.

**If you don't respond in time → it auto-approves and posts.** So you never miss a post just because you were busy. If you want to stop a post, use `/skip` in Telegram before the timer runs out.

### Step 6 — Post to platforms

Each platform uses its own posting module:

| Platform | How it posts |
|---|---|
| **TikTok** | Zernio OAuth API. 3-hour rate limit guard — won't double-post. |
| **Instagram** | Meta Graph API. Uploads the warm-graded Reel version. |
| **YouTube** | YouTube Data API v3. Resumable upload for reliability. |
| **Newspaper** | Instagram Graph API. Posted as an IMAGE (feed post, not Reel). |
| **LinkedIn** | UGC Posts API v2. Weekdays only. Link goes in first comment, not caption. |
| **Blog** | Claude writes a full SEO article → Blogger API publishes it. |

If any platform fails **on Oracle**, the post is queued in `data/pending_posts.json`. Next time the laptop runs, it picks up and retries.

### Step 7 — After posting
- Marks this slot as done for today → pushes the signal to Oracle so it skips
- Updates version state (flips V1↔V2 for next time)
- Routes platform videos to the Revoice Studio dashboard on Oracle
- Pushes data files to Oracle in the background (sync)

---

## The Telegram Commander

The commander (`scripts/telegram_commander.py`) runs **24/7** — on Oracle when the laptop is off, and on the laptop when it's on. It is the only process that polls your Telegram bot, so there's no conflict with the pipeline.

### All commands

| Command | What it does |
|---|---|
| `/menu` | Show all commands |
| `/status` | Show current pipeline state (last run, next slot, what step it's on) |
| `/rerun` | Force re-run the most recent slot now |
| `/v1` | Force next slot to use V1 format (25s Pexels) |
| `/v2` | Force next slot to use V2 format (15s Kling) |
| `/skip` | Cancel the current pending approval (slot will not post) |
| `/pause` | Pause all pipeline activity |
| `/resume` | Resume after a pause |
| `/revoice` | Open Revoice Studio for the latest video (auto-detects slot) |
| `/revoice 1` | Open Revoice Studio for a specific slot (1, 2, or 3) |
| `/music` | Show today's music tracks |
| `/block hashtag` | Block a hashtag from ever being used again |

### How the approval flow works (technical)
The pipeline doesn't poll Telegram itself — that would cause conflicts. Instead:
1. Pipeline sends the video and writes a "pending approval" file locally
2. The commander sees the file, monitors Telegram for your button tap
3. Commander writes the decision to a "web approval" file
4. Pipeline reads that file and proceeds

This means only one process ever talks to Telegram at a time.

---

## Revoice Studio

Revoice Studio lets you replace the AI-generated voice (or add your own voice/music) to any pipeline video after it's been rendered. You can use it from **Telegram** (phone or desktop) or from the **web dashboard** at `boothop.com/commander` → Revoice Studio tab.

### When to use it
- You want to record your own voice over the video instead of (or in addition to) the AI narrator
- You want to swap the background music to something different
- You want to try a different AI voice before locking in a post

### Option A — Telegram (phone or laptop)

**Step 1 — Open the studio**
Type `/revoice` in Telegram, or tap **Re-voice S1** from the `/menu`. The bot sends the current video so you can see exactly what you're working with, then shows you the action menu.

**Step 2 — Choose your approach**

| Button | What happens |
|---|---|
| 🎤 Record Voice | Bot collects your voice note, you review it, then pick music and bake |
| 🤖 Auto TTS | AI generates narration, sends it as an audio clip so you can HEAR it, then you confirm or try a different voice before baking |
| 🎵 Swap Music Only | Keep the existing voice, just change the background music |

**Step 3a — Record Voice flow**
1. Bot displays the script (hook text) for you to read
2. **On phone:** Press and hold the 🎤 mic icon at the bottom of the chat → speak → release to send
3. **On Telegram Desktop:** Click the 🎤 mic icon → speak → click ✅ to send
4. Bot plays back your recording so you can approve it or re-record
5. After approving, the music browser opens

**Step 3b — Auto TTS flow**
1. Bot sends an audio clip of the AI-generated narration (using one of 6 OpenAI voices)
2. You hear the narration first — no baking yet
3. Options: **✅ Bake it in** (lock this voice), **🔄 Try next voice** (cycles nova → alloy → echo → fable → onyx → shimmer), **🎤 Record instead**, **❌ Cancel**

**Step 4 — Pick music (if using voice)**
1. Music browser shows 6 tracks per page with ▶️ preview buttons
2. Tap ▶️ on any track to hear a 30-second preview first
3. After previewing: **✅ Use this** or **↩️ Back** to browse more
4. Navigate pages with **← Prev** / **Next →**

**Step 5 — Bake**
Bot combines your voice + music + video in the background (~30 seconds). When done, the finished video is sent to Telegram automatically.

---

**Notes on speed:** Sending video previews and baking take 20–40 seconds depending on file size and internet speed. The bot acknowledges every button press instantly — if it seems slow, the file is uploading in the background.

---

### Option B — Web Dashboard (`boothop.com/commander`)

The Commander portal has a **Revoice Studio** tab that works entirely in the browser — useful when on a laptop where recording via the browser mic is easier than Telegram.

**Steps:**
1. Go to `boothop.com/commander` and log in
2. Click the **Revoice Studio** tab
3. **Step 1 — Pick your video:** Select a pipeline slot (shows the latest rendered video for each slot) or upload your own file
4. **Step 2 — Record or upload voice:**
   - Click **Start Recording** → speak → click **Stop Recording** (uses your browser microphone)
   - Or click **Choose audio file** to upload an existing MP3/WAV
5. **Step 3 — Pick music:** Choose from the library dropdown or search YouTube by keyword and download directly
6. **Step 4 — Bake & Send:** Click **Bake Video** → the finished video is sent to your Telegram chat

The web dashboard is the easiest option when working on a laptop.

---

## The V2 Kling Pipeline

V2 is the 15-second format using AI-generated cinematic clips.

**The Kling library** (`kling_library/` folder) is the source. New clips are generated daily:
- The pipeline calls Kling AI to generate a 30-40 second clip related to BootHop's niche
- The clip is sent to your Telegram for **manual review** — you decide whether to approve it for the library
- Approved clips sit in `kling_library/` waiting to be used
- Once used in a V2 video, the clip gets a **14-day cooldown** before it can be used again

When V2 runs for a slot:
1. Finds an available Kling clip (not on cooldown, best `boothop_fit` score)
2. Generates content with the same AI as V1
3. Assembles a 15-second video: hook card (2s) → Kling clip + story text (9s) → brand overlay (1.5s) → CTA card (2.5s)
4. Sends to Telegram for approval → posts to all platforms

---

## The Weekly Intelligence Loop

Every **Monday at 05:30** (before the 08:00 slot fires), the pipeline runs a self-improvement cycle:

### Step 1 — Trend Scout
Scans TikTok and YouTube to find what content is performing right now in the UK-Nigeria travel and logistics space. Identifies:
- Which video formats are trending
- Which hook styles are getting the most engagement
- Recommended content angle for the week

Output: `data/trend_report.json` — injected into the AI's content prompts every slot.

### Step 2 — Weekly Review
Pulls your actual performance data from TikTok, YouTube, and Instagram APIs:
- View counts, likes, comments, shares for every post in the last 30 days
- Ranks content pillars by average views
- Identifies which hook openers perform best
- Identifies which day/slot combination works best

Output: `data/pillar_weights.json` — used by the pipeline to sample content pillars. If `family` posts average 3× more views than `courier_business`, family gets picked 3× more often going forward.

**This is the learning loop** — every week the pipeline gets a little smarter about what content to make.

---

## Content Pillars — The 7-Day Rotation

Every slot has a different story angle each day of the week. No two slots on the same day cover the same topic.

| Day | Slot 1 (Morning) | Slot 2 (Afternoon) | Slot 3 (Evening) |
|---|---|---|---|
| Monday | Family & Care | Courier Business | Urgent & Medical |
| Tuesday | Travel Hacks | Airport Deliveries | Travel Hacks |
| Wednesday | Airport Stories | Personal Shopper | Cultural & Earn |
| Thursday | Cost Pain | Community | Airport Deliveries |
| Friday | Community / Faith Friday | Multi-Courier | Smart Travel |
| Saturday | Humans of BootHop | Airport | Cost Pain |
| Sunday | Founder Story | Family | Family |

**Slot 4 (Tue/Fri):** Always Brand Authority (LinkedIn thought leadership).

**B2B pillars** (`Courier Business`, `Multi-Courier`): Posted to Instagram only — never TikTok or YouTube, as these are professional/recruitment angles.

**Wildcard**: Roughly 1 in 10 runs will inject a `Flight Discovery` post regardless of the scheduled pillar — for variety.

The `pillar_weights.json` from the weekly review biases this selection. High-performing pillars appear more often.

---

## Data Files — What Each One Does

| File | Role |
|---|---|
| `data/version_state.json` | Tracks V1/V2 alternation per slot |
| `data/pipeline_ran_today.json` | Prevents double-posting the same slot. Shared with Oracle via SCP. |
| `data/pipeline_crash.log` | All errors AND all successes are appended here |
| `data/pipeline_step.txt` | The current step of a running pipeline (cleared when done) |
| `data/post_log.json` | Every post ever made — platform ID, timestamp, content |
| `data/sync_status.json` | Last 30 run summaries — shows which machine ran, what was posted |
| `data/pillar_weights.json` | Per-pillar performance weights (written by weekly review) |
| `data/trend_report.json` | Weekly trend intelligence (written by trend scout) |
| `data/hook_patterns.json` | Extracted patterns from high-performing hooks |
| `data/memory.json` | Claude's content memory — topics used, tone calibration |
| `data/trending_hashtags.json` | Today's hashtag set (refreshed at Slot 1) |
| `data/kling_library.json` | Kling clip metadata and 14-day cooldown dates |
| `data/pending_posts.json` | Posts that failed on Oracle, queued for laptop retry |
| `data/commander.pid` | PID of the running commander process |
| `data/pending_approval_{N}.json` | Pipeline signals it's waiting for Slot N approval |
| `data/web_approval_{N}.json` | Commander writes the approval decision for Slot N |

---

## Infrastructure Map

```
LAPTOP (Windows)                    ORACLE VM (140.238.73.32)
─────────────────────────────       ──────────────────────────────────
Windows Task Scheduler              Linux cron
  OTB_MultiClientDispatcher           pipeline.py --slot 1  (08:00 UTC)
    → dispatch_scheduler.py           pipeline.py --slot 2  (14:00 UTC)
      → pipeline.py --slot N          pipeline.py --slot 3  (21:00 UTC)
                                      pipeline.py --slot 4  (08:00 Tue/Fri)
  OTB_Commander                       weekly_run.py         (Mon 05:30 UTC)
    → telegram_commander.py           engage.py             (every 2h)
                                      g_inspired cron jobs  (separate client)
  OTB_WeeklyIntelligence
    → weekly_run.py (Mon 05:30)
                                    systemd services
  OTB_TikTokAnalytics (daily)         otb-commander.service (Telegram bot)
  OTB_Engage (every 2h)               otb-dashboard.service (FastAPI port 1030)

Code sync:  Laptop → GitHub → Oracle (auto-pull every 5 min)
Data sync:  Laptop → Oracle via SCP (after each slot)
            Oracle → Laptop via sync_data.ps1 (every 30 min via OTB_SyncFromOracle_30min)
```

---

## The Dashboard (boothop.com)

The dashboard is a FastAPI app running on Oracle, proxied through Vercel.

| URL | What it is |
|---|---|
| `boothop.com/commander` | Commander portal — music management, pipeline control |
| `boothop.com/dashboard` | Revoice Studio — bake history, video review |
| `boothop.com/onboard` | Client self-registration |
| `boothop.com/onboard/admin` | Admin panel — manage all clients |
| `boothop.com/client-onboarding` | Client pipeline setup wizard |

---

## Common Operations

### Check if the pipeline is currently running
```powershell
Get-Content data\pipeline_step.txt
```
If the file has content, the pipeline is running. If it's empty/missing, it's idle.

### Check when it last ran
```powershell
Get-Content data\pipeline_crash.log -Tail 20
```
Both successes and errors are logged here.

### Force-run a slot right now
```powershell
cd C:\users\babso\desktop\otb_pipeline
python pipeline.py --slot 1 --force
```

### Force V2 format on the next run
In Telegram: `/v2`
Or: `python pipeline.py --slot 2 --version v2`

### Pause all posting (e.g. before a trip)
In Telegram: `/pause`
To resume: `/resume`

### Check Oracle's live pipeline log
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.32 "tail -50 /home/ubuntu/otb_pipeline.log"
```

### Re-enable all scheduled tasks (if they got disabled)
```powershell
Get-ScheduledTask | Where-Object TaskName -like "OTB_*" | Enable-ScheduledTask
```

### Restart Oracle commander
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.32 "sudo systemctl restart otb-commander"
```

### Restore Oracle cron jobs (if they get wiped)
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.22 "bash /opt/otb_pipeline/deploy/set_cron.sh"
```

### Sync latest code changes to Oracle
```powershell
git push origin main
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.32 "cd /opt/otb_pipeline && git stash && git pull origin main"
# V2 files (not in git) must be manually copied:
scp -i $k pipeline_kling.py ubuntu@140.238.73.32:/opt/otb_pipeline/
scp -i $k scripts/render_kling_video.py ubuntu@140.238.73.32:/opt/otb_pipeline/scripts/
scp -i $k scripts/analyse_kling_library.py ubuntu@140.238.73.32:/opt/otb_pipeline/scripts/
```

---

## Troubleshooting

### No post went out today
1. Check `data/pipeline_crash.log` — is there a recent error?
2. Check `Get-ScheduledTask | Where TaskName -like "OTB_*"` — are tasks Disabled?
3. Check `data/pipeline_step.txt` — is it stuck at a step?
4. Is the pipeline waiting in a Telegram approval window? Check Telegram and approve/skip.
5. Check `data/pipeline_ran_today.json` — was the slot wrongly marked as already run?

### Post went out on all platforms except one
Check `data/pipeline_crash.log` for that platform's error. Common causes:
- TikTok: token expired → re-authorise via Zernio
- YouTube: OAuth expired → run `python scripts/auth_youtube.py`
- Instagram: access token expired → refresh in social_credentials.json

### Version keeps repeating (always V1 or always V2)
Edit `data/version_state.json` and correct the `next_version` field for the affected slot. Or use `/v1` or `/v2` in Telegram.

### Telegram bot not responding
Check for duplicate commander processes:
```powershell
Get-Process python | Select-Object Id, StartTime
```
Kill the older PID. Only one commander should run on the laptop. Oracle's commander (`sudo systemctl status otb-commander`) should also be running on Oracle.

### Duplicate commanders causing 409 Conflict errors
This happens when Oracle's commander and the laptop's commander run simultaneously. Both back off 30 seconds and retry — it's tolerable but causes a delay. To resolve: kill the older of the two commanders. The Oracle one is persistent (systemd); the laptop one starts via Task Scheduler.

### Oracle not picking up the backup slot
1. Check Oracle cron: `ssh ... "crontab -l"`
2. Check `data/pipeline_ran_today.json` on Oracle — if the laptop posted, did it sync the file?
3. Check Oracle log: `tail -50 /home/ubuntu/otb_pipeline.log`

---

## Key File Locations

### Laptop
| What | Where |
|---|---|
| Pipeline root | `C:\users\babso\desktop\otb_pipeline\` |
| All scripts | `scripts\` |
| All data files | `data\` |
| Rendered videos | `output\` |
| Music tracks | `music\daily\` |
| Kling clips | `kling_library\` |
| API keys | `keys.env` |
| SSH key to Oracle | `C:\Users\babso\.ssh\oracle_boothop.pem` |
| Crash log | `data\pipeline_crash.log` |
| Docs | `docs\` |

### Oracle VM
| What | Where |
|---|---|
| Pipeline root | `/opt/otb_pipeline/` |
| API keys | `/opt/otb_pipeline/keys.env` |
| Dashboard database | `/opt/otb_pipeline/dashboard/otb.db` |
| Pipeline log | `/home/ubuntu/otb_pipeline.log` |
| Weekly run log | `/home/ubuntu/weekly_run.log` |
| Engagement log | `/home/ubuntu/engage.log` |
| Commander service | `sudo systemctl status otb-commander` |
| Dashboard service | `sudo systemctl status otb-dashboard` |

---

## Adding a New Client to the Pipeline

1. Create their Revoice Studio account at `boothop.com/onboard/admin` → Add Company
2. Create their Commander account at `boothop.com/commander` → Create Account
3. Direct them to `boothop.com/client-onboarding` to fill in their pipeline config (brand info, platforms, credentials)
4. Their config saves to Oracle at `/opt/otb_pipeline/dashboard/clients/{slug}/`
5. Their pipeline runs via the multi-client dispatcher — add their client entry to `deploy/dispatch_scheduler.py → CLIENTS`

---

## Technology Stack

| Layer | Technology |
|---|---|
| Content AI | Claude Sonnet 4.6 (story) + Claude Haiku 4.5 (scene planning, QA) |
| Video generation | FFmpeg (assembly + colour grading) |
| AI video clips | Kling AI (V2 library) |
| Stock footage | Pexels API → Pixabay API (fallback) |
| Image generation | Pillow (newspaper, story cards, brand cards) |
| Text-to-speech | gTTS (hook audio clips) |
| TikTok posting | Zernio API |
| Instagram posting | Meta Graph API |
| YouTube posting | YouTube Data API v3 |
| LinkedIn posting | LinkedIn UGC Posts API v2 |
| Blog posting | Blogger API |
| Telegram control | Telegram Bot API (long-poll getUpdates) |
| Trend intelligence | Perplexity API + TikTok API |
| Cloud database | Supabase (Commander accounts, music library) |
| Local database | SQLite (Revoice Studio accounts) |
| Dashboard server | FastAPI + Jinja2 (Oracle) |
| Website | Next.js on Vercel |
| Code sync | GitHub (auto-pull on Oracle every 5 min) |
| Server OS | Ubuntu 22.04 on Oracle Cloud (free tier) |

---

*OTB Pipeline Master Guide — August 2026*
