# x402 Service Discovery API

A registry of x402-payable endpoints with **quality signals**. Agents query it to discover available services ranked by uptime, latency, and health status. Each discovery query costs **$0.005 USDC** on Base.

---

## What is this?

[x402](https://x402.org) is an open protocol for HTTP micropayments. Instead of API keys, services gate access via a single `X-PAYMENT` header containing a USDC payment on Base. No subscriptions, no accounts — just pay and go.

This service is the **discovery layer**: it maintains a quality-ranked registry of x402-payable endpoints, making it easy for AI agents and developers to find reliable services. Unlike static directories, this service continuously monitors endpoint health and ranks results by verified uptime and latency — a data moat that compounds daily.

---

## Quality Signals

Every registered endpoint is automatically monitored every 5 minutes. Results from `/discover` and `/catalog` include:

| Field | Description |
|---|---|
| `uptime_pct` | % of health checks that returned success (last 7 days) |
| `avg_latency_ms` | Average response latency in milliseconds (last 7 days) |
| `total_checks` | Total health checks performed (last 7 days) |
| `successful_checks` | Number of successful checks |
| `last_health_check` | ISO timestamp of most recent check |
| `health_status` | `"verified_up"` / `"degraded"` / `"unverified"` |

### Health Status Definitions

| Status | Meaning |
|---|---|
| `verified_up` | ≥95% uptime in last 7 days |
| `degraded` | <80% uptime in last 7 days |
| `unverified` | Not yet checked, or insufficient data |

### Result Ranking

`/discover` results are sorted by:
1. **Uptime %** — descending (most reliable first)
2. **Avg latency** — ascending (fastest first)
3. **Registration date** — descending (newest first, as tiebreaker)

---

## Pricing

| Endpoint | Cost | Payment Required? |
|---|---|---|
| `GET /` | Free | No |
| `GET /catalog` | Free | No |
| `GET /mcp` | Free | No |
| `POST /register` | Free | No |
| `GET /health/{id}` | **Free** | No (ungated for now) |
| `GET /discover` | **$0.005 USDC** | Yes — `X-PAYMENT` header |

---

## Wallet & Network

| Field | Value |
|---|---|
| Network | Base (Ethereum L2) |
| Asset | USDC |
| USDC Contract | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Wallet | `0xBceC11f20904a30fC4bAF70B85fc33b7A9294683` |
| Discovery price (USDC units) | `5000` ($0.005) |

---

## Usage

### Free: Browse catalog with quality signals

```bash
curl https://x402-discovery-api.onrender.com/catalog
```

Returns all endpoints with uptime %, latency, and health status.

### Free: Live health check for a specific endpoint

```bash
curl https://x402-discovery-api.onrender.com/health/{endpoint_id}
```

Returns real-time check: is this endpoint reachable right now? Includes latency, HTTP status, and 7-day uptime history.

### Free: Service info

```bash
curl https://x402-discovery-api.onrender.com/
```

### Paid: Discover endpoints (quality-ranked, requires x402 payment)

Without payment — returns 402 with payment instructions:

```bash
curl https://x402-discovery-api.onrender.com/discover?q=crypto+price
```

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
    "payTo": "0xBceC11f20904a30fC4bAF70B85fc33b7A9294683",
    "maxTimeoutSeconds": 60,
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "extra": {"name": "USDC", "version": "2"}
  }]
}
```

With payment (using the [x402 SDK](https://github.com/coinbase/x402)):

```bash
curl https://x402-discovery-api.onrender.com/discover?q=research \
  -H "X-PAYMENT: <base64-encoded-payment-payload>"
```

**Sample quality-enriched response:**

```json
{
  "results": [
    {
      "id": "abc-123",
      "name": "x402Engine Crypto Price Feed",
      "description": "Real-time BTC/ETH prices via x402",
      "url": "https://api.x402engine.com/price",
      "category": "data",
      "price_usd": 0.001,
      "tags": ["crypto", "price", "btc", "eth"],
      "uptime_pct": 99.2,
      "avg_latency_ms": 187,
      "total_checks": 288,
      "successful_checks": 285,
      "last_health_check": "2026-02-25T21:00:00Z",
      "health_status": "verified_up"
    }
  ],
  "count": 1,
  "query": {"q": "crypto", "category": null, "limit": 10},
  "queried_at": "2026-02-25T21:01:00Z"
}
```

### Free: Register your endpoint

```bash
curl -X POST https://x402-discovery-api.onrender.com/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Price Feed",
    "description": "Real-time ETH/USD price, pay per query",
    "url": "https://my-service.example.com/api/price",
    "category": "data",
    "price_usd": 0.001,
    "network": "base",
    "asset_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "tags": ["price", "eth", "defi"]
  }'
