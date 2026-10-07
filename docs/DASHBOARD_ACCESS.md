# OTB Pipeline — Getting Online Access

*Added: 2026-10-05, updated 2026-10-07*

There are two completely different kinds of "access" here. Don't mix them up — one is safe to hand to anyone who needs to check on things, the other is full control of the server and every API key on it.

---

## 1. Dashboard access (view/manage pipelines — safe to share)

A web dashboard is deployed on Oracle as a systemd service (`otb-dashboard`), covering **all companies** and **individual** pipelines.

| Page | URL | What it's for |
|---|---|---|
| Admin — all companies | `http://130.162.162.189:8080/admin/login` → `/admin` | Overview of every client pipeline |
| Individual company | `http://130.162.162.189:8080/admin/company/{company_id}` | One client's status, slots, schedule |
| Onboard a new client | `http://130.162.162.189:8080/onboard` | |
| Client onboarding wizard | `http://130.162.162.189:8080/client-onboarding` | |

**Password:** in `credentials/OTB_Dashboard_credentials.txt` (this file is gitignored — local to this laptop only, never committed). This doc deliberately doesn't repeat the password inline.

**To give someone else dashboard access:** just give them the URL + password from that credentials file. That's it — it's a normal login, doesn't expose SSH, API keys, or anything server-level. If you want them to have their *own* password instead of sharing yours, re-run the deploy with a new one:
```powershell
$env:TELEGRAM_TOKEN = "<value from keys.env>"
$env:OTB_ADMIN_PASSWORD = "<new password>"
cd C:\Users\babso\Desktop\OTB_Pipeline
.\deploy\deploy_dashboard_oracle.ps1
```
(This restarts the service with the new password — same URL, old password stops working.)

**Is it actually reachable right now?** The dashboard *runs* as soon as it's deployed, but Oracle Cloud has its own network firewall (Security List) in front of the VM, separate from anything on the server itself — port 8080 has to be explicitly opened there or nothing outside Oracle can reach it, no matter how correctly the service itself is running. Checked 2026-10-05: only ports 22 (SSH), 80, 443 were open. To open 8080:

- **OCI Console** → Networking → Virtual Cloud Networks → your VCN → subnet → Security List → Add Ingress Rules: Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port Range `8080`.
- Or via the OCI Python SDK (`pip install oci` — this installs cleanly; `pip install oci-cli` does not, it needs a full C++ build toolchain for one of its dependencies) using the credentials already in `~/.oci/config`. This requires explicit per-action approval in Claude Code (a firewall change is flagged as a "security weaken" action) — expect a permission prompt rather than it running silently.

---

## What the dashboard can actually do (as of 2026-10-07)

The dashboard existed well before this, but several of its controls looked like they worked and didn't — they updated the dashboard's own database and nothing else, with no error or indication anything was wrong. All of the below is now **confirmed working**, tested against a real profile (`client_profiles/d818.json`, local + Oracle) before being trusted:

| Feature | Status | What it actually does |
|---|---|---|
| **Schedule tab** (`/admin/company/{id}` → Schedule) | ✅ Fixed 2026-10-06 | Writes slot times + active days + timezone directly into that client's `client_profile.json`, both locally and on Oracle (over SSH). Takes effect within 10-15 minutes via the normal dispatcher check — see `docs/HOW_IT_RUNS.md` §4/§5. |
| **Activate/Pause buttons** (company detail page header) | ✅ Fixed 2026-10-07 | Now also sets `schedule.active` in the real profile file (local + Oracle), on top of the dashboard's own `intake_status`/`active` DB columns. Before this fix, clicking these only updated the DB — the pipeline kept running (or not) regardless of what the button said. |
| **D818's own pause/resume** | ✅ Fixed 2026-10-04/05 | Previously toggled Windows Task Scheduler tasks (`D818-Morning` etc.) that were renamed to `OTB_Dispatch_D818` back in September — a silent no-op. Now uses the same profile-file mechanism as BootHop/G-Inspired. |
| **Pause/resume syncing to Oracle at all** (any client) | ✅ Fixed 2026-10-07 | Found while testing the above: the helper that pushes an active/paused change to Oracle (`_oracle_set_active` in `dashboard/main.py`) had a bug that made every single call to it fail silently on Oracle specifically — it built Python code using JSON's `true`/`false` instead of Python's `True`/`False`. This existed before any of today's changes, so **BootHop and G-Inspired's pause/resume have never actually reached Oracle**, only the laptop's local copy, for as long as this function has existed. Fixing it benefits all three clients, not just D818. |

