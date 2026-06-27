# OTB_Pipeline — Auto-sync watcher
# Watches the project folder. On every .py/.ps1/.json save:
#   1. git commit + push to GitHub  (so history is preserved)
#   2. rsync / scp to Oracle        (so Oracle runs the latest code immediately)
#
# Usage:  .\deploy\watch_sync.ps1
# Stop:   Ctrl+C

param(
    [string]$OracleIP    = "140.238.73.32",
    [string]$KeyFile     = "$env:USERPROFILE\.ssh\oracle_boothop.pem",
    [string]$OracleUser  = "ubuntu",
    [string]$RemotePath  = "/opt/otb_pipeline"
)

$LocalPath = Split-Path $PSScriptRoot -Parent

Write-Host "=== OTB_Pipeline Auto-Sync Watcher ===" -ForegroundColor Cyan
Write-Host "Watching: $LocalPath"                    -ForegroundColor Yellow
Write-Host "GitHub:   auto-commit + push on change"  -ForegroundColor Yellow
Write-Host "Oracle:   $OracleUser@${OracleIP}:$RemotePath" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop."                   -ForegroundColor Gray
Write-Host ""

function Git-PushChanges {
    param([string]$ChangedFile = "")
    $label = if ($ChangedFile) { Split-Path $ChangedFile -Leaf } else { "bulk sync" }
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git: staging + push ($label)..." -ForegroundColor Cyan
    Push-Location $LocalPath
    try {
        git add -A 2>&1 | Out-Null
        $status = git status --porcelain
        if ($status) {
            git commit -m "auto-sync: $label [$(Get-Date -Format 'yyyy-MM-dd HH:mm')]" 2>&1 | Out-Null
            git push origin main 2>&1 | Out-Null
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git: pushed OK" -ForegroundColor Green
        } else {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git: no changes to commit" -ForegroundColor Gray
        }
    } catch {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git: push error — $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

function Sync-ToOracle {
    param([string]$ChangedFile = "")
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: syncing..." -ForegroundColor Cyan

    $WslAvail = $null -ne (Get-Command wsl -ErrorAction SilentlyContinue)
    if ($WslAvail) {
        $WslLocal = (wsl wslpath -u "$LocalPath").Trim()
        $WslKey   = (wsl wslpath -u "$KeyFile").Trim()
        $cmd = "rsync -az --delete " +
               "--exclude='.git' --exclude='__pycache__' --exclude='*.pyc' " +
               "--exclude='output/' --exclude='temp/' --exclude='music/daily/' " +
               "--exclude='data/pipeline_crash.log' --exclude='data/pipeline_step.txt' " +
               "-e 'ssh -i $WslKey -o StrictHostKeyChecking=no' " +
               "${WslLocal}/ ${OracleUser}@${OracleIP}:${RemotePath}/"
        wsl bash -c $cmd
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: rsync done" -ForegroundColor Green
    } else {
        # SCP fallback — copy key scripts
        $files = @("pipeline.py", "config.py")
        foreach ($f in $files) {
            $fp = Join-Path $LocalPath $f
            if (Test-Path $fp) {
                & scp -i "$KeyFile" -o StrictHostKeyChecking=no "$fp" "${OracleUser}@${OracleIP}:${RemotePath}/$f" 2>&1
            }
        }
        & scp -r -i "$KeyFile" -o StrictHostKeyChecking=no "$LocalPath\scripts" "${OracleUser}@${OracleIP}:${RemotePath}/" 2>&1
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: scp done" -ForegroundColor Green
    }

    # Restart commander if pipeline/config/commander changed
    if ($ChangedFile -match "telegram_commander|pipeline\.py|config\.py") {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: restarting otb-commander..." -ForegroundColor Magenta
        & ssh -i "$KeyFile" -o StrictHostKeyChecking=no "${OracleUser}@${OracleIP}" "sudo systemctl restart otb-commander 2>/dev/null || true"
    }
    Write-Host ""
}

function Sync-Now {
    param([string]$ChangedFile = "")
    Git-PushChanges -ChangedFile $ChangedFile
    Sync-ToOracle   -ChangedFile $ChangedFile
}

# Initial sync on start
Sync-Now

# File system watcher
$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path                 = $LocalPath
$watcher.Filter               = "*.*"
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter         = [System.IO.NotifyFilters]::LastWrite

$lastSync = [datetime]::MinValue
$lastFile = ""
$debounce = 4   # seconds — wait for burst of saves to settle

$onChange = {
    $path = $Event.SourceEventArgs.FullPath
    if ($path -match "(__pycache__|\.pyc|\.git|output[\\/]|temp[\\/]|music[\\/]daily|~$|\.tmp$)") { return }
    if ($path -match "\.(py|ps1|json|txt|sh|html|service|env)$") {
        $script:lastFile = $path
        $script:lastSync = [datetime]::Now
    }
}

Register-ObjectEvent $watcher Changed -Action $onChange | Out-Null
Register-ObjectEvent $watcher Created -Action $onChange | Out-Null
$watcher.EnableRaisingEvents = $true

Write-Host "Watching .py .ps1 .json .txt .sh .html files for changes..." -ForegroundColor Gray
Write-Host ""

try {
    while ($true) {
        Start-Sleep -Seconds 1
        if ($lastSync -ne [datetime]::MinValue) {
            $elapsed = ([datetime]::Now - $lastSync).TotalSeconds
            if ($elapsed -ge $debounce) {
                $fileToSync = $lastFile
                $lastSync   = [datetime]::MinValue
                $lastFile   = ""
                Sync-Now -ChangedFile $fileToSync
            }
        }
    }
} finally {
    $watcher.EnableRaisingEvents = $false
    $watcher.Dispose()
    Write-Host "Watcher stopped." -ForegroundColor Gray
}
