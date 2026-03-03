"""x402 Service Discovery API
Agents query it to discover available services.
Each discovery query costs $0.010 USDC on Base.

Wallet: 0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA
Network: Base (Ethereum L2)
Asset: USDC (0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913)
"""

from __future__ import annotations

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
from fastapi import FastAPI, Query, Request
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
    "SERVICE_BASE_URL", "https://x402-discovery-api.onrender.com"
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
        scored.sort(key=lambda x: (x[1], x[0].get("query_count", 0)), reverse=True)
        results = [e for e, _ in scored]
    else:
        results.sort(key=lambda e: e.get("query_count", 0), reverse=True)

    # Enrich with quality signals from SQLite
    enriched = [_enrich_with_quality(e) for e in results[:limit * 2]]

    # Re-sort by quality: uptime desc, latency asc, registered_at desc
    def quality_sort_key(e: dict):
        uptime = e.get("uptime_pct") or 0.0
        latency = e.get("avg_latency_ms") or 9999
        registered = e.get("registered_at", "")
        return (-uptime, latency, [-ord(c) for c in registered[:10]])

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
    version="3.3.0",
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
            "version": "3.3.0",
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

    _discover_input_schema = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Keyword search query"},
            "category": {"type": "string", "description": "Filter by category: research, data, compute, agent, utility"},
            "limit": {"type": "integer", "description": "Max results (1-50)", "default": 10},
        },
    }

    if not payment_header:
        log.info("GET /discover — 402 (no payment) q=%r category=%r", q, category)
        return JSONResponse(
            status_code=402,
            content=_payment_required_body(
                host, resource_path, QUERY_PRICE_UNITS,
                "x402 Service Discovery Query",
                input_schema=_discover_input_schema,
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
                "x402 Service Discovery Query — payment invalid or facilitator unreachable",
                input_schema=_discover_input_schema,
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
        "url": "https://x402-discovery-api.onrender.com",
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
        "version": "3.3.0",
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
        jwks = httpx.get("https://x402-discovery-api.onrender.com/jwks").json()
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
        "server_url": "https://x402-discovery-api.onrender.com",
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
        host = request.headers.get("host", "x402-discovery-api.onrender.com")
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
<p>We may update this policy. The latest version is always at <a href="https://x402-discovery-api.onrender.com/privacy">https://x402-discovery-api.onrender.com/privacy</a>.</p>
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
<p><strong>x402 Service Discovery API</strong> — <a href="https://x402-discovery-api.onrender.com">https://x402-discovery-api.onrender.com</a></p>
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
        "documentation": "https://x402-discovery-api.onrender.com/docs",
        "mcp_server": "https://x402-discovery-api.onrender.com/mcp",
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
    """Serve the x402Scout radar favicon (64x64 SVG)."""
    from fastapi.responses import Response
    return Response(content=RADAR_SVG_64, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=300"})


@app.get("/logo.png", include_in_schema=False)
async def serve_logo_png():
    """Serve the x402Scout icon as PNG (256x256)."""
    from fastapi.responses import Response
    return Response(content=LOGO_PNG_256_BYTES, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
