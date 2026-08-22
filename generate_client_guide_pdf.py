"""
BootHop Pipeline — Client Guide PDF
Run: python generate_client_guide_pdf.py
Output: output/BootHop_Pipeline_Client_Guide.pdf
"""
import os
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER

os.makedirs("output", exist_ok=True)
OUT = "output/BootHop_Pipeline_Client_Guide.pdf"

# ── Colours ───────────────────────────────────────────────────
ORANGE  = colors.HexColor("#ff6b00")
AMBER   = colors.HexColor("#ffb800")
DARK    = colors.HexColor("#08080f")
CARD    = colors.HexColor("#121220")
MUTED   = colors.HexColor("#8888a8")
GREEN   = colors.HexColor("#00c853")
BLUE    = colors.HexColor("#5ba4e6")
WHITE   = colors.white
BORDER  = colors.HexColor("#2a2a3a")

# ── Styles ────────────────────────────────────────────────────
SS = getSampleStyleSheet()

def s(name, **kw):
    return ParagraphStyle(name, **kw)

H1  = s("H1",  fontSize=26, textColor=ORANGE,   fontName="Helvetica-Bold",
         spaceAfter=6, leading=32)
H2  = s("H2",  fontSize=16, textColor=WHITE,    fontName="Helvetica-Bold",
         spaceAfter=4, leading=22, spaceBefore=18)
H3  = s("H3",  fontSize=12, textColor=AMBER,    fontName="Helvetica-Bold",
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
          leading=10, spaceAfter=2, textTransform="uppercase")

W, H = A4

