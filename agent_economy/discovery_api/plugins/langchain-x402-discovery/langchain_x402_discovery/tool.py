"""LangChain tool for x402 service discovery."""
from langchain.tools import BaseTool
from pydantic import Field
import requests
from typing import Optional, Type
from pydantic import BaseModel


DISCOVERY_API_URL = "https://x402-discovery-api.onrender.com"


class X402DiscoverInput(BaseModel):
    query: str = Field(description="Natural language description of the capability needed (e.g. 'web search', 'crypto prices')")
    max_price_usd: float = Field(default=0.50, description="Maximum price per call in USD")


class X402DiscoveryTool(BaseTool):
    """
    LangChain tool that discovers x402-payable API endpoints at runtime.

    Gives your LangChain agent the ability to find any paid API service
    from the live x402 catalog without hardcoded URLs or API keys.

    Results are quality-ranked by uptime percentage and average latency.

    Usage:
        from langchain_x402_discovery import get_x402_discovery_tool

        tool = get_x402_discovery_tool()
        agent = create_tool_calling_agent(llm, [tool], prompt)
    """

    name: str = "x402_discover"
    description: str = (
        "Find the best available x402-payable API endpoint for any capability. "
        "Use when you need to access a paid API, data source, compute service, or AI agent. "
        "Input: natural language description of what you need. "
        "Examples: 'web search', 'image generation', 'crypto prices', 'data enrichment'. "
        "Returns endpoint URL, price per call, uptime %, latency, and a Python code snippet."
    )
    args_schema: Type[BaseModel] = X402DiscoverInput
    discovery_api_url: str = Field(default=DISCOVERY_API_URL)
    max_price_usd: float = Field(default=0.50)

    def _run(self, query: str, max_price_usd: float = 0.50) -> str:
        try:
            resp = requests.get(f"{self.discovery_api_url}/catalog", timeout=15)
            resp.raise_for_status()
            data = resp.json()
            services = data if isinstance(data, list) else data.get("endpoints", data.get("services", []))

            query_lower = query.lower()
            query_words = [w for w in query_lower.split() if len(w) > 2]
            price_limit = max_price_usd or self.max_price_usd

            matching = []
            for s in services:
                price = s.get("price_usd", s.get("price_per_call", 999))
                if price > price_limit:
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
                    f"No x402 services found for '{query}' under ${price_limit}.\n"
                    f"Browse all services at: {self.discovery_api_url}/catalog"
                )

            best = matching[0]
            url = best.get("url", best.get("endpoint_url", ""))
            price = best.get("price_usd", best.get("price_per_call", "?"))
            uptime = best.get("uptime_pct", "N/A")
            latency = best.get("avg_latency_ms", "N/A")
            snippet = best.get("sdk_snippet_python", "")

            result = (
                f"Found: {best.get('name')}\n"
                f"URL: {url}\n"
                f"Price: ${price}/call\n"
            )
            if uptime != "N/A":
                result += f"Uptime: {uptime}% | Latency: {latency}ms\n"
            result += f"Description: {best.get('description')}\n"
            if len(matching) > 1:
                result += f"({len(matching) - 1} other match(es) — refine query to narrow down)\n"
            if snippet:
                result += f"\nPython snippet:\n{snippet}"

            return result

        except requests.exceptions.RequestException as e:
            return f"x402 discovery network error: {e}"
        except Exception as e:
            return f"x402 discovery error: {e}"

    async def _arun(self, query: str, max_price_usd: float = 0.50) -> str:
        """Async version — runs sync implementation in executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._run(query, max_price_usd))


def get_x402_discovery_tool(
    discovery_api_url: str = DISCOVERY_API_URL,
    max_price_usd: float = 0.50,
) -> X402DiscoveryTool:
    """
    Get x402 discovery as a LangChain Tool.

    Usage:
        from langchain_x402_discovery import get_x402_discovery_tool

        tool = get_x402_discovery_tool()
        agent = create_tool_calling_agent(llm, [tool], prompt)

    Args:
        discovery_api_url: Override the default discovery API URL
        max_price_usd: Default maximum price per call in USD

    Returns:
        LangChain BaseTool ready to use in any agent
    """
    return X402DiscoveryTool(
        discovery_api_url=discovery_api_url,
        max_price_usd=max_price_usd,
    )
