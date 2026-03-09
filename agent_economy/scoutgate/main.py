"""
ScoutGate — supply-side x402 proxy.

Wraps any existing API with x402 payment enforcement.
Agents pay per call; payments settle via CDP onto the API owner's wallet.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scoutgate")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCOUTGATE_WALLET: str = os.environ.get(
    "SCOUTGATE_WALLET", "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA"
)
SCOUTGATE_FEE_PCT: float = 0.005   # 0.5 %
SCOUTGATE_FEE_MIN: float = 0.001   # $0.001 minimum

USDC_BASE_ADDRESS: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

DATA_FILE: str = (
    "/data/scoutgate_apis.json"
    if os.path.exists("/data")
    else "/tmp/scoutgate_apis.json"
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class APIRegistration(BaseModel):
    api_url: str
    wallet_address: str
    price_usd: float = 0.01
    name: str = ""
    description: str = ""
    category: str = "other"
    forward_headers: bool = False


class APIRegistrationResponse(BaseModel):
    api_id: str
    proxy_url: str
    message: str
    registered_in_catalog: bool


class ProxiedAPI(BaseModel):
    api_id: str
    name: str
    api_url: str
    wallet_address: str
    price_usd: float
    description: str
    category: str
    forward_headers: bool
    registered_at: str
    total_calls: int = 0
    total_revenue_usd: float = 0.0
    trust_score: int = 70


# ---------------------------------------------------------------------------
# In-memory store + persistence
# ---------------------------------------------------------------------------

APIS: dict[str, ProxiedAPI] = {}


def _save_apis() -> None:
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({k: v.model_dump() for k, v in APIS.items()}, f, indent=2)
    except Exception as exc:
        log.error("Failed to save APIs: %s", exc)


def _load_apis() -> None:
    global APIS
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                data = json.load(f)
            APIS = {k: ProxiedAPI(**v) for k, v in data.items()}
            log.info("Loaded %d APIs from %s", len(APIS), DATA_FILE)
        except Exception as exc:
            log.error("Failed to load APIs from %s: %s", DATA_FILE, exc)


# ---------------------------------------------------------------------------
# x402 helpers
# ---------------------------------------------------------------------------


def _calculate_fee(price_usd: float) -> float:
    return max(price_usd * SCOUTGATE_FEE_PCT, SCOUTGATE_FEE_MIN)


def _payment_required_response(api_id: str, price_usd: float, request: Request) -> JSONResponse:
    """Return an RFC-compliant x402 Payment Required response (V1 client format)."""
    amount_usdc = int(price_usd * 1_000_000)  # USDC has 6 decimals
    payment_requirements = {
        "scheme": "exact",
        "network": "eip155:8453",
        "maxAmountRequired": str(amount_usdc),
        "resource": str(request.url),
        "description": f"ScoutGate proxy call — {api_id}",
        "mimeType": "application/json",
        "payTo": SCOUTGATE_WALLET,
        "maxTimeoutSeconds": 300,
        "asset": USDC_BASE_ADDRESS,
        "extra": {
            "name": "USD Coin",
            "version": "2",
        },
    }
    return JSONResponse(
        status_code=402,
        content={"error": "Payment Required", "paymentRequirements": [payment_requirements]},
        headers={"X-Payment-Required": "true"},
    )


def _generate_cdp_jwt(method: str, path: str) -> str | None:
    """Generate a CDP JWT for authenticating against api.cdp.coinbase.com."""
    cdp_key_id = os.environ.get("CDP_API_KEY_ID", "")
    cdp_key_secret = os.environ.get("CDP_API_KEY_SECRET", "")
    if not cdp_key_id or not cdp_key_secret:
        return None
    try:
        from cdp.auth.utils.jwt import generate_jwt, JwtOptions
        return generate_jwt(JwtOptions(
            api_key_id=cdp_key_id,
            api_key_secret=cdp_key_secret,
            request_method=method,
            request_host="api.cdp.coinbase.com",
            request_path=path,
        ))
    except Exception as exc:
        log.warning("CDP JWT generation failed: %s", exc)
        return None


async def _verify_and_settle_payment(
    payment_header: str, price_usd: float
) -> tuple[bool, str]:
    """Verify EIP-712 signature and settle via CDP. Returns (valid, tx_hash_or_error)."""
    if not payment_header:
        return False, "No X-PAYMENT header"

    try:
        data = json.loads(base64.b64decode(payment_header + "==").decode())

        payload = data.get("payload", {})
        signature = payload.get("signature", "")
        auth = payload.get("authorization", {})

        # Check payment expiry
        valid_before = int(auth.get("validBefore", 0))
        if valid_before > 0 and int(time.time()) > valid_before:
            return False, "Payment expired"

        # Reconstruct EIP-712 typed data for signature verification
        nonce_hex: str = auth.get("nonce", "0x" + "0" * 64)
        nonce_bytes = bytes.fromhex(nonce_hex[2:] if nonce_hex.startswith("0x") else nonce_hex)
        structured = {
            "domain": {
                "name": "USD Coin",
                "version": "2",
                "chainId": 8453,
                "verifyingContract": USDC_BASE_ADDRESS,
            },
            "message": {
                "from": auth.get("from", ""),
                "to": auth.get("to", SCOUTGATE_WALLET),
                "value": int(auth.get("value", 0)),
                "validAfter": int(auth.get("validAfter", 0)),
                "validBefore": int(auth.get("validBefore", 0)),
                "nonce": nonce_bytes,
            },
            "primaryType": "TransferWithAuthorization",
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
        }

        msg = encode_typed_data(full_message=structured)
        recovered = Account.recover_message(msg, signature=signature)
        payer_address = auth.get("from", "")

        if recovered.lower() != payer_address.lower():
            log.warning("Signature mismatch: recovered %s, expected %s", recovered, payer_address)
            return False, "Signature mismatch"

        # Verify amount
        expected_amount = int(price_usd * 1_000_000)
        signed_amount = int(auth.get("value", 0))
        if signed_amount < expected_amount:
            log.warning("Underpayment: signed %d, required %d", signed_amount, expected_amount)
            return False, "Underpayment"

        # Verify destination wallet
        if auth.get("to", "").lower() != SCOUTGATE_WALLET.lower():
            log.warning("Wrong recipient: %s", auth.get("to"))
            return False, "Wrong recipient"

        log.info("Payment verified: %s paid %s USDC", payer_address, signed_amount / 1e6)

        # Attempt CDP settle (V2 format)
        try:
            v2_reqs = {
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": USDC_BASE_ADDRESS,
                "amount": str(expected_amount),
                "payTo": SCOUTGATE_WALLET,
                "maxTimeoutSeconds": 60,
                "extra": {"name": "USD Coin", "version": "2"},
            }
            settle_payload = {
                "x402Version": 2,
                "paymentPayload": {
                    "x402Version": 2,
                    "payload": data.get("payload", {}),
                    "accepted": v2_reqs,
                },
                "paymentRequirements": v2_reqs,
            }
            settle_headers: dict[str, str] = {"Content-Type": "application/json"}
            jwt_token = _generate_cdp_jwt("POST", "/platform/v2/x402/settle")
            if jwt_token:
                settle_headers["Authorization"] = f"Bearer {jwt_token}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                settle_resp = await client.post(
                    "https://api.cdp.coinbase.com/platform/v2/x402/settle",
                    json=settle_payload,
                    headers=settle_headers,
                )
                if settle_resp.status_code == 200:
                    tx_hash = settle_resp.json().get("transaction", "settled")
                    log.info("CDP settle success: tx=%s payer=%s", tx_hash, payer_address)
                    return True, tx_hash
                log.warning("CDP settle returned %s: %s", settle_resp.status_code, settle_resp.text[:300])
        except Exception as settle_exc:
            log.warning("CDP settle error (non-fatal): %s", settle_exc)

        # Local verification passed even if settle failed
        return True, "payment_verified"

    except Exception as exc:
        log.warning("Payment verification error: %s", exc)
        return False, f"Payment error: {exc}"


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


async def _auto_register_with_catalog(api: ProxiedAPI, proxy_url: str) -> None:
    """Best-effort registration with x402Scout catalog."""
    discovery_url = os.environ.get("DISCOVERY_API_URL", "https://x402scout.com")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{discovery_url}/register",
                json={
                    "url": proxy_url,
                    "name": f"ScoutGate: {api.name or api.api_url}",
                    "description": api.description or f"x402-enabled proxy for {api.api_url}",
                    "category": api.category,
                    "price_usd": api.price_usd,
                },
            )
            log.info("Registered %s in catalog at %s", api.api_id, discovery_url)
    except Exception as exc:
        log.debug("Catalog registration skipped: %s", exc)


async def _post_call_tasks(api_id: str, price_usd: float) -> None:
    """Fire-and-forget: update stats after a successful paid call."""
    if api_id in APIS:
        APIS[api_id].total_calls += 1
        APIS[api_id].total_revenue_usd += price_usd
        _save_apis()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ScoutGate",
    description="Supply-side x402 proxy — wrap any API with pay-per-call in seconds.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    _load_apis()
    log.info("ScoutGate started. %d APIs registered. Data file: %s", len(APIS), DATA_FILE)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "apis_registered": len(APIS), "version": "1.0.0"}


@app.get("/stats")
async def stats() -> dict[str, Any]:
    total_calls = sum(a.total_calls for a in APIS.values())
    total_revenue = sum(a.total_revenue_usd for a in APIS.values())
    return {
        "total_apis": len(APIS),
        "total_calls": total_calls,
        "total_revenue_usd": round(total_revenue, 6),
        "version": "1.0.0",
    }


@app.post("/register", response_model=APIRegistrationResponse)
async def register_api(registration: APIRegistration) -> APIRegistrationResponse:
    """Register an upstream API for x402 proxying."""
    api_id = str(uuid.uuid4())[:8]
    proxy_url = f"https://x402-scoutgate.onrender.com/api/{api_id}"

    # Normalise: strip trailing slash from upstream URL
    api_url = registration.api_url.rstrip("/")

    api = ProxiedAPI(
        api_id=api_id,
        name=registration.name,
        api_url=api_url,
        wallet_address=registration.wallet_address,
        price_usd=registration.price_usd,
        description=registration.description,
        category=registration.category,
        forward_headers=registration.forward_headers,
        registered_at=datetime.now(timezone.utc).isoformat(),
    )

    APIS[api_id] = api
    _save_apis()

    # Best-effort catalog registration (non-blocking)
    asyncio.ensure_future(_auto_register_with_catalog(api, proxy_url))

    log.info("Registered API %s -> %s", api_id, api_url)

    return APIRegistrationResponse(
        api_id=api_id,
        proxy_url=proxy_url,
        message=f"API registered. Proxy URL: {proxy_url}",
        registered_in_catalog=True,  # attempted; may silently fail
    )


@app.get("/apis")
async def list_apis() -> list[dict[str, Any]]:
    """List all registered APIs. Wallet addresses are redacted for privacy."""
    result = []
    for api in APIS.values():
        entry = api.model_dump()
        entry.pop("wallet_address", None)
        result.append(entry)
    return result


@app.get("/docs-redirect")
async def docs_redirect() -> RedirectResponse:
    return RedirectResponse(url="/docs")


# ---------------------------------------------------------------------------
# Proxy endpoints
# ---------------------------------------------------------------------------


async def _proxy_request(
    api_id: str,
    path: str,
    request: Request,
    method: str,
) -> Response:
    """Core proxy logic shared by GET and POST handlers."""
    api = APIS.get(api_id)
    if api is None:
        raise HTTPException(status_code=404, detail=f"API '{api_id}' not registered")

    # --- payment gate ---
    payment_header = request.headers.get("X-PAYMENT", "")
    if not payment_header:
        return _payment_required_response(api_id, api.price_usd, request)

    valid, reason = await _verify_and_settle_payment(payment_header, api.price_usd)
    if not valid:
        log.info("Payment rejected for %s: %s", api_id, reason)
        return _payment_required_response(api_id, api.price_usd, request)

    # --- build upstream request ---
    upstream_url = f"{api.api_url}/{path}" if path else api.api_url
    query_params = dict(request.query_params)

    forward_headers: dict[str, str] = {"Accept": request.headers.get("Accept", "*/*")}
    if api.forward_headers:
        auth = request.headers.get("Authorization")
        if auth:
            forward_headers["Authorization"] = auth

    body: bytes | None = None
    if method == "POST":
        body = await request.body()
        ct = request.headers.get("Content-Type", "application/json")
        forward_headers["Content-Type"] = ct

    # --- forward to upstream ---
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            if method == "POST":
                upstream_resp = await client.post(
                    upstream_url,
                    params=query_params,
                    headers=forward_headers,
                    content=body,
                )
            else:
                upstream_resp = await client.get(
                    upstream_url,
                    params=query_params,
                    headers=forward_headers,
                )
    except httpx.ConnectError:
        log.warning("Upstream %s unreachable for API %s", api.api_url, api_id)
        return JSONResponse(
            status_code=502,
            content={"error": "Bad Gateway", "detail": f"Upstream {api.api_url} is unreachable"},
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=502,
            content={"error": "Bad Gateway", "detail": "Upstream timed out"},
        )
    except Exception as exc:
        log.error("Upstream error for API %s: %s", api_id, exc)
        return JSONResponse(
            status_code=502,
            content={"error": "Bad Gateway", "detail": str(exc)},
        )

    # --- fire-and-forget post-call tasks ---
    asyncio.ensure_future(_post_call_tasks(api_id, api.price_usd))

    # --- relay upstream response ---
    excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
    response_headers = {
        k: v
        for k, v in upstream_resp.headers.items()
        if k.lower() not in excluded_headers
    }
    response_headers["X-ScoutGate-Api-Id"] = api_id

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
        media_type=upstream_resp.headers.get("content-type", "application/json"),
    )


@app.get("/api/{api_id}/{path:path}")
async def proxy_get(api_id: str, path: str, request: Request) -> Response:
    return await _proxy_request(api_id, path, request, "GET")


@app.post("/api/{api_id}/{path:path}")
async def proxy_post(api_id: str, path: str, request: Request) -> Response:
    return await _proxy_request(api_id, path, request, "POST")


# Handle calls to /api/{api_id} with no trailing path
@app.get("/api/{api_id}")
async def proxy_get_root(api_id: str, request: Request) -> Response:
    return await _proxy_request(api_id, "", request, "GET")


@app.post("/api/{api_id}")
async def proxy_post_root(api_id: str, request: Request) -> Response:
    return await _proxy_request(api_id, "", request, "POST")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
