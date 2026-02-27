"""x402 Service Discovery API
Agents query it to discover available services.
Each discovery query costs $0.005 USDC on Base.

Wallet: 0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA
Network: Base (Ethereum L2)
Asset: USDC (0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913)
"""

from __future__ import annotations

import asyncio
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
    with REGISTRY_PATH.open("w") as fh:
        json.dump(entries, fh, indent=2)


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
    from eth_account.messages import encode_structured_data
    
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
                'nonce': auth.get('nonce', '0x' + '0' * 64),
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
        msg = encode_structured_data(structured)
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
    """Scrape x402scan.com every 6 hours and upsert new endpoints."""
    await asyncio.sleep(10)  # Wait for startup
    while True:
        try:
            new_entries = await scrape_x402scan()
            added = 0
            existing_urls = {e.get("url") for e in _registry}
            for entry in new_entries:
                if entry.get("url") not in existing_urls:
                    _registry.append(_migrate_entry(entry))
                    existing_urls.add(entry.get("url"))
                    added += 1
            if added > 0:
                _save_registry(_registry)
                log.info(
                    "x402scan scraper: added %d new endpoints (total: %d)",
                    added, len(_registry),
                )
        except Exception as exc:
            log.warning("x402scan scraper failed: %s", exc)
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

@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    init_db()
    log.info("SQLite health DB initialized at %s", DB_PATH)
    health_task = asyncio.create_task(_background_health_checker())
    scraper_task = asyncio.create_task(_background_scraper())
    log.info("Background health checker started (interval=%ds)", HEALTH_CHECK_INTERVAL_SECS)
    log.info("Background x402scan scraper started (interval=%ds)", SCRAPE_INTERVAL_SECS)
    # Register with facilitator networks for auto-discovery
    asyncio.create_task(_register_with_payai())
    yield
    health_task.cancel()
    scraper_task.cancel()
    for t in (health_task, scraper_task):
        try:
            await t
        except asyncio.CancelledError:
            pass

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="x402 Service Discovery API",
    version="3.2.0",
    description=(
        "Discover x402-payable endpoints with quality signals. "
        "Each discovery query costs $0.005 USDC on Base."
    ),
    lifespan=_app_lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# GET / — free
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "x402 Service Discovery API",
            "version": "3.2.0",
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
                "mcp": "GET /mcp (free)",
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


@app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
async def smithery_server_card(request: Request) -> JSONResponse:
    """Static server card for Smithery scanner — bypasses x402 payment gate.
    See: https://smithery.ai/docs/build/publish (Static Server Card section)"""
    return JSONResponse(
        {
            "serverInfo": {
                "name": "x402 Service Discovery",
                "version": "3.2.0"
            },
            "authentication": {
                "required": False
            },
            "tools": [
                {
                    "name": "x402_discover",
                    "description": "Discover x402-payable services matching a query. Searches the registry of x402-enabled APIs and returns matching endpoints with quality signals (uptime, latency, payment details). Each query costs $0.005 USDC via x402 protocol.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language or keyword search (e.g. 'weather', 'llm', 'research')"
                            }
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "x402_browse",
                    "description": "Browse all registered x402-payable services with optional filtering by category. Returns the full catalog for free.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "Optional category filter (e.g. 'data', 'compute', 'research')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max results to return (default 20)"
                            }
                        },
                        "required": []
                    }
                },
                {
                    "name": "x402_health",
                    "description": "Check the health and uptime statistics of a specific x402 service by URL or service ID.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The endpoint URL of the service to check"
                            }
                        },
                        "required": ["url"]
                    }
                },
                {
                    "name": "x402_register",
                    "description": "Register a new x402-payable service in the discovery registry. Free to register.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The public HTTPS URL of the x402-enabled endpoint"
                            },
                            "name": {
                                "type": "string",
                                "description": "Human-readable name of the service"
                            },
                            "description": {
                                "type": "string",
                                "description": "What the service does"
                            },
                            "price_usd": {
                                "type": "number",
                                "description": "Price per call in USD"
                            },
                            "category": {
                                "type": "string",
                                "description": "Service category (data, compute, research, etc.)"
                            }
                        },
                        "required": ["url", "name", "description"]
                    }
                }
            ],
            "resources": [],
            "prompts": []
        },
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=3600"}
    )


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


@app.get("/spec", include_in_schema=False)
async def spec_redirect(request: Request):
    """Redirect to the SPEC.md document."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url="https://github.com/bazookam7/ouroboros/blob/ouroboros/agent_economy/discovery_api/SPEC.md"
    )


@app.get("/mcp")
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


@app.post("/mcp/call")
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
        resource_path = "/mcp/call"

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

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
