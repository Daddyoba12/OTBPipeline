@echo off
cd /d "C:\Users\babso\Desktop\OTB_Pipeline"
python scripts\seo_weekly_report.py >> logs\seo_weekly.log 2>&1
