# OTB Pipeline — Full Architecture
*Last updated: June 2026*

---

## Overview

OTB Pipeline is a fully automated video content production and posting system built for BootHop. It runs 24/7 on an Oracle Cloud server, controlled via Telegram, and exposes a multi-tenant client portal through the BootHop website.

---

## Infrastructure

| Component | Where it runs |
|---|---|
| Oracle Cloud VM | `140.238.73.32` — Ubuntu 22.04, 1 OCPU, 6 GB RAM |
| BootHop Website | Vercel (Next.js) — `www.boothop.com` |
| GitHub (pipeline) | `github.com/Daddyoba12/OTBPipeline` |
| GitHub (website) | `github.com/Daddyoba12/boothop` |

---

## System Map

```
┌─────────────────────────────────────────────────────────┐
│                    Oracle Cloud VM                       │
│                   140.238.73.32                          │
│                                                          │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │  pipeline.py  │   │  telegram_   │   │  dashboard/ │  │
│  │  (cron/daily) │   │ commander.py │   │  main.py    │  │
│  │               │   │  (always on) │   │  port 1030  │  │
│  └──────┬────────┘   └──────┬───────┘   └──────┬──────┘  │
│         │                   │                   │         │
│         └───── OUTPUT/ ─────┘                   │         │
│                (mp4 + json)                      │         │
│                                                  │         │
│  ┌───────────────────────────────────────────────┤         │
│  │  nginx (port 80) → proxy → port 1030          │         │
│  └───────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────┘
           ↑ HTTP (port 80, OCI open)
┌──────────────────────┐
│  Vercel (Next.js)    │  rewrites:
│  www.boothop.com     │  /onboard           → Oracle /onboard
│                      │  /client-onboarding → Oracle /client-onboarding
│                      │  /onboard/admin/*   → Oracle /admin/*
└──────────────────────┘
```

---

## Processes on Oracle

Three permanent processes run side by side:

| Process | Path | PID file | Purpose |
|---|---|---|---|
| OTB Commander | `/opt/otb_pipeline/scripts/telegram_commander.py` | — | Telegram control panel for OTB pipeline |
| OTB Dashboard | `/opt/otb_pipeline/dashboard/main.py` | systemd | Client portal + admin (FastAPI on port 1030) |
| BHP Commander | `/opt/boothop/scripts/telegram_commander.py` | — | Original BootHop pipeline Telegram bot |

Both pipelines coexist. OTB and BHP share the same Oracle VM but have separate directories, bots, and databases.

---

## Pipeline Flow (Daily)

```
[Cron / manual trigger]
        │
        ▼
  pipeline.py
        │
        ├─ Generates content (hook / lesson / pillar / caption)
        ├─ Renders video slots S2, S3, S4 using FFmpeg + Pexels/Pixabay footage
        ├─ Saves: OUTPUT/otb_slot{N}_{timestamp}.mp4
        │         OUTPUT/otb_slot{N}_{timestamp}.json  ← sidecar (script text)
        │
        ├─ Sends preview to Telegram with [Post Now | Skip | Re-voice] buttons
        │
        └─ On approval → post_tiktok.py / post_instagram.py
```

---

## Revoice Studio Flow

```
Telegram: user taps [Re-voice S2]
        │
        ▼
commander.py shows script from sidecar JSON
        │
        ▼
User sends voice note to Telegram bot
        │
        ▼
commander.py saves voice file, prompts for music pick
        │
        ▼
User picks music track (or searches YouTube)
        │
        ▼
FFmpeg bake:
  strip audio from video
  mix voice note + music (music at 0.18 vol, fade-out)
  mux back → OUTPUT/otb_slot{N}_{timestamp}_revoiced.mp4
        │
        ▼
Preview sent to Telegram → [Post TikTok | Post Instagram | Discard]
        │
        ▼
post_tiktok.py / post_instagram.py
```

---

## Dashboard (Client Portal)

**Tech stack:** FastAPI + Jinja2 templates + SQLite (`dashboard/otb.db`)

### Routes

| Route | Access | Description |
|---|---|---|
| `GET /onboard` | Public | Client self-registration form |
| `POST /onboard` | Public | Creates company in DB |
| `GET /client-onboarding` | Public | 5-step setup wizard |
| `GET /login` | Public | Client login |
| `POST /login` | Public | Validates password, sets session cookie |
| `GET /dashboard` | Client | Revoice Studio + bake history |
| `GET /admin/login` | Admin | Admin login |
| `POST /admin/login` | Admin | Validates `ADMIN_PASSWORD`, 24h session |
| `GET /admin` | Admin | All companies overview |
| `POST /admin/add-company` | Admin | Manually create client |
| `POST /admin/delete-company/{id}` | Admin | Deactivate client |
| `POST /api/bake` | Client | Submit bake job (background FFmpeg) |
| `POST /api/youtube-music` | Client | Download YouTube audio via yt-dlp |

