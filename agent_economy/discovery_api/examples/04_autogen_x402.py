#!/usr/bin/env python3
"""
Demonstrates: AutoGen agent with x402 discovery function tool.
Source: https://x402-discovery-api.onrender.com

Install: pip install autogen-x402-discovery pyautogen
"""
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

# The actual AutoGen function that gets registered
def x402_discover(capability: str = None, max_price_usd: float = 0.50, query: str = None) -> str:
    """Find x402-payable services matching criteria. Returns quality-ranked results."""
    resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
    services = resp.json().get("services", [])

    if capability:
        services = [s for s in services if capability in s.get("capability_tags", []) or s.get("category") == capability]
    services = [s for s in services if s.get("price_per_call", 999) <= max_price_usd]

    if not services:
        return f"No services found. Full catalog: {DISCOVERY_URL}/catalog"

    return "\n".join(
        f"{i+1}. {s['name']} [${s.get('price_per_call','?')}/call] - {s.get('description','')}"
        for i, s in enumerate(services[:5])
    )

# AutoGen tool schema
X402_DISCOVERY_TOOL_SCHEMA = {
    "name": "x402_discover",
    "description": "Find x402-payable API services. Use when you need a paid service for research, data, or computation.",
    "parameters": {
        "type": "object",
        "properties": {
            "capability": {"type": "string", "description": "Filter: research, data, compute, generation, etc."},
            "max_price_usd": {"type": "number", "description": "Max price per call in USD"},
            "query": {"type": "string", "description": "Free-text search query"},
        },
    },
}

# Demo
print("AutoGen x402 Discovery Integration")
print("=" * 40)
print("Tool schema ready for AutoGen function_map")
print()
print("Test call:")
result = x402_discover(capability="research", max_price_usd=0.10)
print(result)

AUTOGEN_EXAMPLE = """
# Full AutoGen integration:
import autogen
from x402discovery_autogen import x402_discover_function, X402_DISCOVERY_TOOL_SCHEMA

assistant = autogen.AssistantAgent(
    name="assistant",
    llm_config={
        "functions": [X402_DISCOVERY_TOOL_SCHEMA],
        "config_list": [{"model": "gpt-4o", "api_key": "YOUR_KEY"}],
    },
)
user = autogen.UserProxyAgent(
    name="user",
    function_map={"x402_discover": x402_discover_function},
    human_input_mode="NEVER",
)
user.initiate_chat(assistant, message="Find a research service under $0.10/call")
"""
print(AUTOGEN_EXAMPLE)
