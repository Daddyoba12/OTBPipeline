"""
Generate OTB Pipeline Overview PDF using ReportLab.
Run: python generate_pipeline_pdf.py
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from pathlib import Path
from datetime import date

OUT = Path(r"C:\Users\babso\Desktop\OTB_Pipeline\output\OTB_Pipeline_Overview.pdf")
OUT.parent.mkdir(exist_ok=True)

# ── Colours ───────────────────────────────────────────────────────────────────
INDIGO     = colors.HexColor("#4F46E5")
INDIGO_LT  = colors.HexColor("#EEF2FF")
SLATE      = colors.HexColor("#1E293B")
SLATE_MID  = colors.HexColor("#475569")
SLATE_LT   = colors.HexColor("#F1F5F9")
WHITE      = colors.white
TEAL       = colors.HexColor("#0F766E")
TEAL_LT    = colors.HexColor("#CCFBF1")
AMBER      = colors.HexColor("#D97706")
AMBER_LT   = colors.HexColor("#FEF3C7")
RED_LT     = colors.HexColor("#FEE2E2")
RED        = colors.HexColor("#DC2626")
GREEN      = colors.HexColor("#16A34A")
GREEN_LT   = colors.HexColor("#DCFCE7")

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def S(name, **kw):
    base = styles[name] if name in styles else styles["Normal"]
    return ParagraphStyle(name + str(id(kw)), parent=base, **kw)

H1   = S("Heading1", fontSize=22, textColor=WHITE,    leading=28, spaceAfter=0,  fontName="Helvetica-Bold")
H2   = S("Heading2", fontSize=13, textColor=INDIGO,   leading=18, spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold")
H3   = S("Heading3", fontSize=10, textColor=SLATE,    leading=14, spaceBefore=8,  spaceAfter=2, fontName="Helvetica-Bold")
BODY = S("Normal",   fontSize=9,  textColor=SLATE,    leading=13, spaceAfter=3,   fontName="Helvetica")
BODY_SM = S("Normal", fontSize=8, textColor=SLATE_MID, leading=12, spaceAfter=2,  fontName="Helvetica")
MONO = S("Normal",   fontSize=8,  textColor=INDIGO,   leading=12, spaceAfter=2,   fontName="Courier-Bold")
LABEL= S("Normal",   fontSize=7.5,textColor=WHITE,    leading=10, fontName="Helvetica-Bold")
NOTE = S("Normal",   fontSize=8,  textColor=AMBER,    leading=12, fontName="Helvetica-BoldOblique")
TH   = S("Normal",   fontSize=8,  textColor=WHITE,    leading=11, fontName="Helvetica-Bold", alignment=TA_LEFT)
TD   = S("Normal",   fontSize=8,  textColor=SLATE,    leading=11, fontName="Helvetica",      alignment=TA_LEFT)
TD_M = S("Normal",   fontSize=8,  textColor=SLATE_MID,leading=11, fontName="Helvetica-Oblique", alignment=TA_LEFT)
CAPTION = S("Normal",fontSize=7.5,textColor=SLATE_MID,leading=11, fontName="Helvetica-Oblique")

def p(text, style=BODY): return Paragraph(text, style)
def sp(h=6):             return Spacer(1, h)
def hr():                return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=6, spaceBefore=6)

def badge(text, bg=INDIGO, fg=WHITE):
    tbl = Table([[Paragraph(text, ParagraphStyle("b", fontSize=7, textColor=fg,
                  fontName="Helvetica-Bold", leading=9))]], colWidths=[None])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), bg),
        ("ROUNDEDCORNERS", [4]),
        ("TOPPADDING",(0,0),(-1,-1),3),
        ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),6),
        ("RIGHTPADDING",(0,0),(-1,-1),6),
    ]))
    return tbl

def section_header(title, subtitle=""):
    inner = [[Paragraph(title, H1)]]
    if subtitle:
        inner.append([Paragraph(subtitle, ParagraphStyle("sh", fontSize=9, textColor=colors.HexColor("#C7D2FE"),
                       fontName="Helvetica-Oblique", leading=13))])
    tbl = Table(inner, colWidths=[17*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), INDIGO),
        ("TOPPADDING",(0,0),(-1,-1),14),
        ("BOTTOMPADDING",(0,0),(-1,-1),14),
        ("LEFTPADDING",(0,0),(-1,-1),16),
        ("RIGHTPADDING",(0,0),(-1,-1),16),
        ("ROUNDEDCORNERS",[6]),
    ]))
    return tbl

def info_box(rows, col_widths, row_colors=None, header=True):
    tbl_data = []
    for r in rows:
        tbl_data.append([Paragraph(str(c), TH if (header and rows.index(r)==0) else TD) for c in r])
    tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1 if header else 0)
    cmds = [
        ("GRID",    (0,0),(-1,-1), 0.4, colors.HexColor("#E2E8F0")),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),7),
        ("RIGHTPADDING",(0,0),(-1,-1),7),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]
    if header:
        cmds += [("BACKGROUND",(0,0),(-1,0), SLATE), ("TEXTCOLOR",(0,0),(-1,0), WHITE)]
    if row_colors:
        for i, col in row_colors.items():
            cmds.append(("BACKGROUND",(0,i),(-1,i), col))
    else:
        for i in range(1 if header else 0, len(tbl_data)):
            if i % 2 == 0:
                cmds.append(("BACKGROUND",(0,i),(-1,i), SLATE_LT))
    tbl.setStyle(TableStyle(cmds))
    return tbl

def flow_box(stages):
    """Numbered stage flow table."""
    rows = []
    for num, title, desc in stages:
        rows.append([
            Paragraph(str(num), ParagraphStyle("n", fontSize=10, textColor=WHITE,
                       fontName="Helvetica-Bold", alignment=TA_CENTER, leading=12)),
            Paragraph(f"<b>{title}</b>", ParagraphStyle("t", fontSize=8.5, textColor=SLATE,
                       fontName="Helvetica-Bold", leading=12)),
            Paragraph(desc, BODY_SM),
        ])
    tbl = Table(rows, colWidths=[1.1*cm, 4.2*cm, 11.7*cm])
    cmds = [
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1),7),
        ("RIGHTPADDING",(0,0),(-1,-1),7),
        ("LINEBELOW",(0,0),(-1,-2), 0.4, colors.HexColor("#E2E8F0")),
    ]
    for i, (num, _, _) in enumerate(stages):
        bg = INDIGO if i % 2 == 0 else TEAL
        cmds.append(("BACKGROUND",(0,i),(0,i), bg))
        cmds.append(("ROWBACKGROUNDS",(1,i),(-1,i), [SLATE_LT if i%2==0 else WHITE]))
    tbl.setStyle(TableStyle(cmds))
    return tbl

# ── Document ──────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    str(OUT),
    pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm,  bottomMargin=2*cm,
    title="OTB Pipeline — Complete Overview",
    author="BootHop",
)

story = []

# ═══════════════════════════════════════════════════════════════════════════════
# COVER
# ═══════════════════════════════════════════════════════════════════════════════
story.append(sp(20))
story.append(section_header(
    "OTB Pipeline — Complete Overview",
    f"BootHop Content Automation System  •  Generated {date.today().strftime('%d %b %Y')}"
))
story.append(sp(10))
story.append(p(
    "This document maps every program in the OTB Pipeline — what each does, when it runs, "
    "what it produces, and where it connects to the rest of the system. "
    "Observations from the output files are included at the end with specific optimisation recommendations.",
    BODY
))
story.append(sp(6))

# Quick stats row
stats = Table([[
    Table([[p("4", ParagraphStyle("big", fontSize=22, textColor=INDIGO, fontName="Helvetica-Bold", leading=24, alignment=TA_CENTER))],
           [p("Daily Slots", CAPTION)]], colWidths=[4*cm]),
    Table([[p("9", ParagraphStyle("big", fontSize=22, textColor=TEAL, fontName="Helvetica-Bold", leading=24, alignment=TA_CENTER))],
           [p("Pipeline Stages", CAPTION)]], colWidths=[4*cm]),
    Table([[p("5", ParagraphStyle("big", fontSize=22, textColor=AMBER, fontName="Helvetica-Bold", leading=24, alignment=TA_CENTER))],
           [p("Story Beats × 3s", CAPTION)]], colWidths=[4*cm]),
    Table([[p("25s", ParagraphStyle("big", fontSize=22, textColor=RED, fontName="Helvetica-Bold", leading=24, alignment=TA_CENTER))],
           [p("Final Video", CAPTION)]], colWidths=[4*cm]),
]], colWidths=[4.25*cm]*4)
stats.setStyle(TableStyle([
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("ALIGN",(0,0),(-1,-1),"CENTER"),
    ("TOPPADDING",(0,0),(-1,-1),10),
    ("BOTTOMPADDING",(0,0),(-1,-1),10),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("BACKGROUND",(0,0),(-1,-1),SLATE_LT),
]))
story.append(stats)
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — COMPLETE RUN SCHEDULE
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("COMPLETE RUN SCHEDULE", H2))
story.append(hr())
story.append(p(
    "Every program in the pipeline, when it runs, how often, which days, which machine, and what triggers it. "
    "All times are UK (Europe/London). Oracle fires 1 hour after the laptop as a failsafe and skips if the laptop already ran.",
    BODY
))
story.append(sp(8))

# ── Daily automated runs ──────────────────────────────────────────────────────
story.append(p("Daily Automated Runs", H3))

daily_rows = [
    ["Time (UK)", "Script", "Days", "Machine", "Trigger", "What it produces"],
    ["06:30", "post_newsflash.py",         "Every day",  "Laptop + Oracle backup", "Task Scheduler",       "25s flight-deal video → TikTok / IG / LinkedIn (rotating by weekday)"],
    ["08:00", "pipeline.py  --slot 1",     "Every day",  "Laptop + Oracle backup", "Task Scheduler",       "25s story video → TikTok + Instagram + YouTube + Newspaper image"],
    ["08:00", "pipeline_g_inspired.py --slot 1","Every day","Laptop + Oracle backup","Task Scheduler",     "Car video → emailed to Ebube (G-Inspired client)"],
    ["09:00", "post_pending.py",           "Every day",  "Laptop",                 "After Oracle sync pull","Re-posts any Oracle-failed TikTok / IG / YouTube uploads"],
    ["14:00", "pipeline.py  --slot 2",     "Every day",  "Laptop + Oracle backup", "Task Scheduler",       "25s story video → TikTok + Instagram + YouTube"],
    ["21:00", "pipeline.py  --slot 3",     "Every day",  "Laptop + Oracle backup", "Task Scheduler",       "25s story video → TikTok + Instagram + YouTube"],
    ["Every 2h", "engage.py",              "Every day",  "Oracle (cron)",          "Cron job",             "Replies to new IG + YouTube comments using Claude Haiku"],
]

tbl_daily = Table(
    [[Paragraph(c, TH if i == 0 else TD) for c in row] for i, row in enumerate(daily_rows)],
    colWidths=[2*cm, 4.2*cm, 2.2*cm, 3*cm, 2.5*cm, 4.1*cm],
    repeatRows=1,
)
tbl_daily.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0), SLATE), ("TEXTCOLOR",(0,0),(-1,0), WHITE),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("FONTSIZE",(0,1),(-1,-1),7.5),
] + [("BACKGROUND",(0,i),(-1,i),SLATE_LT) for i in range(2,len(daily_rows),2)]))
story.append(tbl_daily)
story.append(sp(10))

# ── Day-specific runs ─────────────────────────────────────────────────────────
story.append(p("Specific-Day Runs", H3))

dayspec_rows = [
    ["Time (UK)", "Script", "Which days", "Machine", "Trigger", "What it produces"],
    ["08:00", "pipeline.py  --slot 4",           "Tue + Fri only",     "Laptop + Oracle backup", "Task Scheduler",    "LinkedIn post + Blog article (BootHop brand authority)"],
    ["08:00", "pipeline_g_inspired.py --slot 4", "Tue + Fri only",     "Laptop + Oracle backup", "Task Scheduler",    "LinkedIn article + SEO blog → emailed to Ebube"],
    ["06:30", "post_newsflash.py  → LinkedIn",   "Monday only",        "Laptop + Oracle backup", "Task Scheduler",    "Newsflash routed to LinkedIn (B2B traveller-earning angle)"],
    ["06:30", "post_newsflash.py  → TikTok",     "Tue / Thu / Sat",    "Laptop + Oracle backup", "Task Scheduler",    "Newsflash routed to TikTok"],
    ["06:30", "post_newsflash.py  → Instagram",  "Wed / Fri / Sun",    "Laptop + Oracle backup", "Task Scheduler",    "Newsflash routed to Instagram Reel"],
    ["Slot 1", "generate_kling.py",              "Mon (odd weeks)",    "Laptop",                 "Called by pipeline.py slot 1", "Kling AI 30–40s cinematic video (boothop / otb_midas only)"],
    ["Slot 2", "generate_kling.py",              "Tue (even weeks)",   "Laptop",                 "Called by pipeline.py slot 2", "Kling AI 30–40s cinematic video (alternating week)"],
]

tbl_day = Table(
    [[Paragraph(c, TH if i == 0 else TD) for c in row] for i, row in enumerate(dayspec_rows)],
    colWidths=[2*cm, 4.2*cm, 2.5*cm, 2.8*cm, 2.8*cm, 3.7*cm],
    repeatRows=1,
)
tbl_day.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0), SLATE), ("TEXTCOLOR",(0,0),(-1,0), WHITE),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("FONTSIZE",(0,1),(-1,-1),7.5),
] + [("BACKGROUND",(0,i),(-1,i),INDIGO_LT) for i in range(2,len(dayspec_rows),2)]))
story.append(tbl_day)
story.append(sp(10))

# ── Weekly runs ───────────────────────────────────────────────────────────────
story.append(p("Weekly Automated Runs (every Monday)", H3))

weekly_rows = [
    ["Time (UK)", "Script", "Frequency", "Machine", "Trigger", "What it produces"],
    ["05:30 Mon", "trend_scout.py",       "Weekly",  "Oracle",  "Cron job",                         "Pulls YouTube/IG/TikTok trends → trend_report.json → injected into all story prompts"],
    ["06:00 Mon", "weekly_review.py",     "Weekly",  "Oracle",  "Cron job",                         "Pulls view counts from all platforms → pillar_weights.json (biases pillar rotation to winners)"],
    ["Slot 1 Mon","hook_analyzer.py",     "Weekly",  "Laptop",  "Called inside pipeline.py slot 1", "Analyses top 30 hooks → hook_patterns.json → injected into every story prompt"],
    ["Every 7d",  "query_learner.py\n(weekly refresh)", "Weekly", "Laptop", "Called inside pipeline.py every run", "Asks Claude for 20 new transport queries, adds novel ones as trials to query_bank.json"],
    ["Monday",    "fetch_trending_hashtags.py", "Weekly", "Laptop", "Called inside pipeline.py slot 1", "Refreshes trending diaspora hashtags → trending_hashtags.json"],
    ["Monday",    "fetch_trending_music.py",    "Weekly", "Laptop", "Called inside pipeline.py slot 1", "Scans for new royalty-free music tracks → music/daily/ folder"],
]

tbl_weekly = Table(
    [[Paragraph(c, TH if i == 0 else TD) for c in row] for i, row in enumerate(weekly_rows)],
    colWidths=[2.2*cm, 4*cm, 1.8*cm, 2*cm, 3.5*cm, 4.5*cm],
    repeatRows=1,
)
tbl_weekly.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0), SLATE), ("TEXTCOLOR",(0,0),(-1,0), WHITE),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("FONTSIZE",(0,1),(-1,-1),7.5),
] + [("BACKGROUND",(0,i),(-1,i),TEAL_LT) for i in range(2,len(weekly_rows),2)]))
story.append(tbl_weekly)
story.append(sp(10))

# ── Every-slot-run scripts ────────────────────────────────────────────────────
story.append(p("Scripts That Run Inside Every Slot (automatic — not scheduled separately)", H3))

inline_rows = [
    ["Script", "When called", "What it does"],
    ["generate_content.py",  "Stage 1 of every slot",       "Writes the 5-beat story using Claude / GPT-4o / Gemini"],
    ["qa_director.py",       "Stage 2 of every slot",       "QA review — rewrites any beat below 80/100"],
    ["scene_planner.py",     "Stage 3 of every slot",       "Turns beats into 5 Pexels search queries"],
    ["photographer.py",      "Stage 4 of every slot",       "Refines queries into hyper-specific search strings"],
    ["cinematographer.py",   "Stage 5 of every slot",       "Generates Kling/Veo video prompts (stored for future use)"],
    ["reviewer.py",          "Stage 6 of every slot",       "Final quality gate — 90/100 threshold, rewrites weak sections"],
    ["generate_hook.py",     "Stage 7 of every slot",       "Generates 2s cinematic opening clip + Gen-Z dialogue"],
    ["render_video.py",      "Stage 8 of every slot",       "Assembles 25s MP4 with TTS narration, music, text overlays"],
    ["promote_demote() in query_learner.py", "After every clip fetch", "Updates query hit rate — promotes/demotes Pexels queries"],
    ["push_pipeline_state.py", "After every slot",          "Pushes data/ JSON files from laptop to Oracle"],
    ["quota_alert.py",       "After every API call",        "Alerts via Telegram if any API quota is near the limit"],
    ["send_to_telegram.py",  "After render + after posting","Sends approval request and result summary to Telegram"],
]

tbl_inline = Table(
    [[Paragraph(c, TH if i == 0 else (TD if i % 2 == 1 else TD)) for c in row] for i, row in enumerate(inline_rows)],
    colWidths=[5.5*cm, 4*cm, 8.5*cm],
    repeatRows=1,
)
tbl_inline.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0), SLATE), ("TEXTCOLOR",(0,0),(-1,0), WHITE),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("FONTSIZE",(0,1),(-1,-1),7.5),
] + [("BACKGROUND",(0,i),(-1,i),SLATE_LT) for i in range(2,len(inline_rows),2)]))
story.append(tbl_inline)
story.append(sp(10))

# ── Manual / on-demand scripts ────────────────────────────────────────────────
story.append(p("Manual / On-Demand Scripts (run when needed)", H3))

manual_rows = [
    ["Script", "How to run", "When to use"],
    ["regen_slots.py",       "python regen_slots.py [2 3]",            "Re-run specific slots — clears ran-today flag, deletes old posts first"],
    ["weekly_review.py",     "python scripts/weekly_review.py",        "Manually pull platform view counts and rebuild pillar_weights.json"],
    ["trend_scout.py",       "python scripts/trend_scout.py",          "Manually refresh trend intelligence from YouTube/IG/TikTok"],
    ["hook_analyzer.py",     "python scripts/hook_analyzer.py",        "Manually re-analyse hooks and update hook_patterns.json"],
    ["auth_youtube.py",      "python auth_youtube.py",                 "Re-authenticate YouTube OAuth (when token expires)"],
    ["auth_linkedin.py",     "python auth_linkedin.py",                "Re-authenticate LinkedIn OAuth (when token expires)"],
    ["set_linkedin_token.py","python set_linkedin_token.py",           "Manually set a LinkedIn access token"],
    ["post_pending.py",      "python scripts/post_pending.py",         "Manually retry failed Oracle posts without waiting for sync"],
    ["generate_kling.py",    "python scripts/generate_kling.py",       "Manually trigger a Kling AI video outside the slot schedule"],
    ["dispatch_scheduler.py","python deploy/dispatch_scheduler.py --status", "View all client schedules and next fire times"],
    ["dispatch_scheduler.py","python deploy/dispatch_scheduler.py --dry-run","Preview what would fire now without actually running it"],
]

tbl_manual = Table(
    [[Paragraph(c, TH if i == 0 else TD) for c in row] for i, row in enumerate(manual_rows)],
    colWidths=[4.5*cm, 5.5*cm, 8*cm],
    repeatRows=1,
)
tbl_manual.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0), SLATE), ("TEXTCOLOR",(0,0),(-1,0), WHITE),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("FONTSIZE",(0,1),(-1,-1),7.5),
] + [("BACKGROUND",(0,i),(-1,i),AMBER_LT) for i in range(2,len(manual_rows),2)]))
story.append(tbl_manual)
story.append(sp(8))

# ── Day-in-the-life summary ───────────────────────────────────────────────────
story.append(p("A Full Day in the Pipeline (Monday example)", H3))
story.append(p(
    "This shows every automated script that fires on a Monday, in order, and what each produces.",
    BODY_SM
))
story.append(sp(4))

day_life = [
    ["Time",    "Script",                       "Output"],
    ["05:30",   "trend_scout.py",               "Refreshed trend_report.json"],
    ["06:00",   "weekly_review.py",             "Refreshed pillar_weights.json"],
    ["06:30",   "post_newsflash.py → LinkedIn", "Flight deal video posted to LinkedIn (B2B angle)"],
    ["08:00",   "pipeline.py --slot 1",         "Stage 1–9 → story + 25s video → Telegram approval → TikTok + IG + YouTube + Newspaper"],
    ["08:00",   "  └ hook_analyzer.py",         "  (inside slot 1) Refreshed hook_patterns.json"],
    ["08:00",   "  └ fetch_trending_hashtags",  "  (inside slot 1) Refreshed trending_hashtags.json"],
    ["08:00",   "  └ fetch_trending_music",     "  (inside slot 1) New music tracks if none fresh today"],
    ["08:00",   "  └ generate_kling.py",        "  (inside slot 1, odd weeks) Kling AI 30–40s video"],
    ["~08:05",  "push_pipeline_state.py",       "Slot 1 data pushed to Oracle"],
    ["09:00",   "Oracle backup slot 1",         "Runs on Oracle — SKIPS (laptop already ran)"],
    ["~10:00",  "engage.py  (first run)",       "Replies to any new IG + YouTube comments"],
    ["~12:00",  "engage.py  (second run)",      "Replies to new comments"],
    ["14:00",   "pipeline.py --slot 2",         "Stage 1–9 → 25s video → TikTok + IG + YouTube"],
    ["~14:05",  "push_pipeline_state.py",       "Slot 2 data pushed to Oracle"],
    ["~16:00",  "engage.py",                    "Replies to new comments"],
    ["~18:00",  "engage.py",                    "Replies to new comments"],
    ["21:00",   "pipeline.py --slot 3",         "Stage 1–9 → 25s video → TikTok + IG + YouTube"],
    ["~21:05",  "push_pipeline_state.py",       "Slot 3 data pushed to Oracle"],
    ["~22:00",  "engage.py",                    "Replies to new comments"],
    ["~23:00",  "engage.py",                    "Final engagement pass for the day"],
]

tbl_dl = Table(
    [[Paragraph(c, TH if i == 0 else (MONO if c.startswith("  └") else TD)) for c in row]
     for i, row in enumerate(day_life)],
    colWidths=[2*cm, 5.5*cm, 10.5*cm],
    repeatRows=1,
)
tbl_dl.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0), INDIGO), ("TEXTCOLOR",(0,0),(-1,0), WHITE),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("FONTSIZE",(0,1),(-1,-1),7.5),
    ("BACKGROUND",(0,5),(2,8), colors.HexColor("#F0FDF4")),
    ("BACKGROUND",(0,10),(2,13), colors.HexColor("#F0FDF4")),
    ("BACKGROUND",(0,15),(2,17), colors.HexColor("#F0FDF4")),
] + [("BACKGROUND",(0,i),(-1,i),INDIGO_LT)
     for i in [1,3,9,14,18]]))
story.append(tbl_dl)
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("2. MAIN PIPELINE — pipeline.py", H2))
story.append(hr())
story.append(p(
    "The master orchestrator. Runs 4× daily via Windows Task Scheduler with <b>--slot 1|2|3|4</b>. "
    "Calls all 9 stages in order, sends the rendered video to Telegram for your approval, then posts to all platforms. "
    "An identical backup copy runs on Oracle Linux 1 hour later and skips automatically if the laptop already ran.",
    BODY
))
story.append(sp(8))

story.append(p("Slot Schedule", H3))
story.append(info_box([
    ["Slot", "Time (UK)", "Platforms", "Frequency"],
    ["1", "08:00", "TikTok + Instagram + YouTube + Newspaper image", "Daily"],
    ["2", "14:00", "TikTok + Instagram + YouTube", "Daily"],
    ["3", "21:00", "TikTok + Instagram + YouTube", "Daily"],
    ["4", "08:00", "LinkedIn + Blog post", "Tue + Fri only"],
], [1.5*cm, 2.5*cm, 9*cm, 4*cm]))
story.append(sp(10))

story.append(p("The 9-Stage Production Pipeline", H3))
story.append(flow_box([
    ("1", "Story Writer — generate_content.py",
     "Claude / GPT-4o / Gemini writes the 5-beat story (hook → problem → stakes → resolution → lesson). "
     "Beat word limits: Hook 10w, Problem 9w, Stakes 8w, Resolution 10w, Lesson 8w. "
     "Reads hook_patterns.json (weekly AI learnings) and pillar_weights.json (performance data) to bias output."),
    ("2", "QA Director — qa_director.py",
     "Reviews story against 7 quality dimensions (hook strength, coherence, beat length, brand safety, "
     "emotional impact, BootHop fit, lesson quality). Scores 0–100. Auto-rewrites any beat below 80/100. "
     "Nothing weak reaches the Scene Planner."),
    ("3", "Scene Planner — scene_planner.py",
     "Converts the 5 beats into 5 Pexels video search queries using PILLAR_BLUEPRINTS (12 pillar templates). "
     "One query per beat. Calls Claude Haiku. Falls back to _FALLBACK_QUERIES if API fails. "
     "V2 generates a second fresh set avoiding V1 queries."),
    ("4", "Photographer — photographer.py",
     "Takes the 5 basic queries and makes them hyper-specific for better Pexels hit rates. "
     "Also produces DALL-E image prompts (stored in .json sidecar for future use). "
     "Example: 'woman apartment' → '35yo Nigerian woman London flat holding phone charger worried medium shot'."),
    ("5", "Cinematographer — cinematographer.py",
     "Converts image prompts into full Kling/Veo/Runway cinematic video prompts — camera movement, "
     "lighting, emotion arc, duration. Stored in output JSON now; will drive AI video generation when Kling "
     "credits are available."),
    ("6", "Reviewer — reviewer.py",
     "Final quality gate. Scores the COMPLETE package (story + scenes together) on 6 dimensions at 90/100 threshold. "
     "Triggers targeted rewrites of weak areas only. Separate from QA Director which sees raw story text only."),
    ("7", "Hook Engine — generate_hook.py",
     "Generates the 2-second cinematic opening. Priority: Pexels VIDEO → Pixabay VIDEO → DALL-E image. "
     "Claude generates fresh Nigerian Pidgin / UK Gen-Z Nigerian dialogue each run. "
     "14-day cooldown per dialogue via hook_used_log.json to prevent repetition."),
    ("8", "Video Renderer — render_video.py",
     "Assembles everything into the final 25-second MP4: hook clip (2s) + 5 story clips (3s each) + "
     "lesson card (5s) + brand end card (5s). Adds OpenAI TTS narration, background music, "
     "text overlays, progress bar, and captions. Outputs platform variants (TikTok/IG/YT)."),
    ("9", "Platform Posting",
     "post_tiktok_zernio.py (Zernio OAuth) → post_instagram.py (Reel + catbox.moe host) → "
     "post_youtube.py (resumable upload) → post_newspaper.py (Pillow-rendered 1080×1350 image) → "
     "post_linkedin.py (UGC Posts API v2). Routes video to Oracle Revoice dashboard via SCP."),
]))
story.append(sp(10))

story.append(p("Output Files Produced Per Slot Run", H3))
story.append(info_box([
    ["File", "Description"],
    ["otb_slot1_YYYYMMDD_HHMMSS.mp4", "Base rendered video (TikTok format, 9:16, 1080×1920)"],
    ["otb_slot1_YYYYMMDD_HHMMSS_ig.mp4", "Instagram variant (same format, separate upload)"],
    ["otb_slot1_YYYYMMDD_HHMMSS.json", "Story sidecar — all 5 beats, captions, hashtags, pillar, slot"],
    ["otb_slot1_YYYYMMDD_HHMMSS_thumb.jpg", "YouTube thumbnail (slot 1 only)"],
    ["otb_slot1_YYYYMMDD_HHMMSS.voiceover.mp3", "TTS narration audio (OpenAI tts-1)"],
], [8*cm, 9*cm]))
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — SUPPORTING PIPELINES
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("3. SUPPORTING PIPELINES", H2))
story.append(hr())

story.append(KeepTogether([
    p("pipeline_g_inspired.py — G-Inspired Automall Client", H3),
    p(
        "Separate pipeline for the G-Inspired car dealership client (Ebube). No Telegram approval loop — "
        "outputs go directly to email.",
        BODY
    ),
    sp(4),
    info_box([
        ["Slot", "What it does"],
        ["Slot 1 (daily)", "Scrapes inventory → picks a car → generates video script → renders MP4 → emails to Ebube"],
        ["Slot 4 (Tue/Fri)", "Generates LinkedIn article + SEO blog post → emails blog to Ebube → posts to LinkedIn"],
    ], [3*cm, 14*cm]),
]))
story.append(sp(10))

story.append(KeepTogether([
    p("scripts/post_newsflash.py — Flight Newsflash (06:30 daily)", H3),
    p(
        "Runs independently at 06:30 every morning. Pulls live flight deals → generates dual-audience content "
        "(sender angle + traveller earning angle) → validates framing contract → renders 25s newsflash video → posts. "
        "Uses slot number 5 (≥ 5) to skip the text-card hook and overlay text directly on real footage.",
        BODY
    ),
    sp(4),
    info_box([
        ["Day", "Platform", "Framing angle"],
        ["Monday",              "LinkedIn",  "B2B — 'earn on your trip' traveller angle"],
        ["Tue / Thu / Sat",     "TikTok",    "Consumer — price shock + movement pivot"],
        ["Wed / Fri / Sun",     "Instagram", "Consumer — sender CTA + traveller CTA"],
    ], [3.5*cm, 3.5*cm, 10*cm]),
    sp(4),
    p("Output: output/newsflash_london-to-lagos_YYYY-MM-DD.mp4", MONO),
]))
story.append(sp(10))

story.append(KeepTogether([
    p("scripts/generate_kling.py — Kling AI Premium Video", H3),
    p(
        "Generates a 30–40s cinematic video using Kling AI. Enabled only for otb_midas and boothop slugs "
        "(KLING_ENABLED_SLUGS in config.py). Alternates Mon/Tue each week. "
        "Falls back to Pexels journey cards + music if Kling has no credits. "
        "Output goes to Revoice dashboard.",
        BODY
    ),
    sp(4),
    p("Output: output/kling_YYYYMMDD_[topic].mp4", MONO),
]))
story.append(sp(10))

story.append(KeepTogether([
    p("dashboard/main.py — Web Dashboard (boothop.com/dashboard)", H3),
    p(
        "Multi-tenant FastAPI app on Oracle. Receives pipeline output files via SCP after each slot. "
        "Two tabs: <b>Pipeline Control</b> (approve/skip/regen/edit text per slot) and <b>Revoice Studio</b> "
        "(re-voice or swap music without re-running the pipeline).",
        BODY
    ),
    sp(4),
    info_box([
        ["Tab", "What you can do"],
        ["Pipeline Control", "See Slot 1–4 videos, approve/skip/regen, edit hook/problem/stakes/resolution/lesson/captions inline, run a slot manually"],
        ["Revoice Studio",   "Pick any pipeline slot video → record voice in browser OR generate AI voice (6 OpenAI voices, hear preview first) → pick music → Bake → baked video downloads + sends to Telegram"],
    ], [4*cm, 13*cm]),
]))
story.append(sp(10))

story.append(KeepTogether([
    p("Revoice Studio — How to use from a laptop", H3),
    p(
        "Open boothop.com/dashboard in any browser. Log in. Click the <b>Revoice Studio</b> tab. "
        "Or click the purple <b>Revoice</b> button on any slot card in Pipeline Control — it jumps straight to "
        "the Revoice tab with that slot's video pre-loaded.",
        BODY
    ),
    sp(4),
    flow_box([
        ("1", "Pick video", "Click a pipeline slot button (Slot 1 V1, Slot 1 V2, etc.) — the video previews in the browser. "
                            "Or use 'Upload different video' to upload any MP4 from your laptop."),
        ("2", "Add voice",  "Option A — Generate AI voice: choose a voice (Nova, Alloy, Echo, Fable, Onyx, Shimmer), "
                            "click Generate, listen to the preview. "
                            "Option B — Record yourself: click Start Recording, speak, click Stop. "
                            "Option C — Upload an existing MP3/WAV file."),
        ("3", "Pick music", "Choose from the music library dropdown. Or search YouTube by keyword — "
                            "it downloads and adds to the library automatically."),
        ("4", "Bake",       "Click Bake Video. Oracle runs FFmpeg to mix voice + music over the video (~30 seconds). "
                            "When done, the baked video is sent to Telegram AND a Download link appears on screen."),
    ]),
]))
story.append(sp(10))

story.append(KeepTogether([
    p("scripts/telegram_commander.py — Telegram Bot", H3),
    p(
        "Handles all Telegram interactions: approval/reject/regenerate votes during pipeline runs, "
        "commander mode (trigger slots from phone, check logs, view status), "
        "and a watchdog that alerts if a slot crashes or hangs mid-run.",
        BODY
    ),
    sp(4),
    info_box([
        ["Command", "What it does"],
        ["/menu",      "Show all commands"],
        ["/status",    "Current pipeline state — last run, next slot, current step"],
        ["/rerun",     "Force re-run the most recent slot"],
        ["/revoice",   "Open Revoice Studio for the latest video (auto-detects slot)"],
        ["/revoice 1", "Open Revoice Studio for a specific slot"],
        ["/v1 / /v2",  "Force next slot to use V1 (25s Pexels) or V2 (15s Kling) format"],
        ["/skip",      "Cancel the current pending approval"],
        ["/pause",     "Pause all pipeline activity"],
        ["/resume",    "Resume after a pause"],
    ], [3.5*cm, 13.5*cm]),
]))
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — INTELLIGENCE & LEARNING
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("4. INTELLIGENCE & SELF-LEARNING SCRIPTS", H2))
story.append(hr())
story.append(p(
    "These scripts run on a schedule and continuously improve the content quality by learning from real performance data.",
    BODY
))
story.append(sp(6))

story.append(info_box([
    ["Script", "Runs", "Input", "Output / Effect"],
    ["hook_analyzer.py",
     "Weekly\n(slot 1 trigger)",
     "Top hooks in memory.json",
     "hook_patterns.json — psychological patterns injected into every story prompt"],
    ["query_learner.py",
     "Every slot run",
     "Pexels result type per query\n(video vs photo)",
     "query_bank.json — promotes winners, demotes duds. 71 seed queries + auto-growing trial pool"],
    ["trend_scout.py",
     "Weekly",
     "YouTube / Instagram /\nTikTok top posts (niche)",
     "trend_report.json — hook openers + visual styles injected into story + scene prompts"],
    ["reviewer.py",
     "Every slot (Stage 6)",
     "Story + scenes together",
     "Targeted rewrite of weak sections. 90/100 threshold before video render"],
    ["qa_director.py",
     "Every slot (Stage 2)",
     "Raw story beats",
     "Auto-rewrites any beat below 80/100. Nothing weak reaches Scene Planner"],
    ["weekly_review.py",
     "Weekly Monday",
     "TikTok / YouTube /\nInstagram view counts",
     "pillar_weights.json — biases future pillar selection toward what performs"],
    ["engage.py",
     "Every 2 hours\n(Oracle cron)",
     "New IG + YT comments",
     "AI replies via Claude Haiku. Never double-replies. TikTok first-comment only"],
], [4*cm, 2.5*cm, 4*cm, 7.5*cm]))
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — SUPPORT SCRIPTS
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("5. SUPPORT & UTILITY SCRIPTS", H2))
story.append(hr())

story.append(info_box([
    ["Script", "Purpose"],
    ["regen_slots.py",            "Interactive slot regenerator — clears ran-today flag, deletes old posts, re-runs selected slots"],
    ["post_pending.py",           "Picks up failed Oracle posts (TikTok/IG/YT) and re-posts from laptop on next sync"],
    ["fetch_trending_hashtags.py","Refreshes trending diaspora hashtags used in captions → data/trending_hashtags.json"],
    ["fetch_trending_music.py",   "Scans for royalty-free music → music/daily/ folder"],
    ["push_pipeline_state.py",    "Pushes data/ JSON files from laptop to Oracle after each slot run"],
    ["quota_alert.py",            "Alerts via Telegram when API quotas (YouTube, Pexels, Pixabay) near limit"],
    ["sync_tiktok_analytics.py",  "Pulls TikTok view/like/comment counts into local analytics log"],
    ["send_to_telegram.py",       "Shared utility for sending messages + videos to Telegram (used by all scripts)"],
    ["commander_watchdog.py",     "Monitors pipeline health; restarts Telegram commander if it dies"],
    ["post_stories.py",           "Posts Instagram Stories with visual poll after each Reel (double-tap boost)"],
    ["post_blog.py",              "Posts Claude-written SEO blog post to Blogger API (slot 4)"],
    ["auth_youtube.py",           "One-time YouTube OAuth token setup"],
    ["auth_linkedin.py",          "One-time LinkedIn OAuth token setup"],
], [5*cm, 12*cm]))
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — KEY DATA FILES
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("6. KEY DATA FILES", H2))
story.append(hr())

story.append(info_box([
    ["File", "Written by", "Read by", "Purpose"],
    ["data/memory.json",         "pipeline.py (each run)", "hook_analyzer.py, weekly_review.py", "Full story archive — hook, beats, queries, scores, pillar, slot"],
    ["data/hook_patterns.json",  "hook_analyzer.py",       "generate_content.py",                "AI-extracted hook patterns injected into Story Writer prompt"],
    ["data/pillar_weights.json", "weekly_review.py",       "generate_content.py",                "Pillar performance weights (biases rotation toward winners)"],
    ["data/query_bank.json",     "query_learner.py",       "render_video.py",                    "Transport query pool — seed / trial / active / weak / archived"],
    ["data/query_hits.json",     "render_video.py",        "query_learner.py",                   "Per-query hit type log (video vs photo vs fallback)"],
    ["data/hook_used_log.json",  "generate_hook.py",       "generate_hook.py",                   "14-day cooldown for hook dialogues — prevents repeats"],
    ["data/trending_hashtags.json","fetch_trending_hashtags.py","generate_content.py",           "Current top diaspora hashtags for captions"],
    ["data/sync_status.json",    "pipeline.py",            "dashboard/main.py",                  "Platform post results per run (true/false per platform per slot)"],
    ["data/pending_posts.json",  "pipeline.py (Oracle)",   "post_pending.py (laptop)",           "Failed Oracle posts queued for laptop re-post on next sync"],
    ["data/engagement_log.json", "engage.py",              "engage.py",                          "Comment reply ID list — prevents double-replying"],
    ["data/pipeline_ran_today.json","pipeline.py",         "scripts/pipeline.py (Oracle)",       "Ran-today flag — Oracle skips if laptop already ran"],
], [4*cm, 4*cm, 4.5*cm, 5.5*cm]))
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — VIDEO STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("7. 25-SECOND VIDEO STRUCTURE", H2))
story.append(hr())

timeline = [
    ["0–2s",   "HOOK CLIP",      "2s", "Cinematic hook engine — Pexels/Pixabay/DALL-E + Gen-Z dialogue voiceover"],
    ["2–5s",   "HOOK BEAT",      "3s", "Beat 0 — Hook text overlay + TTS narration (max 10 words)"],
    ["5–8s",   "PROBLEM BEAT",   "3s", "Beat 1 — Problem text overlay + TTS narration (max 9 words)"],
    ["8–11s",  "STAKES BEAT",    "3s", "Beat 2 — Stakes text overlay + TTS narration (max 8 words)"],
    ["11–14s", "RESOLUTION BEAT","3s", "Beat 3 — Resolution text overlay + TTS narration (max 10 words)"],
    ["14–17s", "LESSON BEAT",    "3s", "Beat 4 — Lesson text overlay + TTS narration (max 8 words)"],
    ["17–22s", "LESSON CARD",    "5s", "Static brand lesson card (dark background, large text)"],
    ["22–27s", "BRAND END CARD", "5s", "BootHop end card with logo + call to action"],
]

tbl_data = [[Paragraph(c, TH) for c in ["Time", "Section", "Duration", "Content"]]]
colors_map = {}
beat_cols = [INDIGO_LT, WHITE, SLATE_LT, WHITE, INDIGO_LT, WHITE, TEAL_LT, GREEN_LT]
for i, row in enumerate(timeline):
    tbl_data.append([Paragraph(str(c), TD) for c in row])
    colors_map[i+1] = beat_cols[i]

tbl = Table(tbl_data, colWidths=[2*cm, 4*cm, 2*cm, 9*cm])
tbl.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0), SLATE),
    ("TEXTCOLOR",(0,0),(-1,0), WHITE),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ("TOPPADDING",(0,0),(-1,-1),5),
    ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),7),
    ("RIGHTPADDING",(0,0),(-1,-1),7),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
] + [("BACKGROUND",(0,i),(-1,i),col) for i,col in colors_map.items()]))
story.append(tbl)
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — PLATFORM ALGORITHMS
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("8. PLATFORM-SPECIFIC POSTING RULES", H2))
story.append(hr())

story.append(info_box([
    ["Platform", "Post type", "Caption rule", "Hashtags", "Special logic"],
    ["TikTok",    "Video (9:16)", "Hook-first, 150 chars max", "20 tags",  "3h rate-limit guard via Zernio OAuth. First comment posted inline"],
    ["Instagram", "Reel",        "125-char visible hook. Full story below fold", "22 mid/micro tags", "catbox.moe video host for API upload. IG Story + poll posted after Reel"],
    ["YouTube",   "Short (9:16)","Keyword-first title. #Shorts in description", "10 tags", "Resumable upload API. Thumbnail generated (slot 1). Episode title format"],
    ["LinkedIn",  "Video post",  "NO link in caption. First-comment link", "3–5 tags",  "Weekday only (Tue+Fri). UGC Posts API v2. Brand/thought-leadership angle"],
    ["Blog",      "HTML article","H2 structure. FAQ section. Longtail keywords", "N/A",  "Claude writes full SEO post. Posted to Blogger API (slot 4)"],
    ["Newspaper", "Image (feed)","Pillow-rendered 1080×1350 image", "Via IG caption", "Rotating mastheads. IG feed IMAGE (content variety signal for algorithm)"],
], [2.5*cm, 2.5*cm, 5*cm, 2.5*cm, 5.5*cm]))
story.append(sp(16))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — OBSERVATIONS FROM OUTPUT FILES
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("9. OBSERVATIONS FROM OUTPUT FILES", H2))
story.append(hr())
story.append(p(
    f"Analysis of the output/ folder and data/ logs as of {date.today().strftime('%d %b %Y')}.",
    CAPTION
))
story.append(sp(6))

obs = [
    ("⚠", AMBER_LT, AMBER, "File Size Variance (Critical)",
     "Video sizes range from 5MB (slot2_20260808) to 31MB (slot3_20260805). "
     "This is caused by Pexels returning 4K clips that get downscaled to 1080×1920. "
     "A 31MB file is 6× larger than needed, slowing render time and upload speed."),
    ("✗", RED_LT, RED, "TikTok is the Most Failure-Prone Platform",
     "Of ~30 recent runs in sync_status.json, TikTok failed approximately 6 times "
     "(slots 1, 2, 4 of July 22, 25, 26). Instagram and YouTube are consistently more reliable. "
     "Cause: Zernio OAuth token expiry mid-upload rather than pre-flight."),
    ("⚠", AMBER_LT, AMBER, "Newspaper & IG Story Silently Failing",
     "Multiple slot 1 runs show newspaper: false and no newspaper file in output/. "
     "No crash log entry for these failures — they are being swallowed silently."),
    ("✗", RED_LT, RED, "Engagement Bot Not Running",
     "data/engagement_log.json is empty (replied_ig: [], replied_yt: []). "
     "The engage.py cron on Oracle has stopped. No comments are being replied to."),
    ("⚠", AMBER_LT, AMBER, "Pillar Weights Not Yet Bootstrapped",
     "data/pillar_weights.json does not exist. The pipeline is doing round-robin "
     "pillar rotation instead of weighting toward top performers. "
     "weekly_review.py needs one run to generate this file."),
    ("✓", GREEN_LT, GREEN, "Hook Patterns Learning is Working",
     "hook_patterns.json shows 30 hooks analysed (last run 2026-08-05) with 6 patterns "
     "scored and ranked. Top pattern (urgency + specific deadline, score 9/10) is being "
     "injected into every story prompt."),
    ("✓", GREEN_LT, GREEN, "Query Learner is Active",
     "query_hits.json shows a healthy mix of 'video' and 'perplexity_alt' hits. "
     "The learner is promoting and demoting queries based on real Pexels returns."),
    ("✓", GREEN_LT, GREEN, "Post Reliability on Instagram + YouTube is High",
     "Of the ~30 tracked runs, Instagram succeeded in ~26 and YouTube in ~27. "
     "Both platforms are posting reliably."),
]

for icon, bg, fg, title, desc in obs:
    row_tbl = Table([[
        Paragraph(icon, ParagraphStyle("ic", fontSize=14, textColor=fg,
                   fontName="Helvetica-Bold", alignment=TA_CENTER, leading=16)),
        Table([
            [Paragraph(title, ParagraphStyle("ot", fontSize=9, textColor=fg,
                        fontName="Helvetica-Bold", leading=12))],
            [Paragraph(desc, BODY_SM)],
        ], colWidths=[14.5*cm]),
    ]], colWidths=[1.2*cm, 15*cm])
    row_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), bg),
        ("TOPPADDING",(0,0),(-1,-1),8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ROUNDEDCORNERS",[4]),
        ("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ]))
    story.append(row_tbl)
    story.append(sp(4))

story.append(sp(10))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — OPTIMISATION RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════════════════════
story.append(p("10. OPTIMISATION RECOMMENDATIONS", H2))
story.append(hr())

recs = [
    ("1", INDIGO, "Cap Pexels Download Resolution (Highest Impact)",
     "In render_video.py, filter Pexels video_files to width ≤ 1080 before downloading. "
     "Currently returning 4K clips that get downscaled. "
     "Expected result: render time drops ~60%, output files shrink from 5–31MB to a consistent 4–6MB, "
     "upload speed to all platforms improves."),
    ("2", INDIGO, "TikTok Pre-Flight Token Refresh",
     "In post_tiktok_zernio.py, add a token validity check BEFORE starting the video upload. "
     "Currently the token expires mid-upload causing a silent failure. "
     "A pre-flight refresh call (or expiry check against stored token timestamp) would prevent the ~20% TikTok failure rate."),
    ("3", TEAL, "Fix Newspaper / IG Story Silent Failures",
     "Add explicit try/except with Telegram alert in the newspaper and IG story posting blocks of pipeline.py. "
     "Currently these fail with no crash log entry and no Telegram notification. "
     "At minimum, the failure reason should appear in the Telegram approval message."),
    ("4", TEAL, "Restart engage.py Cron on Oracle",
     "Run crontab -l on Oracle to verify the every-2-hour engage.py job. "
     "If missing, re-add it. Every unanswered comment is a lost retention signal — "
     "replies in the first 30 minutes after posting are the biggest algorithmic boost available."),
    ("5", TEAL, "Bootstrap Pillar Weights",
     "Run python scripts/weekly_review.py once manually to create pillar_weights.json. "
     "Without it, the pipeline treats all 12 pillars equally even though performance data "
     "already shows which angles get the most views."),
    ("6", AMBER, "Feed Hook Patterns as Direct Examples (Not Just Context)",
     "hook_patterns.json already contains 5 high-scoring suggested_hooks. "
     "Inject these directly into the generate_content.py prompt as 'EXAMPLE HOOKS TO MATCH' "
     "rather than just as background context. This gives the Story Writer a concrete target, "
     "not an abstract description of what to aim for."),
    ("7", AMBER, "Add Resolution Specificity Validator",
     "The QA Director currently scores resolution quality but doesn't enforce the 'specific number' rule. "
     "Add a check: if resolution contains no price (£X), time (X mins/hours), or distance, "
     "trigger an auto-rewrite of that beat. Concrete numbers are the single biggest credibility signal."),
]

for num, col, title, desc in recs:
    row_tbl = Table([[
        Paragraph(num, ParagraphStyle("rn", fontSize=13, textColor=WHITE,
                   fontName="Helvetica-Bold", alignment=TA_CENTER, leading=16)),
        Table([
            [Paragraph(title, ParagraphStyle("rt", fontSize=9, textColor=col,
                        fontName="Helvetica-Bold", leading=12))],
            [Paragraph(desc, BODY_SM)],
        ], colWidths=[14.5*cm]),
    ]], colWidths=[1.2*cm, 15*cm])
    row_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,-1), col),
        ("BACKGROUND",(1,0),(-1,-1), SLATE_LT),
        ("TOPPADDING",(0,0),(-1,-1),8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#E2E8F0")),
    ]))
    story.append(row_tbl)
    story.append(sp(4))

story.append(sp(10))

# ── Footer ────────────────────────────────────────────────────────────────────
story.append(hr())
story.append(p(
    f"OTB Pipeline Overview  •  BootHop  •  {date.today().strftime('%d %B %Y')}  •  CONFIDENTIAL",
    ParagraphStyle("foot", fontSize=7.5, textColor=SLATE_MID, alignment=TA_CENTER,
                   fontName="Helvetica-Oblique", leading=10)
))

# ── Build ─────────────────────────────────────────────────────────────────────
doc.build(story)
print(f"PDF saved to: {OUT}")
