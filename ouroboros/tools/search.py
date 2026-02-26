"""Web search tool."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry

# OpenAI Responses API uses native model names (no "openai/" prefix).
# Supported web_search models as of 2026: gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano
_WEBSEARCH_MODEL_MAP = {
    "openai/gpt-4.1-mini": "gpt-4.1-mini",
    "openai/gpt-4.1": "gpt-4.1",
    "openai/gpt-4.1-nano": "gpt-4.1-nano",
    "openai/gpt-4o": "gpt-4o",
    "openai/gpt-4o-mini": "gpt-4o-mini",
    "openai/gpt-5": "gpt-4.1",  # fallback
    "gpt-5": "gpt-4.1",         # fallback
}
_DEFAULT_MODEL = "gpt-4o-mini"


def _resolve_model(raw: str) -> str:
    """Strip OpenRouter-style prefix and map to valid OpenAI Responses API model."""
    if raw in _WEBSEARCH_MODEL_MAP:
        return _WEBSEARCH_MODEL_MAP[raw]
    # Strip "openai/" prefix if present
    if raw.startswith("openai/"):
        return raw[len("openai/"):]
    return raw


def _web_search(ctx: ToolContext, query: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return json.dumps({"error": "OPENAI_API_KEY not set; web_search unavailable."})
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        raw_model = os.environ.get("OUROBOROS_WEBSEARCH_MODEL", _DEFAULT_MODEL)
        model = _resolve_model(raw_model)
        resp = client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            input=query,
        )
        d = resp.model_dump()
        text = ""
        for item in d.get("output", []) or []:
            if item.get("type") == "message":
                for block in item.get("content", []) or []:
                    if block.get("type") in ("output_text", "text"):
                        text += block.get("text", "")
        return json.dumps({"answer": text or "(no answer)"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": repr(e)}, ensure_ascii=False)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": "Search the web via OpenAI Responses API. Returns JSON with answer + sources.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
            }, "required": ["query"]},
        }, _web_search),
    ]
