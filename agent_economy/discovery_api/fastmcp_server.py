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


def build_mcp_app(search_fn):
    """
    Build the FastMCP ASGI app and return (mcp_app, combined_lifespan_fn).
    
    Args:
        search_fn: callable(query, category, min_uptime, limit) -> list of result dicts
    
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
            "Each call to x402_discover costs $0.005 USDC via x402 protocol."
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

    mcp_http_app = x402_mcp.http_app(path="/")
    log.info("FastMCP server built — will mount at /smithery")
    return mcp_http_app, combine_lifespans
