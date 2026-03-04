# scout_relay — Intelligent Payment Router for AI Agents

> **Find the best payment path. Execute it. Return the result.**
> Built on x402-discovery-mcp.

---

## The Problem

AI agents need to transact. They can discover x402-gated APIs (via x402-discovery-mcp), but discovery is only half the problem. After finding a provider, the agent still must:

- Select the single best option from a ranked list
- Hold and manage a USDC wallet
- Construct and sign the x402 payment payload
- Submit to a facilitator
- Handle failures and retry with the next provider
- Fall back to non-x402 rails when no x402 option exists

Every agent developer solves this problem from scratch. There is no single call that takes "I need weather data for Cincinnati" and returns the data. scout_relay is that call.

---

## What scout_relay Does

scout_relay collapses the discovery → selection → payment → result cycle into a single atomic operation for AI agents and the developers who build them.

**Without scout_relay:**
```
agent → x402_discover() → list of options → pick one → construct wallet tx
      → sign payment → submit to facilitator → await confirmation
      → retry if failed → handle fallback → parse response → use result
```

**With scout_relay:**
```
agent → scout_relay.route("weather data for Cincinnati", budget=0.01) → result
```

scout_relay handles everything in between.

---

## Architecture

scout_relay is a routing intelligence layer built directly on top of x402-discovery-mcp. It does not replace the discovery server — it consumes it and adds execution.

```
┌─────────────────────────────────────────────────────┐
│                    AI Agent                         │
│           scout_relay.route(intent, budget)               │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│                  SCOUT_RELAY ROUTER                       │
│                                                     │
│  1. Intent parsing  →  capability + constraints     │
│  2. Discovery       →  x402-discovery-mcp catalog   │
│  3. Selection       →  price + trust + latency rank │
│  4. Rail selection  →  x402 / ACH / gift card / card│
│  5. Execution       →  payment + retry logic        │
│  6. Response        →  normalized result to agent   │
└──────┬──────────┬──────────────┬────────────────────┘
       │          │              │
  ┌────▼───┐  ┌───▼────┐  ┌─────▼──────┐
  │ x402   │  │ Bridge │  │  Card/Gift  │
  │ (USDC) │  │ (ACH)  │  │  Fallback  │
  └────────┘  └────────┘  └────────────┘
```

### Rail Priority Order

| Priority | Rail | Used When |
|---|---|---|
| 1 | x402 / USDC (Base) | x402-gated API exists for the capability |
| 2 | x402 / USDC (Solana) | Base option unavailable or slower |
| 3 | Bridge → ACH | B2B vendor or service with bank account, no x402 |
| 4 | Gift card API (Tremendous) | Major retailer or brand merchant |
| 5 | Card (Alchemy Pay / Immersve) | Last resort, physical/traditional merchant |

scout_relay always prefers the cheapest, fastest, most trust-verified path. Rail selection is automatic and invisible to the calling agent.

---

## Core Capabilities

### `scout_relay.route(intent, budget, constraints?)`
The primary interface. Agent provides a natural-language intent and optional budget ceiling. scout_relay returns the result of the best available payment path.

```python
result = await scout_relay.route(
    intent="current BTC price with 5-second freshness",
    budget_usd=0.005,
    constraints={"min_trust_score": 80}
)
# Returns: {"price": 94230.50, "timestamp": "...", "source": "Tavily Crypto", "cost_paid": 0.002}
```

### `scout_relay.discover(capability, max_price?)`
Thin wrapper over x402-discovery-mcp. Returns ranked options without executing. Useful when the developer wants to inspect options before committing.

### `scout_relay.execute(endpoint, payload, wallet?)`
Direct execution against a known x402 endpoint. For agents that know exactly what they want and just need payment handled.

### `scout_relay.budget(agent_id, limit, period?)`
Set a spending cap for a given agent identity. scout_relay enforces this at the routing layer — the agent cannot exceed its budget regardless of intent.

### `scout_relay.audit(agent_id, from?, to?)`
Full transaction log for an agent: what was purchased, which rail was used, what was paid, timestamps. Exportable for compliance.

---

## Trust Layer (via ERC-8004)

All routing decisions incorporate ERC-8004 on-chain trust signals inherited from x402-discovery-mcp:

- `erc8004_reputation_score` — on-chain reputation (0–100)
- `erc8004_attestations` — number of verified attestations
- `erc8004_verified` — whether provider hosts a `.well-known/erc8004.json`

By default, scout_relay will not route to providers with reputation scores below 50. Developers can adjust this threshold. This prevents agents from paying for fraudulent or unreliable services discovered in the catalog.

---

## Monetization

### Layer 1 — Routing Spread
Every routed transaction includes a small scout_relay fee embedded in the total. The agent pays the provider price plus scout_relay's spread; the calling agent/developer sees a single line item. scout_relay remits the provider amount and retains the spread.

- Default spread: 8–12% of provider price
- On a $0.005 query: scout_relay earns ~$0.0005
- At x402 Bazaar scale (33M+ tx/month): material recurring revenue
- Spread is invisible to agents optimizing for outcome, not fee structure

