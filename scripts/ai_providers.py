"""
Shared AI fallback-chain helper — OpenAI -> Gemini -> Claude, JSON responses.

Added 2026-10-08 as part of the dynamic client provisioning work (see
.claude/plans/fluttering-singing-perlis.md). The exact same fallback chain
already exists copy-pasted independently in generate_content.py,
generate_content_d818.py, and g_inspired_content.py — this module factors it
out for the two NEW callers (profile_compiler.py, generate_content_generic.py)
without touching any of those three existing files, so none of the 4 live
clients are affected by this module existing.
"""

import json, re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY
import requests


def _call_claude(prompt: str, model: str = "claude-sonnet-4-6", max_tokens: int = 2000) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_openai(prompt: str, model: str = "gpt-4o", max_tokens: int = 2000) -> str:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_gemini(prompt: str, model: str = "gemini-3.8-flash", max_tokens: int = 2000) -> str:
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"No JSON in response: {raw[:200]}")
    return json.loads(m.group())


def call_structured(prompt: str, max_tokens: int = 2000) -> dict:
    """OpenAI -> Gemini -> Claude fallback chain, same order BootHop's
    generate_content.py uses. Returns parsed JSON. Raises RuntimeError only
    if every provider fails — callers should not silently swallow this."""
    last_err = None
    for name, fn in (("openai", _call_openai), ("gemini", _call_gemini), ("claude", _call_claude)):
        try:
            print(f"  [ai_providers] Using {name}")
            raw = fn(prompt, max_tokens=max_tokens)
            return _parse_json(raw)
        except Exception as e:
            print(f"  [ai_providers] {name} failed: {e} — trying next")
            last_err = e
    raise RuntimeError(f"All AI providers failed. Last error: {last_err}")
