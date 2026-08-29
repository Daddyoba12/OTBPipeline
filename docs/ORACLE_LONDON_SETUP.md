# BootHop Oracle Cloud — London Server Setup Guide
**Created:** 28 August 2026  
**Server:** Oracle Cloud Paid — UK South (London)

---

## Server Details

| Detail | Value |
|--------|-------|
| **IP Address** | `130.162.162.189` |
| **Region** | UK South (London) — `uk-london-1` |
| **Shape** | VM.Standard.E4.Flex |
| **OCPUs** | 2 |
| **RAM** | 16 GB |
| **Storage** | 100 GB boot volume |
| **OS** | Ubuntu 22.04 LTS |
| **SSH User** | `ubuntu` |
| **SSH Key** | `C:\Users\babso\.ssh\oracle_boothop.pem` |
| **Pipeline path** | `/opt/otb_pipeline` |
| **OCI Tenancy** | `ocid1.tenancy.oc1..aaaaaaaa54p7paurj65vwwyplktcovw5vqcj44pbgubygssjsfopfct6khwa` |

---

## How to SSH In

```bash
ssh -i C:\Users\babso\.ssh\oracle_boothop.pem ubuntu@130.162.162.189
```

---

## What's Running on the Server

### Telegram Commander (always-on)
Runs as a **systemd service** — survives reboots automatically.

```bash
# Check status
sudo systemctl status otb-commander

# Restart (after code update)
sudo systemctl restart otb-commander

# Live logs
sudo journalctl -u otb-commander -f
```

### Cron Schedule (UTC times)

| UTC Time | Job |
|----------|-----|
| 08:00 daily | Pipeline Slot 1 (TikTok + IG + YouTube + Newspaper) |
| 14:00 daily | Pipeline Slot 2 (TikTok + IG + YouTube) |
| 21:00 daily | Pipeline Slot 3 (TikTok + IG + YouTube) |
| 08:00 Tue+Fri | Pipeline Slot 4 (LinkedIn + Blog) |
| Every 2 hours | Engagement bot (comment replies) |
| Mon 05:30 | Weekly review + pillar weights |
| Mon 08:05 | SEO weekly report (PageSpeed + sitemap) |
| 09:00 daily | Follower tracker (IG + TikTok snapshots) |

View cron jobs: `crontab -l`  
View pipeline log: `tail -f /home/ubuntu/otb_pipeline.log`

---

## Files on the Server

| File | Purpose |
|------|---------|
| `/opt/otb_pipeline/keys.env` | All API keys (Anthropic, OpenAI, etc.) |
| `/opt/otb_pipeline/scripts/social_credentials.json` | TikTok, IG, YouTube tokens |
| `/opt/otb_pipeline/scripts/youtube_token.json` | YouTube OAuth token |
| `/opt/otb_pipeline/client_profile.json` | BootHop client config |
| `/home/ubuntu/otb_pipeline.log` | Pipeline run log |
| `/home/ubuntu/engage.log` | Engagement bot log |
| `/home/ubuntu/weekly_run.log` | Weekly review log |
| `/home/ubuntu/seo_weekly.log` | SEO report log |

---

## Updating Code on Oracle

Code auto-updates via GitHub on every pipeline run. After pushing from laptop:

```bash
# Manual pull (if needed immediately)
ssh -i C:\Users\babso\.ssh\oracle_boothop.pem ubuntu@130.162.162.189 "cd /opt/otb_pipeline && git pull && sudo systemctl restart otb-commander"
```

---

## Updating Credentials

When a social media token expires, update on laptop then copy to Oracle:

```bash
# Copy updated social credentials
scp -i C:\Users\babso\.ssh\oracle_boothop.pem scripts/social_credentials.json ubuntu@130.162.162.189:/opt/otb_pipeline/scripts/social_credentials.json

# Copy updated keys
scp -i C:\Users\babso\.ssh\oracle_boothop.pem keys.env ubuntu@130.162.162.189:/opt/otb_pipeline/keys.env
```

---

## Emergency Manual Run

```bash
ssh -i C:\Users\babso\.ssh\oracle_boothop.pem ubuntu@130.162.162.189
cd /opt/otb_pipeline
python3 pipeline.py --slot 1 --force
```

---

## Troubleshooting

### Pipeline not running
```bash
tail -50 /home/ubuntu/otb_pipeline.log
crontab -l
python3 /opt/otb_pipeline/pipeline.py --slot 1 --force
```

### Commander not responding
```bash
sudo systemctl restart otb-commander
sudo journalctl -u otb-commander -n 30
```

### Disk space
```bash
df -h /opt
find /opt/otb_pipeline/output -name "*.mp4" -mtime +30 -delete
```

---

## OCI Console Access

- **Console:** cloud.oracle.com
- **Tenancy:** `ocid1.tenancy.oc1..aaaaaaaa54p7paurj65vwwyplktcovw5vqcj44pbgubygssjsfopfct6khwa`
- **Region:** UK South (London)
- **Instance OCID:** `ocid1.instance.oc1.uk-london-1.anwgiljtrja3d2acox25y3wgnxpvpeu3rojkh4igmclddteyzxpuzoklcztq`

To start/stop the instance: Compute → Instances → boothop-pipeline

---

## What Changed from Old Server

| | Old (Amsterdam) | New (London) |
|-|-----------------|--------------|
| Plan | Free Tier | Paid |
| Region | Netherlands (Amsterdam) | UK South (London) |
| IP | 140.238.73.32 | **130.162.162.189** |
| Shape | VM.Standard.A1.Flex | VM.Standard.E4.Flex |
| Status | Terminated | Running ✅ |
