"""REPLACE_MARKER
Agents query it to discover available services.
Each discovery query costs $0.005 USDC on Base.

Wallet: 0xBceC11f20904a30fC4bAF70B85fc33b7A9294683
Network: Base (Ethereum L2)
Asset: USDC (0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WALLET_ADDRESS: str = os.getenv(
    "WALLET_ADDRESS", "0xBceC11f20904a30fC4bAF70B85fc33b7A9294683"
)
NETWORK: str = os.getenv("NETWORK", "base")  # CAIP-2 network identifier for x402 v2
USDC_CONTRACT: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Prices expressed in USDC 6-decimal units (1 USDC = 1_000_000 units)
QUERY_PRICE_UNITS: str = os.getenv("QUERY_PRICE_USDC_UNITS", "5000")       # $0.005
HEALTH_PRICE_UNITS: str = os.getenv("HEALTH_CHECK_PRICE_USDC_UNITS", "50000")  # $0.05

FACILITATOR_URL: str = "https://x402.org/facilitator/verify"

REGISTRY_PATH: Path = Path(__file__).parent / "registry.json"

# ---------------------------------------------------------------------------
# Logging — never log payment payloads
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("x402-discovery")

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict]:
    if REGISTRY_PATH.exists():
        with REGISTRY_PATH.open() as fh:
            return json.load(fh)
    return []


def _save_registry(entries: list[dict]) -> None:
    with REGISTRY_PATH.open("w") as fh:
        json.dump(entries, fh, indent=2)


# Held in memory; persisted to disk on mutation.
_registry: list[dict] = _load_registry()

# ---------------------------------------------------------------------------
# x402 payment verification
# ---------------------------------------------------------------------------

async def verify_payment(
    payment_header: str,
    resource_url: str,
    amount: str,
) -> tuple[bool, str]:
    """
    Verify an x402 payment with the Coinbase facilitator.

    Returns (is_valid, payment_response_header_value).
    Never raises — failures return (False, "").
    """
    payload = {
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:8453",
        "payload": payment_header,
        "requirements": {
            "scheme": "exact",
            "network": "eip155:8453",
            "amount": amount,
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
        is_valid: bool = resp.status_code == 200 and data.get("isValid", False)
        payment_response: str = data.get("paymentResponse", "") if is_valid else ""
        return is_valid, payment_response
    except Exception as exc:
        log.warning("Facilitator unreachable: %s", exc)
        return False, ""


def _payment_required_body(
    host: str,
    resource_path: str,
    amount: str,
    description: str,
    input_schema: dict | None = None,
) -> dict:
    entry: dict = {
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": amount,
        "resource": f"https://{host}{resource_path}",
        "description": description,
        "mimeType": "application/json",
        "payTo": WALLET_ADDRESS,
        "maxTimeoutSeconds": 60,
        "asset": USDC_CONTRACT,
        "extra": {"name": "USDC", "version": "2"},
    }
    if input_schema is not None:
        entry["input"] = input_schema
    body: dict = {
        "error": "Payment Required",
        "x402Version": 2,
        "accepts": [entry],
    }
    if input_schema is not None:
        body["extensions"] = {"bazaar": {"info": {"input": input_schema}, "schema": input_schema}}
    return body


# ---------------------------------------------------------------------------
# Search / scoring
# ---------------------------------------------------------------------------

def _score_entry(entry: dict, keywords: list[str]) -> int:
    score = 0
    name_lower = entry.get("name", "").lower()
    desc_lower = entry.get("description", "").lower()
    tags_lower = [t.lower() for t in entry.get("tags", [])]

    for kw in keywords:
        kw = kw.lower()
        if kw in tags_lower:
            score += 3
        if kw in desc_lower:
            score += 2
        if kw in name_lower:
            score += 1
    return score


def _search(
    q: Optional[str],
    category: Optional[str],
    limit: int,
) -> list[dict]:
    results = list(_registry)

    if category:
        results = [e for e in results if e.get("category") == category]

    if q:
        keywords = q.lower().split()
        scored = [(e, _score_entry(e, keywords)) for e in results]
        scored = [(e, s) for e, s in scored if s > 0]
        scored.sort(key=lambda x: (x[1], x[0].get("query_count", 0)), reverse=True)
        results = [e for e, _ in scored]
    else:
        results.sort(key=lambda e: e.get("query_count", 0), reverse=True)

    return results[:limit]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"research", "data", "compute", "agent", "utility"}


class RegisterRequest(BaseModel):
    name: str
    description: str
    url: str
    category: str
    price_usd: float
    network: str = "base"
    asset_address: str = USDC_CONTRACT
    tags: list[str] = []

    @field_validator("category")
    @classmethod
    def category_must_be_valid(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        return v

    @field_validator("price_usd")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price_usd must be > 0")
        return v


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="x402 Service Discovery API",
    version="1.0.0",
    description=(
        "Discover x402-payable endpoints. "
        "Each discovery query costs $0.005 USDC on Base."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# GET / — free health check
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "x402 Service Discovery API",
            "version": "1.0.0",
            "description": (
                "Discover x402-payable endpoints. "
                "Each query costs $0.005 USDC on Base."
            ),
            "wallet": WALLET_ADDRESS,
            "network": NETWORK,
            "query_price_usd": 0.005,
            "endpoints": {
                "discover": "GET /discover?q={keyword}&category={category}&limit={limit}",
                "register": "POST /register",
                "health": "GET /health/{endpoint_id}",
                "catalog": "GET /catalog",
                "mcp": "GET /mcp",
            },
        }
    )

# ---------------------------------------------------------------------------
# GET /discover — PAID ($0.005 USDC)
# ---------------------------------------------------------------------------

@app.get("/discover")
async def discover(
    request: Request,
    q: Optional[str] = Query(default=None, description="Keyword search"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results (1–50)"),
) -> JSONResponse:
    host = request.headers.get("host", "localhost")
    resource_path = "/discover"

    payment_header = request.headers.get("X-PAYMENT")

    _discover_input_schema = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Keyword search query"},
            "category": {"type": "string", "description": "Filter by category: research, data, compute, agent, utility"},
            "limit": {"type": "integer", "description": "Max results (1-50)", "default": 10},
        },
    }

    if not payment_header:
        log.info("GET /discover — 402 (no payment header) q=%r category=%r", q, category)
        return JSONResponse(
            status_code=402,
            content=_payment_required_body(
                host, resource_path, QUERY_PRICE_UNITS,
                "x402 Service Discovery Query",
                input_schema=_discover_input_schema,
            ),
        )

    # Verify with facilitator — never log the header value itself
    resource_url = f"https://{host}{resource_path}"
    is_valid, payment_response = await verify_payment(
        payment_header, resource_url, QUERY_PRICE_UNITS
    )

    if not is_valid:
        log.warning("GET /discover — 402 (invalid payment) q=%r", q)
        return JSONResponse(
            status_code=402,
            content=_payment_required_body(
                host, resource_path, QUERY_PRICE_UNITS,
                "x402 Service Discovery Query — payment invalid or facilitator unreachable",
                input_schema=_discover_input_schema,
            ),
        )

    log.info("GET /discover — 200 (payment verified) q=%r category=%r limit=%d", q, category, limit)

    results = _search(q, category, limit)

    # Increment query_count for matched entries
    matched_ids = {e["id"] for e in results}
    for entry in _registry:
        if entry["id"] in matched_ids:
            entry["query_count"] = entry.get("query_count", 0) + 1
    _save_registry(_registry)

    body = {
        "results": results,
        "count": len(results),
        "query": {"q": q, "category": category, "limit": limit},
        "queried_at": datetime.now(timezone.utc).isoformat(),
    }

    json_response = JSONResponse(content=body)
    if payment_response:
        json_response.headers["X-PAYMENT-RESPONSE"] = payment_response
    return json_response


# ---------------------------------------------------------------------------
# POST /register — free
# ---------------------------------------------------------------------------

@app.post("/register", status_code=201)
async def register(body: RegisterRequest) -> JSONResponse:
    # Reject duplicates by URL
    for existing in _registry:
        if existing.get("url") == body.url:
            return JSONResponse(
                status_code=409,
                content={"error": "An endpoint with this URL is already registered.", "id": existing["id"]},
            )

    entry = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "description": body.description,
        "url": body.url,
        "category": body.category,
        "price_usd": body.price_usd,
        "network": body.network,
        "asset_address": body.asset_address,
        "tags": body.tags,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "query_count": 0,
        "uptime_pct": None,
        "avg_latency_ms": None,
        "last_health_check": None,
        "status": "active",
    }
    _registry.append(entry)
    _save_registry(_registry)

    log.info("POST /register — new endpoint registered id=%s name=%r", entry["id"], entry["name"])
    return JSONResponse(status_code=201, content={"registered": True, "id": entry["id"], "entry": entry})


# ---------------------------------------------------------------------------
# GET /health/{endpoint_id} — PAID ($0.05 USDC)
# ---------------------------------------------------------------------------

@app.get("/health/{endpoint_id}")
async def health_check(endpoint_id: str, request: Request) -> JSONResponse:
    host = request.headers.get("host", "localhost")
    resource_path = f"/health/{endpoint_id}"

    payment_header = request.headers.get("X-PAYMENT")

    _health_input_schema = {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string", "description": "The ID of the endpoint to health-check"},
        },
        "required": ["endpoint_id"],
    }

    if not payment_header:
        log.info("GET /health/%s — 402 (no payment header)", endpoint_id)
        return JSONResponse(
            status_code=402,
            content=_payment_required_body(
                host, resource_path, HEALTH_PRICE_UNITS,
                "x402 Endpoint Live Health Check",
                input_schema=_health_input_schema,
            ),
        )

    resource_url = f"https://{host}{resource_path}"
    is_valid, payment_response = await verify_payment(
        payment_header, resource_url, HEALTH_PRICE_UNITS
    )

    if not is_valid:
        log.warning("GET /health/%s — 402 (invalid payment)", endpoint_id)
        return JSONResponse(
            status_code=402,
            content=_payment_required_body(
                host, resource_path, HEALTH_PRICE_UNITS,
                "x402 Endpoint Live Health Check — payment invalid",
                input_schema=_health_input_schema,
            ),
        )

    # Find the endpoint
    entry = next((e for e in _registry if e["id"] == endpoint_id), None)
    if not entry:
        log.info("GET /health/%s — 404", endpoint_id)
        return JSONResponse(status_code=404, content={"error": "Endpoint not found."})

    # Perform live health check
    target_url = entry["url"]
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            t0 = time.monotonic()
            resp = await client.get(target_url)
            latency_ms = int((time.monotonic() - t0) * 1000)
        reachable = resp.status_code < 500
        http_status = resp.status_code
    except Exception as exc:
        log.info("GET /health/%s — target unreachable: %s", endpoint_id, exc)
        reachable = False
        latency_ms = None
        http_status = None

    # Update registry entry
    entry["last_health_check"] = checked_at
    entry["avg_latency_ms"] = latency_ms
    _save_registry(_registry)

    log.info(
        "GET /health/%s — 200 (payment verified) reachable=%s latency_ms=%s",
        endpoint_id, reachable, latency_ms,
    )

    body = {
        "id": endpoint_id,
        "name": entry.get("name"),
        "url": target_url,
        "reachable": reachable,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "checked_at": checked_at,
    }

    json_response = JSONResponse(content=body)
    if payment_response:
        json_response.headers["X-PAYMENT-RESPONSE"] = payment_response
    return json_response


# ---------------------------------------------------------------------------
# GET /catalog — free, no quality signals
# ---------------------------------------------------------------------------

@app.get("/catalog")
async def catalog() -> JSONResponse:
    # Return stripped-down view without operational signals
    stripped = []
    for e in _registry:
        stripped.append(
            {
                "id": e["id"],
                "name": e["name"],
                "description": e["description"],
                "url": e["url"],
                "category": e["category"],
                "price_usd": e["price_usd"],
                "network": e.get("network", "base"),
                "tags": e.get("tags", []),
                "status": e.get("status", "active"),
                "registered_at": e.get("registered_at"),
            }
        )
    return JSONResponse({"catalog": stripped, "count": len(stripped)})


# ---------------------------------------------------------------------------
# GET /.well-known/x402 — free, x402 discovery document
# ---------------------------------------------------------------------------

@app.get("/.well-known/x402", include_in_schema=True)
async def well_known_x402() -> JSONResponse:
    return JSONResponse(
        {
            "x402Version": 1,
            "endpoints": [
                {
                    "path": "/discover",
                    "method": "GET",
                    "description": "Discover x402-payable endpoints by keyword or category",
                    "price": {
                        "amount": QUERY_PRICE_UNITS,
                        "asset": USDC_CONTRACT,
                        "network": NETWORK,
                    },
                    "payTo": WALLET_ADDRESS,
                    "mimeType": "application/json",
                },
                {
                    "path": "/health/{endpoint_id}",
                    "method": "GET",
                    "description": "Live health check for a registered endpoint",
                    "price": {
                        "amount": HEALTH_PRICE_UNITS,
                        "asset": USDC_CONTRACT,
                        "network": NETWORK,
                    },
                    "payTo": WALLET_ADDRESS,
                    "mimeType": "application/json",
                },
            ],
            "name": "x402 Service Discovery API",
            "description": (
                "Registry and discovery service for x402-payable endpoints. "
                "Find, evaluate, and route to verified x402 services."
            ),
            "url": "https://x402-discovery-api.onrender.com",
        }
    )


# ---------------------------------------------------------------------------
# Startup — self-register this service in its own registry
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def self_register() -> None:
    self_url = "https://x402-discovery-api.onrender.com"
    for existing in _registry:
        if existing.get("url") == self_url:
            log.info("startup — self already registered id=%s", existing["id"])
            return

    entry = {
        "id": str(uuid.uuid4()),
        "name": "x402 Service Discovery API",
        "description": (
            "Registry and discovery service for x402-payable endpoints. "
            "$0.005 USDC per query."
        ),
        "url": self_url,
        "category": "utility",
        "price_usd": 0.005,
        "network": NETWORK,
        "asset_address": USDC_CONTRACT,
        "tags": ["discovery", "registry", "infrastructure", "x402"],
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "query_count": 0,
        "uptime_pct": None,
        "avg_latency_ms": None,
        "last_health_check": None,
        "status": "active",
    }
    _registry.append(entry)
    _save_registry(_registry)
    log.info("startup — self-registered id=%s", entry["id"])


# ---------------------------------------------------------------------------
# GET /mcp — free, MCP tool definitions
# ---------------------------------------------------------------------------

@app.get("/mcp")
async def mcp(request: Request) -> JSONResponse:
    host = request.headers.get("host", "localhost")
    base_url = f"https://{host}"

    return JSONResponse(
        {
            "schema_version": "v1",
            "name": "x402-discovery",
            "description": "Discover and pay for x402-gated API endpoints using USDC on Base.",
            "tools": [
                {
                    "name": "discover_endpoints",
                    "description": (
                        "Search the x402 service registry for payable endpoints. "
                        "Costs $0.005 USDC per query. Requires X-PAYMENT header."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "q": {
                                "type": "string",
                                "description": "Keyword search query",
                            },
                            "category": {
                                "type": "string",
                                "enum": ["research", "data", "compute", "agent", "utility"],
                                "description": "Optional category filter",
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 10,
                                "description": "Maximum number of results",
                            },
                        },
                        "required": [],
                    },
                    "endpoint": f"{base_url}/discover",
                    "method": "GET",
                    "payment": {
                        "amount_usd": 0.005,
                        "network": NETWORK,
                        "asset": "USDC",
                        "payTo": WALLET_ADDRESS,
                    },
                },
                {
                    "name": "register_endpoint",
                    "description": "Register a new x402-payable endpoint in the discovery registry. Free.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "url": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": ["research", "data", "compute", "agent", "utility"],
                            },
                            "price_usd": {"type": "number"},
                            "network": {"type": "string", "default": "base"},
                            "asset_address": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "description", "url", "category", "price_usd"],
                    },
                    "endpoint": f"{base_url}/register",
                    "method": "POST",
                    "payment": None,
                },
                {
                    "name": "browse_catalog",
                    "description": "Browse all registered endpoints without quality signals. Free, no payment required.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                    "endpoint": f"{base_url}/catalog",
                    "method": "GET",
                    "payment": None,
                },
                {
                    "name": "live_health_check",
                    "description": (
                        "Run a live health check on a specific endpoint — measures latency and reachability. "
                        "Costs $0.05 USDC. Requires X-PAYMENT header."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "endpoint_id": {
                                "type": "string",
                                "description": "The 'id' field from the catalog or discover response",
                            }
                        },
                        "required": ["endpoint_id"],
                    },
                    "endpoint": f"{base_url}/health/{{endpoint_id}}",
                    "method": "GET",
                    "payment": {
                        "amount_usd": 0.05,
                        "network": NETWORK,
                        "asset": "USDC",
                        "payTo": WALLET_ADDRESS,
                    },
                },
            ],
        }
    )


# ---------------------------------------------------------------------------
# Entry point for local development
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
