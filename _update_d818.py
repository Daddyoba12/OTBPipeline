"""
Update D818 with full business details.
Run: python _update_d818.py
"""
import sqlite3, json, datetime

DB = "dashboard/otb.db"
conn = sqlite3.connect(DB)

schedule = json.dumps({
    "timezone": "Europe/London",
    "slot1": "09:00",
    "slot2": "13:00",
    "slot3": "18:00",
    "days": ["monday","tuesday","wednesday","thursday","friday","saturday"],
})

conn.execute("""
    UPDATE companies SET
      name              = 'D818 Catering',
      email             = 'info@d818.co.uk',
      contact           = 'D818 Team',
      whatsapp          = '07846682910',
      website_url       = 'https://d818.co.uk',
      ig_handle         = 'd818.restuarant',
      tt_handle         = 'D818_restaurant',
      business_type     = 'catering',
      business_bio      = 'Premium catering service specialising in weddings, parties, and anniversary occasions across the UK. Known for exceptional food presentation, bespoke menus, and flawless event delivery.',
      location          = 'United Kingdom',
      area_covered      = 'UK-wide',
      target_audience   = 'Couples planning weddings, families hosting parties and anniversary celebrations across the UK',
      marketing_focus   = 'events',
      content_tone      = 'elegant',
      visual_keywords   = 'wedding catering, party food, anniversary dining, UK events, food presentation, bespoke menus',
      brand_voice       = 'Warm, sophisticated, celebratory. Every event deserves exceptional food.',
      platforms_enabled = '["tiktok","instagram"]',
      intake_status     = 'active',
      schedule_json     = ?
    WHERE slug = 'd818'
""", (schedule,))
conn.commit()

row = conn.execute(
    "SELECT id, slug, name, email, ig_handle, tt_handle, whatsapp, website_url, intake_status FROM companies WHERE slug='d818'"
).fetchone()
print("D818 updated:")
print(f"  id={row[0]}  slug={row[1]}  name={row[2]}")
print(f"  email={row[3]}  ig=@{row[4]}  tiktok=@{row[5]}")
print(f"  whatsapp={row[6]}  website={row[7]}")
print(f"  status={row[8]}")
conn.close()
