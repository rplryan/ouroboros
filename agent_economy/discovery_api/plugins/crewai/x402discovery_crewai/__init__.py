"""x402 Discovery Tool for CrewAI agents.

Enables CrewAI agents to discover and select x402-payable services at runtime.

Usage:
    from crewai import Agent
    from x402discovery_crewai import X402DiscoveryTool

    researcher = Agent(
        role="Research Specialist",
        goal="Find and use the best paid research services",
        tools=[X402DiscoveryTool()]
    )
"""
from __future__ import annotations
from typing import Optional, Type
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

DISCOVERY_BASE_URL = "https://x402-discovery-api.onrender.com"


class X402DiscoveryInput(BaseModel):
    capability: Optional[str] = Field(None, description="Filter by capability: research, data, compute, monitoring, generation, etc.")
    max_price_usd: float = Field(0.50, description="Maximum price per call in USD")
    query: Optional[str] = Field(None, description="Free-text search query")


class X402DiscoveryTool(BaseTool):
    name: str = "x402_discover"
    description: str = (
        "Find x402-payable API services available at runtime. Use this tool when you need "
        "to access a paid service for research, data, AI generation, or any specialized task. "
        "Returns quality-ranked services with pricing and health status."
    )
    args_schema: Type[BaseModel] = X402DiscoveryInput

    def _run(self, capability: Optional[str] = None, max_price_usd: float = 0.50, query: Optional[str] = None) -> str:
        try:
            resp = requests.get(f"{DISCOVERY_BASE_URL}/catalog", timeout=15)
            resp.raise_for_status()
            services = resp.json().get("services", [])
        except requests.RequestException as e:
            return f"Discovery failed: {e}"

        if capability:
            services = [s for s in services if capability in s.get("capability_tags", []) or s.get("category") == capability]
        services = [s for s in services if s.get("price_per_call", 999) <= max_price_usd]
        if query:
            q = query.lower()
            services = [s for s in services if q in s.get("name", "").lower() or q in s.get("description", "").lower()]

        order = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
        services.sort(key=lambda s: order.get(s.get("quality_tier", "unverified"), 3))

        if not services:
            return f"No services found. Try broadening your search. Full catalog: {DISCOVERY_BASE_URL}/catalog"

        lines = [f"Found {len(services)} services (top 5):"]
        for i, s in enumerate(services[:5], 1):
            lines.append(
                f"{i}. {s.get('name')} [ID: {s.get('service_id')}] "
                f"${s.get('price_per_call', '?')}/call — {s.get('description', '')}"
            )
        lines.append(f"\nTo call: POST to the endpoint URL with x402 payment (USDC on Base)")
        return "\n".join(lines)


__all__ = ["X402DiscoveryTool", "X402DiscoveryInput"]
