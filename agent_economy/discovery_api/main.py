"""x402 Service Discovery API
Agents query it to discover available services.
Each discovery query costs $0.010 USDC on Base.

Wallet: 0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA
Network: Base (Ethereum L2)
Asset: USDC (0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913)
"""

# from __future__ import annotations  # removed: causes FastAPI OpenAPI schema generation failure

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

load_dotenv()

# Try to import scraper (optional dependency)
try:
    from scraper import scrape_x402scan
except ImportError:
    async def scrape_x402scan() -> list[dict]:  # type: ignore[misc]
        return []

# Try to import ecosystem scraper (optional dependency)
try:
    from ecosystem_scraper import run_ecosystem_scan
except ImportError:
    async def run_ecosystem_scan(existing_urls: set) -> list[dict]:  # type: ignore[misc]
        return []

# Try to import Streamable HTTP MCP builder (optional dependency)
try:
    from mcp_streamable import build_streamable_mcp_app
except ImportError:
    def build_streamable_mcp_app(*args, **kwargs):  # type: ignore[misc]
        return None, None

# Try to import attestation module (optional dependency)
try:
    from attestation import get_jwks, build_attestation, is_configured as attest_configured, fetch_chain_verifications, KNOWN_TRUST_PROVIDERS
except ImportError:
    def get_jwks() -> dict: return {"keys": []}  # type: ignore[misc]
    def build_attestation(*args, **kwargs): return None  # type: ignore[misc]
    def attest_configured() -> bool: return False  # type: ignore[misc]
    async def fetch_chain_verifications(*args, **kwargs): return []  # type: ignore[misc]
    KNOWN_TRUST_PROVIDERS: list = []  # type: ignore[misc]

try:
    from oauth import router as oauth_router
    _OAUTH_AVAILABLE = True
except Exception:
    oauth_router = None
    _OAUTH_AVAILABLE = False
# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WALLET_ADDRESS: str = os.getenv(
    "WALLET_ADDRESS", "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA"
)
NETWORK: str = os.getenv("NETWORK", "base")
USDC_CONTRACT: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

QUERY_PRICE_UNITS: str = os.getenv("QUERY_PRICE_USDC_UNITS", "10000")       # $0.010
HEALTH_PRICE_UNITS: str = os.getenv("HEALTH_CHECK_PRICE_USDC_UNITS", "50000")  # $0.05 (reserved)

FACILITATOR_URL: str = os.getenv(
    "FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402/verify"
)
PAYAI_FACILITATOR_URL: str = "https://facilitator.payai.network/verify"
PAYAI_REGISTER_URL: str = "https://facilitator.payai.network/register-merchant"

# ---------------------------------------------------------------------------
# Facilitator registry — known x402 facilitators
# ---------------------------------------------------------------------------

KNOWN_FACILITATORS: list[dict] = [
    {
        "name": "Coinbase",
        "slug": "coinbase",
        "url": "https://x402.org/facilitator",
        "verify_url": "https://x402.org/facilitator/verify",
        "settle_url": "https://x402.org/facilitator/settle",
        "health_url": "https://x402.org/facilitator",
        "supported_networks": ["eip155:8453", "eip155:84532", "solana:5eykt4", "solana:EtWTRA"],
        "network_aliases": {"base": "eip155:8453", "base-sepolia": "eip155:84532"},
        "supported_schemes": ["exact"],
        "fee_info": "Free for first 1000 tx/month on Base, then $0.001/tx",
        "description": "Official Coinbase CDP facilitator — Base mainnet + Sepolia, Solana",
        "docs_url": "https://docs.cdp.coinbase.com/x402",
    },
    {
        "name": "PayAI",
        "slug": "payai",
        "url": "https://facilitator.payai.network",
        "verify_url": "https://facilitator.payai.network/verify",
        "settle_url": "https://facilitator.payai.network/settle",
        "health_url": "https://facilitator.payai.network",
        "supported_networks": [
            "eip155:8453",    # Base
            "eip155:137",     # Polygon
            "eip155:43114",   # Avalanche
            "eip155:4689",    # IoTeX
            "eip155:1313161554",  # Aurora (NEAR)
            "solana:5eykt4",  # Solana mainnet
            "eip155:1482601649",  # SKALE
        ],
        "network_aliases": {"base": "eip155:8453", "polygon": "eip155:137", "solana": "solana:5eykt4"},
        "supported_schemes": ["exact"],
        "fee_info": "Free tier available; see facilitator.payai.network for pricing",
        "description": "Multi-chain facilitator — 15+ networks including Base, Polygon, Solana, Avalanche",
        "docs_url": "https://payai.network/docs",
    },
    {
        "name": "RelAI",
        "slug": "relai",
        "url": "https://facilitator.x402.fi",
        "verify_url": "https://facilitator.x402.fi/verify",
        "settle_url": "https://facilitator.x402.fi/settle",
        "health_url": "https://facilitator.x402.fi",
        "supported_networks": [
            "eip155:8453",        # Base
            "eip155:43114",       # Avalanche
            "eip155:1482601649",  # SKALE
            "solana:5eykt4",      # Solana mainnet
        ],
        "network_aliases": {"base": "eip155:8453", "avalanche": "eip155:43114"},
        "supported_schemes": ["exact"],
        "fee_info": "Contact for pricing",
        "description": "RelAI facilitator — Base, SKALE, Avalanche, Solana",
        "docs_url": "https://x402.fi",
    },
    {
        "name": "xpay",
        "slug": "xpay",
        "url": "https://facilitator.xpay.sh",
        "verify_url": "https://facilitator.xpay.sh/verify",
        "settle_url": "https://facilitator.xpay.sh/settle",
        "health_url": "https://facilitator.xpay.sh/health",
        "supported_networks": [
            "eip155:8453",    # Base mainnet
            "eip155:84532",   # Base Sepolia
        ],
        "network_aliases": {"base": "eip155:8453", "base-sepolia": "eip155:84532"},
        "supported_schemes": ["exact"],
        "fee_info": "Contact for pricing",
        "description": "xpay facilitator — Base Mainnet + Sepolia",
        "docs_url": "https://xpay.sh",
    },
]

# Precompute a set of all (network, scheme) pairs that have facilitator coverage
# Used for O(1) lookup in _enrich_with_facilitator()
_FACILITATOR_NETWORK_INDEX: dict[str, list[dict]] = {}  # network -> list of facilitators
for _f in KNOWN_FACILITATORS:
    for _net in _f["supported_networks"]:
        _FACILITATOR_NETWORK_INDEX.setdefault(_net, []).append(_f)
    for _alias, _net in _f.get("network_aliases", {}).items():
        pass  # aliases already covered by supported_networks canonical forms


def _normalize_network(network: str) -> str:
    """Normalize network string to canonical EIP-155 or Solana chain ID format."""
    _alias_map = {
        "base": "eip155:8453",
        "base-mainnet": "eip155:8453",
        "base_mainnet": "eip155:8453",
        "base-sepolia": "eip155:84532",
        "polygon": "eip155:137",
        "avalanche": "eip155:43114",
        "solana": "solana:5eykt4",
        "solana-mainnet": "solana:5eykt4",
    }
    normalized = network.lower().strip()
    return _alias_map.get(normalized, normalized)


def _get_facilitators_for_network(network: str, scheme: str = "exact") -> list[dict]:
    """Return list of known facilitators that support the given network+scheme."""
    canonical = _normalize_network(network)
    candidates = _FACILITATOR_NETWORK_INDEX.get(canonical, [])
    # Filter by scheme
    return [f for f in candidates if scheme in f.get("supported_schemes", ["exact"])]


async def _check_facilitator_health(facilitator: dict, timeout: float = 3.0) -> dict:
    """Ping a facilitator's health URL with a 3s timeout. Returns enriched dict with health_status."""
    result = dict(facilitator)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            t0 = time.monotonic()
            resp = await client.get(facilitator["health_url"], follow_redirects=True)
            latency_ms = int((time.monotonic() - t0) * 1000)
        result["health_status"] = "up" if resp.status_code < 500 else "degraded"
        result["health_latency_ms"] = latency_ms
        result["health_http_status"] = resp.status_code
    except Exception as exc:
        result["health_status"] = "unknown"
        result["health_latency_ms"] = None
        result["health_http_status"] = None
        result["health_error"] = str(exc)[:120]
    return result


def _enrich_with_facilitator(entry: dict) -> dict:
    """Add facilitator_compatible and recommended_facilitator fields to a service entry."""
    network = entry.get("network", "base")
    canonical_net = _normalize_network(network)
    compatible_facilitators = _get_facilitators_for_network(canonical_net)
    enriched = dict(entry)
    if compatible_facilitators:
        enriched["facilitator_compatible"] = True
        enriched["recommended_facilitator"] = compatible_facilitators[0]["url"]
        enriched["facilitator_count"] = len(compatible_facilitators)
    else:
        enriched["facilitator_compatible"] = False
        enriched["recommended_facilitator"] = None
        enriched["facilitator_count"] = 0
    return enriched

SERVICE_BASE_URL: str = os.getenv(
    "SERVICE_BASE_URL", "https://x402scout.com"
)

REGISTRY_PATH: Path = Path(__file__).parent / "registry.json"
DB_PATH: Path = Path(__file__).parent / "health.db"

HEALTH_CHECK_INTERVAL_SECS: int = 900  # 15 minutes
SCRAPE_INTERVAL_SECS: int = 21600  # 6 hours

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("x402-discovery")

