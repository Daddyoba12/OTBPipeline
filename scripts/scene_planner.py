"""
OTB_Pipeline — Scene Planner (Stage 2)

Converts a story narrative into 8 scene-specific Pexels search queries.
Each pillar has a fixed blueprint that enforces the correct narrative scene order.

Scene positions:
  0-1  HOOK:       Protagonist's world — who they are and where they are
  2-3  PROBLEM:    The specific obstacle they face (pharmacy, courier price, customs)
  4    STAKES:     Why it matters emotionally (worried call, waiting, upset)
  5-6  RESOLUTION: BootHop in action — parcel handover + traveller on journey
  7    LESSON:     Happy ending — delivery, smiling recipient, or confident cityscape
"""

import json, re, sys, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY


# ── Item visual vocabulary ─────────────────────────────────────────────────────
# Maps item keywords (lowercase) to Pexels/Pixabay-friendly search terms.
# Longer/more specific keys are checked first (sorted by length desc at lookup).
_ITEM_VISUAL_TERMS = {
    # Footwear
    "jordan":            "Nike Air Jordan sneakers shoe box trainers",
    "jordans":           "Nike Air Jordan sneakers shoe box trainers",
    "trainers":          "sneakers trainers shoe box gift",
    "shoes":             "shoes trainers sneakers gift box",
    # Nigerian/African fabric & traditional
    "aso-oke":           "African aso-oke colourful woven fabric material held",
    "aso oke":           "African aso-oke colourful woven fabric material held",
    "agbada":            "Nigerian agbada traditional embroidered robe garment",
    "lace fabric":       "Nigerian lace fabric material colourful sewing",
    "fabric":            "colourful African textile fabric material",
    # Medical / health
    "stethoscope":       "medical stethoscope doctor equipment",
    "crutches":          "crutches mobility aid walking support",
    "knee brace":        "knee brace support medical",
    "breast pump":       "baby feeding mother nursing equipment",
    "medication":        "medicine prescription pill bottle pharmacy",
    "prescription":      "medicine prescription pill bottle pharmacy",
    "cpap":              "CPAP machine sleep therapy medical device",
    # Electronics
    "laptop":            "laptop computer modern portable",
    "phone charger":     "phone USB charger cable tech accessories",
    "power bank":        "portable power bank charging device",
    "smart watch":       "smartwatch wrist digital tech",
    "smartwatch":        "smartwatch wrist digital tech",
    "headphones":        "wireless over-ear headphones audio",
    "gaming controller": "gaming controller joystick hands",
    "phone":             "smartphone mobile screen hands",
    # Baby / children
    "baby clothes":      "baby clothes tiny newborn outfit colourful",
    "baby shoes":        "tiny baby shoes newborn soft",
    "formula tin":       "baby formula tin feeding powder",
    "school uniform":    "school uniform blazer shirt child",
    "school shoes":      "school shoes black polished child",
    # Clothing
    "nursing scrubs":    "nurse blue scrubs uniform hospital",
    "scrubs":            "nurse blue scrubs uniform hospital",
    "wedding dress":     "white wedding dress bride gown",
    # Documents & paper
    "exam certificate":  "certificate diploma document official paper",
    "certificate":       "certificate diploma document official paper",
    "acceptance letter":  "university letter envelope official document",
    "driving licence":   "driving licence ID card document",
    "documents":         "official documents papers envelope",
    "invitation":        "wedding invitation card elegant paper",
    "letter":            "handwritten letter envelope paper writing",
    # Jewellery
    "engagement ring":   "engagement ring diamond box proposal jewellery",
    "ring box":          "ring box jewellery engagement proposal",
    "jewellery":         "jewellery necklace gold bracelet",
    # Food / cultural
    "nigerian spices":   "African spice jars containers colourful kitchen shelf",
    "spices":            "African spice jars containers colourful",
    "stockfish":         "dried stockfish packaging seafood",
    "indomie":           "instant noodles packet stack colourful",
    "shea butter":       "shea butter cream jar natural beauty",
    # Keepsakes & gifts
    "framed photo":      "framed family photo picture frame gift",
    "family photo":      "framed family photo picture frame gift",
    "football shirt":    "football jersey signed shirt framed gift",
    "signed":            "signed jersey shirt framed memorabilia",
    "perfume":           "luxury perfume bottle fragrance gift box",
    "gift":              "gift wrapped box ribbon bow",
    # Generic fallback
    "parcel":            "small parcel package wrapped box",
    "package":           "small parcel package wrapped box",
}

