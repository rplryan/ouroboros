# x402 Discovery Layer — Integration Guide

A practical guide for integrating x402 service discovery into your agent, pipeline, or framework. All examples use the reference implementation at https://x402-discovery-api.onrender.com.

---

## Overview

The discovery API has two tiers:

| Tier | Endpoint | Cost | Use Case |
|---|---|---|---|
| Free | `GET /catalog` or `GET /.well-known/x402-discovery` | Free | Browse all services, bootstrap local cache |
| Paid | `GET /discover?q=...` | $0.010 USDC | Quality-ranked search with filters |

The free catalog is the right starting point for most integrations. The paid `/discover` endpoint is worth the $0.010 when you need quality-filtered, ranked results and don't want to filter the full catalog yourself.

---

## Raw Python (5 lines)

The simplest possible integration. No SDK required.

```python
import requests
import json

# Free: browse the full catalog
catalog = requests.get("https://x402-discovery-api.onrender.com/catalog").json()
services = catalog["endpoints"]
print(f"Found {len(services)} services")
```

For the paid `/discover` endpoint, you need to handle the 402 response and provide payment.

**Step 1 — What a 402 response looks like:**

```python
import requests

resp = requests.get(
    "https://x402-discovery-api.onrender.com/discover",
    params={"q": "research", "limit": 5}
)
# resp.status_code == 402
payment_req = resp.json()
print(json.dumps(payment_req, indent=2))
```

Output:
```json
{
  "error": "Payment Required",
  "x402Version": 2,
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "amount": "5000",
    "resource": "https://x402-discovery-api.onrender.com/discover",
    "description": "x402 Service Discovery Query",
    "mimeType": "application/json",
    "payTo": "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA",
    "maxTimeoutSeconds": 60,
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "extra": {"name": "USDC", "version": "2"}
  }]
}
```

**Step 2 — Pay and retry using the x402 SDK:**

```python
from x402.client import wrap  # pip install x402

# wrap() adds automatic payment handling
client = wrap(requests)
resp = client.get(
    "https://x402-discovery-api.onrender.com/discover",
    params={"q": "research", "limit": 5}
)
# Client handles the 402, signs and submits payment, retries
results = resp.json()["results"]
for s in results:
    print(f"{s['name']} — ${s['price_usd']}/call — uptime: {s.get('uptime_pct')}%")
```

---

## Using the x402discovery SDK

A higher-level SDK providing convenience functions for common discovery patterns.

```python
from x402discovery import discover, discover_and_execute

# Find the best research service (quality-filtered, ranked)
service = discover(
    capability="research",
    max_price=0.30,
    min_quality="silver"
)
print(f"Best match: {service['name']} at ${service['price_per_call']}/call")
print(f"Uptime: {service['uptime_7d']}% | P95 latency: {service['latency_p95_ms']}ms")

# Discover AND execute in one call
result = discover_and_execute(
    capability="research",
    query="What are the key provisions of the EU AI Act?",
    max_price=0.50
)
print(result["answer"])
print(result["sources"])
```

The SDK handles:
- Payment negotiation and execution
- Retry logic on transient failures
- Quality tier filtering
- Local caching of discovery results (refreshed hourly)

Install: `pip install x402discovery` (package in development; track at the reference implementation repository)

---

## LangChain Integration

Define x402 discovery as a LangChain Tool. The tool handles the full discovery → call → return cycle.

```python
from langchain.tools import Tool
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

def x402_discover_and_call(input_str: str) -> str:
    """
    Discover and call the best x402 service for the given query.
    Input: "capability:research query:What is the EU AI Act?"
    or just: "research question about EU AI Act"
    """
    # Parse input
    capability = "research"
    query = input_str
    if "capability:" in input_str:
        parts = input_str.split(" ", 1)
        capability = parts[0].replace("capability:", "")
        query = parts[1].replace("query:", "").strip() if len(parts) > 1 else ""

    # Step 1: Browse free catalog (no payment needed)
    catalog_resp = requests.get(f"{DISCOVERY_URL}/catalog")
    services = catalog_resp.json().get("endpoints", [])

    # Filter by category and quality
    matching = [
        s for s in services
        if s.get("category") == capability
        and s.get("health_status") in ("verified_up", "unverified")
        and s.get("status") == "active"
    ]

    if not matching:
        return f"No active {capability} services found in x402 discovery index."

    # Sort by uptime (best first)
    matching.sort(key=lambda s: s.get("uptime_pct") or 0, reverse=True)
    best = matching[0]

    return (
        f"Found x402 service: {best['name']}\n"
        f"URL: {best['url']}\n"
        f"Price: ${best['price_usd']}/call\n"
        f"Uptime: {best.get('uptime_pct')}%\n"
        f"To call: send GET/POST to {best['url']} with X-PAYMENT header (x402 USDC on Base)\n"
        f"Description: {best['description']}"
    )

# Define as LangChain Tool
x402_tool = Tool(
    name="x402_service_discovery",
    func=x402_discover_and_call,
    description=(
        "Find x402-payable API services for a given capability. "
        "Use this when you need to access a paid data source, research API, or compute service. "
        "Input: describe what you need (e.g. 'research on EU AI Act', 'crypto price for ETH'). "
        "Returns: service URL, price per call, uptime stats, and instructions for payment. "
        "After getting the URL, use it to make the actual paid API call."
    )
)

# Use in an agent
llm = ChatOpenAI(model="gpt-4o", temperature=0)
agent = initialize_agent(
    tools=[x402_tool],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

result = agent.run("Find a research service and tell me what EU AI Act compliance requires")
print(result)
```