# ---------------------------------------------------------------------------
# SQLite health DB
# ---------------------------------------------------------------------------

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_url TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                is_up INTEGER NOT NULL,
                latency_ms INTEGER,
                http_status INTEGER
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_endpoint_health_url ON endpoint_health(endpoint_url)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL,
                called INTEGER NOT NULL,
                result TEXT NOT NULL,
                latency_ms INTEGER,
                reported_at TEXT NOT NULL
            )
        """)


def _record_health(url: str, is_up: bool, latency_ms: int | None, http_status: int | None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO endpoint_health (endpoint_url, checked_at, is_up, latency_ms, http_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, datetime.now(timezone.utc).isoformat(), int(is_up), latency_ms, http_status),
        )


def _get_health_stats(url: str) -> dict:
    cutoff_ts = time.time() - 7 * 86400
    cutoff_str = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT is_up, latency_ms FROM endpoint_health "
            "WHERE endpoint_url = ? AND checked_at >= ?",
            (url, cutoff_str),
        ).fetchall()
    if not rows:
        return {"uptime_pct": None, "avg_latency_ms": None, "total_checks": 0, "successful_checks": 0}
    total = len(rows)
    successful = sum(1 for r in rows if r[0])
    latencies = [r[1] for r in rows if r[1] is not None]
    return {
        "uptime_pct": round(successful / total * 100, 1),
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "total_checks": total,
        "successful_checks": successful,
    }


def _get_last_check(url: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT checked_at, is_up, latency_ms, http_status FROM endpoint_health "
            "WHERE endpoint_url = ? ORDER BY checked_at DESC LIMIT 1",
            (url,),
        ).fetchone()
    if not row:
        return None
    return {"checked_at": row[0], "is_up": bool(row[1]), "latency_ms": row[2], "http_status": row[3]}


def _compute_health_status(stats: dict, last_check: dict | None) -> str:
    if stats["total_checks"] == 0 or last_check is None:
        return "unverified"
    uptime = stats.get("uptime_pct")
    if uptime is not None and uptime >= 95:
        return "verified_up"
    if uptime is not None and uptime < 80:
        return "degraded"
    return "unverified"


def _compute_trust_score_from_fields(entry: dict, stats: dict) -> int:
    """Compute 0-100 Trust Score from enriched entry + health stats.

    Scoring:
      Uptime (40): uptime_pct/100 * 40
      Latency (20): <200ms=20, <500ms=15, <1000ms=10, else=5, None=10
      Verification (20): checks>=10=20, >=3=10, >=1=5, 0=0
      Facilitator (10): compatible=10
      Source (10): first-party=10, manual=8, ecosystem=6, else=4
    """
    score = 0
    uptime = stats.get("uptime_pct")
    score += round(uptime / 100.0 * 40) if uptime is not None else 0
    avg_lat = stats.get("avg_latency_ms")
    if avg_lat is None:
        score += 10
    elif avg_lat < 200:
        score += 20
    elif avg_lat < 500:
        score += 15
    elif avg_lat < 1000:
        score += 10
    else:
        score += 5
    total_checks = stats.get("total_checks", 0)
    if total_checks >= 10:
        score += 20
    elif total_checks >= 3:
        score += 10
    elif total_checks >= 1:
        score += 5
    if entry.get("facilitator_compatible", False):
        score += 10
    source = entry.get("source", "")
    if source == "first-party":
        score += 10
    elif source == "manual":
        score += 8
    elif source == "ecosystem":
        score += 6
    else:
        score += 4
    return min(100, max(0, score))


def _enrich_with_quality(entry: dict) -> dict:
    url = entry.get("url", "")
    stats = _get_health_stats(url)
    last = _get_last_check(url)
    enriched = dict(entry)
    enriched["uptime_pct"] = stats["uptime_pct"]
    enriched["avg_latency_ms"] = stats["avg_latency_ms"]
    enriched["total_checks"] = stats["total_checks"]
    enriched["successful_checks"] = stats["successful_checks"]
    enriched["last_health_check"] = last["checked_at"] if last else None
    enriched["health_status"] = _compute_health_status(stats, last)
    # Trust Score — composite 0-100 signal (uptime + latency + verification + facilitator + source)
    enriched["trust_score"] = _compute_trust_score_from_fields(enriched, stats)
    # Add facilitator compatibility (synchronous — uses precomputed index)
    enriched = _enrich_with_facilitator(enriched)
    return enriched

# ---------------------------------------------------------------------------
# Background health checker
# ---------------------------------------------------------------------------

async def _background_health_checker() -> None:
    """Ping all registered endpoints every 5 minutes and record results in SQLite."""
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECS)
        entries = list(_registry)
        log.info("Background health check: checking %d endpoints", len(entries))
        for entry in entries:
            url = entry.get("url", "")
            if not url:
                continue
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    t0 = time.monotonic()
                    resp = await client.head(url, follow_redirects=True)
                    latency_ms = int((time.monotonic() - t0) * 1000)
                is_up = resp.status_code < 500
                http_status = resp.status_code
            except Exception as exc:
                log.debug("Health check failed for %s: %s", url, exc)
                is_up = False
                latency_ms = None
                http_status = None
            _record_health(url, is_up, latency_ms, http_status)
        # Refresh in-memory registry quality fields
        for reg_entry in _registry:
            url = reg_entry.get("url", "")
            if url:
                stats = _get_health_stats(url)
                last = _get_last_check(url)
                reg_entry["uptime_pct"] = stats["uptime_pct"]
                reg_entry["avg_latency_ms"] = stats["avg_latency_ms"]
                reg_entry["last_health_check"] = last["checked_at"] if last else None
                reg_entry["health_status"] = _compute_health_status(stats, last)
                stats_for_ts = _get_health_stats(reg_entry.get("url", ""))
                reg_entry["trust_score"] = _compute_trust_score_from_fields(reg_entry, stats_for_ts)
        _save_registry(_registry)
        log.info("Background health check complete")

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict]:
    if REGISTRY_PATH.exists():
        with REGISTRY_PATH.open() as fh:
            return json.load(fh)
    return []


def _save_registry(entries: list[dict]) -> None:
    try:
        with REGISTRY_PATH.open("w") as fh:
            json.dump(entries, fh, indent=2)
    except Exception as exc:
        log.warning("Could not save registry to disk: %s", exc)


def _guess_capability_tags_simple(name: str, description: str) -> list[str]:
    text = (name + " " + description).lower()
    tags = []
    if any(w in text for w in ["research", "search", "find", "lookup", "query"]):
        tags.append("research")
    if any(w in text for w in ["data", "price", "market", "feed", "ticker", "database"]):
        tags.append("data")
    if any(w in text for w in ["compute", "calculate", "process", "run", "execute"]):
        tags.append("compute")
    if any(w in text for w in ["monitor", "watch", "alert", "track", "notify"]):
        tags.append("monitoring")
    if any(w in text for w in ["route", "discover", "directory", "registry", "index"]):
        tags.append("routing")
    if any(w in text for w in ["verify", "validate", "check", "confirm", "attest"]):
        tags.append("verification")
    if any(w in text for w in ["generate", "create", "write", "image"]):
        tags.append("generation")
    if any(w in text for w in ["store", "save", "upload", "file", "ipfs"]):
        tags.append("storage")
    if any(w in text for w in ["translate", "convert", "transform"]):
        tags.append("translation")
    if any(w in text for w in ["classify", "categorize", "label", "tag"]):
        tags.append("classification")
    if any(w in text for w in ["extract", "parse", "scrape"]):
        tags.append("extraction")
    if any(w in text for w in ["summarize", "summary", "brief", "tldr"]):
        tags.append("summarization")
    if any(w in text for w in ["enrich", "enhance", "augment", "metadata"]):
        tags.append("enrichment")
    if any(w in text for w in ["validate", "lint", "test", "schema"]):
        if "validation" not in tags:
            tags.append("validation")
    return tags if tags else ["other"]


def _migrate_entry(entry: dict) -> dict:
    """Add missing fields to existing registry entries."""
    entry.setdefault("service_id", f"legacy/{entry.get('id', 'unknown')}")
    entry.setdefault(
        "capability_tags",
        _guess_capability_tags_simple(entry.get("name", ""), entry.get("description", "")),
    )
    entry.setdefault("input_format", "json")
    entry.setdefault("output_format", "json")
    entry.setdefault("pricing_model", "flat")
    entry.setdefault("agent_callable", True)
    entry.setdefault("auth_required", False)
    entry.setdefault("source", "manual")
    if "llm_usage_prompt" not in entry:
        entry["llm_usage_prompt"] = (
            f"To use {entry.get('name', 'this service')}, call {entry.get('url', '')} "
            f"with x402 payment of {entry.get('price_usd', 0)} USDC. "
            f"Send json input. Returns json. Description: {entry.get('description', '')}"
        )
    if "sdk_snippet_python" not in entry:
        price_units = int(entry.get("price_usd", 0.005) * 1_000_000)
        entry["sdk_snippet_python"] = (
            f'import requests\n# Call {entry.get("name", "service")}\n'
            f'resp = requests.get("{entry.get("url", "")}")\n'
            f'# Returns 402 with payment info: {price_units} USDC micro-units'
        )
    return entry


_registry: list[dict] = [_migrate_entry(e) for e in _load_registry()]

# ---------------------------------------------------------------------------
# x402 payment verification
# ---------------------------------------------------------------------------

async def verify_payment(
    payment_header: str,
    resource_url: str,
    amount: str,
) -> tuple[bool, str]:
    """Verify x402 payment locally using EIP-712 signature verification."""
    import base64
    import json as _json
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    
    try:
        # Decode the base64 payment header
        decoded = base64.b64decode(payment_header + '==')
        data = _json.loads(decoded)
        
        # Extract payment info
        scheme = data.get('scheme', '')
        network = data.get('network', '')
        if scheme != 'exact' or network != 'eip155:8453':
            return False, ''
        
        payload = data.get('payload', {})
        signature = payload.get('signature', '')
        auth = payload.get('authorization', {})
        
        # Get accepted requirements
        accepted = data.get('accepted', {})
        pay_to = accepted.get('payTo', WALLET_ADDRESS)
        asset = accepted.get('asset', USDC_CONTRACT)
        expected_amount = int(accepted.get('amount', amount))
        extra = accepted.get('extra', {})
        
        # Check timing
        valid_before = int(auth.get('validBefore', 0))
        if valid_before > 0 and int(time.time()) > valid_before:
            log.warning('Payment expired')
            return False, ''
        
        # Reconstruct EIP-712 typed data
        structured = {
            'domain': {
                'name': extra.get('name', 'USD Coin'),
                'version': extra.get('version', '2'),
                'chainId': 8453,
                'verifyingContract': asset,
            },
            'message': {
                'from': auth.get('from', ''),
                'to': auth.get('to', pay_to),
                'value': int(auth.get('value', 0)),
                'validAfter': int(auth.get('validAfter', 0)),
                'validBefore': valid_before,
                'nonce': bytes.fromhex(nonce_hex[2:]) if (nonce_hex := auth.get('nonce', '0x' + '0' * 64)).startswith('0x') else bytes.fromhex(nonce_hex),
            },
            'primaryType': 'TransferWithAuthorization',
            'types': {
                'EIP712Domain': [
                    {'name': 'name', 'type': 'string'},
                    {'name': 'version', 'type': 'string'},
                    {'name': 'chainId', 'type': 'uint256'},
                    {'name': 'verifyingContract', 'type': 'address'},
                ],
                'TransferWithAuthorization': [
                    {'name': 'from', 'type': 'address'},
                    {'name': 'to', 'type': 'address'},
                    {'name': 'value', 'type': 'uint256'},
                    {'name': 'validAfter', 'type': 'uint256'},
                    {'name': 'validBefore', 'type': 'uint256'},
                    {'name': 'nonce', 'type': 'bytes32'},
                ],
            },
        }
        
        # Recover signer address from signature
        msg = encode_typed_data(full_message=structured)
        recovered = Account.recover_message(msg, signature=signature)
        payer_address = auth.get('from', '')
        
        if recovered.lower() != payer_address.lower():
            log.warning('Signature mismatch: recovered %s, expected %s', recovered, payer_address)
            return False, ''
        
        # Verify amount matches
        signed_amount = int(auth.get('value', 0))
        if signed_amount < expected_amount:
            log.warning('Underpayment: signed %d, required %d', signed_amount, expected_amount)
            return False, ''
        
        # Verify destination
        if auth.get('to', '').lower() != WALLET_ADDRESS.lower():
            log.warning('Wrong recipient: %s', auth.get("to"))
            return False, ''
        
        # All checks passed
        log.info('Payment verified: %s paid %s USDC', payer_address, signed_amount/1e6)
        payment_response = base64.b64encode(_json.dumps({
            'success': True,
            'payer': payer_address,
            'amount': signed_amount,
            'network': 'eip155:8453'
        }).encode()).decode()
        return True, payment_response
        
    except Exception as exc:
        log.warning("Payment verification error: %s", exc)
        return False, ''


def _payment_required_body(
    host: str,
    resource_path: str,
    amount: str,
    description: str,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> dict:
    """Build a standards-compliant x402 Payment Required response body.

    Includes outputSchema for Coinbase CDP Bazaar auto-indexing.
    See: https://docs.cdp.coinbase.com/x402/docs/bazaar
    """
    entry: dict = {
        "scheme": "exact",
        "network": "base",
        "maxAmountRequired": amount,
        "resource": f"https://{host}{resource_path}",
        "description": description,
        "mimeType": "application/json",
        "payTo": WALLET_ADDRESS,
        "maxTimeoutSeconds": 60,
        "asset": USDC_CONTRACT,
        "extra": {"name": "USD Coin", "version": "2"},
    }
    if output_schema is not None:
        entry["outputSchema"] = output_schema
        # Build extensions.bazaar from outputSchema for CDP Bazaar auto-indexing
        entry["extensions"] = {
            "bazaar": {
                "info": output_schema,
                "schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "http"},
                                "method": {"type": "string", "enum": ["GET", "POST"]},
                                "queryParams": {"type": "object"},
                                "discoverable": {"type": "boolean"},
                            },
                            "required": ["type"],
                        },
                        "output": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "example": {"type": "object"},
                            },
                            "required": ["type"],
                        },
                    },
                    "required": ["input"],
                },
            }
        }
    body: dict = {
        "x402Version": 1,
        "accepts": [entry],
    }
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
    capability: Optional[str],
    limit: int,
) -> list[dict]:
    results = list(_registry)

    if category:
        results = [e for e in results if e.get("category") == category]

    if capability:
        results = [e for e in results if capability in e.get("capability_tags", [])]

    if q:
        keywords = q.lower().split()
        scored = [(e, _score_entry(e, keywords)) for e in results]
        scored = [(e, s) for e, s in scored if s > 0]
        scored.sort(key=lambda x: (x[1], x[0].get("trust_score", 0), x[0].get("query_count", 0)), reverse=True)
        results = [e for e, _ in scored]
    else:
        results.sort(key=lambda e: (e.get("trust_score", 0), e.get("uptime_pct", 0), e.get("query_count", 0)), reverse=True)

    # Enrich with quality signals from SQLite
    enriched = [_enrich_with_quality(e) for e in results[:limit * 2]]

    # Re-sort by quality: trust_score desc, uptime desc, latency asc, registered_at desc
    def quality_sort_key(e: dict):
        trust = e.get("trust_score") or 0.0
        uptime = e.get("uptime_pct") or 0.0
        latency = e.get("avg_latency_ms") or 9999
        registered = e.get("registered_at", "")
        return (-trust, -uptime, latency, [-ord(c) for c in registered[:10]])

    enriched.sort(key=quality_sort_key)
    return enriched[:limit]

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"research", "data", "compute", "agent", "utility"}

CAPABILITY_VOCABULARY = {
    "research", "data", "compute", "monitoring", "verification",
    "routing", "storage", "translation", "classification", "generation",
    "extraction", "summarization", "enrichment", "validation", "other",
}


class RegisterRequest(BaseModel):
    name: str
    description: str
    url: str
    category: str
    price_usd: float
    network: str = "base"
    asset_address: str = USDC_CONTRACT
    tags: list[str] = []
    # New optional fields (auto-populated if not provided)
    service_id: Optional[str] = None
    capability_tags: list[str] = []
    input_format: str = "json"
    output_format: str = "json"
    pricing_model: str = "flat"
    source: str = "self-registration"

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


class ReportRequest(BaseModel):
    service_id: str
    called: bool
    result: str  # "success" | "fail" | "timeout"
    latency_ms: Optional[int] = None

# ---------------------------------------------------------------------------
# Background x402scan scraper
# ---------------------------------------------------------------------------

async def _background_scraper() -> None:
    """Scrape x402scan.com and ecosystem sources every 6 hours; upsert new endpoints."""
    await asyncio.sleep(10)  # Wait for startup
    while True:
        try:
            existing_urls = {e.get("url") for e in _registry}

            # --- x402scan scraper ---
            x402scan_entries = await scrape_x402scan()
            added_x402scan = 0
            for entry in x402scan_entries:
                if entry.get("url") not in existing_urls:
                    _registry.append(_migrate_entry(entry))
                    existing_urls.add(entry.get("url"))
                    added_x402scan += 1
            if added_x402scan > 0:
                log.info("x402scan scraper: added %d new endpoints (total: %d)", added_x402scan, len(_registry))

            # --- ecosystem scraper (x402.org + awesome-x402) ---
            new_ecosystem = await run_ecosystem_scan(existing_urls)
            added_ecosystem = 0
            for entry in new_ecosystem:
                if entry.get("url") not in existing_urls:
                    _registry.append(_migrate_entry(entry))
                    existing_urls.add(entry.get("url"))
                    added_ecosystem += 1
            if added_ecosystem > 0:
                log.info("ecosystem scraper: added %d new services (total: %d)", added_ecosystem, len(_registry))

            total_added = added_x402scan + added_ecosystem
            if total_added > 0:
                _save_registry(_registry)
                log.info("Background scraper cycle complete: +%d services", total_added)

        except Exception as exc:
            log.warning("Background scraper failed: %s", exc)
        await asyncio.sleep(SCRAPE_INTERVAL_SECS)




# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------

async def _register_with_payai() -> None:
    """Advertise with PayAI facilitator network.
    
    PayAI uses crawl-based discovery: they crawl /.well-known/x402.json on services
    that advertise their facilitator URL. We confirm their API is up and log status.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://facilitator.payai.network/list")
            if resp.status_code == 200:
                data = resp.json()
                count = len(data) if isinstance(data, list) else data.get("total", "?")
                log.info("PayAI facilitator active — %s services indexed. Our /.well-known/x402.json advertises PayAI as facilitator.", count)
            else:
                log.info("PayAI facilitator responded %s — crawl-based discovery active via /.well-known/x402.json", resp.status_code)
    except Exception as exc:
        log.warning("PayAI status check failed (non-fatal): %s", exc)

