# x402Scout — Project Outline
> **Version:** 1.4 | **Status:** Pre-Build / Design Phase | **Date:** 2026-03-03
> **Author:** Ryan (Ohio Valley / rplryan) | **For:** Agent & Developer Reference

---

## 1. Project Identity

| Field | Value |
|---|---|
| **Suite Brand** | x402Scout |
| **Product Name** | Scout Spend |
| **Repo Name** | x402-spend-mcp |
| **Tagline** | The spending layer for the onchain economy |
| **Teaser Line** | Scout Spend is coming. built on x402. |
| **Chain** | Base (L2, Coinbase) |
| **Settlement Asset** | USDC (native Base) |
| **Protocol Type** | Onchain Payment Orchestration Protocol (PayFi) |
| **Revenue Model** | Transaction fees only — no subscriptions |
| **Regulatory Surface** | Minimal — protocol routes, never holds funds |
| **Repo Owner** | rplryan (GitHub) |

---

## 2. Suite Context

Scout Spend is the second product in the x402Scout suite, extending the existing x402-discovery-mcp infrastructure into real-world spending.

### 2.1 The x402Scout Suite

```
x402Scout  (suite brand / interface layer)
    │
    ├── x402-discovery-mcp   LIVE   find + pay for x402-gated APIs
    │                               agents discover services at runtime
    │                               tools: x402_discover, x402_browse,
    │                                      x402_health, x402_register, x402_trust
    │
    └── x402-spend-mcp       COMING  route USDC to real-world spending rails
                                     humans + AI agents spend anywhere Visa accepted
                                     tools: scout_card, scout_pay, scout_agent, scout_vault
```

### 2.2 How They Work Together

| Repo | Function | Completes the Stack |
|---|---|---|
| `x402-discovery-mcp` | Agents find and pay for x402-gated APIs | Onchain economy |
| `x402-spend-mcp` | Humans and agents spend USDC in the real world | Real-world economy |

x402-discovery-mcp handles what is onchain. x402-spend-mcp handles the real world. Together they form the complete agent commerce stack — find it, pay for it, spend it anywhere.

### 2.3 Naming Convention

All suite products follow the pattern: `x402-[function]-mcp`

| Repo | Function Word | What It Does |
|---|---|---|
| x402-discovery-mcp | discovery | Finds x402-gated services |
| x402-spend-mcp | spend | Routes USDC to spending rails |

---

## 3. Project Classification

Scout Spend is an **Onchain Payment Orchestration Protocol** — specifically categorized within the emerging Web3 taxonomy as a **PayFi Protocol**.

### 3.1 What It Is Not

Scout Spend is not a wallet, exchange, DEX, bridge, or lending protocol. None of those categories capture what it does. It does not store funds, manage keys, swap assets, or provide credit.

### 3.2 Canonical Classification by Audience

| Audience | Description |
|---|---|
| Crypto-native developer | A Base-native PayFi protocol and payment router |
| Builder / partner | An onchain spending primitive and SDK |
| Non-crypto audience | Infrastructure that lets any crypto wallet spend at real-world merchants |
| Whitepaper / formal | A non-custodial onchain payment orchestration protocol |
| Ecosystem / DappRadar | PayFi Protocol — spending rail aggregator on Base |

### 3.3 Category Definitions

**PayFi Protocol** — The most current and accurate term. PayFi (Payment Finance) is the emerging category for protocols that bridge onchain assets with real-world payment execution. It describes DeFi-native infrastructure that produces real-world spending outcomes without requiring users to exit the crypto ecosystem.

**Payment Router** — The functional description. Analogous to how 1inch is a DEX aggregator (routes between swap venues), Scout Spend is a spend aggregator (routes between spending rails).

**Spending Primitive** — How Base ecosystem builders classify it. A composable building block that other protocols snap onto. This framing drives SDK adoption and developer integrations.

**Onchain Payment Middleware** — The enterprise framing. Infrastructure sitting between wallets and payment networks.

### 3.4 Comparable Protocol Analogies

| Protocol | Category | Scout Spend Equivalent |
|---|---|---|
| 1inch | DEX aggregator (routes swaps) | Scout Spend routes spend rails |
| Uniswap | Swap protocol (fee on volume) | Scout Spend charges fee on spend volume |
| Aave | Lending primitive (composable) | Scout Spend is a spending primitive (composable) |
| Stripe | Payment infrastructure (developer API) | Scout Spend is onchain payment infrastructure |

