from llama_index.core.tools import FunctionTool
import requests
from typing import Optional


def x402_discover(
    query: str,
    max_price_usd: float = 0.50,
    network: str = "base"
) -> str:
    """
    Find the best available x402-payable API endpoint for a capability.

    Use this whenever you need to access any paid API service.
    Returns endpoint URL, pricing, quality signals, and a Python code snippet.

    Args:
        query: What capability you need (e.g. 'web search', 'image generation', 'data enrichment')
        max_price_usd: Maximum acceptable price per call in USD (default 0.50)
        network: Blockchain network preference: 'base', 'ethereum', or 'solana' (default 'base')

    Returns:
        Service details including URL, price, uptime, and usage snippet
    """
    try:
        resp = requests.get("https://x402-discovery-api.onrender.com/catalog", timeout=10)
        catalog = resp.json()
        services = catalog.get("services", [])

        query_lower = query.lower()
        matching = [
            s for s in services
            if s.get("price_per_call", 999) <= max_price_usd and
            any(word in s.get("description", "").lower() or
                word in " ".join(s.get("capability_tags", [])).lower() or
                word in s.get("name", "").lower()
                for word in query_lower.split())
        ]

        matching.sort(key=lambda s: (-s.get("uptime_pct", 0), s.get("avg_latency_ms", 9999)))

        if not matching:
            return f"No x402 services found for '{query}'. Browse at https://x402-discovery-api.onrender.com/catalog"

        best = matching[0]
        return (
            f"Service: {best.get('name')}\n"
            f"URL: {best.get('endpoint_url')}\n"
            f"Price: ${best.get('price_per_call')}/call\n"
            f"Uptime: {best.get('uptime_pct', 'N/A')}% | Latency: {best.get('avg_latency_ms', 'N/A')}ms\n"
            f"Description: {best.get('description')}\n"
            f"Snippet:\n{best.get('sdk_snippet_python', 'See documentation')}"
        )
    except Exception as e:
        return f"Discovery error: {e}"


def get_x402_discovery_tool(discovery_api_url: str = "https://x402-discovery-api.onrender.com"):
    """Get x402 discovery as a LlamaIndex FunctionTool."""
    return FunctionTool.from_defaults(
        fn=x402_discover,
        name="x402_discover",
        description=(
            "Find and return the best available x402-payable API endpoint for any capability. "
            "Use when you need to access a paid API service, data source, or compute capability. "
            "Returns endpoint URL, price, quality signals, and usage code snippet."
        )
    )
