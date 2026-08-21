# OTB Pipeline — How It All Runs

*Last updated: 2026-08-21*

---

## 1. The Two Machines

The pipeline runs across two machines that work as primary + backup.

| | Laptop (Windows) | Oracle Cloud VM |
|---|---|---|
| IP / Host | Local | 140.238.73.32 |
| Primary role | Runs pipeline (generates + posts) | Backup pipeline + always-on services |
| Telegram Commander | Runs via Task Scheduler | Runs via systemd (`otb-commander.service`) |
| Schedule trigger | Windows Task Scheduler | Linux cron |
| Fires when | Laptop is awake | Always (even when laptop is off) |
| Backup timing | — | 1 hour after laptop's scheduled time |
| Code source | Local files | Cloned from GitHub, auto-pulls every 5 min |
| API keys | `keys.env` in project root | `keys.env` in `/opt/otb_pipeline/` |

**Double-post prevention**: When the laptop successfully posts a slot, it writes `data/pipeline_ran_today.json` and immediately SCPs it to Oracle. Oracle's `pipeline.py` checks this file at startup — if the slot is already marked for today, it exits without posting.

---

## 2. The Schedule

Defined in `client_profile.json` → `schedule.slots`. Timezone: **Europe/London**.

| Slot | London Time | UTC (BST/summer) | Platforms | Days |
|---|---|---|---|---|
| 1 — Morning | 08:00 | 07:00 | TikTok + Instagram + YouTube + Newspaper | Daily |
| 2 — Afternoon | 14:00 | 13:00 | TikTok + Instagram + YouTube | Daily |
| 3 — Evening | 21:00 | 20:00 | TikTok + Instagram + YouTube | Daily |
| 4 — Weekly | 08:00 | 07:00 | LinkedIn + Blog | Tue + Fri only |

Oracle backup fires exactly 1 hour after each UTC time above (08:00, 14:00, 21:00, 08:00 UTC on Tue/Fri).

---

## 3. What Triggers Each Run

### Laptop side — Windows Task Scheduler

There are 10+ scheduled tasks under the `OTB_*` prefix. The key ones:

- **OTB_MultiClientDispatcher** — runs every 15 minutes. Calls `deploy/dispatch_scheduler.py`, which checks if any slot is within a 30-minute window of its scheduled time. If yes, it calls `pipeline.py --slot N`. This is a **blocking call** — the dispatcher waits for the pipeline to finish before the task ends.
- **OTB_Commander** — starts `scripts/telegram_commander.py` and keeps it running.
- **OTB_MusicRefresh** — runs at 06:00, fetches today's trending music tracks.
- **OTB_WeeklyIntelligence** — runs every **Monday at 05:30** (before slot 1). Chains `trend_scout.py` + `weekly_review.py`. Writes `data/trend_report.json` and `data/pillar_weights.json` which the pipeline reads every slot to bias content toward best performers.

If any of these tasks are **Disabled**, nothing runs. Check status with:
```powershell
Get-ScheduledTask | Where-Object TaskName -like "OTB_*" | Select-Object TaskName, State
```
Re-enable all:
```powershell
Get-ScheduledTask | Where-Object TaskName -like "OTB_*" | Enable-ScheduledTask
```

### Oracle side — Linux cron

```cron
# BootHop backup — fires 1h after laptop primary
0  8 * * *     cd /opt/otb_pipeline && python3 pipeline.py --slot 1
0 14 * * *     cd /opt/otb_pipeline && python3 pipeline.py --slot 2
0 21 * * *     cd /opt/otb_pipeline && python3 pipeline.py --slot 3
0  8 * * 2,5   cd /opt/otb_pipeline && python3 pipeline.py --slot 4

# Weekly intelligence — Monday 05:30 UTC (06:30 London BST) before slot 1 fires
30  5 * * 1    cd /opt/otb_pipeline && python3 scripts/weekly_run.py

# Engagement bot — every 2 hours
10 */2 * * *   cd /opt/otb_pipeline && python3 scripts/engage.py
```

---

