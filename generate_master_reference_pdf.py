"""
BootHop Pipeline — Master Reference Document
For the pipeline owner / super user.
Run: python generate_master_reference_pdf.py
Output: output/BootHop_Pipeline_Master_Reference.pdf
"""
import os
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT

os.makedirs("output", exist_ok=True)
OUT = "output/BootHop_Pipeline_Master_Reference.pdf"

W, H = A4

# ── Colours ──────────────────────────────────────────────────
ORANGE = colors.HexColor("#ff6b00")
AMBER  = colors.HexColor("#ffb800")
GREEN  = colors.HexColor("#00c853")
BLUE   = colors.HexColor("#5ba4e6")
RED    = colors.HexColor("#e53935")
WHITE  = colors.white
SLATE  = colors.HexColor("#e0e0f0")
MUTED  = colors.HexColor("#888888")
DARK   = colors.HexColor("#121220")
BORDER = colors.HexColor("#dddddd")
LIGHT  = colors.HexColor("#f9f9fb")
AMBER_LIGHT = colors.HexColor("#fff8e1")
AMBER_BORDER = colors.HexColor("#ffe082")
RED_LIGHT = colors.HexColor("#ffebee")
RED_BORDER = colors.HexColor("#ef9a9a")
GREEN_LIGHT = colors.HexColor("#e8f5e9")
GREEN_BORDER = colors.HexColor("#a5d6a7")
BLUE_LIGHT = colors.HexColor("#e3f2fd")

# ── Styles ────────────────────────────────────────────────────
def s(name, **kw):
    return ParagraphStyle(name, **kw)

TITLE   = s("TI", fontSize=28, textColor=ORANGE, fontName="Helvetica-Bold",
             leading=34, spaceAfter=4)
SUBTITLE= s("ST", fontSize=14, textColor=colors.HexColor("#444466"),
             fontName="Helvetica", leading=18, spaceAfter=6)
H1      = s("H1", fontSize=18, textColor=ORANGE, fontName="Helvetica-Bold",
             leading=24, spaceAfter=6, spaceBefore=22)
H2      = s("H2", fontSize=13, textColor=colors.HexColor("#222244"),
             fontName="Helvetica-Bold", leading=18, spaceAfter=4, spaceBefore=14)
BODY    = s("BD", fontSize=10, textColor=colors.HexColor("#333355"),
             fontName="Helvetica", leading=16, spaceAfter=5)
BOLD    = s("BO", fontSize=10, textColor=colors.HexColor("#111133"),
             fontName="Helvetica-Bold", leading=16, spaceAfter=4)
SMALL   = s("SM", fontSize=8.5, textColor=colors.HexColor("#555577"),
             fontName="Helvetica", leading=13, spaceAfter=3)
CODE    = s("CO", fontSize=9, textColor=colors.HexColor("#aa4400"),
             fontName="Courier", leading=14, spaceAfter=3)
CENTRE  = s("CE", fontSize=8.5, textColor=MUTED, fontName="Helvetica",
             alignment=TA_CENTER, leading=12)
LBL     = s("LB", fontSize=7.5, textColor=MUTED, fontName="Helvetica-Bold",
             leading=10, spaceAfter=1)

CW = W - 4*cm   # content width

def rule(color=BORDER):
    return HRFlowable(width="100%", thickness=0.8, color=color, spaceAfter=10)

def thin_rule():
    return HRFlowable(width="100%", thickness=0.4, color=BORDER, spaceAfter=6)

def section_rule():
    return HRFlowable(width="100%", thickness=2, color=ORANGE, spaceAfter=14)

def box(paragraphs, bg=LIGHT, border=BORDER, left_accent=None):
    style = [
        ("BACKGROUND",    (0,0), (-1,-1), bg),
        ("LEFTPADDING",   (0,0), (-1,-1), 14),
        ("RIGHTPADDING",  (0,0), (-1,-1), 14),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("BOX",           (0,0), (-1,-1), 0.7, border),
    ]
    if left_accent:
        style.append(("LINEBEFORE", (0,0), (-1,-1), 3, left_accent))
    t = Table([[p] if not isinstance(p, list) else p for p in paragraphs],
              colWidths=[CW])
    t.setStyle(TableStyle(style))
    return t

