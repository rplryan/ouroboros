"""
ERC-8004 Trust Layer Integration for x402 Service Discovery API.

ERC-8004 is an Ethereum standard (launched Jan 29, 2026) providing decentralized
AI agent trust via three on-chain registries:
  - Identity Registry  — unique on-chain agent identifiers
  - Reputation Registry — verifiable interaction scores
  - Validation Registry — third-party attestations

Reference: https://eips.ethereum.org/EIPS/eip-8004
GitHub:    https://github.com/erc-8004/erc-8004-contracts

Contract addresses (Ethereum mainnet + Base mainnet — same addresses):
  Identity Registry:   0x1234... (TBC — see DEPLOYMENT_STATUS below)
  Reputation Registry: 0x5678... (TBC)
  Validation Registry: 0x9abc... (TBC)

DEPLOYMENT STATUS (as of Feb 2026):
  The EIP was published Jan 29, 2026 and is in DRAFT status.
  Reference implementation is available at the GitHub repo above,
  but MAINNET DEPLOYMENT HAS NOT BEEN CONFIRMED with public RPC verification.
  This module is structured to go live immediately once addresses are confirmed.

  Until then: `get_trust_profile()` returns status="draft_standard" with a
  `.well-known/erc8004.json` check for services that self-attest.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ERC-8004 Contract Addresses
# Source: https://github.com/erc-8004/erc-8004-contracts
# Status: DRAFT — addresses extracted from repo README/deployments.
#         Verified on-chain pending confirmation.
# ---------------------------------------------------------------------------

# These are placeholders until mainnet deployment is publicly confirmed.
# Set to None to disable on-chain lookup until verified.
IDENTITY_REGISTRY_ADDRESS: Optional[str] = None   # "0x..." — TBC
REPUTATION_REGISTRY_ADDRESS: Optional[str] = None  # "0x..." — TBC
VALIDATION_REGISTRY_ADDRESS: Optional[str] = None  # "0x..." — TBC

# Base mainnet RPC (free, no API key required)
BASE_RPC_URL = "https://mainnet.base.org"
ETH_RPC_URL = "https://eth.llamarpc.com"

# Minimal ABI for read-only registry calls
# Based on ERC-8004 spec interface (IERC8004IdentityRegistry, etc.)
IDENTITY_ABI_MINIMAL = [
    {
        "name": "identityOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [
            {"name": "identityId", "type": "bytes32"},
            {"name": "registeredAt", "type": "uint256"},
            {"name": "metadataURI", "type": "string"},
        ],
    },
    {
        "name": "isRegistered",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]

REPUTATION_ABI_MINIMAL = [
    {
        "name": "reputationOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [
            {"name": "score", "type": "uint256"},
            {"name": "interactions", "type": "uint256"},
            {"name": "lastUpdated", "type": "uint256"},
        ],
    },
]

VALIDATION_ABI_MINIMAL = [
    {
        "name": "validationCountOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "agent", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getValidations",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "agent", "type": "address"},
            {"name": "offset", "type": "uint256"},
            {"name": "limit", "type": "uint256"},
        ],
        "outputs": [
            {
                "name": "validations",
                "type": "tuple[]",
                "components": [
                    {"name": "validator", "type": "address"},
                    {"name": "score", "type": "uint256"},
                    {"name": "attestedAt", "type": "uint256"},
                    {"name": "metadataURI", "type": "string"},
                ],
            }
        ],
    },
]


# ---------------------------------------------------------------------------
# Well-known self-attestation check
# ---------------------------------------------------------------------------

async def _check_well_known(service_url: str) -> dict:
    """
    Check if a service has self-attested ERC-8004 identity via
    /.well-known/erc8004.json (analogous to /.well-known/x402.json).

    Returns parsed attestation or empty dict.
    """
    if not service_url:
        return {}

    # Normalize to base URL
    base = service_url.rstrip("/")
    if not base.startswith("http"):
        return {}

    # Strip path to get root
    from urllib.parse import urlparse
    parsed = urlparse(base)
    root = f"{parsed.scheme}://{parsed.netloc}"

    well_known_url = f"{root}/.well-known/erc8004.json"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(well_known_url)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "well_known_verified": True,
                    "well_known_url": well_known_url,
                    "self_attested": data,
                }
    except Exception:
        pass
    return {"well_known_verified": False}


# ---------------------------------------------------------------------------
# On-chain lookup (Web3 / JSON-RPC)
# ---------------------------------------------------------------------------

async def _eth_call(rpc_url: str, contract: str, data: str) -> Optional[str]:
    """Low-level eth_call via JSON-RPC. Returns hex result or None on error."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": contract, "data": data}, "latest"],
        "id": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(rpc_url, json=payload)
            result = resp.json()
            if "result" in result and result["result"] != "0x":
                return result["result"]
    except Exception as e:
        log.debug("eth_call failed: %s", e)
    return None


def _encode_is_registered(address: str) -> str:
    """Encode isRegistered(address) call data."""
    # keccak256("isRegistered(address)")[:4] = function selector
    # isRegistered selector: 0xc4552791
    addr_padded = address.lower().replace("0x", "").zfill(64)
    return f"0xc4552791{addr_padded}"


def _decode_bool(hex_result: Optional[str]) -> Optional[bool]:
    """Decode a boolean from eth_call result."""
    if not hex_result:
        return None
    try:
        val = int(hex_result, 16)
        return val != 0
    except Exception:
        return None


def _decode_uint256(hex_result: Optional[str]) -> Optional[int]:
    """Decode first uint256 from eth_call result."""
    if not hex_result:
        return None
    try:
        # Take first 32 bytes (64 hex chars) after 0x prefix
        stripped = hex_result[2:] if hex_result.startswith("0x") else hex_result
        if len(stripped) < 64:
            return None
        return int(stripped[:64], 16)
    except Exception:
        return None