---

## 4. Problem Statement

Most real-world crypto spending still requires routing through traditional banking infrastructure:

```
Crypto → Custodial Exchange → Bank Account → Card Network
```

This introduces:
- Custodial risk (user loses key ownership)
- Regulatory friction and KYC barriers
- Settlement delays (1–7 business days)
- Geographic limitations
- Banking dependency

**Core gap:** No single protocol exists that routes USDC from any wallet to real-world spending rails — for both humans and AI agents — with no account creation, no KYC, and no bank intermediary.

---

## 5. Solution Architecture

### 5.1 Core Design Principles

1. **Wallet-first, not account-first** — No registration, no email, no password. Wallet IS the account.
2. **Rail-agnostic routing** — Protocol selects optimal spending rail invisibly (card / bill pay / voucher / x402 direct).
3. **Agent-native from day one** — Humans and AI agents share identical routing infrastructure.
4. **Protocol, not product** — Smart contract layer with no fiat custody, no identity collection.

### 5.2 The Scout Router Contract

The single core primitive. Every product is an interface on top of this contract.

```
User Wallet (any Base-compatible wallet)
        │
        ▼
Scout Router Contract (Base)
        │
        ├── Atomic fee deduction (0.50–0.75% on tx value)
        ├── Backend priority queue query
        ├── Route to optimal destination
        ├── Onchain receipt emission
        └── Fee to Scout treasury
```

**Key property:** Funds pass through atomically in a single transaction.
Scout Spend never holds user funds. Never touches fiat. Never collects identity.

### 5.3 Backend Priority Queue (Redundancy Hedge)

```
Priority 1 (Primary):    Laso Finance
Priority 2 (Secondary):  Immersve
Priority 3 (Tertiary):   Rain / BingCard
Priority 4 (Fallback):   Bitrefill voucher rail
```

If any backend goes down, changes terms, or faces regulatory action,
the router silently promotes the next backend. Users never notice. Revenue continues.

### 5.4 Capacity Architecture (The Stacking Moat)

The multi-backend queue is not just a resilience feature — it is a **capacity architecture**. Each backend carries its own independent monthly spend limit under its own regulatory carveout. The Scout Router aggregates them.

**Two provisioning modes:**

**Sequential (default):** Router exhausts primary backend limit, then promotes to next.
```
Days 1–20:   Laso capacity exhausted → router promotes Immersve
Days 20–25:  Immersve capacity exhausted → router promotes Rain
Days 25–30:  Rain handles remainder
User sees:   uninterrupted spending across entire month
```

**Parallel (high-volume):** Router provisions cards across all backends simultaneously at deposit time and load-balances across them. Total capacity is additive from day one, not sequential.

**Estimated monthly spending ceiling by configuration:**

| User Type | Configuration | Monthly Ceiling |
|---|---|---|
| Individual, no-KYC | 1 wallet, 3 backends sequential | $15,000–$30,000 |
| Individual, light voluntary KYC | 1 wallet, 3 backends tiered | $50,000–$100,000 |
| Agent (single policy wallet) | 1 agent wallet, 3 backends parallel | $15,000–$30,000 |
| Agent (multi-wallet deployment) | 10 agent wallets × 3 backends | $150,000–$300,000 |
| DAO / institutional | N wallets, full backend stack | Uncapped at protocol level |

**Estimated backend limit ranges:**

| Backend | Monthly Limit (no-KYC tier) | Notes |
|---|---|---|
| Laso Finance | $5,000–$10,000 | FinCEN prepaid carveout |
| Immersve | $5,000–$10,000 | Mastercard principal member, tiered |
| Rain / BingCard | $5,000–$10,000 | Similar prepaid regulatory structure |
| Bitrefill | Effectively unlimited | Voucher/gift card rail, no card network ceiling |

**Sequential floor for a single no-KYC wallet: $15,000–$30,000/month** — already 3–6x the effective limit of any single-backend competitor at the same KYC tier.

**Why single-backend competitors cannot replicate this:** MetaMask Card (Immersve-only) or Bitget (Immersve-only) hits its backend ceiling and stops. The user has no recourse. Scout routes to the next backend transparently. Closing that gap requires competitors to become multi-backend routing protocols — which is what Scout Spend is. They cannot add this capability without rebuilding their architecture from scratch.

