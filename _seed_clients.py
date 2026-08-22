"""
Seed G-Inspired and D818 into the pipeline DB.
Run once: python _seed_clients.py
"""
import sqlite3, hashlib, json, secrets, datetime

DB = "dashboard/otb.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

def _hash(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ── 1. Migrations ─────────────────────────────────────────────
migrations = [
    "ALTER TABLE companies ADD COLUMN platforms_enabled TEXT DEFAULT '[]'",
    "ALTER TABLE companies ADD COLUMN credentials_json  TEXT DEFAULT '{}'",
    "ALTER TABLE companies ADD COLUMN digest_email      TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN digest_frequency  TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN website_url      TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN youtube_url      TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN linkedin_url     TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN facebook_url     TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN tt_handle        TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN ig_handle        TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN business_type    TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN business_bio     TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN location         TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN area_covered     TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN target_audience  TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN marketing_focus  TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN content_tone     TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN visual_keywords  TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN brand_voice      TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN logo_path        TEXT DEFAULT ''",
    "ALTER TABLE companies ADD COLUMN schedule_json    TEXT DEFAULT '{}'",
    "ALTER TABLE companies ADD COLUMN intake_status    TEXT DEFAULT 'active'",
    "ALTER TABLE companies ADD COLUMN intake_submitted TEXT DEFAULT ''",
]
for sql in migrations:
    try:
        conn.execute(sql)
    except Exception:
        pass
conn.commit()
print("Migrations done.")

# ── 2. G-Inspired ────────────────────────────────────────────
G_PW   = "ginspired-2026"
G_SLUG = "g-inspired"

existing = conn.execute("SELECT id FROM companies WHERE slug=?", (G_SLUG,)).fetchone()
if existing:
    print(f"G-Inspired already exists (id={existing[0]}) — updating fields.")
    conn.execute("""
        UPDATE companies SET
          name='G-Inspired Automall',
          email='info@kreativerock.com',
          contact='Ebube',
          plan='pro',
          password_h=?,
          api_key=?,
          active=1,
          website_url='https://www.ginspiredautomall.com',
          facebook_url='https://www.facebook.com/ginspiredautomall/',
          business_type='automotive',
          business_bio='Used car dealership offering quality pre-owned vehicles at honest prices with no hidden fees.',
          location='Washington, IL',
          area_covered='Central Illinois',
          target_audience='Local car buyers looking for honest, fee-free used vehicle deals',
          content_tone='trustworthy',
          visual_keywords='cars, dealership, honest pricing, Washington IL',
          brand_voice='Straight-talking, fee-free, CARFAX-verified. No hidden fees, no games.',
          platforms_enabled='["facebook","email"]',
          intake_status='active',
          schedule_json=?
        WHERE slug=?
    """, (
        _hash(G_PW),
        secrets.token_hex(16),
        json.dumps({
            "timezone": "America/Chicago",
            "slot1": "09:00",
            "slot2": "13:00",
            "slot3": "18:00",
            "slot4": "09:00",
            "days": ["monday","tuesday","wednesday","thursday","friday"],
            "slot4_days": ["tuesday","friday"]
        }),
        G_SLUG
    ))
else:
    conn.execute("""
        INSERT INTO companies
          (slug, name, email, contact, plan, password_h, api_key, active,
           website_url, facebook_url, business_type, business_bio,
           location, area_covered, target_audience, content_tone,
           visual_keywords, brand_voice, platforms_enabled, intake_status,
           schedule_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        G_SLUG,
        "G-Inspired Automall",
        "info@kreativerock.com",
        "Ebube",
        "pro",
        _hash(G_PW),
        secrets.token_hex(16),
        1,
        "https://www.ginspiredautomall.com",
        "https://www.facebook.com/ginspiredautomall/",
        "automotive",
        "Used car dealership offering quality pre-owned vehicles at honest prices with no hidden fees.",
        "Washington, IL",
        "Central Illinois",
        "Local car buyers looking for honest, fee-free used vehicle deals",
        "trustworthy",
        "cars, dealership, honest pricing, Washington IL",
        "Straight-talking, fee-free, CARFAX-verified. No hidden fees, no games.",
        '["facebook","email"]',
        "active",
        json.dumps({
            "timezone": "America/Chicago",
            "slot1": "09:00",
            "slot2": "13:00",
            "slot3": "18:00",
            "slot4": "09:00",
            "days": ["monday","tuesday","wednesday","thursday","friday"],
            "slot4_days": ["tuesday","friday"]
        }),
        datetime.datetime.now().isoformat()
    ))

conn.commit()
g_id = conn.execute("SELECT id FROM companies WHERE slug=?", (G_SLUG,)).fetchone()[0]
print(f"G-Inspired seeded  — id={g_id}  slug={G_SLUG}  password={G_PW}")

# ── 3. D818 ──────────────────────────────────────────────────
D_PW   = "d818-pipeline-2026"
D_SLUG = "d818"

existing = conn.execute("SELECT id FROM companies WHERE slug=?", (D_SLUG,)).fetchone()
if existing:
    print(f"D818 already exists (id={existing[0]}) — skipping.")
else:
    conn.execute("""
        INSERT INTO companies
          (slug, name, email, contact, plan, password_h, api_key, active,
           business_type, intake_status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        D_SLUG,
        "D818",
        "",
        "",
        "pro",
        _hash(D_PW),
        secrets.token_hex(16),
        1,
        "general",
        "active",
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    d_id = conn.execute("SELECT id FROM companies WHERE slug=?", (D_SLUG,)).fetchone()[0]
    print(f"D818 seeded        — id={d_id}  slug={D_SLUG}  password={D_PW}")

# ── 4. Verify ─────────────────────────────────────────────────
print()
print("=== CURRENT DB STATE ===")
for row in conn.execute(
    "SELECT id, slug, name, email, plan, intake_status, active FROM companies WHERE id != -1"
):
    print(dict(row))

conn.close()
