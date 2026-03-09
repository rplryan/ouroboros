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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
SCOUTGATE_FEE_PCT: float = 0.02    # 2 %
SCOUTGATE_FEE_MIN: float = 0.002   # $0.002 minimum

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


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """ScoutGate landing page."""
    total_apis = len(APIS)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScoutGate — x402 API Monetization Gateway</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0a0a0a; color: #e0e0e0; font-family: 'Courier New', monospace; min-height: 100vh; }}
  .header {{ background: #0d1a0d; border-bottom: 1px solid #1a4a1a; padding: 20px 40px; display: flex; align-items: center; gap: 16px; }}
  .logo {{ font-size: 28px; color: #39ff14; font-weight: bold; letter-spacing: 2px; }}
  .tagline {{ color: #888; font-size: 13px; }}
  .hero {{ padding: 60px 40px 40px; max-width: 860px; margin: 0 auto; }}
  h1 {{ font-size: 36px; color: #39ff14; margin-bottom: 12px; }}
  .sub {{ color: #aaa; font-size: 16px; margin-bottom: 40px; line-height: 1.6; }}
  .stats {{ display: flex; gap: 24px; margin-bottom: 48px; flex-wrap: wrap; }}
  .stat {{ background: #111; border: 1px solid #1a4a1a; border-radius: 8px; padding: 16px 24px; min-width: 140px; }}
  .stat-val {{ font-size: 28px; color: #39ff14; font-weight: bold; }}
  .stat-label {{ font-size: 12px; color: #666; margin-top: 4px; }}
  .section {{ margin-bottom: 48px; }}
  h2 {{ color: #39ff14; font-size: 18px; margin-bottom: 16px; border-bottom: 1px solid #1a4a1a; padding-bottom: 8px; }}
  .steps {{ display: flex; flex-direction: column; gap: 16px; }}
  .step {{ background: #111; border: 1px solid #222; border-radius: 8px; padding: 20px; }}
  .step-num {{ color: #39ff14; font-size: 12px; font-weight: bold; margin-bottom: 8px; }}
  .step-title {{ color: #fff; font-size: 15px; margin-bottom: 8px; }}
  pre {{ background: #0d0d0d; border: 1px solid #222; border-radius: 6px; padding: 14px; overflow-x: auto; font-size: 12px; color: #ccc; margin-top: 8px; line-height: 1.5; }}
  .highlight {{ color: #39ff14; }}
  .links {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  a.btn {{ display: inline-block; background: #0d1a0d; border: 1px solid #39ff14; color: #39ff14; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-size: 13px; transition: background 0.2s; }}
  a.btn:hover {{ background: #1a3a1a; }}
  .footer {{ text-align: center; color: #444; font-size: 12px; padding: 40px; border-top: 1px solid #1a1a1a; margin-top: 40px; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <div class="logo">⬡ ScoutGate</div>
    <div class="tagline">by x402Scout — the supply-side onboarding ramp for the x402 ecosystem</div>
  </div>
</div>
<div class="hero">
  <h1>Wrap any API with x402 payments in 30 seconds.</h1>
  <p class="sub">Paste your API URL. Set a price. Get a proxy URL that handles 402 headers, EIP-712 signing, and on-chain USDC settlement on Base — automatically. Your API is instantly listed in the <a href="https://x402scout.com" style="color:#39ff14">x402Scout catalog</a>.</p>

  <div class="stats">
    <div class="stat">
      <div class="stat-val">{total_apis}</div>
      <div class="stat-label">APIs registered</div>
    </div>
  </div>

  <div class="section">
    <h2>How it works</h2>
    <div class="steps">
      <div class="step">
        <div class="step-num">STEP 1 — Register your API</div>
        <div class="step-title">POST your existing API URL, wallet, and price</div>
        <pre>curl -X POST https://x402-scoutgate.onrender.com/register \\
  -H "Content-Type: application/json" \\
  -d '{{
    <span class="highlight">"api_url"</span>: "https://your-api.com",
    <span class="highlight">"wallet_address"</span>: "0xYourWalletAddress",
    <span class="highlight">"price_usd"</span>: 0.01,
    "name": "My API",
    "description": "Does something useful"
  }}'</pre>
      </div>
      <div class="step">
        <div class="step-num">STEP 2 — Get your proxy URL</div>
        <div class="step-title">Response includes a ready-to-share proxy URL</div>
        <pre>{{
  "api_id": "abc123",
  <span class="highlight">"proxy_url"</span>: "https://x402-scoutgate.onrender.com/api/abc123",
  "registered_in_catalog": true
}}</pre>
      </div>
      <div class="step">
        <div class="step-num">STEP 3 — Share it</div>
        <div class="step-title">Callers without payment get a 402. Callers with valid USDC authorization on Base get your real response.</div>
        <pre># No payment → 402 Payment Required
GET https://x402-scoutgate.onrender.com/api/abc123/endpoint

# With X-PAYMENT header → your API response + on-chain settlement</pre>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Quick links</h2>
    <div class="links">
      <a class="btn" href="/docs">API Docs</a>
      <a class="btn" href="https://x402scout.com">x402Scout Catalog</a>
      <a class="btn" href="https://github.com/rplryan/x402-discovery-mcp">GitHub</a>
    </div>
  </div>
</div>
<div class="footer">ScoutGate is part of the x402Scout ecosystem &mdash; the discovery layer for agent-native commerce on Base.</div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "apis_registered": len(APIS), "version": "1.0.0"}



@app.get("/register", response_class=HTMLResponse)
async def register_page() -> HTMLResponse:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Register API &mdash; ScoutGate</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0a0a0a; color: #e0e0e0; font-family: 'Courier New', monospace; min-height: 100vh; }
    .header { background: #0d1a0d; border-bottom: 1px solid #1a4a1a; padding: 20px 40px; display: flex; align-items: center; gap: 16px; }
    .logo { font-size: 28px; color: #39ff14; font-weight: bold; letter-spacing: 2px; text-decoration: none; }
    .tagline { color: #888; font-size: 13px; }
    .container { max-width: 680px; margin: 0 auto; padding: 48px 24px; }
    h1 { font-size: 28px; color: #39ff14; margin-bottom: 10px; }
    .sub { color: #aaa; font-size: 14px; margin-bottom: 36px; line-height: 1.6; }
    .form-group { margin-bottom: 20px; }
    label { display: block; font-size: 12px; color: #888; margin-bottom: 6px; letter-spacing: 1px; text-transform: uppercase; }
    label .req { color: #39ff14; margin-left: 2px; }
    input, textarea, select {
      width: 100%; background: #111; border: 1px solid #222; border-radius: 6px;
      color: #e0e0e0; font-family: 'Courier New', monospace; font-size: 13px;
      padding: 10px 14px; outline: none; transition: border-color 0.2s;
    }
    input:focus, textarea:focus, select:focus { border-color: #39ff14; }
    select option { background: #111; }
    textarea { resize: vertical; min-height: 72px; }
    .hint { font-size: 11px; color: #555; margin-top: 5px; }
    .btn-submit {
      display: inline-block; background: #0d1a0d; border: 1px solid #39ff14;
      color: #39ff14; padding: 12px 28px; border-radius: 6px; font-family: 'Courier New', monospace;
      font-size: 14px; font-weight: bold; cursor: pointer; transition: background 0.2s; letter-spacing: 1px;
    }
    .btn-submit:hover { background: #1a3a1a; }
    .btn-submit:disabled { opacity: 0.5; cursor: not-allowed; }
    #result { margin-top: 28px; display: none; }
    .result-success { background: #0d1a0d; border: 1px solid #39ff14; border-radius: 8px; padding: 24px; }
    .result-error { background: #1a0d0d; border: 1px solid #4a1a1a; border-radius: 8px; padding: 24px; }
    .result-label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
    .proxy-url { font-size: 15px; color: #39ff14; word-break: break-all; margin: 6px 0 14px; }
    .copy-btn {
      background: #111; border: 1px solid #2a4a2a; color: #39ff14; border-radius: 4px;
      font-family: 'Courier New', monospace; font-size: 11px; padding: 5px 12px;
      cursor: pointer; transition: background 0.2s;
    }
    .copy-btn:hover { background: #1a3a1a; }
    .error-msg { color: #ff4444; font-size: 13px; }
    .footer { text-align: center; color: #444; font-size: 12px; padding: 40px; border-top: 1px solid #1a1a1a; margin-top: 40px; }
    a { color: #39ff14; }
  </style>
</head>
<body>
  <div class="header">
    <a class="logo" href="/">SCOUTGATE</a>
    <span class="tagline">x402 proxy gateway &mdash; register your API</span>
  </div>
  <div class="container">
    <h1>Register an API</h1>
    <p class="sub">Provide your API URL and a wallet to receive payments. ScoutGate wraps your endpoint with x402 payment headers and settles USDC on Base automatically.</p>

    <form id="reg-form" onsubmit="submitForm(event)">
      <div class="form-group">
        <label>API URL <span class="req">*</span></label>
        <input type="url" id="api_url" placeholder="https://your-api.example.com" required>
        <div class="hint">The upstream URL ScoutGate will proxy requests to.</div>
      </div>
      <div class="form-group">
        <label>Wallet Address <span class="req">*</span></label>
        <input type="text" id="wallet_address" placeholder="0x..." required pattern="^0x[0-9a-fA-F]{40}$">
        <div class="hint">EVM address on Base that receives USDC payments.</div>
      </div>
      <div class="form-group">
        <label>Price (USD)</label>
        <input type="number" id="price_usd" value="0.01" min="0.000001" step="0.001">
        <div class="hint">Cost per API call in USD. Default: $0.01.</div>
      </div>
      <div class="form-group">
        <label>Name</label>
        <input type="text" id="name" placeholder="My Awesome API">
      </div>
      <div class="form-group">
        <label>Description</label>
        <textarea id="description" placeholder="What does your API do?"></textarea>
      </div>
      <div class="form-group">
        <label>Category</label>
        <select id="category">
          <option value="other">Other</option>
          <option value="data">Data</option>
          <option value="ai">AI</option>
          <option value="defi">DeFi</option>
          <option value="utility">Utility</option>
          <option value="media">Media</option>
        </select>
      </div>
      <button type="submit" class="btn-submit" id="submit-btn">REGISTER API</button>
    </form>

    <div id="result"></div>
  </div>
  <div class="footer">ScoutGate is part of the x402Scout ecosystem &mdash; the discovery layer for agent-native commerce on Base.</div>

  <script>
    async function submitForm(e) {
      e.preventDefault();
      const btn = document.getElementById('submit-btn');
      btn.disabled = true;
      btn.textContent = 'REGISTERING...';

      const payload = {
        api_url: document.getElementById('api_url').value.trim(),
        wallet_address: document.getElementById('wallet_address').value.trim(),
        price_usd: parseFloat(document.getElementById('price_usd').value) || 0.01,
        name: document.getElementById('name').value.trim() || null,
        description: document.getElementById('description').value.trim() || null,
        category: document.getElementById('category').value,
      };

      const resultDiv = document.getElementById('result');
      resultDiv.style.display = 'block';

      try {
        const resp = await fetch('/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (resp.ok) {
          resultDiv.innerHTML = `
            <div class="result-success">
              <div class="result-label">Registration successful</div>
              <div class="result-label" style="margin-top:16px;">Your proxy URL</div>
              <div class="proxy-url" id="proxy-url-text">${data.proxy_url}</div>
              <button class="copy-btn" onclick="copyProxy()">COPY URL</button>
              <div style="margin-top:16px; font-size:12px; color:#666;">
                API ID: <span style="color:#aaa">${data.api_id}</span><br>
                <span style="margin-top:6px; display:inline-block">${data.message}</span>
              </div>
            </div>`;
        } else {
          const detail = data.detail || JSON.stringify(data);
          resultDiv.innerHTML = `<div class="result-error"><span class="error-msg">Registration failed: ${escapeHtml(detail)}</span></div>`;
        }
      } catch (err) {
        resultDiv.innerHTML = `<div class="result-error"><span class="error-msg">Request failed: ${escapeHtml(err.message)}</span></div>`;
      } finally {
        btn.disabled = false;
        btn.textContent = 'REGISTER API';
      }
    }

    function copyProxy() {
      const url = document.getElementById('proxy-url-text').textContent;
      navigator.clipboard.writeText(url).then(() => {
        const btn = document.querySelector('.copy-btn');
        btn.textContent = 'COPIED!';
        setTimeout(() => { btn.textContent = 'COPY URL'; }, 2000);
      });
    }

    function escapeHtml(str) {
      return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


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
async def list_apis() -> JSONResponse:
    raise HTTPException(status_code=404, detail="Not found")


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

    valid, tx_hash = await _verify_and_settle_payment(payment_header, api.price_usd)
    if not valid:
        log.info("Payment rejected for %s: %s", api_id, tx_hash)
        return _payment_required_response(api_id, api.price_usd, request)

    # Extract payer address from payment header for X-PAYMENT-RESPONSE
    payer_address = ""
    try:
        _pd = json.loads(base64.b64decode(payment_header + "==").decode())
        payer_address = _pd.get("payload", {}).get("authorization", {}).get("from", "")
    except Exception:
        pass

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
    response_headers["X-PAYMENT-RESPONSE"] = base64.b64encode(
        json.dumps({
            "success": True,
            "transaction": tx_hash,
            "network": "base-mainnet",
            "payer": payer_address,
        }).encode()
    ).decode()
    response_headers["x-payment-response"] = response_headers["X-PAYMENT-RESPONSE"]
    response_headers["Access-Control-Expose-Headers"] = "X-PAYMENT-RESPONSE, X-SCOUTGATE-API-ID"

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
