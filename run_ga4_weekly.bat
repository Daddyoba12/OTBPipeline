@echo off
cd /d "C:\Users\babso\Desktop\OTB_Pipeline"
python scripts\ga4_weekly_report.py >> logs\ga4_weekly.log 2>&1
