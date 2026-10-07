import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

gmail_user = "titobalo12@gmail.com"
gmail_pw   = "howq mtby fbei ydzj"
to_email   = "titobalo12@gmail.com"

html = """<!DOCTYPE html>
<html>
<head>
<style>
body{font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:0}
.wrap{max-width:620px;margin:30px auto;background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e0e0e0}
.header{background:linear-gradient(135deg,#ff6b00,#ffb800);padding:28px 30px}
.header h1{color:#fff;margin:0;font-size:1.4rem;font-weight:900}
.header p{color:rgba(255,255,255,0.7);margin:4px 0 0;font-size:.85rem}
.body{padding:28px 30px}
h2{font-size:1rem;font-weight:800;color:#ff6b00;margin:24px 0 8px;padding-bottom:6px;border-bottom:2px solid #fff0e0}
h2:first-child{margin-top:0}
.row{margin-bottom:8px;font-size:.88rem;line-height:1.5}
.lbl{color:#888;font-size:.78rem;display:block;margin-bottom:1px}
.val{color:#1a1a2e;font-weight:700;font-family:monospace;word-break:break-all}
.note{background:#fff8f0;border-left:3px solid #ffb800;padding:10px 14px;border-radius:0 6px 6px 0;font-size:.82rem;color:#555;margin:10px 0 16px}
.footer{background:#f9f9f9;padding:16px 30px;font-size:.75rem;color:#aaa;border-top:1px solid #eee}
table{width:100%;border-collapse:collapse;font-size:.87rem}
td{padding:7px 10px;border-bottom:1px solid #f0f0f0;vertical-align:top}
td:first-child{color:#888;font-size:.8rem;white-space:nowrap;width:160px}
td:last-child{font-family:monospace;font-weight:700;color:#1a1a2e;word-break:break-all}
tr:last-child td{border-bottom:none}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>BootHop Pipeline &mdash; Master Reference</h1>
    <p>Passwords, URLs, manuals and reset process &mdash; keep this safe</p>
  </div>
  <div class="body">

    <h2>Super User (Admin)</h2>
    <table>
      <tr><td>Login URL</td><td>130.162.162.189:8080/admin/login</td></tr>
      <tr><td>Super User Guide</td><td>130.162.162.189:8080/admin/guide</td></tr>
      <tr><td>Password</td><td>Stored as hash in DB &mdash; change from bottom of 130.162.162.189:8080/admin</td></tr>
    </table>
    <div class="note">If ever locked out: re-run deploy/deploy_dashboard_oracle.ps1 with a new -AdminPassword (editing keys.env alone won't work — the systemd service's own environment variable overrides it). See docs/DASHBOARD_ACCESS.md.</div>

    <h2>Client Logins &mdash; 130.162.162.189:8080/pipeline-login</h2>
    <table>
      <tr><td>G-Inspired</td><td>ID: g-inspired &nbsp;|&nbsp; PW: ginspired-2026</td></tr>
      <tr><td>D818 Catering</td><td>ID: d818 &nbsp;|&nbsp; PW: d818-2026</td></tr>
      <tr><td>BootHop (internal)</td><td>ID: boothop &nbsp;|&nbsp; PW: boothop-pipeline-2026</td></tr>
    </table>

    <h2>Password Reset Process</h2>
    <table>
      <tr><td>Client self-service</td><td>130.162.162.189:8080/forgot-password &mdash; enter Company ID + email, link sent to email AND Telegram, expires 1 hour</td></tr>
      <tr><td>Admin resets client</td><td>Admin portal &rarr; company page &rarr; Profile tab &rarr; set new password</td></tr>
      <tr><td>Admin resets own PW</td><td>130.162.162.189:8080/admin &rarr; scroll to bottom &rarr; Change Admin Password form</td></tr>
    </table>

    <h2>Online Manuals (live &mdash; auto-update)</h2>
    <table>
      <tr><td>Client Guide</td><td>130.162.162.189:8080/manual &mdash; PUBLIC, no login needed. Share this link with clients. Covers login, dashboard, Telegram setup, WhatsApp setup, FAQ.</td></tr>
      <tr><td>Super User Guide</td><td>130.162.162.189:8080/admin/guide &mdash; Admin login required. Full reference: server SSH, how scheduling works, all platform API credential guides, troubleshooting.</td></tr>
    </table>
    <div class="note">Both manuals update automatically every time a change is pushed to GitHub. Bookmark the URL &mdash; never save a PDF copy.</div>

    <h2>All Key URLs</h2>
    <table>
      <tr><td>Admin overview</td><td>130.162.162.189:8080/admin</td></tr>
      <tr><td>Client login</td><td>130.162.162.189:8080/pipeline-login</td></tr>
      <tr><td>Forgot password</td><td>130.162.162.189:8080/forgot-password</td></tr>
      <tr><td>Client Guide</td><td>130.162.162.189:8080/manual</td></tr>
      <tr><td>Super User Guide</td><td>130.162.162.189:8080/admin/guide</td></tr>
      <tr><td>Onboarding form</td><td>130.162.162.189:8080/get-started</td></tr>
      <tr><td>Manual onboard</td><td>130.162.162.189:8080/client-onboarding</td></tr>
      <tr><td>48h activity feed</td><td>130.162.162.189:8080/feed</td></tr>
      <tr><td>Telegram commander</td><td>130.162.162.189:8080/commander</td></tr>
    </table>

    <h2>Oracle Server (SSH)</h2>
    <table>
      <tr><td>IP address</td><td>130.162.162.189</td></tr>
      <tr><td>SSH command</td><td>ssh -i ~/.ssh/oracle_boothop.pem ubuntu@130.162.162.189</td></tr>
      <tr><td>App path</td><td>/opt/otb_pipeline</td></tr>
      <tr><td>API keys file</td><td>/opt/otb_pipeline/keys.env</td></tr>
      <tr><td>Restart app</td><td>sudo systemctl restart otb-dashboard</td></tr>
      <tr><td>Live logs</td><td>journalctl -u otb-dashboard -f</td></tr>
      <tr><td>Deploy</td><td>Push to GitHub main branch &mdash; manual deploy only — no auto-pull</td></tr>
    </table>

  </div>
  <div class="footer">
    BootHop Pipeline &nbsp;&middot;&nbsp; titobalo12@gmail.com &nbsp;&middot;&nbsp; Keep this email private &mdash; it contains access credentials.
  </div>
</div>
</body>
</html>"""