async def _trust_stub(wallet: str | None = None, service_url: str | None = None) -> dict:
    """Stub trust function — ERC-8004 integration temporarily disabled."""
    return {
        "status": "pending",
        "wallet": wallet,
        "service_url": service_url,
        "message": "ERC-8004 trust verification temporarily unavailable",
    }


# Build Streamable HTTP MCP app at module level (must be before FastAPI())
_mcp_instance, _streamable_mcp_asgi = build_streamable_mcp_app(_search, _trust_stub)


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    """Application lifespan — starts background tasks and MCP session manager."""
    init_db()
    log.info("SQLite health DB initialized at %s", DB_PATH)
    health_task = asyncio.create_task(_background_health_checker())
    scraper_task = asyncio.create_task(_background_scraper())
    log.info("Background health checker started (interval=%ds)", HEALTH_CHECK_INTERVAL_SECS)
    log.info("Background scraper started (x402scan + ecosystem, interval=%ds)", SCRAPE_INTERVAL_SECS)
    # Register with facilitator networks for auto-discovery
    asyncio.create_task(_register_with_payai())
    # Start MCP streamable HTTP lifespan (session manager task group)
    if _streamable_mcp_asgi is not None:
        async with _streamable_mcp_asgi.lifespan(_streamable_mcp_asgi):
            try:
                yield
            finally:
                health_task.cancel()
                scraper_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await health_task
                with contextlib.suppress(asyncio.CancelledError):
                    await scraper_task
    else:
        try:
            yield
        finally:
            health_task.cancel()
            scraper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await health_task
            with contextlib.suppress(asyncio.CancelledError):
                await scraper_task

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="x402 Service Discovery API",
    version="3.4.0",
    description=(
        "Discover x402-payable endpoints with quality signals. "
        "Each discovery query costs $0.010 USDC on Base."
    ),
    lifespan=_app_lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Mount Streamable HTTP MCP ASGI app — must be before any routes
if _streamable_mcp_asgi is not None:
    app.mount("/mcp", _streamable_mcp_asgi)
    log.info("Streamable HTTP MCP mounted at /mcp")

# ---------------------------------------------------------------------------
# GET / — free
# ---------------------------------------------------------------------------

@app.post("/catalog/refresh", tags=["admin"])
async def catalog_refresh(background_tasks: BackgroundTasks) -> dict:
    """Admin endpoint: trigger an immediate ecosystem catalog scan.

    Runs the x402scan + ecosystem scrapers in the background and returns
    immediately. Check /stats for updated service count after ~60 seconds.
    """
    async def _do_refresh():
        try:
            existing_urls = {e.get("url") for e in _registry}
            x402scan_entries = await scrape_x402scan()
            added = 0
            for entry in x402scan_entries:
                if entry.get("url") not in existing_urls:
                    _registry.append(_migrate_entry(entry))
                    existing_urls.add(entry.get("url"))
                    added += 1
            new_ecosystem = await run_ecosystem_scan(existing_urls)
            for entry in new_ecosystem:
                if entry.get("url") not in existing_urls:
                    _registry.append(_migrate_entry(entry))
                    existing_urls.add(entry.get("url"))
                    added += 1
            if added > 0:
                _save_registry(_registry)
            log.info("Manual catalog refresh complete: +%d services (total: %d)", added, len(_registry))
        except Exception as exc:
            log.warning("Manual catalog refresh failed: %s", exc)

    background_tasks.add_task(_do_refresh)
    return {
        "status": "refresh_started",
        "message": "Catalog scan running in background. Check /stats in ~60 seconds for updated count.",
        "current_service_count": len(_registry),
    }

