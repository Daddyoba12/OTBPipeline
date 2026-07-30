# OTB_Pipeline — Windows Task Scheduler setup
# Run ONCE as Administrator to register all pipeline tasks.
#
# Right-click PowerShell → "Run as administrator" → paste:
#   powershell -ExecutionPolicy Bypass -File "C:\users\babso\desktop\otb_pipeline\deploy\setup_scheduler.ps1"

$Python     = "C:\Python314\python.exe"
$Base       = "C:\users\babso\desktop\otb_pipeline"
$Dispatcher = "$Base\deploy\dispatch_scheduler.py"
$SyncScript = "$Base\deploy\sync_data.ps1"

Write-Host "OTB Pipeline — registering Task Scheduler tasks..." -ForegroundColor Cyan

# ── Remove old broken individual-slot tasks (wrong times / wrong interval) ───
Write-Host "`nRemoving old slot tasks..." -ForegroundColor Yellow
foreach ($old in @("OTB-Slot1","OTB-Slot2","OTB-Slot3","OTB-Slot4",
                   "OTB-Morning","OTB-Afternoon","OTB-Evening")) {
    if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $old -Confirm:$false
        Write-Host "  Removed: $old"
    }
}

# ── Task 1: Multi-client dispatcher — every 15 min ───────────────────────────
# Reads each client's schedule from client_profile.json and fires at correct local time.
# 15-min interval + 30-min window = guaranteed to catch every slot even if laptop wakes late.
$DispArgs = "-WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& '$Python' '$Dispatcher'`""
$action1  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $DispArgs
$trigger1 = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 15) -Once -At (Get-Date)
$settings1 = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 120) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName    "OTB_MultiClientDispatcher" `
    -Description "Fires BootHop (08:00/14:00/21:00 UK) and G-Inspired (09:00/13:00/18:00 CT) pipeline slots" `
    -Action      $action1 `
    -Trigger     $trigger1 `
    -Settings    $settings1 `
    -RunLevel    Highest `
    -Force | Out-Null

Write-Host "  OK  OTB_MultiClientDispatcher (every 15 min)" -ForegroundColor Green

# ── Task 2: Oracle data sync — pull every 30 min ─────────────────────────────
$SyncArgs = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$SyncScript`" -Direction pull"
$action2  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $SyncArgs
$trigger2 = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At (Get-Date)
$settings2 = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName    "OTB_SyncFromOracle_30min" `
    -Description "Pull pipeline data from Oracle every 30 min" `
    -Action      $action2 `
    -Trigger     $trigger2 `
    -Settings    $settings2 `
    -RunLevel    Highest `
    -Force | Out-Null

Write-Host "  OK  OTB_SyncFromOracle_30min" -ForegroundColor Green

# ── Task 3: Pull on logon / wake from sleep ───────────────────────────────────
$action3  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $SyncArgs
$trigger3 = New-ScheduledTaskTrigger -AtLogOn
$settings3 = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName    "OTB_WakeSync" `
    -Description "Pull Oracle data when laptop wakes/unlocks" `
    -Action      $action3 `
    -Trigger     $trigger3 `
    -Settings    $settings3 `
    -RunLevel    Highest `
    -Force | Out-Null

Write-Host "  OK  OTB_WakeSync (on logon/unlock)" -ForegroundColor Green

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Done. Active tasks:" -ForegroundColor Green
Get-ScheduledTask -TaskName "OTB_MultiClientDispatcher","OTB_SyncFromOracle_30min","OTB_WakeSync" `
    -ErrorAction SilentlyContinue | Select-Object TaskName, State

Write-Host ""
Write-Host "Pipeline schedule:" -ForegroundColor Cyan
Write-Host "  BootHop (Europe/London)      — 08:00, 14:00, 21:00 UK"
Write-Host "  BootHop Slot 4 (Tue/Fri)    — 08:00 UK"
Write-Host "  G-Inspired (America/Chicago) — 09:00, 13:00, 18:00 CT"
Write-Host "  G-Inspired Slot 4 (Tue/Fri) — 09:00 CT"
Write-Host ""
Write-Host "Check schedule:    python deploy/dispatch_scheduler.py --status"
Write-Host "Force test slot 1: python pipeline.py --slot 1 --no-post"
