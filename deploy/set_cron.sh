#!/bin/bash
# Oracle crontab.
#
# NOTE (2026-09-28): this script is stale relative to what's actually live on
# Oracle and was NOT re-run to produce the current crontab — it's kept here as
# a reference/rebuild script, now corrected. Two things changed from the
# original version:
#
# 1. Primary/backup roles flipped since this was last accurate: Oracle
#    (Linux, always-on) is now PRIMARY, the Windows laptop is BACKUP — see
#    deploy/dispatch_scheduler.py's IS_PRIMARY/HEAD_START logic. The comment
#    below used to say the opposite.
# 2. The hardcoded `pipeline.py --slot N` / `pipeline_g_inspired.py --slot N`
#    lines below were removed. They fired at fixed UTC times that duplicated
#    (and during BST, slightly diverged from) what dispatch_scheduler.py
#    already does correctly via each client's client_profile.json schedule
#    (timezone-aware, with proper primary/backup windowing). Keeping both
#    meant BootHop could attempt to run twice around the same time every day
#    — harmless in practice only because pipeline.py's own lock/already-ran
#    checks silently absorbed the duplicate, but wasteful and confusing.
#    dispatch_scheduler.py is now the single source of truth for client
#    scheduling; if a client's times need to change, edit its
#    client_profile.json, not this file.
cat > /tmp/newcron << 'CRON'
# Music refresh at 06:00 UTC — Oracle uses archive only (30-day gap enforced).
# Laptop slot 1 is the sole SoundCloud downloader; Oracle just draws from local archive.
0 6 * * * cd /opt/otb_pipeline && python3 scripts/fetch_trending_music.py --skip-if-fresh --archive-only >> /home/ubuntu/music_refresh.log 2>&1
# Engagement bot — reply to comments every 2h
0 */2 * * * cd /opt/otb_pipeline && python3 scripts/engage.py >> /home/ubuntu/engage.log 2>&1
# TikTok analytics sync — daily at 09:00 UTC
0 9 * * * cd /opt/otb_pipeline && python3 scripts/sync_tiktok_analytics.py >> /home/ubuntu/tiktok_analytics.log 2>&1
# Weekly performance review — Mondays 05:30 UTC
30 5 * * 1 cd /opt/otb_pipeline && python3 scripts/weekly_review.py >> /home/ubuntu/weekly_run.log 2>&1
# Follower count tracker — daily 09:00 UTC
0 9 * * * cd /opt/otb_pipeline && python3 scripts/follower_tracker.py >> /home/ubuntu/follower.log 2>&1
# Weekly SEO report — Mondays 08:05 UTC
5 8 * * 1 cd /opt/otb_pipeline && python3 scripts/seo_weekly_report.py >> /home/ubuntu/seo_weekly.log 2>&1
# Split into 3 independent per-client dispatcher runs — a hang in one
# client's pipeline used to block the others since they shared one
# sequential process. Each client has its own lock file, so these can
# never block each other now.
*/10 * * * * cd /opt/otb_pipeline && python3 deploy/dispatch_scheduler.py --client boothop    >> /home/ubuntu/dispatch_scheduler.log 2>&1
*/10 * * * * cd /opt/otb_pipeline && python3 deploy/dispatch_scheduler.py --client g_inspired >> /home/ubuntu/dispatch_scheduler.log 2>&1
*/10 * * * * cd /opt/otb_pipeline && python3 deploy/dispatch_scheduler.py --client d818       >> /home/ubuntu/dispatch_scheduler.log 2>&1
CRON
crontab /tmp/newcron
echo "Crontab installed:"
crontab -l