## 4. The Dispatcher (`deploy/dispatch_scheduler.py`)

Every time the Task Scheduler fires it (every 15 min), the dispatcher:

1. Reads `client_profile.json` → gets timezone + slot times
2. Converts each slot time to UTC
3. Checks if current UTC time is within **±30 minutes** of any slot
4. If a slot is in-window → runs `python pipeline.py --slot N` (blocking)
5. Only one slot fires per dispatcher run

The 30-minute window means if the laptop woke up late (e.g., from sleep), it can still catch a missed slot as long as it's within 30 minutes.

---

## 5. The Pipeline — Stage by Stage

When `pipeline.py --slot N` runs, it goes through these stages in order:

### Stage 0 — Pre-slot tasks (Slot 1 only)
- **Music refresh**: Fetches today's trending tracks from TikTok/YouTube via `scripts/fetch_trending_music.py`. Tracks are stored in `music/daily/` and used as background audio.
- **Hashtag pre-warm**: Fetches trending hashtags from Perplexity + TikTok API via `scripts/fetch_trending_hashtags.py`. Stored in `data/trending_hashtags.json`.
- **Hook analysis**: Reads recent post performance, extracts patterns from top-performing hooks, updates `data/hook_patterns.json` to bias future content generation.

### Stage 0c — Kling production (separate from V1/V2 alternation)
- Generates a 30-40s Kling AI video for the Kling library — happens once per day on alternating slots (Mon/Wed/Fri = slot 1, Tue/Thu/Sat = slot 2).
- The generated clip gets sent to Telegram for manual review. It does **not** get posted automatically — it feeds the `kling_library/` folder for future V2 runs.

### Stage 1 — Version routing (V1 or V2)

At the start of each slot run, the pipeline checks `data/version_state.json` to decide which video format to use:

- **V1**: 25-second Pexels/Pixabay stock footage video (the original format)
- **V2**: 15-second Kling library clip video (the newer format)

Slots alternate: if the last post for this slot was V1 → next is V2, and vice versa.

```
version_state.json example:
{
  "slot1": {"last_version": "v1", "last_posted_at": "...", "next_version": "v2"},
  "slot2": {"last_version": "v2", "last_posted_at": "...", "next_version": "v1"}
}
```

If V2 is selected, `pipeline.py` hands off to `pipeline_kling.py → run_v2()`. If V2 fails for any reason, it falls back to V1 automatically.

Slots 1, 2, 3 alternate V1/V2. Slot 4 (LinkedIn/Blog) always runs V1 only.

### Stage 2 — Content generation (`scripts/generate_content.py`)

Selects a **content pillar** based on slot + day of week (7-day rotation defined in `config.py → SLOT_PILLARS`), then generates:

- Hook (attention-grabbing opening line)
- Problem statement
- Stakes
- Resolution
- Lesson / CTA
- TikTok caption (hook-first, 20 hashtags)
- Instagram caption (125-char visible hook, 20 mid/micro hashtags)

Uses Claude Sonnet 4.6 (configurable: `STORY_MODEL` in `config.py`) for the story, then a QA pass with `QA_MODEL`. The hook similarity checker prevents reusing hooks that are >50% similar to recent posts (checked against `data/hook_analysis_log.json`).

### Stage 3 — Hook engine (`scripts/generate_hook.py`)

Tries to generate a **2-second cinematic hook clip** using Pexels video search + gTTS audio. This is prepended to the main video as the opening visual. If no matching clip is found, the standard text-card hook is used instead.

### Stage 4 — Render (`scripts/render_video.py`)

For V1: assembles the 25-second video from:
- Hook clip (2s) — from Pexels/Pixabay, matching the hook's visual theme
- Problem clip (3s)
- Stakes clip (3s)
- Resolution clip (3s)
- Lesson clip (3s)
- Lesson text card (5s) — dark background with lesson overlaid
- Brand end card (5s) — BootHop logo, CTA, rotating palettes

Clips sourced from Pexels API → Pixabay API → local user clips (as fallbacks). All clips have a **14-day cooldown** before reuse.