plain = """BOOTHOP PIPELINE -- MASTER REFERENCE
=====================================

SUPER USER (ADMIN)
  Login:      130.162.162.189:8080/admin/login
  Guide:      130.162.162.189:8080/admin/guide
  Password:   Stored as DB hash -- change from bottom of admin portal
  Locked out? Re-run deploy_dashboard_oracle.ps1 with a new -AdminPassword
  (editing keys.env alone won't work -- systemd's own env var overrides it)

CLIENT LOGINS  (130.162.162.189:8080/pipeline-login)
  G-Inspired:   ID: g-inspired    PW: ginspired-2026
  D818:         ID: d818          PW: d818-2026
  BootHop:      ID: boothop       PW: boothop-pipeline-2026

PASSWORD RESET
  Client self-service:  130.162.162.189:8080/forgot-password
                        Company ID + email -> link sent to email + Telegram (expires 1hr)
  Admin resets client:  Admin portal -> company -> Profile tab
  Admin resets own PW:  130.162.162.189:8080/admin -> scroll to bottom -> Change Admin Password

ONLINE MANUALS (auto-update on every GitHub push)
  Client Guide (public):    130.162.162.189:8080/manual
  Super User Guide (admin): 130.162.162.189:8080/admin/guide

ALL KEY URLS
  Admin overview:      130.162.162.189:8080/admin
  Client login:        130.162.162.189:8080/pipeline-login
  Forgot password:     130.162.162.189:8080/forgot-password
  Client Guide:        130.162.162.189:8080/manual
  Super User Guide:    130.162.162.189:8080/admin/guide
  Onboarding form:     130.162.162.189:8080/get-started
  Manual onboard:      130.162.162.189:8080/client-onboarding
  48h feed:            130.162.162.189:8080/feed
  Commander:           130.162.162.189:8080/commander

ORACLE SERVER
  IP:       130.162.162.189
  SSH:      ssh -i ~/.ssh/oracle_boothop.pem ubuntu@130.162.162.189
  App:      /opt/otb_pipeline
  Keys:     /opt/otb_pipeline/keys.env
  Restart:  sudo systemctl restart otb-dashboard
  Logs:     journalctl -u otb-dashboard -f
  Deploy:   push to GitHub main -- manual deploy only — no auto-pull
"""

msg = MIMEMultipart("alternative")
msg["Subject"] = "BootHop Pipeline - Master Reference (passwords, URLs, manuals)"
msg["From"]    = gmail_user
msg["To"]      = to_email
msg.attach(MIMEText(plain, "plain"))
msg.attach(MIMEText(html,  "html"))

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(gmail_user, gmail_pw)
        s.sendmail(gmail_user, to_email, msg.as_string())
    print("Email sent successfully to", to_email)
except Exception as e:
    print(f"Error: {e}")
