# Contributing to x402 Service Discovery

Register your x402-payable endpoint to make it discoverable by autonomous agents worldwide.

## Quick Registration

```bash
curl -X POST https://x402-discovery-api.onrender.com/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Research API",
    "url": "https://your-service.example.com/endpoint",
    "description": "One sentence: what input, what output.",
    "price_usd": 0.05,
    "category": "research"
  }'
```

Or via Python:

```python
import requests

requests.post("https://x402-discovery-api.onrender.com/register", json={
    "name": "My Research API",
    "url": "https://your-service.example.com/endpoint",
    "description": "Answers research queries, returns structured JSON summaries.",
    "price_usd": 0.05,
    "category": "research",
})
```

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable service name (max 60 chars) |
| `url` | string | Your x402-gated endpoint URL (must be HTTPS) |
| `description` | string | One sentence: what input it takes, what it returns (max 160 chars) |
| `price_usd` | float | Price per call in USD (e.g. `0.005`) |
| `category` | string | Primary category (see list below) |

## Categories

`research` · `data` · `compute` · `monitoring` · `verification` · `routing` · `storage` · `translation` · `classification` · `generation` · `extraction` · `summarization` · `enrichment` · `validation` · `other`

## What Happens After Registration

1. **Immediate** — your service appears in `/catalog` and `/.well-known/x402-discovery`
2. **Within 5 minutes** — first health check runs (HEAD/GET to your URL)
3. **Quality tier assigned** — starts as `unverified`, upgrades automatically:
   - `bronze` — 3+ successful health checks
   - `silver` — 24h uptime ≥ 95%, avg latency < 1000ms
   - `gold` — 7d uptime ≥ 99%, avg latency < 500ms, 10+ quality signals

## Health Check Behavior

The discovery layer pings your endpoint every 5 minutes. Your endpoint should:

- Return **HTTP 200** (or **HTTP 402** — both confirm the endpoint is live)
- Respond within **10 seconds**
- Return consistent status codes

If your endpoint fails 3 consecutive health checks, it's marked `degraded`. After 24 consecutive failures, it's removed from search results but kept in the catalog.

## The x402 Contract

Your endpoint must return a valid x402 response for unpaid requests:

```json
{
  "x402Version": 1,
  "accepts": [{
    "scheme": "exact",
    "network": "base-mainnet",
    "maxAmountRequired": "5000",
    "resource": "https://your-service.example.com/endpoint",
    "description": "One call to My Service",
    "mimeType": "application/json",
    "payTo": "0xYourWalletAddress",
    "maxTimeoutSeconds": 60,
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "extra": {"name": "USDC", "version": "2"}
  }],
  "error": "X-PAYMENT header required"
}
```

## Quality Tiers

| Tier | Criteria | Benefit |
|------|----------|---------|
| `unverified` | Just registered | Listed in catalog |
| `bronze` | 3+ health checks passed | Higher search ranking |
| `silver` | 24h uptime ≥ 95%, latency < 1000ms | Priority discovery results |
| `gold` | 7d uptime ≥ 99%, latency < 500ms | Top-ranked, featured listing |

## Agent-Optimized Metadata (Optional)

Help agents select your service intelligently:

```json
{
  "capability_tags": ["research", "summarization"],
  "input_format": "natural_language",
  "output_format": "json",
  "agent_callable": true,
  "llm_usage_prompt": "To use this service, POST to {url} with {\"query\": \"your question\"}. Returns {\"answer\": ..., \"sources\": [...]}."
}
```

## Reporting Outcomes (Optional but Valuable)

After calling a discovered service, report the result to improve rankings for everyone:

```python
import requests

requests.post("https://x402-discovery-api.onrender.com/report", json={
    "service_id": "provider/service-name",
    "called": True,
    "result": "success",  # success | fail | timeout
    "latency_ms": 340,
})
```

This feedback loop makes the entire index more accurate over time — no central coordination needed.

## Resources

- [API Documentation](https://x402-discovery-api.onrender.com/docs)
- [Full Schema Spec](SPEC.md)
- [Integration Guide](ADOPTION.md)
- [Live Catalog](https://x402-discovery-api.onrender.com/catalog)
- [Well-Known Index](https://x402-discovery-api.onrender.com/.well-known/x402-discovery)