def warning_box(text):
    return box([Paragraph(f"<b>Important:</b>  {text}", SMALL)],
               bg=RED_LIGHT, border=RED_BORDER, left_accent=RED)

def tip_box(text):
    return box([Paragraph(f"<b>Tip:</b>  {text}", SMALL)],
               bg=AMBER_LIGHT, border=AMBER_BORDER, left_accent=AMBER)

def info_box(text):
    return box([Paragraph(text, SMALL)],
               bg=BLUE_LIGHT, border=BLUE, left_accent=BLUE)

def grid(rows, col_widths=None, header=True):
    cw = col_widths or [CW / len(rows[0])] * len(rows[0])
    data = [[Paragraph(str(c), LBL if (i==0 and header) else SMALL)
             for c in row] for i, row in enumerate(rows)]
    style = [
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LINEBELOW",     (0,0), (-1,-1), 0.4, BORDER),
    ]
    if header:
        style += [
            ("BACKGROUND",  (0,0), (-1,0),  LIGHT),
            ("LINEBELOW",   (0,0), (-1,0),  1,   ORANGE),
        ]
    t = Table(data, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t

def pw_row(field, value, note=""):
    rows = [[Paragraph(field, LBL), Paragraph(value, CODE), Paragraph(note, SMALL)]]
    t = Table(rows, colWidths=[4*cm, 6*cm, CW-10*cm])
    t.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LINEBELOW",     (0,0), (-1,-1), 0.4, BORDER),
        ("BACKGROUND",    (1,0), (1,-1),  colors.HexColor("#fff3e0")),
    ]))
    return t

# ── Document ─────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2.2*cm, bottomMargin=2*cm,
    title="BootHop Pipeline Master Reference",
    author="BootHop"
)
story = []

# ═══════════════════════════════════════════════════════════════
#  COVER
# ═══════════════════════════════════════════════════════════════
story.append(Spacer(1, 1.2*cm))
story.append(Paragraph("BootHop Pipeline", TITLE))
story.append(Paragraph("Master Reference — Passwords, URLs & How It All Works",
    s("ST2", fontSize=13, textColor=colors.HexColor("#444466"),
      fontName="Helvetica", leading=18, spaceAfter=6)))
story.append(Spacer(1, 0.2*cm))
story.append(section_rule())
story.append(Paragraph(
    "This document is your single reference for every login, every URL, "
    "and every part of how the BootHop Pipeline system runs. "
    "Keep it private — it contains admin credentials.",
    BODY))
story.append(Spacer(1, 0.3*cm))

# ═══════════════════════════════════════════════════════════════
#  SECTION 1 — WHAT IS THIS SYSTEM?
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("1. What Is This System?", H1))
story.append(rule())
story.append(Paragraph(
    "The BootHop Pipeline is an automated content system. It researches trending topics, "
    "writes video scripts, generates or sources video clips, adds branding and voice-over, "
    "and publishes to social media — all on a schedule, for multiple clients at once.",
    BODY))
story.append(Spacer(1, 0.15*cm))
story.append(Paragraph(
    "The system runs on an Oracle Cloud server (always on) and is managed through "
    "a web dashboard at <b>boothop.com</b>. You control it from any browser. "
    "Each client gets their own pipeline, schedule, and login.",
    BODY))
story.append(Spacer(1, 0.3*cm))

story.append(grid([
    ["Part",            "What it does",                             "Where it runs"],
    ["Oracle Server",   "Hosts the app, runs the pipeline jobs",    "140.238.73.32 (always on)"],
    ["Dashboard App",   "Web UI for you and your clients",          "boothop.com (port 8000)"],
    ["SQLite Database", "Stores all client data and bake history",  "Server: /opt/otb_pipeline/dashboard/otb.db"],
    ["GitHub Repo",     "Source of truth — server pulls every 5min","github.com/Daddyoba12/OTBPipeline"],
    ["cron.org",        "Fires the pipeline at scheduled times",    "External service — manual setup"],
    ["Telegram Bot",    "Notifications for you and clients",        "@BoothHopBot"],
    ["Supabase",        "Cloud video storage and sync",             "zwgngbzbdvnrdnanjded.supabase.co"],
], col_widths=[3.5*cm, 6.5*cm, CW-10*cm]))

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 2 — LOGINS AND PASSWORDS (MASTER TABLE)
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("2. Every Login, URL and Password", H1))
story.append(rule())
story.append(Paragraph(
    "There are four types of login in the system. Each has its own URL and purpose. "
    "Do not share the admin password with clients.",
    BODY))