---

## AutoGen Integration

Define x402 discovery as an AutoGen function tool.

```python
import autogen
import requests
from typing import Annotated

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

# Define the function tool
def discover_x402_service(
    capability: Annotated[str, "The capability needed: research, data, compute, agent, utility"],
    max_price_usd: Annotated[float, "Maximum price per call in USD"] = 0.10,
) -> dict:
    """
    Find the best available x402-payable service for the given capability.
    Returns service metadata including URL, price, and quality signals.
    """
    catalog_resp = requests.get(f"{DISCOVERY_URL}/catalog")
    if catalog_resp.status_code != 200:
        return {"error": "Discovery index unavailable"}

    services = catalog_resp.json().get("endpoints", [])

    # Filter by capability and price
    matching = [
        s for s in services
        if s.get("category") == capability
        and s.get("price_usd", 999) <= max_price_usd
        and s.get("status") in ("active", "community")
    ]

    if not matching:
        return {"error": f"No {capability} services found under ${max_price_usd}/call"}

    # Sort by quality: uptime desc, latency asc
    matching.sort(
        key=lambda s: (-(s.get("uptime_pct") or 0), s.get("avg_latency_ms") or 9999)
    )

    best = matching[0]
    return {
        "service_name": best["name"],
        "endpoint_url": best["url"],
        "price_usd": best["price_usd"],
        "uptime_pct": best.get("uptime_pct"),
        "avg_latency_ms": best.get("avg_latency_ms"),
        "health_status": best.get("health_status"),
        "description": best["description"],
        "payment_instructions": (
            f"Call {best['url']} with X-PAYMENT header. "
            f"Pay {best['price_usd']} USDC on Base to "
            f"0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA"
        )
    }

# AutoGen configuration
config_list = [{"model": "gpt-4o", "api_key": "your-key-here"}]

llm_config = {
    "config_list": config_list,
    "functions": [
        {
            "name": "discover_x402_service",
            "description": "Find and return the best x402-payable API service for a given capability. Use this to locate paid APIs for research, data, compute, or agent tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "capability": {
                        "type": "string",
                        "description": "Service capability: research, data, compute, agent, utility",
                        "enum": ["research", "data", "compute", "agent", "utility"]
                    },
                    "max_price_usd": {
                        "type": "number",
                        "description": "Maximum acceptable price per call in USD",
                        "default": 0.10
                    }
                },
                "required": ["capability"]
            }
        }
    ]
}

assistant = autogen.AssistantAgent(
    name="x402_agent",
    llm_config=llm_config,
    system_message="You are a helpful agent that can discover and use x402-payable API services."
)

user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    function_map={"discover_x402_service": discover_x402_service}
)

user_proxy.initiate_chat(
    assistant,
    message="Find me a research service for looking up regulatory filings"
)
```

---

## CrewAI Integration

Define x402 discovery as a CrewAI Tool.

