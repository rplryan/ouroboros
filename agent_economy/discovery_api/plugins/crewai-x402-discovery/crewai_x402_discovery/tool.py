from crewai.tools import BaseTool
from pydantic import Field
import requests


class X402DiscoveryTool(BaseTool):
    name: str = "x402_service_discovery"
    description: str = (
        "Find the best available x402-payable API endpoint for any capability. "
        "Use when you need to access a paid API, data source, or compute service. "
        "Input: natural language description of what you need (e.g. 'weather data', 'image analysis'). "
        "Returns: endpoint URL, price per call, quality metrics, and Python code snippet."
    )
    discovery_api_url: str = "https://x402-discovery-api.onrender.com"
    max_price_usd: float = Field(default=0.50)

    def _run(self, query: str) -> str:
        try:
            resp = requests.get(f"{self.discovery_api_url}/catalog", timeout=10)
            catalog = resp.json()
            services = catalog.get("services", [])

            query_lower = query.lower()
            matching = [
                s for s in services
                if s.get("price_per_call", 999) <= self.max_price_usd and
                any(word in s.get("description", "").lower() or
                    word in " ".join(s.get("capability_tags", [])).lower() or
                    word in s.get("name", "").lower()
                    for word in query_lower.split())
            ]

            matching.sort(key=lambda s: (-s.get("uptime_pct", 0), s.get("avg_latency_ms", 9999)))

            if not matching:
                return f"No x402 services found for: {query}"

            best = matching[0]
            return (
                f"Found: {best['name']}\n"
                f"URL: {best['endpoint_url']}\n"
                f"Cost: ${best['price_per_call']}/call\n"
                f"Uptime: {best.get('uptime_pct', 'N/A')}%\n"
                f"Description: {best['description']}\n"
                f"Usage:\n{best.get('sdk_snippet_python', '')}"
            )
        except Exception as e:
            return f"Discovery error: {e}"