async def _lookup_onchain(wallet: str) -> dict:
    """
    Attempt on-chain ERC-8004 lookup for a wallet address.

    Returns dict with on-chain data or status="contracts_not_deployed" if
    contract addresses are not yet confirmed.
    """
    if not all([IDENTITY_REGISTRY_ADDRESS, REPUTATION_REGISTRY_ADDRESS]):
        return {
            "onchain_status": "contracts_not_deployed",
            "note": (
                "ERC-8004 contract addresses on Base/Ethereum mainnet not yet confirmed. "
                "Standard is in DRAFT (launched Jan 29, 2026). "
                "On-chain lookup will activate automatically once addresses are confirmed."
            ),
        }

    # Check identity registration
    is_reg_data = _encode_is_registered(wallet)
    is_reg_hex = await _eth_call(BASE_RPC_URL, IDENTITY_REGISTRY_ADDRESS, is_reg_data)
    is_registered = _decode_bool(is_reg_hex)

    if not is_registered:
        # Try Ethereum mainnet as fallback
        is_reg_hex_eth = await _eth_call(ETH_RPC_URL, IDENTITY_REGISTRY_ADDRESS, is_reg_data)
        is_registered = _decode_bool(is_reg_hex_eth)

    return {
        "onchain_status": "looked_up",
        "is_registered": is_registered,
        "identity_id": None,   # requires identityOf() decode (bytes32 + string)
        "reputation_score": None,  # requires reputationOf() decode
        "validation_count": None,  # requires validationCountOf() decode
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _noop_task() -> dict:
    """Async noop — returns empty dict."""
    return {}


async def get_trust_profile(
    wallet: Optional[str] = None,
    service_url: Optional[str] = None,
) -> dict:
    """
    Return full ERC-8004 trust profile for a wallet address and/or service URL.

    Performs:
    1. Well-known self-attestation check (/.well-known/erc8004.json)
    2. On-chain registry lookup (if contract addresses are confirmed)

    Args:
        wallet: Ethereum address (0x...)
        service_url: Service URL (used for well-known check and registry lookup by URL)

    Returns:
        Trust profile dict with:
        - erc8004_status: "registered" | "not_registered" | "draft_standard" | "unknown"
        - identity_id: bytes32 on-chain identity ID or None
        - reputation_score: 0-100 normalized score or None
        - validation_count: number of third-party attestations or None
        - well_known_verified: whether service self-attests via /.well-known/erc8004.json
        - note: human-readable status explanation
    """
    result: dict = {
        "wallet": wallet,
        "service_url": service_url,
        "erc8004_status": "unknown",
        "identity_id": None,
        "reputation_score": None,
        "validation_count": None,
        "well_known_verified": False,
        "registered": False,
        "spec_version": "ERC-8004 (DRAFT, Jan 29 2026)",
        "spec_url": "https://eips.ethereum.org/EIPS/eip-8004",
    }

    tasks = []

    # Well-known check (runs if we have a URL)
    if service_url:
        tasks.append(_check_well_known(service_url))
    else:
        tasks.append(_noop_task())

    # On-chain check (runs if we have a wallet)
    if wallet and re.match(r"^0x[0-9a-fA-F]{40}$", wallet):
        tasks.append(_lookup_onchain(wallet))
    else:
        tasks.append(_noop_task())

    well_known_data, onchain_data = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge well-known data
    if isinstance(well_known_data, dict):
        result["well_known_verified"] = well_known_data.get("well_known_verified", False)
        if well_known_data.get("self_attested"):
            result["self_attested"] = well_known_data["self_attested"]

    # Merge on-chain data
    if isinstance(onchain_data, dict):
        result["onchain"] = onchain_data
        if onchain_data.get("onchain_status") == "contracts_not_deployed":
            result["erc8004_status"] = "draft_standard"
            result["note"] = onchain_data["note"]
        elif onchain_data.get("is_registered") is True:
            result["erc8004_status"] = "registered"
            result["registered"] = True
            result["identity_id"] = onchain_data.get("identity_id")
            result["reputation_score"] = onchain_data.get("reputation_score")
            result["validation_count"] = onchain_data.get("validation_count")
        elif onchain_data.get("is_registered") is False:
            result["erc8004_status"] = "not_registered"
        else:
            result["erc8004_status"] = "draft_standard"
            result["note"] = (
                "ERC-8004 is in DRAFT status (launched Jan 29, 2026). "
                "On-chain lookup pending contract address confirmation on Base/Ethereum mainnet."
            )
    else:
        result["erc8004_status"] = "draft_standard"
        result["note"] = (
            "ERC-8004 is in DRAFT status (launched Jan 29, 2026). "
            "On-chain lookup pending contract address confirmation on Base/Ethereum mainnet."
        )

    return result


async def get_trust_summary(wallet: Optional[str] = None) -> dict:
    """
    Return a condensed trust summary suitable for embedding in catalog entries.

    Returns dict with just: status, registered, reputation_score, validation_count
    """
    if not wallet:
        return {
            "status": "no_wallet",
            "registered": False,
            "reputation_score": None,
            "validation_count": None,
        }
    profile = await get_trust_profile(wallet=wallet)
    return {
        "status": profile.get("erc8004_status", "unknown"),
        "registered": profile.get("registered", False),
        "reputation_score": profile.get("reputation_score"),
        "validation_count": profile.get("validation_count"),
        "well_known_verified": profile.get("well_known_verified", False),
    }
