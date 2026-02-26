#!/usr/bin/env python3
"""
Demonstrates: Coinbase AgentKit agent using x402 Service Discovery to autonomously
find and pay for a crypto price data service, using its built-in Base wallet.

Pattern overview
----------------
1. AgentKit is configured with X402DiscoveryActionProvider — adds 4 actions.
2. The agent receives a task: find the cheapest crypto price service under $0.05.
3. Agent calls x402_discover → gets ranked list of matching services.
4. Agent calls x402_pay_and_call → probes the service, receives HTTP 402 challenge.
5. Action returns AgentKit payment hint → agent calls erc20_transfer to pay.
6. Agent retries with X-PAYMENT header → receives data.

The agent never needs a hardcoded API key. Its AgentKit wallet IS the credential.

Install:
    pip install "agentkit-x402-discovery[agentkit]"
    pip install coinbase-agentkit-langchain langchain-anthropic langchain-core

Env vars needed for real operation:
    CDP_API_KEY_NAME      — Coinbase Developer Platform key name
    CDP_API_KEY_PRIVATE   — CDP private key
    ANTHROPIC_API_KEY     — for the LLM (or swap for OpenAI)

This file also includes a standalone demo that runs without any API keys,
showing the discovery + payment flow against the live catalog.
"""

import json
import os
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"


# ---------------------------------------------------------------------------
# Full AgentKit + LangChain integration
# (requires: pip install coinbase-agentkit coinbase-agentkit-langchain
#             langchain-anthropic langchain-core agentkit-x402-discovery)
# ---------------------------------------------------------------------------

FULL_AGENTKIT_CODE = '''
import os
from coinbase_agentkit import AgentKit, AgentKitConfig, CdpWalletProvider, CdpWalletProviderConfig
from coinbase_agentkit_langchain import get_langchain_tools
from agentkit_x402_discovery import x402_discovery_action_provider

from langchain_anthropic import ChatAnthropic
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# --- 1. Wallet provider (funded Base wallet with USDC) ---
wallet_provider = CdpWalletProvider(CdpWalletProviderConfig(
    api_key_name=os.environ["CDP_API_KEY_NAME"],
    api_key_private=os.environ["CDP_API_KEY_PRIVATE"],
    network_id="base-mainnet",
))

# --- 2. AgentKit with x402 discovery wired in ---
#
# X402DiscoveryActionProvider adds 4 actions to the agent:
#   x402_discover      — find services by keyword/category
#   x402_browse        — list the full catalog
#   x402_health        — check live health of a service
#   x402_pay_and_call  — discover + probe + surface payment instructions
#
agent_kit = AgentKit(AgentKitConfig(
    wallet_provider=wallet_provider,
    action_providers=[
        x402_discovery_action_provider(),   # <-- x402 service discovery
        # add other providers here (e.g. WalletActionProvider, ERC20ActionProvider)
    ]
))

# --- 3. Expose AgentKit actions as LangChain tools ---
tools = get_langchain_tools(agent_kit)

# --- 4. LLM + system prompt ---
llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=os.environ["ANTHROPIC_API_KEY"],
)

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an autonomous agent with a funded Base/USDC wallet.

You have access to the x402 service discovery catalog. When you need external
data or compute, use these actions:

  x402_discover      — find the best services matching a query or capability
  x402_browse        — see all registered x402 services
  x402_health        — check uptime/latency for a specific service
  x402_pay_and_call  — discover a service and call it (handles 402 payment flow)

When x402_pay_and_call returns "payment_required":
  1. Read the agentkit_payment_hint field.
  2. Use erc20_transfer to send the specified USDC amount to the payment_recipient.
  3. After the transfer confirms, retry the service call with the X-PAYMENT header.

Your wallet already has USDC on Base. You can spend up to $1.00 total.
Always pick the cheapest service that meets quality requirements."""),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

# --- 5. Wire up the agent executor ---
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,        # shows each tool call
    max_iterations=10,   # safety limit
    return_intermediate_steps=True,
)

# --- 6. Run the task ---
result = executor.invoke({
    "input": (
        "Find me the cheapest crypto price data service under $0.05 "
        "and tell me about it — name, price, quality, and what it covers."
    )
})

print("\\n" + "="*60)
print("Agent answer:")
print(result["output"])
print("="*60)

# Show the tool calls the agent made
print("\\nTool calls:")
for step in result.get("intermediate_steps", []):
    action, observation = step
    print(f"  [{action.tool}] args={json.dumps(action.tool_input, indent=2)[:120]}...")
'''


