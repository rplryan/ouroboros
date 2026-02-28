"""
Discovery Attestation Module — x402 Service Discovery API

Provides Ed25519-signed JWT attestations of service quality measurements.
Used as the discoveryAttestation field in the ERC-8004 coldStartSignals spec.

Key infrastructure:
- Ed25519 key pair: private key in ATTEST_PRIVATE_KEY_B64URL env var
- GET /jwks  — public key for offline verification (JWK Set / RFC 7517)
- GET /v1/attest/:serviceId — signed JWT with quality measurements

JWT payload shape:
{
  "iss": "https://x402-discovery-api.onrender.com",
  "sub": "<serviceId>",
  "iat": <unix>, "exp": <unix + 86400>, "jti": "<uuid>",
  "service":    { id, name, url, category, price_usd, network },
  "quality":    { uptime_pct, avg_latency_ms, total_checks, successful_checks,
                  health_status, last_checked },
  "facilitator":{ compatible, count, recommended },
  "indexed_at": <iso8601>,
  "indexed_by": "x402-discovery-api",
  "spec":       "https://github.com/coinbase/x402/issues/1375"
}

Verification (Python):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    import base64, json

    # Fetch public key from /jwks
    jwk = requests.get("https://x402-discovery-api.onrender.com/jwks").json()["keys"][0]
    raw = base64.urlsafe_b64decode(jwk["x"] + "==")
    pub = Ed25519PublicKey.from_public_bytes(raw)

    # Decode + verify
    header_b64, payload_b64, sig_b64 = token.split(".")
    signing_input = f"{header_b64}.{payload_b64}".encode()
    sig = base64.urlsafe_b64decode(sig_b64 + "==")
    pub.verify(sig, signing_input)   # raises InvalidSignature if tampered
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Generic ERC-8004 trust provider registry
# ---------------------------------------------------------------------------
# Any ERC-8004-compliant trust provider can be listed here.
# To be listed, a provider must publish:
#   - A JWKS endpoint (for offline signature verification)
#   - A /v1/trust endpoint that accepts providerAddress and returns a signed trust profile
# InsumerAPI is one provider; others will be added as the ecosystem matures.

KNOWN_TRUST_PROVIDERS: list[dict] = [
    {
        "slug": "insumerapi",
        "name": "InsumerAPI",
        "trust_url": "https://insumermodel.com/v1/trust",
        "jwks_url": "https://insumermodel.com/.well-known/jwks.json",
        "description": "On-chain wallet trust scoring — stablecoin holdings, staking, DJD Agent Score",
        "erc8004_registered": True,
    },
    # Add more ERC-8004 trust providers here as they become available.
    # Schema: slug (str), name (str), trust_url (str), jwks_url (str),
    #         description (str), erc8004_registered (bool)
]


async def fetch_chain_verifications(
    provider_address: str | None,
    timeout: float = 3.0,
) -> list[dict]:
    """
    Query all known ERC-8004 trust providers for a given on-chain provider address.

    Each result includes:
      - provider: slug identifying the trust provider
      - jwks: URL for offline verification of the provider's signature
      - raw: the raw response from the provider (may contain trustId, compositeScore, etc.)
      - error: set if the provider was unreachable or returned an error

    The caller (e.g. build_attestation) embeds this list as `chainVerifications`.
    Clients can independently verify each entry's signature against the provider's JWKS.
    """
    if not provider_address:
        return []

    results: list[dict] = []
    import httpx as _httpx

    async with _httpx.AsyncClient(timeout=timeout) as client:
        for provider in KNOWN_TRUST_PROVIDERS:
            entry: dict = {
                "provider": provider["slug"],
                "jwks": provider["jwks_url"],
                "queried_address": provider_address,
            }
            try:
                resp = await client.post(
                    provider["trust_url"],
                    json={"providerAddress": provider_address},
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    entry["raw"] = resp.json()
                elif resp.status_code == 404:
                    entry["error"] = "address_not_registered"
                else:
                    entry["error"] = f"http_{resp.status_code}"
            except Exception as exc:
                entry["error"] = f"unreachable: {str(exc)[:80]}"
            results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ISSUER: str = os.getenv("SERVICE_BASE_URL", "https://x402-discovery-api.onrender.com")
_PRIVATE_KEY_B64: str = os.getenv("ATTEST_PRIVATE_KEY_B64URL", "")
_PUBLIC_KEY_B64: str = os.getenv("ATTEST_PUBLIC_KEY_B64URL", "")


def _compute_kid(public_b64: str) -> str:
    """RFC 7638-style JWK thumbprint (SHA-256 of canonical JWK) used as key ID."""
    if not public_b64:
        return "unknown"
    canonical = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": public_b64},
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


_KEY_ID: str = _compute_kid(_PUBLIC_KEY_B64)

# ---------------------------------------------------------------------------
# Lazy key loading
# ---------------------------------------------------------------------------

_private_key = None
_keys_loaded: bool = False


def _load_keys() -> bool:
    """Load Ed25519 private key from env var on first call. Thread-safe enough for read-only use."""
    global _private_key, _keys_loaded
    if _keys_loaded:
        return _private_key is not None

    _keys_loaded = True

    if not _PRIVATE_KEY_B64 or not _PUBLIC_KEY_B64:
        log.warning(
            "Attestation keys not configured — "
            "set ATTEST_PRIVATE_KEY_B64URL and ATTEST_PUBLIC_KEY_B64URL env vars."
        )
        return False

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        raw = base64.urlsafe_b64decode(_PRIVATE_KEY_B64 + "==")
        _private_key = Ed25519PrivateKey.from_private_bytes(raw)
        log.info("Attestation private key loaded. kid=%s", _KEY_ID)
        return True
    except Exception as exc:
        log.error("Failed to load attestation key: %s", exc)
        return False


def is_configured() -> bool:
    """Return True if the attestation signing key is available."""
    return _load_keys()


# ---------------------------------------------------------------------------
# JWKS
# ---------------------------------------------------------------------------


def get_jwks() -> dict:
    """Return a JWK Set (RFC 7517) containing the Ed25519 verification key."""
    if not _PUBLIC_KEY_B64:
        return {"keys": []}
    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "x": _PUBLIC_KEY_B64,
                "kid": _KEY_ID,
                "use": "sig",
                "alg": "EdDSA",
            }
        ]
    }


# ---------------------------------------------------------------------------
# JWT signing (manual — avoids PyJWT's limited EdDSA path on older versions)
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _sign_jwt(payload: dict) -> str:
    """Produce a compact JWT string signed with Ed25519."""
    _load_keys()
    if _private_key is None:
        raise RuntimeError("Attestation private key not loaded")

    header = {"alg": "EdDSA", "typ": "JWT", "kid": _KEY_ID}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    signature = _private_key.sign(signing_input)
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


# ---------------------------------------------------------------------------
# Attestation builder
# ---------------------------------------------------------------------------


def build_attestation(
    service_entry: dict,
    health_stats: dict,
    last_health_check: Optional[dict],
    chain_verifications: Optional[list] = None,
) -> Optional[str]:
    """
    Build and sign a discovery attestation JWT for a single service.

    Args:
        service_entry:       Registry entry dict (id/service_id, name, url, category, price_usd, …)
        health_stats:        Dict with uptime_pct, avg_latency_ms, total_checks, successful_checks
        last_health_check:   Dict with checked_at, is_up, latency_ms — or None
        chain_verifications: List of ERC-8004 trust provider results (from fetch_chain_verifications)

    Returns:
        Compact JWT string, or None if keys not configured / signing fails.
    """
    if not _load_keys():
        return None

    now = int(datetime.now(timezone.utc).timestamp())
    service_id = service_entry.get("service_id") or service_entry.get("id", "unknown")

    payload: dict = {
        # Standard JWT claims
        "iss": _ISSUER,
        "sub": service_id,
        "iat": now,
        "exp": now + 86400,       # 24-hour validity
        "jti": str(uuid.uuid4()),

        # Service identity snapshot
        "service": {
            "id": service_id,
            "name": service_entry.get("name", ""),
            "url": service_entry.get("url", ""),
            "category": service_entry.get("category", ""),
            "price_usd": service_entry.get("price_usd"),
            "network": service_entry.get("network", "base"),
        },

        # Quality measurements — the oracle value we provide
        "quality": {
            "uptime_pct": health_stats.get("uptime_pct"),
            "avg_latency_ms": health_stats.get("avg_latency_ms"),
            "total_checks": health_stats.get("total_checks", 0),
            "successful_checks": health_stats.get("successful_checks", 0),
            "health_status": service_entry.get("health_status", "unverified"),
            "last_checked": last_health_check["checked_at"] if last_health_check else None,
        },

        # Facilitator compatibility
        "facilitator": {
            "compatible": service_entry.get("facilitator_compatible", False),
            "count": service_entry.get("facilitator_count", 0),
            "recommended": service_entry.get("recommended_facilitator"),
        },

        # Generic chain verifications from ERC-8004 trust providers.
        # Each entry includes: provider (slug), jwks (verification URL), and
        # raw provider response (independently verifiable against provider's JWKS).
        # Empty list = no provider address available or all providers unreachable.
        "chainVerifications": chain_verifications or [],

        # Provenance
        "indexed_at": service_entry.get("listed_at", datetime.now(timezone.utc).isoformat()),
        "indexed_by": "x402-discovery-api",
        "spec": "https://github.com/coinbase/x402/issues/1375",
    }

    try:
        return _sign_jwt(payload)
    except Exception as exc:
        log.error("Failed to sign attestation for %s: %s", service_id, exc)
        return None
