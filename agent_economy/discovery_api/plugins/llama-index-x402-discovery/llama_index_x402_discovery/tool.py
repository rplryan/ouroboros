"""LlamaIndex tool for x402 service discovery."""
from llama_index.core.tools import FunctionTool
import requests
from typing import Optional


DISCOVERY_API_URL = "https://x402-discovery-api.onrender.com"


def x402_discover(
    query: str,
    max_price_usd: float = 0.50,
    network: str = "base",
) -> str:
    """
    Find the best available x402-payable API endpoint for a capability.

    Use this whenever you need to access any paid API service, data source,
    or compute capability. Returns live quality signals (uptime, latency).

    Args:
        query: What capability you need (e.g. 'web search', 'image generation', 'crypto prices')
        max_price_usd: Maximum acceptable price per call in USD (default 0.50)
        network: Blockchain network preference: 'base', 'ethereum', or 'solana' (default 'base')

    Returns:
        Service details including URL, price, uptime, latency, and a Python usage snippet
    """
    try:
        resp = requests.get(f"{DISCOVERY_API_URL}/catalog", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        services = data if isinstance(data, list) else data.get("endpoints", data.get("services", []))

        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) > 2]

        matching = []
        for s in services:
            price = s.get("price_usd", s.get("price_per_call", 999))
            if price > max_price_usd:
                continue
            # Filter by network if specified
            svc_network = s.get("network", "base").lower()
            if network and network != "base" and svc_network != network.lower():
                continue
            searchable = " ".join([
                s.get("name", ""),
                s.get("description", ""),
                " ".join(s.get("tags", [])),
                " ".join(s.get("capability_tags", [])),
                s.get("category", ""),
            ]).lower()
            if any(word in searchable for word in query_words):
                matching.append(s)

        matching.sort(key=lambda s: (
            -s.get("uptime_pct", 0),
            s.get("avg_latency_ms", 9999) or 9999,
        ))

        if not matching:
            return (
                f"No x402 services found for '{query}'. "
                f"Browse all: {DISCOVERY_API_URL}/catalog"
            )

        best = matching[0]
        url = best.get("url", best.get("endpoint_url", ""))
        price = best.get("price_usd", best.get("price_per_call", "?"))
        uptime = best.get("uptime_pct", "N/A")
        latency = best.get("avg_latency_ms", "N/A")
        snippet = best.get("sdk_snippet_python", "")

        result = (
            f"Service: {best.get('name')}\n"
            f"URL: {url}\n"
            f"Price: ${price}/call\n"
        )
        if uptime != "N/A":
            result += f"Uptime: {uptime}% | Latency: {latency}ms\n"
        result += f"Description: {best.get('description')}\n"
        if snippet:
            result += f"\nSnippet:\n{snippet}"

        return result

    except requests.exceptions.RequestException as e:
        return f"x402 discovery network error: {e}"
    except Exception as e:
        return f"x402 discovery error: {e}"


def get_x402_discovery_tool(
    discovery_api_url: str = DISCOVERY_API_URL,
) -> FunctionTool:
    """
    Get x402 discovery as a LlamaIndex FunctionTool.

    Usage:
        from llama_index.core.agent import ReActAgent
        from llama_index_x402_discovery import get_x402_discovery_tool

        tools = [get_x402_discovery_tool()]
        agent = ReActAgent.from_tools(tools, llm=llm, verbose=True)

    Args:
        discovery_api_url: Override the default discovery API URL

    Returns:
        LlamaIndex FunctionTool ready to use in any agent
    """
    return FunctionTool.from_defaults(
        fn=x402_discover,
        name="x402_discover",
        description=(
            "Find the best available x402-payable API endpoint for any capability. "
            "Use when you need to access a paid API, data source, or compute capability. "
            "Input: natural language description (e.g. 'web search', 'crypto prices'). "
            "Returns endpoint URL, price per call, quality signals, and usage code snippet."
        )
    )