# ---------------------------------------------------------------------------
# Standalone demo — runs without any API keys
# Shows exactly what x402_discover and x402_pay_and_call return
# ---------------------------------------------------------------------------

def demo_discover(query: str = "crypto prices", max_price: float = 0.05) -> None:
    """Simulate what x402_discover returns to an AgentKit agent."""
    print(f"[x402_discover] Searching: '{query}' (max ${max_price}/call)")

    try:
        resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        services = data.get("endpoints", data) if isinstance(data, dict) else data
    except requests.RequestException as e:
        print(f"  Discovery API unreachable: {e}")
        return

    # Client-side filter (mirrors provider._filter_services logic)
    quality_rank = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
    q = query.lower()
    results = [
        s for s in services
        if (s.get("price_usd") or 999) <= max_price
        and (
            q in s.get("name", "").lower()
            or q in s.get("description", "").lower()
            or any(q in t.lower() for t in s.get("tags", []))
            or any(q in t.lower() for t in s.get("capability_tags", []))
        )
    ]
    results.sort(key=lambda s: (
        quality_rank.get(s.get("health_status", "unverified"), 3),
        s.get("price_usd") or 999,
    ))

    if not results:
        print(f"  No services found for '{query}' under ${max_price}/call")
        print(f"  (Total in catalog: {len(services)} services)")
        # Show cheapest available instead
        by_price = sorted(
            [s for s in services if s.get("price_usd")],
            key=lambda s: s.get("price_usd", 999)
        )
        if by_price:
            cheapest = by_price[0]
            print(f"  Cheapest available: {cheapest.get('name')} at ${cheapest.get('price_usd')}/call")
        return

    top = results[:3]
    print(f"  Found {len(results)} match(es). Top results:")
    for i, s in enumerate(top, 1):
        print(f"  [{i}] {s.get('name')}")
        print(f"       Price:   ${s.get('price_usd')}/call")
        print(f"       Quality: {s.get('health_status', 'unverified')}")
        print(f"       URL:     {s.get('url', 'N/A')}")
        print(f"       Wallet:  {s.get('wallet_address', 'N/A')}")
        desc = s.get("description", "")
        if desc:
            print(f"       Desc:    {desc[:80]}{'...' if len(desc) > 80 else ''}")
        print()


