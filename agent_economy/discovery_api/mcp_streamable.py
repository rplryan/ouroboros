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

# Import shared helpers and tool-registration functions from fastmcp_server
try:
    from fastmcp_server import (
        _DISCOVER_VERIFY_PROMPT_TEMPLATE,
        _register_browse_tool,
        _register_discover_tools,
        _register_registration_tools,
        _register_scan_tool,
    )
except ImportError:
    # Fallback stubs if fastmcp_server is unavailable
    _DISCOVER_VERIFY_PROMPT_TEMPLATE = (
        "1. Call x402_browse to see all available services. "
        "2. Call x402_discover with query='{capability}' to find matching services. "
        "3. Call x402_health on the top result to verify it's online. "
        "4. The service URL uses x402 protocol — your first request will return HTTP 402 with payment instructions."
    )

    def _register_scan_tool(mcp, api_base): pass  # type: ignore[misc]
    def _register_browse_tool(mcp, search_fn, api_base): pass  # type: ignore[misc]
    def _register_discover_tools(mcp, search_fn, trust_fn, api_base): pass  # type: ignore[misc]
    def _register_registration_tools(mcp, api_base): pass  # type: ignore[misc]


def build_streamable_mcp_app(search_fn, trust_fn=None):
    """
    Build a FastMCP ASGI app with stateless_http=True for claude.ai/mcp.

    Args:
        search_fn: callable(query, category, min_uptime, limit) -> list of result dicts
        trust_fn: async callable(wallet=..., service_url=...) -> trust profile dict

    Returns:
        Tuple of (mcp_instance, asgi_app) to mount at /mcp, or None if fastmcp unavailable
    """
    if not FASTMCP_AVAILABLE:
        return (None, None)

    api_base = "https://x402-discovery-api.onrender.com"
    x402_mcp = FastMCP(
        "x402 Service Discovery",
        instructions=(
            "Discovers x402-payable APIs for autonomous agents. "
            "Use x402_discover to find endpoints that accept micropayments on Base. "
            "Each call to x402_discover costs $0.010 USDC via x402 protocol. "
            "Use x402_trust to check a service's ERC-8004 on-chain trust profile."
        ),
    )

    _register_scan_tool(x402_mcp, api_base)
    _register_browse_tool(x402_mcp, search_fn, api_base)
    _register_discover_tools(x402_mcp, search_fn, trust_fn, api_base)
    _register_registration_tools(x402_mcp, api_base)

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

    asgi_app = x402_mcp.http_app(path="/", stateless_http=True)
    log.info("Streamable HTTP MCP server built — will mount at /mcp")
    return x402_mcp, asgi_app