# Maps protagonist role keywords to visual description for search queries
_ROLE_VISUAL_TERMS = {
    "nurse":             "Black nurse woman blue scrubs uniform",
    "doctor":            "Black doctor woman white coat stethoscope",
    "pharmacist":        "Nigerian pharmacist counter white coat",
    "midwife":           "Black midwife nurse uniform hospital",
    "care worker":       "Black care worker uniform compassionate",
    "nhs":               "Black NHS worker uniform hospital corridor",
    "teacher":           "Nigerian woman teacher classroom professional",
    "lecturer":          "Black university lecturer professional smart",
    "accountant":        "Nigerian woman accountant office professional",
    "finance":           "Black professional finance office suit",
    "architect":         "Nigerian woman architect office drawing plans",
    "software":          "Black software developer laptop coding",
    "it consultant":     "Black IT consultant laptop office suit",
    "consultant":        "Black professional consultant office suit jacket",
    "analyst":           "Black analyst office professional laptop",
    "manager":           "Nigerian woman manager office professional",
    "security":          "Black security guard uniform professional",
    "chef":              "Black chef apron kitchen uniform",
    "driver":            "Black delivery driver van uniform",
    "plumber":           "Black tradesman tools work clothes",
    "market trader":     "Nigerian woman market stall colourful clothes",
    "photographer":      "Black photographer camera professional",
    "social worker":     "Black social worker professional compassionate",
    "student":           "Black student university backpack casual",
    "corporate":         "Black professional suit jacket office shirt",
    "businessman":       "Black businessman suit jacket tie",
    "professional":      "Black professional suit jacket office",
    "traveller":         "Black traveller cabin luggage airport confident",
}


def _extract_story_visuals(story: dict) -> tuple[str, str, str, str]:
    """
    Read story_anchor to extract the item and protagonist context.
    Returns (item_name, item_visual_term, role_name, role_visual_term).
    Falls back to empty strings if not found.
    """
    anchor   = story.get("story_anchor", {})
    raw_item = (anchor.get("item", "") or "").lower()
    raw_char = (anchor.get("character", "") or "").lower()

    # Also scan hook text in case anchor is absent
    hook_text = (story.get("hook", "") or "").lower()

    # Find item visual: check all keys sorted by length (longest match wins)
    item_name   = ""
    item_visual = ""
    for key in sorted(_ITEM_VISUAL_TERMS.keys(), key=len, reverse=True):
        if key in raw_item or key in hook_text:
            item_name   = key
            item_visual = _ITEM_VISUAL_TERMS[key]
            break

    # Find role visual
    role_name   = ""
    role_visual = ""
    for key in sorted(_ROLE_VISUAL_TERMS.keys(), key=len, reverse=True):
        if key in raw_char:
            role_name   = key
            role_visual = _ROLE_VISUAL_TERMS[key]
            break

    return item_name, item_visual, role_name, role_visual


# ── Location visual vocabulary ─────────────────────────────────────────────────
# Maps UK city names to iconic/recognisable landmark search terms for Pexels/Pixabay
_LOCATION_VISUAL_TERMS = {
    "manchester":    "Manchester Piccadilly train station street UK city",
    "birmingham":    "Birmingham Bullring city centre street UK",
    "leeds":         "Leeds city centre street Yorkshire UK",
    "bristol":       "Bristol harbour waterfront street UK city",
    "liverpool":     "Liverpool Lime Street docks waterfront UK",
    "sheffield":     "Sheffield city centre street South Yorkshire UK",
    "nottingham":    "Nottingham city centre street UK",
    "leicester":     "Leicester city street UK",
    "coventry":      "Coventry city street cathedral UK",
    "wolverhampton": "Wolverhampton city street West Midlands UK",
    "edinburgh":     "Edinburgh city centre castle street Scotland UK",
    "cardiff":       "Cardiff city centre bay street Wales UK",
    "croydon":       "South London city street busy UK",
    "peckham":       "South London Peckham street busy UK",
    "brixton":       "Brixton South London street market UK",
    "hackney":       "East London street urban UK",
    "east london":   "East London street urban modern UK",
    "canary wharf":  "Canary Wharf London financial district glass towers",
    "cambridge":     "Cambridge city centre UK university street",
    "exeter":        "Exeter city centre street South West UK",
    "luton":         "London Luton airport exterior UK",
    "slough":        "Slough train station commuter UK",
    "milton keynes": "Milton Keynes city centre modern street UK",
    "london":        "London city street busy UK",
}

