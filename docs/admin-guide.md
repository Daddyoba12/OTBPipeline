# Admin Guide
**BootHop Pipeline — Full Admin Reference**
*Updated June 2026*

---

## Where Everything Lives

| System | URL / Location | Auth |
|---|---|---|
| **Commander** (client music portal) | `www.boothop.com/commander` | Company ID + password (Supabase) |
| **Oracle Admin** (revoice + bake history) | `www.boothop.com/onboard/admin` | `ADMIN_PASSWORD` env var |
| **Supabase** (Commander database) | `zwgngbzbdvnrdnanjded.supabase.co` | Service role key |
| **Oracle SQLite** (revoice database) | `/opt/otb_pipeline/dashboard/otb.db` | SSH → sqlite3 |
| **BootHop Admin** (delivery marketplace) | `www.boothop.com/admin` | `ADMIN_SECRET` |

---

## Setting Up a New Client (Full Process)

A new client needs to be set up in **two places**: Oracle (Revoice Studio) and Commander (music management). Both are needed for a fully working pipeline account.

---

### Part A — Oracle (Revoice Studio + Pipeline Config)

New clients complete **two separate registrations**:

#### 1. Client fills in the onboarding wizard (pipeline config):
Send them to `www.boothop.com/client-onboarding` — the client fills this in themselves.
They work through 5 steps: business info, content strategy, platforms + their social credentials, notifications.
At Step 5 they click **Save & Register Client** — this POSTs to Oracle and saves:
- `clients/{slug}/pipeline_profile.json`
- `clients/{slug}/config.env`
They also download `config.env` locally for running `OTBCommander.exe`.

#### 2. Client self-registers their Revoice Studio login:
Send them to `www.boothop.com/onboard` — they enter their company name, email, and choose a password.
Their Revoice Studio account is created in SQLite (`otb.db`) automatically.
They use this email + password to log in at `www.boothop.com/login`.

#### Or you add their Revoice Studio account manually (Oracle admin):
1. Go to `www.boothop.com/onboard/admin`
2. Log in with the admin password
3. Click **Add Company** and fill in:

| Field | Notes |
|---|---|
| Company Name | Their trading name |
| Contact Name | Primary contact |
| Email | Login email for Revoice Studio |
| Password | Set this for them — give them the password separately |
| WhatsApp | Optional — for pipeline notifications |
| Telegram Chat ID | Optional — for bot messages |
| Plan | `basic` or `priority` |

4. Click **Create** — they can now log in at `www.boothop.com/login`

---

### Part B — Commander Account (Music Management)

Send the client to `www.boothop.com/commander` → **Create Account**.

Or create it yourself:
- Fill in their company name, choose a Company ID slug, their email, and set a password
- Tell the client their **Company ID** and **password** — they use these at `/commander`

Once created, the account appears in Supabase → `pipeline_clients` table.

---

## Viewing All Clients

### Oracle clients (Revoice Studio):
`www.boothop.com/onboard/admin` → shows table of all companies with bake counts and activity.

Or via SSH:
```bash
ssh -i ~/.ssh/oracle_boothop.pem ubuntu@140.238.73.32
sqlite3 /opt/otb_pipeline/dashboard/otb.db
SELECT id, slug, name, email, plan, active, created_at FROM companies;
```

### Commander clients (music / Supabase):
Go to Supabase dashboard → Table Editor → `pipeline_clients`.

### Clients who completed the onboarding wizard:
```bash
ssh -i C:\Users\babso\.ssh\oracle_boothop.pem ubuntu@140.238.73.32
ls /opt/otb_pipeline/dashboard/clients/
```
Each folder is one client. Check their config: `cat /opt/otb_pipeline/dashboard/clients/{slug}/pipeline_profile.json`

---

## Viewing What a Client Has Set Up

### Their music assignments (Supabase):
```sql
-- All tracks assigned to a client
SELECT mt.title, mt.artist, mt.genre, mt.source, mt.youtube_id, cm.assigned_at
FROM client_music cm
JOIN music_tracks mt ON mt.id = cm.track_id
JOIN pipeline_clients pc ON pc.id = cm.client_id
WHERE pc.slug = 'their-company-id'
ORDER BY cm.assigned_at DESC;
```

### Their bake history (Oracle SQLite):
```bash
sqlite3 /opt/otb_pipeline/dashboard/otb.db
SELECT b.id, c.name, b.status, b.created_at FROM bakes b
JOIN companies c ON c.id = b.company_id
WHERE c.slug = 'their-slug'
ORDER BY b.created_at DESC;
```

---

## Managing Music in Supabase

### Add a track to the shared library:
In Supabase → SQL Editor:
```sql
INSERT INTO music_tracks (title, artist, genre, source, youtube_id)
VALUES ('Track Title', 'Artist Name', 'Afrobeats', 'library', NULL);
```

