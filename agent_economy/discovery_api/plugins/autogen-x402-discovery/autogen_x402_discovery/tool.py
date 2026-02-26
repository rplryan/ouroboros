"""AutoGen tool for x402 service discovery."""
import requests
from typing import Optional, Callable


DISCOVERY_API_URL = "https://x402-discovery-api.onrender.com"


def x402_discover(
    query: str,
    max_price_usd: float = 0.50,
) -> str:
    """
    Find the best available x402-payable API endpoint for any capability.

    Use this tool whenever you need to access any paid API service, data source,
    or compute capability. Discovers live x402 services with quality signals
    (uptime %, latency, health status).

    Args:
        query (str): Natural language description of the capability needed.
                     Examples: "web search", "image generation", "crypto prices"
        max_price_usd (float): Maximum price per call in USD (default: 0.50)

    Returns:
        str: Service details with URL, price, quality metrics, and Python usage snippet
    """
    try:
        resp = requests.get(f"{DISCOVERY_API_URL}/catalog", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # catalog returns {"endpoints": [...], "count": N}
        services = data if isinstance(data, list) else data.get("endpoints", data.get("services", []))

        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) > 2]

        matching = []
        for s in services:
            price = s.get("price_usd", s.get("price_per_call", 999))
            if price > max_price_usd:
                continue
            # Match against name, description, tags
            searchable = " ".join([
                s.get("name", ""),
                s.get("description", ""),
                " ".join(s.get("tags", [])),
                " ".join(s.get("capability_tags", [])),
                s.get("category", ""),
            ]).lower()
            if any(word in searchable for word in query_words):
                matching.append(s)

        # Sort by uptime (desc), then latency (asc)
        matching.sort(key=lambda s: (
            -s.get("uptime_pct", 0),
            s.get("avg_latency_ms", 9999) or 9999,
        ))

        if not matching:
            return (
                f"No x402 services found for '{query}' under ${max_price_usd}.\n"
                f"Browse all services at: {DISCOVERY_API_URL}/catalog"
            )

        best = matching[0]
        url = best.get("url", best.get("endpoint_url", ""))
        price = best.get("price_usd", best.get("price_per_call", "?"))
        uptime = best.get("uptime_pct", "N/A")
        latency = best.get("avg_latency_ms", "N/A")
        snippet = best.get("sdk_snippet_python", f'# See: {DISCOVERY_API_URL}')

        lines = [
            f"Best match: {best.get('name', 'Unknown')}",
            f"Endpoint: {url}",
            f"Price: ${price}/call",
        ]
        if uptime != "N/A":
            lines.append(f"Quality: {uptime}% uptime, {latency}ms avg latency")
        lines.append(f"Description: {best.get('description', '')}")
        if len(matching) > 1:
            lines.append(f"({len(matching) - 1} other match(es) available)")
        lines.append(f"\nPython snippet:\n{snippet}")

        return "\n".join(lines)

    except requests.exceptions.RequestException as e:
        return f"x402 discovery network error: {e}"
    except Exception as e:
        return f"x402 discovery error: {e}"


def register_with_autogen(agent, name: str = "x402_discover") -> object:
    """
    Register x402_discover as a callable tool on an AutoGen ConversableAgent.

    Usage:
        import autogen
        from autogen_x402_discovery import register_with_autogen

        agent = autogen.ConversableAgent("assistant", llm_config={...})
        register_with_autogen(agent)

    Args:
        agent: AutoGen ConversableAgent instance
        name: Tool name to register (default: "x402_discover")

    Returns:
        The agent with the tool registered
    """
    try:
        # AutoGen 0.2.x API
        agent.register_for_llm(
            name=name,
            description=(
                "Find x402-payable API services at runtime. Use when you need to access "
                "a paid API, data source, or compute capability. Returns endpoint URL, "
                "price, quality signals, and a Python usage snippet."
            )
        )(x402_discover)
    except AttributeError:
        # Fallback: direct function_map registration
        if hasattr(agent, "function_map"):
            agent.function_map[name] = x402_discover

    return agent


def get_autogen_tool_schema() -> dict:
    """Return the OpenAI function-calling schema for x402_discover."""
    return {
        "type": "function",
        "function": {
            "name": "x402_discover",
            "description": (
                "Find the best available x402-payable API endpoint for any capability. "
                "Use when you need to access a paid API, data source, or compute service. "
                "Returns endpoint URL, price, quality metrics, and usage code snippet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of the capability needed (e.g. 'web search', 'crypto prices')"
                    },
                    "max_price_usd": {
                        "type": "number",
                        "description": "Maximum price per call in USD (default: 0.50)"
                    }
                },
                "required": ["query"]
            }
        }
    }