# ── Helpers ───────────────────────────────────────────────────
def rule():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=10)

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
    """rows = list of (step_num, title, description)"""
    data = []
    for num, title, desc in rows:
        data.append([
            Paragraph(str(num), s(f"sn{num}", fontSize=13, textColor=ORANGE,
                                  fontName="Helvetica-Bold", alignment=TA_CENTER)),
            [Paragraph(title, BOLD_BODY),
             Paragraph(desc, SMALL)]
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

def feature_row(rows):
    """rows = list of (icon_char, title, desc)"""
    data = [[
        Paragraph(icon, s(f"ic{i}", fontSize=14, alignment=TA_CENTER,
                          textColor=ORANGE, fontName="Helvetica-Bold")),
        [Paragraph(title, BOLD_BODY),
         Paragraph(desc, SMALL)]
    ] for i, (icon, title, desc) in enumerate(rows)]
    t = Table(data, colWidths=[1.2*cm, W - 5.2*cm])
    t.setStyle(TableStyle([
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING",(0,0), (-1,-1), 6),
        ("TOPPADDING",  (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LINEBELOW",   (0,0), (-1,-2), 0.3, BORDER),
    ]))
    return t

# ── Document ──────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2.2*cm, bottomMargin=2*cm,
    title="BootHop Pipeline — Client Guide",
    author="BootHop"
)

story = []

# ── Cover ─────────────────────────────────────────────────────
story.append(Spacer(1, 1.4*cm))
story.append(Paragraph("BootHop Pipeline", H1))
story.append(Paragraph("Client Guide", s("SH", fontSize=18, textColor=WHITE,
             fontName="Helvetica-Bold", spaceAfter=8, leading=24)))
story.append(Paragraph("Everything you need to know about your automated content pipeline.",
             BODY))
story.append(rule())
story.append(Spacer(1, 0.3*cm))

# ── 1. What is BootHop Pipeline? ──────────────────────────────
story.append(Paragraph("1. What is BootHop Pipeline?", H2))
story.append(Paragraph(
    "BootHop Pipeline is a fully managed content automation system. "
    "Once set up, it researches trending topics in your industry, writes scripts, "
    "generates or sources video clips, adds your branding and voice-over, "
    "and publishes to your social media channels — automatically, on a schedule you control.",
    BODY))
story.append(Spacer(1, 0.2*cm))
story.append(feature_row([
    ("→", "Zero daily effort",  "Your content goes out whether you're in a meeting or on holiday."),
    ("→", "Your brand, your voice", "Every video uses your tone, keywords, and visual style."),
    ("→", "Multi-platform",     "TikTok, Instagram Reels, YouTube Shorts, LinkedIn, and more."),
    ("→", "You stay in control", "Pause, preview, and re-voice any video before it goes live."),
]))
story.append(Spacer(1, 0.3*cm))

# ── 2. Getting Started ────────────────────────────────────────
story.append(Paragraph("2. Getting Started", H2))
story.append(Paragraph("Your pipeline goes live in three stages:", BODY))
story.append(Spacer(1, 0.15*cm))
story.append(step_table([
    (1, "Submit your intake form",
        "Go to boothop.com/get-started and fill in your business details, platforms, "
        "handles, and brand preferences. This takes about 10 minutes."),
    (2, "Onboarding call",
        "A BootHop team member will contact you to go through your content strategy, "
        "connect your platform accounts, and set your posting schedule."),
    (3, "Pipeline activated",
        "You will receive a Telegram message confirming your pipeline is live, "
        "including your schedule details. Your first video will run at the next scheduled slot."),
]))
story.append(Spacer(1, 0.3*cm))
story.append(tip_box(
    "Have your social media handles and account login details ready before the onboarding call. "
    "You do NOT need to share passwords — we use read/publish API tokens."
))

# ── 3. Logging In ────────────────────────────────────────────
story.append(Paragraph("3. Logging In", H2))
story.append(Paragraph(
    "Your client dashboard is at:", BODY))
story.append(Paragraph("boothop.com/pipeline-login", CODE))
story.append(Paragraph(
    "You will receive your Company ID and temporary password from the BootHop team "
    "after your pipeline is activated. Your Company ID is a short slug, for example: "
    "<font color='#ffb800' name='Courier'>acme-media</font>.", BODY))
story.append(Spacer(1, 0.15*cm))
story.append(info_box(
    "<b>Forgot your password?</b>  Contact the BootHop team and we will reset it for you. "
    "Password self-reset is coming soon."
))

# ── 4. Your Dashboard ────────────────────────────────────────
story.append(Paragraph("4. Your Dashboard", H2))
story.append(Paragraph(
    "Once logged in you will see four tabs:", BODY))
story.append(Spacer(1, 0.1*cm))
story.append(feature_row([
    ("1", "Pipeline",
        "Shows your last 30 video bakes. Each row shows the headline, platforms it was posted to, "
        "timestamp, and status (posted, pending, failed). Click any row to see the full script and hook."),
    ("2", "Revoice",
        "Pick any video from your recent bakes and re-record the voice-over with a different tone "
        "or update the on-screen text. Useful if a topic changes after a video is generated."),
    ("3", "Clients",
        "Manage your team members who also need access to this dashboard (Pro plan only)."),
    ("4", "How it Works",
        "A full explanation of each pipeline stage, from topic research to publishing — "
        "and answers to frequently asked questions."),
]))

# ── 5. Pipeline Control ───────────────────────────────────────
story.append(Paragraph("5. Pipeline Control", H2))
story.append(Paragraph(
    "The Pipeline tab shows every video your system has generated. "
    "Here is what each column means:", BODY))
story.append(Spacer(1, 0.1*cm))

col_data = [
    [Paragraph("Column", LABEL),    Paragraph("What it means", LABEL)],
    [Paragraph("Headline", SMALL),  Paragraph("The hook line that opens the video.", SMALL)],
    [Paragraph("Platforms", SMALL), Paragraph("Icons showing which platforms the video was posted to.", SMALL)],
    [Paragraph("Time", SMALL),      Paragraph("When the bake job ran.", SMALL)],
    [Paragraph("Status", SMALL),    Paragraph("Posted = published. Pending = in queue. Failed = see logs.", SMALL)],
    [Paragraph("Actions", SMALL),   Paragraph("Open the bake detail, or send to Revoice.", SMALL)],
]
ct = Table(col_data, colWidths=[3.5*cm, W - 7.5*cm])
ct.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1, 0), CARD),
    ("LINEBELOW",     (0,0), (-1, 0), 1,   BORDER),
    ("LINEBELOW",     (0,1), (-1,-1), 0.3, BORDER),
    ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ("TOPPADDING",    (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(ct)

# ── 6. Revoice Studio ────────────────────────────────────────
story.append(Paragraph("6. Revoice Studio", H2))
story.append(Paragraph(
    "Revoice lets you regenerate a video's audio track with a different voice, "
    "speed, or script — without rerunning the whole pipeline.", BODY))
story.append(Spacer(1, 0.1*cm))
story.append(step_table([
    (1, "Select a video", "Go to the Pipeline tab and click 'Revoice' on any row."),
    (2, "Edit the script", "Adjust the text that will be spoken. Keep it under 90 seconds of audio."),
    (3, "Choose a voice", "Pick from available voice options (tone: calm, energetic, authoritative)."),
    (4, "Regenerate",     "Click Revoice — the new audio is applied and the video is re-rendered. "
                          "The original is kept in your history."),
]))

# ── 7. Telegram Notifications ────────────────────────────────
story.append(Paragraph("7. Telegram Notifications", H2))
story.append(Paragraph(
    "Your pipeline sends you a Telegram message every time a video is generated. "
    "The message includes a preview of the hook line and the platforms it will be posted to.", BODY))
story.append(Spacer(1, 0.15*cm))
story.append(info_box(
    "<b>Setting up Telegram:</b>  Open Telegram and search for @userinfobot. "
    "Send it any message and it will reply with your Chat ID — a number like 8641867751. "
    "Share this number with the BootHop team during your onboarding call."
))
story.append(Spacer(1, 0.2*cm))
story.append(Paragraph("Notifications you will receive:", BODY))
story.append(feature_row([
    ("→", "Pipeline activated",   "Sent when your pipeline goes live for the first time."),
    ("→", "Video preview",        "Sent each time a slot runs — includes the hook text."),
    ("→", "Post confirmed",       "Sent when the video is successfully published to a platform."),
    ("→", "Error alert",          "Sent if a platform rejects the post so you can take action."),
]))

# ── 8. Stock Video and Pexels/Pixabay ───────────────────────
story.append(Paragraph("8. Background Video (Pexels / Pixabay)", H2))
story.append(Paragraph(
    "When your pipeline does not have a custom video clip to use as background, "
    "it searches Pexels and Pixabay — two free stock video libraries — for a relevant clip. "
    "This happens automatically.", BODY))
story.append(tip_box(
    "If you have your own branded video footage, the BootHop team can upload it to your "
    "clip library so the pipeline uses your clips first. Accepted formats: MP4, MOV. "
    "Minimum length: 5 seconds."
))
story.append(Spacer(1, 0.15*cm))
story.append(Paragraph(
    "You do not need a Pexels or Pixabay account — we provide the API access. "
    "All stock clips used are royalty-free for commercial use.", BODY))

# ── 9. Content Schedule ──────────────────────────────────────
story.append(Paragraph("9. Your Content Schedule", H2))
story.append(Paragraph(
    "Your pipeline runs on a fixed schedule set during onboarding. "
    "You can have up to four posting slots per active day:", BODY))
story.append(Spacer(1, 0.1*cm))
slot_data = [
    [Paragraph("Slot", LABEL), Paragraph("Typical time", LABEL), Paragraph("Best for", LABEL)],
    [Paragraph("Morning",   SMALL), Paragraph("07:00 – 09:00", SMALL), Paragraph("News hooks, daily tips", SMALL)],
    [Paragraph("Midday",    SMALL), Paragraph("12:00 – 13:00", SMALL), Paragraph("Trending topics", SMALL)],
    [Paragraph("Evening",   SMALL), Paragraph("18:00 – 20:00", SMALL), Paragraph("How-tos, opinion pieces", SMALL)],
    [Paragraph("Weekly",    SMALL), Paragraph("Monday 08:00",  SMALL), Paragraph("Weekly round-ups, reviews", SMALL)],
]
st = Table(slot_data, colWidths=[3*cm, 4*cm, W - 11*cm])
st.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1, 0), CARD),
    ("LINEBELOW",     (0,0), (-1, 0), 1,   BORDER),
    ("LINEBELOW",     (0,1), (-1,-1), 0.3, BORDER),
    ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ("TOPPADDING",    (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(st)
story.append(Spacer(1, 0.2*cm))
story.append(Paragraph(
    "To change your schedule, contact the BootHop team. "
    "We can pause, resume, or adjust posting days at any time.", BODY))

# ── 10. Daily Email Digest ───────────────────────────────────
story.append(Paragraph("10. Daily Email Digest", H2))
story.append(Paragraph(
    "If you opted in during sign-up, you will receive a daily (or weekly) email "
    "summarising every post sent in the last 24 hours, the platforms they reached, "
    "and what is scheduled for the next day.", BODY))
story.append(info_box(
    "To update your digest email address or frequency, contact the BootHop team. "
    "You can also opt out at any time."
))

# ── 11. FAQ ──────────────────────────────────────────────────
story.append(Paragraph("11. Frequently Asked Questions", H2))

faqs = [
    ("Can I approve videos before they go live?",
     "Not automatically — the pipeline is designed to be hands-free. However, "
     "you can use Revoice to edit any video after generation and before the next slot runs. "
     "Manual approval queues are on our roadmap."),
    ("What happens if a platform post fails?",
     "You will receive a Telegram alert. The pipeline will retry once automatically. "
     "If it fails again, the BootHop team is notified and will investigate."),
    ("Can I post to multiple platforms per slot?",
     "Yes — during onboarding you select which platforms each slot targets. "
     "A single bake can publish to TikTok, Instagram Reels, YouTube Shorts, and LinkedIn simultaneously."),
    ("How do you pick what topics to cover?",
     "The pipeline searches current trending topics in your industry and location. "
     "Your brand keywords, target audience, and content tone guide which topics are selected."),
    ("Will my competitors see the same content?",
     "No. Topics are combined with your unique brand voice, keywords, and visual style. "
     "No two pipelines produce the same output."),
    ("Can I upload my own video clips?",
     "Yes. Share MP4 or MOV files with the BootHop team and they will be added to your private clip library."),
    ("How do I pause the pipeline?",
     "Contact the BootHop team via Telegram or email and we will pause it immediately. "
     "Self-service pause is coming to the dashboard soon."),
    ("Is my social media login data safe?",
     "We never store your username or password. We use OAuth tokens issued by each platform, "
     "which can be revoked at any time from your platform's security settings."),
]
for q, a in faqs:
    story.append(KeepTogether([
        Paragraph(q, BOLD_BODY),
        Paragraph(a, SMALL),
        Spacer(1, 0.1*cm),
    ]))

# ── 12. Contact & Support ────────────────────────────────────
story.append(Paragraph("12. Contact & Support", H2))
story.append(feature_row([
    ("@", "Telegram",  "Fastest response — message the BootHop admin directly on Telegram."),
    ("✉", "Email",     "support@boothop.com — for non-urgent queries and billing questions."),
    ("⊕", "Dashboard", "Use the 'How it Works' tab for self-serve answers."),
]))
story.append(Spacer(1, 0.4*cm))
story.append(rule())
story.append(Paragraph(
    "BootHop Pipeline · boothop.com · support@boothop.com",
    CENTRE))
story.append(Paragraph(
    "This document is confidential and intended for BootHop Pipeline clients only.",
    s("FT", fontSize=7.5, textColor=MUTED, fontName="Helvetica",
      alignment=TA_CENTER, leading=11)))

# ── Build ─────────────────────────────────────────────────────
doc.build(story)
print(f"Created: {OUT}")
