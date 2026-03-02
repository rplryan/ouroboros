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

try:
    from mcp.types import ToolAnnotations
    HAS_ANNOTATIONS = True
except ImportError:
    HAS_ANNOTATIONS = False
    ToolAnnotations = dict  # fallback — annotations skipped


# Exported for /.well-known/mcp/server-card.json (scores Smithery configSchema points)
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "baseUrl": {
            "type": "string",
            "title": "Custom API Base URL",
            "description": "Override the default API endpoint (e.g. for self-hosted instances)",
            "default": "https://x402-discovery-api.onrender.com",
        },
        "maxResults": {
            "type": "integer",
            "title": "Max Results",
            "description": "Maximum number of results to return per discovery query",
            "default": 5,
            "minimum": 1,
            "maximum": 20,
        },
        "minUptimePct": {
            "type": "number",
            "title": "Minimum Uptime %",
            "description": "Only return services with uptime above this threshold (0-100)",
            "default": 0,
            "minimum": 0,
            "maximum": 100,
        },
    },
}


async def _attest_service(service_id: str, raw: bool = False) -> dict:
    """Fetch and decode a signed EdDSA attestation JWT for a registered x402 service."""
    import httpx as _httpx
    import base64 as _b64
    import json as _json
    DISCOVERY_API = "https://x402-discovery-api.onrender.com"
    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{DISCOVERY_API}/v1/attest/{service_id}")
            if resp.status_code == 404:
                return {
                    "error": f"Service '{service_id}' not found in the registry.",
                    "suggestion": "Use x402_browse to find valid service IDs."
                }
            if resp.status_code == 503:
                return {"error": "Attestation signing not configured on this server."}
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"error": f"Attestation error: {e}"}

    jwt_str = data.get("attestation", "")

    if raw:
        return {"jwt": jwt_str, "issued_at": data.get("issued_at"), "verify_at": data.get("verify_at")}

    try:
        parts = jwt_str.split(".")
        payload_bytes = _b64.urlsafe_b64decode(parts[1] + "==")
        payload = _json.loads(payload_bytes)
        quality = payload.get("quality", {})
        facilitator = payload.get("facilitator", {})
        chain = payload.get("chainVerifications", [])
        return {
            "service_id": service_id,
            "service_name": data.get("service_name", service_id),
            "quality": {
                "health_status": quality.get("health_status"),
                "uptime_pct": quality.get("uptime_pct"),
                "avg_latency_ms": quality.get("avg_latency_ms"),
                "last_checked": quality.get("last_checked"),
            },
            "facilitator": {
                "compatible": facilitator.get("compatible"),
                "count": facilitator.get("count"),
                "recommended": facilitator.get("recommended"),
            },
            "chain_verifications": chain,
            "issued_at": data.get("issued_at"),
            "expires_in": "24 hours",
            "verify_at": data.get("verify_at"),
            "spec": data.get("spec"),
            "jwt_preview": jwt_str[:80] + "..." if len(jwt_str) > 80 else jwt_str,
        }
    except Exception:
        return {
            "service_id": service_id,
            "issued_at": data.get("issued_at"),
            "verify_at": data.get("verify_at"),
            "jwt": jwt_str,
        }


def _register_redirect(
    name: str,
    url: str,
    description: str,
    price_usd: float,
    category: str,
    tags=None,
    wallet: str = "",
    network: str = "base",
) -> dict:
    """Return a redirect dict instructing callers to use the REST API for registration."""
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


_DISCOVER_VERIFY_PROMPT_TEMPLATE = (
    "1. Call x402_browse to see all available services. "
    "2. Call x402_discover with query='{capability}' to find matching services. "
    "3. Call x402_health on the top result to verify it's online. "
    "4. The service URL uses x402 protocol — your first request will return HTTP 402 with payment instructions."
)


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
            "Each call to x402_discover costs $0.010 USDC via x402 protocol. "
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

    mcp_http_app = x402_mcp.http_app(path="/")
    log.info("FastMCP server built — will mount at /smithery")
    return mcp_http_app, combine_lifespans