```

---

## Query Parameters for `/discover`

| Param | Type | Default | Description |
|---|---|---|---|
| `q` | string | — | Keyword search across name, description, tags |
| `category` | string | — | Filter: `research`, `data`, `compute`, `agent`, `utility` |
| `limit` | integer | 10 | Max results, 1–50 |

### Scoring (relevance phase)

Results first pass a relevance filter, then are re-sorted by quality:

- Exact tag match: **+3 pts**
- Description keyword match: **+2 pts**
- Name keyword match: **+1 pt**

After relevance filtering, results are sorted by: uptime % → latency → registration date.

---

## MCP Integration

To add this service as a tool in Claude, Cursor, or any MCP-compatible host:

```bash
curl https://x402-discovery-api.onrender.com/mcp
```

This returns an MCP tool manifest with four tools:

| Tool | Payment | Description |
|---|---|---|
| `discover_endpoints` | $0.005 | Quality-ranked keyword search |
| `browse_catalog` | Free | List all endpoints |
| `register_endpoint` | Free | Add your endpoint |
| `live_health_check` | Free | Real-time check for one endpoint |

---

## Categories

| Category | Description |
|---|---|
| `research` | AI-powered research, synthesis, RAG |
| `data` | Price feeds, filings, real-time data |
| `compute` | Model inference, consensus, processing |
| `agent` | Autonomous agents, workflow automation |
| `utility` | Proxies, gateways, infrastructure |

---

## Architecture

### Data flow

```
background task (every 5 min)
  └─ pings each endpoint URL (HEAD request, 10s timeout)
       └─ records result → SQLite (health.db)
            └─ updates in-memory registry

/discover query (paid)
  └─ relevance filter + scoring
       └─ _enrich_with_quality() — reads SQLite stats
            └─ re-sort by uptime/latency
                 └─ return ranked results

/health/{id} (free)
  └─ live GET request → records to SQLite → returns full stats
```

### Storage

- **`registry.json`** — endpoint metadata, persisted to disk on every mutation
- **`health.db`** — SQLite database with `endpoint_health` table, indexed by URL

### Schema: `endpoint_health`

```sql
CREATE TABLE endpoint_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_url TEXT NOT NULL,
    checked_at TEXT NOT NULL,   -- ISO 8601 UTC
    is_up INTEGER NOT NULL,     -- 0 or 1
    latency_ms INTEGER,         -- NULL if timeout
    http_status INTEGER         -- NULL if connection failed
);
CREATE INDEX idx_endpoint_health_url ON endpoint_health(endpoint_url);
```

### Payment verification

Delegates to `https://x402.org/facilitator/verify`. If the facilitator is unreachable, endpoints return 402 (fail-closed — never grants free access).

### No secrets in logs

The `X-PAYMENT` header value is never logged. Only timestamps, query params, and payment validity outcomes are recorded.

---

## Local Development

```bash
cd agent_economy/discovery_api
pip install -r requirements.txt
python main.py
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

The SQLite `health.db` is created automatically on first run.

---

## Pre-seeded Services

| Name | Category | Price | Status |
|---|---|---|---|
| Cloudflare Pay Per Crawl | data | $0.001 | active |
| x402Engine Crypto Price Feed | data | $0.001 | active |
| to402.com API Proxy | utility | $0.002 | active |
| x402agent.shop n8n Marketplace | agent | $0.01 | active |
| AgentSearch Research API | research | $0.005 | community |
| Regulatory Filings Feed | data | $0.01 | community |
| Ouroboros Research API | research | $0.05 | coming_soon |
| Ouroboros Multi-Model Consensus | compute | $0.025 | coming_soon |