story.append(Spacer(1, 0.25*cm))

# 2a — Pipeline Super User (Admin)
story.append(Paragraph("2a.  Pipeline Super User  (You)", H2))
story.append(Paragraph(
    "This is your master control panel. From here you can see all clients, "
    "check intake applications, set API credentials, manage schedules, and activate pipelines.",
    BODY))
story.append(Spacer(1, 0.1*cm))
story.append(pw_row("Login URL",    "boothop.com/admin/login",  "Go here in any browser"))
story.append(pw_row("Password",     "otb-admin-2026",           "Default — change this immediately via Change Admin Password at the bottom of the admin page"))
story.append(Spacer(1, 0.3*cm))
story.append(tip_box(
    "To change the admin password: log in → scroll to the bottom of the admin page → "
    "Change Admin Password form. The new password is stored securely in the database."
))

# 2b — Pipeline Clients
story.append(Spacer(1, 0.25*cm))
story.append(Paragraph("2b.  Pipeline Clients  (Your Customers)", H2))
story.append(Paragraph(
    "Each client has their own Company ID and password. They log in at the same URL "
    "but see only their own pipeline, bakes, and settings.",
    BODY))
story.append(Spacer(1, 0.1*cm))
story.append(pw_row("Login URL", "boothop.com/pipeline-login", "Same for all clients"))
story.append(Spacer(1, 0.2*cm))

story.append(grid([
    ["Client",              "Company ID",    "Temp Password",          "Timezone"],
    ["BootHop",             "boothop",       "boothop-pipeline-2026",  "Europe/London"],
    ["G-Inspired Automall", "g-inspired",    "ginspired-2026",         "America/Chicago"],
    ["D818 Catering",       "d818",          "d818-pipeline-2026",     "Europe/London"],
], col_widths=[4.5*cm, 3.5*cm, 5*cm, CW-13*cm]))
story.append(Spacer(1, 0.15*cm))
story.append(warning_box(
    "These are temporary passwords. Ask each client to change their password "
    "immediately after first login using Settings → Change Password in their dashboard. "
    "You can also reset any client's password from the admin portal: "
    "admin panel → click the client → Profile tab → Reset Password."
))

# 2c — Client self-service
story.append(Spacer(1, 0.25*cm))
story.append(Paragraph("2c.  Forgotten Password (Self-Service)", H2))
story.append(Paragraph(
    "Clients who forget their password do not need to call you. They can reset it themselves:",
    BODY))
story.append(Spacer(1, 0.1*cm))
story.append(pw_row("Forgot Password Page", "boothop.com/forgot-password", "Public — no login needed"))
story.append(Spacer(1, 0.1*cm))
story.append(info_box(
    "The client enters their Company ID and registered email. "
    "A secure reset link is sent to their Telegram (and always also to you as backup). "
    "The link expires after 1 hour. Once they click it, they set a new password directly."
))

# 2d — New client intake
story.append(Spacer(1, 0.25*cm))
story.append(Paragraph("2d.  New Client Intake Form", H2))
story.append(Paragraph(
    "When a new business wants to join the pipeline, send them this link. "
    "It collects everything needed to set up their pipeline — no login required.",
    BODY))
story.append(Spacer(1, 0.1*cm))
story.append(pw_row("Intake Form",       "boothop.com/get-started",         "Public — share freely"))
story.append(pw_row("Client Onboarding", "boothop.com/client-onboarding",   "Admin-only wizard (no auth needed but keep internal)"))

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 3 — HOW THE PIPELINE WORKS
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("3. How the Pipeline Works — Step by Step", H1))
story.append(rule())
story.append(Paragraph(
    "Each time a scheduled slot fires, the pipeline runs through six stages automatically. "
    "This happens for each client on their own schedule.",
    BODY))
story.append(Spacer(1, 0.2*cm))

