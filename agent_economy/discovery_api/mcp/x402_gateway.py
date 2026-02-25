#!/usr/bin/env python3
"""x402 MCP Payment Gateway — Track C: Category Creation.

An MCP server where EACH TOOL CALL requires an x402 micropayment before executing.
This is the convergence point: x402 (micropayments) + MCP (tool calls) =
programmable tool economy where agents pay for capabilities automatically.

Architecture:
  MCP Client (Claude/Cursor/any agent)
      ↓  tool call
  x402_gateway (this server)
      ↓  issues payment challenge (HTTP 402 equivalent in MCP response)
  MCP Client handles payment (USDC on Base)
      ↓  tool call with payment proof
  x402_gateway verifies payment with x402.org/facilitator
      ↓  verified
  Tool executes, result returned

Running:
    python x402_gateway.py

Environment variables (optional):
    WALLET_ADDRESS    — USDC recipient (default: CDP wallet)
    GATEWAY_PORT      — port (default: 8080)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WALLET_ADDRESS: str = os.getenv(
    "WALLET_ADDRESS", "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA"
)
USDC_CONTRACT: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
NETWORK: str = "eip155:8453"  # Base (CAIP-2)
FACILITATOR_URL: str = "https://x402.org/facilitator/verify"
DISCOVERY_API_URL: str = "https://x402-discovery-api.onrender.com"

log = logging.getLogger("x402-gateway")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Payment state (in-memory, production would use Redis/DB)
# ---------------------------------------------------------------------------

# payment_id -> {tool_name, args, expires_at, price_usdc_units}
_pending_payments: Dict[str, Dict] = {}

# tool_name -> total calls routed through this gateway
_tool_call_counts: Dict[str, int] = {}

# ---------------------------------------------------------------------------
# Tool pricing table
# ---------------------------------------------------------------------------

@dataclass
class ToolPricing:
    """Pricing config for a gated tool."""
    name: str
    description: str
    price_usdc_units: int  # in USDC micro-units (1 USDC = 1_000_000 units)
    handler: Callable[..., str]
    tags: List[str] = field(default_factory=list)

    @property
    def price_usd(self) -> float:
        return self.price_usdc_units / 1_000_000


# Registry of gated tools: name -> ToolPricing
_GATED_TOOLS: Dict[str, ToolPricing] = {}


def register_gated_tool(
    name: str,
    description: str,
    price_usdc_units: int,
    handler: Callable[..., str],
    tags: List[str] | None = None,
) -> None:
    """Register a tool that requires x402 payment to call."""
    _GATED_TOOLS[name] = ToolPricing(
        name=name,
        description=description,
        price_usdc_units=price_usdc_units,
        handler=handler,
        tags=tags or [],
    )

# ---------------------------------------------------------------------------
# Payment verification
# ---------------------------------------------------------------------------

async def verify_x402_payment(
    payment_header: str,
    tool_name: str,
    amount_units: str,
) -> tuple[bool, str]:
    """Verify a payment with the x402 facilitator.

    Returns (is_valid, payment_response).
    """
    resource_url = f"{DISCOVERY_API_URL}/tools/{tool_name}"
    payload = {
        "x402Version": 2,
        "scheme": "exact",
        "network": NETWORK,
        "payload": payment_header,
        "requirements": {
            "scheme": "exact",
            "network": NETWORK,
            "amount": amount_units,
            "resource": resource_url,
            "payTo": WALLET_ADDRESS,
            "asset": USDC_CONTRACT,
            "maxTimeoutSeconds": 60,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(FACILITATOR_URL, json=payload)
        data = resp.json()
        is_valid = resp.status_code == 200 and data.get("isValid", False)
        return is_valid, data.get("paymentResponse", "") if is_valid else ""
    except Exception as exc:
        log.warning("Facilitator unreachable: %s", exc)
        # In dev mode, allow payment bypass for testing
        if os.getenv("X402_DEV_MODE", "").lower() in ("1", "true", "yes"):
            log.warning("DEV MODE: skipping payment verification")
            return True, "dev_mode_bypass"
        return False, ""


def _payment_challenge(tool_name: str, price_units: int) -> str:
    """Generate a payment challenge string (MCP equivalent of HTTP 402 body)."""
    resource_url = f"{DISCOVERY_API_URL}/tools/{tool_name}"
    challenge = {
        "error": "Payment Required",
        "x402Version": 2,
        "tool": tool_name,
        "accepts": [{
            "scheme": "exact",
            "network": NETWORK,
            "amount": str(price_units),
            "resource": resource_url,
            "description": f"Payment required to call tool: {tool_name}",
            "mimeType": "application/json",
            "payTo": WALLET_ADDRESS,
            "maxTimeoutSeconds": 60,
            "asset": USDC_CONTRACT,
            "extra": {"name": "USDC", "version": "2"},
        }],
        "instructions": (
            f"To call this tool, pay {price_units} USDC micro-units "
            f"(${price_units / 1_000_000:.4f} USD) to {WALLET_ADDRESS} on Base "
            f"and include the payment proof in the 'x402_payment' parameter."
        ),
    }
    return json.dumps(challenge, indent=2)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "x402-payment-gateway",
    instructions=(
        "This is an x402 Payment Gateway. Each tool requires a micropayment in USDC on Base "
        "before it executes. This enables programmable tool economics — agents pay for "
        "capabilities they use, providers earn per call.\n\n"
        "HOW TO USE:\n"
        "1. Call any tool without 'x402_payment' to get a payment challenge.\n"
        "2. Pay the specified amount to the wallet address on Base.\n"
        "3. Call the tool again with 'x402_payment' set to your payment proof.\n"
        "4. Tool executes and returns results.\n\n"
        f"Payment recipient: {WALLET_ADDRESS}\n"
        "Network: Base (eip155:8453) | Token: USDC"
    ),
)


@mcp.tool(
    description=(
        "List all available tools and their prices. "
        "Call this first to see what's available and how much each tool costs."
    )
)
def list_gated_tools() -> str:
    """List all tools available through the payment gateway with their prices."""
    if not _GATED_TOOLS:
        return "No tools registered yet. The gateway is running but empty."

    lines = [
        f"x402 Payment Gateway — {len(_GATED_TOOLS)} tools available\n",
        f"Payment wallet: {WALLET_ADDRESS}",
        f"Network: Base (eip155:8453) | Token: USDC\n",
        "---",
    ]
    for tool in _GATED_TOOLS.values():
        lines.append(
            f"• {tool.name} — ${tool.price_usd:.4f}/call ({tool.price_usdc_units} USDC units)\n"
            f"  {tool.description}\n"
            f"  Tags: {', '.join(tool.tags) if tool.tags else 'none'}"
        )

    lines.append("\n---")
    lines.append(
        "To call any tool: include 'x402_payment' parameter with your payment proof.\n"
        "To get a payment challenge: call the tool without 'x402_payment'."
    )
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Discover x402-payable services by capability. This tool itself requires payment "
        "via x402 (the gateway is self-referential). Returns quality-ranked services "
        "with uptime, latency, and pricing signals."
    )
)
def discover_x402_services(
    capability: Optional[str] = None,
    max_price_usd: float = 0.50,
    query: Optional[str] = None,
    x402_payment: Optional[str] = None,
) -> str:
    """Find x402-payable services matching your requirements.

    Args:
        capability: Filter by capability (research, data, compute, monitoring, etc.)
        max_price_usd: Maximum price per call in USD.
        query: Free-text search term.
        x402_payment: Payment proof from x402 facilitator. Include to bypass payment gate.

    Returns:
        Payment challenge (if no payment) or ranked service list (if payment valid).
    """
    tool_name = "discover_x402_services"
    tool = _GATED_TOOLS.get(tool_name)

    if tool is None:
        # Self-register if not already registered
        price = 1000  # $0.001 — cheap discovery
        if x402_payment is None:
            return _payment_challenge(tool_name, price)
        # Verify payment async (run in sync context)
        loop = asyncio.new_event_loop()
        is_valid, _ = loop.run_until_complete(
            verify_x402_payment(x402_payment, tool_name, str(price))
        )
        loop.close()
        if not is_valid:
            return f"Payment verification failed.\n\n{_payment_challenge(tool_name, price)}"
    elif x402_payment is None:
        return _payment_challenge(tool_name, tool.price_usdc_units)
    else:
        loop = asyncio.new_event_loop()
        is_valid, _ = loop.run_until_complete(
            verify_x402_payment(x402_payment, tool_name, str(tool.price_usdc_units))
        )
        loop.close()
        if not is_valid:
            return f"Payment verification failed.\n\n{_payment_challenge(tool_name, tool.price_usdc_units if tool else 1000)}"

    # Payment verified — execute
    _tool_call_counts[tool_name] = _tool_call_counts.get(tool_name, 0) + 1

    try:
        import requests
        resp = requests.get(
            f"{DISCOVERY_API_URL}/catalog", timeout=15
        )
        resp.raise_for_status()
        services = resp.json().get("services", [])
    except Exception as e:
        return f"Discovery API error: {e}"

    # Filter
    if capability:
        services = [s for s in services if capability in s.get("capability_tags", [])]
    services = [s for s in services if s.get("price_per_call", 999) <= max_price_usd]
    if query:
        q = query.lower()
        services = [s for s in services if q in s.get("name", "").lower() or q in s.get("description", "").lower()]

    # Sort by quality
    order = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
    services.sort(key=lambda s: order.get(s.get("quality_tier", "unverified"), 3))

    top = services[:5]
    if not top:
        return f"No services found for capability={capability!r}, query={query!r}."

    lines = [f"Payment verified. Found {len(services)} services (top {len(top)}):\n"]
    for i, s in enumerate(top, 1):
        lines.append(
            f"{i}. {s.get('name', '?')} [{s.get('quality_tier', 'unverified').upper()}]\n"
            f"   URL: {s.get('endpoint_url', s.get('url', '?'))}\n"
            f"   Price: ${s.get('price_per_call', '?')}/call\n"
            f"   Uptime: {s.get('uptime_pct', '?')}% | Latency: {s.get('avg_latency_ms', '?')}ms\n"
            f"   {s.get('description', '')}\n"
        )
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Get payment gateway statistics: total calls processed, revenue earned, "
        "tools registered. Free, no payment required."
    )
)
def gateway_stats() -> str:
    """Return gateway statistics and revenue tracking."""
    total_calls = sum(_tool_call_counts.values())

    # Estimate revenue
    total_revenue_units = 0
    for tool_name, count in _tool_call_counts.items():
        tool = _GATED_TOOLS.get(tool_name)
        if tool:
            total_revenue_units += tool.price_usdc_units * count
        else:
            total_revenue_units += 1000 * count  # default $0.001

    revenue_usd = total_revenue_units / 1_000_000

    lines = [
        "x402 Payment Gateway — Statistics",
        "=" * 40,
        f"Tools registered: {len(_GATED_TOOLS)}",
        f"Total calls processed: {total_calls}",
        f"Estimated revenue: ${revenue_usd:.6f} USDC",
        f"Payment wallet: {WALLET_ADDRESS}",
        "",
        "Per-tool breakdown:",
    ]
    for tool_name, count in sorted(_tool_call_counts.items(), key=lambda x: -x[1]):
        tool = _GATED_TOOLS.get(tool_name)
        price = tool.price_usdc_units if tool else 1000
        tool_revenue = price * count / 1_000_000
        lines.append(f"  {tool_name}: {count} calls -> ${tool_revenue:.6f} USDC")

    return "\n".join(lines)


@mcp.tool(
    description=(
        "Register a new tool with the payment gateway. "
        "After registration, the tool will require x402 payment to call. "
        "Returns the payment challenge format for the new tool."
    )
)
def register_tool_for_payment(
    tool_name: str,
    description: str,
    price_usdc_units: int,
    endpoint_url: str,
    tags: str = "",
) -> str:
    """Register an external tool/service with the payment gateway.

    Args:
        tool_name: Unique tool identifier (e.g. 'weather_lookup').
        description: What this tool does (one sentence).
        price_usdc_units: Price in USDC micro-units (1 USDC = 1,000,000 units).
        endpoint_url: The actual endpoint that gets called after payment.
        tags: Comma-separated capability tags.

    Returns:
        Confirmation with payment challenge format for this tool.
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    # Create a proxy handler that calls the endpoint_url
    def proxy_handler(**kwargs) -> str:
        import requests
        kwargs.pop("x402_payment", None)
        try:
            resp = requests.post(endpoint_url, json=kwargs, timeout=30)
            return resp.text
        except Exception as e:
            return f"Endpoint error: {e}"

    register_gated_tool(
        name=tool_name,
        description=description,
        price_usdc_units=price_usdc_units,
        handler=proxy_handler,
        tags=tag_list,
    )

    price_usd = price_usdc_units / 1_000_000
    return (
        f"Tool '{tool_name}' registered successfully.\n"
        f"Price: ${price_usd:.4f}/call ({price_usdc_units} USDC micro-units)\n"
        f"Tags: {', '.join(tag_list) or 'none'}\n\n"
        f"Payment challenge for '{tool_name}':\n"
        f"{_payment_challenge(tool_name, price_usdc_units)}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting x402 Payment Gateway MCP Server")
    log.info("Wallet: %s", WALLET_ADDRESS)
    log.info("Gated tools: %d", len(_GATED_TOOLS))
    mcp.run()
