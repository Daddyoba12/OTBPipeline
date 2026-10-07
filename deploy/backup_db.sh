#!/bin/bash
# backup_db.sh — daily backup of the dashboard's SQLite DB.
# Added 2026-10-07: otb.db had no backup of any kind — a disk failure or a
# bad migration would have silently lost every client's credentials,
# schedule, and bake history. Keeps 14 days of dated copies, prunes older.
# Installed via cron on Oracle (see set_cron.sh) — not meant to be run from
# the laptop, since Oracle is the machine the dashboard actually runs on.

set -euo pipefail

APP_DIR="/opt/otb_pipeline"
DB="$APP_DIR/dashboard/otb.db"
BACKUP_DIR="$APP_DIR/dashboard/backups"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB" ]; then
    echo "[backup_db] $DB not found — nothing to back up"
    exit 0
fi

TS=$(date -u +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/otb_${TS}.db"

# sqlite3 .backup takes a consistent snapshot even if the dashboard is
# mid-write, unlike a plain cp which could copy a half-written page.
sqlite3 "$DB" ".backup '$DEST'"
echo "[backup_db] Backed up to $DEST"

find "$BACKUP_DIR" -name "otb_*.db" -mtime "+${KEEP_DAYS}" -delete
echo "[backup_db] Pruned backups older than ${KEEP_DAYS} days"
