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
    "pipeline_ran_today.json",
    "sync_status.json",
    "memory.json",
    "trending_hashtags.json",
    "hashtag_used_log.json",
    "pending_posts.json",
    "video_clip_log.json",
    "user_clip_log.json"
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

        & scp -i "$KeyFile" -o StrictHostKeyChecking=no -o ConnectTimeout=8 "$remote" "$local" 2>&1
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

    # After pull, check if Oracle left any failed posts for the laptop to handle
    $PendingFile = Join-Path $LocalData "pending_posts.json"
    if (Test-Path $PendingFile) {
        $pendingRaw = Get-Content $PendingFile -Raw
        if ($pendingRaw -match '"status":\s*"pending"') {
            Write-Host "[PendingPosts] Oracle has failed posts — laptop taking over..." -ForegroundColor Yellow
            $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
            if (-not $pythonExe) { $pythonExe = "python3" }
            & $pythonExe "$PSScriptRoot\..\scripts\post_pending.py"
            # Push the updated pending_posts.json back to Oracle so it knows it's done
            & scp -i "$KeyFile" -o StrictHostKeyChecking=no -o ConnectTimeout=8 "$PendingFile" "${OracleUser}@${OracleIP}:/opt/otb_pipeline/data/pending_posts.json" 2>&1 | Out-Null
            Write-Host "[PendingPosts] Result synced back to Oracle." -ForegroundColor Green
        }
    }

} elseif ($Direction -eq "push") {
    Write-Host "Pushing laptop data -> Oracle..." -ForegroundColor Yellow

    foreach ($file in $DataFiles) {
        $local = Join-Path $LocalData $file
        if (-not (Test-Path $local)) {
            Write-Host "  --  $file (not on laptop)" -ForegroundColor Gray
            continue
        }
        $remote = "${RemoteData}/$file"
        & scp -i "$KeyFile" -o StrictHostKeyChecking=no -o ConnectTimeout=8 "$local" "$remote" 2>&1
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
