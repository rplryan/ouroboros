"""x402 Service Discovery API
Agents query it to discover available services.
Each discovery query costs $0.005 USDC on Base.

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

QUERY_PRICE_UNITS: str = os.getenv("QUERY_PRICE_USDC_UNITS", "5000")        # $0.005
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
        "Each discovery query costs $0.005 USDC on Base."
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
async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "x402 Service Discovery API",
            "version": "3.3.0",
            "description": (
                "Discover x402-payable endpoints with quality signals. "
                "Each query costs $0.005 USDC on Base."
            ),
            "wallet": WALLET_ADDRESS,
            "network": NETWORK,
            "query_price_usd": 0.005,
            "quality_signals": ["uptime_pct", "avg_latency_ms", "health_status", "last_health_check"],
            "endpoints": {
                "well_known": "GET /.well-known/x402-discovery (FREE — full catalog)",
                "discover": "GET /discover?q={keyword}&category={category}&capability={tag}&max_price={usd}&limit={limit} (paid $0.005)",
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
                "price": {"amount": "5000", "currency": "USDC", "network": "base"},
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
