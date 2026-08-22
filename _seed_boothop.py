"""
Add BootHop as a proper pipeline client in the DB.
Run: python _seed_boothop.py
"""
import sqlite3, hashlib, json, secrets, datetime

DB = "dashboard/otb.db"
conn = sqlite3.connect(DB)

def _hash(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

SLUG = "boothop"
PW   = "boothop-pipeline-2026"

existing = conn.execute("SELECT id FROM companies WHERE slug=?", (SLUG,)).fetchone()
if existing:
    print(f"BootHop already exists (id={existing[0]}) — updating.")
    conn.execute("""
        UPDATE companies SET
          name              = 'BootHop',
          email             = 'titobalo12@gmail.com',
          contact           = 'Toyin',
          plan              = 'pro',
          password_h        = ?,
          active            = 1,
          website_url       = 'https://boothop.com',
          ig_handle         = 'boothopuk',
          tt_handle         = 'boothopuk',
          business_type     = 'logistics',
          business_bio      = 'UK to Nigeria peer-to-peer parcel delivery via travellers. Earn money carrying parcels on trips you are already making.',
          location          = 'United Kingdom',
          area_covered      = 'UK to Nigeria (and growing)',
          target_audience   = 'UK-based Nigerian diaspora — both senders and travellers looking to earn',
          content_tone      = 'energetic',
          visual_keywords   = 'travel, parcels, Nigeria, diaspora, peer delivery, UK, earn money travelling',
          brand_voice       = 'Bold, community-driven, relatable to the UK diaspora. Real stories, real people.',
          platforms_enabled = '["tiktok","instagram"]',
          intake_status     = 'active',
          schedule_json     = ?
        WHERE slug = ?
    """, (
        _hash(PW),
        json.dumps({
            "timezone": "Europe/London",
            "slot1": "08:00",
            "slot2": "14:00",
            "slot3": "21:00",
            "days": ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        }),
        SLUG
    ))
else:
    conn.execute("""
        INSERT INTO companies
          (slug, name, email, contact, plan, password_h, api_key, active,
           website_url, ig_handle, tt_handle, business_type, business_bio,
           location, area_covered, target_audience, content_tone,
           visual_keywords, brand_voice, platforms_enabled, intake_status,
           schedule_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        SLUG, "BootHop", "titobalo12@gmail.com", "Toyin", "pro",
        _hash(PW), secrets.token_hex(16), 1,
        "https://boothop.com", "boothopuk", "boothopuk", "logistics",
        "UK to Nigeria peer-to-peer parcel delivery via travellers. Earn money carrying parcels on trips you are already making.",
        "United Kingdom", "UK to Nigeria (and growing)",
        "UK-based Nigerian diaspora — both senders and travellers looking to earn",
        "energetic",
        "travel, parcels, Nigeria, diaspora, peer delivery, UK, earn money travelling",
        "Bold, community-driven, relatable to the UK diaspora. Real stories, real people.",
        '["tiktok","instagram"]', "active",
        json.dumps({
            "timezone": "Europe/London",
            "slot1": "08:00",
            "slot2": "14:00",
            "slot3": "21:00",
            "days": ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        }),
        datetime.datetime.now().isoformat()
    ))

conn.commit()

row = conn.execute(
    "SELECT id, slug, name, email, ig_handle, tt_handle, intake_status FROM companies WHERE slug=?",(SLUG,)
).fetchone()
print(f"BootHop: id={row[0]}  slug={row[1]}  name={row[2]}")
print(f"  email={row[3]}  ig=@{row[4]}  tiktok=@{row[5]}  status={row[6]}")

print()
print("=== ALL COMPANIES ===")
for r in conn.execute("SELECT id,slug,name,intake_status FROM companies WHERE id!=-1"):
    print(f"  {r[0]}  {r[1]:<20} {r[2]:<25} {r[3]}")

conn.close()
