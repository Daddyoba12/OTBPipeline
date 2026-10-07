# Run this from an ELEVATED PowerShell (right-click -> Run as administrator).
#
# Adds NewsFlash to the dispatcher-driven task model (see split_dispatcher_tasks.ps1
# for the original 3-client split). Previously NewsFlash ran on its own standalone
# daily task (OTB-NewsFlash) with no Oracle equivalent and no dedup — see
# HOW_IT_RUNS.md Known Gotchas, fixed 2026-10-07. This creates OTB_Dispatch_NewsFlash
# (same pattern as OTB_Dispatch_BootHop/GInspired/D818: dispatch_scheduler.py
# --client newsflash, every 15 min, logging to logs\dispatch_scheduler.log) and
# disables (not deletes) the old standalone task.

$taskName = "OTB_Dispatch_NewsFlash"
$logPath  = "C:\Users\babso\Desktop\OTB_Pipeline\logs\dispatch_scheduler.log"
$cmd      = "& 'C:\Python314\python.exe' 'C:\users\babso\desktop\otb_pipeline\deploy\dispatch_scheduler.py' --client newsflash *>> '$logPath'"

$trigger   = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId "babso" -LogonType Interactive -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable
$action    = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$cmd`""

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Output "$taskName already exists - skipping (delete it first if you want to recreate)"
} else {
    try {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -ErrorAction Stop | Out-Null
        Write-Output "Created $taskName (--client newsflash, every 15 min, logs to $logPath)"
    } catch {
        Write-Output "FAILED to create $taskName : $_"
        Write-Output "(Must be run from an elevated/Administrator PowerShell - these tasks use RunLevel Highest.)"
    }
}

if (Get-ScheduledTask -TaskName "OTB-NewsFlash" -ErrorAction SilentlyContinue) {
    try {
        Disable-ScheduledTask -TaskName "OTB-NewsFlash" -ErrorAction Stop | Out-Null
        Write-Output "Disabled OTB-NewsFlash (old standalone daily task) - OTB_Dispatch_NewsFlash replaces it."
    } catch {
        Write-Output "FAILED to disable OTB-NewsFlash : $_"
        Write-Output "(Must be run from an elevated/Administrator PowerShell.)"
    }
}

Write-Output ""
Write-Output "Verify with:"
Write-Output "  Get-ScheduledTask -TaskName 'OTB_Dispatch_NewsFlash','OTB-NewsFlash' | Select-Object TaskName, State"
