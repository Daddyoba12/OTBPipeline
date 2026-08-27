"""Quick test — renders all 3 newspaper templates locally."""
import sys, datetime
sys.path.insert(0, ".")
import scripts.post_newspaper as np_mod
from scripts.post_newspaper import _make_newspaper_image, TEMPLATES, TEMPLATE_NAMES

content = {
    "hook": "A father in London paid £145 to send his daughter birthday gift to Lagos",
    "problem": "Soaring courier prices and slow delivery times are leaving UK-Nigeria families frustrated and out of pocket. A simple birthday gift costs more to send than it is worth.",
    "stakes": "Families are forced to choose between missing important occasions or paying extortionate courier fees.",
    "resolution": "BootHop connects you with verified travellers already making the journey — same-day delivery for a fraction of the cost.",
    "lesson": "Someone is already going your way. Why pay courier prices when a traveller can carry it for you?",
    "pillar": "cost_pain",
    "engagement": "Have you ever paid too much to send something to Nigeria? Drop your story.",
}

base = datetime.date.today().toordinal()

class FakeDate:
    _ord = base
    @classmethod
    def today(cls):
        return cls
    @classmethod
    def toordinal(cls):
        return cls._ord
    @classmethod
    def strftime(cls, fmt):
        return datetime.date.today().strftime(fmt)

for i in range(len(TEMPLATES)):
    FakeDate._ord = base - (base % len(TEMPLATES)) + i
    np_mod.date = FakeDate
    dest = f"data/test_newspaper_tmpl{i}.jpg"
    ok = _make_newspaper_image(content, dest)
    print(f"Template {i} ({TEMPLATE_NAMES[i]}): {'OK -> ' + dest if ok else 'FAILED'}")

np_mod.date = datetime.date
print("\nOpen the images in data/ to review.")
