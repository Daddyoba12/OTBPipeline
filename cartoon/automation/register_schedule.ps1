# Register BOUNCE ON THE MOVE weekly scheduler
# Runs every Sunday at 06:00 — produces 2 episodes (Tuesday + Thursday ready to post)
# Run this script once as Administrator to install the Task Scheduler entry

$PythonPath  = "C:\Python314\python.exe"
$RunnerPath  = "$PSScriptRoot\episode_runner.py"
$PipelineDir = Split-Path $PSScriptRoot -Parent | Split-Path -Parent

$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$RunnerPath`" --batch 2" `
    -WorkingDirectory $PipelineDir

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "06:00AM"

Register-ScheduledTask `
    -TaskName "BootHop-Cartoon-Sunday" `
    -Action $Action `
    -Trigger $Trigger `
    -RunLevel Highest `
    -Force

Write-Host "Cartoon schedule registered: every Sunday at 06:00 (batch 2 episodes)"
Write-Host ""
Write-Host "To post an episode to Telegram manually at any time:"
Write-Host "  python `"$RunnerPath`" --post 1"
Write-Host "  python `"$RunnerPath`" --post 2"