```python
from crewai import Agent, Task, Crew
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import requests
from typing import Type

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

class X402DiscoveryInput(BaseModel):
    capability: str = Field(description="The capability needed: research, data, compute, agent, utility")
    max_price: float = Field(default=0.10, description="Maximum price per call in USD")
    query: str = Field(default="", description="Optional keyword to refine search")

class X402DiscoveryTool(BaseTool):
    name: str = "x402_service_discovery"
    description: str = (
        "Find x402-payable API services for a given capability. "
        "Returns the best available service with URL, price, uptime, and payment instructions. "
        "Use this tool when you need to access external paid data or compute services."
    )
    args_schema: Type[BaseModel] = X402DiscoveryInput

    def _run(self, capability: str, max_price: float = 0.10, query: str = "") -> str:
        resp = requests.get(f"{DISCOVERY_URL}/catalog")
        if resp.status_code != 200:
            return "Error: Discovery index unavailable"

        services = resp.json().get("endpoints", [])

        # Filter and sort
        matching = [
            s for s in services
            if s.get("category") == capability
            and s.get("price_usd", 999) <= max_price
            and s.get("status") == "active"
        ]

        if query:
            kw = query.lower()
            matching = [
                s for s in matching
                if kw in s.get("name", "").lower()
                or kw in s.get("description", "").lower()
                or any(kw in t for t in s.get("tags", []))
            ] or matching  # fall back to all if none match

        if not matching:
            return f"No active {capability} services found under ${max_price}/call"

        matching.sort(key=lambda s: (-(s.get("uptime_pct") or 0), s.get("avg_latency_ms") or 9999))
        s = matching[0]

        return (
            f"Service: {s['name']}\n"
            f"URL: {s['url']}\n"
            f"Price: ${s['price_usd']}/call\n"
            f"Quality: {s.get('health_status', 'unverified')} | Uptime: {s.get('uptime_pct')}%\n"
            f"Description: {s['description']}\n"
            f"Payment: X-PAYMENT header, USDC on Base, pay to 0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA"
        )

# Define a CrewAI agent that uses the tool
research_agent = Agent(
    role="Research Coordinator",
    goal="Find the best available research services and retrieve information",
    backstory="You coordinate research by discovering and using x402-payable research APIs",
    tools=[X402DiscoveryTool()],
    verbose=True
)

research_task = Task(
    description="Find a research service and discover what x402 services are available for EU regulatory research",
    expected_output="Name, URL, price, and quality metrics of the best available research service",
    agent=research_agent
)

crew = Crew(agents=[research_agent], tasks=[research_task])
result = crew.kickoff()
print(result)
```

---

## MCP Client Usage

Add this discovery API as an MCP server in Claude Desktop or Cursor.

**Claude Desktop** — edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "x402-discovery": {
      "command": "python",
      "args": ["/path/to/agent_economy/discovery_api/mcp/server.py"],
      "env": {}
    }
  }
}
```

**Cursor** — add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "x402-discovery": {
      "command": "python",
      "args": ["/path/to/agent_economy/discovery_api/mcp/server.py"]
    }
  }
}
```

After restarting, Claude/Cursor will have access to `x402_discover` and `x402_browse` tools:

- `x402_discover`: Paid quality-ranked search ($0.010 USDC)
- `x402_browse`: Free catalog browser

---

## The /.well-known/x402-discovery Pattern

For framework builders: implement the well-known URL consumer to bootstrap a local service cache.

```python
import requests
import json
import time
from pathlib import Path

WELL_KNOWN_URL = "https://x402-discovery-api.onrender.com/.well-known/x402-discovery"
CACHE_FILE = Path("/tmp/x402_discovery_cache.json")
CACHE_TTL_SECONDS = 3600  # 1 hour

def get_x402_index(force_refresh: bool = False) -> list[dict]:
    """
    Fetch the full x402 service index from the well-known URL.
    Caches locally for 1 hour. Returns list of service entries.
    """
    # Check cache
    if not force_refresh and CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text())
        age = time.time() - cache.get("cached_at", 0)
        if age < CACHE_TTL_SECONDS:
            return cache["services"]

    # Fetch fresh index
    resp = requests.get(WELL_KNOWN_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # Persist cache
    CACHE_FILE.write_text(json.dumps({
        "cached_at": time.time(),
        "services": data.get("services", [])
    }))

    return data.get("services", [])

def find_service(capability: str, max_price: float = None) -> dict | None:
    """Find a service from local cache without any API payment."""
    services = get_x402_index()
    matching = [
        s for s in services
        if capability in s.get("capability_tags", [])
        and (max_price is None or s.get("price_per_call", 999) <= max_price)
    ]
    if not matching:
        return None
    # Sort by quality tier: gold > silver > bronze > unverified
    tier_order = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
    matching.sort(key=lambda s: tier_order.get(s.get("quality_tier", "unverified"), 3))
    return matching[0]

if __name__ == "__main__":
    # Returns full index of all x402 services, no payment required
    index = get_x402_index()
    print(f"Loaded {len(index)} services from x402 discovery index")

    # Find a research service under $0.10/call
    service = find_service("research", max_price=0.10)
    if service:
        print(f"Best research service: {service['name']}")
        print(f"Inject into agent context: {service.get('llm_usage_prompt', 'N/A')}")
```

**Implementation pattern for framework builders:**

1. Fetch `/.well-known/x402-discovery` at agent startup
2. Cache locally with TTL = 1 hour
3. Filter by `capability_tags` to find relevant services
4. Extract `llm_usage_prompt` from matching entries
5. Inject these prompts into your agent's system context
6. The agent can now call those services without additional discovery

This pattern gives zero additional cost per agent run (the well-known URL is free), with 1-hour staleness tolerance.