@app.get("/", include_in_schema=False)
async def root(request: Request):
    from fastapi.responses import HTMLResponse
    from landing import LANDING_HTML
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return HTMLResponse(content=LANDING_HTML)
    return JSONResponse(
        {
            "service": "x402 Service Discovery API",
            "version": "3.4.0",
            "description": (
                "Discover x402-payable endpoints with quality signals. "
                "Each query costs $0.010 USDC on Base."
            ),
            "wallet": WALLET_ADDRESS,
            "network": NETWORK,
            "query_price_usd": 0.010,
            "quality_signals": ["uptime_pct", "avg_latency_ms", "health_status", "last_health_check"],
            "endpoints": {
                "well_known": "GET /.well-known/x402-discovery (FREE — full catalog)",
                "discover": "GET /discover?q={keyword}&category={category}&capability={tag}&max_price={usd}&limit={limit} (paid $0.010)",
                "register": "POST /register (free)",
                "report": "POST /report (free — agent outcome reporting)",
                "health": "GET /health/{endpoint_id} (free)",
                "catalog": "GET /catalog (free)",
                "mcp": "GET /mcp (Streamable HTTP MCP for claude.ai/mcp) | GET /mcp-manifest (legacy JSON manifest)",
            },
            "capability_tags": sorted(CAPABILITY_VOCABULARY),
        }
    )

# ---------------------------------------------------------------------------
# GET /discover — PAID ($0.010 USDC)
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

    _discover_output_schema = {
        "input": {
            "type": "http",
            "method": "GET",
            "queryParams": {"q": "ai data", "category": "data", "limit": "10"},
            "discoverable": True,
        },
        "output": {
            "type": "json",
            "example": {
                "results": [
                    {
                        "id": "abc123",
                        "name": "Example x402 Service",
                        "url": "https://example.com/api",
                        "category": "data",
                        "trust_score": 85,
                        "price_usd": 0.01,
                        "description": "An example x402-enabled data service"
                    }
                ],
                "total": 1
            }
        }
    }

    if not payment_header:
        log.info("GET /discover — 402 (no payment) q=%r category=%r", q, category)
        return JSONResponse(
            status_code=402,
            content=_payment_required_body(
                host, resource_path, QUERY_PRICE_UNITS,
                "x402 Service Discovery — search and filter 646+ live x402-enabled services by keyword, category, and trust score",
                output_schema=_discover_output_schema,
            ),
        )

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
                "x402 Service Discovery — search and filter 646+ live x402-enabled services by keyword, category, and trust score",
                output_schema=_discover_output_schema,
            ),
        )

    log.info("GET /discover — 200 (payment verified) q=%r category=%r limit=%d", q, category, limit)

    results = _search(q, category, None, limit)

    # Increment query_count for matched entries
    matched_ids = {e["id"] for e in results}
    try:
        for entry in _registry:
            if entry["id"] in matched_ids:
                entry["query_count"] = entry.get("query_count", 0) + 1
        _save_registry(_registry)
    except Exception as exc:
        log.warning("Could not update query counts: %s", exc)

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
        "health_status": "unverified",
        "status": "active",
    }
    _registry.append(entry)
    _save_registry(_registry)

    log.info("POST /register — new endpoint id=%s name=%r", entry["id"], entry["name"])
    return JSONResponse(status_code=201, content={"registered": True, "id": entry["id"], "entry": entry})

# ---------------------------------------------------------------------------
# GET /health/{endpoint_id} — FREE (ungated for now)
# ---------------------------------------------------------------------------

@app.get("/health/{endpoint_id}")
async def health_check(endpoint_id: str, request: Request) -> JSONResponse:
    entry = next((e for e in _registry if e["id"] == endpoint_id), None)
    if not entry:
        log.info("GET /health/%s — 404", endpoint_id)
        return JSONResponse(status_code=404, content={"error": "Endpoint not found."})

    target_url = entry["url"]
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            t0 = time.monotonic()
            resp = await client.get(target_url, follow_redirects=True)
            latency_ms = int((time.monotonic() - t0) * 1000)
        is_up = resp.status_code < 500
        http_status = resp.status_code
    except Exception as exc:
        log.info("GET /health/%s — target unreachable: %s", endpoint_id, exc)
        is_up = False
        latency_ms = None
        http_status = None
        checked_at = datetime.now(timezone.utc).isoformat()

    _record_health(target_url, is_up, latency_ms, http_status)

    # Refresh in-memory registry entry
    stats = _get_health_stats(target_url)
    health_status = _compute_health_status(stats, {"is_up": is_up})
    for reg_entry in _registry:
        if reg_entry.get("id") == endpoint_id:
            reg_entry["uptime_pct"] = stats["uptime_pct"]
            reg_entry["avg_latency_ms"] = stats["avg_latency_ms"]
            reg_entry["last_health_check"] = checked_at
            reg_entry["health_status"] = health_status
    _save_registry(_registry)

    return JSONResponse({
        "endpoint_id": endpoint_id,
        "name": entry.get("name"),
        "url": target_url,
        "is_up": is_up,
        "latency_ms": latency_ms,
        "http_status": http_status,
        "checked_at": checked_at,
        "uptime_pct": stats["uptime_pct"],
        "avg_latency_ms": stats["avg_latency_ms"],
        "total_checks": stats["total_checks"],
        "successful_checks": stats["successful_checks"],
        "health_status": health_status,
    })

# ---------------------------------------------------------------------------
# GET /catalog — free
# ---------------------------------------------------------------------------

@app.get("/catalog")
async def catalog() -> JSONResponse:
    enriched = [_enrich_with_quality(e) for e in _registry]
    enriched.sort(key=lambda x: (x.get("trust_score", 0), x.get("uptime_pct", 0), x.get("query_count", 0)), reverse=True)
    return JSONResponse({
        "endpoints": enriched,
        "count": len(enriched),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    })

# ---------------------------------------------------------------------------
# GET /mcp — free, MCP tool manifest
# ---------------------------------------------------------------------------


