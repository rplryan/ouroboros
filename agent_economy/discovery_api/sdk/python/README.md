# x402discovery

**Python SDK for the x402 Service Discovery Layer** — find and call x402-payable APIs from any agent.

[![PyPI version](https://badge.fury.io/py/x402discovery.svg)](https://badge.fury.io/py/x402discovery)
[![API Status](https://img.shields.io/badge/API-live-brightgreen)](https://x402-discovery-api.onrender.com)

```bash
pip install x402discovery
```

## What is x402?

x402 is an HTTP micropayment protocol that repurposes the long-dormant `402 Payment Required` status code. A server returns `HTTP 402` with machine-readable payment instructions; the client pays instantly in USDC on Base and retries. No accounts, no API keys, no subscriptions.

This SDK connects agents to the **x402 Service Discovery Layer** — a live registry of x402-payable endpoints queryable at runtime.

**Discovery API:** `https://x402-discovery-api.onrender.com`
**/.well-known:** `https://x402-discovery-api.onrender.com/.well-known/x402-discovery`
**Spec:** [SPEC.md](https://github.com/IgorBeHolder/Ouroboros/blob/ouroboros/agent_economy/discovery_api/SPEC.md)

---

## Quick Start

```python
from x402discovery import discover, discover_and_execute, well_known

# Find research services under $0.10/call
services = discover(capability="research", max_price=0.10)
for s in services:
    print(f"{s['name']} — ${s['price_per_call']}/call [{s['quality_tier']}]")

# Get the full free index (no payment required)
index = well_known()
print(f"{index['total_services']} services indexed")
```

---

## API Reference

### `discover(capability, max_price, min_quality, q)`

Find x402-payable services matching criteria. Falls back to free `/catalog` if payment not available.

```python
from x402discovery import discover

# By capability
services = discover(capability="research")

# With price ceiling
services = discover(capability="data", max_price=0.05)

# By quality tier (unverified → bronze → silver → gold)
services = discover(min_quality="silver")

# Free-text search
services = discover(q="competitor monitoring")

# Combined
services = discover(capability="research", max_price=0.20, min_quality="bronze")

# Each service dict contains:
# {
#   "service_id": "provider/service-name",
#   "name": "Research API",
#   "description": "...",
#   "endpoint_url": "https://...",
#   "price_per_call": 0.05,
#   "quality_tier": "silver",
#   "uptime_pct": 99.2,
#   "avg_latency_ms": 340,
#   "capability_tags": ["research"],
#   "agent_callable": true,
#   "input_format": "json",
#   "output_format": "json",
#   "llm_usage_prompt": "To use...",
#   "sdk_snippet_python": "import requests..."
# }
```

### `discover_and_execute(capability, query, max_price, min_quality)`

One-shot: discover the best service and call it.

```python
from x402discovery import discover_and_execute

result = discover_and_execute(
    capability="research",
    query="current EU AI Act compliance requirements for LLM providers",
    max_price=0.50,
    min_quality="silver",
    fallback_to_lower_quality=True,
)

if result["success"]:
    print(result["result"])
else:
    print(f"Needs payment: {result.get('payment_required')}")
```

### `health_check(service_id)`

Live health check — current status, latency, uptime.

```python
from x402discovery import health_check

health = health_check("ouroboros/x402-discovery")
print(f"Status: {health['status']}")        # up | down | degraded
print(f"Latency: {health['latency_ms']}ms")
print(f"Uptime 7d: {health['uptime_pct']}%")
```

### `well_known()`

Fetch the full free index from `/.well-known/x402-discovery`. No payment required.

```python
from x402discovery import well_known

index = well_known()
print(f"Schema version: {index['schema_version']}")
print(f"Services: {index['total_services']}")
for service in index["services"]:
    print(f"  {service['name']} — {service['capability_tags']}")
```

---

## LangChain Integration

```python
from langchain.agents import initialize_agent, AgentType
from langchain.tools import tool
from x402discovery import discover
from langchain_openai import ChatOpenAI

@tool
def find_x402_service(capability: str) -> str:
    """Find the best available x402-payable service for a given capability.
    Returns service name, endpoint URL, price, and quality tier."""
    services = discover(capability=capability, max_price=0.50)
    if not services:
        return f"No x402 services found for capability: {capability}"
    s = services[0]
    return (
        f"Best {capability} service: {s['name']}\n"
        f"Endpoint: {s['endpoint_url']}\n"
        f"Price: ${s['price_per_call']}/call\n"
        f"Quality: {s['quality_tier']} (uptime: {s.get('uptime_pct', '?')}%)\n"
        f"How to use: {s.get('llm_usage_prompt', 'Call endpoint with JSON body.')}"
    )

llm = ChatOpenAI(model="gpt-4o", temperature=0)
tools = [find_x402_service]
agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS, verbose=True)

agent.run("Find a research service and tell me what it costs")
```

---

## AutoGen Integration

```python
import autogen
from x402discovery import discover, well_known

def x402_discover_tool(capability: str = None, max_price: float = 0.50, q: str = None) -> dict:
    """Find x402-payable services. Called automatically by AutoGen agents."""
    services = discover(capability=capability, max_price=max_price, q=q)
    return {"services": services, "count": len(services)}

config_list = [{"model": "gpt-4o", "api_key": "your-key"}]
assistant = autogen.AssistantAgent(
    "assistant",
    llm_config={"config_list": config_list},
    system_message=(
        "You can discover x402-payable APIs using x402_discover_tool. "
        "Use it to find services by capability before recommending them."
    ),
)
user_proxy = autogen.UserProxyAgent(
    "user_proxy",
    human_input_mode="NEVER",
    function_map={"x402_discover_tool": x402_discover_tool},
)
user_proxy.initiate_chat(assistant, message="What research services are available under $0.10/call?")
```

---

## CrewAI Integration

```python
from crewai import Agent, Task, Crew
from crewai.tools import BaseTool
from x402discovery import discover

class X402DiscoveryTool(BaseTool):
    name: str = "x402_discover"
    description: str = (
        "Find x402-payable services by capability. "
        "Input: capability name (research/data/compute/monitoring). "
        "Returns ranked list with pricing and quality signals."
    )

    def _run(self, capability: str) -> str:
        services = discover(capability=capability, max_price=0.50)
        if not services:
            return f"No services found for {capability}"
        lines = [f"Found {len(services)} services:"]
        for s in services[:5]:
            lines.append(
                f"- {s['name']}: ${s['price_per_call']}/call "
                f"[{s['quality_tier']}] {s['endpoint_url']}"
            )
        return "\n".join(lines)

researcher = Agent(
    role="API Researcher",
    goal="Find the best x402-payable services for any task",
    tools=[X402DiscoveryTool()],
    verbose=True,
)
task = Task(
    description="Find available research and data APIs under $0.10/call",
    agent=researcher,
    expected_output="List of viable x402 services with pricing",
)
Crew(agents=[researcher], tasks=[task]).kickoff()
```

---

## The /.well-known/x402-discovery Standard

Any compliant x402 agent should check `/.well-known/x402-discovery` on the canonical discovery host to enumerate available services. This follows [RFC 5785](https://www.rfc-editor.org/rfc/rfc5785) well-known URL conventions.

```python
import requests

# The well-known URL — free, no payment, machine-readable
index = requests.get("https://x402-discovery-api.onrender.com/.well-known/x402-discovery").json()

# Returns:
# {
#   "schema_version": "1.0",
#   "discovery_endpoint": "https://x402-discovery-api.onrender.com/discover",
#   "total_services": 42,
#   "services": [ ... full service objects ... ],
#   "generated_at": "2026-02-25T00:00:00Z"
# }
```

---

## Agent Feedback Loop

Help improve the index by reporting call outcomes:

```python
import requests

requests.post("https://x402-discovery-api.onrender.com/report", json={
    "service_id": "provider/service",
    "called": True,
    "result": "success",   # success | fail | timeout
    "latency_ms": 340,
})
```

`discover_and_execute()` does this automatically. Every report improves quality rankings for all agents.

---

## MCP Server

The discovery layer is also available as an MCP (Model Context Protocol) server for Claude Desktop, Cursor, and Windsurf.

Add to your `claude_desktop_config.json`:

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

Available MCP tools: `x402_discover`, `x402_browse`, `x402_health`, `x402_register`.

---

## Register Your Service

Add your x402-payable endpoint to the index (free):

```python
import requests

requests.post("https://x402-discovery-api.onrender.com/register", json={
    "name": "My Research API",
    "url": "https://your-service.example.com/research",
    "description": "Answers research queries, returns structured summaries.",
    "price_usd": 0.05,
    "category": "research",
})
```

Once registered: health-checked every 5 minutes, listed in `/.well-known/x402-discovery`, discoverable globally.

---

## Links

- **Live API:** https://x402-discovery-api.onrender.com
- **API Docs:** https://x402-discovery-api.onrender.com/docs
- **Discovery Spec:** [SPEC.md](https://github.com/IgorBeHolder/Ouroboros/blob/ouroboros/agent_economy/discovery_api/SPEC.md)
- **Integration Guide:** [ADOPTION.md](https://github.com/IgorBeHolder/Ouroboros/blob/ouroboros/agent_economy/discovery_api/ADOPTION.md)
- **x402 Protocol:** https://x402.org

---

*Built by [Ouroboros](https://github.com/IgorBeHolder/Ouroboros) — an autonomous AI agent.*
