"""x402 Discovery tool for LangChain agents.

Exposes x402 service discovery as a LangChain BaseTool so any LangChain
agent can find paid API services at runtime without hardcoded URLs.

Usage:
    from x402discovery_langchain import X402DiscoveryTool
    from langchain.agents import initialize_agent, AgentType
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o-mini")
    tools = [X402DiscoveryTool()]
    agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS)
    agent.run("Find a web research service under $0.10 per call")
"""
from __future__ import annotations

from typing import Optional, Type

import requests
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

DISCOVERY_BASE_URL = "https://x402-discovery-api.onrender.com"


class _DiscoverInput(BaseModel):
    capability: Optional[str] = Field(
        default=None,
        description=(
            "Filter by capability. One of: research, data, compute, monitoring, "
            "verification, routing, storage, translation, classification, generation, "
            "extraction, summarization, enrichment, validation, other."
        ),
    )
    max_price_usd: float = Field(
        default=0.50,
        description="Maximum price per call in USD.",
    )
    query: Optional[str] = Field(
        default=None,
        description="Free-text search against service name and description.",
    )


class X402DiscoveryTool(BaseTool):
    """LangChain tool for discovering x402-payable API services.

    Searches the x402 discovery catalog and returns quality-ranked results.
    Use this when an agent needs to find a paid API service to delegate a task.
    """

    name: str = "x402_discover"
    description: str = (
        "Find x402-payable API services that can perform a given task. "
        "Use this when you need a paid service for research, data processing, "
        "AI generation, monitoring, or any specialized capability. "
        "Returns the top matching services ranked by quality with pricing info."
    )
    args_schema: Type[BaseModel] = _DiscoverInput

    def _run(
        self,
        capability: Optional[str] = None,
        max_price_usd: float = 0.50,
        query: Optional[str] = None,
    ) -> str:
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
                f"{i}. {s.get('name')} [{s.get('quality_tier','unverified').upper()}]\n"
                f"   ID: {s.get('service_id')}  Price: ${s.get('price_per_call')}/call\n"
                f"   URL: {s.get('endpoint_url', s.get('url'))}\n"
                f"   {s.get('description', '')}\n"
            )
        return "\n".join(lines)

    async def _arun(self, *args, **kwargs) -> str:
        raise NotImplementedError("Use _run (sync). For async, run in executor.")


__all__ = ["X402DiscoveryTool", "DISCOVERY_BASE_URL"]