steps = [
    ("Stage 1", "Topic Research",
     "The pipeline searches for trending topics relevant to the client's industry, "
     "location, and target audience. It pulls live data from news feeds and search trends."),
    ("Stage 2", "Script Generation",
     "An AI writes a short video script — hook, main content, call to action — "
     "in the client's brand voice and tone."),
    ("Stage 3", "Video Assembly",
     "Background video clips are sourced (from the client's own library first, "
     "then Pexels/Pixabay as fallback). The script is laid over the clip with "
     "branded text and transitions."),
    ("Stage 4", "Voice-Over",
     "A text-to-speech voice reads the script. The client can re-voice any video "
     "from their dashboard if they want a different tone or wording."),
    ("Stage 5", "Publishing",
     "The finished video is posted to the client's enabled platforms: "
     "TikTok, Instagram Reels, YouTube Shorts, LinkedIn, or Facebook."),
    ("Stage 6", "Notification",
     "A Telegram message is sent to the client showing the hook line and "
     "which platforms the video was posted to. A daily digest email is also "
     "sent if the client opted in."),
]
for stage, title, desc in steps:
    story.append(KeepTogether([
        Paragraph(f"<b>{stage}: {title}</b>", BOLD),
        Paragraph(desc, SMALL),
        Spacer(1, 0.1*cm),
    ]))

story.append(Spacer(1, 0.2*cm))
story.append(tip_box(
    "Nothing in stages 1–5 requires any action from you or the client. "
    "The whole process is fully automatic once the schedule is set up in cron.org."
))

# ═══════════════════════════════════════════════════════════════
#  SECTION 4 — CLIENT TIMEZONES AND SCHEDULES
# ═══════════════════════════════════════════════════════════════
story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("4. Client Schedules and Timezones", H1))
story.append(rule())
story.append(Paragraph(
    "Each client posts on their own local timezone. The admin portal converts "
    "local times to UTC automatically when you set up a schedule — "
    "because cron.org, which triggers the pipeline, always runs in UTC.",
    BODY))
story.append(Spacer(1, 0.2*cm))

story.append(grid([
    ["Client",              "Timezone",          "Current Slots (local)",      "UTC equivalent (approx)"],
    ["BootHop",             "Europe/London",      "08:00 / 14:00 / 21:00",     "08:00 / 14:00 / 21:00 (GMT) or +1hr BST"],
    ["G-Inspired Automall", "America/Chicago",    "09:00 / 13:00 / 18:00",     "14:00 / 18:00 / 23:00 (CDT) or +1hr CST"],
    ["D818 Catering",       "Europe/London",      "09:00 / 13:00 / 18:00",     "09:00 / 13:00 / 18:00 (GMT) or +1hr BST"],
], col_widths=[4*cm, 3.5*cm, 5*cm, CW-12.5*cm]))

story.append(Spacer(1, 0.2*cm))
story.append(warning_box(
    "UK clocks change in late March (GMT → BST, clocks go forward 1 hour) "
    "and late October (BST → GMT, clocks go back). "
    "US Central clocks change in March and November. "
    "When this happens, update the affected cron.org jobs by 1 hour — "
    "otherwise posts will fire an hour early or late."
))
story.append(Spacer(1, 0.2*cm))
story.append(Paragraph(
    "To update or view a client's schedule: log in as admin → click the client → "
    "Schedule tab. The page auto-calculates the correct UTC cron expression "
    "with local-to-UTC chips showing the conversion for each slot. "
    "Copy the expression and paste it into cron.org.",
    BODY))

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 5 — CRON.ORG SETUP
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("5. Setting Up Schedules in cron.org", H1))
story.append(rule())
story.append(Paragraph(
    "cron.org is the external service that fires your pipeline at the right time. "
    "It sends an HTTP request to your server at each scheduled slot. "
    "You set it up once per client and only need to touch it when schedules change.",
    BODY))
story.append(Spacer(1, 0.2*cm))

