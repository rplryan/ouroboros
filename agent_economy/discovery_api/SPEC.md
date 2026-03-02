# x402 Service Discovery Protocol v0.1
## A Proposed Standard for Agent-Native Service Resolution

**Status:** PROPOSED STANDARD  
**Version:** 0.1.0  
**Date:** 2026-02-25  
**Authors:** Ouroboros Project  
**Repository:** https://github.com/dorianjanezic/ouroboros/blob/ouroboros/agent_economy/discovery_api/  
**Reference Implementation:** https://x402-discovery-api.onrender.com  

---

## Abstract

The x402 micropayment protocol for HTTP (HTTP 402) enables autonomous agents to pay for API access without accounts, subscriptions, or human-mediated authentication. A payment token in the `X-PAYMENT` header is the complete access credential. However, the x402 ecosystem currently lacks a runtime mechanism by which an autonomous agent can discover which services exist, what capabilities they offer, what they cost, and whether they are currently operational. This document proposes a standard addressing that gap: a well-known URL pattern (`/.well-known/x402-discovery`), a canonical service listing schema, a quality signals methodology for continuous endpoint monitoring, and an agent feedback loop protocol that allows the index to improve through use.

This specification is motivated by the practical observation that the existing x402 service landscape is fragmented across several static, incomplete, or non-queryable directories. x402engine.com is defunct. to402.com/discover contains zero active listings. x402scan.com has indexed 1,354 servers but exposes no programmatic query interface. No cross-directory aggregator exists. No schema standard exists for machine-readable service metadata. The result is that autonomous agents must hardcode service URLs or fail to discover services entirely — a fundamental barrier to the emergence of a functioning agent economy. This specification proposes to fix that.

---

## 1. Motivation

### 1.1 The Fragmentation Problem

The x402 protocol specifies how to pay for an HTTP resource once you have its URL. It does not specify how to find that URL. This gap — service discovery — is currently addressed by no standard mechanism.

The existing landscape as of Q1 2026:

| Directory | Status | Queryable at Runtime? | Listing Count |
|---|---|---|---|
| x402engine.com | Defunct | No | — |
| to402.com/discover | Live, empty | Partially | 0 active |
| x402scan.com | Live, read-only | No API | ~1,354 indexed |
| This specification | Proposed standard | Yes | Open |

An autonomous agent operating in the wild — one that has been given a budget and a task, but not a specific service URL — has no mechanism to discover that a research API, a price feed, or a data enrichment service exists and is available for payment. The agent either requires a human to hardcode a URL before runtime, or it fails.

### 1.2 The Agent-Native Design Requirement

Human-oriented API directories (documentation sites, Postman collections, RapidAPI listings) are optimized for developer discovery at code-writing time. Agent-native service discovery has different requirements:

1. **Runtime access**: Discovery must be callable at agent execution time, not just at development time.
2. **Machine-readable schema**: Descriptions must be written for LLM consumption, not human browsing.
3. **Quality signals**: An agent cannot manually evaluate reliability. The index must provide verified uptime and latency data.
4. **Self-describing capability format**: The agent must be able to determine, from the index entry alone, whether a service meets its current task requirements.
5. **Invocation instructions**: Ideally, the index entry contains enough information for the agent to construct a valid API call without additional documentation.

### 1.3 Why a Well-Known URL Standard Matters

If every x402 service provider could expose a standard `/.well-known/x402-discovery` endpoint, the discovery problem becomes solvable without any central authority. Any agent that knows the x402 protocol can discover any x402 service by probing or aggregating from known providers. Central aggregators like the reference implementation described in Section 7 provide a convenient bootstrap point, but the architecture does not require them.

---

## 2. The /.well-known/x402-discovery Standard

### 2.1 Background

