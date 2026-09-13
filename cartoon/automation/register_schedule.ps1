# Register BOUNCE ON THE MOVE scheduler
#
# FLOW:
#   Sunday   06:00  → Produce 3 episodes (batch), send all to Telegram with Post Now buttons
#   Sunday   06:00  → Listen 30min for Post Now taps after batch
#   Tue/Thu/Sat 09:00 → Auto-post next queued episode to YouTube (if not already posted via Post Now)
#
# TikTok: posted manually by the user whenever they want
# Run this script once as Administrator

$PythonPath  = "C:\Python314\python.exe"
$RunnerPath  = "$PSScriptRoot\episode_runner.py"
$YTPostPath  = "$PSScriptRoot\post_cartoon_youtube.py"
$PipelineDir = Split-Path $PSScriptRoot -Parent | Split-Path -Parent

# ── Sunday: produce 3 episodes as a batch ─────────────────────────────────────
$ActionBatch = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$RunnerPath`" --batch 3" `
    -WorkingDirectory $PipelineDir

$TriggerSun = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "06:00AM"
Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-Batch" `
    -Action $ActionBatch -Trigger $TriggerSun `
    -RunLevel Highest -Force

# ── Sunday: listen 30min for Post Now button taps right after batch ────────────
$ActionListen = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$YTPostPath`" --listen 1800" `
    -WorkingDirectory $PipelineDir

$TriggerSunListen = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "06:30AM"
Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-PostNow-Listener" `
    -Action $ActionListen -Trigger $TriggerSunListen `
    -RunLevel Highest -Force

# ── Tue/Thu/Sat 09:00: auto-post next queued episode to YouTube ───────────────
$ActionYT = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$YTPostPath`" --scheduled" `
    -WorkingDirectory $PipelineDir

$TriggerTue = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday   -At "09:00AM"
Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-YouTube-Tuesday" `
    -Action $ActionYT -Trigger $TriggerTue `
    -RunLevel Highest -Force

$TriggerThu = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday  -At "09:00AM"
Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-YouTube-Thursday" `
    -Action $ActionYT -Trigger $TriggerThu `
    -RunLevel Highest -Force

$TriggerSat = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday  -At "09:00AM"
Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-YouTube-Saturday" `
    -Action $ActionYT -Trigger $TriggerSat `
    -RunLevel Highest -Force

Write-Host ""
Write-Host "Cartoon schedule registered:"
Write-Host "  Sunday 06:00      Produce 3 episodes, send to Telegram with Post Now button"
Write-Host "  Sunday 06:30      Listen 30min for Post Now taps"
Write-Host "  Tue/Thu/Sat 09:00 Auto-post next queued episode to YouTube"
Write-Host ""
Write-Host "TikTok: post manually from Telegram whenever you want."
Write-Host "To re-send an episode to Telegram: python `"$RunnerPath`" --post N"
Write-Host "To post an episode to YouTube now: python `"$YTPostPath`" --post N"
Write-Host ""
Write-Host "IMPORTANT: Run as Administrator for Task Scheduler registration to succeed."