cron_steps = [
    ("1", "Generate the cron expression",
     "Open boothop.com/admin/login → click the client → Schedule tab. "
     "Set the slot times (in the client's local time) and active days. "
     "The page immediately shows you the UTC cron expression and a local→UTC chip for each slot. "
     "Click 'Copy All'."),
    ("2", "Log into cron.org",
     "Go to cron.org and sign in with the BootHop account. Click 'Add Job'."),
    ("3", "Create one job per active slot",
     "Paste the cron expression into the Schedule field. "
     "Each active slot is a separate job. "
     "Name them clearly: 'G-Inspired Slot 1 — 09:00 CT' for example."),
    ("4", "Set the webhook URL",
     "URL format: https://boothop.com/api/run-pipeline/{client-slug}\n"
     "Method: POST\n"
     "Header: X-Pipeline-Secret: {your pipeline secret from keys.env}"),
    ("5", "Save and run a test",
     "Click Save, then 'Run Now' to trigger a test bake. "
     "Open the admin portal → click the client → Bakes tab. "
     "A new bake should appear within 30 seconds."),
]
data = [[
    Paragraph(num, s(f"n{i}", fontSize=13, textColor=ORANGE, fontName="Helvetica-Bold",
                     alignment=TA_CENTER)),
    [Paragraph(title, BOLD), Paragraph(desc, SMALL)]
] for i, (num, title, desc) in enumerate(cron_steps)]
t = Table(data, colWidths=[1.1*cm, CW-1.1*cm])
t.setStyle(TableStyle([
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("TOPPADDING",    (0,0), (-1,-1), 7),
    ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ("LINEBELOW",     (0,0), (-1,-2), 0.4, BORDER),
]))
story.append(t)
story.append(Spacer(1, 0.2*cm))

story.append(Paragraph("Common cron expressions:", H2))
story.append(grid([
    ["What you want",          "Cron expression (UTC)"],
    ["09:00 London time (GMT)", "0 9 * * *"],
    ["09:00 London time (BST)", "0 8 * * *   ← 1 hour earlier in UTC during BST"],
    ["09:00 Chicago time (CST)","0 15 * * *"],
    ["09:00 Chicago time (CDT)","0 14 * * *   ← 1 hour earlier in UTC during CDT"],
    ["Mon–Fri only",            "0 9 * * 1-5"],
    ["Mon, Wed, Fri only",      "0 9 * * 1,3,5"],
    ["Every day",               "0 9 * * *"],
], col_widths=[7*cm, CW-7*cm]))

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 6 — ONBOARDING A NEW CLIENT
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("6. Onboarding a New Client", H1))
story.append(rule())
story.append(Paragraph(
    "There are two ways to add a new client: they fill in the intake form themselves, "
    "or you create them manually in the admin portal.",
    BODY))
story.append(Spacer(1, 0.2*cm))

story.append(Paragraph("Option A — Client fills the intake form (recommended)", H2))
onboard_a = [
    ("1", "Share the intake URL with the client", "boothop.com/get-started"),
    ("2", "You receive a Telegram notification",  "Tells you the company name, email, and selected platforms"),
    ("3", "Book an onboarding call",              "Collect API credentials (TikTok, Instagram, YouTube keys etc.)"),
    ("4", "Fill Stage 2 credentials",             "Admin portal → client → Credentials tab → save"),
    ("5", "Set the schedule",                     "Admin portal → client → Schedule tab → generate cron expression → set up in cron.org"),
    ("6", "Click Activate Pipeline",              "Admin portal → client → Activate button. Client receives a Telegram with their schedule."),
]
data2 = [[Paragraph(n, s(f"x{i}", fontSize=10, textColor=ORANGE, fontName="Helvetica-Bold",
                          alignment=TA_CENTER)),
          [Paragraph(t, BOLD), Paragraph(d, SMALL)]]
         for i, (n, t, d) in enumerate(onboard_a)]
t2 = Table(data2, colWidths=[0.8*cm, CW-0.8*cm])
t2.setStyle(TableStyle([
    ("VALIGN",       (0,0),(-1,-1),"TOP"),
    ("LEFTPADDING",  (0,0),(-1,-1), 6),
    ("RIGHTPADDING", (0,0),(-1,-1), 6),
    ("TOPPADDING",   (0,0),(-1,-1), 6),
    ("BOTTOMPADDING",(0,0),(-1,-1), 6),
    ("LINEBELOW",    (0,0),(-1,-2), 0.4, BORDER),
]))
story.append(t2)
story.append(Spacer(1, 0.2*cm))

story.append(Paragraph("Option B — You create them manually", H2))
story.append(Paragraph(
    "Log into the admin portal → scroll to 'Add Company Manually' → fill in the form. "
    "The client is created immediately and can log in right away. "
    "You will still need to fill in the Credentials and Schedule tabs for them.",
    BODY))