RFC 5785 defines a standard URL path prefix `/.well-known/` for well-known URIs. Services use this to expose metadata about themselves at predictable, stable URLs. Examples include `/.well-known/openid-configuration` (OpenID Connect), `/.well-known/security.txt` (responsible disclosure), and `/.well-known/acme-challenge/` (Let's Encrypt certificate validation).

This specification proposes `/.well-known/x402-discovery` as the standard path for x402 service self-description.

### 2.2 Requirements

A conforming x402 service implementation:

- **MUST** expose `GET /.well-known/x402-discovery` returning a JSON document conforming to the schema in Section 3.
- **MUST** return `Content-Type: application/json`.
- **MUST NOT** gate this endpoint behind an x402 payment. This endpoint exists to enable discovery; gating it defeats the purpose.
- **SHOULD** return HTTP 200. Any other status code indicates non-conformance.
- **SHOULD** return a stable, cacheable response. The `Cache-Control` header **SHOULD** include `max-age=3600` (1 hour).
- **MAY** return either a single service entry or an array of service entries if the host serves multiple x402-gated paths.

### 2.3 Example Response

A conforming `GET /.well-known/x402-discovery` response for a single-service host:

```json
{
  "x402_discovery_version": "0.1",
  "generated_at": "2026-02-25T12:00:00Z",
  "services": [
    {
      "service_id": "acme-corp/research-api",
      "name": "ACME Research API",
      "description": "Takes a research question as plain text input. Returns a structured JSON report with cited sources, a summary, and a confidence score. Suitable for due diligence, market research, and competitive analysis.",
      "capability_tags": ["research", "summarization", "extraction"],
      "endpoint_url": "https://api.acme-corp.example/research",
      "network": "base",
      "payment_token": "usdc",
      "price_per_call": 0.05,
      "pricing_model": "flat",
      "provider_wallet": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
      "listed_at": "2026-01-15T00:00:00Z",
      "last_verified": "2026-02-25T11:55:00Z",
      "agent_callable": true,
      "input_format": "natural_language",
      "output_format": "json",
      "auth_required": false,
      "llm_usage_prompt": "To use ACME Research API, call https://api.acme-corp.example/research with x402 payment of 0.05 USDC. Send natural_language input: a research question as plain text. Returns json.",
      "sdk_snippet_python": "import requests\nfrom x402.client import wrap\nresult = wrap(requests).get('https://api.acme-corp.example/research', params={'q': 'your question'}).json()",
      "sdk_snippet_javascript": "import { withPaymentInterceptor } from 'x402-axios';\nconst client = withPaymentInterceptor(axios.create(), wallet);\nconst result = await client.get('https://api.acme-corp.example/research', { params: { q: 'your question' } });"
    },
    {
      "service_id": "acme-corp/price-feed",
      "name": "ACME Crypto Price Feed",
      "description": "Takes a ticker symbol (e.g. BTC, ETH, SOL) as a query parameter. Returns current price in USD, 24h change, and volume. Sub-100ms latency. Supports 500+ tokens.",
      "capability_tags": ["data", "enrichment"],
      "endpoint_url": "https://api.acme-corp.example/price",
      "network": "base",
      "payment_token": "usdc",
      "price_per_call": 0.001,
      "pricing_model": "flat",
      "provider_wallet": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
      "listed_at": "2026-01-15T00:00:00Z",
      "last_verified": "2026-02-25T11:55:00Z",
      "agent_callable": true,
      "input_format": "json",
      "output_format": "json",
      "auth_required": false,
      "llm_usage_prompt": "To use ACME Crypto Price Feed, call https://api.acme-corp.example/price with x402 payment of 0.001 USDC. Send json input: a ticker symbol (e.g. BTC, ETH, SOL) as query parameter ?symbol=. Returns json with price_usd, change_24h, volume_24h.",
      "sdk_snippet_python": "import requests\nfrom x402.client import wrap\nresult = wrap(requests).get('https://api.acme-corp.example/price', params={'symbol': 'ETH'}).json()",
      "sdk_snippet_javascript": "const result = await client.get('https://api.acme-corp.example/price', { params: { symbol: 'ETH' } });"
    }
  ]
}
```

---

## 3. Schema Specification

This section defines the canonical schema for x402 service entries. All conforming implementations MUST support the required fields. Optional fields SHOULD be populated where applicable.

### 3.1 Required Fields

| Field | Type | Constraints | Description |
|---|---|---|---|
| `service_id` | string | format: `{provider_handle}/{service_slug}` | Unique identifier for the service. Provider handle is the organization or developer name (lowercase, hyphens OK). Service slug describes the specific service. Example: `"acme-corp/research-api"` |
| `name` | string | max 60 chars | Human-readable name. SHOULD be concise and descriptive. |
| `description` | string | max 160 chars | Written for an LLM reader: what input it takes, what output it returns. MUST NOT be marketing copy. MUST include input type and output type. |
| `capability_tags` | array[string] | controlled vocabulary (see §3.1.1) | One or more tags from the controlled vocabulary. MUST accurately reflect service capabilities. |
| `endpoint_url` | string | valid HTTPS URL | The live x402-gated URL. An HTTP GET or POST to this URL without `X-PAYMENT` MUST return HTTP 402. |
| `network` | enum | `base` \| `solana` \| `ethereum` \| `other` | Blockchain network for payment. Default: `"base"` |
| `payment_token` | enum | `usdc` \| `eth` \| `sol` \| `other` | Payment asset. Default: `"usdc"` |
| `price_per_call` | float | > 0, USD equivalent | Price in USD-equivalent per API call. For USDC on Base, this is a direct dollar amount. |
| `pricing_model` | enum | `flat` \| `outcome_triggered` \| `tiered` | `flat`: same price every call. `outcome_triggered`: charged only on successful result. `tiered`: price varies by usage tier. |
| `provider_wallet` | string | wallet address | The wallet address receiving payments. On Base/Ethereum, this is a 0x-prefixed EIP-55 checksum address. |
| `listed_at` | string | ISO 8601 datetime | When this service entry was first created. |
| `last_verified` | string | ISO 8601 datetime | When this entry was last verified by a monitoring system. |

#### 3.1.1 Controlled Vocabulary for capability_tags

Valid values: `research`, `data`, `compute`, `monitoring`, `verification`, `routing`, `storage`, `translation`, `classification`, `generation`, `extraction`, `summarization`, `enrichment`, `validation`, `other`

Multiple tags are permitted and encouraged. A service that accepts documents and returns summaries SHOULD tag as both `extraction` and `summarization`.

### 3.2 Quality Fields

Quality fields are populated by monitoring infrastructure (see Section 5). These fields MUST NOT be self-reported by the service provider; doing so undermines the trust model. A conforming aggregator MUST populate these from its own verification.

| Field | Type | Description |
|---|---|---|
| `uptime_7d` | float \| null | Percentage of health checks that returned success over the past 7 days. Null if fewer than 10 checks have been performed. |
| `latency_p50_ms` | integer \| null | Median response latency in milliseconds over the past 7 days. |
| `latency_p95_ms` | integer \| null | 95th percentile response latency in milliseconds over the past 7 days. |
| `quality_tier` | enum | `unverified` \| `bronze` \| `silver` \| `gold` |

#### 3.2.1 Quality Tier Criteria

| Tier | Uptime Requirement | p95 Latency Requirement | Monitoring Duration |
|---|---|---|---|
| `unverified` | No monitoring data | — | < 10 checks |
| `bronze` | ≥ 80% | < 2000ms | Any |
| `silver` | ≥ 95% | < 1000ms | ≥ 7 days |
| `gold` | ≥ 99% | < 500ms | ≥ 30 days |

Tier assignment is strict: all criteria for a tier must be simultaneously satisfied. A service with 99.5% uptime but 600ms p95 latency is `silver`, not `gold`.

### 3.3 Autonomous Adoption Fields

These fields represent the key innovation of this specification. They are designed to make x402 services callable by autonomous LLM agents without any additional documentation lookup.

**Design principle:** An agent should be able to extract a service entry from the index and immediately construct a valid, paid API call using only the information in that entry. No developer portal, no documentation site, no human in the loop.

| Field | Type | Description |
|---|---|---|
| `agent_callable` | boolean | `true` if this service can be called by an autonomous agent with no human approval required. MUST be `false` for services that require account setup, OAuth, or out-of-band registration. |
| `input_format` | enum | `json` \| `natural_language` \| `structured_prompt` \| `raw` — the format in which the primary input should be sent. |
| `output_format` | enum | `json` \| `markdown` \| `plain_text` \| `binary` — the format of the successful response body. |
| `auth_required` | boolean | For x402 endpoints, this MUST always be `false`. Payment IS the authentication. There is no separate auth step. |
| `llm_usage_prompt` | string | A pre-written instruction an LLM can inject directly into its own context to know how to call this service. Format: `"To use {service_name}, call {endpoint_url} with x402 payment of {price_per_call} USDC. Send {input_format} input: {description}. Returns {output_format}."` |
| `sdk_snippet_python` | string | Complete, copy-pasteable Python code snippet. Must include imports. SHOULD use the official x402 Python SDK where available. |
| `sdk_snippet_javascript` | string | Complete, copy-pasteable JavaScript/TypeScript code snippet. |

#### 3.3.1 The llm_usage_prompt Field

This field deserves special attention. It is not a human-readable description. It is a machine-readable instruction designed to be injected directly into an LLM's system prompt or tool description at runtime.

When an agent queries the discovery index and receives a result, it can:

1. Extract `llm_usage_prompt` from the matching service entry.
2. Inject it into its own context: `"Available tool: " + entry["llm_usage_prompt"]`
3. Call the service using that injected context, without any additional documentation.

This creates a self-bootstrapping capability injection mechanism. The service registers once; every agent that discovers it gains the ability to call it.

---

## 4. Query Protocol

### 4.1 Endpoint Summary

| Method | Path | Payment | Description |
|---|---|---|---|
| GET | `/.well-known/x402-discovery` | Free | Full index of all services. Never gated. Permanent and stable. |
| GET | `/discover` | $0.010 x402 | Quality-ranked search. Supports `capability`, `max_price`, `min_quality` parameters. |
| GET | `/service/{service_id}` | $0.002 x402 | Single service lookup by service_id. |
| GET | `/health/{service_id}` | Free | Live health check for a specific service. |
| GET | `/browse` | Free | Ungated paginated catalog. Returns all services sorted by quality tier. |

### 4.2 GET /.well-known/x402-discovery

Returns the complete service index. No payment required. This endpoint:

- MUST return HTTP 200 with `Content-Type: application/json`
- MUST return all active service entries
- MUST NOT require any form of authentication or payment
- SHOULD include `Cache-Control: public, max-age=3600`

**Response schema:**

```json
{
  "x402_discovery_version": "0.1",
  "generated_at": "<ISO8601>",
  "total_services": 42,
  "services": [ /* array of service entries per §3 */ ]
}
```

### 4.3 GET /discover

Quality-ranked search, gated at $0.010 USDC on Base.

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `capability` | string | Filter by capability tag from controlled vocabulary |
| `q` | string | Free-text keyword search across name, description, tags |
| `max_price` | float | Maximum price_per_call in USD |
| `min_quality` | string | Minimum quality tier: `bronze` \| `silver` \| `gold` |
| `network` | string | Filter by network |
| `limit` | integer | Maximum results, 1–50, default 10 |

**Without payment — HTTP 402 response:**

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

**With valid payment — HTTP 200 response:**

```json
{
  "results": [
    {
      "service_id": "acme-corp/research-api",
      "name": "ACME Research API",
      "description": "Takes a research question. Returns structured report with citations.",
      "capability_tags": ["research", "summarization"],
      "endpoint_url": "https://api.acme-corp.example/research",
      "price_per_call": 0.05,
      "quality_tier": "gold",
      "uptime_7d": 99.2,
      "latency_p50_ms": 340,
      "latency_p95_ms": 890,
      "agent_callable": true,
      "llm_usage_prompt": "To use ACME Research API, call https://api.acme-corp.example/research with x402 payment of 0.05 USDC. Send natural_language input: a research question. Returns json."
    }
  ],
  "count": 1,
  "query": {"capability": "research", "max_price": 0.10, "min_quality": "silver"},
  "queried_at": "2026-02-25T12:00:00Z"
}
```

### 4.4 GET /service/{service_id}

Returns the full schema entry for a single service. Gated at $0.002 USDC. Returns 404 if the service_id is not found.

### 4.5 GET /health/{service_id}

Live health check. Performs a real HTTP request to the service endpoint and returns the result. Always free. Returns:

```json
{
  "service_id": "acme-corp/research-api",
  "is_up": true,
  "latency_ms": 342,
  "http_status": 402,
  "checked_at": "2026-02-25T12:00:00Z",
  "uptime_7d": 99.2,
  "quality_tier": "gold"
}
```

Note: HTTP 402 is a valid "up" response — it means the service is operating and correctly requiring payment.

### 4.6 GET /browse

Free paginated catalog. Returns all services sorted by quality tier (gold first), then uptime descending. Supports `page` and `per_page` parameters.

---

## 5. Quality Signals Standard

### 5.1 Health Check Methodology

A conforming discovery aggregator MUST implement continuous endpoint health monitoring. The reference methodology:

1. **Method**: Issue an HTTP `HEAD` request to `endpoint_url`. Fall back to `GET` if `HEAD` returns 405.
2. **Timeout**: 10 seconds. Connections that do not complete within this window are recorded as failures.
3. **Frequency**: Every 5–15 minutes per endpoint. The reference implementation uses 5 minutes.
4. **Success criterion**: HTTP status < 500. HTTP 402 (Payment Required) is a success — it indicates the service is operational and correctly gating access.
5. **Failure criterion**: HTTP status ≥ 500, connection timeout, DNS failure, or any network error.

### 5.2 Data Recording

Each health check produces one record:

```
{
  endpoint_url: string,
  checked_at: ISO8601,
  is_up: boolean,
  latency_ms: integer | null,  // null on connection failure
  http_status: integer | null  // null on connection failure
}
```

Records MUST be timestamped in UTC. Records SHOULD be retained for at minimum 30 days to support `gold` tier evaluation.

### 5.3 Uptime Calculation

Uptime is calculated over a rolling 7-day window:

```
uptime_7d = (successful_checks / total_checks) * 100
```

Where `successful_checks` counts records where `is_up = true` within the past 168 hours, and `total_checks` counts all records within the same window.

A minimum of 10 checks must exist before uptime statistics are reported. Fewer than 10 checks results in `quality_tier: "unverified"` regardless of their outcomes.

### 5.4 Latency Percentiles

`latency_p50_ms` and `latency_p95_ms` are calculated from all successful checks (where `latency_ms is not null`) over the past 7-day window.

### 5.5 Quality Tier Promotion

Tier evaluation runs after each health check cycle. Promotion is automatic when criteria are satisfied. Demotion is also automatic and immediate.

A service that drops below its tier's uptime threshold is immediately demoted to the appropriate lower tier.

### 5.6 Staleness and Removal

An endpoint that accumulates 24 consecutive failures MUST be marked `status: degraded` and excluded from paid `/discover` results. It remains visible in `/browse` with its degraded status. After 72 consecutive failures (approximately 6 hours at 5-minute intervals), it MAY be marked `status: inactive` and excluded from all results except direct `/service/{service_id}` lookup.

---

## 6. Agent Feedback Loop

### 6.1 The POST /report Endpoint

Discovery aggregators implementing this specification SHOULD expose a `POST /report` endpoint for agent-submitted usage feedback.

**Request schema:**

```json
{
  "service_id": "acme-corp/research-api",
  "called": true,
  "result": "success",
  "latency_ms": 412,
  "agent_id": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `service_id` | string | Yes | The service that was called |
| `called` | boolean | Yes | Whether the agent actually attempted to call the service |
| `result` | enum | Yes | `"success"` \| `"fail"` \| `"timeout"` |
| `latency_ms` | integer | No | Observed end-to-end latency in milliseconds |
| `agent_id` | string \| null | No | Optional pseudonymous agent identifier. Never a real identity. |

**Authentication:** None required. Agent reports are pseudonymous by design. The protocol trusts the aggregate signal, not individual reporters.

### 6.2 Influence on Quality Scores

Agent-submitted reports are treated as supplementary signals:

- Reports with `result: "success"` provide positive weight toward uptime calculation.
- Reports with `result: "fail"` or `"timeout"` provide negative weight.
- Agent-reported latency contributes to a secondary latency estimate (not used for tier calculation, but reported separately as `agent_reported_latency_p50_ms`).
- Agent reports have lower weight than direct monitoring checks (ratio: 1:5 by default).

### 6.3 The Self-Improving Index

The agent feedback loop creates a virtuous cycle:

1. An agent queries the discovery index and finds a service.
2. The agent calls the service and reports the outcome.
3. The report updates quality signals for that service.
4. Future agents querying the index receive more accurate quality data.
5. High-quality services rise in rankings; poor-quality services fall.

This means agent usage itself trains the index without human intervention. The more agents use the index, the more accurate it becomes. No editorial review, no manual curation — quality emerges from aggregate agent behavior.

This is analogous to how search engine ranking improves from click-through data, except the signals are generated by autonomous software agents rather than human users.

---

## 7. Reference Implementation

### 7.1 Deployment

The reference implementation of this specification is deployed at:

- **API Base URL**: https://x402-discovery-api.onrender.com
- **Source Code**: https://github.com/dorianjanezic/ouroboros/blob/ouroboros/agent_economy/discovery_api/
- **Well-Known URL**: https://x402-discovery-api.onrender.com/.well-known/x402-discovery
- **Free Catalog**: https://x402-discovery-api.onrender.com/catalog
- **Paid Discovery**: https://x402-discovery-api.onrender.com/discover (requires $0.010 USDC)

### 7.2 Technical Stack

- **Framework**: FastAPI (Python 3.11+)
- **Storage**: SQLite for health monitoring data; JSON file for service registry
- **Health Monitoring**: Background asyncio task, 5-minute intervals
- **Hosting**: Render.com free tier
- **Payment Verification**: Delegates to https://x402.org/facilitator/verify

### 7.3 Payment Details

| Field | Value |
|---|---|
| Network | Base (Ethereum L2, Chain ID: 8453) |
| Asset | USDC |
| USDC Contract | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Recipient Wallet | `0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA` |
| Discovery query price | 10000 USDC units ($0.010) |

### 7.4 Conformance Notes

The reference implementation conforms to this specification with the following implementation-specific notes:

- The `service_id` field is stored as `id` internally and may use UUID format for legacy registrations.
- The `capability_tags` field is stored as `tags` internally.
- The `endpoint_url` field is stored as `url` internally.
- The `price_per_call` field is stored as `price_usd` internally.
- The `quality_tier` field is computed dynamically from `uptime_pct` and `avg_latency_ms`.
- The `/discover` endpoint supports `q` (free-text) and `category` parameters in the current implementation.

Future versions of the reference implementation will align field names with this specification exactly.

---

## 8. Future Extensions

### 8.1 Demand Signals API

A demand signals endpoint would aggregate anonymized query patterns to reveal where agent demand exceeds current supply. If 500 agents query for `capability: verification` in a 24-hour period but only 2 services are registered, this signal is valuable to potential service providers. Format:

```json
{
  "demand_signals": [
    {"capability": "verification", "queries_24h": 500, "services_available": 2, "demand_supply_ratio": 250},
    {"capability": "translation", "queries_24h": 200, "services_available": 0, "demand_supply_ratio": null}
  ]
}
```

### 8.2 Multi-Network Support

This specification currently focuses on USDC on Base. Extensions for Solana (SOL/USDC), Ethereum mainnet, and other EVM networks are planned. The `network` and `payment_token` fields in the schema are designed to accommodate this.

### 8.3 Provider Analytics Dashboard

A dashboard exposing per-service analytics to registered providers: discovery impressions, click-through rate, agent feedback scores, quality tier history. Free for providers; powered by x402 payments for detailed reports.

### 8.4 Cross-Directory Aggregation

If multiple directories adopt the `/.well-known/x402-discovery` standard, an aggregator can harvest all of them into a unified index by periodically fetching their well-known URLs. This creates a federated discovery layer with no central authority.

The aggregation algorithm must handle:
- Deduplication by `endpoint_url` across sources
- Conflict resolution for differing metadata
- Source credibility weighting

### 8.5 Verifiable Output Attestation

A cryptographic signing scheme for x402 API responses that allows downstream consumers to verify that a response was produced by a specific service at a specific time without re-querying it. This is useful for audit trails and for multi-step agent workflows where intermediate results must be attributed.

The attestation would be provided as an additional response header:

```
X-ATTESTATION: <base64-encoded-signature>
X-ATTESTATION-PUBKEY: <provider-public-key>
```

---

## 9. Security Considerations

### 9.1 Registry Poisoning

An adversarial actor could register a service with a well-crafted `description` or `llm_usage_prompt` designed to manipulate agent behavior. Mitigations:

- Discovery aggregators SHOULD sanitize and length-limit all text fields.
- The `llm_usage_prompt` field SHOULD be sanitized to remove prompt injection patterns.
- Quality tier requirements create a natural filter: newly registered services start at `unverified` and must demonstrate operational reliability before rising in rankings.

### 9.2 Payment Replay Attacks

The x402 payment protocol specifies a `maxTimeoutSeconds` field. Payments MUST expire within this window. The reference implementation sets this to 60 seconds.

### 9.3 Facilitator Dependency

The reference implementation delegates payment verification to `https://x402.org/facilitator/verify`. If the facilitator is unreachable, the reference implementation fails closed (returns 402, never grants free access). Conforming implementations MUST adopt the same fail-closed behavior.

### 9.4 Endpoint URL Validation

Registered endpoint URLs MUST be validated as HTTPS URLs. HTTP (non-TLS) endpoints SHOULD be rejected. This prevents traffic interception attacks on payment headers.

---

## 10. Copyright

This document is placed in the public domain. No rights reserved.

Implementations of this specification may be deployed, modified, and distributed without restriction. Attribution is appreciated but not required.

---

*End of x402 Service Discovery Protocol v0.1*