Creates **platform variants**:
- TikTok: base video (1080×1920)
- Instagram: warm colour grade applied via FFmpeg LUT
- YouTube: same as TikTok (YouTube Shorts)
- Newspaper (Slot 1 only): 1080×1350 Pillow-rendered image with rotating BootHop masthead

### Stage 5 — Telegram preview + approval

The rendered video is sent to the Telegram bot chat. The bot displays inline buttons:
- **Post Now** — post immediately
- **Skip** — discard this slot's run
- **Regen** — regenerate content and re-render (up to 3 attempts)
- **Edit text** — edit hook/lesson/captions before posting

Approval timeout per slot (configured in `config.py → TELEGRAM_BUFFER_MINUTES`):
- Slot 1: 60 minutes
- Slot 2: 30 minutes
- Slot 3: 30 minutes
- Slot 4: 60 minutes

On timeout → **auto-approves and posts**. If you need to cancel, use `/skip` in Telegram before the timer runs out.

The approval mechanism is **file-based when the commander is running** (commander writes `data/web_approval_{slot}.json`) so the pipeline doesn't conflict with the commander's Telegram polling.

### Stage 6 — Platform posting

Posts to all platforms configured for the slot. Each platform call returns a post ID on success or `None` on failure.

| Platform | Module | Method |
|---|---|---|
| TikTok | `post_tiktok_zernio.py` | Zernio OAuth API |
| Instagram | `post_instagram.py` | Meta Graph API (Reel) |
| YouTube | `post_youtube.py` | YouTube Data API v3 (resumable upload) |
| Newspaper | `post_newspaper.py` | Instagram feed IMAGE (not a Reel) |
| LinkedIn | `post_linkedin.py` | UGC Posts API v2 — weekdays only |
| Blog | `post_blog.py` | Claude SEO article → Blogger API |

If a post fails **on Oracle**, it is queued in `data/pending_posts.json`. The next time the laptop runs, it picks up and posts the queued items.

### Stage 7 — Post-run housekeeping

- Marks slot as done in `data/pipeline_ran_today.json`
- SCPs `pipeline_ran_today.json` to Oracle (so Oracle skips if laptop already ran)
- Updates `data/version_state.json` (sets `next_version` for this slot)
- Updates `data/sync_status.json` with run summary
- Routes platform videos to Oracle dashboard (`/opt/otb_pipeline/dashboard/companies/boothop/`)
- Pushes data files to Oracle in background via `deploy/sync_data.ps1`

---

## 6. The V2 Pipeline (`pipeline_kling.py`)

When V2 is selected, `run_v2(slot)` runs instead:

1. **Library check** — scans `kling_library/` for clips not on cooldown (`data/kling_library.json` tracks cooldown dates)
2. **Content generation** — same `generate_content.py` as V1
3. **Render** (`scripts/render_kling_video.py`) — Claude picks the best Kling clip for the story, assembles a 15-second video:
   - Hook text card (2s)
   - Kling clip with story text overlaid (9s)
   - Brand message overlay (1.5s)
   - CTA end card (2.5s)
   - Outputs TikTok, Instagram, and YouTube variants
4. **Telegram approval** — sends TikTok variant to Telegram, then waits using the same file-based mechanism
5. **Post to platforms** — calls `post_video(video_path, content, slot)` on each platform module
6. **Updates version state** — marks `last_version: v2`, sets `next_version: v1`

If V2 fails at any step → `run_v2()` returns `False` → `pipeline.py` falls back to the V1 pipeline automatically.

---

## 7. The Telegram Commander (`scripts/telegram_commander.py`)

A long-running process that polls the Telegram bot for commands. It is the **only** process that should poll `getUpdates` from Telegram. The pipeline communicates with it through local files, not by polling Telegram directly.

Uses Telegram **long-polling** with a 30-second timeout — button presses are acknowledged immediately, then heavy work (video upload, TTS generation, baking) runs in background threads so the bot stays responsive.