story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("Client intake status flow:", H2))
story.append(grid([
    ["Status",    "Meaning",                        "What to do next"],
    ["submitted", "Client filled the intake form",  "Review, book onboarding call, fill Stage 2 credentials"],
    ["stage2",    "Credentials saved",              "Set the schedule in Schedule tab, then activate"],
    ["active",    "Pipeline is live and posting",   "Nothing — it runs automatically"],
    ["paused",    "Pipeline temporarily stopped",   "Click Activate to resume, update cron.org if needed"],
], col_widths=[2.5*cm, 5.5*cm, CW-8*cm]))

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 7 — THE ADMIN PORTAL IN DETAIL
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("7. The Admin Portal", H1))
story.append(rule())
story.append(Paragraph(
    "Everything you need to manage clients is at boothop.com/admin/login. "
    "Here is what each section does.",
    BODY))
story.append(Spacer(1, 0.2*cm))

story.append(Paragraph("Admin Overview Page", H2))
story.append(grid([
    ["Section",           "What it shows / does"],
    ["Stats row",         "Total clients, total bakes, active today, number of pending intake applications"],
    ["Intake Queue",      "Highlighted in amber when clients are waiting. Shows name, email, platforms, submitted date. Click 'Set Up' to go to their profile."],
    ["All Companies",     "Full list of every client with status, plan, bake count, last active date"],
    ["Add Company",       "Manually create a new company without them filling the intake form"],
    ["Change Admin Password", "Update the super user password directly from this page"],
], col_widths=[4.5*cm, CW-4.5*cm]))

story.append(Spacer(1, 0.2*cm))
story.append(Paragraph("Company Detail Page Tabs", H2))
story.append(grid([
    ["Tab",          "What you can do"],
    ["Profile",      "View business info, social handles, contact details. Reset the client's password."],
    ["Schedule",     "Set slot times in the client's timezone, choose active days, copy the UTC cron expression for cron.org."],
    ["Credentials",  "Enter API keys for TikTok, Instagram, YouTube, LinkedIn, Pexels, Pixabay after the onboarding call."],
    ["Bakes",        "Full history of every video generated — hook text, platforms, timestamp, status."],
    ["Danger",       "Permanently delete the company and all its data. Cannot be undone."],
], col_widths=[2.8*cm, CW-2.8*cm]))

# ═══════════════════════════════════════════════════════════════
#  SECTION 8 — TELEGRAM NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════
story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("8. Telegram Notifications", H1))
story.append(rule())
story.append(Paragraph(
    "The pipeline communicates through Telegram. Both you and your clients "
    "receive messages at key moments.",
    BODY))
story.append(Spacer(1, 0.2*cm))
story.append(Paragraph("Notifications you (admin) receive:", H2))
story.append(grid([
    ["Event",                   "What the message says"],
    ["New intake submitted",    "Company name, contact email, selected platforms — sent the moment a client submits the intake form"],
    ["Password reset requested","Company ID and a reset link — so you have a backup if the client can't access their Telegram"],
    ["Pipeline error",          "Company slug and error summary when a bake job fails"],
], col_widths=[5*cm, CW-5*cm]))
story.append(Spacer(1, 0.1*cm))
story.append(Paragraph("Notifications clients receive:", H2))
story.append(grid([
    ["Event",               "What the message says"],
    ["Pipeline activated",  "Welcome message with their full schedule (slot times, days, timezone) and login URL"],
    ["Video published",     "Hook text and list of platforms the video was posted to"],
    ["Password reset link", "Secure link to set a new password (valid 1 hour)"],
], col_widths=[4*cm, CW-4*cm]))

story.append(Spacer(1, 0.2*cm))
story.append(info_box(
    "<b>Client Telegram Chat ID:</b>  Clients find their Chat ID by opening Telegram "
    "and messaging @userinfobot. It replies with a number like 8641867751. "
    "This number goes in the 'Telegram Chat ID' field during onboarding. "
    "Without it, the client will not receive any Telegram notifications."
))

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 9 — API CREDENTIALS GUIDE
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("9. API Credentials — Where to Get Them", H1))
story.append(rule())
story.append(Paragraph(
    "After the onboarding call, you fill in the client's social media API keys "
    "in the Credentials tab. Here is where each key comes from.",
    BODY))
