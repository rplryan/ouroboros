"""
FastMCP HTTP transport for Smithery.ai compatibility.

Mounts at /smithery on the main FastAPI app, providing proper MCP protocol
transport (streamable HTTP) for MCP clients like Smithery.
"""

from __future__ import annotations
import logging

log = logging.getLogger(__name__)

try:
    from fastmcp import FastMCP
    from fastmcp.utilities.lifespan import combine_lifespans
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    log.warning("fastmcp not installed — Smithery MCP transport disabled")


def build_mcp_app(search_fn, trust_fn=None):
    """
    Build the FastMCP ASGI app and return (mcp_app, combined_lifespan_fn).

    Args:
        search_fn: callable(query, category, min_uptime, limit) -> list of result dicts
        trust_fn: async callable(wallet_or_url) -> trust profile dict

    Returns:
        (mcp_http_app, combine_lifespans_fn) or (None, None) if fastmcp unavailable
    """
    if not FASTMCP_AVAILABLE:
        return None, None

    x402_mcp = FastMCP(
        "x402 Service Discovery",
        instructions=(
            "Discovers x402-payable APIs for autonomous agents. "
            "Use x402_discover to find endpoints that accept micropayments on Base. "
            "Each call to x402_discover costs $0.005 USDC via x402 protocol. "
            "Use x402_trust to check a service's ERC-8004 on-chain trust profile."
        ),
    )

    @x402_mcp.tool
    async def x402_discover(query: str) -> dict:
        """
        Discover x402-payable services matching a query.

        Searches the registry of x402-enabled APIs and returns matching endpoints
        with quality signals (uptime, latency, payment details).

        Args:
            query: Natural language or keyword search (e.g. 'weather', 'llm', 'research')

        Returns:
            dict with 'results' (list of matching services) and 'count'
        """
        results = search_fn(query, None, None, 5)
        return {"results": results, "count": len(results), "query": query}

    @x402_mcp.tool
    async def x402_browse(category: str = "", limit: int = 20) -> dict:
        """
        Browse all registered x402-payable services with optional category filtering.

        Free — no payment required.

        Args:
            category: Optional filter (e.g. 'data', 'compute', 'research', 'agent', 'utility')
            limit: Max results to return (default 20)

        Returns:
            dict with 'results' and 'count'
        """
        results = search_fn("", category or None, None, limit)
        return {"results": results, "count": len(results), "category": category or "all"}

    @x402_mcp.tool
    async def x402_health(url: str) -> dict:
        """
        Check the health and uptime statistics of a specific x402 service.

        Free — no payment required.

        Args:
            url: The endpoint URL of the service to check

        Returns:
            dict with health_status, uptime_pct, avg_latency_ms, last_check
        """
        results = search_fn(url, None, None, 50)
        for r in results:
            if r.get("url") == url or url in r.get("url", ""):
                return {
                    "url": r.get("url"),
                    "health_status": r.get("health_status", "unknown"),
                    "uptime_pct": r.get("uptime_pct"),
                    "avg_latency_ms": r.get("avg_latency_ms"),
                    "last_health_check": r.get("last_health_check"),
                    "query_count": r.get("query_count", 0),
                }
        return {"url": url, "health_status": "not_found", "error": "Service not in registry"}

    @x402_mcp.tool
    async def x402_trust(wallet_or_url: str) -> dict:
        """
        Get the ERC-8004 on-chain trust profile for a service or wallet address.

        ERC-8004 is an Ethereum standard providing decentralized AI agent trust via:
        - Identity Registry: verifiable on-chain agent identifier
        - Reputation Registry: interaction scores from past transactions
        - Validation Registry: third-party attestations

        Free — no payment required.

        Args:
            wallet_or_url: Ethereum wallet address (0x...) or service URL

        Returns:
            dict with erc8004 trust profile including identity_id, reputation_score,
            validation_count, and well_known_verified status
        """
        if trust_fn is not None:
            import re
            if re.match(r"^0x[0-9a-fA-F]{40}$", wallet_or_url):
                return await trust_fn(wallet=wallet_or_url)
            else:
                return await trust_fn(service_url=wallet_or_url)
        return {
            "wallet": wallet_or_url,
            "erc8004_status": "unavailable",
            "error": "Trust lookup function not initialized",
        }

    @x402_mcp.tool
    async def x402_register(
        name: str,
        url: str,
        description: str,
        price_usd: float,
        category: str,
        tags: list[str] | None = None,
        wallet: str = "",
        network: str = "base",
    ) -> dict:
        """
        Register a new x402-payable service in the discovery catalog.

        Free — no payment required.

        Args:
            name: Human-readable name of the service
            url: The x402-enabled endpoint URL
            description: What the service does
            price_usd: Price per request in USD
            category: Category (data / compute / research / agent / utility)
            tags: Optional list of capability tags
            wallet: Ethereum wallet address that receives payments (optional)
            network: Network name (default: base)

        Returns:
            dict with registration status and assigned service ID
        """
        return {
            "status": "use_rest_api",
            "message": "Registration requires the REST API. POST to https://x402-discovery-api.onrender.com/register",
            "endpoint": "https://x402-discovery-api.onrender.com/register",
            "method": "POST",
            "body_example": {
                "name": name,
                "url": url,
                "description": description,
                "price_usd": price_usd,
                "category": category,
                "tags": tags or [],
                "wallet": wallet,
                "network": network,
            },
        }

    mcp_http_app = x402_mcp.http_app(path="/")
    log.info("FastMCP server built — will mount at /smithery")
    return mcp_http_app, combine_lifespans
