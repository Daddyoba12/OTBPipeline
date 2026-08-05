#!/bin/bash
# Oracle backup crontab
# BootHop: laptop primary at 08:00/14:00/21:00 UK BST (07:00/13:00/20:00 UTC), Oracle 1h later
# G-Inspired: laptop primary at 09:00/13:00/18:00 Chicago CDT (14:00/18:00/23:00 UTC), Oracle 1h later
# Slot 4 (LinkedIn+Blog) runs Tue+Fri for both clients
cat > /tmp/newcron << 'CRON'
# BootHop backup — fires 1h after laptop primary
0 8 * * * cd /opt/otb_pipeline && python3 pipeline.py --slot 1 >> /home/ubuntu/otb_pipeline.log 2>&1
0 14 * * * cd /opt/otb_pipeline && python3 pipeline.py --slot 2 >> /home/ubuntu/otb_pipeline.log 2>&1
0 21 * * * cd /opt/otb_pipeline && python3 pipeline.py --slot 3 >> /home/ubuntu/otb_pipeline.log 2>&1
0 8 * * 2,5 cd /opt/otb_pipeline && python3 pipeline.py --slot 4 >> /home/ubuntu/otb_pipeline.log 2>&1
# G-Inspired backup — fires 1h after laptop primary (CDT times)
0 15 * * * cd /opt/otb_pipeline && OTB_CLIENT_BASE=/opt/g_inspired python3 pipeline_g_inspired.py --slot 1 >> /home/ubuntu/g_inspired.log 2>&1
0 19 * * * cd /opt/otb_pipeline && OTB_CLIENT_BASE=/opt/g_inspired python3 pipeline_g_inspired.py --slot 1 >> /home/ubuntu/g_inspired.log 2>&1
0 10 * * 2,5 cd /opt/otb_pipeline && OTB_CLIENT_BASE=/opt/g_inspired python3 pipeline_g_inspired.py --slot 4 >> /home/ubuntu/g_inspired.log 2>&1
# Engagement bot — reply to comments every 2h
0 */2 * * * cd /opt/otb_pipeline && python3 scripts/engage.py >> /home/ubuntu/engage.log 2>&1
# TikTok analytics sync — daily at 09:00 UTC
0 9 * * * cd /opt/otb_pipeline && python3 scripts/sync_tiktok_analytics.py >> /home/ubuntu/tiktok_analytics.log 2>&1
CRON
crontab /tmp/newcron
echo "Crontab installed:"
crontab -l
