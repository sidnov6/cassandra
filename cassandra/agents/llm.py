"""Anthropic LLM wrapper with graceful fallback.

If ANTHROPIC_API_KEY is set, agents reason with the model using the §6.4 prompt templates
and return schema-validated JSON. If not, every agent runs its deterministic rule engine,
so the entire pipeline produces a full, grounded dossier with zero external dependencies.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..config import (ANTHROPIC_API_KEY, GROQ_API_KEY, GROQ_MODEL, LLM_ENABLED,
                      LLM_MODEL, LLM_PROVIDER)


def llm_available() -> bool:
    return LLM_ENABLED


def _groq_chat(system: str, user: str, max_tokens: int) -> Optional[str]:
    """Groq's OpenAI-compatible chat completions (httpx, no extra dependency), with a short
    backoff on 429 so the agent graph's burst of calls degrades gracefully under free-tier
    rate limits rather than all falling back at once."""
    import time

    import httpx
    for attempt in range(3):
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": GROQ_MODEL, "max_tokens": max_tokens, "temperature": 0.2,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=45,
        )
        if r.status_code == 429 and attempt < 2:
            time.sleep(1.2 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    return None


def _anthropic_chat(system: str, user: str, max_tokens: int) -> Optional[str]:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(model=LLM_MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _chat(system: str, user: str, max_tokens: int) -> Optional[str]:
    if LLM_PROVIDER == "groq":
        return _groq_chat(system, user, max_tokens)
    if LLM_PROVIDER == "anthropic":
        return _anthropic_chat(system, user, max_tokens)
    return None


def call_json(system: str, user: str, max_tokens: int = 1500) -> Optional[Any]:
    """Call the active LLM and parse a JSON object/array. None on any failure."""
    if not LLM_ENABLED:
        return None
    try:
        return _extract_json(_chat(system, user, max_tokens) or "")
    except Exception:
        return None


def call_text(system: str, user: str, max_tokens: int = 1800) -> Optional[str]:
    if not LLM_ENABLED:
        return None
    try:
        return _chat(system, user, max_tokens)
    except Exception:
        return None


def _extract_json(text: str) -> Optional[Any]:
    text = text.strip()
    # strip code fences
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # find first balanced [ ... ] or { ... }
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i = text.find(open_c)
        j = text.rfind(close_c)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                continue
    return None
