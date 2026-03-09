# ScoutGate

**ScoutGate** is the supply-side onboarding ramp for the x402 ecosystem — part of the x402Scout product suite.

Wrap any existing API in x402 payment logic in seconds. No x402 knowledge required.

## How it works

1. **Register your API**: POST your API URL, wallet address, price per call, and a name
2. **Get a proxy URL**: `https://x402-scoutgate.onrender.com/api/{id}/...`
3. **Agents pay**: Any x402-compatible agent can call your proxy — ScoutGate handles the 402/payment/settlement flow
4. **Earn USDC**: Payments land directly in your wallet (minus ScoutGate's 0.5% fee)
5. **Auto-discovery**: Your API is automatically registered in the x402Scout catalog

## Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `POST /register` | None | Register an API for proxying |
| `GET /apis` | None | List all registered proxied APIs |
| `GET /api/{id}/{path}` | x402 payment | Proxy call to your API |
| `POST /api/{id}/{path}` | x402 payment | Proxy POST to your API |
| `GET /health` | None | Service health |
| `GET /stats` | None | Aggregate stats |

## Revenue model

ScoutGate takes **0.5%** (minimum $0.001) of each settled payment. Payments flow:
```
Agent → ScoutGate → CDP Settle → API Owner Wallet (99.5%)
                              → ScoutGate Wallet (0.5%)
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
