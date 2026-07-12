# BootHop BlogDrop Task Registration
# Run this script as Administrator (right-click -> Run as administrator)

$taskName   = "BootHop-BlogDrop"
$scriptPath = "C:\Users\babso\Desktop\BootHopPipeline\blog\pdf_drop_to_blog.py"
$python     = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = "python" }

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action    = New-ScheduledTaskAction -Execute $python -Argument "`"$scriptPath`"" -WorkingDirectory "C:\Users\babso\Desktop\BootHopPipeline\blog"
$trigger   = New-ScheduledTaskTrigger -Daily -At "09:30AM"
$settings  = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "BootHop: Post PDFs dropped into blog/drop/ to Blogger daily at 09:30"

Write-Host ""
Write-Host ""
Write-Host "Task registered: $taskName - runs daily at 09:30." -ForegroundColor Green
Write-Host "Drop folder:  C:\Users\babso\Desktop\BootHopPipeline\blog\drop" -ForegroundColor Cyan
Write-Host "Posted PDFs:  C:\Users\babso\Desktop\BootHopPipeline\blog\posted\pdfs" -ForegroundColor Cyan