The ceiling is not a card limit. The ceiling is: `(number of wallets) × (sum of backend limits)`. For institutional and agent-heavy deployments that is effectively uncapped at the protocol layer.

---

## 6. Product Suite (x402-spend-mcp Tools)

### 6.1 scout_card — Scout Card

**Function:** One-click Visa prepaid card issuance from any Base wallet.

**User flow:**
```
Connect wallet → Enter amount → Sign one tx → Card in Apple/Google Pay
(~30 seconds, no forms, no ID)
```

- **Fee:** 0.75% deducted atomically from USDC before reaching card backend
- **Backend:** Laso Finance (primary) — non-reloadable prepaid Visa, re-issued on depletion
- **Wallets:** MetaMask, Coinbase Wallet, Rainbow, WalletConnect (~95% of Base users)
- **Card compatibility:** Apple Pay, Google Pay, Samsung Pay, online merchants, in-store Visa

---

### 6.2 scout_pay — Scout Pay

**Function:** USDC bill payment for any biller that accepts Visa — no bank account, no ACH, no fiat conversion required.

**Supported payments:** Utilities, insurance, subscriptions, online rent portals, software services — anything with an online Visa-accepting payment page.

**What it is not:** ACH/wire transfers, routing-number-based payments, or landlords accepting bank transfer only. Those require fiat rails. Scout Pay does not touch fiat.

**User flow:**
```
Connect wallet → Enter biller details (saved onchain, portable) →
Scout issues ephemeral Visa charge → Payment posts → Receipt onchain
```

- **Fee:** 0.50% on transaction value, capped at $10/tx
- **Backend:** Same Laso prepaid Visa card infrastructure as scout_card — no new rail, no new integration
- **Key feature:** Biller profiles saved as encrypted onchain preferences. Portable across any Scout-integrated app. Follows wallet, not platform.

---

### 6.3 scout_agent — Scout Agent

**Function:** Extends x402-discovery-mcp by adding real-world spending destinations to the existing x402 routing table. Agents that already use x402-discovery-mcp can spend in the real world without any additional wallet setup.

**Agent capabilities:**
- Pay x402-gated APIs directly (existing x402-discovery-mcp capability)
- Issue ephemeral Scout Cards for one-time real-world purchases
- Execute recurring bill payments via Visa rail within policy limits
- Route to gift card/voucher rail for merchant-specific spend
- Return onchain receipts to owner wallet

**Spending policy contract (set once by wallet owner):**

```solidity
contract AgentSpendingPolicy {
    address public owner;
    uint256 public perTxLimit;
    uint256 public dailyLimit;
    uint256 public monthlyLimit;
    SpendCategory[] public allowedCategories;
    address[] public approvedRouters;
    uint8 public multiSigThreshold; // for large txs
}
```

- **Fee:** 0.50–0.75% on all agent-executed transactions (same as human fee)

---

### 6.4 scout_vault — Scout Vault

**Function:** Idle USDC earns yield automatically between deposit and card settlement.

- **Mechanism:** USDC routes through Aave/Morpho/Compound on Base; yield accrues until moment of spend
- **Split:** 85% to user / 15% to Scout protocol treasury
- **UX:** Transparent — "Scout Balance" appreciates slightly over time; retention mechanism

---

## 7. Fee Architecture

All revenue is transaction-based. Zero subscriptions. Zero invoices. Zero billing cycles.

| Action | Fee | Payer | Execution |
|---|---|---|---|
| scout_card (card issuance) | 0.75% of USDC deposited | User | Atomic, same tx |
| scout_pay (bill routing) | 0.50% of tx value | User | Atomic, same tx |
| x402 API payment (via discovery-mcp) | $0.005–0.010/query | Agent / User | Existing infrastructure |
| scout_agent (card issuance) | 0.75% (same as user) | Agent | Atomic, same tx |
| scout_vault (yield share) | 15% of yield earned | Protocol earns | Automatic |
| SDK volume routing | 0.25% (split with builder) | End user | Atomic, same tx |

**Blended effective fee:** ~0.65% across all routing types.

---

## 8. Regulatory Architecture

### 8.1 Two-Layer Compliance Design

```
Layer 1 — Scout Spend Protocol (zero regulatory surface)
    Holds no funds. Issues no cards. Transmits no fiat.
    Pure routing software. Not a money transmitter.

Layer 2 — Card Issuance Backends (Laso, Immersve, Rain)
    Hold their own MSB / card issuer regulatory burden.
    Scout has commercial agreements with minimum 3 providers.
    scout_pay uses the same Visa card rail as scout_card —
    no separate fiat bridge, no ACH, no additional compliance layer.
```

