# x402 Service Discovery API

A registry of x402-payable endpoints. Agents query it to discover available services and their payment terms. Each discovery query costs **$0.005 USDC** on Base.

---

## What is this?

[x402](https://x402.org) is an open protocol for HTTP micropayments. Instead of API keys, services gate access via a single `X-PAYMENT` header containing a USDC payment on Base. No subscriptions, no accounts — just pay and go.

This service is a **discovery layer**: it maintains a registry of x402-payable endpoints across the ecosystem, making it easy for AI agents and developers to find and pay for the services they need.

---

## Pricing

| Endpoint | Cost | Payment Required? |
|---|---|---|
| `GET /` | Free | No |
| `GET /catalog` | Free | No |
| `GET /mcp` | Free | No |
| `POST /register` | Free | No |
| `GET /discover` | **$0.005 USDC** | Yes — `X-PAYMENT` header |
| `GET /health/{id}` | **$0.05 USDC** | Yes — `X-PAYMENT` header |

---

## Wallet & Network

| Field | Value |
|---|---|
| Network | Base (Ethereum L2) |
| Asset | USDC |
| USDC Contract | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Wallet | `0xBceC11f20904a30fC4bAF70B85fc33b7A9294683` |
| Query price (USDC units) | `5000` ($0.005) |
| Health check price (USDC units) | `50000` ($0.05) |

---

## Usage

### Free: Browse the catalog

```bash
curl https://your-deployment.onrender.com/catalog
```

### Free: Service info

```bash
curl https://your-deployment.onrender.com/
```

### Paid: Discover endpoints (requires x402 payment)

Without payment — returns 402 with payment instructions:

```bash
curl https://your-deployment.onrender.com/discover?q=crypto+price
```

```json
{
  "error": "Payment Required",
  "x402Version": 1,
  "accepts": [{
    "scheme": "exact",
    "network": "base",
    "maxAmountRequired": "5000",
    "resource": "https://your-deployment.onrender.com/discover",
    "description": "x402 Service Discovery Query",
    "mimeType": "application/json",
    "payTo": "0xBceC11f20904a30fC4bAF70B85fc33b7A9294683",
    "maxTimeoutSeconds": 60,
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "extra": {"name": "USDC", "version": "2"}
  }]
}
```

With payment (using the [x402 JS/Python SDK](https://github.com/coinbase/x402)):

```bash
curl https://your-deployment.onrender.com/discover?q=research \
  -H "X-PAYMENT: <base64-encoded-payment-payload>"
```

### Paid: Live health check

```bash
curl https://your-deployment.onrender.com/health/x402engine-crypto-prices \
  -H "X-PAYMENT: <base64-encoded-payment-payload>"
```

### Free: Register your endpoint

```bash
curl -X POST https://your-deployment.onrender.com/register \
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

### Scoring

Results are ranked by relevance:

- Exact tag match: **+3 pts**
- Description keyword match: **+2 pts**
- Name keyword match: **+1 pt**

Tiebreaker: `query_count` descending (most popular first).

---

## MCP Integration

To add this service as a tool in Claude, Cursor, or any MCP-compatible host:

```bash
curl https://your-deployment.onrender.com/mcp
```

This returns an MCP tool manifest with all four tools:

- `discover_endpoints` — search the registry (paid)
- `register_endpoint` — add your endpoint (free)
- `browse_catalog` — list everything (free)
- `live_health_check` — test an endpoint (paid)

For Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "x402-discovery": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-fetch"],
      "env": {
        "BASE_URL": "https://your-deployment.onrender.com"
      }
    }
  }
}
```

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

## Deploy to Render

1. Fork this repo or copy the `agent_economy/discovery_api/` directory.
2. Create a new Web Service on [Render](https://render.com).
3. Point it at the directory containing `render.yaml`.
4. Render will auto-detect the config and deploy.
5. Set the `PORT` env var (Render injects this automatically).

---

## Local Development

```bash
cd agent_economy/discovery_api
pip install -r requirements.txt
python main.py
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

---

## Architecture Notes

- **Registry persistence**: `registry.json` is loaded at startup and written on every mutation (register, health check). For production scale, swap for Redis or Postgres.
- **Payment verification**: Delegates entirely to `https://x402.org/facilitator/verify`. If the facilitator is unreachable, the endpoint returns 402 rather than granting free access.
- **No payment payloads in logs**: The `X-PAYMENT` header value is never logged. Only timestamps, query params, and payment validity outcomes are recorded.
- **Free catalog**: `GET /catalog` returns all endpoints without quality signals (no query_count, no uptime). Use it for browsing; use `/discover` for ranked, agent-optimised results.

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
