# agentkit-x402-discovery

Coinbase AgentKit ActionProvider for **x402 Service Discovery** — gives your AgentKit agent the ability to find, evaluate, and pay for any x402-payable API at runtime, using the wallet it already has.

## Installation

```bash
pip install agentkit-x402-discovery
# with AgentKit
pip install "agentkit-x402-discovery[agentkit]"
```

## Why AgentKit + x402 is a natural fit

AgentKit agents already have a **funded Base wallet with USDC**. The x402 protocol turns any HTTP endpoint into a pay-per-use API secured by that same wallet.

Without this package, an agent that needs, say, crypto price data must have an API key pre-configured. With `agentkit-x402-discovery`, the agent:

1. Calls `x402_discover` to find the best available crypto-price service in the live catalog
2. Learns the service URL, price ($0.001–$0.10/call), and the recipient wallet address
3. Uses its **existing AgentKit USDC balance** to pay and retrieve the data

No API keys. No pre-registration. The agent's wallet is the credential.

## Quick Start

```python
import os
from coinbase_agentkit import AgentKit, AgentKitConfig
from coinbase_agentkit_langchain import get_langchain_tools
from agentkit_x402_discovery import x402_discovery_action_provider

from langchain_anthropic import ChatAnthropic
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# 1. Build AgentKit with x402 discovery wired in
agent_kit = AgentKit(AgentKitConfig(
    wallet_provider=your_wallet_provider,          # funded Base wallet
    action_providers=[
        x402_discovery_action_provider(),          # <-- adds the 4 x402 actions
        # ...your other providers
    ]
))

# 2. Expose as LangChain tools
tools = get_langchain_tools(agent_kit)

# 3. Build the agent
llm = ChatAnthropic(model="claude-sonnet-4-6")
prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are an autonomous agent with a funded Base wallet. "
        "Use x402_discover to find paid API services, x402_pay_and_call to execute them, "
        "and x402_browse to explore the full catalog."
    )),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# 4. Run — the agent autonomously discovers and pays for x402 services
result = executor.invoke({
    "input": "Find the cheapest crypto price data service under $0.05 and tell me about it"
})
print(result["output"])
```

## Actions

All 4 actions are automatically registered with AgentKit and surfaced to your LLM.

### `x402_discover`

Find x402-payable services by capability or keyword. Returns a ranked list (up to 5) with pricing, quality tier, endpoint URL, and wallet address.

```python
# The LLM will call this automatically, but you can also invoke directly:
result = agent_kit.run_action("x402_discover", {
    "query": "crypto prices",
    "max_price_usd": 0.05,
    "min_quality": "silver",
})
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | `None` | Free-text search: `"weather data"`, `"crypto prices"` |
| `capability` | `str` | `None` | Category: `research\|data\|compute\|agent\|utility\|monitoring` |
| `max_price_usd` | `float` | `0.50` | Maximum price per call in USD |
| `min_quality` | `str` | `None` | Minimum quality tier: `gold\|silver\|bronze\|unverified` |

### `x402_browse`

List the entire x402 service catalog. Free — no payment or parameters required. Good for letting the agent survey the landscape before committing to a service.

### `x402_health`

Check live health for a specific service by ID. Returns uptime %, average latency (ms), and current status. Free.

| Parameter | Type | Description |
|---|---|---|
| `service_id` | `str` | Service ID from the catalog, e.g. `"x402engine-crypto-prices"` |

### `x402_pay_and_call`

The full autonomous loop in one action: discover the best matching service, attempt the API call, and surface the x402 payment challenge with precise AgentKit payment instructions.

When the service returns HTTP 402, this action returns the `x402_challenge` plus an `agentkit_payment_hint` telling the agent exactly which AgentKit action to use next (`erc20_transfer`) and what parameters to pass. The agent then pays and retries — completely hands-free.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | `None` | What kind of service to find |
| `capability` | `str` | `None` | Category filter |
| `max_price_usd` | `float` | `0.10` | Max price per call |
| `call_payload` | `dict` | `None` | Request body to forward to the service |

## How x402 Payments Work

```
Agent calls x402_pay_and_call("crypto prices")
    │
    ▼
Discovery API → best matching service (e.g. $0.003/call on Base)
    │
    ▼
POST service_url  →  HTTP 402 + x402 challenge
    │                 { "accepts": [{ "network": "base", "asset": "USDC",
    │                                 "amount": "3000", "payTo": "0x..." }] }
    │
    ▼
AgentKit erc20_transfer: 0.003 USDC → service wallet on Base
    │
    ▼
POST service_url + X-PAYMENT header  →  HTTP 200 + data
```

## Advanced: Custom Catalog URL

Point at a private catalog for internal services:

```python
from agentkit_x402_discovery import x402_discovery_action_provider

provider = x402_discovery_action_provider(
    base_url="https://my-internal-catalog.example.com"
)
```

## Works Without AgentKit Installed

The package loads cleanly even if `coinbase-agentkit` is not installed, using stub base classes. This lets you import and unit-test the provider logic in isolation.

```python
# Works even without coinbase-agentkit
from agentkit_x402_discovery import X402DiscoveryActionProvider
provider = X402DiscoveryActionProvider()
result = provider._get_catalog()   # direct catalog fetch
```

## Links

- [x402 Discovery API](https://x402-discovery-api.onrender.com)
- [Live catalog](https://x402-discovery-api.onrender.com/catalog)
- [API docs](https://x402-discovery-api.onrender.com/docs)
- [GitHub](https://github.com/rplryan/ouroboros)
- [Coinbase AgentKit](https://github.com/coinbase/agentkit)
- [x402 Protocol](https://github.com/coinbase/x402)

## License

MIT
