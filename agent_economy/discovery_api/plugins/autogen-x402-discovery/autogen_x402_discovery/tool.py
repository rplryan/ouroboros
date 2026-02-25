import requests
from typing import Optional


def x402_discover(
    query: str,
    max_price_usd: float = 0.50,
) -> str:
    """
    Find the best available x402-payable API endpoint for any capability.

    Use this tool whenever you need to access any paid API service, data source,
    or compute capability. Discovers live x402 services with quality signals.

    Args:
        query (str): Natural language description of the capability needed
        max_price_usd (float): Maximum price per call in USD (default: 0.50)

    Returns:
        str: Service details with URL, price, quality metrics, and usage snippet
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
                word in " ".join(s.get("capability_tags", [])).lower()
                for word in query_lower.split())
        ]

        matching.sort(key=lambda s: (-s.get("uptime_pct", 0), s.get("avg_latency_ms", 9999)))

        if not matching:
            return f"No x402 services found for '{query}' under ${max_price_usd}"

        best = matching[0]
        return (
            f"Best match: {best['name']}\n"
            f"Endpoint: {best['endpoint_url']}\n"
            f"Price: ${best['price_per_call']}/call\n"
            f"Quality: {best.get('uptime_pct', 'N/A')}% uptime, {best.get('avg_latency_ms', 'N/A')}ms avg\n"
            f"Description: {best['description']}\n"
            f"Code: {best.get('sdk_snippet_python', 'See https://x402-discovery-api.onrender.com')}"
        )
    except Exception as e:
        return f"x402 discovery failed: {e}"


def register_with_autogen(agent):
    """Register x402_discover as a tool on an AutoGen ConversableAgent."""
    agent.register_for_llm(name="x402_discover", description="Find x402-payable API services")(x402_discover)
    return agent
