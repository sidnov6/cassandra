"""Anthropic LLM wrapper with graceful fallback.

If ANTHROPIC_API_KEY is set, agents reason with the model using the §6.4 prompt templates
and return schema-validated JSON. If not, every agent runs its deterministic rule engine,
so the entire pipeline produces a full, grounded dossier with zero external dependencies.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..config import ANTHROPIC_API_KEY, LLM_ENABLED, LLM_MODEL


def llm_available() -> bool:
    return LLM_ENABLED


def call_json(system: str, user: str, max_tokens: int = 1500) -> Optional[Any]:
    """Call Claude and parse a JSON object/array from the response. None on any failure."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=LLM_MODEL, max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return _extract_json(text)
    except Exception:
        return None


def call_text(system: str, user: str, max_tokens: int = 1800) -> Optional[str]:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=LLM_MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
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
