# OTB_Pipeline — Windows Task Scheduler setup
# Run this ONCE as Administrator to register the sync tasks.
# Right-click PowerShell → "Run as administrator" → paste this command:
#   powershell -ExecutionPolicy Bypass -File "C:\users\babso\desktop\otb_pipeline\deploy\setup_scheduler.ps1"

$SyncScript = "C:\users\babso\desktop\otb_pipeline\deploy\sync_data.ps1"
$PsArgs     = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$SyncScript`" -Direction pull"

Write-Host "OTB Pipeline — registering Task Scheduler sync tasks..." -ForegroundColor Cyan

# ── Task 1: Pull from Oracle every 30 minutes ─────────────────────────────────
# Keeps laptop data current while awake. Also catches wake-from-sleep.
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $PsArgs
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -WakeToRun $false

Register-ScheduledTask `
    -TaskName    "OTB_SyncFromOracle_30min" `
    -Description "Pull pipeline data from Oracle every 30 min" `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null

Write-Host "  OK  OTB_SyncFromOracle_30min" -ForegroundColor Green

# ── Task 2: Pull immediately on screen unlock (wake from sleep / laptop open) ─
$action2 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $PsArgs
$trigger2 = New-ScheduledTaskTrigger -AtLogOn

$settings2 = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName    "OTB_WakeSync" `
    -Description "Pull Oracle data when laptop wakes/unlocks" `
    -Action      $action2 `
    -Trigger     $trigger2 `
    -Settings    $settings2 `
    -RunLevel    Highest `
    -Force | Out-Null

Write-Host "  OK  OTB_WakeSync (on logon/unlock)" -ForegroundColor Green

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Done. Two tasks registered:" -ForegroundColor Green
Write-Host "  OTB_SyncFromOracle_30min  — runs every 30 min while laptop is on"
Write-Host "  OTB_WakeSync              — runs at logon (catches every wake)"
Write-Host ""
Write-Host "Both tasks pull data/pipeline_ran_today.json and data/sync_status.json"
Write-Host "from Oracle so the laptop always knows what Oracle ran while you were sleeping."
Write-Host ""
Write-Host "To check sync status at any time:"
Write-Host "  cd C:\users\babso\desktop\otb_pipeline"
Write-Host "  .\deploy\sync_data.ps1"

Get-ScheduledTask -TaskName "OTB_SyncFromOracle_30min","OTB_WakeSync" -ErrorAction SilentlyContinue |
    Select-Object TaskName, State