@app.get("/.well-known/x402-discovery", include_in_schema=False)
async def well_known_discovery(request: Request) -> JSONResponse:
    """RFC 5785 well-known URL — free, permanent, no payment gate.
    Returns full index in machine-readable JSON for autonomous agent consumption."""
    all_entries = [_enrich_with_quality(e) for e in _registry]
    return JSONResponse(
        {
            "version": "1.0",
            "spec": "https://github.com/bazookam7/ouroboros/blob/ouroboros/agent_economy/discovery_api/SPEC.md",
            "discovery_provider": "x402 Service Discovery",
            "discovery_url": str(request.base_url).rstrip("/"),
            "total_services": len(all_entries),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "attestation_endpoint": f"{SERVICE_BASE_URL}/v1/attest/{{serviceId}}",
            "jwks_uri": f"{SERVICE_BASE_URL}/jwks",
            "services": all_entries,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/.well-known/x402.json", include_in_schema=False)
async def well_known_x402_json():
    """CDP Bazaar auto-discovery endpoint. Crawled to list this service in Bazaar."""
    paid_services = [
        {
            "url": s.get("url", ""),
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "price": {
                "amount": str(int(float(s.get("price_usd", 0)) * 1_000_000)),
                "currency": "USDC",
                "network": s.get("network", "base"),
            },
            "wallet": s.get("wallet_address", ""),
            "tags": s.get("tags") or [],
            "health": s.get("health_status", "unverified"),
        }
        for s in _registry
    ]
    return {
        "version": "1",
        "name": "x402 Service Discovery API",
        "description": "Discover x402-payable APIs with quality signals. Enables autonomous agents to find and pay for services via USDC micropayments on Base.",
        "url": "https://x402scout.com",
        "wallet": "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA",
        "network": "base",
        "facilitator": PAYAI_FACILITATOR_URL,
        "discoverable": True,
        "services": paid_services[:50],  # cap for crawlers
        "endpoints": [
            {
                "path": "/discover",
                "method": "GET",
                "payment_required": True,
                "price": {"amount": "10000", "currency": "USDC", "network": "base"},
                "description": "Discover x402 services by keyword",
            },
            {
                "path": "/catalog",
                "method": "GET",
                "payment_required": False,
                "description": "Browse full catalog (free)",
            },
            {
                "path": "/register",
                "method": "POST",
                "payment_required": False,
                "description": "Register a new service (free)",
            },
        ],
    }


@app.get("/facilitator-check", include_in_schema=False)
async def facilitator_check(
    network: str = "eip155:8453",
    scheme: str = "exact",
) -> JSONResponse:
    """Check which x402 payment facilitators support a given network and scheme.

    Query params:
        network: CAIP-2 network identifier (default: "eip155:8453" = Base mainnet)
        scheme:  x402 payment scheme to filter by (default: "exact")

    Returns JSON with supported flag, facilitator count, and full facilitator list.
    Free — no x402 payment required.
    """
    facilitators = _get_facilitators_for_network(network, scheme)
    return JSONResponse({
        "network": network,
        "scheme": scheme,
        "supported": len(facilitators) > 0,
        "facilitator_count": len(facilitators),
        "facilitators": [
            {
                "name": f.get("name", ""),
                "url": f.get("url", ""),
                "networks": f.get("supported_networks", []),
                "description": f.get("description", ""),
            }
            for f in facilitators
        ],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/scan")
async def scan_endpoint(url: str) -> dict:
    """Scan a URL for x402 protocol compliance. Free — no payment required."""
    import httpx as _httpx
    import json as _json

    signals = []
    issues = []
    score = 0

    try:
        async with _httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})

            if resp.status_code == 402:
                signals.append("✅ Returns HTTP 402 Payment Required")
                score += 30
            elif resp.status_code in (200, 401, 403):
                issues.append(f"⚠️ Returns {resp.status_code}, not 402 — may require x402 header to trigger payment flow")
                score += 5
            else:
                issues.append(f"❌ Returns {resp.status_code} — unexpected response")

            body = {}
            try:
                body = resp.json()
            except Exception:
                issues.append("⚠️ Response body is not valid JSON")

            if body.get("x402Version"):
                signals.append(f"✅ x402Version: {body['x402Version']}")
                score += 20
            else:
                issues.append("❌ Missing x402Version field in response body")

            accepts = body.get("accepts", [])
            if accepts and isinstance(accepts, list) and len(accepts) > 0:
                first = accepts[0]
                if first.get("scheme") and first.get("network") and first.get("maxAmountRequired"):
                    signals.append(f"✅ Valid accepts array — scheme={first.get('scheme')}, network={first.get('network')}, amount={first.get('maxAmountRequired')}")
                    score += 20
                else:
                    issues.append("⚠️ accepts array present but malformed")
                    score += 5
            else:
                issues.append("❌ Missing or empty accepts array")

            usdc_base = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
            body_str = _json.dumps(body).lower()
            if usdc_base.lower() in body_str:
                signals.append("✅ USDC on Base contract address found")
                score += 15
            elif "base" in body_str and ("usdc" in body_str or "erc" in body_str):
                signals.append("✅ Base network USDC referenced")
                score += 10
            else:
                issues.append("⚠️ No USDC/Base contract address detected")

            if "transferWithAuthorization" in _json.dumps(body) or "eip3009" in body_str or "eip-3009" in body_str:
                signals.append("✅ EIP-3009 transferWithAuthorization referenced")
                score += 15
            elif resp.status_code == 402:
                signals.append("ℹ️ EIP-3009 assumed (standard x402 flow)")
                score += 8
            else:
                issues.append("⚠️ Could not confirm EIP-3009 compliance")

    except _httpx.TimeoutException:
        return {"url": url, "compliance_score": 0, "grade": "F — Unreachable", "signals": [], "issues": ["❌ Connection timed out (10s)"], "recommendation": "Service is unreachable."}
    except Exception as e:
        return {"url": url, "compliance_score": 0, "grade": "F — Error", "signals": [], "issues": [f"❌ Error: {e}"], "recommendation": "Could not connect."}

    if score >= 80:
        grade = "A — Fully x402 Compliant"
        recommendation = "Safe to use with autonomous agents."
    elif score >= 60:
        grade = "B — Mostly Compliant"
        recommendation = "Review issues for full compliance."
    elif score >= 40:
        grade = "C — Partial Compliance"
        recommendation = "Use with caution."
    elif score >= 20:
        grade = "D — Minimal Compliance"
        recommendation = "Not recommended for autonomous payments."
    else:
        grade = "F — Not x402 Compliant"
        recommendation = "Do not attempt autonomous payments."

    return {"url": url, "compliance_score": score, "grade": grade, "signals": signals, "issues": issues, "recommendation": recommendation}


@app.get("/v1/trust-providers")
async def list_trust_providers():
    """
    List known ERC-8004-registered trust providers.

    These are the providers queried when building a chainVerifications block
    in a discovery attestation. Any ERC-8004-compliant provider can be listed here.
    Each provider publishes a JWKS endpoint for offline signature verification.
    """
    return {
        "providers": KNOWN_TRUST_PROVIDERS,
        "count": len(KNOWN_TRUST_PROVIDERS),
        "spec": "https://github.com/coinbase/x402/issues/1375",
        "note": "To add a provider, open an issue or PR at https://github.com/rplryan/x402-discovery-mcp"
    }


_SERVER_CARD_DATA = {
    "serverInfo": {
        "name": "x402-discovery-mcp",
        "displayName": "x402 Service Discovery",
        "version": "3.4.0",
        "description": "The index for the x402 agent economy. Discover, route, and verify 251+ live x402-payable services across Base mainnet. Quality signals, health monitoring, trust attestations, and payment facilitator compatibility — everything an AI agent needs to pay its way through the web.",
        "homepage": "https://github.com/rplryan/x402-discovery-mcp",
        "icon": "https://raw.githubusercontent.com/rplryan/x402-discovery-mcp/main/icon.png"
    },
    "authentication": {
        "required": False
    },
    "tools": [
        {
            "name": "x402_discover",
            "description": "Discover x402-payable services matching a query. Searches the registry of 251+ x402-enabled APIs and returns matching endpoints with quality signals (uptime %, avg latency, health status, trust score). Use this when an agent needs to find a service to pay for a capability.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language or keyword search query. Examples: 'weather forecast', 'LLM inference', 'image generation', 'financial data', 'web scraping'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 10, max: 50)",
                        "default": 10
                    }
                },
                "required": ["query"]
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "x402_browse",
            "description": "Browse all registered x402-payable services with optional category filtering. Returns the full catalog for free — no x402 payment required. Good for exploring what's available or building a service list.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter. Valid values: 'data', 'compute', 'research', 'agent', 'utility', 'llm', 'image', 'finance'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default: 20, max: 100)",
                        "default": 20
                    }
                },
                "required": []
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "x402_health",
            "description": "Check the live health and uptime statistics of a specific x402 service. Returns current status (up/down/degraded), uptime percentage, average response latency, last check timestamp, and payment facilitator compatibility.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The HTTPS endpoint URL of the x402 service to check. Must be a registered service URL."
                    }
                },
                "required": ["url"]
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "x402_register",
            "description": "Register a new x402-payable service in the discovery catalog. Free to register — no x402 payment required. The service will be monitored for health and uptime automatically after registration.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public HTTPS URL of the x402-enabled endpoint (must return HTTP 402 on unauthenticated requests)"
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable name of the service (e.g. 'Weather API', 'GPT-4 Proxy')"
                    },
                    "description": {
                        "type": "string",
                        "description": "What the service does and what agents can use it for"
                    },
                    "price_usd": {
                        "type": "number",
                        "description": "Price per API call in USD (e.g. 0.001, 0.01, 0.10)"
                    },
                    "category": {
                        "type": "string",
                        "description": "Service category: 'data', 'compute', 'research', 'agent', 'utility', 'llm', 'image', 'finance'"
                    }
                },
                "required": ["url", "name", "description"]
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": True
            }
        },
        {
            "name": "x402_facilitator_check",
            "description": "Check which x402 payment facilitators support a given blockchain network. Returns available facilitators with their URLs, supported networks, and fee structures. Use before initiating a payment to find a compatible facilitator.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "network": {
                        "type": "string",
                        "description": "CAIP-2 network identifier (default: 'eip155:8453' = Base mainnet). Other options: 'eip155:1' (Ethereum), 'eip155:137' (Polygon)",
                        "default": "eip155:8453"
                    },
                    "scheme": {
                        "type": "string",
                        "description": "x402 payment scheme to filter by (default: 'exact')",
                        "default": "exact"
                    }
                },
                "required": []
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "x402_attest",
            "description": "Fetch a signed EdDSA attestation (JWT) for a registered x402 service. The attestation contains cryptographically signed quality measurements: uptime %, avg latency, health status, and facilitator compatibility. Implements the ERC-8004 coldStartSignals spec (coinbase/x402#1375). Verify the signature offline using GET /jwks. Valid for 24 hours.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID from the catalog (e.g. 'legacy/cf-pay-per-crawl'). Use x402_browse to find valid service IDs."
                    },
                    "raw": {
                        "type": "boolean",
                        "description": "If true, return the compact JWT string instead of a human-readable summary. Default false.",
                        "default": False
                    }
                },
                "required": ["service_id"]
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        }
    ],
    "resources": [
        {
            "uri": "x402://catalog",
            "name": "x402 Service Catalog",
            "description": "The full index of 251+ live x402-payable services. Updated every 6 hours by an auto-scanner. Each entry includes service URL, category, price, uptime %, average latency, health status, and supported payment facilitators.",
            "mimeType": "application/json"
        },
        {
            "uri": "x402://facilitators",
            "name": "x402 Facilitator Registry",
            "description": "List of known x402 payment facilitators with their supported networks and endpoint URLs.",
            "mimeType": "application/json"
        }
    ],
    "prompts": [
        {
            "name": "find_service_for_task",
            "description": "Find the best x402-payable service for a specific agent task. Discovers services, checks health, and recommends the optimal endpoint.",
            "arguments": [
                {
                    "name": "task_description",
                    "description": "What the agent needs to accomplish (e.g. 'get current weather for New York', 'generate an image of a cat', 'summarize this document')",
                    "required": True
                },
                {
                    "name": "max_price_usd",
                    "description": "Maximum price per call the agent is willing to pay in USD (optional)",
                    "required": False
                }
            ]
        },
        {
            "name": "audit_service_quality",
            "description": "Perform a quality audit on an x402 service before using it. Checks health, uptime history, trust attestation, and facilitator compatibility.",
            "arguments": [
                {
                    "name": "service_url",
                    "description": "The HTTPS URL of the x402 service to audit",
                    "required": True
                }
            ]
        }
    ]
}


@app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
async def smithery_server_card(request: Request) -> JSONResponse:
    """Static server card for Smithery scanner — bypasses x402 payment gate.
    See: https://smithery.ai/docs/build/publish (Static Server Card section)"""
    return JSONResponse(_SERVER_CARD_DATA, media_type="application/json", headers={"Cache-Control": "public, max-age=3600"})


@app.post("/report")
async def report_outcome(req: ReportRequest, request: Request) -> JSONResponse:
    """Agent feedback endpoint — free, no payment gate.
    Records agent-reported call outcomes to improve quality signals."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO agent_reports (service_id, called, result, latency_ms, reported_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                req.service_id,
                int(req.called),
                req.result,
                req.latency_ms,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    # Update quality signals based on reports
    for entry in _registry:
        if entry.get("service_id") == req.service_id or entry.get("id") == req.service_id:
            if req.result == "success" and req.latency_ms:
                # Blend reported latency into our measurements
                current_avg = entry.get("avg_latency_ms")
                if current_avg:
                    entry["avg_latency_ms"] = int(current_avg * 0.8 + req.latency_ms * 0.2)
                else:
                    entry["avg_latency_ms"] = req.latency_ms
            entry["query_count"] = entry.get("query_count", 0) + 1
            break
    return JSONResponse({"status": "recorded", "service_id": req.service_id, "result": req.result})


# ---------------------------------------------------------------------------
# Discovery Attestation endpoints
# ---------------------------------------------------------------------------

@app.get("/jwks", include_in_schema=False)
async def jwks_endpoint() -> JSONResponse:
    """
    JWK Set for offline verification of discovery attestation JWTs.

    Returns the Ed25519 public key used to sign attestations from /v1/attest/:serviceId.
    Compatible with standard JWKS clients (e.g. jose, python-jwt, jsonwebtoken).

    Example verification (Python):
        import jwt, httpx
        jwks = httpx.get("https://x402scout.com/jwks").json()
        pub_key = jwks["keys"][0]["x"]  # base64url Ed25519 public key
        payload = jwt.decode(token, algorithms=["EdDSA"], options={"verify_signature": False})
    """
    return JSONResponse(
        get_jwks(),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/v1/attest/{service_id:path}")
async def attest_service(service_id: str, request: Request) -> JSONResponse:
    """
    Return a signed discovery attestation JWT for a service.

    The JWT is signed with Ed25519 and contains:
    - Service identity (id, name, url, category, price)
    - Quality measurements (uptime_pct, avg_latency_ms, health_status)
    - Facilitator compatibility (compatible, count, recommended)
    - Provenance (indexed_at, indexed_by)

    Verify offline using the public key from GET /jwks.

    This attestation can be embedded in ERC-8004 coldStartSignals.discoveryAttestation
    as proposed in: https://github.com/coinbase/x402/issues/1375

    Returns 404 if service not found, 503 if attestation keys not configured.
    """
    # Find the service in registry (match on service_id OR id OR name slug)
    entry = None
    for e in _registry:
        sid = e.get("service_id") or e.get("id", "")
        if sid == service_id:
            entry = e
            break
        # Also try URL-safe name match
        name_slug = e.get("name", "").lower().replace(" ", "-")
        if name_slug == service_id.lower():
            entry = e
            break

    if entry is None:
        return JSONResponse(
            {
                "error": "service_not_found",
                "service_id": service_id,
                "message": f"No service with id '{service_id}' in the registry. "
                           f"Browse services at GET /.well-known/x402-discovery",
            },
            status_code=404,
        )

    # Get quality data from SQLite
    url = entry.get("url", "")
    health_stats = _get_health_stats(url)
    last_check = _get_last_check(url)

    # Enrich entry with facilitator data
    enriched_entry = _enrich_with_facilitator(entry)

    # Check keys are available
    if not attest_configured():
        # Return unsigned attestation with warning — still useful for testing
        return JSONResponse(
            {
                "error": "keys_not_configured",
                "message": "Attestation signing keys not configured on this instance. "
                           "Set ATTEST_PRIVATE_KEY_B64URL and ATTEST_PUBLIC_KEY_B64URL env vars.",
                "service_id": service_id,
                "service": enriched_entry.get("name"),
            },
            status_code=503,
        )

    # Fetch chain verifications from ERC-8004 trust providers (generic, not vendor-specific)
    provider_address = enriched_entry.get("provider_address") or enriched_entry.get("wallet_address")
    chain_verifications = await fetch_chain_verifications(provider_address)

    # Build and sign the attestation JWT
    token = build_attestation(enriched_entry, health_stats, last_check, chain_verifications=chain_verifications)
    if token is None:
        return JSONResponse(
            {"error": "attestation_failed", "service_id": service_id},
            status_code=500,
        )

    # Return the token + metadata for easy consumption
    return JSONResponse(
        {
            "attestation": token,
            "service_id": service_id,
            "service_name": entry.get("name", ""),
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "expires_in_seconds": 86400,
            "verify_at": f"{SERVICE_BASE_URL}/jwks",
            "spec": "https://github.com/coinbase/x402/issues/1375",
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/spec", include_in_schema=False)
async def spec_redirect(request: Request):
    """Redirect to the SPEC.md document."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url="https://github.com/bazookam7/ouroboros/blob/ouroboros/agent_economy/discovery_api/SPEC.md"
    )




