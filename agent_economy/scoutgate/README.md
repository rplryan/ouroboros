# ScoutGate

**ScoutGate** is the supply-side onboarding ramp for the x402 ecosystem — part of the x402Scout product suite.

🌐 **Live at:** https://x402-scoutgate.onrender.com

Wrap any existing API in x402 payment logic in seconds. No x402 knowledge required.

## How it works

1. **Register your API**: POST your API URL, wallet address, price per call, and a name
2. **Get a proxy URL**: `https://x402-scoutgate.onrender.com/api/{id}/...`
3. **Agents pay**: Any x402-compatible agent can call your proxy — ScoutGate handles the full 402 / EIP-712 / settlement flow
4. **Earn USDC**: Payments land directly in your wallet on Base mainnet
5. **Auto-discovery**: Your API is automatically listed in the x402Scout catalog at https://x402scout.com

## Quick start (30 seconds)

**Register your API:**
```bash
curl -X POST https://x402-scoutgate.onrender.com/register \
  -H "Content-Type: application/json" \
  -d '{
    "api_url": "https://your-api.com",
    "wallet_address": "0xYourWalletAddress",
    "price_usd": 0.01,
    "name": "My API",
    "description": "Does something useful",
    "category": "data"
  }'
```

**Response:**
```json
{
  "api_id": "abc123",
  "proxy_url": "https://x402-scoutgate.onrender.com/api/abc123"
}
```

**Replace your original API URL with the proxy URL in your docs. Done.**

## What callers experience

Without payment → `402 Payment Required` with x402-compliant headers

With valid x402 payment header → full API response proxied through

## Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | None | Branded landing page with live stats |
| `/register` | GET | None | Registration UI (browser form) |
| `/register` | POST | None | Register an API for proxying (JSON API) |
| `/api/{id}/{path}` | GET/POST | x402 payment | Proxy call to your registered API |
| `/health` | GET | None | Service health + registered API count |
| `/docs` | GET | None | Swagger UI |

## Revenue model

ScoutGate takes a **2% fee (min $0.002 per call)** of each settled payment. Payments flow:
```
Agent → ScoutGate → CDP Settle → API Owner Wallet (98%)
                              → ScoutGate Wallet (2%)
```

## Environment variables

```
SCOUTGATE_WALLET=0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA
CDP_API_KEY_ID=...
CDP_API_KEY_SECRET=...
CDP_WALLET_ID=...
DISCOVERY_API_URL=https://x402scout.com
PORT=8000
```

## E2E verification

ScoutGate's settlement is verified on Base mainnet. The on-chain test:
- Payer `0x3EF037...` → Receive `0xDBBe14...`
- Balance change: +$0.0620 USDC confirmed on-chain
- Real Base mainnet settlement ✅

## Part of the x402Scout suite

| Product | Purpose | URL |
|---------|---------|-----|
| **x402Scout** | Service discovery | https://x402scout.com |
| **ScoutGate** | API monetization | https://x402-scoutgate.onrender.com |
| **RouteNet** | Smart routing | https://x402-routenet.onrender.com |
