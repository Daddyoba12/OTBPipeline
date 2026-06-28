# deploy_dashboard_oracle.ps1
# Deploys OTB Dashboard to Oracle as a systemd service on port 1031.
# Run once from laptop (as Administrator not required).

param(
    [string]$OracleIP   = "140.238.73.32",
    [string]$OracleUser = "ubuntu",
    [string]$BasePath   = "/opt/otb_pipeline"
)

$TgToken       = "8717698733:AAF7GI9Yw1DhdYVv_TK35fYQcwaGdk4caeA"
$AdminPassword = "otb-admin-2026"

Write-Host ""
Write-Host "OTB Dashboard — Deploying to Oracle ($OracleIP)" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan

# ── 1. Install Python packages ─────────────────────────────────────────────────
Write-Host "[1/5] Installing Python packages on Oracle..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" @"
pip3 install fastapi uvicorn "python-multipart" jinja2 --quiet --break-system-packages 2>/dev/null || \
pip3 install fastapi uvicorn python-multipart jinja2 --quiet
echo "  Packages: OK"
"@

# ── 2. Create required directories ────────────────────────────────────────────
Write-Host "[2/5] Creating directories..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" @"
mkdir -p ${BasePath}/music/daily
mkdir -p ${BasePath}/music/archive
mkdir -p ${BasePath}/music/yt_downloads
mkdir -p ${BasePath}/dashboard/companies
mkdir -p ${BasePath}/dashboard/clients
echo "  Directories: OK"
"@

# ── 3. Write systemd service file ─────────────────────────────────────────────
Write-Host "[3/5] Writing systemd service..." -ForegroundColor Yellow

$ServiceContent = @"
[Unit]
Description=OTB Pipeline Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=${BasePath}/dashboard
ExecStart=/usr/bin/python3 ${BasePath}/dashboard/main.py
Restart=always
RestartSec=10
Environment=PORT=1031
Environment=PIPELINE_ROOT=${BasePath}
Environment=TELEGRAM_TOKEN=${TgToken}
Environment=ADMIN_PASSWORD=${AdminPassword}

[Install]
WantedBy=multi-user.target
"@

# Pipe the service content directly to tee on Oracle
$ServiceContent | ssh "${OracleUser}@${OracleIP}" "sudo tee /etc/systemd/system/otb-dashboard.service > /dev/null && echo '  Service file: OK'"

# ── 4. Enable + start the service ─────────────────────────────────────────────
Write-Host "[4/5] Enabling and starting service..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" @"
sudo systemctl daemon-reload
sudo systemctl enable otb-dashboard --quiet
sudo systemctl restart otb-dashboard
sleep 3
sudo systemctl status otb-dashboard --no-pager -l
"@

# ── 5. Open port 1031 in Ubuntu firewall ──────────────────────────────────────
Write-Host "[5/5] Opening port 1031 in Ubuntu firewall..." -ForegroundColor Yellow
ssh "${OracleUser}@${OracleIP}" @"
sudo iptables -I INPUT -p tcp --dport 1031 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 1031 -j ACCEPT -m comment --comment "OTB Dashboard"
# Persist iptables rules
sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null 2>&1 || \
sudo sh -c 'iptables-save > /etc/iptables.rules' 2>/dev/null || true
echo "  Port 1031: OPEN"
"@

# ── Done ───────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Dashboard deployed on Oracle!" -ForegroundColor Green
Write-Host ""
Write-Host "  URL: http://${OracleIP}:1031" -ForegroundColor Cyan
Write-Host "  Admin: http://${OracleIP}:1031/admin/login  (password: $AdminPassword)" -ForegroundColor Cyan
Write-Host "  Onboard: http://${OracleIP}:1031/onboard" -ForegroundColor Cyan
Write-Host "  Wizard:  http://${OracleIP}:1031/client-onboarding" -ForegroundColor Cyan
Write-Host ""
Write-Host "ACTION REQUIRED — Open port 1031 in OCI Console:" -ForegroundColor Yellow
Write-Host "  1. Go to cloud.oracle.com -> Networking -> Virtual Cloud Networks"
Write-Host "  2. Click your VCN -> Security Lists -> Default Security List"
Write-Host "  3. Add Ingress Rule:"
Write-Host "       Source CIDR : 0.0.0.0/0"
Write-Host "       Protocol    : TCP"
Write-Host "       Dest Port   : 1031"
Write-Host "  4. Save. Dashboard will be live at http://${OracleIP}:1031"
Write-Host ""
