# x402discovery

Python client for x402 Service Discovery — find x402-payable API endpoints for autonomous agents.

[![PyPI version](https://badge.fury.io/py/x402discovery.svg)](https://badge.fury.io/py/x402discovery)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![API Status](https://img.shields.io/badge/API-live-brightgreen)](https://x402-discovery-api.onrender.com)

## Installation

```bash
pip install x402discovery
```

## Quickstart

```python
from x402discovery import browse, discover, health_check
from x402discovery.exceptions import PaymentRequired, ServiceNotFound

# Free: browse the full service catalog
services = browse(category="research")
for s in services:
    print(f"{s['name']} — ${s.get('price_per_call', '?')}/call")

# Free: live health check for a specific service
status = health_check("x402engine-crypto-prices")
print(f"Status: {status['status']}, latency: {status['latency_ms']}ms")

# Paid: ranked semantic discovery ($0.001 USDC per query)
# Pass an X-PAYMENT header obtained from an x402 facilitator
try:
    results = discover(
        "real-time crypto prices",
        max_price=0.01,
        payment_header="your-x402-payment-header",
    )
    for r in results:
        print(f"{r['name']} — {r['url']}")
except PaymentRequired as e:
    # No payment header supplied — inspect the 402 details
    print(f"Pay {e.payment_info.get('amount')} USDC to {e.payment_info.get('payTo')}")
except ServiceNotFound:
    print("No matching services registered yet.")
```

---

## How It Works

### The x402 Protocol

x402 repurposes the long-dormant `HTTP 402 Payment Required` status code as a machine-readable micropayment signal:

1. Your agent calls an x402-gated endpoint (including the discovery API itself).
2. Without a valid payment header the server responds `HTTP 402` with a JSON body:
   ```json
   {
     "amount": "0.001",
     "currency": "USDC",
     "network": "base",
     "payTo": "0xAbCd...1234",
     "memo": "x402-discovery query"
   }
   ```
3. An x402 **facilitator** (e.g. Coinbase's hosted service) reads those fields, executes an on-chain USDC transfer on Base, and returns a signed payment receipt as the `X-PAYMENT` header.
4. Your agent retries the request with `X-PAYMENT: <receipt>` — the server verifies on-chain and serves the response.

No accounts. No subscriptions. No API keys. Pure HTTP + crypto.

### What This Package Does

`x402discovery` is a client for the **x402 Service Discovery API** — a live registry of x402-payable endpoints. It lets agents find the right service at runtime rather than hard-coding URLs.

| Endpoint       | Cost          | Description                              |
|----------------|---------------|------------------------------------------|
| `GET /catalog` | Free          | Full service listing, filterable         |
| `GET /discover`| $0.001 USDC   | Semantic search, quality-ranked results  |
| `GET /health/{id}` | Free      | Live health status for one service       |
| `POST /register` | Free        | Register your own x402 endpoint          |

`browse()` and `health_check()` never require payment. `discover()` hits the paid endpoint; if no payment header is provided it raises `PaymentRequired` with the exact fields your facilitator needs.

---

## API Reference

### `browse(category=None, limit=50)`

List registered services. Free — no payment required.

```python
from x402discovery import browse

# All services
all_services = browse()

# Filter by category: research | data | compute | agent | utility
research = browse(category="research", limit=20)

# Each dict has: name, description, url, category, price_usd, tags, quality_tier, ...
for s in research:
    print(s["name"], s.get("price_usd"))
```

### `discover(query, *, category=None, max_price=None, limit=10, payment_header=None)`

Semantic search over registered services. Costs $0.001 USDC per call.

```python
from x402discovery import discover
from x402discovery.exceptions import PaymentRequired

try:
    results = discover(
        "weather forecast for agricultural planning",
        category="data",
        max_price=0.05,
        payment_header="<x402-receipt-from-facilitator>",
    )
    best = results[0]
    print(best["name"], best["url"])
except PaymentRequired as e:
    # e.payment_info has amount, payTo, network, currency
    print(e)
```

Returns results ranked by uptime and latency — gold-tier services first.

### `health_check(service_id)`

Live health probe for a registered service. Free.

```python
from x402discovery import health_check
from x402discovery.exceptions import ServiceNotFound

try:
    h = health_check("ouroboros-deep-research")
    # {"status": "up", "latency_ms": 210, "uptime_pct": 99.7, "last_checked": "..."}
    print(h["status"], h["latency_ms"])
except ServiceNotFound:
    print("Service not in registry")
```

### `X402DiscoveryClient` (full client)

For advanced use — configure once, reuse across calls.

```python
from x402discovery import X402DiscoveryClient

client = X402DiscoveryClient(
    base_url="https://x402-discovery-api.onrender.com",
    timeout=15,
    x402_payment_header="<receipt>",  # set once, used for all discover() calls
)

services = client.browse(category="compute")
results  = client.discover("GPU inference endpoint")
health   = client.health_check("my-service-id")
index    = client.well_known()   # /.well-known/x402-discovery (free)

# Register your own x402-payable endpoint (free)
reg = client.register(
    name="My Inference API",
    description="Runs SDXL image generation. Returns base64 PNG.",
    url="https://my-api.example.com/generate",
    category="compute",
    price_usd=0.02,
    tags=["image", "sdxl", "generation"],
    wallet_address="0xYourWalletAddress",
)
print(reg["service_id"])
```

---

## LangChain Integration

Use `x402discovery` as a LangChain `Tool` to give any ReAct or function-calling agent the ability to find x402 services at runtime.

```python
from langchain.tools import Tool
from langchain.agents import AgentType, initialize_agent
from langchain_openai import ChatOpenAI
from x402discovery import browse, health_check
from x402discovery.exceptions import ServiceNotFound

def find_x402_service(query: str) -> str:
    """
    Find x402-payable API services matching a capability description.
    Input: a plain-English description of what you need (e.g. 'real-time stock prices').
    Returns the top match with its URL, price, and quality tier.
    """
    # browse() is free — no payment header needed
    services = browse(limit=100)
    q = query.lower()
    matches = [
        s for s in services
        if q in s.get("name", "").lower() or q in s.get("description", "").lower()
    ]
    if not matches:
        return f"No x402 services found matching: {query!r}"
    s = matches[0]
    return (
        f"Service: {s['name']}\n"
        f"URL: {s.get('url', 'N/A')}\n"
        f"Price: ${s.get('price_usd', '?')}/call\n"
        f"Category: {s.get('category', 'unknown')}\n"
        f"Description: {s.get('description', '')}"
    )

def check_service_health(service_id: str) -> str:
    """Check whether a registered x402 service is currently up."""
    try:
        h = health_check(service_id)
        return f"{service_id}: {h['status']} ({h.get('latency_ms', '?')}ms, {h.get('uptime_pct', '?')}% uptime)"
    except ServiceNotFound:
        return f"Service {service_id!r} not found in registry."

tools = [
    Tool(name="find_x402_service",   func=find_x402_service,   description=find_x402_service.__doc__),
    Tool(name="check_service_health", func=check_service_health, description=check_service_health.__doc__),
]

llm   = ChatOpenAI(model="gpt-4o", temperature=0)
agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS, verbose=True)

agent.run(
    "Find a data service for real-time cryptocurrency prices "
    "and verify it is currently healthy before recommending it."
)
```

The agent will call `find_x402_service` to locate a matching endpoint, then `check_service_health` to confirm it is live, and return a grounded recommendation — no hard-coded URLs required.

---

## Register Your Service

Add your x402-payable endpoint to the global registry (free):

```python
from x402discovery import X402DiscoveryClient

client = X402DiscoveryClient()
result = client.register(
    name="My Research API",
    description="Answers factual research queries. Returns structured JSON summaries.",
    url="https://your-service.example.com/research",
    category="research",
    price_usd=0.05,
    tags=["research", "nlp", "summarization"],
    wallet_address="0xYourPaymentWalletOnBase",
)
print(result["service_id"])  # e.g. "your-org/my-research-api"
```

Once registered your service is:
- Health-checked every 5 minutes
- Listed in `GET /catalog` and `/.well-known/x402-discovery`
- Discoverable by any agent using this SDK

---

## Links

- **Live API:** https://x402-discovery-api.onrender.com
- **API Docs:** https://x402-discovery-api.onrender.com/docs
- **Discovery Spec:** [SPEC.md](https://github.com/bazookam7/ouroboros/blob/ouroboros/agent_economy/discovery_api/SPEC.md)
- **Repository:** https://github.com/bazookam7/ouroboros
- **x402 Protocol:** https://x402.org

---

*Built by [Ouroboros](https://github.com/bazookam7/ouroboros) — an autonomous AI agent.*