story.append(Spacer(1, 0.15*cm))

cred_guide = [
    ("TikTok",
     "TikTok Session ID",
     "Client logs into TikTok in a browser → F12 → Application → Cookies → tiktok.com → copy the 'sessionid' value."),
    ("TikTok",
     "Client Key & Secret",
     "Developer Portal at developer.tiktok.com → Your App → Keys & tokens."),
    ("Instagram",
     "App ID & App Secret",
     "Meta Developer Portal (developers.facebook.com) → Your App → Settings → Basic."),
    ("Instagram",
     "Access Token",
     "Long-lived token from the Graph API. Use the Token Debugger at developers.facebook.com/tools/debug/accesstoken."),
    ("Instagram",
     "User ID",
     "Numeric Instagram user ID — visible in the Graph API explorer or via the API: GET /me?fields=id."),
    ("YouTube",
     "API Key",
     "Google Cloud Console → Your Project → Credentials → Create API Key. Enable the YouTube Data API v3."),
    ("YouTube",
     "Channel ID",
     "YouTube Studio → Settings → Advanced Settings → Channel ID (starts with UC...)."),
    ("YouTube",
     "Refresh Token",
     "OAuth 2.0 flow with youtube.upload scope. Use Google OAuth Playground (developers.google.com/oauthplayground)."),
    ("LinkedIn",
     "Client ID & Secret",
     "LinkedIn Developer Portal (developer.linkedin.com) → Your App → Auth tab."),
    ("LinkedIn",
     "Access Token",
     "3-legged OAuth with w_member_social scope. Use the LinkedIn token generator in the app settings."),
    ("Pexels",
     "API Key",
     "Free account at pexels.com/api — key is generated immediately. Limit: 200 requests/hour."),
    ("Pixabay",
     "API Key",
     "Free account at pixabay.com/api/docs — key is on your account page. Limit: 100 requests/minute."),
]
cred_data = [
    [Paragraph(p, LBL), Paragraph(k, BOLD), Paragraph(d, SMALL)]
    for p, k, d in cred_guide
]
ct = Table(cred_data, colWidths=[2.5*cm, 4*cm, CW-6.5*cm])
ct.setStyle(TableStyle([
    ("VALIGN",       (0,0),(-1,-1),"TOP"),
    ("LEFTPADDING",  (0,0),(-1,-1), 8),
    ("RIGHTPADDING", (0,0),(-1,-1), 6),
    ("TOPPADDING",   (0,0),(-1,-1), 6),
    ("BOTTOMPADDING",(0,0),(-1,-1), 6),
    ("LINEBELOW",    (0,0),(-1,-1), 0.4, BORDER),
    ("BACKGROUND",   (0,0), (0,-1), LIGHT),
]))
story.append(ct)

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 10 — PASSWORD MANAGEMENT
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("10. Password Management", H1))
story.append(rule())
story.append(Paragraph(
    "The system has three ways to manage passwords. "
    "Use whichever is appropriate for the situation.",
    BODY))
story.append(Spacer(1, 0.2*cm))

story.append(Paragraph("Admin password — change it yourself", H2))
story.append(Paragraph(
    "Log in as admin → scroll to the bottom of the admin overview page → "
    "Change Admin Password form → enter current and new password → submit. "
    "Takes effect immediately. The new password is saved in the database.",
    BODY))

story.append(Paragraph("Client password — reset it from the admin portal", H2))
story.append(Paragraph(
    "Admin portal → click the client → Profile tab → Reset Password section → "
    "enter a new password → Save. You then give the client their new password "
    "directly (via Telegram or WhatsApp).",
    BODY))

story.append(Paragraph("Client forgot password — self-service reset", H2))
story.append(Paragraph(
    "The client goes to boothop.com/forgot-password, enters their Company ID and email. "
    "A reset link is sent to their Telegram. They click the link, enter a new password, "
    "and can log in immediately. The link expires after 1 hour.",
    BODY))
story.append(Spacer(1, 0.1*cm))
story.append(info_box(
    "As admin, you always receive a copy of reset links on Telegram. "
    "So if a client's Telegram is not working, you can forward the link to them manually."
))