### Commands
| Command | Action |
|---|---|
| `/menu` | Show all available commands |
| `/status` | Show pipeline status, last run, current step |
| `/rerun` | Force re-run the most recent slot |
| `/v1` | Force next slot to use V1 format |
| `/v2` | Force next slot to use V2 format |
| `/skip` | Skip the currently pending approval |
| `/pause` | Pause the pipeline (sets `schedule.active: false`) |
| `/resume` | Resume the pipeline |
| `/revoice` | Open Revoice Studio for the latest video |
| `/revoice 1` | Open Revoice Studio for a specific slot |
| `/music` | Show today's music tracks |
| `/block` | Block a hashtag from future use |

### Approval flow (file-based)
When the pipeline sends a video for approval, it writes `data/pending_approval_{slot}.json`. The commander sees the pending file, monitors Telegram for button taps, then writes `data/web_approval_{slot}.json` with the decision (`post`, `skip`, `regen`, `edit`). The pipeline reads this file and proceeds.

### Revoice Studio (Telegram)
The commander hosts a full interactive voice-over studio via Telegram.

**Flow:**
1. `/revoice` → bot sends the current slot video so you see what you're working on
2. Choose: **🎤 Record Voice** / **🤖 Auto TTS** / **🎵 Swap Music Only**

**Record Voice:**
- Bot shows the script (hook text) to read aloud
- On phone: hold the 🎤 mic icon → speak → release to send
- On Telegram Desktop: click 🎤 → speak → click ✅ to send
- Bot plays back your recording → approve or re-record

**Auto TTS:**
- Bot generates narration and sends it as an audio clip first (so you hear it before baking)
- Choose ✅ Bake it in, 🔄 Try next voice (6 OpenAI voices cycle), 🎤 Record instead, or ❌ Cancel

**Music browser:**
- 6 tracks per page with ▶️ preview — tap ▶️ to hear 30-second preview before committing
- Navigate pages; after hearing, tap ✅ Use this or ↩️ Back

**Baking:** Runs in a background thread (~30s), then sends the finished video to Telegram.

**Web alternative:** The Commander portal at `boothop.com/commander` → Revoice Studio tab provides the same workflow in a browser — easier for recording on a laptop (uses browser mic).

### Watchdog
A separate `scripts/commander_watchdog.py` runs via Task Scheduler and restarts the commander if its PID file (`data/commander.pid`) shows the process has died.

---

## 8. Oracle vs Laptop — Who Does What

| Situation | What happens |
|---|---|
| Laptop on + awake at slot time | Laptop runs the pipeline (primary). After posting, pushes `pipeline_ran_today.json` to Oracle. Oracle backup fires 1h later, sees the file, and skips. |
| Laptop off or asleep at slot time | Oracle's cron fires 1h later. Checks `pipeline_ran_today.json` (was pushed last time laptop ran). If today's slot isn't marked, Oracle runs the pipeline. |
| Oracle run — platform post fails | Queued in `data/pending_posts.json`. Laptop picks it up on next sync. |
| Both commanders running simultaneously | Each gets 409 Conflict from Telegram. Both back off 30 seconds and retry. One eventually processes the update. This is tolerable but not ideal. |

---

## 9. Data Files

| File | Purpose |
|---|---|
| `data/version_state.json` | Tracks last V1/V2 version per slot — drives alternation |
| `data/pipeline_ran_today.json` | Prevents double-running same slot on same day (shared laptop↔Oracle via SCP) |
| `data/pipeline_crash.log` | Appended on every error and on every successful slot completion |
| `data/pipeline_step.txt` | Current step of the running pipeline (cleared on completion) |
| `data/post_log.json` | Log of every post with platform IDs |
| `data/sync_status.json` | Recent run summaries (last 30 runs, laptop + Oracle) |
| `data/commander.pid` | PID of the running commander process |
| `data/pending_approval_{slot}.json` | Written by pipeline when waiting for Telegram approval |
| `data/web_approval_{slot}.json` | Written by commander when user taps a button |
| `data/pending_posts.json` | Posts that failed on Oracle, queued for laptop retry |
| `data/trending_hashtags.json` | Today's hashtag set (refreshed Slot 1) |
| `data/hook_patterns.json` | Extracted patterns from high-performing hooks |
| `data/hook_analysis_log.json` | Hook history + similarity cache |
| `data/music_log.json` | Today's music tracks |
| `data/query_bank.json` | Pexels/Pixabay search query pool |
| `data/query_hits.json` | Query hit rates (drives query selection) |
| `data/kling_library.json` | Kling clip metadata + cooldown dates |
| `data/tg_offset.json` | Telegram getUpdates offset (prevents reprocessing old messages) |
| `data/memory.json` | Claude memory context (content variety, topics used, tone calibration) |

