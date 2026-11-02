"""response_utils.py — helpers for reading OpenAI-compatible responses.

Reasoning models (Nemotron, DeepSeek-R1, QwQ, Phi-4-reasoning) can return
``content: null`` and place the answer in ``reasoning_content``. Every place
that reads ``choices[0].message.content`` must use this helper instead.
"""
from __future__ import annotations
from typing import Any, Dict


def _extract_choice_text(resp: Dict[str, Any]) -> str:
    """Extract assistant text from an OpenAI-compat chat completion response."""
    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(msg, dict):
        return str(msg) if msg else ""
    text = msg.get("content")
    if text is None or (isinstance(text, str) and not text.strip()):
        for alt in ("reasoning_content", "reasoning", "text"):
            val = msg.get(alt)
            if val and str(val).strip():
                return str(val)
        return ""
    return text


def extract_choice_text(resp: Dict[str, Any]) -> str:
    """Public alias."""
    return _extract_choice_text(resp)
