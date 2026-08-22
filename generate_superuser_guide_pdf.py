"""
BootHop Pipeline — Super User / Admin Guide PDF
Run: python generate_superuser_guide_pdf.py
Output: output/BootHop_Pipeline_SuperUser_Guide.pdf
"""
import os
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER

os.makedirs("output", exist_ok=True)
OUT = "output/BootHop_Pipeline_SuperUser_Guide.pdf"

# ── Colours ───────────────────────────────────────────────────
ORANGE  = colors.HexColor("#ff6b00")
AMBER   = colors.HexColor("#ffb800")
DARK    = colors.HexColor("#08080f")
CARD    = colors.HexColor("#121220")
MUTED   = colors.HexColor("#8888a8")
GREEN   = colors.HexColor("#00c853")
BLUE    = colors.HexColor("#5ba4e6")
RED     = colors.HexColor("#ff4040")
WHITE   = colors.white
BORDER  = colors.HexColor("#2a2a3a")
PURPLE  = colors.HexColor("#c080ff")

W, H = A4

# ── Styles ────────────────────────────────────────────────────
def s(name, **kw):
    return ParagraphStyle(name, **kw)

H1   = s("H1",  fontSize=26, textColor=ORANGE, fontName="Helvetica-Bold",
          spaceAfter=6, leading=32)
H2   = s("H2",  fontSize=16, textColor=WHITE,  fontName="Helvetica-Bold",
          spaceAfter=4, leading=22, spaceBefore=18)
H3   = s("H3",  fontSize=12, textColor=AMBER,  fontName="Helvetica-Bold",
          spaceAfter=3, leading=16, spaceBefore=10)
BODY = s("BD",  fontSize=9.5, textColor=colors.HexColor("#c0c0d8"),
          fontName="Helvetica", leading=15, spaceAfter=5)
BOLD_BODY = s("BB", fontSize=9.5, textColor=WHITE, fontName="Helvetica-Bold",
               leading=15, spaceAfter=5)
SMALL = s("SM", fontSize=8, textColor=MUTED, fontName="Helvetica",
           leading=12, spaceAfter=4)
CODE  = s("CO", fontSize=8.5, textColor=AMBER, fontName="Courier",
           leading=13, spaceAfter=4)
CENTRE = s("CE", fontSize=9, textColor=MUTED, fontName="Helvetica",
            alignment=TA_CENTER, leading=13)
LABEL = s("LB", fontSize=7.5, textColor=MUTED, fontName="Helvetica-Bold",
           leading=10, spaceAfter=2)
WARN  = s("WN", fontSize=8.5, textColor=RED, fontName="Helvetica-Bold",
           leading=12, spaceAfter=4)

# ── Helpers ───────────────────────────────────────────────────
def rule():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=10)

