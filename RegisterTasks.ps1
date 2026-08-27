# OTB_Pipeline — Register Task Scheduler tasks
# Run as Administrator once to activate the 3-slot + LinkedIn/Blog schedule.

$Python   = "C:\Python314\python.exe"
$Pipeline = "C:\Users\babso\Desktop\OTB_Pipeline\pipeline.py"
$Cmdr     = "C:\Users\babso\Desktop\OTB_Pipeline\scripts\telegram_commander.py"
$Music    = "C:\Users\babso\Desktop\OTB_Pipeline\scripts\fetch_trending_music.py"
$WorkDir  = "C:\Users\babso\Desktop\OTB_Pipeline"

New-Item -ItemType Directory -Force "$WorkDir\data" | Out-Null

$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Remove any existing OTB tasks (clean slate)
$oldTasks = @("OTB-Slot1","OTB-Slot2","OTB-Slot3","OTB-Slot4","OTB_Slot1","OTB_Slot2","OTB_Slot3","OTB_Slot4")
foreach ($t in $oldTasks) {
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Write-Output "Old slot tasks cleared."

function Register-OTBSlot {
    param($Name, $Hour, $Minute, $Slot, $DaysOfWeek = $null)
    $action   = New-ScheduledTaskAction -Execute $Python -Argument "$Pipeline --slot $Slot" -WorkingDirectory $WorkDir
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 5) -RunOnlyIfNetworkAvailable -StartWhenAvailable

    if ($DaysOfWeek) {
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DaysOfWeek -At ('{0}:{1:D2}' -f $Hour, $Minute)
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At ('{0}:{1:D2}' -f $Hour, $Minute)
    }

    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $Principal -Description "OTB slot $Slot" | Out-Null
    $dayStr = if ($DaysOfWeek) { " ($DaysOfWeek)" } else { " (daily)" }
    Write-Output "Registered: $Name at ${Hour}:$("{0:D2}" -f $Minute)$dayStr"
}

# Music refresh at 06:00 — downloads trending tracks before first slot fires
$musicAction   = New-ScheduledTaskAction -Execute $Python -Argument "$Music --skip-if-fresh" -WorkingDirectory $WorkDir
$musicTrigger  = New-ScheduledTaskTrigger -Daily -At "06:00"
$musicSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RunOnlyIfNetworkAvailable
Unregister-ScheduledTask -TaskName "OTB-MusicRefresh" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "OTB-MusicRefresh" -Action $musicAction -Trigger $musicTrigger -Settings $musicSettings -Principal $Principal -Description "OTB daily trending music download" | Out-Null
Write-Output "Registered: OTB-MusicRefresh at 06:00 (daily)"

# ── Slot 1 — 09:00 daily — TikTok + Instagram + YouTube
# UK morning commute / Nigeria late morning / 4am EST
# 60-min Telegram review window (configured in TELEGRAM_BUFFER_MINUTES)
Register-OTBSlot -Name "OTB-Slot1" -Hour 9  -Minute 0  -Slot 1

# ── Slot 2 — 15:00 daily — TikTok + Instagram + YouTube
# UK afternoon / US morning (10am EST) / Nigeria evening
# 30-min Telegram review window
Register-OTBSlot -Name "OTB-Slot2" -Hour 15 -Minute 0  -Slot 2

# ── Slot 3 — 22:00 daily — TikTok + Instagram + YouTube
# US prime time (5-6pm EST) / Nigeria night / UK late
# 30-min Telegram review window — highest-stakes slot
Register-OTBSlot -Name "OTB-Slot3" -Hour 22 -Minute 0  -Slot 3

# ── Slot 4 — 09:00 Tue+Fri — LinkedIn + Blog (Telegram-gated, not --force)
Register-OTBSlot -Name "OTB-Slot4" -Hour 9  -Minute 0  -Slot 4 -DaysOfWeek "Tuesday","Friday"

# ── Commander — runs at startup, keeps the Telegram bot alive
$cmdAction   = New-ScheduledTaskAction -Execute $Python -Argument $Cmdr -WorkingDirectory $WorkDir
$cmdTrigger  = New-ScheduledTaskTrigger -AtStartup
$cmdSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 5) -RunOnlyIfNetworkAvailable
Unregister-ScheduledTask -TaskName "OTB-Commander" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "OTB-Commander" -Action $cmdAction -Trigger $cmdTrigger -Settings $cmdSettings -Principal $Principal -Description "OTB Telegram commander" | Out-Null
Write-Output "Registered: OTB-Commander (at startup)"

# ── Follower Tracker — 09:30 daily — snapshots IG + TikTok follower counts
$followerScript   = "C:\Users\babso\Desktop\OTB_Pipeline\scripts\follower_tracker.py"
$followerAction   = New-ScheduledTaskAction -Execute $Python -Argument $followerScript -WorkingDirectory $WorkDir
$followerTrigger  = New-ScheduledTaskTrigger -Daily -At "09:30"
$followerSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RunOnlyIfNetworkAvailable -StartWhenAvailable
Unregister-ScheduledTask -TaskName "OTB-FollowerTracker" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "OTB-FollowerTracker" -Action $followerAction -Trigger $followerTrigger -Settings $followerSettings -Principal $Principal -Description "OTB daily IG + TikTok follower snapshot" | Out-Null
Write-Output "Registered: OTB-FollowerTracker at 09:30 (daily)"

# ── SEO Weekly — 08:00 Monday — PageSpeed + sitemap health + Google ping
$seoScript   = "C:\Users\babso\Desktop\OTB_Pipeline\scripts\seo_weekly_report.py"
$seoAction   = New-ScheduledTaskAction -Execute $Python -Argument $seoScript -WorkingDirectory $WorkDir
$seoTrigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00"
$seoSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -RunOnlyIfNetworkAvailable -StartWhenAvailable
Unregister-ScheduledTask -TaskName "OTB-SEOWeekly" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "OTB-SEOWeekly" -Action $seoAction -Trigger $seoTrigger -Settings $seoSettings -Principal $Principal -Description "BootHop weekly SEO audit + Telegram report" | Out-Null
Write-Output "Registered: OTB-SEOWeekly at 08:00 (Monday)"

# ── GA4 Weekly — 08:05 Monday — Google Analytics data report
$ga4Script   = "C:\Users\babso\Desktop\OTB_Pipeline\scripts\ga4_weekly_report.py"
$ga4Action   = New-ScheduledTaskAction -Execute $Python -Argument $ga4Script -WorkingDirectory $WorkDir
$ga4Trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:05"
$ga4Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RunOnlyIfNetworkAvailable -StartWhenAvailable
Unregister-ScheduledTask -TaskName "OTB-GA4Weekly" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "OTB-GA4Weekly" -Action $ga4Action -Trigger $ga4Trigger -Settings $ga4Settings -Principal $Principal -Description "BootHop weekly GA4 analytics report" | Out-Null
Write-Output "Registered: OTB-GA4Weekly at 08:05 (Monday)"

Write-Output ""
Write-Output "Active OTB tasks:"
Get-ScheduledTask | Where-Object { $_.TaskName -like "OTB-*" } | Select-Object TaskName, State | Format-Table -AutoSize
