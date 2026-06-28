# deploy_dashboard_oracle.ps1
# Deploys OTB Dashboard to Oracle as a systemd service on port 8080.
# Run once from laptop.

param(
    [string]$OracleIP   = "140.238.73.32",
    [string]$OracleUser = "ubuntu",
    [string]$BasePath   = "/opt/otb_pipeline"
)

$TgToken       = "8717698733:AAF7GI9Yw1DhdYVv_TK35fYQcwaGdk4caeA"
$AdminPassword = "otb-admin-2026"

Write-Host ""
Write-Host "OTB Dashboard -- Deploying to Oracle ($OracleIP)" -ForegroundColor Cyan

# 1. Pull latest code
Write-Host "[1/5] Pulling latest code on Oracle..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" "cd $BasePath && git pull origin main 2>&1 | tail -3"

# 2. Install Python packages
Write-Host "[2/5] Installing Python packages..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" "pip3 install fastapi uvicorn python-multipart jinja2 --quiet --break-system-packages 2>/dev/null || pip3 install fastapi uvicorn python-multipart jinja2 --quiet && echo 'Packages OK'"

# 3. Create directories
Write-Host "[3/5] Creating directories..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" "mkdir -p $BasePath/music/daily $BasePath/music/archive $BasePath/music/yt_downloads $BasePath/dashboard/companies $BasePath/dashboard/clients && echo 'Dirs OK'"

# 4. Write systemd service file
Write-Host "[4/5] Writing systemd service..." -ForegroundColor Yellow

$svc = @'
[Unit]
Description=OTB Pipeline Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=BASEPATH/dashboard
ExecStart=/usr/bin/python3 BASEPATH/dashboard/main.py
Restart=always
RestartSec=10
Environment=PORT=8080
Environment=PIPELINE_ROOT=BASEPATH
Environment=TELEGRAM_TOKEN=TGTOKEN
Environment=ADMIN_PASSWORD=ADMINPW

[Install]
WantedBy=multi-user.target
'@

$svc = $svc.Replace("BASEPATH", $BasePath).Replace("TGTOKEN", $TgToken).Replace("ADMINPW", $AdminPassword)
$svc | ssh "${OracleUser}@${OracleIP}" "sudo tee /etc/systemd/system/otb-dashboard.service > /dev/null && echo 'Service file written'"

# 5. Enable, start, open firewall
Write-Host "[5/5] Starting service and opening port 8080..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" "sudo systemctl daemon-reload && sudo systemctl enable otb-dashboard --quiet && sudo systemctl restart otb-dashboard && sudo iptables -I INPUT -p tcp --dport 8080 -j ACCEPT && sleep 3 && sudo systemctl status otb-dashboard --no-pager -l"

Write-Host ""
Write-Host "Done! Dashboard deployed on Oracle." -ForegroundColor Green
Write-Host "  Onboard  : http://${OracleIP}:8080/onboard" -ForegroundColor Cyan
Write-Host "  Wizard   : http://${OracleIP}:8080/client-onboarding" -ForegroundColor Cyan
Write-Host "  Admin    : http://${OracleIP}:8080/admin/login   (pw: $AdminPassword)" -ForegroundColor Cyan
Write-Host ""
