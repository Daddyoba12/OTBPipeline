# Register BOUNCE ON THE MOVE weekly scheduler
# Runs every Tuesday and Thursday at 06:00 UK time (Europe/London)
# Run this script once as Administrator to install the Task Scheduler entries

$PythonPath  = "C:\Python314\python.exe"
$RunnerPath  = "$PSScriptRoot\episode_runner.py"
$PipelineDir = Split-Path $PSScriptRoot -Parent | Split-Path -Parent

# Tuesday 06:00
$ActionTue = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$RunnerPath`"" `
    -WorkingDirectory $PipelineDir

$TriggerTue = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Tuesday -At "06:00AM"

Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-Tuesday" `
    -Action $ActionTue `
    -Trigger $TriggerTue `
    -RunLevel Highest `
    -Force

# Thursday 06:00
$ActionThu = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$RunnerPath`"" `
    -WorkingDirectory $PipelineDir

$TriggerThu = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Thursday -At "06:00AM"

Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-Thursday" `
    -Action $ActionThu `
    -Trigger $TriggerThu `
    -RunLevel Highest `
    -Force

Write-Host "Cartoon schedule registered: Tuesday + Thursday at 06:00"
