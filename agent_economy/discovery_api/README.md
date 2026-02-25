# x402 Service Discovery API

**Runtime discovery infrastructure for the x402 agent economy.**

Find any x402-payable API at runtime. Quality-ranked. Agent-native. Permanently free index.

🌐 **Live:** https://x402-discovery-api.onrender.com  
📋 **Spec:** [SPEC.md](SPEC.md) — x402 Service Discovery Protocol v0.1  
🔌 **MCP:** `GET /mcp` for Claude/Cursor tool manifest  
📡 **Well-Known:** `GET /.well-known/x402-discovery` — full index, no auth, free forever

---

## Why this exists

The x402 ecosystem has fragmented directories (x402scan.com, to402, x402 Studio) with no cross-index, no quality signals, and no runtime discovery for autonomous agents. Agents currently use hardcoded URLs — when an endpoint moves or goes down, the agent breaks.

This service is the aggregator layer: one query finds the best available endpoint for any capability, ranked by verified uptime and latency. Agents query at runtime instead of hardcoding URLs.

---

## Quickstart (Python, 3 lines)

```python
import requests

# Get full free catalog — no payment, no auth
catalog = requests.get("https://x402-discovery-api.onrender.com/.well-known/x402-discovery").json()
print(f"{catalog['total_services']} x402 services indexed")

# Or use the SDK (handles x402 payment for ranked results)
# from x402discovery import discover
# services = discover(capability="research", max_price=0.10)
```

---

## Endpoints

| Endpoint | Auth | Price | Description |
|---|---|---|---|
| `GET /.well-known/x402-discovery` | None | **Free** | Full machine-readable index (RFC 5785) |
| `GET /catalog` | None | **Free** | Full catalog with quality signals |
| `GET /discover?q=...&capability=...` | x402 | **$0.005** | Quality-ranked discovery |
| `GET /health/{service_id}` | None | **Free** | Live health check |
| `POST /report` | None | **Free** | Report call outcome (improves quality signals) |
| `POST /register` | None | **Free** | Submit your x402 endpoint |
| `GET /mcp` | None | **Free** | MCP tool manifest |
| `GET /docs` | None | **Free** | Swagger UI |

---

## Discovery Query Parameters

```
GET /discover?capability=research&max_price=0.10&min_quality=silver&q=competitor+monitoring
```

| Param | Values | Description |
|---|---|---|
| `capability` | research, data, compute, monitoring, verification, routing, storage, translation, classification, generation, extraction, summarization, enrichment, validation, other | Filter by capability |
| `max_price` | float (USD) | Maximum price per call |
| `min_quality` | unverified, bronze, silver, gold | Minimum quality tier |
| `q` | string | Free-text search |

Returns HTTP 402 with payment instructions. Pay $0.005 USDC on Base, retry with proof header.

---

## Service Schema

Every listing includes:

```json
{
  "service_id": "ouroboros/discovery",
  "name": "x402 Service Discovery",
  "description": "Find and query any x402-payable endpoint at runtime",
  "capability_tags": ["routing", "data"],
  "endpoint_url": "https://x402-discovery-api.onrender.com/discover",
  "price_per_call": 0.005,
  "pricing_model": "flat",
  "input_format": "json",
  "output_format": "json",
  "agent_callable": true,
  "auth_required": false,
  "llm_usage_prompt": "To use x402 Service Discovery, call https://x402-discovery-api.onrender.com/discover with x402 payment of 0.005 USDC. Send json input. Returns json.",
  "quality_tier": "gold",
  "uptime_pct": 99.8,
  "avg_latency_ms": 320
}
```

**Key fields for agents:**
- `agent_callable: true` — can be called without human approval
- `auth_required: false` — payment IS the auth (no API keys)
- `llm_usage_prompt` — inject directly into agent context to configure usage

---

## Well-Known URL Standard

```
GET /.well-known/x402-discovery
```

Free, permanent, no authentication. Returns full index as machine-readable JSON.

This follows RFC 5785 (well-known URIs). Any agent, crawler, or framework code that checks `/.well-known/x402-discovery` on a domain will find the complete x402 service catalog. We propose this as the standard well-known URL for x402 ecosystem discovery.

See [SPEC.md](SPEC.md) for the full proposed standard.

---

## Agent Feedback Loop

Report call outcomes to improve quality signals for everyone:

```bash
curl -X POST https://x402-discovery-api.onrender.com/report \
  -H "Content-Type: application/json" \
  -d '{"service_id": "provider/service", "called": true, "result": "success", "latency_ms": 450}'
```

The Python SDK (`discover_and_execute()`) does this automatically.

---

## Register Your x402 Endpoint

```bash
curl -X POST https://x402-discovery-api.onrender.com/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Service",
    "description": "What it does in one sentence.",
    "url": "https://my-service.example.com/api",
    "price_usd": 0.01,
    "category": "research",
    "capability_tags": ["research", "data"],
    "pricing_model": "flat"
  }'
```

---

## Python SDK

```python
# Install: pip install requests (SDK not yet on PyPI)
# Copy sdk/python/x402discovery/__init__.py into your project

from x402discovery import discover, health_check, well_known, discover_and_execute

# Find services
services = discover(capability="research", max_price=0.10, min_quality="bronze")

# Health check
status = health_check("ouroboros/discovery")

# Full free catalog
catalog = well_known()
```

See [sdk/python/README.md](sdk/python/README.md) for full SDK documentation.

---

## MCP Integration (Claude / Cursor / Windsurf)

Add to your MCP config:

```json
{
  "mcpServers": {
    "x402-discovery": {
      "url": "https://x402-discovery-api.onrender.com/mcp"
    }
  }
}
```

This gives Claude and other MCP-compatible agents a native `x402_discover` tool.

---

## Architecture

- **Runtime**: Render.com free tier (Python/FastAPI)
- **Database**: SQLite with health monitoring
- **Quality signals**: Background health checks every 5 minutes
- **Scraper**: x402scan.com indexed every 6 hours
- **Payment**: x402 v2 on Base, USDC, via Coinbase facilitator
- **Wallet**: `0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA` (CDP, Base)

---

## Spec / Standard Proposal

[SPEC.md](SPEC.md) — x402 Service Discovery Protocol v0.1

A proposed standard for agent-native service resolution. This document defines:
- The `/.well-known/x402-discovery` URL pattern
- Canonical service schema
- Quality signals methodology
- Agent feedback loop protocol

Submitted to the x402 Foundation as a proposed extension to x402 V2.