@app.get("/mcp-manifest")
async def mcp_manifest() -> JSONResponse:
    """MCP server manifest — lists available tools and their schemas."""
    return JSONResponse({
        "protocol": "mcp",
        "version": "2024-11-05",
        "name": "x402-discovery",
        "description": "Runtime x402 service discovery for the agent economy",
        "tools": [
            {
                "name": "x402_discover",
                "description": (
                    "Find x402-payable services by capability. Returns quality-ranked results "
                    "with uptime and latency signals. Requires x402 micropayment ($0.001 USDC on Base)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capability": {"type": "string", "description": "Filter by capability tag (research, data, compute, monitoring, verification, routing, storage, generation, extraction, summarization, other)"},
                        "max_price_usd": {"type": "number", "description": "Maximum price per call in USD (default 0.50)"},
                        "query": {"type": "string", "description": "Free-text search term"},
                        "x402_payment": {"type": "string", "description": "x402 payment proof. Omit to get payment challenge."},
                    },
                },
            },
            {
                "name": "x402_browse",
                "description": "Browse the complete free x402 service catalog grouped by category. No payment required.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "x402_health",
                "description": "Check live health status of a specific x402 service. Free.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service_id": {"type": "string", "description": "Service ID from catalog, e.g. ouroboros/discovery"},
                    },
                    "required": ["service_id"],
                },
            },
            {
                "name": "x402_register",
                "description": "Register a new x402-payable service with the discovery layer. Free.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "description": {"type": "string"},
                        "price_usd": {"type": "number"},
                        "category": {"type": "string"},
                    },
                    "required": ["name", "url", "description", "price_usd", "category"],
                },
            },
            {
                "name": "x402_facilitator_check",
                "description": "Check which x402 payment facilitators support a given blockchain network and scheme. Returns available facilitators, their URLs, and fee info. Free.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "network": {"type": "string", "description": "CAIP-2 network identifier (default: 'eip155:8453' = Base mainnet)"},
                        "scheme": {"type": "string", "description": "x402 payment scheme (default: 'exact')"},
                    },
                },
            },
        ],
        "server_url": "https://x402scout.com",
        "payment_info": {
            "wallet": WALLET_ADDRESS,
            "network": "eip155:8453",
            "asset": USDC_CONTRACT,
            "currency": "USDC",
            "paid_tools": ["x402_discover"],
            "price_per_call_usd": 0.001,
        },
    })


@app.post("/mcp-manifest/call")
async def mcp_call(request: Request) -> JSONResponse:
    """Handle MCP tool calls via HTTP POST.

    Request body: {"tool": "x402_discover", "arguments": {...}}
    Response: tool result or 402 payment challenge.
    """
    body = await request.json()
    tool_name = body.get("tool")
    arguments = body.get("arguments", {})

    if tool_name == "x402_browse":
        # Free tool
        services = list(_registry)
        by_category: dict = {}
        for s in services:
            cat = s.get("category") or (s.get("capability_tags") or ["other"])[0]
            by_category.setdefault(cat, []).append(s)
        return JSONResponse({"result": {"categories": len(by_category), "total": len(services), "catalog": by_category}})

    elif tool_name == "x402_health":
        service_id = arguments.get("service_id")
        if not service_id:
            return JSONResponse({"error": "service_id required"}, status_code=400)
        entry = next((e for e in _registry if e.get("service_id") == service_id or e.get("id") == service_id), None)
        if not entry:
            return JSONResponse({"error": f"Service '{service_id}' not found"}, status_code=404)
        url = entry.get("url", "")
        stats = _get_health_stats(url)
        last = _get_last_check(url)
        return JSONResponse({"result": {
            "service_id": service_id,
            "status": _compute_health_status(stats, last),
            "uptime_pct": stats.get("uptime_pct"),
            "avg_latency_ms": stats.get("avg_latency_ms"),
            "last_checked": last.get("checked_at") if last else None,
        }})

    elif tool_name == "x402_register":
        name = arguments.get("name", "")
        url_arg = arguments.get("url", "")
        desc = arguments.get("description", "")
        price_usd = arguments.get("price_usd", 0.01)
        category = arguments.get("category", "other")
        if not all([name, url_arg, desc]):
            return JSONResponse({"error": "name, url, and description are required"}, status_code=400)
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
            "source": "mcp_call",
        }
        reg_entry = _migrate_entry(reg_entry)
        _registry.append(reg_entry)
        _save_registry(_registry)
        return JSONResponse({"result": {"service_id": service_id, "status": "registered"}})

    elif tool_name == "x402_discover":
        # x402-gated tool
        payment_header = arguments.get("x402_payment")
        host = request.headers.get("host", "x402scout.com")
        resource_path = "/mcp-manifest/call"

        DISCOVER_PRICE = "1000"  # $0.001 USDC

        if not payment_header:
            challenge = _payment_required_body(host, resource_path, DISCOVER_PRICE, "x402_discover tool call")
            return JSONResponse(challenge, status_code=402, headers={
                "X-PAYMENT": json.dumps(challenge["accepts"][0]),
                "Access-Control-Expose-Headers": "X-PAYMENT",
            })

        is_valid, payment_response = await verify_payment(payment_header, f"https://{host}{resource_path}", DISCOVER_PRICE)
        if not is_valid:
            challenge = _payment_required_body(host, resource_path, DISCOVER_PRICE, "x402_discover tool call")
            return JSONResponse({"error": "Payment invalid", **challenge}, status_code=402)

        q = arguments.get("query") or arguments.get("capability")
        max_price = arguments.get("max_price_usd", 0.50)
        capability = arguments.get("capability")

        results = _search(q, capability, capability, 10)
        results = [e for e in results if e.get("price_usd", 999) <= max_price]

        return JSONResponse({
            "result": results[:5],
            "X-PAYMENT-RESPONSE": payment_response,
        })

    elif tool_name == "x402_facilitator_check":
        network = arguments.get("network", "eip155:8453")
        scheme = arguments.get("scheme", "exact")
        facilitators = _get_facilitators_for_network(network, scheme)
        return JSONResponse({"result": {
            "network": network,
            "scheme": scheme,
            "supported": len(facilitators) > 0,
            "facilitator_count": len(facilitators),
            "facilitators": [
                {
                    "name": f.get("name", ""),
                    "url": f.get("url", ""),
                    "networks": f.get("supported_networks", []),
                    "description": f.get("description", ""),
                }
                for f in facilitators
            ],
        }})

    else:
        return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=404)

# Mount MCP Streamable HTTP Transport (Smithery-compatible) from mcp_transport module
from mcp_transport import create_mcp_router  # noqa: E402


async def _trust_stub(wallet: str | None = None, service_url: str | None = None) -> dict:
    """Stub trust function — ERC-8004 integration temporarily disabled."""
    return {
        "status": "pending",
        "wallet": wallet,
        "service_url": service_url,
        "message": "ERC-8004 trust verification temporarily unavailable",
    }


app.include_router(create_mcp_router(
    registry=_registry,
    search_fn=_search,
    payment_fn=verify_payment,
    enrich_fn=_enrich_with_quality,
    health_stats_fn=_get_health_stats,
    last_check_fn=_get_last_check,
    health_status_fn=_compute_health_status,
    migrate_fn=_migrate_entry,
    save_fn=_save_registry,
    query_price_units=QUERY_PRICE_UNITS,
    payment_required_body_fn=_payment_required_body,
    trust_fn=_trust_stub,
))

if oauth_router is not None:
    app.include_router(oauth_router)

