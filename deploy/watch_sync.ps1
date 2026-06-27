# OTB_Pipeline — Auto-sync watcher
# Watches the project folder. On every .py/.ps1/.json save:
#   1. git commit + push to GitHub
#   2. rsync / scp to Oracle
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
Write-Host "Oracle:   ${OracleUser}@${OracleIP}:$RemotePath" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop."                   -ForegroundColor Gray
Write-Host ""

# ── Git push ──────────────────────────────────────────────────────────────────
function Do-GitPush {
    param([string]$Label = "bulk sync")
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git: staging + push ($Label)..." -ForegroundColor Cyan
    Push-Location $LocalPath
    try {
        git add -A 2>&1 | Out-Null
        $dirty = git status --porcelain
        if ($dirty) {
            $msg = "auto-sync: $Label [$(Get-Date -Format 'yyyy-MM-dd HH:mm')]"
            git commit -m $msg 2>&1 | Out-Null
            git push origin main 2>&1 | Out-Null
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git: pushed OK" -ForegroundColor Green
        } else {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git: nothing to commit" -ForegroundColor Gray
        }
    } catch {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Git error: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

# ── Oracle sync via SCP ───────────────────────────────────────────────────────
function Do-OracleSync {
    param([string]$ChangedFile = "")
    $dest = "${OracleUser}@${OracleIP}:${RemotePath}"
    $scp  = @("-i", $KeyFile, "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes")

    # If we know exactly which file changed, just push that one file
    if ($ChangedFile -and (Test-Path $ChangedFile)) {
        $rel = $ChangedFile.Substring($LocalPath.Length).TrimStart("\").Replace("\", "/")
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: pushing $rel..." -ForegroundColor Cyan
        & scp @scp "$ChangedFile" "${dest}/${rel}" 2>&1 | Out-Null
    } else {
        # Full sync of code folders (no large output/temp/music)
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: full sync..." -ForegroundColor Cyan
        & scp @scp "$LocalPath\pipeline.py"  "${dest}/pipeline.py"  2>&1 | Out-Null
        & scp @scp "$LocalPath\config.py"    "${dest}/config.py"    2>&1 | Out-Null
        & scp @scp -r "$LocalPath\scripts"   "${dest}/scripts"      2>&1 | Out-Null
        & scp @scp -r "$LocalPath\deploy"    "${dest}/deploy"       2>&1 | Out-Null
    }

    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: done" -ForegroundColor Green

    # Restart commander if a core file changed
    if ($ChangedFile -match "telegram_commander|pipeline\.py|config\.py") {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Oracle: restarting commander..." -ForegroundColor Magenta
        & ssh -i "$KeyFile" -o StrictHostKeyChecking=no "${OracleUser}@${OracleIP}" `
            "sudo systemctl restart otb-commander 2>/dev/null || true"
    }
    Write-Host ""
}

# ── Initial sync on start ─────────────────────────────────────────────────────
Do-GitPush  -Label "initial"
Do-OracleSync

# ── File system watcher ───────────────────────────────────────────────────────
$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path                  = $LocalPath
$watcher.Filter                = "*.*"
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter          = [System.IO.NotifyFilters]::LastWrite

$script:lastSync = [datetime]::MinValue
$script:lastFile = ""
$debounce = 4

$onChange = {
    $path = $Event.SourceEventArgs.FullPath
    if ($path -match "(__pycache__|\.pyc|\.git|output[\\/]|temp[\\/]|music[\\/]daily|~$|\.tmp$)") { return }
    if ($path -match "\.(py|ps1|json|txt|sh|html|service)$") {
        $script:lastFile = $path
        $script:lastSync = [datetime]::Now
    }
}

Register-ObjectEvent $watcher Changed -Action $onChange | Out-Null
Register-ObjectEvent $watcher Created -Action $onChange | Out-Null
$watcher.EnableRaisingEvents = $true

Write-Host "Watching .py .ps1 .json .txt .sh .html files..." -ForegroundColor Gray
Write-Host ""

# ── Poll loop ─────────────────────────────────────────────────────────────────
try {
    while ($true) {
        Start-Sleep -Seconds 1
        if ($script:lastSync -ne [datetime]::MinValue) {
            $elapsed = ([datetime]::Now - $script:lastSync).TotalSeconds
            if ($elapsed -ge $debounce) {
                $fileToSync          = $script:lastFile
                $script:lastSync     = [datetime]::MinValue
                $script:lastFile     = ""
                $label = Split-Path $fileToSync -Leaf -ErrorAction SilentlyContinue
                if (-not $label) { $label = "file change" }
                Do-GitPush    -Label $label
                Do-OracleSync -ChangedFile $fileToSync
            }
        }
    }
} finally {
    $watcher.EnableRaisingEvents = $false
    $watcher.Dispose()
    Write-Host "Watcher stopped." -ForegroundColor Gray
}