### Layer 2 — Priority Placement Fee (Provider-Side)
When two or more providers are comparably ranked on price, trust score, and latency, scout_relay's tiebreaker is which provider has paid a placement fee for that capability category. The fee is a per-transaction surcharge paid by the provider on every transaction actually routed to them — not a flat subscription, not a listing fee.

- Provider sets a placement bid per capability category (e.g. "weather data", "crypto prices", "web search")
- scout_relay routes to the highest bidder among providers that are genuinely competitive on merit
- Provider pays the surcharge only when they receive a transaction — zero cost for impressions or catalog presence
- Bid floor: $0.0001 per routed transaction
- scout_relay collects the surcharge at settlement, on top of the routing spread from Layer 1

This preserves router integrity — a provider cannot buy their way to the top if their price or trust score disqualifies them — while creating a pure pay-for-performance revenue stream that scales directly with transaction volume.

---

## Competitive Position

| Product | Discovery | Execution | Multi-rail | Agent-native |
|---|---|---|---|---|
| x402-discovery-mcp (current) | ✅ | ❌ | ❌ | ✅ |
| **scout_relay (this product)** | ✅ | ✅ | ✅ | ✅ |
| Coinbase Agentic Wallets | ❌ | ✅ | ❌ (x402 only) | ✅ |
| Stripe Machine Payments | ❌ | ✅ (merchant-side) | ❌ | Partial |
| Natural.co | ❌ | ✅ | ❌ | ✅ (B2B only) |
| Privacy.com (USDC cards) | ❌ | ✅ | ❌ (card only) | ❌ |

**The gap scout_relay fills:** No existing product combines discovery + execution + multi-rail routing + agent-native interface. Coinbase and Stripe are building rails, not routing intelligence. scout_relay is the routing intelligence layer that sits above all rails — including theirs.

---

## Relationship to x402-discovery-mcp

scout_relay is an extension of x402-discovery-mcp, not a replacement or competitor.

- x402-discovery-mcp remains the open-source discovery layer — free, MIT licensed, community-owned
- scout_relay is the commercial execution layer built on top of it
- Every scout_relay transaction begins with an x402-discovery-mcp catalog query
- scout_relay's traction grows x402-discovery-mcp adoption; x402-discovery-mcp's traction creates scout_relay's addressable market

This is the same relationship GitHub has to Git — the open protocol drives adoption of the commercial product. Keeping x402-discovery-mcp open and free is strategically correct regardless of scout_relay's commercial trajectory.

---

## Development Phases

### Phase 1 — x402 Execution Layer (MVP)
**Scope:** Add execution to existing discovery. Agent calls scout_relay, scout_relay selects best x402 provider, executes payment, returns result.

- x402 payment signing and submission
- Facilitator integration (Coinbase hosted + self-hosted option)
- Retry logic and fallback to next-ranked provider
- Basic spend logging

**Timeline:** 3–4 weeks. Builds directly on existing server.py.

### Phase 2 — Budget & Audit
**Scope:** Agent identity, spending caps, transaction history.

- Agent ID system (wallet-based or API key)
- Per-agent budget enforcement
- Audit log API
- Developer dashboard (basic)

**Timeline:** 3–4 weeks after Phase 1.

### Phase 3 — Multi-Rail
**Scope:** ACH and gift card fallback rails for non-x402 merchants.

- Bridge API integration (USDC → ACH)
- Tremendous API integration (gift card execution)
- Rail selection logic
- Card fallback (Alchemy Pay)

**Timeline:** 6–8 weeks after Phase 2.

### Phase 4 — Enterprise & Monetization
**Scope:** Paid tiers, priority routing marketplace, provider dashboard.

- Stripe billing integration for developer tiers
- Provider dashboard (routing analytics, priority listing purchase)
- SLA infrastructure
- Enterprise onboarding

**Timeline:** Parallel with Phase 3 where possible.

---

## Open Questions

- [ ] Self-hosted facilitator vs. Coinbase hosted facilitator as default — affects decentralization story and latency
- [ ] Whether to expose scout_relay itself as an x402-gated API (meta: scout_relay charges agents per route call via x402)
- [ ] Wallet custody model for agents — scout_relay-managed vs. developer-provided
- [ ] MCP tool naming convention (`scout_relay_route` vs. `route` vs. staying within x402 namespace)
- [ ] Whether Phase 3 multi-rail is necessary for MVP or deferred until x402 coverage gaps are demonstrated empirically

---

## Name

**scout_relay** — replaces scout_spend.

"Spend" positions this as a consumer expenditure product. The router is developer infrastructure for agent commerce. "scout_relay" captures the core behavior: reconnaissance, pathfinding, executing on the best available route. It also preserves continuity with x402-discovery-mcp's existing brand presence in the x402 ecosystem.

---

*Built on [x402-discovery-mcp](https://github.com/rplryan/x402-discovery-mcp) · MIT License · Base + Solana*
