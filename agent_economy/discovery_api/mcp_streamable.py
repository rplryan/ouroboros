"""
Streamable HTTP MCP transport for claude.ai/mcp Connectors Directory.

Builds a FastMCP app with stateless_http=True and mounts at /mcp on the
main FastAPI app. This is separate from the Smithery mount at /smithery.
"""

from __future__ import annotations
import logging

log = logging.getLogger(__name__)

try:
    from fastmcp import FastMCP
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    log.warning("fastmcp not installed — Streamable HTTP MCP disabled")

try:
    from mcp.types import ToolAnnotations
    HAS_ANNOTATIONS = True
except ImportError:
    HAS_ANNOTATIONS = False
    ToolAnnotations = dict  # fallback — annotations skipped

# Import shared helpers from fastmcp_server to avoid duplication
try:
    from fastmcp_server import (
        _attest_service,
        _register_redirect,
        _DISCOVER_VERIFY_PROMPT_TEMPLATE,
    )
except ImportError:
    # Fallback definitions if fastmcp_server is unavailable
    async def _attest_service(service_id: str, raw: bool = False) -> dict:  # type: ignore[misc]
        return {"error": "Attestation module unavailable"}

    def _register_redirect(name, url, description, price_usd, category, tags=None, wallet="", network="base") -> dict:  # type: ignore[misc]
        return {
            "status": "use_rest_api",
            "endpoint": "https://x402-discovery-api.onrender.com/register",
            "method": "POST",
        }

    _DISCOVER_VERIFY_PROMPT_TEMPLATE = (
        "1. Call x402_browse to see all available services. "
        "2. Call x402_discover with query='{capability}' to find matching services. "
        "3. Call x402_health on the top result to verify it's online. "
        "4. The service URL uses x402 protocol — your first request will return HTTP 402 with payment instructions."
    )


def build_streamable_mcp_app(search_fn, trust_fn=None):
    """
    Build a FastMCP ASGI app with stateless_http=True for claude.ai/mcp.

    Args:
        search_fn: callable(query, category, min_uptime, limit) -> list of result dicts
        trust_fn: async callable(wallet=..., service_url=...) -> trust profile dict

    Returns:
        ASGI app to mount at /mcp, or None if fastmcp unavailable
    """
    if not FASTMCP_AVAILABLE:
        return None

    x402_mcp = FastMCP(
        "x402 Service Discovery",
        stateless_http=True,
        instructions=(
            "Discovers x402-payable APIs for autonomous agents. "
            "Use x402_discover to find endpoints that accept micropayments on Base. "
            "Each call to x402_discover costs $0.005 USDC via x402 protocol. "
            "Use x402_trust to check a service's ERC-8004 on-chain trust profile."
        ),
    )

    def _tool(**ann):
        """Return an @x402_mcp.tool decorator, with ToolAnnotations if available."""
        if HAS_ANNOTATIONS:
            return x402_mcp.tool(annotations=ToolAnnotations(**ann))
        return x402_mcp.tool

    @_tool(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
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

    @_tool(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
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

    @_tool(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
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

    @_tool(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
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

    @_tool(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
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
        return _register_redirect(name, url, description, price_usd, category, tags, wallet, network)

    @_tool(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    async def x402_attest(service_id: str, raw: bool = False) -> dict:
        """
        Fetch a signed EdDSA attestation (JWT) for a registered x402 service.

        The attestation contains cryptographically signed quality measurements:
        uptime %, avg latency, health status, and facilitator compatibility.
        Implements the ERC-8004 coldStartSignals spec (coinbase/x402#1375).
        Verify offline using GET /jwks. Valid for 24 hours.

        Free — no payment required.

        Args:
            service_id: The service ID from the catalog (e.g. 'legacy/cf-pay-per-crawl').
                        Use x402_browse to find valid service IDs.
            raw: If True, return the raw JWT string for embedding. Default False returns
                 a human-readable summary of the signed measurements.

        Returns:
            dict with attestation data — quality measurements, facilitator info,
            issued_at, verify_at (JWKS URL), and either a human-readable summary
            or the raw JWT.
        """
        return await _attest_service(service_id, raw)

    @x402_mcp.prompt
    def find_service_for_task(task: str) -> str:
        """Find the best x402 service for a specific task.

        Args:
            task: Description of what you need to accomplish
        """
        return f"Use x402_discover to find x402-payable services for: {task}. Then use x402_health to verify the top result is online before proceeding."

    @x402_mcp.prompt
    def discover_and_verify(capability: str) -> str:
        """Discover and verify an x402 service by capability.

        Args:
            capability: The capability you need (e.g. 'web search', 'data extraction', 'llm inference')
        """
        return _DISCOVER_VERIFY_PROMPT_TEMPLATE.format(capability=capability)

    asgi_app = x402_mcp.http_app(path="/")
    log.info("Streamable HTTP MCP server built — will mount at /mcp")
    return asgi_app
