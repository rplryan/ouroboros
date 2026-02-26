"""ERC-8004 trust layer lookup for the x402 Service Discovery API.

ERC-8004 provides on-chain identity and reputation for AI agents.
Contracts are deployed on Base mainnet (same address as Ethereum mainnet).

IdentityRegistry:  0x8004A169FB4a3325136EB29fA0ceB6D2e539a432
ReputationRegistry: 0x8004BAa17C55a88189AE136b182e5fdA19dE9b63

We use raw JSON-RPC eth_call over httpx — no web3.py dependency.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("x402-discovery.erc8004")

# ---------------------------------------------------------------------------
# Contract addresses — Base mainnet (same as Ethereum mainnet)
# ---------------------------------------------------------------------------

IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
REPUTATION_REGISTRY = "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63"
BASE_RPC = "https://mainnet.base.org"

# ---------------------------------------------------------------------------
# ABI-encoded function selectors (keccak256 first 4 bytes)
# Standard ERC-721 + ERC-721Enumerable selectors
# ---------------------------------------------------------------------------

SEL_BALANCE_OF           = "70a08231"  # balanceOf(address)
SEL_TOKEN_OF_OWNER_IDX   = "2f745c59"  # tokenOfOwnerByIndex(address,uint256)
SEL_TOKEN_URI            = "c87b56dd"  # tokenURI(uint256)
SEL_TOTAL_SUPPLY         = "18160ddd"  # totalSupply()
# ReputationRegistry: getClients(uint256) — keccak256("getClients(uint256)") first 4 bytes
SEL_GET_CLIENTS          = "27d23fb5"  # getClients(uint256)

# ---------------------------------------------------------------------------
# Simple in-process cache: {wallet_address_lower: (timestamp, result)}
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL_SECS = 300  # 5 minutes


def _encode_address(addr: str) -> str:
    """Encode an address as 32-byte ABI hex (left-padded)."""
    addr = addr.lower().removeprefix("0x")
    return addr.zfill(64)


def _encode_uint256(n: int) -> str:
    """Encode a uint256 as 32-byte ABI hex."""
    return hex(n)[2:].zfill(64)


def _decode_uint256(hex_str: str) -> int:
    """Decode a 32-byte ABI-encoded uint256."""
    return int(hex_str.removeprefix("0x"), 16)


async def _eth_call(contract: str, data: str, timeout: float = 8.0) -> str | None:
    """Execute an eth_call. Returns hex result string or None on failure."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": contract, "data": f"0x{data}"}, "latest"],
        "id": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(BASE_RPC, json=payload)
            data_out = resp.json()
            result = data_out.get("result")
            if result and result != "0x":
                return result
    except Exception as exc:
        log.debug("eth_call failed for %s: %s", contract, exc)
    return None


async def _get_balance(wallet: str) -> int:
    """How many agent NFTs does this wallet own (0 = not registered)."""
    data = SEL_BALANCE_OF + _encode_address(wallet)
    result = await _eth_call(IDENTITY_REGISTRY, data)
    if result:
        return _decode_uint256(result)
    return 0


async def _get_first_agent_id(wallet: str) -> int | None:
    """Get first agentId (tokenId) owned by this wallet."""
    data = SEL_TOKEN_OF_OWNER_IDX + _encode_address(wallet) + _encode_uint256(0)
    result = await _eth_call(IDENTITY_REGISTRY, data)
    if result:
        return _decode_uint256(result)
    return None


async def _get_agent_uri(agent_id: int) -> str | None:
    """Get the agentURI for an agentId (returns JSON profile URL)."""
    data = SEL_TOKEN_URI + _encode_uint256(agent_id)
    result = await _eth_call(IDENTITY_REGISTRY, data)
    if not result:
        return None
    # Result is ABI-encoded dynamic string: offset(32) + length(32) + utf8 data
    hex_data = result.removeprefix("0x")
    try:
        # Skip first 32 bytes (offset), read length from next 32 bytes
        length = int(hex_data[64:128], 16)
        # Read `length` bytes of string data
        string_hex = hex_data[128:128 + length * 2]
        return bytes.fromhex(string_hex).decode("utf-8")
    except Exception:
        return None


async def _get_reputation_clients(agent_id: int) -> int:
    """Get count of unique clients who gave feedback for this agent."""
    data = SEL_GET_CLIENTS + _encode_uint256(agent_id)
    result = await _eth_call(REPUTATION_REGISTRY, data)
    if not result:
        return 0
    # Result is ABI-encoded address[]: offset(32) + length(32) + addresses
    hex_data = result.removeprefix("0x")
    try:
        if len(hex_data) < 128:
            return 0
        count = int(hex_data[64:128], 16)
        return count
    except Exception:
        return 0


async def lookup_erc8004(wallet_address: str) -> dict:
    """Look up ERC-8004 trust profile for a wallet address.

    Returns dict with:
    - registered: bool
    - agent_id: int | None
    - agent_uri: str | None
    - reputation_count: int (number of unique clients who gave feedback)
    - verified: bool (registered + at least 1 reputation entry)
    - network: str
    - error: str | None
    """
    wallet_lower = wallet_address.lower()

    # Cache hit
    if wallet_lower in _cache:
        ts, cached = _cache[wallet_lower]
        if time.time() - ts < CACHE_TTL_SECS:
            return cached

    empty: dict[str, Any] = {
        "registered": False,
        "agent_id": None,
        "agent_uri": None,
        "reputation_count": 0,
        "verified": False,
        "network": "base",
        "error": None,
    }

    try:
        balance = await _get_balance(wallet_lower)
        if balance == 0:
            _cache[wallet_lower] = (time.time(), empty)
            return empty

        agent_id = await _get_first_agent_id(wallet_lower)
        if agent_id is None:
            _cache[wallet_lower] = (time.time(), empty)
            return empty

        # Fetch URI and reputation in parallel
        agent_uri, rep_count = await asyncio.gather(
            _get_agent_uri(agent_id),
            _get_reputation_clients(agent_id),
        )

        result: dict[str, Any] = {
            "registered": True,
            "agent_id": agent_id,
            "agent_uri": agent_uri,
            "reputation_count": rep_count,
            "verified": rep_count > 0,
            "network": "base",
            "error": None,
        }
        _cache[wallet_lower] = (time.time(), result)
        return result

    except Exception as exc:
        log.warning("ERC-8004 lookup failed for %s: %s", wallet_address, exc)
        error_result = {**empty, "error": "lookup_failed"}
        _cache[wallet_lower] = (time.time(), error_result)
        return error_result