### 8.2 Regulatory Posture

- Scout Spend never holds user funds (atomic routing — in and out in one tx)
- Scout Spend never converts crypto to fiat (backends do that)
- Scout Spend never knows user identity (backends handle their own KYC if required)
- Scout Spend is a smart contract — analogous to Uniswap's legal posture
- Contract designed with upgradeability via multisig

### 8.3 KYC Reality

"No-KYC to the user" is real but sustainable because:
- Laso operates under prepaid card regulatory carveout (lighter requirements than debit/credit)
- Laso is FinCEN-registered MSB, absorbing compliance burden at issuer level
- Scout Spend abstracts compliance away from user — does not eliminate it

---

## 9. Competitive Landscape

### 9.1 Direct Comparison

| Feature | x402-spend-mcp | MetaMask Card | Bitget/Immersve | Laso Finance | x402 Protocol |
|---|---|---|---|---|---|
| No KYC to user | YES | NO | NO | YES | N/A |
| Any wallet | YES | NO (MetaMask only) | NO (Bitget only) | YES | YES |
| One-click, no account | YES | NO | NO | YES | N/A |
| Protocol (not product) | YES | NO | NO | NO | YES |
| Agent / AI payments | YES | NO | NO | NO | YES |
| Multi-backend routing | YES | NO | NO | NO | NO |
| Base-native USDC | YES | YES | YES | YES | YES |
| Developer SDK | YES | NO | Partial | NO | YES |
| Bill pay (Visa rail) | YES | NO | NO | NO | NO |
| Yield on idle funds | YES | NO | NO | NO | NO |
| Transaction fee only | YES | NO | NO | NO | YES |
| Suite integration | YES (x402Scout) | NO | NO | NO | NO |

### 9.2 Key Competitive Gaps (Unoccupied Today)

1. Unified spending router on Base routing to card + bill pay + x402 APIs in single atomic tx — **does not exist**
2. Wallet-connect to real-world card in one click with no account at protocol layer — **does not exist**
3. Agent spending policy contracts as production-quality standalone primitive — **does not exist**
4. Protocol unifying human spending + agent spending under same fee-generating routing contract — **entirely unbuilt**
5. Spend router natively integrated with an x402 discovery layer — **does not exist**

### 9.3 Primary Threats

| Threat | Risk Level | Mitigation |
|---|---|---|
| x402 V2 scope expansion | High (slow) | Build speed + own consumer UX Coinbase won't prioritize |
| MetaMask Card growth | Medium | KYC-gated and wallet-locked — different category |
| Stripe stablecoin infra | Medium | Developer primitive, not consumer product |
| Laso backend failure | Medium | Multi-backend priority queue |
| Regulatory tightening | Medium | Backend-agnostic design; KYC at issuer not protocol |

---

## 10. Go-To-Market Sequence

| Phase | Tool | Timeline | Target |
|---|---|---|---|
| 1 | scout_card (Laso backend) | Months 1–3 | Crypto-native Base USDC holders |
| 2 | scout_agent (x402-discovery-mcp extension) | Months 2–4 | x402 developer ecosystem |
| 3 | Scout SDK (open infrastructure) | Months 4–6 | Base builders, DAO tooling, MCP devs |
| 4 | scout_pay (Visa-rail bill pay) | Months 5–8 | Users with recurring Visa-payable expenses |
| 5 | scout_vault (yield layer) | Months 6–9 | All users with idle Scout balances |

---

## 11. Revenue Projections (Transaction Fees Only)

### 11.1 Volume-Based Model

| Scenario | Monthly Volume | Fee (0.65%) | Monthly Revenue |
|---|---|---|---|
| Early (month 3) | $500K | 0.65% | $3,250 |
| Growing (month 6) | $3M | 0.65% | $19,500 |
| Established (month 12) | $15M | 0.65% | $97,500 |
| Scale (month 24) | $75M | 0.65% | $487,500 |

### 11.2 Vault Yield (Additive at Scale)

At $75M monthly volume, 4-hour average float, 5% APY:
~$50,000–100,000/month additional passive revenue at maturity.

### 11.3 By Product at Maturity (Year 2)

