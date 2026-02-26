"""MCP Streamable HTTP Transport — Smithery-compatible.

Creates a FastAPI APIRouter with /smithery (POST + GET) and
/.well-known/mcp/server-card.json routes.
Dependencies are injected via create_mcp_router() to avoid circular imports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

MCP_TOOLS = [
    {
        "name": "x402_discover",
        "description": (
            "Find x402-payable APIs at runtime. Returns quality-ranked results "
            "with uptime, latency, and trust signals. Agents pay $0.005 USDC "
            "on Base per query. Omit x402_payment to receive a payment challenge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Free-text search query"},
                "category": {
                    "type": "string",
                    "description": "Filter by category: research, data, compute, agent, utility, monitoring, verification, routing, storage, generation, extraction, summarization, other",
                },
                "limit": {"type": "integer", "description": "Max results (1-50)", "default": 10},
                "x402_payment": {
                    "type": "string",
                    "description": "x402 payment proof header value. Omit to receive 402 payment challenge.",
                },
            },
        },
        "annotations": {
            "title": "Discover x402 APIs",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "x402_browse",
        "description": "Browse the full x402 service catalog grouped by category. Free — no payment required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional: filter by category",
                },
            },
        },
        "annotations": {
            "title": "Browse x402 Catalog",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "x402_health",
        "description": "Check live health, uptime %, and latency of a registered x402 service. Free.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "Service ID from catalog (e.g. 'ouroboros/discovery')",
                },
            },
            "required": ["service_id"],
        },
        "annotations": {
            "title": "Check Service Health",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "x402_register",
        "description": "Register a new x402-payable service with the discovery layer. Free.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Service name"},
                "url": {"type": "string", "description": "Service base URL"},
                "description": {"type": "string", "description": "What the service does"},
                "price_usd": {"type": "number", "description": "Price per call in USD"},
                "category": {"type": "string", "description": "Category tag"},
            },
            "required": ["name", "url", "description", "price_usd", "category"],
        },
        "annotations": {
            "title": "Register x402 Service",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "x402_trust",
        "description": "Look up the ERC-8004 trust profile for an x402 service. Returns on-chain identity, reputation score, validation attestations, and well-known verification status. Free — no payment required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wallet": {
                    "type": "string",
                    "description": "Ethereum/Base wallet address (0x...) to look up",
                },
                "url": {
                    "type": "string",
                    "description": "Service URL to check /.well-known/erc8004.json verification",
                },
            },
        },
        "annotations": {
            "title": "ERC-8004 Trust Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
]

MCP_PROMPTS = [
    {
        "name": "discover_x402_services",
        "description": "Generate a discovery query to find x402-payable APIs matching a capability or use-case.",
        "arguments": [
            {
                "name": "capability",
                "description": "What capability you need (e.g. 'web search', 'code execution', 'weather data')",
                "required": True,
            }
        ],
    },
    {
        "name": "evaluate_service_trustworthiness",
        "description": "Evaluate whether an x402 service is trustworthy based on ERC-8004 identity, health signals, and pricing.",
        "arguments": [
            {
                "name": "service_id",
                "description": "Service ID or wallet address to evaluate",
                "required": True,
            }
        ],
    },
]

MCP_RESOURCES = [
    {
        "uri": "x402://catalog",
        "name": "x402 Service Catalog",
        "description": "Full index of registered x402-payable APIs with quality signals and trust scores.",
        "mimeType": "application/json",
    },
    {
        "uri": "x402://catalog/featured",
        "name": "Featured x402 Services",
        "description": "Curated selection of high-quality, verified x402 services.",
        "mimeType": "application/json",
    },
]


# ---------------------------------------------------------------------------
# Tool call handler
# ---------------------------------------------------------------------------

async def _handle_mcp_tool_call(
    tool_name: str,
    arguments: dict,
    request: Request,
    registry: list,
    search_fn: Callable,
    payment_fn: Callable,
    enrich_fn: Callable,
    health_stats_fn: Callable,
    last_check_fn: Callable,
    health_status_fn: Callable,
    migrate_fn: Callable,
    save_fn: Callable,
    query_price_units: str,
    payment_required_body_fn: Callable,
    trust_fn: Callable,
) -> dict:
    """Execute an MCP tool call and return the result content."""
    if tool_name == "x402_browse":
        category_filter = arguments.get("category")
        services = list(registry)
        if category_filter:
            services = [s for s in services if s.get("category") == category_filter]
        by_category: dict = {}
        for s in services:
            cat = s.get("category") or "other"
            by_category.setdefault(cat, []).append(enrich_fn(s))
        return {
            "type": "text",
            "text": json.dumps({
                "total": len(services),
                "categories": len(by_category),
                "catalog": by_category,
            }, indent=2),
        }

    elif tool_name == "x402_health":
        service_id = arguments.get("service_id", "")
        entry = next(
            (e for e in registry if e.get("service_id") == service_id or e.get("id") == service_id),
            None,
        )
        if not entry:
            return {"type": "text", "text": json.dumps({"error": f"Service '{service_id}' not found"})}
        url = entry.get("url", "")
        stats = health_stats_fn(url)
        last = last_check_fn(url)
        return {
            "type": "text",
            "text": json.dumps({
                "service_id": service_id,
                "name": entry.get("name"),
                "status": health_status_fn(stats, last or {}),
                "uptime_pct": stats.get("uptime_pct"),
                "avg_latency_ms": stats.get("avg_latency_ms"),
                "last_checked": last.get("checked_at") if last else None,
            }, indent=2),
        }

    elif tool_name == "x402_register":
        name = arguments.get("name", "")
        url_arg = arguments.get("url", "")
        desc = arguments.get("description", "")
        price_usd = arguments.get("price_usd", 0.01)
        category = arguments.get("category", "other")
        if not all([name, url_arg, desc]):
            return {"type": "text", "text": json.dumps({"error": "name, url, and description are required"})}
        service_id = f"{name.lower().replace(' ', '-')}/{hashlib.md5(url_arg.encode()).hexdigest()[:8]}"
        reg_entry = {
            "id": str(uuid.uuid4()),
            "service_id": service_id,
            "name": name,
            "url": url_arg,
            "description": desc,
            "price_usd": price_usd,
            "category": category,
            "listed_at": datetime.now(timezone.utc).isoformat(),
            "source": "mcp_smithery",
        }
        reg_entry = migrate_fn(reg_entry)
        registry.append(reg_entry)
        save_fn(registry)
        return {"type": "text", "text": json.dumps({"service_id": service_id, "status": "registered"}, indent=2)}

    elif tool_name == "x402_discover":
        payment_header = arguments.get("x402_payment")
        host = request.headers.get("host", "x402-discovery-api.onrender.com")
        resource_path = "/discover"

        if not payment_header:
            challenge = payment_required_body_fn(
                host, resource_path, query_price_units, "x402 Service Discovery Query"
            )
            return {
                "type": "text",
                "text": json.dumps({
                    "payment_required": True,
                    "message": "This tool requires an x402 micropayment of $0.005 USDC on Base.",
                    "payment_challenge": challenge,
                    "how_to_pay": "Include the x402_payment argument with your payment proof to execute the query.",
                }, indent=2),
                "isError": False,
            }

        is_valid, _payment_response = await payment_fn(
            payment_header,
            f"https://{host}{resource_path}",
            query_price_units,
        )
        if not is_valid:
            return {
                "type": "text",
                "text": json.dumps({"error": "Payment verification failed", "payment_required": True}),
                "isError": True,
            }

        q = arguments.get("q")
        category = arguments.get("category")
        limit = min(int(arguments.get("limit", 10)), 50)
        results = search_fn(q, category, None, limit)
        return {
            "type": "text",
            "text": json.dumps({"results": results, "count": len(results)}, indent=2),
        }

    elif tool_name == "x402_trust":
        wallet = arguments.get("wallet")
        url_arg = arguments.get("url")
        if not wallet and not url_arg:
            return {"type": "text", "text": json.dumps({"error": "Provide wallet address or url"})}
        import asyncio
        profile = await trust_fn(wallet=wallet, service_url=url_arg)
        return {"type": "text", "text": json.dumps(profile, indent=2)}

    else:
        return {"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"}), "isError": True}


# ---------------------------------------------------------------------------
# Prompt and resource helpers (module-level — no closure needed)
# ---------------------------------------------------------------------------

def _handle_prompts(method: str, req_id, params: dict) -> JSONResponse:
    if method == "prompts/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"prompts": MCP_PROMPTS},
        })
    # prompts/get
    prompt_name = params.get("name", "")
    prompt = next((p for p in MCP_PROMPTS if p["name"] == prompt_name), None)
    if not prompt:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": f"Prompt not found: {prompt_name}"},
        }, status_code=404)
    args = params.get("arguments", {})
    if prompt_name == "discover_x402_services":
        capability = args.get("capability", "APIs")
        messages = [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"Use x402_discover to find x402-payable services for: {capability}. Show results with quality scores, pricing, and health status.",
                },
            }
        ]
    else:
        service_id = args.get("service_id", "the service")
        messages = [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"Check trustworthiness of {service_id}: use x402_health for uptime/latency, x402_trust for ERC-8004 on-chain identity. Summarize risk level.",
                },
            }
        ]
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"description": prompt["description"], "messages": messages},
    })


def _handle_resources(method: str, req_id, params: dict, registry: list) -> JSONResponse:
    if method == "resources/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"resources": MCP_RESOURCES},
        })
    # resources/read
    uri = params.get("uri", "")
    if uri == "x402://catalog":
        catalog_summary = [
            {"id": e.get("id"), "name": e.get("name"), "category": e.get("category"), "price_usd": e.get("price_usd")}
            for e in registry
        ]
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"services": catalog_summary, "count": len(catalog_summary)}, indent=2),
                    }
                ]
            },
        })
    elif uri == "x402://catalog/featured":
        sorted_entries = sorted(
            registry,
            key=lambda e: (e.get("uptime_pct", 0) or 0) + (100 - min(e.get("avg_latency_ms", 100) or 100, 100)),
            reverse=True,
        )[:5]
        featured = [
            {"id": e.get("id"), "name": e.get("name"), "category": e.get("category"), "price_usd": e.get("price_usd"), "uptime_pct": e.get("uptime_pct"), "health_status": e.get("health_status")}
            for e in sorted_entries
        ]
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"featured": featured, "count": len(featured)}, indent=2),
                    }
                ]
            },
        })
    else:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": f"Resource not found: {uri}"},
        }, status_code=404)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_mcp_router(
    registry: list,
    search_fn: Callable,
    payment_fn: Callable,
    enrich_fn: Callable,
    health_stats_fn: Callable,
    last_check_fn: Callable,
    health_status_fn: Callable,
    migrate_fn: Callable,
    save_fn: Callable,
    query_price_units: str,
    payment_required_body_fn: Callable,
    trust_fn: Callable,
) -> APIRouter:
    """Create and return an APIRouter with MCP Streamable HTTP transport routes."""
    router = APIRouter()

    @router.post("/smithery")
    async def smithery_mcp(request: Request) -> JSONResponse:
        """MCP Streamable HTTP transport endpoint for Smithery.

        Implements JSON-RPC 2.0 over HTTP POST per MCP spec.
        Handles: initialize, notifications/initialized, tools/list, tools/call,
                 prompts/list, prompts/get, resources/list, resources/read
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
                status_code=400,
            )

        method = body.get("method", "")
        params = body.get("params", {})
        req_id = body.get("id")  # None for notifications

        # Notifications (no id) — acknowledge with 202
        if req_id is None:
            return JSONResponse({}, status_code=202)

        if method == "initialize":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "prompts": {"listChanged": False},
                        "resources": {"listChanged": False, "subscribe": False},
                    },
                    "serverInfo": {
                        "name": "x402-discovery",
                        "version": "3.1.0",
                    },
                    "instructions": (
                        "x402 Service Discovery: find and pay for APIs at runtime. "
                        "Use x402_browse to explore the catalog (free), x402_discover "
                        "to search with quality signals ($0.005 USDC on Base), "
                        "x402_health to check uptime, x402_register to list your API. "
                        "Use x402_trust to check ERC-8004 on-chain trust profiles."
                    ),
                },
            })

        elif method == "tools/list":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": MCP_TOOLS},
            })

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                content = await _handle_mcp_tool_call(
                    tool_name, arguments, request,
                    registry, search_fn, payment_fn, enrich_fn,
                    health_stats_fn, last_check_fn, health_status_fn,
                    migrate_fn, save_fn, query_price_units, payment_required_body_fn,
                    trust_fn,
                )
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [content],
                        "isError": content.get("isError", False),
                    },
                })
            except Exception as exc:
                log.error("MCP tools/call error: %s", exc)
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Internal error: {exc}"},
                }, status_code=500)

        elif method in ("prompts/list", "prompts/get"):
            return _handle_prompts(method, req_id, params)

        elif method in ("resources/list", "resources/read"):
            return _handle_resources(method, req_id, params, registry)

        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }, status_code=404)

    @router.get("/smithery")
    async def smithery_info() -> JSONResponse:
        """GET /smithery — server info for discoverability."""
        return JSONResponse({
            "transport": "streamable-http",
            "endpoint": "POST /smithery",
            "protocol": "mcp",
            "version": "2024-11-05",
            "server": "x402-discovery",
            "tools": [t["name"] for t in MCP_TOOLS],
        })

    @router.get("/.well-known/mcp/server-card.json", include_in_schema=False)
    async def mcp_server_card() -> JSONResponse:
        """Smithery server card for automated discovery."""
        return JSONResponse({
            "schema_version": "1.0",
            "name": "x402 Service Discovery",
            "description": (
                "Discovers x402-payable APIs at runtime. Enables autonomous agents to find, "
                "evaluate, and pay for services via USDC micropayments on Base — "
                "no API keys or subscriptions required."
            ),
            "homepage": "https://x402-discovery-api.onrender.com",
            "mcp_endpoint": "https://x402-discovery-api.onrender.com/smithery",
            "transport": "streamable-http",
            "tools": [t["name"] for t in MCP_TOOLS],
            "pricing": {
                "model": "x402-micropayment",
                "currency": "USDC",
                "network": "base",
                "paid_tools": ["x402_discover"],
                "price_per_call_usd": 0.005,
            },
        })

    return router