---

## 10. Key Scripts at a Glance

| Script | Role |
|---|---|
| `pipeline.py` | Main orchestrator — called per slot |
| `pipeline_kling.py` | V2 orchestrator — called by pipeline.py when V2's turn |
| `deploy/dispatch_scheduler.py` | Multi-client scheduler, runs every 15 min |
| `scripts/telegram_commander.py` | Always-on Telegram bot + approval handler |
| `scripts/generate_content.py` | AI content generation (story, captions, hashtags) |
| `scripts/render_video.py` | V1 video assembly (25s Pexels/Pixabay) |
| `scripts/render_kling_video.py` | V2 video assembly (15s Kling clip) |
| `scripts/generate_hook.py` | 2s cinematic hook clip engine |
| `scripts/generate_kling.py` | Generates new Kling clips for the library |
| `scripts/analyse_kling_library.py` | Scans kling_library/, maintains cooldown log |
| `scripts/fetch_trending_music.py` | Fetches today's trending music tracks |
| `scripts/fetch_trending_hashtags.py` | Fetches trending hashtags via Perplexity |
| `scripts/hook_analyzer.py` | Analyses post performance, extracts hook patterns |
| `scripts/engage.py` | Engagement bot — runs every 2h on Oracle |
| `scripts/scene_planner.py` | Plans visual scenes for each story beat |
| `scripts/sync_tiktok_analytics.py` | Pulls TikTok analytics for performance tracking |
| `post_tiktok_zernio.py` | TikTok posting via Zernio OAuth |
| `post_instagram.py` | Instagram Reel posting via Meta Graph API |
| `post_youtube.py` | YouTube Shorts posting via Data API v3 |
| `post_newspaper.py` | Newspaper image rendering + IG feed post |
| `post_linkedin.py` | LinkedIn video post (weekdays only) |
| `post_blog.py` | SEO blog article → Blogger API |
| `deploy/sync_data.ps1` | Syncs `data/` between laptop and Oracle |
| `deploy/set_cron.sh` | Sets up Oracle's cron jobs (run to restore) |

---

## 11. The Kling Library

`kling_library/` folder contains MP4 clips generated by Kling AI. These are the source material for V2 videos.

- New clips are generated daily by `scripts/generate_kling.py` (called from pipeline.py Stage 0c)
- After generating, the clip is sent to Telegram for **manual review** — you decide whether to approve it for the library
- Approved clips sit in `kling_library/` until they're used in a V2 run
- Once used in a V2 video, the clip gets a **14-day cooldown** (tracked in `data/kling_library.json`)
- `scripts/analyse_kling_library.py → available_clips()` returns only clips not on cooldown, sorted by `boothop_fit` score

---

## 12. Content Pillars & Rotation

7 content angles rotate through the week. Each slot has its own rotation so no two slots on the same day cover the same topic.

| Day | Slot 1 | Slot 2 | Slot 3 |
|---|---|---|---|
| Monday | family | courier_business | urgent_medical |
| Tuesday | travel_hacks | airport_deliveries | travel_hacks |
| Wednesday | airport | personal_shopper | cultural_earn |
| Thursday | cost_pain | community | airport_deliveries |
| Friday | community / faith_friday | multi_courier | smart |
| Saturday | humans_of_boothop | airport | cost_pain |
| Sunday | founder_story | family | family |

B2B pillars (`courier_business`, `multi_courier`) post to Instagram only — never TikTok or YouTube.

There's also a **wildcard pillar** (`flight_discovery`) that randomly injects into ~1 in 10 slot runs.

