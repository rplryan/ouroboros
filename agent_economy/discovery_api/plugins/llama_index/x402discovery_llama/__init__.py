"""x402 Discovery tool for LlamaIndex agents.

Exposes x402 service discovery as a LlamaIndex FunctionTool so any
LlamaIndex agent or query engine can find paid API services at runtime.

Usage:
    from x402discovery_llama import X402DiscoveryTool
    from llama_index.core.agent import ReActAgent
    from llama_index.llms.openai import OpenAI

    llm = OpenAI(model="gpt-4o-mini")
    agent = ReActAgent.from_tools([X402DiscoveryTool], llm=llm, verbose=True)
    response = agent.chat("Find a data enrichment service under $0.05 per call")
"""
from __future__ import annotations

from typing import Optional

import requests
from llama_index.core.tools import FunctionTool

DISCOVERY_BASE_URL = "https://x402-discovery-api.onrender.com"


def _discover(
    capability: Optional[str] = None,
    max_price_usd: float = 0.50,
    query: Optional[str] = None,
) -> str:
    """Find x402-payable API services matching a capability or free-text query.

    Args:
        capability: Optional capability filter. Options: research, data, compute,
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


# LlamaIndex FunctionTool wraps the plain Python function
X402DiscoveryTool = FunctionTool.from_defaults(
    fn=_discover,
    name="x402_discover",
    description=(
        "Find x402-payable API services for research, data, computation, or any "
        "specialized capability. Returns quality-ranked results with endpoint URLs "
        "and pricing. Use when you need to delegate a task to a paid external service."
    ),
)

__all__ = ["X402DiscoveryTool", "DISCOVERY_BASE_URL"]