def _extract_location_visual(story: dict) -> tuple[str, str]:
    """
    Read story_anchor character field for a UK city name.
    Returns (city_name, location_visual_term). Falls back to ("", "").
    """
    anchor   = story.get("story_anchor", {})
    # Check character field, hook text, and full narrative text
    search_text = " ".join([
        anchor.get("character", "") or "",
        story.get("hook", "") or "",
        story.get("problem", "") or "",
    ]).lower()

    for city, visual in sorted(_LOCATION_VISUAL_TERMS.items(), key=lambda x: len(x[0]), reverse=True):
        if city in search_text:
            return city, visual
    return "", ""


# ── African/Nigerian name detection ───────────────────────────────────────────
# When the character has a Nigerian/African name the AI must NEVER show white people.
_AFRICAN_NAMES = {
    # Yoruba
    "tunde", "tunji", "kunle", "sola", "bisi", "kemi", "femi", "segun", "wale",
    "titi", "yemi", "lola", "bola", "dele", "nike", "toyin", "yetunde", "yewande",
    "funke", "funmi", "tolani", "adunni", "remi", "dayo", "tobi", "tola", "deji", "dotun",
    "lanre", "taiwo", "kehinde", "shola", "biodun", "olamide", "bukola", "abiodun",
    "seun", "sade", "ade", "titi", "bola", "yinka", "ronke",
    # Igbo
    "emeka", "chukwu", "ngozi", "adaeze", "chidi", "uche", "nneka", "amaka",
    "nkem", "obiageli", "chioma", "chizoba", "obinna", "ifeanyi", "nonso",
    "chinwe", "ezinne", "obi", "ifeoma", "adaora", "chisom", "ebuka",
    "onyeka", "nkechi", "amara",
    # Hausa / Northern
    "aisha", "fatima", "musa", "ibrahim", "aminu", "hafsat", "zainab",
    "halima", "abdullahi", "bello", "sani", "lawal", "yakubu",
    # Pan-Nigerian / diaspora
    "blessing", "grace", "precious", "favour", "chukwuemeka", "adebayo",
    "adeola", "afolabi", "adewale", "adeyemi", "temitayo", "temitope",
    "oluwatobi", "oluwaseun", "oluwakemi", "oluwafemi", "oluwatosin",
    "olusegun", "olumide", "oluwaseyi", "oluwatobiloba", "olawale",
    "ayooluwa", "ayobami", "ayomide", "adekunle", "adekola",
}


def _extract_name_hint(story: dict) -> str:
    """
    Detect Nigerian/African character name anywhere in the story.
    Returns a mandatory diversity block if found, else empty string.
    """
    anchor = story.get("story_anchor", {})
    # Scan every text field — name may appear in hook, problem, or character field
    search_text = " ".join([
        anchor.get("character", "") or "",
        anchor.get("movement", "") or "",
        story.get("hook", "") or "",
        story.get("hook_v2", "") or "",
        story.get("problem", "") or "",
        story.get("resolution", "") or "",
    ]).lower()

    # Tokenise to avoid partial matches (e.g. "grace" inside "graceful")
    tokens = set(re.findall(r"[a-z]+", search_text))
    matched = tokens & _AFRICAN_NAMES
    if matched:
        # Pick the longest (most specific) matched name
        name = sorted(matched, key=len, reverse=True)[0].capitalize()
        return (
            f"\nCHARACTER ETHNICITY — CRITICAL:\n"
            f"The character's name is \"{name}\" — this is a Nigerian/African person.\n"
            f"EVERY query that includes a person MUST use one of these subject descriptors:\n"
            f"  \"Nigerian woman\", \"Nigerian man\", \"African woman\", \"African man\",\n"
            f"  \"Black British woman\", \"Black traveller\", \"diverse Black people\"\n"
            f"NEVER generate a query that could match a white actor. No exceptions.\n"
            f"Example of WRONG query: \"woman worried face holding parcel\" — no ethnicity!\n"
            f"Example of RIGHT query: \"Nigerian woman worried face holding parcel medium shot\""
        )
    return ""