---

## 13. Common Operations

### Check if pipeline is running
```powershell
Get-Content data\pipeline_step.txt
Get-ScheduledTaskInfo -TaskName "OTB_MultiClientDispatcher" | Select LastRunTime, LastTaskResult
```

### Force-run a slot now
```powershell
cd C:\users\babso\desktop\otb_pipeline
python pipeline.py --slot 1 --force
```

### Force V2 for next slot
```
/v2   (via Telegram)
```
or:
```powershell
python pipeline.py --slot 1 --version v2
```

### Check Oracle logs
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.32 "tail -50 /home/ubuntu/otb_pipeline.log"
```

### View last 50 crash log entries
```powershell
Get-Content data\pipeline_crash.log -Tail 50
```

### Re-enable all scheduled tasks after they've been disabled
```powershell
Get-ScheduledTask | Where-Object TaskName -like "OTB_*" | Enable-ScheduledTask
```

### Restore Oracle cron jobs (if lost)
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.32 "bash /opt/otb_pipeline/deploy/set_cron.sh"
```

### Restart Oracle commander
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.32 "sudo systemctl restart otb-commander"
```

### Kill a duplicate commander on the laptop
```powershell
Get-Process python | Select-Object Id, StartTime
# Then kill whichever one is older:
Stop-Process -Id <OLD_PID> -Force
```

### Sync latest pipeline code to Oracle
```powershell
git push origin main   # push laptop changes to GitHub
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@140.238.73.32 "cd /opt/otb_pipeline && git stash && git pull origin main"
# Then copy un-tracked V2 files:
scp -i $k pipeline_kling.py ubuntu@140.238.73.32:/opt/otb_pipeline/
scp -i $k scripts/render_kling_video.py ubuntu@140.238.73.32:/opt/otb_pipeline/scripts/
scp -i $k scripts/analyse_kling_library.py ubuntu@140.238.73.22:/opt/otb_pipeline/scripts/
```

---

## 14. Known Gotchas

**Duplicate commanders → 409 Conflicts**
If both the Oracle commander and the laptop commander are running simultaneously, they both poll Telegram's getUpdates endpoint and get `409 Conflict`. Each backs off 30 seconds and retries. Approval buttons still work — one eventually processes the tap — but there may be a 30s delay. To check:
```powershell
Get-Process python | Select-Object Id, StartTime
```
Kill older PIDs. Oracle's commander always runs. Laptop's should only start when the laptop's Task Scheduler fires `OTB_Commander`.

**Scheduled tasks disabled**
The Task Scheduler tasks can end up in a `Disabled` state. This happened in August 2026 (all 10 tasks disabled from Aug 11). Re-enable with the command in section 13.

**Version_state.json drift**
If a slot keeps running the same version (always V1 or always V2), check `data/version_state.json`. The `next_version` field should alternate between `"v1"` and `"v2"`. If it's stuck, edit the file manually or use `/v1` or `/v2` in Telegram.

**Oracle code out of date**
Oracle pulls from GitHub every 5 minutes (via cron). But files not tracked in git (`pipeline_kling.py`, `scripts/render_kling_video.py`, `scripts/analyse_kling_library.py`) must be manually SCPed. See the sync command in section 13.

**TikTok 3-hour rate limit**
If TikTok fails with a rate-limit error, it means two posts went out within 3 hours. The pipeline has a guard but if you force-run manually, be aware. Wait 3 hours before the next TikTok post.

**YouTube re-auth**
YouTube OAuth tokens expire. If you see `YT comment access denied — token may need re-auth`, run:
```powershell
python scripts/auth_youtube.py
```
Then approve in the browser and the new token saves to `scripts/youtube_token.json`.

**No post despite pipeline running**
1. Check `data/pipeline_crash.log` for the error
2. Check `data/pipeline_step.txt` — is the pipeline stuck at a step?
3. Check if it's in the Telegram approval window — approve or wait for timeout
4. Check `data/pipeline_ran_today.json` — was the slot marked as already-ran prematurely?