### Database schema (SQLite)

```sql
companies (id, slug, name, email, contact, plan, password_h, api_key, tg_chat_id, whatsapp, active, created_at)
sessions  (id, token, company_id, is_admin, expires_at)
bakes     (id, company_id, slot, video_path, voice_path, music_path, output_path, status, created_at)
```

---

## Networking

| Port | Open where | Used for |
|---|---|---|
| 22 | OCI + iptables | SSH |
| 80 | OCI + iptables | nginx → dashboard proxy |
| 443 | OCI + iptables | SSL (commander.boothop.com via Certbot) |
| 1030 | iptables only | Dashboard (internal, nginx proxies to it) |

OCI Security List controls cloud-level firewall. Ubuntu iptables is a second layer.
Port 1030 is intentionally not exposed externally — all external traffic goes through nginx on port 80.

---

## Vercel Rewrites (next.config.ts)

Vercel acts as a reverse proxy for the Oracle dashboard. Rewrites are server-side (invisible to the browser URL bar).

```
/onboard            → http://140.238.73.32/onboard
/client-onboarding  → http://140.238.73.32/client-onboarding
/onboard/admin/*    → http://140.238.73.32/admin/*
/pipeline/commander/* → http://140.238.73.32/* (legacy)
```

`boothop.com/admin/*` is NOT proxied — it serves the original Next.js boothop admin pages directly.

---

## nginx Config (Oracle)

File: `/etc/nginx/sites-enabled/otb-dashboard`

```nginx
server {
    listen 80 default_server;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:1030;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120;
    }
}
```

`commander.boothop.com` is served by a separate nginx site (`sites-enabled/commander`) on port 443 with a Let's Encrypt cert.

---

## Systemd Services

| Service | File | Auto-restart |
|---|---|---|
| `otb-dashboard` | `/etc/systemd/system/otb-dashboard.service` | Yes (RestartSec=10) |

Commander runs as a standalone Python process (not systemd). A watchdog script (`ensure_commander.py`) relaunches it if it dies.

### Key environment variables in `otb-dashboard.service`

```ini
Environment=PORT=1030
Environment=PIPELINE_ROOT=/opt/otb_pipeline
Environment=TELEGRAM_TOKEN=...
Environment=ADMIN_PASSWORD=...
Environment=ADMIN_PREFIX=/onboard/admin
```

---

## File Layout (Oracle)

```
/opt/otb_pipeline/
├── pipeline.py                  ← main daily pipeline
├── config.py                    ← API keys, constants
├── post_tiktok.py
├── post_instagram.py
├── OUTPUT/                      ← rendered videos + sidecar JSON
│   ├── otb_slot2_20260628.mp4
│   ├── otb_slot2_20260628.json
│   └── ...
├── music/
│   ├── daily/                   ← today's music pool
│   ├── archive/
│   └── yt_downloads/            ← YouTube audio downloads
├── data/
│   └── revoice_studio.json      ← Revoice Studio state (1h expiry)
├── scripts/
│   └── telegram_commander.py    ← Telegram bot (always running)
└── dashboard/
    ├── main.py                  ← FastAPI server
    ├── otb.db                   ← SQLite database
    ├── companies/               ← per-client directories
    └── templates/               ← Jinja2 HTML templates
        ├── onboard.html
        ├── client_onboarding.html
        ├── admin.html
        ├── admin_login.html
        ├── admin_company.html
        ├── login.html
        ├── dashboard.html
        └── landing.html
```

---

## Deployment

### Deploy dashboard changes to Oracle
```bash
cd /opt/otb_pipeline
git pull origin main
sudo systemctl restart otb-dashboard
```

### Deploy website changes (Vercel)
```bash
cd /path/to/boothop
git add . && git commit -m "..."
git push origin main   # Vercel auto-deploys on push
```

### Full redeploy script (from laptop)
```
PowerShell: deploy\deploy_dashboard_oracle.ps1
```

---

## Key Credentials

| Secret | Location |
|---|---|
| Oracle SSH key | `C:\Users\babso\.ssh\oracle_boothop.pem` |
| Admin password | `ADMIN_PASSWORD` env var on Oracle |
| Telegram token | `TELEGRAM_TOKEN` env var / `config.py` |
| Vercel | Auto-deploy from GitHub push |

---

*OTB Pipeline Architecture — v1.0 — June 2026*
