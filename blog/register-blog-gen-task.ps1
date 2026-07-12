# Register BootHop-DailyBlog task — generates a fresh blog post at 8:00am daily
$action  = New-ScheduledTaskAction -Execute "python" -Argument "C:\Users\babso\Desktop\BootHopPipeline\blog\generate_daily_blog.py" -WorkingDirectory "C:\Users\babso\Desktop\BootHopPipeline\blog"
$trigger = New-ScheduledTaskTrigger -Daily -At "08:00AM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
  -TaskName    "BootHop-DailyBlog" `
  -Action      $action `
  -Trigger     $trigger `
  -Settings    $settings `
  -RunLevel    Highest `
  -Force

Write-Host "BootHop-DailyBlog task registered. Runs daily at 8:00am."
Write-Host "Test now: python C:\Users\babso\Desktop\BootHopPipeline\blog\generate_daily_blog.py"
