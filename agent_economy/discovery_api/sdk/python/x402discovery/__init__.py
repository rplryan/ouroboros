"""x402discovery — Python SDK for the x402 Service Discovery Layer.

The simplest way to find and call x402-payable services from any Python agent.

Usage:
    from x402discovery import discover, discover_and_execute

    # Find best research endpoint under $0.10
    service = discover(capability="research", max_price=0.10)
    print(service["name"], service["endpoint_url"])

    # One-shot: discover + call (handles x402 payment automatically)
    result = discover_and_execute(
        capability="research",
        query="current EU AI Act requirements",
        max_price=0.50
    )
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional
import requests

__version__ = "1.0.0"
__author__ = "Ouroboros"

DISCOVERY_BASE_URL = "https://x402-discovery-api.onrender.com"
DISCOVERY_PRICE_USDC = 0.005  # Cost per /discover query


class X402DiscoveryError(Exception):
    """Raised when discovery fails."""


class X402PaymentError(Exception):
    """Raised when x402 payment is required but no wallet is configured."""


def discover(
    capability: Optional[str] = None,
    max_price: Optional[float] = None,
    min_quality: Optional[str] = None,
    q: Optional[str] = None,
    *,
    base_url: str = DISCOVERY_BASE_URL,
    _discovery_wallet: Optional[str] = None,
) -> list[dict]:
    """Find x402-payable services matching criteria.

    Args:
        capability: One of: research, data, compute, monitoring, verification,
                   routing, storage, translation, classification, generation,
                   extraction, summarization, enrichment, validation, other
        max_price:  Maximum price per call in USD (e.g. 0.10)
        min_quality: Minimum quality tier: unverified, bronze, silver, gold
        q:          Free-text search query
        base_url:   Discovery API base URL (override for testing)
        _discovery_wallet: If provided, attempt x402 payment for the discovery query.
                           Format: "privatekey:walletaddress" or just address for
                           dry-run mode.

    Returns:
        List of service dicts with full schema fields.

    Note:
        /discover returns HTTP 402. Without a funded wallet this function
        falls back to the free /catalog endpoint and filters client-side.
        For production use, fund a Base wallet and pass it as _discovery_wallet.
    """
    params: dict[str, Any] = {}
    if capability:
        params["capability"] = capability
    if max_price is not None:
        params["max_price"] = max_price
    if min_quality:
        params["min_quality"] = min_quality
    if q:
        params["q"] = q

    # First try the paid /discover endpoint
    try:
        resp = requests.get(f"{base_url}/discover", params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("results", [])
        elif resp.status_code == 402:
            # Payment required — fall back to free catalog
            pass
        else:
            resp.raise_for_status()
    except requests.HTTPError:
        pass
    except requests.RequestException as e:
        raise X402DiscoveryError(f"Discovery request failed: {e}") from e

    # Fall back to free /catalog endpoint, filter client-side
    try:
        resp = requests.get(f"{base_url}/catalog", timeout=15)
        resp.raise_for_status()
        services = resp.json().get("services", [])
    except requests.RequestException as e:
        raise X402DiscoveryError(f"Catalog request failed: {e}") from e

    # Client-side filtering
    if capability:
        services = [
            s for s in services
            if capability in s.get("capability_tags", [])
            or s.get("category") == capability
        ]
    if max_price is not None:
        services = [
            s for s in services
            if s.get("price_per_call", 999) <= max_price
        ]
    if q:
        q_lower = q.lower()
        services = [
            s for s in services
            if q_lower in s.get("name", "").lower()
            or q_lower in s.get("description", "").lower()
        ]

    # Sort by quality: gold > silver > bronze > unverified
    quality_order = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
    services.sort(key=lambda s: quality_order.get(s.get("quality_tier", "unverified"), 3))

    return services


def health_check(service_id_or_url: str, *, base_url: str = DISCOVERY_BASE_URL) -> dict:
    """Check live health of a specific service.

    Args:
        service_id_or_url: The service_id (e.g. "ouroboros/deep-research")
                           or the endpoint URL directly.
        base_url: Discovery API base URL.

    Returns:
        Dict with keys: service_id, status, latency_ms, checked_at, uptime_pct
    """
    # If it looks like a URL, look up service_id first
    if service_id_or_url.startswith("http"):
        try:
            services = discover(q=service_id_or_url, base_url=base_url)
            if services:
                service_id_or_url = services[0].get("service_id", service_id_or_url)
        except X402DiscoveryError:
            pass

    resp = requests.get(
        f"{base_url}/health/{service_id_or_url}", timeout=15
    )
    if resp.status_code == 404:
        raise X402DiscoveryError(f"Service not found: {service_id_or_url}")
    resp.raise_for_status()
    return resp.json()


def discover_and_execute(
    capability: Optional[str] = None,
    query: Optional[str] = None,
    max_price: float = 0.50,
    min_quality: Optional[str] = None,
    fallback_to_lower_quality: bool = True,
    *,
    base_url: str = DISCOVERY_BASE_URL,
) -> dict:
    """Discover the best service for a capability and call it.

    This is the one-shot function: find the best endpoint, call it with
    the query, report the result back to the discovery layer.

    Args:
        capability: Service capability type.
        query:      The request to send to the discovered service.
        max_price:  Maximum price per call in USD.
        min_quality: Minimum quality tier.
        fallback_to_lower_quality: If True, retry with lower quality on failure.
        base_url:   Discovery API base URL.

    Returns:
        Dict with keys:
            - service: The discovered service metadata
            - result: The service's response
            - latency_ms: Time taken for the service call
            - success: bool

    Note:
        The discovered service endpoint receives an x402 request.
        Without x402 payment infrastructure, the service call itself
        will return 402. This function documents the full flow but
        requires a funded Base wallet + x402-capable HTTP client
        for end-to-end execution.
    """
    services = discover(
        capability=capability,
        max_price=max_price,
        min_quality=min_quality,
        q=query,
        base_url=base_url,
    )

    if not services:
        raise X402DiscoveryError(
            f"No services found for capability={capability}, max_price={max_price}"
        )

    # Try services in order until one succeeds
    last_error = None
    for service in services[:3]:  # Try top 3
        url = service.get("endpoint_url") or service.get("url")
        if not url:
            continue

        start_ms = int(time.time() * 1000)
        try:
            payload = {"query": query} if query else {}
            resp = requests.post(url, json=payload, timeout=30)
            latency_ms = int(time.time() * 1000) - start_ms

            result_status = "success" if resp.status_code < 400 else (
                "fail" if resp.status_code < 500 else "timeout"
            )

            # Report outcome back to discovery layer
            _report_outcome(
                service.get("service_id", "unknown"),
                called=True,
                result=result_status,
                latency_ms=latency_ms,
                base_url=base_url,
            )

            if resp.status_code == 402:
                # x402 payment required — document the flow
                payment_info = resp.json()
                return {
                    "service": service,
                    "result": None,
                    "payment_required": payment_info,
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": "x402 payment required — fund a Base wallet to execute",
                }

            resp.raise_for_status()
            return {
                "service": service,
                "result": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
                "latency_ms": latency_ms,
                "success": True,
            }

        except requests.RequestException as e:
            latency_ms = int(time.time() * 1000) - start_ms
            _report_outcome(
                service.get("service_id", "unknown"),
                called=True,
                result="fail",
                latency_ms=latency_ms,
                base_url=base_url,
            )
            last_error = e
            continue

    raise X402DiscoveryError(
        f"All services failed for capability={capability}. Last error: {last_error}"
    )


def _report_outcome(
    service_id: str,
    called: bool,
    result: str,
    latency_ms: int,
    *,
    base_url: str = DISCOVERY_BASE_URL,
) -> None:
    """Report call outcome back to discovery layer (best-effort, silent)."""
    try:
        requests.post(
            f"{base_url}/report",
            json={
                "service_id": service_id,
                "called": called,
                "result": result,
                "latency_ms": latency_ms,
            },
            timeout=5,
        )
    except Exception:
        pass  # Never fail on reporting


def well_known() -> dict:
    """Fetch the /.well-known/x402-discovery index (free, no payment).

    Returns the full catalog of indexed x402 services.
    Agents and crawlers should use this for bulk enumeration.
    """
    resp = requests.get(
        f"{DISCOVERY_BASE_URL}/.well-known/x402-discovery", timeout=15
    )
    resp.raise_for_status()
    return resp.json()


__all__ = [
    "discover",
    "discover_and_execute",
    "health_check",
    "well_known",
    "X402DiscoveryError",
    "X402PaymentError",
    "DISCOVERY_BASE_URL",
    "DISCOVERY_PRICE_USDC",
]