@app.get("/.well-known/openai-apps-challenge", include_in_schema=False)
async def openai_domain_verification():
    """OpenAI domain verification token."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("FOQuubpFmWXwYoAM6V3-sg4bBcQCrZ172wyHAbOTq94")


@app.get("/privacy", include_in_schema=False)
async def privacy_policy():
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Privacy Policy — x402 Service Discovery</title>
<style>body{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#333}h1{color:#111}h2{color:#444;margin-top:2em}a{color:#0066cc}</style>
</head>
<body>
<h1>Privacy Policy</h1>
<p><strong>Service:</strong> x402 Service Discovery API<br>
<strong>Operator:</strong> x402Scout<br>
<strong>Contact:</strong> <a href="mailto:x402scout@proton.me">x402scout@proton.me</a><br>
<strong>Last updated:</strong> March 1, 2026</p>

<h2>What data we collect</h2>
<p>When you use this MCP server or API, we may log:</p>
<ul>
<li>Query strings and search terms submitted to discovery tools</li>
<li>API endpoint URLs checked via health tools</li>
<li>Timestamps of requests</li>
<li>Standard server access logs (IP address, HTTP method, path, response code)</li>
</ul>
<p>We do <strong>not</strong> collect names, email addresses, or account credentials through this service. No OAuth or user authentication is implemented.</p>

<h2>How we use data</h2>
<ul>
<li>To operate and improve the x402 service registry</li>
<li>To monitor service health and uptime</li>
<li>To debug errors and improve reliability</li>
</ul>
<p>We do <strong>not</strong> sell data to third parties. We do not use query data for advertising.</p>

<h2>Data retention</h2>
<p>Server access logs are retained for up to 30 days. Health check data (uptime/latency statistics) is retained for 7 days as described in our API documentation.</p>

<h2>Third-party services</h2>
<p>This service is hosted on <a href="https://render.com/privacy">Render</a>. Query results reference third-party x402-enabled APIs; we are not responsible for the privacy practices of those services.</p>

<h2>Your rights</h2>
<p>To request deletion of any data associated with your queries, contact us at <a href="mailto:x402scout@proton.me">x402scout@proton.me</a>.</p>

<h2>Changes</h2>
<p>We may update this policy. The latest version is always at <a href="https://x402scout.com/privacy">https://x402scout.com/privacy</a>.</p>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/terms", include_in_schema=False)
async def terms_of_service():
    """Terms of Service for x402 Service Discovery API."""
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Terms of Service — x402 Service Discovery</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.6; }
  h1 { color: #1a1a2e; } h2 { color: #16213e; margin-top: 2em; }
  a { color: #0066cc; }
</style>
</head>
<body>
<h1>Terms of Service</h1>
<p><strong>x402 Service Discovery API</strong> — <a href="https://x402scout.com">https://x402scout.com</a></p>
<p><em>Effective date: March 1, 2026</em></p>

<h2>1. Acceptance of Terms</h2>
<p>By accessing or using the x402 Service Discovery API ("the Service"), you agree to be bound by these Terms of Service. If you do not agree, do not use the Service.</p>

<h2>2. Description of Service</h2>
<p>The Service provides a discovery catalog of x402-payable APIs, quality metrics, uptime monitoring, and cryptographic attestations for autonomous AI agents and developers. The Service is provided free of charge for discovery queries; individual x402-gated endpoints may have their own pricing.</p>

<h2>3. Acceptable Use</h2>
<p>You may use the Service to:</p>
<ul>
  <li>Discover and evaluate x402-payable API services</li>
  <li>Integrate the MCP server into AI agent workflows</li>
  <li>Submit your own x402-compliant services for listing</li>
</ul>
<p>You may not:</p>
<ul>
  <li>Use the Service to send spam, malware, or abusive requests</li>
  <li>Attempt to reverse-engineer or disrupt the Service</li>
  <li>Submit false or misleading service registrations</li>
  <li>Circumvent rate limits or access controls</li>
</ul>

<h2>4. Service Listings</h2>
<p>We index x402-payable services based on automated discovery and community submissions. We do not endorse, guarantee, or take responsibility for any listed third-party service. Service listings may be added, modified, or removed at any time.</p>

<h2>5. No Warranty</h2>
<p>The Service is provided "as is" without warranties of any kind. We do not guarantee uptime, accuracy of service data, or continued availability of any listed service.</p>

<h2>6. Limitation of Liability</h2>
<p>To the maximum extent permitted by law, x402 Service Discovery shall not be liable for any indirect, incidental, special, or consequential damages arising from your use of the Service or any listed service.</p>

<h2>7. Modifications</h2>
<p>We may update these Terms at any time. Continued use of the Service after changes constitutes acceptance of the updated Terms.</p>

<h2>8. Contact</h2>
<p>Questions about these Terms: <a href="mailto:x402scout@proton.me">x402scout@proton.me</a></p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@app.get("/support", include_in_schema=False)
async def support_info():
    return {
        "support_email": "x402scout@proton.me",
        "github": "https://github.com/rplryan/x402-discovery-mcp",
        "documentation": "https://x402scout.com/docs",
        "mcp_server": "https://x402scout.com/mcp",
        "issues": "https://github.com/rplryan/x402-discovery-mcp/issues",
    }


RADAR_SVG_256 = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs>
    <!-- Glow filter for center dot -->
    <filter id="glow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="4" result="blur1"/>
      <feGaussianBlur stdDeviation="10" result="blur2"/>
      <feGaussianBlur stdDeviation="20" result="blur3"/>
      <feMerge>
        <feMergeNode in="blur3"/>
        <feMergeNode in="blur2"/>
        <feMergeNode in="blur1"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <!-- Soft glow for arcs -->
    <filter id="arcglow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <!-- Atmospheric background gradient -->
    <radialGradient id="bgGrad" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#010e01" stop-opacity="1"/>
      <stop offset="60%" stop-color="#020a02" stop-opacity="1"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="1"/>
    </radialGradient>
    <!-- Center dot glow gradient -->
    <radialGradient id="centerGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="1"/>
      <stop offset="15%" stop-color="#80ff80" stop-opacity="0.9"/>
      <stop offset="35%" stop-color="#00ff41" stop-opacity="0.6"/>
      <stop offset="60%" stop-color="#004d00" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>
    <!-- Arc glow -->
    <radialGradient id="arcGlowGrad" cx="30%" cy="50%" r="60%">
      <stop offset="0%" stop-color="#00ff41" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <!-- Pure black background -->
  <rect width="256" height="256" fill="#000000"/>
  
  <!-- Atmospheric background glow (very subtle green tint in center) -->
  <rect width="256" height="256" fill="url(#bgGrad)"/>
  
  <!-- Very faint left-side atmospheric wash from arcs -->
  <ellipse cx="90" cy="128" rx="90" ry="90" fill="url(#arcGlowGrad)"/>

  <!-- Outer ring 1 - faint at r=115 -->
  <circle cx="128" cy="128" r="115" fill="none" 
    stroke="#00ff41" stroke-width="0.8" stroke-opacity="0.15"
    stroke-dasharray="8,4"/>
  
  <!-- Outer ring 2 - slightly more visible at r=105 -->
  <circle cx="128" cy="128" r="105" fill="none" 
    stroke="#00ff41" stroke-width="0.6" stroke-opacity="0.12"/>

  <!-- Tick marks on outer ring - compass-style at key positions -->
  <g stroke="#00ff41" stroke-opacity="0.25" stroke-width="1">
    <!-- Top tick -->
    <line x1="128" y1="9" x2="128" y2="17"/>
    <!-- Bottom tick -->
    <line x1="128" y1="239" x2="128" y2="247"/>
    <!-- Left tick -->
    <line x1="9" y1="128" x2="17" y2="128"/>
    <!-- Right tick -->
    <line x1="239" y1="128" x2="247" y2="128"/>
    <!-- Diagonal ticks (45deg positions) -->
    <line x1="46" y1="46" x2="52" y2="52"/>
    <line x1="204" y1="46" x2="210" y2="52"/>
    <line x1="46" y1="210" x2="52" y2="204"/>
    <line x1="204" y1="210" x2="210" y2="204"/>
  </g>

  <!-- Inner faint echo arcs (thinner, slightly smaller radius) -->
  <g stroke="#00ff41" stroke-opacity="0.2" stroke-width="3" fill="none" stroke-linecap="round">
    <path d="M 69.02,86.70 A 72,72 0 0,1 140.50,57.09"/>
    <path d="M 103.37,195.66 A 72,72 0 0,1 57.09,115.50"/>
  </g>

  <!-- MAIN thick arc segments (with glow filter) -->
  <g filter="url(#arcglow)">
    <!-- Arc A: upper-left, 10:00 to 12:30, strokeWidth 7 -->
    <path d="M 58.72,88.00 A 80,80 0 0,1 148.71,50.73" stroke="#00ff41" stroke-width="7" fill="none" stroke-linecap="round" stroke-opacity="0.95"/>
    <!-- Arc B: lower-left, 6:30 to 9:30, strokeWidth 8 -->
    <path d="M 107.29,205.27 A 80,80 0 0,1 50.73,107.29" stroke="#00ff41" stroke-width="8" fill="none" stroke-linecap="round" stroke-opacity="0.95"/>
    <!-- Arc C: bottom tick, 5:30 to 6:30, strokeWidth 6 -->
    <path d="M 148.71,205.27 A 80,80 0 0,1 107.29,205.27" stroke="#00ff41" stroke-width="6" fill="none" stroke-linecap="round" stroke-opacity="0.85"/>
  </g>

  <!-- Horizontal crosshair lines -->
  <!-- Left side: from edge to near center, with gap -->
  <g stroke="#00ff41" stroke-opacity="0.55" stroke-width="1" fill="none">
    <!-- Left arm: x=4 to x=108 (20px gap from center 128) -->
    <line x1="4" y1="128" x2="108" y2="128"/>
    <!-- Right arm: x=148 to x=252 -->
    <line x1="148" y1="128" x2="252" y2="128"/>
    
    <!-- Tick marks on left crosshair arm -->
    <line x1="60" y1="124" x2="60" y2="132"/>
    <line x1="80" y1="125" x2="80" y2="131"/>
    <line x1="100" y1="126" x2="100" y2="130"/>
    <!-- Tick marks on right crosshair arm -->
    <line x1="156" y1="126" x2="156" y2="130"/>
    <line x1="176" y1="125" x2="176" y2="131"/>
    <line x1="196" y1="124" x2="196" y2="132"/>
    
    <!-- Short vertical marks at top and bottom center (not full lines) -->
    <line x1="128" y1="4" x2="128" y2="30"/>
    <line x1="128" y1="226" x2="128" y2="252"/>
    
    <!-- Tick on vertical arms -->
    <line x1="124" y1="24" x2="132" y2="24"/>
    <line x1="124" y1="232" x2="132" y2="232"/>
  </g>

  <!-- Center radial glow bloom (large, very soft) -->
  <circle cx="128" cy="128" r="80" fill="url(#centerGlow)" opacity="0.35"/>

  <!-- Center dot with hard glow filter -->
  <circle cx="128" cy="128" r="9" fill="#00ff41" filter="url(#glow)" opacity="0.9"/>
  <circle cx="128" cy="128" r="5" fill="#ccffcc" filter="url(#glow)"/>
  <circle cx="128" cy="128" r="3" fill="#ffffff"/>
  
</svg>"""