def _build_specificity_block(story: dict) -> str:
    """
    Build the combined ITEM, CHARACTER, LOCATION, and NAME ETHNICITY block
    injected into scene planner prompts. Empty string if nothing detected.
    """
    item_name, item_visual, role_name, role_visual = _extract_story_visuals(story)
    city_name, city_visual = _extract_location_visual(story)
    name_hint = _extract_name_hint(story)

    lines = []

    if item_visual:
        lines.append(
            f"\nITEM SPECIFICITY — MANDATORY:\n"
            f"This story is about: \"{item_name}\"\n"
            f"Pexels search term for this item: \"{item_visual}\"\n"
            f"Rules:\n"
            f"  - Scene 0 (hook): protagonist WITH the item — holding it, showing it, or looking at it\n"
            f"    Example: \"Nigerian woman holding {item_visual} worried medium shot\"\n"
            f"  - Scene 2 or 3 (problem): the item visible while protagonist looks stressed or shocked\n"
            f"    Example: \"Black man {item_visual} looking shocked phone medium shot\"\n"
            f"  - Scene 7 (lesson): recipient RECEIVING or WEARING the item — happy, relieved\n"
            f"    Example: \"Nigerian person receiving {item_visual} door smiling medium shot\"\n"
            f"  Every other scene may use transport/travel visuals as per the blueprint."
        )

    if role_visual:
        lines.append(
            f"\nCHARACTER APPEARANCE — MANDATORY:\n"
            f"The protagonist is a \"{role_name}\"\n"
            f"Use this visual for Scene 0 or Scene 1: \"{role_visual}\"\n"
            f"Example: \"{role_visual} medium shot\""
        )

    if city_visual:
        lines.append(
            f"\nLOCATION SPECIFICITY — MANDATORY:\n"
            f"The protagonist is based in/from: \"{city_name.title()}\"\n"
            f"Scene 0 or Scene 1 MUST include a recognisable {city_name.title()} landmark or street scene.\n"
            f"Use this search term for that scene: \"{city_visual}\"\n"
            f"Example: \"{city_visual} medium shot\""
        )

    if name_hint:
        lines.append(name_hint)

    return "\n".join(lines)

