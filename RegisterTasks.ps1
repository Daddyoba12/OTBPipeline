# OTB_Pipeline - Register Task Scheduler tasks
# Run as Administrator once

$Python   = "C:\Python314\python.exe"
$Pipeline = "C:\Users\babso\Desktop\OTB_Pipeline\pipeline.py"
$Cmdr     = "C:\Users\babso\Desktop\OTB_Pipeline\scripts\telegram_commander.py"
$Music    = "C:\Users\babso\Desktop\OTB_Pipeline\scripts\fetch_trending_music.py"
$WorkDir  = "C:\Users\babso\Desktop\OTB_Pipeline"

New-Item -ItemType Directory -Force "$WorkDir\data" | Out-Null

$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

function Register-OTBTask {
    param($Name, $Hour, $Minute, $Slot)
    $action   = New-ScheduledTaskAction -Execute $Python -Argument "$Pipeline --slot $Slot" -WorkingDirectory $WorkDir
    $trigger  = New-ScheduledTaskTrigger -Daily -At ('{0}:{1:D2}' -f $Hour, $Minute)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 5) -RunOnlyIfNetworkAvailable -StartWhenAvailable
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $Principal -Description "OTB slot $Slot" | Out-Null
    $minStr = "{0:D2}" -f $Minute
    Write-Output "Registered: $Name at ${Hour}:$minStr"
}

# Music refresh at 6:00am — downloads 4 trending tracks (one per slot) before Slot 1 fires.
# Uses YouTube API: Nigeria trending -> UK Grime -> US R&B -> Amapiano -> archive fallback.
# 7-day no-repeat. If already fresh today, skips automatically (--skip-if-fresh).
$musicAction   = New-ScheduledTaskAction -Execute $Python -Argument "$Music --skip-if-fresh" -WorkingDirectory $WorkDir
$musicTrigger  = New-ScheduledTaskTrigger -Daily -At "06:00"
$musicSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RunOnlyIfNetworkAvailable
Unregister-ScheduledTask -TaskName "OTB-MusicRefresh" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "OTB-MusicRefresh" -Action $musicAction -Trigger $musicTrigger -Settings $musicSettings -Principal $Principal -Description "OTB daily trending music download" | Out-Null
Write-Output "Registered: OTB-MusicRefresh at 06:00"

# Slot times account for ~10min generation+render so the post lands IN the peak window
# Slot 1: 7:00am  -> posts ~7:10am  (morning commute peak)
# Slot 2: 12:00pm -> posts ~12:10pm (lunch scroll peak)
# Slot 3: 5:30pm  -> posts ~5:40pm  (evening peak 6-8pm — arrives early to catch it)
# Slot 4: 8:30pm  -> posts ~8:40pm  (night scroll peak, also 9-11pm Nigeria time)
Register-OTBTask -Name "OTB-Slot1" -Hour 7  -Minute 0  -Slot 1
Register-OTBTask -Name "OTB-Slot2" -Hour 12 -Minute 0  -Slot 2
Register-OTBTask -Name "OTB-Slot3" -Hour 17 -Minute 30 -Slot 3
Register-OTBTask -Name "OTB-Slot4" -Hour 20 -Minute 30 -Slot 4

# Commander - runs at startup, restarts on failure
$cmdAction   = New-ScheduledTaskAction -Execute $Python -Argument $Cmdr -WorkingDirectory $WorkDir
$cmdTrigger  = New-ScheduledTaskTrigger -AtStartup
$cmdSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 5) -RunOnlyIfNetworkAvailable
Unregister-ScheduledTask -TaskName "OTB-Commander" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "OTB-Commander" -Action $cmdAction -Trigger $cmdTrigger -Settings $cmdSettings -Principal $Principal -Description "OTB Telegram commander" | Out-Null
Write-Output "Registered: OTB-Commander (at startup)"

Write-Output ""
Write-Output "All OTB tasks:"
Get-ScheduledTask | Where-Object { $_.TaskName -like "OTB-*" } | Select-Object TaskName, State | Format-Table -AutoSize
