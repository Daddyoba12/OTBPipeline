# Run this from an ELEVATED PowerShell (right-click -> Run as administrator).
# Splits the single OTB_MultiClientDispatcher task into 3 independent per-client
# tasks so one client hanging can never block another (see the incident this
# fixes: BootHop Slot 3 hung on 2026-09-27 21:34, blocking D818's 20:00 slot
# for the rest of the night because the old dispatcher processed clients
# sequentially in one shared loop/process).
#
# Each new task is an exact copy of the working OTB_MultiClientDispatcher
# task's schedule/principal/settings, just filtered to one client via the
# --client flag added to deploy/dispatch_scheduler.py.

$clients = @(
    @{ Slug = "boothop";    TaskName = "OTB_Dispatch_BootHop" },
    @{ Slug = "g_inspired"; TaskName = "OTB_Dispatch_GInspired" },
    @{ Slug = "d818";       TaskName = "OTB_Dispatch_D818" }
)

$trigger   = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId "babso" -LogonType Interactive -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable

foreach ($c in $clients) {
    $arg = "-WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& 'C:\Python314\python.exe' 'C:\users\babso\desktop\otb_pipeline\deploy\dispatch_scheduler.py' --client $($c.Slug)`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg

    if (Get-ScheduledTask -TaskName $c.TaskName -ErrorAction SilentlyContinue) {
        Write-Output "$($c.TaskName) already exists — skipping (delete it first if you want to recreate)"
        continue
    }
    Register-ScheduledTask -TaskName $c.TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    Write-Output "Created $($c.TaskName) (--client $($c.Slug), every 15 min)"
}

# Disable (not delete) the old combined task — kept as a manual fallback.
Disable-ScheduledTask -TaskName "OTB_MultiClientDispatcher" | Out-Null
Write-Output "Disabled OTB_MultiClientDispatcher (old combined task) — the 3 new tasks replace it."

Write-Output ""
Write-Output "Done. Verify with:"
Write-Output "  Get-ScheduledTask -TaskName 'OTB_Dispatch_*' | Select-Object TaskName, State"