# ── Pillar blueprints — fixed narrative scene order per content pillar ─────────
# Each list entry describes what the clip at that position MUST show.
# The Scene Planner AI uses these as hard constraints when writing search queries.
PILLAR_BLUEPRINTS = {
    "supply_chain": [
        "Black British woman in UK home or office — looks worried, holds a small item to send",
        "Phone screen showing an expensive courier price — Nigerian woman reacting shocked",
        "African woman on phone call looking frustrated at a high delivery price",
        "Black man at train station handing small parcel to a traveller — wide shot",
        "African traveller seated on a train or flight — relaxed, parcel with them",
        "Black traveller arriving in Lagos — airport arrivals hall wide shot",
        "Nigerian woman smiling at door receiving small parcel — friendly handover",
        "Wide London or Lagos cityscape — confident aspirational wide shot",
    ],
    "family": [
        "Nigerian woman in UK home — holds small gift cream or medicine for family — medium shot",
        "Black woman at courier counter reacting to expensive price — shocked medium shot",
        "African woman upset or worried on phone at home — medium shot",
        "Black man at train station handing small parcel to traveller — friendly wide shot",
        "African traveller on flight heading to Nigeria — window seat relaxed medium shot",
        "Nigerian traveller arriving at home doorstep — warm family reunion wide shot",
        "Black family member smiling receiving a small gift — warm happy medium shot",
        "Wide London residential street or Lagos neighbourhood — people walking",
    ],
    "airport": [
        "Busy airport departures hall — African and Black travellers moving with luggage wide shot",
        "Customs security checkpoint — Black traveller bags being checked wide shot",
        "Nigerian woman looking stressed at airport counter medium shot",
        "Black traveller at departure gate with cabin luggage and small parcel medium shot",
        "Wide airplane taking off from runway — dramatic wide shot",
        "Airport arrivals hall — Black travellers walking out confidently wide shot",
        "African woman friendly parcel handover at airport arrivals smiling wide shot",
        "Wide aerial international airport or Lagos skyline wide shot",
    ],
    "airport_deliveries": [
        "Black woman at pharmacy counter collecting prescription — medium shot",
        "Nigerian woman holding small medicine box prescription packet — medium shot",
        "African man on phone call looking worried — explaining urgent problem medium shot",
        "Black traveller at train station receiving small medical parcel from sender wide shot",
        "African traveller on flight window seat plane in air medium shot",
        "Nigerian traveller walking through customs arrivals confidently medium shot",
        "Black person smiling at door receiving medication parcel — relief medium shot",
        "Wide London city street — diverse people walking confident wide shot",
    ],
    "community": [
        "Nigerian man or woman in London street or apartment — animated talking medium shot",
        "Two Black people talking warmly — community gathering or cafe wide shot",
        "African woman using phone app in public — smiling satisfied medium shot",
        "Black traveller at train station receiving parcel from Nigerian community member wide shot",
        "African traveller on train or at airport gate heading out medium shot",
        "Nigerian person arriving home with parcel front door medium shot",
        "Black family happy handover at door — smiling recipient receives parcel medium shot",
        "Wide London street or community space — diverse Black people welcoming wide shot",
    ],
    "smart": [
        "Black British professional at London airport departure lounge confident medium shot",
        "African man on phone checking app looking pleased at earnings medium shot",
        "Wide airport departure gate — Black traveller with cabin luggage confident wide shot",
        "Nigerian woman handing small parcel to Black traveller at train station wide shot",
        "African traveller on flight relaxed looking out window medium shot",
        "Black traveller arriving Lagos airport confidently exiting wide shot",
        "Two Black people parcel handover both smiling mutual benefit wide shot",
        "Wide Lagos or London skyline — successful aspirational wide shot",
    ],
    "travel_hacks": [
        "Black British traveller at airport departure lounge checking phone — excited realisation medium shot",
        "African traveller with cabin luggage at airport gate wide shot",
        "Nigerian woman shocked face looking at expensive courier price on phone medium shot",
        "Black traveller receiving small parcel from Nigerian sender at train station wide shot",
        "African man handing parcel to traveller airport departures smiling wide shot",
        "Airplane taking off runway wide dramatic shot",
        "Black traveller arrivals hall Lagos airport confident walking medium shot",
        "Nigerian person at door receiving parcel smiling relief wide shot",
    ],
    "logistics_stories": [
        "Wide cargo ship at sea or shipping containers stacked at port wide shot",
        "Black woman at courier counter reacting to high price surprised medium shot",
        "African man on phone frustrated logistics problem medium shot",
        "Wide Black traveller at airport handing parcel to Nigerian recipient wide shot",
        "African traveller on flight or train — parcel safely with them medium shot",
        "Black traveller walking through arrivals hall confidently wide shot",
        "Nigerian woman smiling receiving parcel at door medium shot",
        "Wide busy port cargo facility or London Lagos cityscape wide shot",
    ],
    "cost_pain": [
        "Nigerian woman in UK home looking shocked holding courier price quote medium shot",
        "Black woman at laptop or phone — expensive courier website shown on screen medium shot",
        "African man at courier counter shocked at high delivery price medium shot",
        "Nigerian woman on phone call upset about delivery cost medium shot",
        "Black traveller and Nigerian sender at train station parcel handover wide shot",
        "African traveller on flight with parcel relaxed window seat medium shot",
        "Black woman on phone smiling — happy with affordable delivery medium shot",
        "Diverse Black people London street confident celebrating wide shot",
    ],
    "cultural_earn": [
        "Black British traveller at Heathrow airport confident departure lounge medium shot",
        "African man at airport check-in with cabin luggage earning money on phone medium shot",
        "Nigerian woman talking animatedly on phone — excited about earning medium shot",
        "Two Black people shaking hands airport or station — traveller and sender wide shot",
        "African traveller on flight smiling relaxed window seat medium shot",
        "Black traveller arriving Lagos airport earning accomplished wide shot",
        "Two African people mutual parcel handover both smiling satisfied wide shot",
        "Wide London or Lagos street — successful Black diaspora people wide shot",
    ],
    "urgent_medical": [
        "Nigerian woman at pharmacy looking worried holding prescription medium shot",
        "Black woman on phone urgently explaining medical situation medium shot",
        "African man at pharmacy counter medication unavailable worried medium shot",
        "Nigerian family member on video call worried urgent expression medium shot",
        "Black traveller at train station receiving small medical parcel from sender wide shot",
        "African traveller on flight with small parcel window seat relaxed medium shot",
        "Nigerian woman at door receiving medication parcel — relief smiling medium shot",
        "Wide London street — diverse Black people community warm wide shot",
    ],
    "brand_authority": [
        "Black British professional confident smiling at London office medium shot",
        "Wide shot diverse Black diaspora people on London high street wide shot",
        "Nigerian woman on phone looking confident and satisfied medium shot",
        "Nigerian man comparing delivery options on phone looking pleased medium shot",
        "African man and Black woman friendly professional parcel handover wide shot",
        "Black traveller at airport confident with luggage departure lounge medium shot",
        "Nigerian couple receiving parcel at door both smiling wide shot",
        "Diverse group Black people celebrating community London wide shot",
    ],
}