For a YouTube track:
```sql
INSERT INTO music_tracks (title, artist, genre, source, youtube_id)
VALUES ('Track Title', 'Channel Name', 'YouTube', 'youtube', 'dQw4w9WgXcQ');
```

### Assign a track to a client:
```sql
INSERT INTO client_music (client_id, track_id)
SELECT pc.id, mt.id
FROM pipeline_clients pc, music_tracks mt
WHERE pc.slug = 'their-company-id'
AND mt.title = 'Track Title';
```

### Deactivate a Commander account:
```sql
UPDATE pipeline_clients SET status = 'inactive' WHERE slug = 'their-company-id';
```

---

## URL Map — All Admin Entry Points

| URL | What it does | Auth |
|---|---|---|
| `boothop.com/commander` | Commander login/register/reset | Company ID + password |
| `boothop.com/commander/dashboard` | Client dashboard | Commander session |
| `boothop.com/commander/music` | Client music management | Commander session |
| `boothop.com/client-onboarding` | Pipeline config wizard — client fills this in themselves | Public (client self-serve) |
| `boothop.com/onboard` | Client self-register for Revoice Studio | Public (client fills in) |
| `boothop.com/login` | Revoice Studio login | Email + password (SQLite) |
| `boothop.com/dashboard` | Revoice Studio | Oracle session |
| `boothop.com/onboard/admin/login` | Oracle admin login | ADMIN_PASSWORD |
| `boothop.com/onboard/admin` | Oracle admin panel | Oracle admin session |
| `boothop.com/onboard/admin/add-company` | Add Oracle client (POST) | Oracle admin session |
| `140.238.73.32` | Direct Oracle access (bypass Vercel) | — |

---

## Oracle Server — SSH & Maintenance

SSH key location: `C:\Users\babso\.ssh\oracle_boothop.pem`

```bash
ssh -i C:\Users\babso\.ssh\oracle_boothop.pem ubuntu@140.238.73.32
```

### Restart the dashboard:
```bash
sudo systemctl restart otb-dashboard
sudo systemctl status otb-dashboard
```

### View live logs:
```bash
sudo journalctl -u otb-dashboard -f
```

### Deploy pipeline changes:
```bash
cd /opt/otb_pipeline
git pull origin main
sudo systemctl restart otb-dashboard
```

---

## Pipeline Schedule

The OTB pipeline runs 4 video slots per day automatically via Task Scheduler (Windows) or cron (Oracle):

| Slot | Fire time | Platforms | Pillar type |
|---|---|---|---|
| S1 | 07:00 | IG Story + Blog + LinkedIn | Community / soft content |
| S2 | 09:00 | TikTok + Instagram Reel | Best hook of the day |
| S3 | 17:30 | TikTok + Instagram + IG Story | Evening diaspora window |
| S4 | 20:30 | TikTok + YouTube | Night scroll / Nigeria prime time |

Slots rotate through pillars (Community, Travel Hacks, Logistics, Supply Chain) on a 4-day cycle.

---

## Environment Variables Reference

### Oracle (`/etc/systemd/system/otb-dashboard.service`)

| Variable | Purpose |
|---|---|
| `PORT` | Dashboard listens on this port (1030) |
| `PIPELINE_ROOT` | Path to pipeline root on Oracle |
| `TELEGRAM_TOKEN` | Bot token for Telegram commander |
| `ADMIN_PASSWORD` | Oracle admin panel password |
| `ADMIN_PREFIX` | URL prefix for admin routes (`/onboard/admin`) |

To change:
```bash
sudo nano /etc/systemd/system/otb-dashboard.service
sudo systemctl daemon-reload && sudo systemctl restart otb-dashboard
```

### Vercel (Next.js / boothop.com)

| Variable | Purpose |
|---|---|
| `APP_SESSION_SECRET` | Signs Commander JWT cookies |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase DB access (Commander) |
| `RESEND_API_KEY` | Password reset emails |
| `YOUTUBE_DATA_API_KEY` | YouTube music search in Commander |
| `ADMIN_SECRET` | BootHop delivery marketplace admin |

---

## Databases — Quick Reference

| Database | Technology | Location | What's in it |
|---|---|---|---|
| Supabase | PostgreSQL | Cloud (`zwgngbzbdvnrdnanjded.supabase.co`) | Commander accounts, music library, assignments |
| Oracle SQLite | SQLite | `/opt/otb_pipeline/dashboard/otb.db` | Revoice Studio clients, sessions, bake history |
| BootHop Supabase | PostgreSQL | Same Supabase project | Delivery marketplace data (trips, matches, users) |

---

## Supabase Tables (Commander)

| Table | Purpose |
|---|---|
| `pipeline_clients` | One row per Commander account |
| `commander_reset_tokens` | Password reset links (1h expiry) |
| `music_tracks` | Shared track library (library + YouTube imports) |
| `client_music` | Which tracks are assigned to which client |

SQL migrations: `boothop/docs/commander-migrations.sql` (already run)

---

*BootHop Pipeline — Admin Reference v2.0 — June 2026*
