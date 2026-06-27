# OTB_Pipeline — Bidirectional data sync
# Syncs runtime data files between Oracle and laptop WITHOUT touching code.
# Code sync is handled by git (watch_sync.ps1). Data sync is separate because:
#   - post_log.json, query_bank.json — Oracle writes these, laptop needs them
#   - query_log.json, music_log.json — 14-day dedup logs, must stay in sync
#
# Usage:
#   Pull Oracle data to laptop:  .\deploy\sync_data.ps1
#   Push laptop data to Oracle:  .\deploy\sync_data.ps1 -Direction push

param(
    [string]$OracleIP   = "140.238.73.32",
    [string]$KeyFile    = "$env:USERPROFILE\.ssh\oracle_boothop.pem",
    [string]$OracleUser = "ubuntu",
    [string]$Direction  = "pull"
)

$LocalData  = "$PSScriptRoot\..\data"
$RemoteData = "${OracleUser}@${OracleIP}:/opt/otb_pipeline/data"
$BackupDir  = "$PSScriptRoot\..\data\backups"

$DataFiles = @(
    "post_log.json",
    "query_bank.json",
    "query_hits.json",
    "query_log.json",
    "query_refresh.json",
    "music_log.json",
    "daily_info.json",
    "pipeline_ran_today.json"
)

New-Item -ItemType Directory -Force $BackupDir | Out-Null

$ts = Get-Date -Format "yyyyMMdd_HHmmss"

if ($Direction -eq "pull") {
    Write-Host "Pulling data from Oracle -> laptop..." -ForegroundColor Cyan

    foreach ($file in $DataFiles) {
        $local  = Join-Path $LocalData $file
        $remote = "${RemoteData}/$file"
        $backup = Join-Path $BackupDir "${ts}_${file}"

        # Backup local copy first
        if (Test-Path $local) {
            Copy-Item $local $backup -ErrorAction SilentlyContinue
        }

        & scp -i "$KeyFile" -o StrictHostKeyChecking=no "$remote" "$local" 2>&1
        if ($?) {
            Write-Host "  OK  $file" -ForegroundColor Green
        } else {
            Write-Host "  --  $file (not on Oracle yet)" -ForegroundColor Gray
            # Restore backup if scp failed
            if (Test-Path $backup) { Copy-Item $backup $local -ErrorAction SilentlyContinue }
        }
    }

    Write-Host ""
    Write-Host "Pull complete. Backups saved to data/backups/$ts..." -ForegroundColor Gray

} elseif ($Direction -eq "push") {
    Write-Host "Pushing laptop data -> Oracle..." -ForegroundColor Yellow

    foreach ($file in $DataFiles) {
        $local = Join-Path $LocalData $file
        if (-not (Test-Path $local)) {
            Write-Host "  --  $file (not on laptop)" -ForegroundColor Gray
            continue
        }
        $remote = "${RemoteData}/$file"
        & scp -i "$KeyFile" -o StrictHostKeyChecking=no "$local" "$remote" 2>&1
        if ($?) {
            Write-Host "  OK  $file" -ForegroundColor Green
        } else {
            Write-Host "  ERR $file" -ForegroundColor Red
        }
    }

    Write-Host ""
    Write-Host "Push complete." -ForegroundColor Green

} else {
    Write-Host "Unknown direction. Use 'pull' (default) or 'push'." -ForegroundColor Red
}