def demo_pay_and_call_flow(query: str = "crypto prices", max_price: float = 0.05) -> None:
    """
    Simulate the x402_pay_and_call action flow.

    In a real AgentKit run:
      1. x402_pay_and_call probes the service → gets HTTP 402 challenge
      2. Returns payment_required with agentkit_payment_hint
      3. Agent calls erc20_transfer (its wallet action) to pay
      4. Agent retries the service call with X-PAYMENT header
    """
    print(f"[x402_pay_and_call] query='{query}', max_price=${max_price}")

    try:
        resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        services = data.get("endpoints", data) if isinstance(data, dict) else data
    except requests.RequestException as e:
        print(f"  Discovery API unreachable: {e}")
        return

    quality_rank = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
    q = query.lower()
    results = [
        s for s in services
        if (s.get("price_usd") or 999) <= max_price
        and (
            q in s.get("name", "").lower()
            or q in s.get("description", "").lower()
            or any(q in t.lower() for t in s.get("tags", []))
        )
    ]
    results.sort(key=lambda s: (
        quality_rank.get(s.get("health_status", "unverified"), 3),
        s.get("price_usd") or 999,
    ))

    if not results:
        print(json.dumps({
            "status": "no_service_found",
            "message": "No matching x402 service found within price limit."
        }, indent=2))
        return

    service = results[0]
    service_url = service.get("url")
    price_usd = service.get("price_usd", 0.005)
    wallet_address = service.get("wallet_address")

    print(f"  Selected: {service.get('name')} (${price_usd}/call)")

    if not service_url:
        print(json.dumps({"status": "error", "message": "Service has no endpoint URL"}))
        return

    # Probe the service without payment
    print(f"  Probing: POST {service_url}")
    try:
        probe = requests.post(service_url, json={}, timeout=10)
        print(f"  HTTP {probe.status_code}")

        if probe.status_code == 402:
            # x402 payment required — this is the expected happy path
            try:
                challenge = probe.json()
            except Exception:
                challenge = {"raw": probe.text[:200]}

            result = {
                "status": "payment_required",
                "service": service.get("name"),
                "service_id": service.get("id"),
                "service_url": service_url,
                "price_usd": price_usd,
                "payment_recipient": wallet_address,
                "network": service.get("network", "base"),
                "x402_challenge": challenge,
                "instruction": (
                    f"Service requires x402 payment of ${price_usd} USDC on Base. "
                    f"Send USDC to {wallet_address} using your AgentKit wallet, "
                    "then retry the call with X-PAYMENT header."
                ),
                "agentkit_payment_hint": (
                    "Use the AgentKit erc20_transfer action: "
                    f"send {price_usd} USDC to {wallet_address} on base-mainnet, "
                    "then retry the POST with X-PAYMENT header containing the receipt."
                ),
            }
            print(json.dumps(result, indent=2))

            # Show what the AgentKit agent does next
            print()
            print("  >> Agent next step (autonomous payment loop):")
            print(f"     erc20_transfer(token=USDC, to={wallet_address}, amount={price_usd})")
            print(f"     POST {service_url} + X-PAYMENT: <receipt>")

        elif probe.status_code == 200:
            content_type = probe.headers.get("content-type", "")
            response_body = (
                probe.json()
                if content_type.startswith("application/json")
                else probe.text[:300]
            )
            print(json.dumps({
                "status": "success",
                "service": service.get("name"),
                "response": response_body,
            }, indent=2))

        else:
            print(json.dumps({
                "status": "service_error",
                "http_status": probe.status_code,
                "message": probe.text[:200],
            }, indent=2))

    except requests.RequestException as e:
        # Service unreachable — still useful: we have the service details
        print(json.dumps({
            "status": "call_failed",
            "service": service.get("name"),
            "service_url": service_url,
            "error": str(e),
            "service_info": {
                "id": service.get("id"),
                "price_usd": price_usd,
                "wallet_address": wallet_address,
            },
        }, indent=2))


def demo_browse() -> None:
    """Simulate x402_browse — show the full catalog summary."""
    print("[x402_browse] Fetching full catalog...")
    try:
        resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        services = data.get("endpoints", data) if isinstance(data, dict) else data
        print(f"  Total services: {len(services)}")
        by_category: dict = {}
        for s in services:
            cat = s.get("category", "unknown")
            by_category.setdefault(cat, []).append(s.get("name", "?"))
        for cat, names in sorted(by_category.items()):
            print(f"  {cat}: {', '.join(names[:3])}{'...' if len(names) > 3 else ''}")
    except requests.RequestException as e:
        print(f"  Error: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Coinbase AgentKit + x402 Service Discovery — Example 15")
    print("=" * 60)
    print()

    # --- Demo 1: Browse the catalog ---
    demo_browse()
    print()

    # --- Demo 2: Discover crypto price services ---
    demo_discover(query="crypto prices", max_price=0.05)

    # --- Demo 3: Simulate x402_pay_and_call flow ---
    print("-" * 60)
    demo_pay_and_call_flow(query="crypto prices", max_price=0.05)
    print()

    # --- Show the full LangChain integration code ---
    print("=" * 60)
    print("Full AgentKit + LangChain integration code:")
    print("(requires: pip install agentkit-x402-discovery coinbase-agentkit-langchain langchain-anthropic)")
    print()
    print(FULL_AGENTKIT_CODE)
