# Admin Guide
**OTB Pipeline Dashboard**

---

## Accessing the Admin Panel

```
https://www.boothop.com/onboard/admin/login
```

Password is set via the `ADMIN_PASSWORD` environment variable on Oracle. Default: `otb-admin-2026`.

> This is separate from the main BootHop admin at `boothop.com/admin`.

---

## Admin Dashboard Overview

After logging in you see a table of all registered companies with:

- Company name, plan, and slug
- Contact name and email
- Bake count (total videos processed)
- Last activity date
- Actions: **View**, **Delete**

At the top: total bakes across all clients and how many companies were active today.

---

## Adding a Client Manually

Click **Add Company** and fill in:

| Field | Notes |
|---|---|
| Company Name | Used to generate the URL slug (e.g. `acme-corp`) |
| Contact Name | Person's name |
| Email | Login email |
| Password | They use this to log in — tell them this |
| WhatsApp | Optional |
| Telegram Chat ID | Optional — for bot notifications |
| Plan | `basic` or `priority` |

Click **Create**. The client can now log in at `boothop.com/login`.

> Clients can also self-register at `boothop.com/onboard` — you don't need to do this manually.

---

## Viewing a Client's Detail

Click **View** next to a company to see:

- All bakes for that client (video slot, status, timestamps)
- API key (for programmatic access)
- Account settings

---

## Deactivating a Client

Click **Delete** next to the company. This sets `active=0` in the database — the client can no longer log in. This does **not** delete their data.

---

## Logging Out

Click **Logout** in the top-right. Sessions expire automatically after 24 hours.

---

## Environment Variables (Oracle systemd service)

The dashboard service runs at `/etc/systemd/system/otb-dashboard.service`.

| Variable | Purpose | Default |
|---|---|---|
| `PORT` | Port the server listens on | `1030` |
| `PIPELINE_ROOT` | Path to the OTB pipeline root | auto-detected |
| `TELEGRAM_TOKEN` | Bot token for Telegram integration | — |
| `ADMIN_PASSWORD` | Admin login password | `otb-admin-2026` |
| `ADMIN_PREFIX` | URL prefix for admin redirects | `/onboard/admin` |

To change a variable:
```bash
sudo nano /etc/systemd/system/otb-dashboard.service
sudo systemctl daemon-reload
sudo systemctl restart otb-dashboard
```

---

## Database

Location: `/opt/otb_pipeline/dashboard/otb.db` (SQLite)

Tables:
- `companies` — registered clients
- `sessions` — active login tokens
- `bakes` — all video bake jobs

To inspect:
```bash
sqlite3 /opt/otb_pipeline/dashboard/otb.db
.tables
SELECT * FROM companies;
```

---

## Restarting the Dashboard

```bash
sudo systemctl restart otb-dashboard
sudo systemctl status otb-dashboard
```

Logs:
```bash
sudo journalctl -u otb-dashboard -f
```

---

## URL Map

| URL | What it does |
|---|---|
| `boothop.com/onboard` | Client self-registration |
| `boothop.com/client-onboarding` | 5-step setup wizard |
| `boothop.com/login` | Client login |
| `boothop.com/dashboard` | Client dashboard / Revoice Studio |
| `boothop.com/onboard/admin/login` | Admin login |
| `boothop.com/onboard/admin` | Admin overview |
| `boothop.com/onboard/admin/add-company` | Add client (POST) |
| `140.238.73.32/onboard` | Direct Oracle access (bypass Vercel) |

---

*OTB Pipeline — Admin reference v1.0 — June 2026*
