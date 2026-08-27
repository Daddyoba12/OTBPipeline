"""
tts_nigerian.py — TTS engine for OTB_Pipeline.

Two functions:
  generate_nigerian_tts()  — for BootHop content (Nigerian English accent)
  generate_american_tts()  — for G-Inspired content (American English, uses ElevenLabs subscription)

── Nigerian TTS priority ─────────────────────────────────────────────────────
  1. Azure TTS   → en-NG-EzinneNeural / en-NG-AbeoNeural (real Nigerian English)
                   Free 500k chars/month. Best choice for Nigerian accent.
  2. ElevenLabs  → fallback if Azure not configured (not Nigerian-accented)
  3. OpenAI TTS  → last resort

── American TTS priority (G-Inspired) ────────────────────────────────────────
  1. ElevenLabs  → uses your subscription, sounds great for American English
  2. OpenAI TTS  → fallback

── SETUP ─────────────────────────────────────────────────────────────────────

Azure TTS (Nigerian voice — free 500k chars/month):
  1. portal.azure.com → Create resource → Azure AI Services → Speech Service → Free F0
  2. Copy Key 1 and Region from the resource overview
  3. Add to keys.env:
       AZURE_TTS_KEY=your_key_here
       AZURE_TTS_REGION=uksouth

ElevenLabs (already subscribed — used for G-Inspired American English):
  1. elevenlabs.io → go to your Voices → pick any English voice you like
  2. Copy its Voice ID
  3. Add to keys.env:
       ELEVENLABS_API_KEY=your_key_here
       ELEVENLABS_VOICE_ID=the_voice_id

Nigerian voices from Azure:
  Female: en-NG-EzinneNeural  (warm, clear Nigerian English)
  Male:   en-NG-AbeoNeural    (confident Nigerian English)
"""

import sys
import xml.sax.saxutils as _xmlesc
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    OPENAI_API_KEY,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_LAGOS_F,
    ELEVENLABS_VOICE_LAGOS_M,
    ELEVENLABS_VOICE_OTHER,
    AZURE_TTS_KEY,
    AZURE_TTS_REGION,
)

_LAGOS_KEYWORDS = {
    "lagos", "ikeja", "victoria island", "vi ", "lekki", "ajah", "surulere",
    "yaba", "ikorodu", "festac", "oshodi", "agege", "apapa", "mainland",
    "island", "abuja", "ibadan", "ph ", "port harcourt", "enugu", "kano",
    "naija", "nigeria",
}

def _pick_elevenlabs_voice(text: str, gender: str) -> str:
    """Pick ElevenLabs voice based on story location and character gender."""
    lower = text.lower()
    is_lagos = any(kw in lower for kw in _LAGOS_KEYWORDS)
    if is_lagos:
        return ELEVENLABS_VOICE_LAGOS_F if gender == "female" else ELEVENLABS_VOICE_LAGOS_M
    return ELEVENLABS_VOICE_OTHER

_AZURE_NG_FEMALE = "en-NG-EzinneNeural"
_AZURE_NG_MALE   = "en-NG-AbeoNeural"


def generate_nigerian_tts(text: str, out_path: Path, gender: str = "female") -> bool:
    """
    Nigerian-accented TTS for BootHop content.
    Priority: ElevenLabs (context-aware voice) → edge-tts en-NG → Azure en-NG → OpenAI (last resort)

    Voice routing:
      Lagos + female  → Nigerian woman pigin
      Lagos + male    → Naija english
      Other country   → Boothop1
    """
    if not text.strip():
        return False

    # ElevenLabs — primary, context-aware voice selection
    if ELEVENLABS_API_KEY:
        voice_id = _pick_elevenlabs_voice(text, gender)
        if _elevenlabs(text, out_path, voice_id=voice_id):
            return True

    # edge-tts — backup (real Nigerian English neural voice, free)
    if _edge_tts(text, out_path, gender):
        return True

    # Azure — tertiary (real Nigerian English, free 500k chars/month)
    if AZURE_TTS_KEY:
        voice = _AZURE_NG_FEMALE if gender == "female" else _AZURE_NG_MALE
        if _azure(text, out_path, voice):
            return True

    # OpenAI — last resort
    if OPENAI_API_KEY:
        if _openai(text, out_path, voice="onyx"):
            return True

    print("  [TTS-NG] All providers failed — no audio generated")
    return False


def generate_american_tts(text: str, out_path: Path, gender: str = "female") -> bool:
    """
    American English TTS for G-Inspired content.
    Priority: ElevenLabs (subscription) → OpenAI
    """
    if not text.strip():
        return False

    # ElevenLabs — subscription is well-suited to American English
    if ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID:
        if _elevenlabs(text, out_path):
            return True

    # OpenAI fallback
    if OPENAI_API_KEY:
        ov = "nova" if gender == "female" else "onyx"
        if _openai(text, out_path, voice=ov):
            return True

    print("  [TTS-AM] All providers failed — no audio generated")
    return False


def _edge_tts(text: str, out_path: Path, gender: str = "female") -> bool:
    voice = "en-NG-EzinneNeural" if gender == "female" else "en-NG-AbeoNeural"
    try:
        import asyncio, edge_tts
        async def _run():
            comm = edge_tts.Communicate(text, voice)
            await comm.save(str(out_path))
        asyncio.run(_run())
        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"  [TTS] edge-tts {voice} — {len(text)} chars — {out_path.name}")
            return True
    except Exception as e:
        print(f"  [TTS] edge-tts failed: {e}")
    return False


def _elevenlabs(text: str, out_path: Path, voice_id: str = ELEVENLABS_VOICE_OTHER) -> bool:
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.50,
                    "similarity_boost": 0.75,
                    "style": 0.40,
                    "use_speaker_boost": True,
                },
            },
            timeout=30,
        )
        r.raise_for_status()
        out_path.write_bytes(r.content)
        print(f"  [TTS] ElevenLabs — {len(text)} chars — {out_path.name}")
        return True
    except Exception as e:
        print(f"  [TTS] ElevenLabs failed: {e}")
    return False


def _azure(text: str, out_path: Path, voice: str = _AZURE_NG_FEMALE) -> bool:
    ssml = (
        f'<speak version="1.0" xml:lang="en-NG">'
        f'<voice name="{voice}">'
        f'<prosody rate="+5%">{_xmlesc.escape(text)}</prosody>'
        f'</voice></speak>'
    )
    try:
        region = AZURE_TTS_REGION or "eastus"
        r = requests.post(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": AZURE_TTS_KEY,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            },
            data=ssml.encode("utf-8"),
            timeout=30,
        )
        r.raise_for_status()
        out_path.write_bytes(r.content)
        print(f"  [TTS] Azure {voice} — {len(text)} chars — {out_path.name}")
        return True
    except Exception as e:
        print(f"  [TTS] Azure failed: {e}")
    return False


def _openai(text: str, out_path: Path, voice: str = "onyx") -> bool:
    try:
        r = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "tts-1-hd", "input": text, "voice": voice, "speed": 1.05},
            timeout=30,
        )
        r.raise_for_status()
        out_path.write_bytes(r.content)
        print(f"  [TTS] OpenAI {voice} (fallback) — {len(text)} chars — {out_path.name}")
        return True
    except Exception as e:
        print(f"  [TTS] OpenAI failed: {e}")
    return False
