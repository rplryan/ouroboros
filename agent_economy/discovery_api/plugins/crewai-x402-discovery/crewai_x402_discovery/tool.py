"""CrewAI tool for x402 service discovery."""
from crewai.tools import BaseTool
from pydantic import Field
import requests
from typing import Optional


DISCOVERY_API_URL = "https://x402-discovery-api.onrender.com"


class X402DiscoveryTool(BaseTool):
    """
    CrewAI tool that discovers x402-payable API endpoints at runtime.

    Agents use this to find the best available paid API service for any capability
    without hardcoding URLs or API keys. Results are ranked by uptime and latency.

    Usage:
        from crewai import Agent, Task, Crew
        from crewai_x402_discovery import X402DiscoveryTool

        tool = X402DiscoveryTool()
        agent = Agent(
            role="Research Specialist",
            goal="Find and use the best APIs for any task",
            tools=[tool],
        )
    """

    name: str = "x402_service_discovery"
    description: str = (
        "Find the best available x402-payable API endpoint for any capability. "
        "Use when you need to access a paid API, data source, compute service, or agent. "
        "Input: natural language description of what you need "
        "(e.g. 'web search', 'image generation', 'crypto prices', 'data enrichment'). "
        "Returns: endpoint URL, price per call, uptime %, latency, and a Python code snippet."
    )
    discovery_api_url: str = Field(default=DISCOVERY_API_URL)
    max_price_usd: float = Field(default=0.50, description="Maximum price per call in USD")

    def _run(self, query: str) -> str:
        try:
            resp = requests.get(f"{self.discovery_api_url}/catalog", timeout=15)
            resp.raise_for_status()
            data = resp.json()
            services = data if isinstance(data, list) else data.get("endpoints", data.get("services", []))

            query_lower = query.lower()
            query_words = [w for w in query_lower.split() if len(w) > 2]

            matching = []
            for s in services:
                price = s.get("price_usd", s.get("price_per_call", 999))
                if price > self.max_price_usd:
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
                    f"No x402 services found for: {query}\n"
                    f"Browse all: {self.discovery_api_url}/catalog"
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
                f"Cost: ${price}/call\n"
            )
            if uptime != "N/A":
                result += f"Uptime: {uptime}% | Latency: {latency}ms\n"
            result += f"Description: {best.get('description')}\n"
            if snippet:
                result += f"\nUsage:\n{snippet}"

            return result

        except requests.exceptions.RequestException as e:
            return f"x402 discovery network error: {e}"
        except Exception as e:
            return f"x402 discovery error: {e}"
