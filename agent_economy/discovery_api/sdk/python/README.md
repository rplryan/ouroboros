# x402discovery — Python SDK

Find and call x402-payable API services from any Python agent. One import, one function call.

## Install

```bash
pip install requests  # Only dependency until on PyPI
# Soon: pip install x402discovery
```

For now, copy `x402discovery/__init__.py` into your project.

## Quickstart

```python
from x402discovery import discover, discover_and_execute

# Find the best research service under $0.10/call
services = discover(capability="research", max_price=0.10)
if services:
    print(services[0]["name"])          # "Deep Research API"
    print(services[0]["endpoint_url"])  # "https://..."
    print(services[0]["price_per_call"]) # 0.005

# Get the full free index (no payment required)
from x402discovery import well_known
catalog = well_known()
print(f"{catalog['total_services']} services indexed")

# Check if a service is live right now
from x402discovery import health_check
status = health_check("ouroboros/discovery")
print(status["health_status"])  # "up", "down", "unknown"
```

## Functions

### `discover(capability, max_price, min_quality, q)`

Find services matching criteria. Returns list sorted by quality tier.

```python
# By capability tag
services = discover(capability="research")

# By price ceiling
services = discover(max_price=0.05)

# By quality tier
services = discover(min_quality="silver")

# Free-text search
services = discover(q="competitor monitoring")

# Combined
services = discover(capability="monitoring", max_price=0.10, min_quality="bronze")
```

**Capability tags:** `research`, `data`, `compute`, `monitoring`, `verification`,
`routing`, `storage`, `translation`, `classification`, `generation`,
`extraction`, `summarization`, `enrichment`, `validation`, `other`

**Quality tiers:** `unverified` → `bronze` → `silver` → `gold`

### `discover_and_execute(capability, query, max_price, min_quality)`

One-shot: discover the best service + call it with your query.

```python
result = discover_and_execute(
    capability="research",
    query="current EU AI Act compliance requirements for LLM providers",
    max_price=0.50,
    min_quality="bronze",
)

if result["success"]:
    print(result["result"])
else:
    print("x402 payment required:", result.get("payment_required"))
```

### `health_check(service_id_or_url)`

Live health check on any indexed service.

```python
status = health_check("ouroboros/discovery")
# Returns: {service_id, status, latency_ms, checked_at, uptime_pct}
```

### `well_known()`

Fetch the full free catalog (no payment).

```python
catalog = well_known()
# Returns: {version, total_services, updated_at, services: [...]}
```

## Discovery API

Base URL: `https://x402-discovery-api.onrender.com`

| Endpoint | Auth | Price | Description |
|---|---|---|---|
| `GET /discover` | x402 | $0.005 | Ranked discovery with quality signals |
| `GET /catalog` | None | Free | Full unranked catalog |
| `GET /.well-known/x402-discovery` | None | Free | RFC 5785 machine-readable index |
| `GET /health/{id}` | None | Free | Live health check |
| `POST /report` | None | Free | Agent outcome reporting |
| `POST /register` | None | Free | Submit your x402 endpoint |

## Schema

Every service in the catalog has:

```json
{
  "service_id": "provider/service-slug",
  "name": "Human-readable name",
  "description": "What it does in one sentence.",
  "capability_tags": ["research", "data"],
  "endpoint_url": "https://...",
  "price_per_call": 0.005,
  "pricing_model": "flat",
  "input_format": "json",
  "output_format": "json",
  "agent_callable": true,
  "auth_required": false,
  "llm_usage_prompt": "To use ..., call ... with x402 payment of ... USDC.",
  "quality_tier": "silver",
  "uptime_pct": 99.2,
  "avg_latency_ms": 450
}
```

## Why `auth_required` is always false

x402 payment IS the authentication. There are no API keys, no accounts, no signup.
An agent that can pay can call. No human approval required at call time.

## Spec

See [SPEC.md](../SPEC.md) for the full x402 Service Discovery Protocol v0.1 specification.