RADAR_SVG_64 = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <defs>
    <filter id="glow64" x="-150%" y="-150%" width="400%" height="400%">
      <feGaussianBlur stdDeviation="1.5" result="blur1"/>
      <feGaussianBlur stdDeviation="3" result="blur2"/>
      <feMerge>
        <feMergeNode in="blur2"/>
        <feMergeNode in="blur1"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <filter id="arcglow64" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="0.8" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <radialGradient id="bgGrad64" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#010e01" stop-opacity="1"/>
      <stop offset="60%" stop-color="#020a02" stop-opacity="1"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="1"/>
    </radialGradient>
    <radialGradient id="centerGlow64" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="1"/>
      <stop offset="15%" stop-color="#80ff80" stop-opacity="0.9"/>
      <stop offset="35%" stop-color="#00ff41" stop-opacity="0.6"/>
      <stop offset="60%" stop-color="#004d00" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="arcGlowGrad64" cx="30%" cy="50%" r="60%">
      <stop offset="0%" stop-color="#00ff41" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <!-- Background -->
  <rect width="64" height="64" fill="#000000"/>
  <rect width="64" height="64" fill="url(#bgGrad64)"/>

  <!-- Atmospheric wash (left side) -->
  <ellipse cx="22" cy="32" rx="22" ry="22" fill="url(#arcGlowGrad64)"/>

  <!-- Outer rings -->
  <circle cx="32" cy="32" r="28.75" fill="none" stroke="#00ff41" stroke-width="0.4" stroke-opacity="0.15" stroke-dasharray="2,1"/>
  <circle cx="32" cy="32" r="26.25" fill="none" stroke="#00ff41" stroke-width="0.3" stroke-opacity="0.12"/>

  <!-- Tick marks at compass positions -->
  <g stroke="#00ff41" stroke-opacity="0.25" stroke-width="0.5">
    <line x1="32" y1="2" x2="32" y2="4"/>
    <line x1="32" y1="60" x2="32" y2="62"/>
    <line x1="2" y1="32" x2="4" y2="32"/>
    <line x1="60" y1="32" x2="62" y2="32"/>
  </g>

  <!-- Inner echo arcs -->
  <g stroke="#00ff41" stroke-opacity="0.2" stroke-width="0.75" fill="none" stroke-linecap="round">
    <path d="M 17.26,21.68 A 18,18 0 0,1 35.13,14.27"/>
    <path d="M 25.84,48.92 A 18,18 0 0,1 14.27,28.88"/>
  </g>

  <!-- MAIN thick arc segments -->
  <g filter="url(#arcglow64)">
    <!-- Arc A: upper-left ~10:00 to 12:30 -->
    <path d="M 14.68,22.00 A 20,20 0 0,1 37.18,12.68" stroke="#00ff41" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-opacity="0.95"/>
    <!-- Arc B: lower-left ~6:30 to 9:30 -->
    <path d="M 26.82,51.32 A 20,20 0 0,1 12.68,26.82" stroke="#00ff41" stroke-width="2" fill="none" stroke-linecap="round" stroke-opacity="0.95"/>
    <!-- Arc C: bottom ~5:30 to 6:30 -->
    <path d="M 37.18,51.32 A 20,20 0 0,1 26.82,51.32" stroke="#00ff41" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-opacity="0.85"/>
  </g>

  <!-- Horizontal crosshair -->
  <g stroke="#00ff41" stroke-opacity="0.55" stroke-width="0.5" fill="none">
    <line x1="1" y1="32" x2="27" y2="32"/>
    <line x1="37" y1="32" x2="63" y2="32"/>
    <!-- Tick marks on crosshair -->
    <line x1="15" y1="30" x2="15" y2="34"/>
    <line x1="20" y1="31" x2="20" y2="33"/>
    <line x1="24" y1="31.5" x2="24" y2="32.5"/>
    <line x1="40" y1="31.5" x2="40" y2="32.5"/>
    <line x1="44" y1="31" x2="44" y2="33"/>
    <line x1="49" y1="30" x2="49" y2="34"/>
    <!-- Vertical stubs -->
    <line x1="32" y1="1" x2="32" y2="7"/>
    <line x1="32" y1="57" x2="32" y2="63"/>
    <line x1="30" y1="6" x2="34" y2="6"/>
    <line x1="30" y1="58" x2="34" y2="58"/>
  </g>

  <!-- Center glow bloom -->
  <circle cx="32" cy="32" r="20" fill="url(#centerGlow64)" opacity="0.35"/>

  <!-- Center dot with glow -->
  <circle cx="32" cy="32" r="2.25" fill="#00ff41" filter="url(#glow64)" opacity="0.9"/>
  <circle cx="32" cy="32" r="1.25" fill="#ccffcc" filter="url(#glow64)"/>
  <circle cx="32" cy="32" r="0.75" fill="#ffffff"/>

</svg>"""

RADAR_SVG_512 = """<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <radialGradient id="bg512" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#010f01" stop-opacity="1"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="1"/>
    </radialGradient>
    <radialGradient id="center512" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="1"/>
      <stop offset="8%" stop-color="#ccffdd" stop-opacity="0.95"/>
      <stop offset="18%" stop-color="#00ff41" stop-opacity="0.8"/>
      <stop offset="40%" stop-color="#006600" stop-opacity="0.35"/>
      <stop offset="70%" stop-color="#001a00" stop-opacity="0.1"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>
    <filter id="bloom512" x="-200%" y="-200%" width="500%" height="500%">
      <feGaussianBlur stdDeviation="6" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="arcglow512" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <!-- Background -->
  <rect width="512" height="512" fill="#000000"/>
  <circle cx="256" cy="256" r="256" fill="url(#bg512)"/>
  <!-- Outer rings -->
  <circle cx="256" cy="256" r="210" fill="none" stroke="#00ff41" stroke-width="0.8" opacity="0.18"/>
  <circle cx="256" cy="256" r="230" fill="none" stroke="#00ff41" stroke-width="0.5" opacity="0.12" stroke-dasharray="4 8"/>
  <!-- Ring tick marks on outer ring -->
  <line x1="486" y1="256" x2="492" y2="256" stroke="#00ff41" stroke-width="0.8" opacity="0.3"/>
  <line x1="256" y1="486" x2="256" y2="492" stroke="#00ff41" stroke-width="0.8" opacity="0.3"/>
  <line x1="26" y1="256" x2="20" y2="256" stroke="#00ff41" stroke-width="0.8" opacity="0.3"/>
  <line x1="256" y1="26" x2="256" y2="20" stroke="#00ff41" stroke-width="0.8" opacity="0.3"/>
  <!-- Thick arc segments (glow layer) -->
  <path d="M 101.45 214.59 A 160 160 0 0 1 297.41 101.45" fill="none" stroke="#00ff41" stroke-width="12" stroke-linecap="round" opacity="0.15" filter="url(#arcglow512)"/>
  <path d="M 228.22 413.57 A 160 160 0 0 1 98.43 228.22" fill="none" stroke="#00ff41" stroke-width="14" stroke-linecap="round" opacity="0.15" filter="url(#arcglow512)"/>
  <!-- Thick arc segments (main) -->
  <path d="M 101.45 214.59 A 160 160 0 0 1 297.41 101.45" fill="none" stroke="#00ff41" stroke-width="14" stroke-linecap="round" opacity="0.95"/>
  <path d="M 228.22 413.57 A 160 160 0 0 1 98.43 228.22" fill="none" stroke="#00ff41" stroke-width="16" stroke-linecap="round" opacity="0.9"/>
  <path d="M 269.94 415.39 A 160 160 0 0 1 230.97 414.03" fill="none" stroke="#00ff41" stroke-width="10" stroke-linecap="round" opacity="0.85"/>
  <!-- Horizontal crosshair -->
  <line x1="0" y1="256" x2="211" y2="256" stroke="#00ff41" stroke-width="0.8" opacity="0.6"/>
  <line x1="301" y1="256" x2="512" y2="256" stroke="#00ff41" stroke-width="0.8" opacity="0.6"/>
  <!-- Crosshair tick marks -->
  <line x1="176" y1="252" x2="176" y2="260" stroke="#00ff41" stroke-width="0.8" opacity="0.5"/>
  <line x1="116" y1="253" x2="116" y2="259" stroke="#00ff41" stroke-width="0.6" opacity="0.4"/>
  <line x1="336" y1="252" x2="336" y2="260" stroke="#00ff41" stroke-width="0.8" opacity="0.5"/>
  <line x1="396" y1="253" x2="396" y2="259" stroke="#00ff41" stroke-width="0.6" opacity="0.4"/>
  <!-- Vertical ticks -->
  <line x1="256" y1="211" x2="256" y2="156" stroke="#00ff41" stroke-width="0.6" opacity="0.4"/>
  <line x1="256" y1="301" x2="256" y2="356" stroke="#00ff41" stroke-width="0.6" opacity="0.4"/>
  <!-- Center radial glow -->
  <circle cx="256" cy="256" r="80" fill="url(#center512)"/>
  <!-- Center dot with bloom -->
  <circle cx="256" cy="256" r="10" fill="#00ff41" opacity="0.9" filter="url(#bloom512)"/>
  <circle cx="256" cy="256" r="6" fill="#ffffff"/>
</svg>"""

import base64 as _base64

# Base64-encoded 256x256 PNG icon (generated from brand kit)
# To regenerate: python3 -c "from PIL import Image; import io,base64; img=Image.open('/root/Ouroboros/data/promo_screenshots/Logo (Profile) (Small).png').convert('RGBA'); img=img.resize((256,256),Image.LANCZOS); buf=io.BytesIO(); img.save(buf,format='PNG',optimize=True); print(base64.b64encode(buf.getvalue()).decode())"
LOGO_PNG_256_B64 = "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"
LOGO_PNG_256_BYTES = _base64.b64decode(LOGO_PNG_256_B64) if LOGO_PNG_256_B64 else b""

# 64x64 PNG favicon from new brand kit
FAVICON_PNG_64_B64 = "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"
FAVICON_PNG_64_BYTES = _base64.b64decode(FAVICON_PNG_64_B64)

# Full wordmark PNG (512x341) from brand kit
WORDMARK_PNG_B64 = "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"
WORDMARK_PNG_BYTES = _base64.b64decode(WORDMARK_PNG_B64)


@app.get("/logo.svg", include_in_schema=False)
async def serve_logo():
    """Serve the x402Scout radar logo (256x256)."""
    from fastapi.responses import Response
    return Response(content=RADAR_SVG_256, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=300"})


@app.get("/logo-full.svg", include_in_schema=False)
async def serve_logo_full():
    """Serve the x402Scout radar logo high-res (512x512) for Anthropic Connectors Directory."""
    from fastapi.responses import Response
    return Response(content=RADAR_SVG_512, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=300"})


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    """Serve the x402Scout radar favicon (64x64 PNG)."""
    from fastapi.responses import Response
    return Response(content=FAVICON_PNG_64_BYTES, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/logo.png", include_in_schema=False)
async def serve_logo_png():
    """Serve the x402Scout icon as PNG (256x256)."""
    from fastapi.responses import Response
    return Response(content=LOGO_PNG_256_BYTES, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})




@app.get("/wordmark.png", include_in_schema=False)
async def serve_wordmark():
    """Serve the x402Scout wordmark (full logo with text, 512x341 PNG)."""
    from fastapi.responses import Response
    return Response(content=WORDMARK_PNG_BYTES, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
