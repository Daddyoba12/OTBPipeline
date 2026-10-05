# OTB Pipeline — How It All Runs

*Last updated: 2026-10-05*

---

## 1. The Two Machines

The pipeline runs across two machines that work as primary + backup.

| | Laptop (Windows) | Oracle Cloud VM |
|---|---|---|
| IP / Host | Local | **130.162.162.189** (corrected 2026-10-05 — most docs still say `140.238.73.32`, which is stale/wrong; see Known Gotchas) |
| Primary role | **Backup** — per `dispatch_scheduler.py`, Oracle is primary and the laptop is backup, not the other way round (see §4's window math) | **Primary** — runs pipeline (generates + posts) |
| Telegram Commander | Runs via Task Scheduler | Runs via systemd (`otb-commander.service`) |
| Schedule trigger | Windows Task Scheduler | Linux cron |
| Fires when | Laptop is awake | Always (even when laptop is off) |
| Code source | Local files, pushed to GitHub manually | Its own clone at `/opt/otb_pipeline` — **does NOT auto-pull**. There is no `git pull` cron entry (checked the live crontab 2026-10-05). Only `pipeline.py` calls `_git_pull()` itself at the top of each run; `pipeline_d818.py` and `pipeline_kling.py` have no such call, so fixes to those two files sit on GitHub doing nothing until someone manually `scp`s them over. See Known Gotchas. |
| API keys | `keys.env` in project root | `keys.env` in `/opt/otb_pipeline/` |

**Double-post prevention**: the real, current mechanism is a **Supabase claim**, not just the SCP'd JSON file this section used to describe. Right after a slot's lock is acquired (before content generation even starts), the pipeline writes `{today}:{slot}` into the `otb_pipeline_state` table's `ran_slots_json` column (slot `0` = BootHop, `818` = D818) via `_claim_slot_supabase()`, and also to a local `*_ran_today.json` file. `_already_ran_today()` checks the local file first, then falls back to querying Supabase — so whichever machine claims a slot first, the other sees it within seconds regardless of which machine it is. The local `data/pipeline_ran_today.json` SCP push (`_push_ran_signal_to_oracle()`) still exists as a secondary signal, but Supabase is what actually prevents the double-post.

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

- **OTB_Dispatch_BootHop / OTB_Dispatch_GInspired / OTB_Dispatch_D818** — three **independent** tasks (as of 2026-09-28; see incident note below), each running every 15 minutes, each calling `deploy/dispatch_scheduler.py --client <slug>`. Each checks only its own client's schedule and, if a slot is in-window, runs that client's pipeline script (blocking, with a 90-minute hard timeout — see below). Because each client has its own lock file and now its own task/process entirely, one client hanging can never block another's slot from firing.
- **OTB_MultiClientDispatcher** — the old combined task (all 3 clients in one sequential loop). Disabled, kept only as a manual fallback. Do not re-enable without understanding why it was retired (see below).
- **OTB_Commander** — starts `scripts/telegram_commander.py` and keeps it running.
- **OTB_MusicRefresh** — runs at 06:00, fetches today's trending music tracks.
- **OTB_WeeklyIntelligence** — runs every **Monday at 05:30** (before slot 1). Chains `trend_scout.py` + `weekly_review.py`. Writes `data/trend_report.json` and `data/pillar_weights.json` which the pipeline reads every slot to bias content toward best performers.

> **Why 3 separate tasks instead of 1 (2026-09-28 incident):** on 2026-09-27, BootHop's Slot 3 hung mid-run. Because the old `OTB_MultiClientDispatcher` processed all clients in one sequential loop/process, D818's 20:00 slot never got a turn that night — not a D818 bug, just stuck behind a hung sibling in the same queue. Splitting into 3 independent tasks (via the `--client` flag added to `dispatch_scheduler.py`) removes that class of failure entirely: each client's dispatcher instance is its own OS process with its own lock file, so a hang in one can't touch the others. See `deploy/split_dispatcher_tasks.ps1` for the exact task definitions if these ever need to be recreated.

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
# 3 independent per-client dispatcher runs — see the incident note above.
# dispatch_scheduler.py + each client's client_profile.json is the single
# source of truth for *when* each client posts. Do not add hardcoded
# "pipeline.py --slot N" cron lines here — that was tried before, produced
# near-duplicate runs of the same slot, and was removed on 2026-09-28.
*/10 * * * * cd /opt/otb_pipeline && python3 deploy/dispatch_scheduler.py --client boothop    >> /home/ubuntu/dispatch_scheduler.log 2>&1
*/10 * * * * cd /opt/otb_pipeline && python3 deploy/dispatch_scheduler.py --client g_inspired >> /home/ubuntu/dispatch_scheduler.log 2>&1
*/10 * * * * cd /opt/otb_pipeline && python3 deploy/dispatch_scheduler.py --client d818       >> /home/ubuntu/dispatch_scheduler.log 2>&1

# Weekly intelligence — Monday 05:30 UTC (06:30 London BST) before slot 1 fires
30  5 * * 1    cd /opt/otb_pipeline && python3 scripts/weekly_run.py

# Engagement bot — every 2 hours
0 */2 * * *    cd /opt/otb_pipeline && python3 scripts/engage.py
```

Rebuildable from `deploy/set_cron.sh` (kept in sync with the above).

---

## 4. The Dispatcher (`deploy/dispatch_scheduler.py`)

Every time a `--client <slug>` task/cron entry fires it (every 10–15 min depending on machine), the dispatcher:

1. Filters to just that one client (or, with no `--client` flag, all of them — legacy single-task mode, not used in production anymore)
2. Reads that client's `client_profile.json` → gets timezone + slot times
3. Converts each slot time to UTC
4. Checks if current UTC time is within its machine's window of any slot — Oracle (primary) checks `[nominal-30min, nominal+20min]`, the laptop (backup) checks `[nominal+20min, nominal+50min]`, so the two never overlap and never race
5. If a slot is in-window → runs that client's pipeline script (blocking within this one process, **capped at 90 minutes** — if a child hangs longer than that, the dispatcher force-kills it and exits cleanly rather than freezing forever)
6. Only one slot fires per dispatcher run

Because each client is now its own process (see above), a slow/hung run only ever delays *that* client's next slot by up to 90 minutes — it no longer has any effect on the other two clients' schedules.

### The pipeline lock (`data/pipeline.lock`, `data/d818_pipeline.lock`)

Each client's pipeline script takes an exclusive local lock (a JSON file with `{slot, locked_at}`) at the very start of `run_slot()`, before it does anything else. If the lock file already exists and is less than 90 minutes old, the run reports `"pipeline lock held"` and exits immediately; past 90 minutes it's treated as stale and overwritten. This is a **per-machine, local** lock — it has nothing to do with the cross-machine Supabase claim described above, which is what actually stops two machines from duplicating a post.

**Fixed 2026-10-04/05** (previously the source of repeated "pipeline lock held" Telegram messages — see incident notes below):
1. **Lock wasn't guaranteed to release.** `run_slot()` relied on every individual code path manually calling `_release_lock()` before returning. Any uncaught exception, or the process just dying (laptop sleep mid-run, a killed subprocess), skipped that call entirely and left the lock stuck for the full 90 minutes. Fixed by wrapping the whole locked body in `try/finally: _release_lock()` in `pipeline.py` and `pipeline_d818.py`, so release is now unconditional.
2. **Lock was held through the entire Telegram approval wait and posting, not just rendering.** The slot is already claimed in Supabase the moment a run starts — rendering is the only part that actually needs the local lock (to stop a second dispatcher tick from rendering the same slot twice). Approval-waiting and posting don't need it. Previously the lock stayed held for the full approval window (up to 60 min), so any dispatcher retry landing in that window collided and sent a noisy "lock held, try again shortly" message — even though nothing was actually wrong. Fixed by releasing the lock right after rendering completes, in all three render paths (`pipeline.py` V1, `pipeline_kling.py`'s V2, `pipeline_d818.py`). A retry during a normal approval wait now hits the quiet `_already_ran_today()` skip instead (no Telegram message at all), since the slot's already claimed.

After these two fixes, a `"pipeline lock held"` message should only ever appear for a genuine, currently-in-progress render — if you see one that doesn't resolve within a few minutes, something is actually stuck (check `data/*.lock`'s `locked_at` timestamp and whether a matching python process is really running before deleting it).

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
| Normal day | **Oracle is primary** — its dispatcher window opens first (`[nominal-30min, nominal+20min]`) and it fires the slot, claiming it in Supabase immediately. |
| Laptop's turn comes | The laptop's backup window only opens *after* Oracle's closes (`[nominal+20min, nominal+50min]`) — non-overlapping by design. By the time it checks, Oracle's Supabase claim is already visible, so `_already_ran_today()` returns true and the laptop skips quietly, no render, no Telegram message. |
| Oracle is down/unreachable | Nothing claims the slot in its primary window. The laptop's backup window opens 20+ min later, finds no claim, and runs the pipeline itself. |
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
| `deploy/dispatch_scheduler.py` | Per-client scheduler — run once per client via `--client <slug>`, every 10-15 min |
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
Get-ScheduledTask -TaskName "OTB_Dispatch_*" | Get-ScheduledTaskInfo | Select TaskName, LastRunTime, LastTaskResult
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
ssh -i $k ubuntu@130.162.162.189 "tail -50 /home/ubuntu/dispatch_scheduler.log"
```

### Check laptop dispatcher logs (added 2026-10-05)
The laptop-side `OTB_Dispatch_*` tasks previously redirected their output nowhere — nothing to check if something went wrong. As of 2026-10-05 they append to the same shared log Oracle uses the convention for:
```powershell
Get-Content C:\Users\babso\Desktop\OTB_Pipeline\logs\dispatch_scheduler.log -Tail 50
```
If a task's Action doesn't end in `*>> '...\logs\dispatch_scheduler.log'`, the redirect got lost (e.g. the task was recreated from scratch) — re-add it with `Set-ScheduledTask` (requires an elevated/Admin PowerShell, since these tasks run with `RunLevel: Highest`):
```powershell
$cmd = "& 'C:\Python314\python.exe' 'C:\users\babso\desktop\otb_pipeline\deploy\dispatch_scheduler.py' --client d818 *>> 'C:\Users\babso\Desktop\OTB_Pipeline\logs\dispatch_scheduler.log'"
$newAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$cmd`""
Set-ScheduledTask -TaskName "OTB_Dispatch_D818" -Action $newAction
```

### Check / clear a stuck pipeline lock
```powershell
Get-Content data\pipeline.lock, data\d818_pipeline.lock -ErrorAction SilentlyContinue
```
Before deleting, confirm nothing is actually still running — on Windows: `Get-Process python | Select Id, StartTime`; on Oracle: `ssh ... "ps aux | grep pipeline"`. If the `locked_at` timestamp is old and nothing's running, it's safe to delete:
```powershell
Remove-Item data\pipeline.lock, data\d818_pipeline.lock -ErrorAction SilentlyContinue
```
Since the 2026-10-05 fix (see §4), this should rarely be needed — a crash/hang now self-clears via `try/finally`, and the lock no longer sits held through the whole approval wait. If you're seeing it repeatedly again, something's actually wrong, not just noisy.

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
ssh -i $k ubuntu@130.162.162.189 "bash /opt/otb_pipeline/deploy/set_cron.sh"
```

### Restart Oracle commander
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
ssh -i $k ubuntu@130.162.162.189 "sudo systemctl restart otb-commander"
```

### Kill a duplicate commander on the laptop
```powershell
Get-Process python | Select-Object Id, StartTime
# Then kill whichever one is older:
Stop-Process -Id <OLD_PID> -Force
```

### Sync latest pipeline code to Oracle
**Important (confirmed 2026-10-05): Oracle does NOT auto-pull from git.** There's no `git pull` cron entry, and `git status` on Oracle already shows several locally-modified files that were never committed — so a bare `git pull` risks a merge conflict with Oracle-only changes. Check `git diff <file>` there first; if the diff is something the laptop's current version already includes (i.e. it was already committed properly at some point), it's safe to overwrite. Otherwise, pushing to GitHub does **nothing** on Oracle until someone deploys it:
```powershell
git push origin main   # pushes to GitHub, but Oracle won't see it on its own

$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
# pipeline.py pulls git itself at the top of every run, but ONLY if Oracle's
# working tree has no uncommitted changes blocking the pull — check first:
ssh -i $k ubuntu@130.162.162.189 "cd /opt/otb_pipeline && git status --short"

# pipeline_d818.py and pipeline_kling.py have NO self-pull — always scp them directly:
scp -i $k pipeline_d818.py ubuntu@130.162.162.189:/opt/otb_pipeline/pipeline_d818.py
scp -i $k pipeline_kling.py ubuntu@130.162.162.189:/opt/otb_pipeline/pipeline_kling.py
scp -i $k scripts/render_kling_video.py ubuntu@130.162.162.189:/opt/otb_pipeline/scripts/
scp -i $k scripts/analyse_kling_library.py ubuntu@130.162.162.189:/opt/otb_pipeline/scripts/
```
**Gotcha (found 2026-10-05):** Oracle has a *second*, untracked copy of `pipeline_kling.py` at `scripts/pipeline_kling.py` — a stray duplicate, same byte size as the real one at the time it was found. Because `sys.path` puts `scripts/` ahead of the project root, **that duplicate is the one Python actually imports**, not the root copy. A fix scp'd only to the root file silently does nothing. Deploy to *both* paths until someone deletes the stray copy for good:
```powershell
scp -i $k pipeline_kling.py ubuntu@130.162.162.189:/opt/otb_pipeline/scripts/pipeline_kling.py
```

### Re-authenticate a dead YouTube token (BootHop or D818)
```powershell
python auth_youtube.py        # BootHop's channel — writes scripts/youtube_token.json
python auth_youtube_d818.py   # D818's channel — writes scripts/youtube_token_d818.json
```
A browser opens — log into the correct channel's Google account (not the other one's). **Neither token file is synced to Oracle automatically** — there's no scp/sync step for `youtube_token*.json` anywhere in the deploy scripts. After re-authenticating on the laptop, push it manually or Oracle keeps failing with the same `invalid_grant` error indefinitely:
```powershell
$k = "$env:USERPROFILE\.ssh\oracle_boothop.pem"
scp -i $k scripts/youtube_token_d818.json ubuntu@130.162.162.189:/opt/otb_pipeline/scripts/youtube_token_d818.json
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

**Oracle code out of date (corrected 2026-10-05 — this entry was wrong)**
Oracle does **not** auto-pull from GitHub — there's no `git pull` cron entry on Oracle at all. `pipeline.py` pulls git itself at the start of every run (but can be blocked by Oracle's own uncommitted local changes — check `git status` there first). `pipeline_d818.py` and `pipeline_kling.py` have no self-pull logic whatsoever, so any fix to those two files sits inert on GitHub until manually `scp`'d over. This is exactly what happened 2026-10-04: a lock-handling fix was pushed and tested on the laptop, but Oracle (the *primary* machine — see §1) kept running the old broken code for hours because nothing ever deployed it there. See the sync command in §13, and the duplicate-`pipeline_kling.py` gotcha below.

**Duplicate `scripts/pipeline_kling.py` on Oracle**
Found 2026-10-05: Oracle has a second, untracked copy of `pipeline_kling.py` sitting at `scripts/pipeline_kling.py`, separate from the real tracked one at the project root. Because `sys.path.insert(0, BASE/"scripts")` runs after `sys.path.insert(0, BASE)`, the `scripts/` copy wins import resolution — meaning a fix deployed only to the root file can silently fail to take effect. Always scp to both paths (§13) until this stray copy is deleted.

**TikTok 3-hour rate limit**
If TikTok fails with a rate-limit error, it means two posts went out within 3 hours. The pipeline has a guard but if you force-run manually, be aware. Wait 3 hours before the next TikTok post.

**YouTube re-auth — and it's per-channel AND per-machine**
YouTube OAuth tokens expire or get revoked. If you see `invalid_grant: Token has been expired or revoked` (D818) or `YT comment access denied` (BootHop), re-run the matching script — see §13 for both commands and file paths. Two things that are easy to miss:
- BootHop and D818 are **separate Google accounts/channels** with separate token files — re-authenticating one does nothing for the other.
- **Neither token syncs to Oracle automatically.** Re-authenticating on the laptop only fixes the laptop; Oracle keeps using its own (possibly still-dead) copy until you manually `scp` the new token file over (§13). This bit us 2026-10-05: the D818 token was fixed on the laptop 2026-10-04 but Oracle — which actually handles most D818 posts as primary — kept failing with the exact same error a full day later, because nothing had deployed the fix there.

**Pipeline lock (`data/pipeline.lock`, `data/d818_pipeline.lock`) stuck / repeated "pipeline lock held" messages**
See the dedicated explanation in §4. Short version: fixed 2026-10-04/05 so the lock (a) always releases even on a crash/hang (previously could stay stuck up to 90 min), and (b) releases right after rendering instead of being held through the whole approval wait + posting (previously caused noisy false-positive "lock held, try again shortly" messages on every dispatcher retry during a normal, longer-than-10-min approval wait). If you're seeing this message again now, it means something is genuinely stuck — check `locked_at` age and whether a matching process is actually running (§13) before clearing it.

**No post despite pipeline running**
1. Check `data/pipeline_crash.log` (or `data/d818_pipeline_crash.log`) for the error
2. Check `data/pipeline_step.txt` — is the pipeline stuck at a step?
3. Check if it's in the Telegram approval window — approve or wait for timeout
4. Check Supabase (`otb_pipeline_state` table, `ran_slots_json` column) and the local `*_ran_today.json` — was the slot marked as already-ran prematurely, or claimed by a machine that then failed to actually post?