| Product | Monthly Estimate |
|---|---|
| scout_card | $80,000–150,000 |
| scout_pay | $20,000–40,000 |
| scout_agent | $30,000–60,000 |
| Scout SDK | $25,000–50,000 |
| scout_vault | $30,000–60,000 |
| **Total** | **$185,000–360,000/month** |

---

## 12. Technical Stack

| Component | Technology |
|---|---|
| Chain | Base (Coinbase L2) |
| Settlement asset | USDC (native Base) |
| Smart contract language | Solidity |
| Contract upgradeability | Multisig proxy pattern |
| Agent payment layer | x402-discovery-mcp (existing suite product) |
| Card backend (primary) | Laso Finance |
| Card backend (secondary) | Immersve |
| Card backend (tertiary) | Rain |
| Bill pay backend | Laso Visa rail (same as scout_card — no separate integration) |
| Yield layer | Aave / Morpho on Base |
| Authorization standard | EIP-3009 (transferWithAuthorization) |
| Wallet compatibility | WalletConnect v2 (MetaMask, Coinbase Wallet, Rainbow, +400 wallets) |
| Agent framework | MCP (Model Context Protocol) |
| Trust standard | ERC-8004 (from x402-discovery-mcp) |

---

## 13. Key Dependencies & Risks

| Dependency | Risk | Mitigation |
|---|---|---|
| Laso Finance | Regulatory or operational failure | 3-backend queue; swap without UX change |
| x402 protocol (Coinbase) | Scope expansion overlaps Scout Spend | Speed + own consumer UX layer |
| Base chain | Sequencer downtime, fee spikes | Coinbase-operated; lowest risk L2 |
| Regulatory environment | No-KYC prepaid card tightening | Backend-agnostic; KYC at issuer not protocol |
| x402-discovery-mcp traction | Agent layer adoption risk | Already organic; Scout Spend extends existing momentum |

---

## 14. Security & Audit Strategy

Smart contract auditing is not optional for any protocol handling real user USDC on Base. The audit strategy below is sequenced to maximize coverage while minimizing cost — build on audited primitives first, self-audit second, crowdsourced audit third.

### 14.1 Build on Battle-Tested Primitives

The Scout Router Contract's novel code surface should be as small as possible. Use audited libraries for every standard operation:

| Library | Usage in Scout Router | Audit Status |
|---|---|---|
| OpenZeppelin `SafeERC20` | USDC transfer handling | Continuously audited, billions TVL secured |
| OpenZeppelin `ReentrancyGuard` | Eliminates reentrancy in one line | Continuously audited |
| OpenZeppelin `AccessControl` | Backend registry permissioning | Continuously audited |
| OpenZeppelin `Pausable` | Emergency stop if backend misbehaves | Continuously audited |
| Solmate `SafeTransferLib` | Gas-optimized alternative to OZ for transfers | Widely audited, Base-native devs prefer it |

**Target:** Scout Router's novel Solidity — the routing logic, priority queue, fee deduction, and backend registry — should be 100–200 lines maximum. That is what gets audited. Not the whole contract.

