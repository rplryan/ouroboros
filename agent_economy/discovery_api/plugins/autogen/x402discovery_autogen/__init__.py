"""x402 Discovery integration for AutoGen agents.

Provides a plain Python function + JSON schema that AutoGen agents can use
to discover x402-payable API services at runtime.

Usage:
    from x402discovery_autogen import x402_discover_function, X402_DISCOVERY_TOOL_SCHEMA
    import autogen

    assistant = autogen.AssistantAgent(
        name="assistant",
        llm_config={
            "functions": [X402_DISCOVERY_TOOL_SCHEMA],
            "config_list": [{"model": "gpt-4o-mini", "api_key": "..."}],
        },
    )
    user = autogen.UserProxyAgent(
        name="user",
        function_map={"x402_discover": x402_discover_function},
    )
    user.initiate_chat(assistant, message="Find a web research API under $0.10")
"""
from __future__ import annotations

from typing import Optional

import requests

DISCOVERY_BASE_URL = "https://x402-discovery-api.onrender.com"


def x402_discover_function(
    capability: Optional[str] = None,
    max_price_usd: float = 0.50,
    query: Optional[str] = None,
) -> str:
    """Find x402-payable API services matching a capability or free-text query.

    Args:
        capability: Optional capability filter. One of: research, data, compute,
                    monitoring, verification, routing, storage, translation,
                    classification, generation, extraction, summarization,
                    enrichment, validation, other.
        max_price_usd: Maximum price per call in USD (default 0.50).
        query: Free-text search against service name and description.

    Returns:
        Top 5 matching services ranked by quality, with pricing and endpoint URLs.
    """
    try:
        resp = requests.get(f"{DISCOVERY_BASE_URL}/catalog", timeout=15)
        resp.raise_for_status()
        services = resp.json().get("services", [])
    except requests.RequestException as e:
        return f"Discovery failed: {e}"

    if capability:
        services = [
            s for s in services
            if capability in s.get("capability_tags", [])
            or s.get("category") == capability
        ]
    services = [
        s for s in services
        if s.get("price_per_call", 999) <= max_price_usd
    ]
    if query:
        q = query.lower()
        services = [
            s for s in services
            if q in s.get("name", "").lower()
            or q in s.get("description", "").lower()
        ]

    order = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
    services.sort(key=lambda s: order.get(s.get("quality_tier", "unverified"), 3))
    top5 = services[:5]

    if not top5:
        return f"No services found for capability={capability!r}, max_price_usd={max_price_usd}."

    lines = [f"Top {len(top5)} x402 services:\n"]
    for i, s in enumerate(top5, 1):
        lines.append(
            f"{i}. {s.get('name')} [{s.get('quality_tier', 'unverified').upper()}]\n"
            f"   ID: {s.get('service_id')}  Price: ${s.get('price_per_call')}/call\n"
            f"   URL: {s.get('endpoint_url', s.get('url'))}\n"
            f"   {s.get('description', '')}\n"
        )
    return "\n".join(lines)


# JSON schema for AutoGen's `functions` list in llm_config
X402_DISCOVERY_TOOL_SCHEMA = {
    "name": "x402_discover",
    "description": (
        "Find x402-payable API services that can perform a given task. "
        "Use this when you need a paid external service for research, data processing, "
        "AI generation, monitoring, or any specialized capability. "
        "Returns up to 5 quality-ranked results with endpoint URLs and pricing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "capability": {
                "type": "string",
                "description": (
                    "Capability category to filter by. One of: research, data, compute, "
                    "monitoring, verification, routing, storage, translation, classification, "
                    "generation, extraction, summarization, enrichment, validation, other."
                ),
            },
            "max_price_usd": {
                "type": "number",
                "description": "Maximum price per call in USD. Default 0.50.",
                "default": 0.50,
            },
            "query": {
                "type": "string",
                "description": "Free-text search against service name and description.",
            },
        },
        "required": [],
    },
}

__all__ = ["x402_discover_function", "X402_DISCOVERY_TOOL_SCHEMA", "DISCOVERY_BASE_URL"]
