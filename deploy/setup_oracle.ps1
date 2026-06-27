# OTB_Pipeline — One-time Oracle server setup
# Run this ONCE after creating the GitHub repo and pushing the first commit.
#
# What it does on Oracle:
#   1. Creates /opt/otb_pipeline directory
#   2. Clones the GitHub repo
#   3. Installs Python dependencies
#   4. Sets up a systemd service for the Telegram Commander
#   5. Sets up a cron job to pull code from GitHub every 5 minutes
#      (this is the Oracle -> Laptop sync path: Oracle pulls GitHub, Laptop pushes GitHub)
#
# Prerequisites:
#   - GitHub repo created at https://github.com/Daddyoba12/OTBPipeline
#   - First commit pushed (done by watch_sync.ps1 or manually)
#   - Oracle SSH key at ~/.ssh/oracle_boothop.pem

param(
    [string]$OracleIP   = "140.238.73.32",
    [string]$KeyFile    = "$env:USERPROFILE\.ssh\oracle_boothop.pem",
    [string]$OracleUser = "ubuntu",
    [string]$RemotePath = "/opt/otb_pipeline",
    [string]$GitHubRepo = "https://github.com/Daddyoba12/OTBPipeline.git"
)

$SSH = "ssh -i `"$KeyFile`" -o StrictHostKeyChecking=no ${OracleUser}@${OracleIP}"

Write-Host "=== OTB_Pipeline Oracle Setup ===" -ForegroundColor Cyan
Write-Host "Oracle: ${OracleUser}@${OracleIP}:${RemotePath}"
Write-Host ""

function Run-Oracle {
    param([string]$Cmd)
    Write-Host "[Oracle] $Cmd" -ForegroundColor Yellow
    & ssh -i "$KeyFile" -o StrictHostKeyChecking=no "${OracleUser}@${OracleIP}" $Cmd
}

# 1. Clone or update repo
Write-Host "Step 1: Clone repo..." -ForegroundColor Cyan
Run-Oracle "if [ -d '$RemotePath/.git' ]; then cd $RemotePath && git pull origin main; else sudo mkdir -p $RemotePath && sudo chown ubuntu:ubuntu $RemotePath && git clone $GitHubRepo $RemotePath; fi"

# 2. Install dependencies
Write-Host ""
Write-Host "Step 2: Install Python packages..." -ForegroundColor Cyan
Run-Oracle "pip3 install anthropic requests python-telegram-bot yt-dlp pillow google-auth google-auth-oauthlib google-api-python-client 2>&1 | tail -5"

# 3. Create data directory
Write-Host ""
Write-Host "Step 3: Create data dir..." -ForegroundColor Cyan
Run-Oracle "mkdir -p $RemotePath/data $RemotePath/output $RemotePath/temp $RemotePath/music/daily $RemotePath/music/archive"

# 4. Install Commander systemd service
Write-Host ""
Write-Host "Step 4: Set up Telegram Commander service..." -ForegroundColor Cyan
$serviceContent = @"
[Unit]
Description=OTB Pipeline Telegram Commander
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$RemotePath
ExecStart=/usr/bin/python3 $RemotePath/scripts/telegram_commander.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"@
Run-Oracle "echo '$serviceContent' | sudo tee /etc/systemd/system/otb-commander.service > /dev/null"
Run-Oracle "sudo systemctl daemon-reload && sudo systemctl enable otb-commander && sudo systemctl start otb-commander"

# 5. Set up auto-pull cron (Oracle pulls from GitHub every 5 minutes — bidirectional sync)
Write-Host ""
Write-Host "Step 5: Set up auto-pull cron (every 5 min)..." -ForegroundColor Cyan
$cronLine = "*/5 * * * * cd $RemotePath && git pull origin main >> /var/log/otb_sync.log 2>&1"
Run-Oracle "(crontab -l 2>/dev/null | grep -v otb_pipeline; echo '$cronLine') | crontab -"

Write-Host ""
Write-Host "=== Oracle setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Bidirectional sync is now active:" -ForegroundColor Cyan
Write-Host "  Laptop -> Oracle:  watch_sync.ps1 (auto on file save)" -ForegroundColor White
Write-Host "  Oracle -> Laptop:  Oracle cron pulls GitHub every 5 min, you run sync_data.ps1 for data" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Run .\RegisterTasks.ps1 as Administrator (adds OTB-MusicRefresh at 6am)"
Write-Host "  2. Run .\deploy\watch_sync.ps1 to start the live watcher"
Write-Host "  3. Check Commander: ssh -i $KeyFile ${OracleUser}@${OracleIP} 'sudo systemctl status otb-commander'"