def warn_box(text):
    data = [[Paragraph(f"<b>WARNING</b>  {text}", WARN)]]
    t = Table(data, colWidths=[W - 4*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#ff404010")),
        ("LINEABOVE",  (0,0), (-1, 0), 2, RED),
        ("LEFTPADDING",(0,0), (-1,-1), 10),
        ("RIGHTPADDING",(0,0),(-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
    ]))
    return t

def tip_box(text):
    data = [[Paragraph(f"<b>TIP</b>  {text}", SMALL)]]
    t = Table(data, colWidths=[W - 4*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#ffb80010")),
        ("LINEABOVE",  (0,0), (-1, 0), 1.5, AMBER),
        ("LEFTPADDING",(0,0), (-1,-1), 10),
        ("RIGHTPADDING",(0,0),(-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
    ]))
    return t

def info_box(text):
    data = [[Paragraph(text, SMALL)]]
    t = Table(data, colWidths=[W - 4*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#5ba4e610")),
        ("LINEABOVE",  (0,0), (-1, 0), 1.5, BLUE),
        ("LEFTPADDING",(0,0), (-1,-1), 10),
        ("RIGHTPADDING",(0,0),(-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
    ]))
    return t

def step_table(rows):
    data = []
    for num, title, desc in rows:
        data.append([
            Paragraph(str(num), s(f"sn{num}", fontSize=13, textColor=ORANGE,
                                  fontName="Helvetica-Bold", alignment=TA_CENTER)),
            [Paragraph(title, BOLD_BODY), Paragraph(desc, SMALL)]
        ])
    t = Table(data, colWidths=[1*cm, W - 5*cm])
    t.setStyle(TableStyle([
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING",(0,0), (-1,-1), 6),
        ("TOPPADDING",  (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LINEBELOW",   (0,0), (-1,-2), 0.3, BORDER),
    ]))
    return t

def row_table(rows, col_w=None):
    data = [[Paragraph(a, LABEL), Paragraph(b, SMALL)] for a, b in rows]
    cw = col_w or [3.5*cm, W - 7.5*cm]
    t = Table(data, colWidths=cw)
    t.setStyle(TableStyle([
        ("LINEBELOW",   (0,0), (-1,-1), 0.3, BORDER),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING",(0,0), (-1,-1), 8),
        ("TOPPADDING",  (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
    ]))
    return t

# ── Document ──────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2.2*cm, bottomMargin=2*cm,
    title="BootHop Pipeline — Super User Guide",
    author="BootHop"
)

story = []

# ── Cover ─────────────────────────────────────────────────────
story.append(Spacer(1, 1.4*cm))
story.append(Paragraph("BootHop Pipeline", H1))
story.append(Paragraph("Super User & Admin Guide",
             s("SH", fontSize=18, textColor=WHITE, fontName="Helvetica-Bold",
               spaceAfter=8, leading=24)))
story.append(Paragraph(
    "Confidential — for BootHop team members and pipeline administrators only.",
    s("CI", fontSize=9, textColor=RED, fontName="Helvetica-Bold", leading=13, spaceAfter=6)))
story.append(rule())

# ── 1. System Overview ────────────────────────────────────────
story.append(Paragraph("1. System Overview", H2))
story.append(Paragraph(
    "The BootHop Pipeline is a FastAPI application running on Oracle Cloud (140.238.73.32). "
    "It manages multi-tenant content automation: each client (company) has its own isolated "
    "pipeline, schedule, credentials, and bake history, all stored in a single SQLite database "
    "at dashboard/otb.db.", BODY))
story.append(Spacer(1, 0.2*cm))
story.append(Paragraph("Key system facts:", H3))
story.append(row_table([
    ("Server",       "Oracle Cloud Always Free · 140.238.73.32 · Ubuntu 22.04"),
    ("App",          "FastAPI + Uvicorn · auto-restarted by systemd · port 8000"),
    ("GitHub sync",  "Cron pulls from GitHub every 5 minutes → /root/otb_pipeline"),
    ("Database",     "SQLite · dashboard/otb.db · one row per company"),
    ("Config",       "keys.env in pipeline root · loaded at startup · never commit this file"),
    ("Telegram bot", "Token in config.py · TELEGRAM_TOKEN · chat ID 8641867751 (admin)"),
]))

# ── 2. Four User Types ────────────────────────────────────────
story.append(Paragraph("2. The Four User Types", H2))
story.append(Paragraph(
    "The system has four distinct user types with separate login portals and permissions:", BODY))
story.append(Spacer(1, 0.1*cm))

user_data = [
    [Paragraph("Type", LABEL),      Paragraph("Login URL", LABEL),
     Paragraph("Who",  LABEL),      Paragraph("Access", LABEL)],
    [Paragraph("BootHop Website\nCustomer", SMALL),
     Paragraph("boothop.com/login", CODE),
     Paragraph("Members of the main boothop.com website", SMALL),
     Paragraph("Website features only — no pipeline access", SMALL)],
    [Paragraph("BootHop Admin\n(Website)", SMALL),
     Paragraph("boothop.com/boothop-admin", CODE),
     Paragraph("BootHop website staff", SMALL),
     Paragraph("Manage boothop.com website content and members", SMALL)],
    [Paragraph("Pipeline Client", SMALL),
     Paragraph("boothop.com/pipeline-login", CODE),
     Paragraph("Paying pipeline clients", SMALL),
     Paragraph("Their own dashboard: Pipeline, Revoice, Clients tabs", SMALL)],
    [Paragraph("Pipeline Super\nUser (Admin)", SMALL),
     Paragraph("boothop.com/admin/login", CODE),
     Paragraph("BootHop pipeline team", SMALL),
     Paragraph("All companies, intake queue, credentials, schedules, bake logs", SMALL)],
]
ut = Table(user_data, colWidths=[3.2*cm, 4.2*cm, 4*cm, W - 15.4*cm])
ut.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1, 0), CARD),
    ("LINEBELOW",     (0,0), (-1, 0), 1,   BORDER),
    ("LINEBELOW",     (0,1), (-1,-1), 0.3, BORDER),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("TOPPADDING",    (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(ut)
story.append(Spacer(1, 0.2*cm))
story.append(info_box(
    "<b>Admin password:</b>  Set in dashboard/main.py line ~42 as ADMIN_PASSWORD. "
    "Default: <font color='#ffb800' name='Courier'>otb-admin-2026</font>. "
    "This is NOT in keys.env — change it directly in the file and redeploy."
))

# ── 3. Admin Login ────────────────────────────────────────────
story.append(Paragraph("3. Admin Login", H2))
story.append(Paragraph(
    "Pipeline super user login is at:", BODY))
story.append(Paragraph("boothop.com/admin/login", CODE))
story.append(Paragraph(
    "This gives access to the admin dashboard showing all registered companies, "
    "the intake queue, company detail pages, and system controls.", BODY))
story.append(warn_box(
    "Never share the admin password with clients. "
    "If you suspect it is compromised, update ADMIN_PASSWORD in main.py immediately and redeploy."
))

# ── 4. Intake Workflow ────────────────────────────────────────
story.append(Paragraph("4. Client Intake Workflow", H2))
story.append(Paragraph(
    "New clients go through a two-stage intake before their pipeline is activated:", BODY))
story.append(Spacer(1, 0.15*cm))
story.append(step_table([
    (1, "Client submits intake form (boothop.com/get-started)",
        "Client fills in: company name, website, logo, industry, bio, location, target audience, "
        "tone, platforms, social handles, contact details, digest email. "
        "Status → 'submitted'. Admin receives a Telegram notification."),
    (2, "Onboarding call & Stage 2 credentials",
        "Admin goes to /admin/company/{id} → Credentials tab. "
        "Fills in API keys for each enabled platform: TikTok session/key/secret, "
        "Instagram app_id/secret/token/user_id, YouTube API key/channel_id/refresh_token, "
        "LinkedIn client_id/secret/access_token, Pexels key, Pixabay key. "
        "Click 'Save Credentials' — status → 'stage2'."),
    (3, "Set the schedule",
        "Go to the Schedule tab. Set slot times (up to 4 per day), toggle active days, "
        "select timezone. Copy the generated cron expression and enter it in cron.org."),
    (4, "Activate",
        "Click 'Activate Pipeline' on the company detail page. "
        "Status → 'active'. Client receives a Telegram notification with their schedule."),
]))
story.append(Spacer(1, 0.2*cm))
story.append(tip_box(
    "The intake queue on the admin overview highlights pending clients in amber. "
    "A number > 0 on the 'Intake Pending' stat card means action is required."
))

# ── 5. Schedule Setup & cron.org ─────────────────────────────
story.append(Paragraph("5. Schedule Setup & cron.org", H2))
story.append(Paragraph(
    "BootHop Pipeline uses cron.org as the external scheduler — it fires an HTTP call "
    "to the pipeline server at the configured times. You do not run cron jobs on the server directly.", BODY))
story.append(Spacer(1, 0.15*cm))
story.append(Paragraph("How to set up a cron.org job:", H3))
story.append(step_table([
    (1, "Generate the cron expression",
        "Go to /admin/company/{id} → Schedule tab. Set the slot times and days. "
        "The page automatically shows the correct cron expression — copy it with the button."),
    (2, "Open cron.org",
        "Go to https://cron.org and log in to the BootHop account. "
        "Click 'Add Job'."),
    (3, "Paste the cron expression",
        "Paste the expression into the 'Schedule' field. "
        "Example for 07:00 Mon–Fri: 0 7 * * 1-5"),
    (4, "Set the URL",
        "URL: https://boothop.com/api/run-pipeline/{slug} "
        "Method: POST · add header: X-Pipeline-Secret: {pipeline_secret}"),
    (5, "Save and test",
        "Click Save. Use 'Run Now' to trigger a test bake — check the Pipeline tab "
        "for the client to confirm a bake job appears."),
]))
story.append(Spacer(1, 0.2*cm))
story.append(row_table([
    ("Cron format", "minute hour day-of-month month day-of-week"),
    ("07:00 daily", "0 7 * * *"),
    ("12:00 Mon–Fri", "0 12 * * 1-5"),
    ("18:00 Mon/Wed/Fri", "0 18 * * 1,3,5"),
    ("09:00 Mondays only", "0 9 * * 1"),
], col_w=[4*cm, W - 8*cm]))

# ── 6. Stage 2 Credentials ───────────────────────────────────
story.append(Paragraph("6. Stage 2 API Credentials", H2))
story.append(Paragraph(
    "Each platform requires different credentials. Collect these during the onboarding call "
    "or from the client's developer settings pages.", BODY))
story.append(Spacer(1, 0.1*cm))

platforms = [
    ("TikTok",
     "session_key, session_token (from TikTok app auth or Business Center), "
     "api_key, api_secret (from TikTok Developer Portal → Your App)"),
    ("Instagram",
     "app_id, app_secret (from Meta Developer Portal → App), "
     "access_token (long-lived token from Graph API), user_id (numeric Instagram user ID)"),
    ("YouTube",
     "api_key (from Google Cloud Console → Credentials), "
     "channel_id (from YouTube Studio → Settings → Advanced), "
     "refresh_token (from OAuth2 flow with youtube.upload scope)"),
    ("LinkedIn",
     "client_id, client_secret (from LinkedIn Developer Portal → App), "
     "access_token (3-legged OAuth with w_member_social scope)"),
    ("Pexels",
     "api_key — free account at pexels.com/api. Limit: 200 req/hour, 20,000 req/month."),
    ("Pixabay",
     "api_key — free account at pixabay.com/api/docs. Limit: 100 req/minute."),
    ("Blog",
     "platform (wordpress/ghost/webflow), blog_id, refresh_token"),
]
for plat, details in platforms:
    story.append(KeepTogether([
        Paragraph(plat, H3),
        Paragraph(details, SMALL),
        Spacer(1, 0.05*cm),
    ]))

story.append(warn_box(
    "All credentials are stored in the otb.db SQLite database. "
    "Do not export or share the database file — it contains all client API tokens."
))

# ── 7. Company Detail Page ───────────────────────────────────
story.append(Paragraph("7. Company Detail Page", H2))
story.append(Paragraph(
    "Access any company's full detail at: /admin/company/{company_id}", BODY))
story.append(Paragraph(
    "The page has five tabs:", BODY))
story.append(Spacer(1, 0.1*cm))
story.append(row_table([
    ("Profile",      "Business info, social handles, contact details, logo. Reset password."),
    ("Schedule",     "Slot time pickers, day toggles, timezone, cron expression generator."),
    ("Credentials",  "Platform API keys — Stage 2 form + existing credentials display."),
    ("Bakes",        "Full bake history: headline, platforms, timestamp, status."),
    ("Danger",       "Permanently delete the company and all its data."),
]))

# ── 8. Activating & Pausing ──────────────────────────────────
story.append(Paragraph("8. Activating & Pausing a Client", H2))
story.append(Paragraph(
    "Activation and pause buttons are on the company detail page header area.", BODY))
story.append(Spacer(1, 0.1*cm))
story.append(row_table([
    ("Activate Pipeline",
     "Sets intake_status = 'active'. Sends Telegram notification to client with schedule summary. "
     "Pipeline will run at next cron.org slot."),
    ("Pause Pipeline",
     "Sets intake_status = 'paused'. Pipeline stops generating new bakes. "
     "Existing bakes in queue are not affected. To fully stop: also disable the cron.org job."),
    ("Reset Password",
     "Generates a new SHA-256 hash for the client's chosen password. "
     "You must tell the client their new password manually (Telegram or email)."),
]))

# ── 9. Telegram Notifications ────────────────────────────────
story.append(Paragraph("9. Telegram Notifications (Admin)", H2))
story.append(Paragraph(
    "The admin Telegram chat ID is hardcoded as 8641867751. "
    "Notifications sent to admin:", BODY))
story.append(row_table([
    ("New intake submitted",
     "Fires when a client completes /get-started. "
     "Shows company name, contact email, and selected platforms."),
    ("Pipeline error",
     "Fires when a bake job fails on the server — includes company slug and error summary."),
]))
story.append(Spacer(1, 0.1*cm))
story.append(Paragraph("Notifications sent to client (at their tg_chat_id):", BODY))
story.append(row_table([
    ("Pipeline activated",
     "Fires when admin clicks 'Activate Pipeline'. "
     "Includes slot times, active days, timezone, and login URL."),
    ("Video preview",
     "Fires each time a bake slot runs — hook text and platforms."),
]))
story.append(info_box(
    "Telegram notifications only fire if tg_chat_id is set for the company. "
    "Always collect the client's Telegram chat ID during onboarding. "
    "They can find it by messaging @userinfobot on Telegram."
))

# ── 10. Manually Adding a Company ───────────────────────────
story.append(Paragraph("10. Manually Adding a Company", H2))
story.append(Paragraph(
    "Use the 'Add Company Manually' form at the bottom of the admin dashboard "
    "for clients who could not complete the online intake form. "
    "Required fields: Company Name, Password. "
    "Also enter contact name, email, Telegram chat ID, and plan.", BODY))
story.append(tip_box(
    "Manually added companies bypass the intake workflow and default to 'active' status. "
    "Make sure to fill their credentials in the Credentials tab before the first cron run."
))

# ── 11. Database Schema ──────────────────────────────────────
story.append(Paragraph("11. Key Database Columns", H2))
story.append(Paragraph(
    "Table: companies (SQLite · dashboard/otb.db)", BODY))
story.append(Spacer(1, 0.1*cm))
schema = [
    ("id",               "Auto-increment primary key"),
    ("name",             "Company display name"),
    ("slug",             "URL-safe ID used as login username (e.g. acme-media)"),
    ("pw_hash",          "SHA-256 of the client password"),
    ("email",            "Client contact email"),
    ("tg_chat_id",       "Telegram chat ID for client notifications"),
    ("intake_status",    "submitted → stage2 → active | paused"),
    ("intake_submitted", "ISO timestamp when /get-started form was submitted"),
    ("schedule_json",    "JSON with slot1–slot4 times, days[], timezone"),
    ("platforms_enabled","JSON array of enabled platform names"),
    ("logo_path",        "Relative path to logo file under dashboard/companies/{slug}/"),
    ("tt_handle",        "TikTok @handle (no @)"),
    ("ig_handle",        "Instagram @handle (no @)"),
    ("youtube_url",      "Full YouTube channel URL"),
    ("linkedin_url",     "Full LinkedIn company/personal page URL"),
    ("website_url",      "Client's main website"),
    ("business_bio",     "Short description used in content prompts"),
    ("target_audience",  "Audience description used in content prompts"),
    ("brand_voice",      "Tone/style notes for script generation"),
    ("digest_email",     "Email for daily/weekly report digest"),
    ("digest_frequency", "daily | weekly | both"),
]
t = Table(
    [[Paragraph(k, LABEL), Paragraph(v, SMALL)] for k, v in schema],
    colWidths=[4*cm, W - 8*cm]
)
t.setStyle(TableStyle([
    ("LINEBELOW",   (0,0), (-1,-1), 0.3, BORDER),
    ("LEFTPADDING", (0,0), (-1,-1), 8),
    ("RIGHTPADDING",(0,0), (-1,-1), 8),
    ("TOPPADDING",  (0,0), (-1,-1), 5),
    ("BOTTOMPADDING",(0,0),(-1,-1), 5),
    ("VALIGN",      (0,0), (-1,-1), "TOP"),
]))
story.append(t)

# ── 12. Server & Deployment ──────────────────────────────────
story.append(Paragraph("12. Server & Deployment", H2))
story.append(row_table([
    ("SSH access",       "ssh -i ~/.ssh/oracle_key ubuntu@140.238.73.32"),
    ("App directory",    "/root/otb_pipeline (pulled from GitHub)"),
    ("Restart app",      "sudo systemctl restart otb-pipeline"),
    ("View logs",        "sudo journalctl -u otb-pipeline -f"),
    ("GitHub sync",      "Cron job: */5 * * * * cd /root/otb_pipeline && git pull"),
    ("DB backup",        "Copy dashboard/otb.db off-server weekly. No automated backup currently."),
    ("keys.env",         "/root/otb_pipeline/keys.env — never commit. "
                          "Contains TELEGRAM_TOKEN, TG_ADMIN_CHAT_ID, platform API keys, ADMIN_PASSWORD env override."),
]))
story.append(Spacer(1, 0.2*cm))
story.append(warn_box(
    "keys.env is in .gitignore. If you add a new key variable, update keys.env on the server "
    "manually via SSH — it will NOT be pulled from GitHub."
))

# ── 13. Troubleshooting ──────────────────────────────────────
story.append(Paragraph("13. Troubleshooting", H2))
faqs = [
    ("Client says they can't log in",
     "Check that intake_status = 'active' in the DB. "
     "Check the slug matches exactly (lowercase, hyphens). "
     "Use 'Reset Password' on the company detail page to issue a new password."),
    ("Bake job shows 'failed' status",
     "Go to company detail → Bakes tab. Click the bake row for the error message. "
     "Common causes: expired API token (re-enter in Credentials tab), "
     "platform rate limit (bake will retry next slot), video too large for platform."),
    ("Client not receiving Telegram notifications",
     "Check tg_chat_id is set correctly (no spaces, correct numeric ID). "
     "Ask client to message @userinfobot to confirm their ID. "
     "Check that the bot has not been blocked by the client."),
    ("cron.org job fires but no bake appears",
     "Check cron.org logs for the HTTP response code. "
     "Common: 422 (wrong URL slug), 403 (wrong pipeline secret in header), "
     "500 (server error — check journalctl)."),
    ("Server unresponsive",
     "SSH in and run: sudo systemctl status otb-pipeline. "
     "If stopped: sudo systemctl start otb-pipeline. "
     "If memory: sudo reboot (data is safe in DB)."),
    ("Need to add a new API key globally",
     "Add to keys.env on the server. Add os.environ.get('NEW_KEY') in config.py. "
     "Restart the app: sudo systemctl restart otb-pipeline."),
]
for q, a in faqs:
    story.append(KeepTogether([
        Paragraph(q, BOLD_BODY),
        Paragraph(a, SMALL),
        Spacer(1, 0.1*cm),
    ]))

# ── Footer ────────────────────────────────────────────────────
story.append(Spacer(1, 0.4*cm))
story.append(rule())
story.append(Paragraph(
    "BootHop Pipeline · Internal Admin Guide · boothop.com · support@boothop.com",
    CENTRE))
story.append(Paragraph(
    "CONFIDENTIAL — Do not share outside the BootHop team.",
    s("FT", fontSize=7.5, textColor=RED, fontName="Helvetica-Bold",
      alignment=TA_CENTER, leading=11)))

# ── Build ─────────────────────────────────────────────────────
doc.build(story)
print(f"Created: {OUT}")