story.append(Paragraph("Client changes their own password", H2))
story.append(Paragraph(
    "When logged into their dashboard, clients can change their password anytime: "
    "Settings tab → Change Password → enter current password, new password, confirm → Update.",
    BODY))

story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
#  SECTION 11 — SERVER AND DEPLOYMENT
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("11. Server and Deployment", H1))
story.append(rule())
story.append(Paragraph(
    "The system runs on an Oracle Cloud always-free server. "
    "Code changes pushed to GitHub appear on the server within 5 minutes automatically.",
    BODY))
story.append(Spacer(1, 0.15*cm))

story.append(grid([
    ["Item",             "Detail"],
    ["Server IP",        "140.238.73.32"],
    ["SSH key",          "~/.ssh/oracle_boothop.pem  (on your laptop)"],
    ["SSH command",      "ssh -i ~/.ssh/oracle_boothop.pem ubuntu@140.238.73.32"],
    ["App directory",    "/opt/otb_pipeline"],
    ["Database",         "/opt/otb_pipeline/dashboard/otb.db"],
    ["API keys file",    "/opt/otb_pipeline/keys.env  (never committed to GitHub)"],
    ["Restart app",      "sudo systemctl restart otb-pipeline"],
    ["View live logs",   "sudo journalctl -u otb-pipeline -f"],
    ["GitHub sync",      "Automatic every 5 minutes — push to main branch to deploy"],
], col_widths=[3.8*cm, CW-3.8*cm]))

story.append(Spacer(1, 0.25*cm))
story.append(warning_box(
    "keys.env is not on GitHub — it lives only on the server. "
    "If you add a new API key, you must SSH into the server and update keys.env manually, "
    "then restart the app. Never add keys.env to the git repository."
))

# ═══════════════════════════════════════════════════════════════
#  SECTION 12 — TROUBLESHOOTING
# ═══════════════════════════════════════════════════════════════
story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("12. Troubleshooting", H1))
story.append(rule())

problems = [
    ("Client cannot log in",
     "Check their intake_status is 'active' in the admin portal. "
     "Check the Company ID is correct (lowercase, hyphens). "
     "Reset their password via Profile tab → Reset Password."),
    ("Pipeline is not posting",
     "Check cron.org — is the job enabled and is it hitting the right URL? "
     "Check the Bakes tab — is a new bake showing at all? "
     "Check the server logs: sudo journalctl -u otb-pipeline -f"),
    ("Bake shows 'failed'",
     "Open the Bakes tab for the client and click the failed row. "
     "Common causes: expired API token (update in Credentials tab), "
     "platform rate limit (will retry next slot), video too large (platform limit)."),
    ("Client not getting Telegram messages",
     "Confirm their tg_chat_id is set in their Profile tab. "
     "Ask them to message @userinfobot to confirm their Chat ID. "
     "Make sure they have not blocked the bot."),
    ("Wrong posting time — posts 1 hour off",
     "Clocks have changed (DST). Update the cron.org UTC time by 1 hour for affected clients. "
     "UK clients: update in March (forward) and October (back). "
     "US clients: update in March and November."),
    ("Server not responding",
     "SSH in and run: sudo systemctl status otb-pipeline. "
     "If stopped: sudo systemctl start otb-pipeline. "
     "If out of memory: sudo reboot (data is safe)."),
    ("Forgot admin password",
     "The default password is otb-admin-2026. "
     "If you changed it and forgot it, SSH into the server and run: "
     "python3 -c \"import sqlite3; c=sqlite3.connect('dashboard/otb.db'); "
     "c.execute(\\\"UPDATE companies SET password_h='' WHERE id=-1\\\"); c.commit()\" "
     "from /opt/otb_pipeline. This clears the DB-stored hash so the default is used again."),
]
for prob, sol in problems:
    story.append(KeepTogether([
        Paragraph(prob, BOLD),
        Paragraph(sol, SMALL),
        Spacer(1, 0.12*cm),
    ]))

# ═══════════════════════════════════════════════════════════════
#  FOOTER
# ═══════════════════════════════════════════════════════════════
story.append(Spacer(1, 0.5*cm))
story.append(rule())
story.append(Paragraph(
    "BootHop Pipeline · boothop.com · Confidential — do not share",
    CENTRE))

# ── Build ─────────────────────────────────────────────────────
doc.build(story)
print(f"Created: {OUT}")
