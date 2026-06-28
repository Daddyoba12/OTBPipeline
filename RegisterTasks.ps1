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

# Slot times aligned to timing.docx grid (accounts for ~10min render before post lands):
# Slot 1: 07:00 -> posts ~07:10  IG Story + Blog + Newspaper + LinkedIn
# Slot 2: 08:50 -> posts ~09:00  TikTok V1 + IG Reel  (premium 9am slot)
# Slot 3: 17:50 -> posts ~18:00  TikTok V2 + IG Reel + IG Story  (evening peak)
# Slot 4: 20:20 -> posts ~20:30  TikTok + YouTube  (night scroll / Nigeria prime time)
Register-OTBTask -Name "OTB-Slot1" -Hour 7  -Minute 0  -Slot 1
Register-OTBTask -Name "OTB-Slot2" -Hour 8  -Minute 50 -Slot 2
Register-OTBTask -Name "OTB-Slot3" -Hour 17 -Minute 50 -Slot 3
Register-OTBTask -Name "OTB-Slot4" -Hour 20 -Minute 20 -Slot 4

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
