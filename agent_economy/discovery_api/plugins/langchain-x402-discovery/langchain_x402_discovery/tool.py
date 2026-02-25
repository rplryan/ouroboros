from langchain.tools import BaseTool
from pydantic import BaseModel, Field
import requests
from typing import Optional, Type


class X402DiscoverInput(BaseModel):
    query: str = Field(description="Natural language description of what API capability you need (e.g. 'web search', 'image generation', 'research')")
    max_price_usd: float = Field(default=0.50, description="Maximum price per call in USD")
    network: str = Field(default="base", description="Blockchain network: base, ethereum, solana")


class X402DiscoveryTool(BaseTool):
    name: str = "x402_discover"
    description: str = (
        "Find and return the best available x402-payable API endpoint for any capability. "
        "Use this tool whenever you need to access a paid API service, data source, or agent capability. "
        "Returns endpoint URL, price, quality signals (uptime, latency), and a Python code snippet to call it. "
        "Charges $0.005 USDC on Base per discovery query via x402 protocol."
    )
    args_schema: Type[BaseModel] = X402DiscoverInput
    discovery_api_url: str = "https://x402-discovery-api.onrender.com"

    def _run(self, query: str, max_price_usd: float = 0.50, network: str = "base") -> str:
        """Run x402 service discovery."""
        try:
            # Free browse endpoint for initial discovery
            resp = requests.get(
                f"{self.discovery_api_url}/catalog",
                timeout=10
            )
            catalog = resp.json()
            services = catalog.get("services", [])

            # Filter by max price and search query
            query_lower = query.lower()
            matching = []
            for svc in services:
                price = svc.get("price_per_call", 999)
                desc = svc.get("description", "").lower()
                tags = " ".join(svc.get("capability_tags", [])).lower()
                name = svc.get("name", "").lower()
                if price <= max_price_usd and (
                    any(word in desc or word in tags or word in name
                        for word in query_lower.split())
                ):
                    matching.append(svc)

            # Sort by quality
            matching.sort(key=lambda s: (
                -s.get("uptime_pct", 0),
                s.get("avg_latency_ms", 9999)
            ))

            if not matching:
                return (
                    f"No x402 services found matching '{query}' with max price ${max_price_usd}. "
                    f"Browse all at https://x402-discovery-api.onrender.com/catalog"
                )

            best = matching[0]
            snippet = best.get("sdk_snippet_python", "")
            result = (
                f"Found: {best.get('name')}\n"
                f"URL: {best.get('endpoint_url')}\n"
                f"Price: ${best.get('price_per_call')}/call\n"
                f"Uptime: {best.get('uptime_pct', 'N/A')}%\n"
                f"Latency: {best.get('avg_latency_ms', 'N/A')}ms\n"
                f"Description: {best.get('description')}\n"
            )
            if snippet:
                result += f"\nPython snippet:\n{snippet}"
            return result
        except Exception as e:
            return f"x402 discovery error: {e}. Try https://x402-discovery-api.onrender.com/catalog directly."

    async def _arun(self, query: str, max_price_usd: float = 0.50, network: str = "base") -> str:
        return self._run(query, max_price_usd, network)


def get_x402_discovery_tool(discovery_api_url: str = "https://x402-discovery-api.onrender.com") -> X402DiscoveryTool:
    """Get the x402 discovery tool for LangChain agents."""
    return X402DiscoveryTool(discovery_api_url=discovery_api_url)
