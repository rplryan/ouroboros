"""
ERC-8004 Trust Layer Integration
==================================
ERC-8004 is a decentralized AI agent trust standard (launched Jan 29, 2026).
It provides three on-chain registries:
  1. Identity Registry  — unique on-chain identifier per agent/service
  2. Reputation Registry — verifiable interaction scores (0-100 scale)
  3. Validation Registry — third-party attestations

Contract addresses (SAME on Ethereum mainnet AND Base mainnet):
  Identity Registry:   0x1234567890123456789012345678901234567890  (placeholder — see notes)
  Reputation Registry: 0x2345678901234567890123456789012345678901  (placeholder — see notes)
  Validation Registry: 0x3456789012345678901234567890123456789012  (placeholder — see notes)

DEPLOYMENT STATUS (as of 2026-02-26):
--------------------------------------
ERC-8004 is in DRAFT status (not yet Final). The EIP was authored Jan 29, 2026.
Based on research:
  - The EIP references 8004.org as an exploratory site
  - The erc-8004/erc-8004-contracts GitHub repo exists with ABIs but
    NO verified deployment events have been confirmed on-chain
  - etherscan.io search for "ERC-8004" returns no verified contracts
  - Base network: No confirmed deployment found

THEREFORE: This module implements the full ERC-8004 interface but operates in
PENDING MODE when contracts are not found at lookup time. All fields return
null/pending until official contract addresses are confirmed.

The `well-known` URL pattern (https://{domain}/.well-known/erc-8004) IS
implementable NOW — we check if a service's domain has declared an ERC-8004
address, which is part of the standard's off-chain binding mechanism.

Python dependencies: httpx (already in requirements.txt)
Optional: web3 (for on-chain calls) — gracefully absent if not installed
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ERC-8004 contract addresses
# NOTE: Update these when official deployment is confirmed.
# The EIP specifies these should be the same address on all supported chains.
# Reference: https://github.com/erc-8004/erc-8004-contracts
# ---------------------------------------------------------------------------

# These are the addresses from the ERC-8004 GitHub repo ABIs + ethereum-magicians thread.
# Marked as UNVERIFIED until we can confirm on-chain.
ERC8004_IDENTITY_REGISTRY = "0x0000000000000000000000000000000000000000"   # TBD — not yet deployed
ERC8004_REPUTATION_REGISTRY = "0x0000000000000000000000000000000000000000"  # TBD — not yet deployed
ERC8004_VALIDATION_REGISTRY = "0x0000000000000000000000000000000000000000"  # TBD — not yet deployed

# Base mainnet RPC (free, no API key)
BASE_RPC = "https://mainnet.base.org"

# Ethereum mainnet RPC (free Cloudflare)
ETH_RPC = "https://cloudflare-eth.com"

# Whether contracts are confirmed deployed (set to True when addresses are real)
CONTRACTS_DEPLOYED = False

# Cache TTL in seconds (1 hour)
CACHE_TTL = 3600

# In-memory cache: wallet_address -> {result, fetched_at}
_trust_cache: dict[str, dict] = {}

# Minimal ABIs for read-only calls
IDENTITY_ABI = [
    {
        "name": "getIdentity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [
            {"name": "identityId", "type": "bytes32"},
            {"name": "metadata", "type": "string"},
            {"name": "registeredAt", "type": "uint256"},
        ],
    },
    {
        "name": "hasIdentity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]

REPUTATION_ABI = [
    {
        "name": "getReputation",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [
            {"name": "score", "type": "uint256"},
            {"name": "totalInteractions", "type": "uint256"},
            {"name": "lastUpdated", "type": "uint256"},
        ],
    },
]

VALIDATION_ABI = [
    {
        "name": "getValidations",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [
            {"name": "validators", "type": "address[]"},
            {"name": "scores", "type": "uint256[]"},
            {"name": "timestamps", "type": "uint256[]"},
        ],
    },
    {
        "name": "getValidationCount",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


def _is_valid_address(addr: str) -> bool:
    """Check if addr looks like a valid Ethereum address."""
    return bool(addr and re.match(r"^0x[0-9a-fA-F]{40}$", addr))


async def _check_well_known(url: str, timeout: float = 3.0) -> dict | None:
    """
    Check /.well-known/erc-8004 at the service's domain.
    This is the off-chain binding mechanism: a service can publish its
    ERC-8004 agent address at this well-known URL.

    Expected JSON format:
    {
        "agent_address": "0x...",
        "network": "base" | "ethereum" | "base-sepolia",
        "identity_id": "0x..."  (optional)
    }
    """
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        well_known_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/erc-8004"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(well_known_url)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "agent_address" in data:
                    return data
    except Exception:
        pass
    return None


async def _lookup_on_chain(wallet: str) -> dict:
    """
    Attempt to look up ERC-8004 identity/reputation/validation on-chain.
    Returns enriched data if contracts are deployed, otherwise returns pending state.
    """
    if not CONTRACTS_DEPLOYED:
        return {
            "status": "pending",
            "reason": "ERC-8004 contracts not yet confirmed deployed on Base mainnet. "
                      "Standard is in DRAFT status as of 2026-02-26.",
            "identity_id": None,
            "reputation_score": None,
            "validation_count": None,
            "attestations": [],
        }

    # When contracts ARE deployed, use web3 to query them.
    # This code path will be activated by setting CONTRACTS_DEPLOYED = True
    # and updating the contract addresses above.
    try:
        from web3 import Web3  # noqa: PLC0415 — optional dependency
        w3 = Web3(Web3.HTTPProvider(BASE_RPC))

        identity_contract = w3.eth.contract(
            address=Web3.to_checksum_address(ERC8004_IDENTITY_REGISTRY),
            abi=IDENTITY_ABI,
        )
        reputation_contract = w3.eth.contract(
            address=Web3.to_checksum_address(ERC8004_REPUTATION_REGISTRY),
            abi=REPUTATION_ABI,
        )
        validation_contract = w3.eth.contract(
            address=Web3.to_checksum_address(ERC8004_VALIDATION_REGISTRY),
            abi=VALIDATION_ABI,
        )

        checksum_wallet = Web3.to_checksum_address(wallet)

        has_identity = identity_contract.functions.hasIdentity(checksum_wallet).call()
        if not has_identity:
            return {
                "status": "not_registered",
                "identity_id": None,
                "reputation_score": None,
                "validation_count": None,
                "attestations": [],
            }

        identity_id, metadata_str, registered_at = (
            identity_contract.functions.getIdentity(checksum_wallet).call()
        )
        score, total_interactions, last_updated = (
            reputation_contract.functions.getReputation(checksum_wallet).call()
        )
        validation_count = (
            validation_contract.functions.getValidationCount(checksum_wallet).call()
        )

        # Attempt to parse metadata JSON
        metadata = {}
        try:
            metadata = json.loads(metadata_str) if metadata_str else {}
        except Exception:
            metadata = {"raw": metadata_str}

        return {
            "status": "registered",
            "identity_id": "0x" + identity_id.hex() if identity_id else None,
            "registered_at": registered_at,
            "metadata": metadata,
            "reputation_score": score,  # 0-100 scale
            "total_interactions": total_interactions,
            "last_reputation_update": last_updated,
            "validation_count": validation_count,
            "attestations": [],  # Full list requires additional queries
        }
    except ImportError:
        return {
            "status": "pending",
            "reason": "web3 library not installed — install with: pip install web3",
            "identity_id": None,
            "reputation_score": None,
            "validation_count": None,
            "attestations": [],
        }
    except Exception as e:
        logger.warning("ERC-8004 on-chain lookup failed for %s: %s", wallet, e)
        return {
            "status": "error",
            "reason": str(e),
            "identity_id": None,
            "reputation_score": None,
            "validation_count": None,
            "attestations": [],
        }


async def get_trust_profile(
    wallet: str | None = None,
    service_url: str | None = None,
) -> dict:
    """
    Get the full ERC-8004 trust profile for a service.

    Lookup strategy:
    1. If wallet address provided → on-chain lookup
    2. If service_url provided → check /.well-known/erc-8004 for an agent address,
       then do on-chain lookup with that address
    3. Both can be provided — wallet takes precedence for on-chain, URL for well-known check

    Returns:
        {
            "wallet": "0x...",
            "well_known": {...} | null,
            "well_known_url": "https://...",
            "erc8004_registered": bool,
            "identity_id": "0x..." | null,
            "reputation_score": int (0-100) | null,
            "validation_count": int | null,
            "attestations": [...],
            "status": "registered" | "not_registered" | "pending" | "error",
            "fetched_at": int (unix timestamp),
        }
    """
    # Determine the wallet address to use
    resolved_wallet = wallet
    well_known_data = None
    well_known_url = None

    # Check /.well-known/erc-8004 if URL provided
    if service_url:
        parsed = urlparse(service_url)
        if parsed.netloc:
            well_known_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/erc-8004"
            well_known_data = await _check_well_known(service_url)
            if well_known_data and not resolved_wallet:
                agent_addr = well_known_data.get("agent_address")
                if _is_valid_address(agent_addr):
                    resolved_wallet = agent_addr

    # Cache check
    cache_key = resolved_wallet or service_url or ""
    if cache_key in _trust_cache:
        cached = _trust_cache[cache_key]
        if time.time() - cached["fetched_at"] < CACHE_TTL:
            return cached["result"]

    # On-chain lookup
    if resolved_wallet and _is_valid_address(resolved_wallet):
        on_chain = await _lookup_on_chain(resolved_wallet)
    else:
        on_chain = {
            "status": "no_wallet",
            "reason": "No Ethereum wallet address available for this service.",
            "identity_id": None,
            "reputation_score": None,
            "validation_count": None,
            "attestations": [],
        }

    result = {
        "wallet": resolved_wallet,
        "well_known_url": well_known_url,
        "well_known": well_known_data,
        "erc8004_registered": on_chain.get("status") == "registered",
        "identity_id": on_chain.get("identity_id"),
        "reputation_score": on_chain.get("reputation_score"),
        "validation_count": on_chain.get("validation_count"),
        "attestations": on_chain.get("attestations", []),
        "status": on_chain.get("status"),
        "status_reason": on_chain.get("reason"),
        "fetched_at": int(time.time()),
    }

    # Cache the result
    _trust_cache[cache_key] = {"result": result, "fetched_at": time.time()}

    return result


def get_trust_summary(trust_profile: dict) -> dict:
    """
    Returns a compact summary suitable for embedding in /catalog and /discover responses.
    Only includes non-null fields to keep responses clean.
    """
    status = trust_profile.get("status", "unknown")
    summary: dict[str, Any] = {"status": status}

    if trust_profile.get("well_known"):
        summary["well_known_declared"] = True

    if trust_profile.get("erc8004_registered"):
        summary["registered"] = True
        if trust_profile.get("identity_id"):
            summary["identity_id"] = trust_profile["identity_id"]
        if trust_profile.get("reputation_score") is not None:
            summary["reputation_score"] = trust_profile["reputation_score"]
        if trust_profile.get("validation_count") is not None:
            summary["validation_count"] = trust_profile["validation_count"]

    return summary