# Safe fallback queries — used when the API call fails
_FALLBACK_QUERIES = [
    "Black British woman london flat worried medium shot",
    "African travellers airport departures wide shot",
    "Nigerian woman post office counter shocked medium shot",
    "Black traveller train station luggage wide shot",
    "African woman phone call worried medium shot",
    "Black man parcel handover train station smiling wide shot",
    "African man plane window seat flight medium shot",
    "diverse Black people london street wide establishing shot",
]


def plan_scenes(story: dict, pillar: str) -> list[str]:
    """
    Stage 2: convert a story narrative into 8 scene-specific Pexels search queries.
    Always uses Claude Haiku (fast, cheap) regardless of the STORY_MODEL setting.
    Returns a list of 8 query strings. Falls back to safe defaults if the API fails.
    """
    blueprint = PILLAR_BLUEPRINTS.get(pillar, PILLAR_BLUEPRINTS["supply_chain"])
    blueprint_lines = "\n".join(f"  Scene {i}: {desc}" for i, desc in enumerate(blueprint))

    airport_rule = ""
    if pillar in ("airport", "airport_deliveries"):
        airport_rule = "\nAIRPORT PILLAR RULE — MANDATORY: EVERY one of the 8 queries must contain a specific airport visual: departures hall, runway, airport gate, check-in counter, arrivals hall, airplane taking off, plane landing, or airport exterior. No exceptions.\n"

    specificity_block = _build_specificity_block(story)

    prompt = f"""You are a Scene Planner for a short social media video. Convert this story into 8 Pexels video search queries.

STORY:
  Hook: {story.get('hook', '')}
  Problem: {story.get('problem', '')}
  Stakes: {story.get('stakes', '')}
  Resolution: {story.get('resolution', '')}
  Lesson: {story.get('lesson', '')}

SCENE BLUEPRINT — follow this order EXACTLY. Each query must visually match its scene:
{blueprint_lines}
{airport_rule}{specificity_block}

RULES FOR EVERY QUERY (non-negotiable):
- Maximum 6 words per query
- ALWAYS use "medium shot" OR "wide shot" in the query — no exceptions
- NEVER use "close up", "close-up", "extreme", or "face only"
- NEVER use animals: dog, cat, horse, farm, zoo, bird, wildlife, livestock
- NEVER use food: restaurant, kitchen, grocery, meal, cooking, cafe
- NEVER use Christmas, Halloween, pumpkin, Santa
- NEVER name courier companies: DHL, FedEx, Royal Mail, Hermes, UPS

DIVERSITY PREFERENCE:
BootHop serves the UK-Nigeria diaspora. Where the story character is Nigerian or African,
all person-focused queries MUST reflect this. Preferred identifiers:
  "Black British woman", "Nigerian woman", "African man", "Black traveller",
  "African couple", "Black man", "Nigerian man", "diverse Black people"
If the character has an English name, queries may show any appropriate ethnicity.

DYNAMIC CONTENT (prefer for hook scene 0 and lesson scene 7):
  Use active subjects: "woman dancing celebration", "man talking animated",
  "people celebrating street", "woman laughing phone" — not static posed shots.

AIRPORT PILLAR — MANDATORY (if pillar is airport or airport_deliveries):
  EVERY query must include a specific airport visual: departures hall, runway, gate,
  check-in counter, arrivals hall, airplane taking off, plane landing, or airport exterior.
  Examples:
    "African travellers busy airport departures hall wide shot"
    "airplane taking off runway dramatic wide shot"
    "Black traveller airport departure gate cabin luggage medium shot"
    "airport arrivals hall Nigerian family reunion smiling wide shot"

CORRECT examples (any pillar):
  "Black British woman london flat worried medium shot"
  "Nigerian woman pharmacy counter shocked medium shot"
  "African man train station parcel handover wide shot"
  "Black traveller plane window seat medium shot"
  "Nigerian woman door smiling parcel medium shot"
  "diverse Black people london street wide shot"
  "African woman dancing celebration wide shot"

WRONG — never do this:
  "woman close up face shocked"   ← no ethnicity, close-up
  "DHL courier tracking parcel"   ← brand name
  "farm green field landscape"    ← no people, banned
  "airport crowd far away wide"   ← vague, no people descriptor

Return ONLY valid JSON with no markdown:
{{"visual_queries": ["q0","q1","q2","q3","q4","q5","q6","q7"]}}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group())
            queries = data.get("visual_queries", [])
            if len(queries) == 8:
                print(f"  [ScenePlanner] Planned {len(queries)} scenes for pillar: {pillar}")
                for i, q in enumerate(queries):
                    print(f"    Scene {i}: {q}")
                return queries
            print(f"  [ScenePlanner] Expected 8 queries, got {len(queries)} — using fallback")
    except Exception as e:
        print(f"  [ScenePlanner] Failed: {e} — using fallback queries")

    return list(_FALLBACK_QUERIES)


def plan_scenes_v2(story: dict, pillar: str, v1_queries: list[str]) -> list[str]:
    """
    Scene Planner for V2 — generates a fresh set of 8 queries for the same pillar
    but avoids repeating V1's queries. Rotates blueprint perspective slightly.
    """
    blueprint = PILLAR_BLUEPRINTS.get(pillar, PILLAR_BLUEPRINTS["supply_chain"])
    blueprint_lines = "\n".join(f"  Scene {i}: {desc}" for i, desc in enumerate(blueprint))
    v1_str = "\n".join(f"  - {q}" for q in v1_queries[:8])

    airport_rule = ""
    if pillar in ("airport", "airport_deliveries"):
        airport_rule = "\nAIRPORT RULE: EVERY query must include a specific airport visual (departures hall, runway, gate, check-in, arrivals hall, airplane, plane). No exceptions.\n"

    specificity_block = _build_specificity_block(story)

    prompt = f"""You are a Scene Planner for a social media video. Generate a SECOND SET of 8 Pexels search queries for the same story.

STORY:
  Hook: {story.get('hook_v2', story.get('hook', ''))}
  Problem: {story.get('problem', '')}
  Resolution: {story.get('resolution', '')}
  Lesson: {story.get('lesson_v2', story.get('lesson', ''))}

SCENE BLUEPRINT (same structure as V1 — follow this order):
{blueprint_lines}

V1 already used these queries — do NOT repeat them, find fresh alternatives:
{v1_str}
{specificity_block}
RULES: same as V1 — medium/wide shots only, no close-ups, no animals, no food, no courier brand names.{airport_rule}

Return ONLY valid JSON:
{{"visual_queries": ["q0","q1","q2","q3","q4","q5","q6","q7"]}}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group())
            queries = data.get("visual_queries", [])
            if len(queries) == 8:
                print(f"  [ScenePlanner-V2] Planned {len(queries)} fresh scenes for pillar: {pillar}")
                return queries
    except Exception as e:
        print(f"  [ScenePlanner-V2] Failed: {e} — rotating V1 queries")

    # Fallback: rotate V1 queries by 4
    return v1_queries[4:] + v1_queries[:4]