None of this required a password change or re-login — if you were already relying on these buttons before 2026-10-07 and assumed they worked, it's worth double-checking each client's actual `schedule.active` state now matches what the dashboard says, since the two could have drifted apart silently.

---

## 2. Server / infrastructure access (full control — do NOT casually share)

This is SSH into the actual Oracle VM, or OCI Console access to the cloud account itself. Either one means full control: every API key in `keys.env`, the ability to change what the pipeline does, delete things, see every client's data.

| What | Where it lives | Grants |
|---|---|---|
| SSH private key | `~/.ssh/oracle_boothop.pem` (this laptop only) | Full shell on the Oracle VM as `ubuntu` |
| OCI API key | `~/.oci/oci_api_key.pem` + `~/.oci/config` (this laptop only) | Full control of the Oracle Cloud account — create/delete servers, change firewall rules, billing, everything |

**Never send either of these files anywhere** — not git, not Slack, not email, not another machine. If someone else legitimately needs server access:
- **SSH**: have them generate their *own* key pair (`ssh-keygen`), send you the **public** key only, and add it to `~/.ssh/authorized_keys` on Oracle yourself. Don't hand out this `.pem` file.
- **OCI Console**: add them as a user in the OCI Console (Identity & Security → Domains → Users) with whatever permissions they actually need, rather than sharing this account's API key.

If you only need someone to *see* pipeline status, approve/reject posts, or check on a client — that's the dashboard in §1, not this.

---

## Troubleshooting

### Every page 500s with a cryptic Jinja2 error ("unhashable type: 'dict'")

Hit this during the initial 2026-10-05 deploy. Root cause: `deploy/deploy_dashboard_oracle.ps1` installs `fastapi uvicorn python-multipart jinja2` with **no version pins** — it just grabs whatever's current on PyPI. At some point, Starlette (FastAPI's underlying framework) changed `TemplateResponse()`'s signature to require `request` as the first positional argument (`TemplateResponse(request, name, context)`) instead of the old form (`TemplateResponse(name, context)` with `request` tucked inside `context`). Under the new signature, calling it the old way silently shuffles arguments: the template name string lands in the `request` parameter, and the context *dict* lands in the `name` parameter — which then gets used as a Jinja2 template cache key. Dicts aren't hashable, hence the error, three call-frames deep inside Jinja2 internals with no obvious connection to the real cause.

Fixed 2026-10-05/06: all 29 `templates.TemplateResponse(...)` call sites in `dashboard/main.py` now pass `request` as the explicit first argument. If this exact error reappears after a future `deploy_dashboard_oracle.ps1` run pulls a dependency update, it's very unlikely to be this same bug again (the code's now written against the current signature) — check `sudo journalctl -u otb-dashboard --no-pager -n 50` on Oracle for the actual new traceback rather than assuming it's a repeat.

**The underlying risk is still there**: because the deploy script pins nothing, *any* future redeploy can pull a newer FastAPI/Starlette/Jinja2 with its own breaking changes. If you want to stop this class of bug from recurring entirely, pin exact versions in the script's `pip3 install` line once a known-good combination is confirmed working.

### Dashboard runs but isn't reachable (connection times out, not even refused)

That's the Oracle Cloud Security List blocking the port — see §1's "Is it actually reachable right now?" section. A timeout (not a "connection refused") is the tell: the request never even reached the VM.

---

## Quick reference

```powershell
# SSH into Oracle directly
ssh -i $env:USERPROFILE\.ssh\oracle_boothop.pem ubuntu@130.162.162.189

# Check the dashboard service is actually running
ssh -i $env:USERPROFILE\.ssh\oracle_boothop.pem ubuntu@130.162.162.189 "sudo systemctl status otb-dashboard --no-pager"

# Re-deploy the dashboard (new code, new password, or after a reboot)
cd C:\Users\babso\Desktop\OTB_Pipeline
.\deploy\deploy_dashboard_oracle.ps1
```

See `docs/HOW_IT_RUNS.md` for how the pipeline itself works once you're in.