Reference: [OpenZeppelin Contracts Wizard](https://wizard.openzeppelin.com) generates audited boilerplate for the exact use case. Uniswap V3's `SwapRouter.sol` is the closest architectural analog — read it before writing a line.

### 14.2 Self-Audit Tools (Free, Run During Development)

| Tool | Source | What It Catches |
|---|---|---|
| **Slither** | Trail of Bits (open source) | Static analysis — reentrancy, access control, integer issues, uninitialized storage. Run first. |
| **Echidna** | Trail of Bits (open source) | Property-based fuzzing — thousands of random inputs against invariants. Catches what static analysis misses. |
| **Medusa** | Trail of Bits (open source) | Faster fuzzer, newer, good complement to Echidna |
| **Foundry invariant tests** | Standard toolchain | Unit + integration tests, invariant testing — should exist regardless of audit |
| **Certik Skynet** | Certik (free tier) | Automated scan on deployed testnet contract. Shallow but useful for optics. |

These tools are used by Trail of Bits and Spearbit internally as a first pass before paid engagements. Running them yourself before paying for an audit resolves all low-hanging-fruit findings — which reduces paid audit cost and scope.

**Resource:** [Solodit.xyz](https://solodit.xyz) — searchable database of thousands of public audit reports. Search "payment router" and read every finding. Learn the attack vectors before writing code.

### 14.3 Crowdsourced Audit (Pre-Launch Requirement)

| Platform | Model | Cost | Quality |
|---|---|---|---|
| **Code4rena** | Open competition, prize pool | $15,000–$40,000 | Rivals Spearbit at 30–50% cost |
| **Sherlock** | Curated auditors + coverage | $15,000–$40,000 | Adds insurance component |

A well-incentivized Code4rena contest on 150–200 lines of novel routing logic is the correct audit vehicle for v1 — not a $150K Trail of Bits engagement. Dozens of independent researchers attack the code simultaneously for a defined window (1–2 weeks). Finding quality is high when the prize pool is meaningful.

### 14.4 Audit Timeline

| Step | Tool / Platform | Cost | When |
|---|---|---|---|
| Self-audit pass | Slither + Echidna + Medusa | Free | During development |
| Invariant test suite | Foundry | Free | During development |
| Testnet scan | Certik Skynet | Free | Pre-audit |
| Crowdsourced audit | Code4rena or Sherlock | $15,000–$40,000 | 6 weeks before mainnet launch |
| Professional audit (v2) | Spearbit | $50,000–$150,000 | After revenue funds it |

**The Code4rena contest is a hard launch blocker — it is in the timeline, not optional.**

---

## 15. Open Questions for Development

- [ ] Laso Finance commercial API agreement (programmatic card issuance endpoint)
- [ ] Immersve commercial agreement for backup backend
- [ ] Multisig structure for Scout treasury and contract upgrades
- [ ] Frontend framework decision (React / Next.js on Base)
- [ ] Token vs. no-token decision for protocol governance
- [ ] x402Scout / Scout Spend domain acquisition
- [ ] GitHub org vs. personal repo decision for suite

---

## 16. Glossary

| Term | Definition |
|---|---|
| **x402Scout** | The suite brand. Parent identity for all x402Scout products. |
| **Scout Spend** | Consumer-facing product name for x402-spend-mcp. |
| **x402-spend-mcp** | GitHub repo name. MCP server that routes USDC to real-world spending rails. |
| **x402-discovery-mcp** | Existing live suite product. MCP server for finding and paying for x402-gated APIs. |
| **x402** | HTTP 402-based payment protocol by Coinbase. Enables micropayments embedded in web requests. |
| **PayFi** | Payment Finance. Emerging Web3 category for protocols bridging onchain assets with real-world payment execution. |
| **Scout Router** | Core Base smart contract. Receives USDC, deducts fee atomically, routes to optimal spending backend. |
| **Laso Finance** | FinCEN-registered MSB and primary card backend. Issues no-KYC Visa prepaid cards against USDC deposits. |
| **Immersve** | Mastercard principal member and licensed card issuer. Secondary backend for scout_card. |
| **EIP-3009** | Ethereum standard enabling gasless, pre-authorized USDC transfers. Critical for agent-executed payments. |
| **Spending policy contract** | Agent-specific contract defining per-tx limits, daily caps, merchant categories, and multi-sig thresholds. |
| **scout_vault** | Yield layer tool. Idle USDC earns Aave/Morpho yield between deposit and spend. 85/15 user/protocol split. |
| **Rail** | A spending pathway — card issuance (Visa), voucher/gift card, or direct x402 API payment. scout_pay uses the same Visa card rail as scout_card. |
| **Atomic routing** | Single blockchain tx simultaneously deducting fee AND routing to backend. Funds never sit in Scout Spend. |
| **MCP** | Model Context Protocol. Standard for connecting AI agents to external tools and APIs. |
| **MSB** | Money Services Business. US Treasury (FinCEN) registration required for money transmission. |
| **ERC-8004** | Decentralized AI agent trust standard. Used in x402-discovery-mcp for service reputation scoring. |
| **EIP-4626** | Tokenized vault standard. Used for scout_vault yield positions. |
| **Payment Router** | Functional classification. Routes between spending rails the way a DEX aggregator routes between swap venues. |
| **Spending Primitive** | Composable building block classification. Other protocols integrate Scout Spend as a spend execution layer. |

---

*This document is intended for agent and developer consumption.*
*It represents the current design-phase outline of x402-spend-mcp (Scout Spend), part of the x402Scout suite.*
*Last updated: 2026-03-03 — v1.4 added §5.4 Capacity Architecture (multi-backend stacking moat, ceiling estimates by user type)*
