"""
x402discovery — Python client for the x402 Service Discovery API.

Browse (catalog listing) and health checks are free.
The /discover endpoint is x402-gated ($0.005 USDC); this client uses /catalog
and filters locally so discover() works without any payment setup.

Usage:
    from x402discovery import discover, browse, health_check

    # Free: browse all services
    services = browse()

    # Free: filtered discovery (calls /catalog and filters locally)
    results = discover(capability="research", max_price=0.10)
    results = discover(query="crypto prices")

    # Free: live health check
    status = health_check("x402engine-crypto-prices")
"""

import requests
from typing import Optional, List, Dict, Any

from .exceptions import ServiceNotFound, DiscoveryAPIError

DEFAULT_BASE_URL = "https://x402-discovery-api.onrender.com"

_QUALITY_RANK = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}


class X402DiscoveryClient:
    """Client for the x402 Service Discovery API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "x402discovery/0.1.1 python-requests",
                "Accept": "application/json",
            }
        )

    def browse(self) -> List[Dict[str, Any]]:
        """
        Return all registered services from /catalog. Free — no payment required.

        Returns:
            List of endpoint dicts. Each dict has: id, name, description, url,
            category, price_usd, network, tags, capability_tags, uptime_pct,
            avg_latency_ms, status, health_status, llm_usage_prompt, etc.
        """
        resp = self._session.get(
            f"{self.base_url}/catalog", timeout=self.timeout
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("endpoints", []) if isinstance(data, dict) else data
        raise DiscoveryAPIError(
            f"Catalog request failed: {resp.status_code} {resp.text[:200]}"
        )

    def discover(
        self,
        capability: Optional[str] = None,
        max_price: float = 0.50,
        query: Optional[str] = None,
        min_quality: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Discover x402 services by filtering the free catalog locally.

        Args:
            capability: Filter by capability_tag or category
                        (e.g. "research", "data", "compute", "monitoring")
            max_price: Maximum price per call in USD (default 0.50)
            query: Free-text search against service name and description
            min_quality: Minimum health_status tier (gold|silver|bronze|unverified)

        Returns:
            Matching services sorted by quality tier then price (cheapest first)
        """
        services = self.browse()

        if capability:
            services = [
                s for s in services
                if capability in s.get("capability_tags", [])
                or s.get("category") == capability
            ]

        services = [s for s in services if (s.get("price_usd") or 999) <= max_price]

        if query:
            q = query.lower()
            services = [
                s for s in services
                if q in s.get("name", "").lower()
                or q in s.get("description", "").lower()
            ]

        if min_quality:
            min_rank = _QUALITY_RANK.get(min_quality, 3)
            services = [
                s for s in services
                if _QUALITY_RANK.get(s.get("health_status", "unverified"), 3) <= min_rank
            ]

        services.sort(key=lambda s: (
            _QUALITY_RANK.get(s.get("health_status", "unverified"), 3),
            s.get("price_usd") or 999,
        ))

        return services

    def health_check(self, service_id: str) -> Dict[str, Any]:
        """
        Live health check for a specific service. Free — no payment required.

        Args:
            service_id: The service ID from the registry

        Returns:
            Dict with status, latency_ms, uptime_pct, last_checked
        """
        resp = self._session.get(
            f"{self.base_url}/health/{service_id}", timeout=self.timeout
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            raise ServiceNotFound(f"Service not found: {service_id!r}")
        raise DiscoveryAPIError(
            f"Health check failed: {resp.status_code} {resp.text[:200]}"
        )

    def discover_and_execute(
        self,
        capability: Optional[str] = None,
        max_price: float = 0.50,
        query: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Discover services and return the best match ready for execution.

        Note: Actually calling the selected service requires x402 payment setup
        on the caller's side (construct the X-PAYMENT header via an x402 facilitator).

        Returns:
            The top-ranked matching service dict, or None if no matches.
        """
        results = self.discover(capability=capability, max_price=max_price, query=query)
        return results[0] if results else None

    def register(
        self,
        name: str,
        description: str,
        url: str,
        category: str,
        price_usd: float,
        tags: Optional[List[str]] = None,
        wallet_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register a new x402 service. Free.

        Args:
            name: Human-readable name
            description: One sentence description for LLM consumers
            url: The x402-gated endpoint URL
            category: research|data|compute|agent|utility
            price_usd: Price per call in USD
            tags: Optional list of tags
            wallet_address: Payment recipient wallet (optional)

        Returns:
            Registration confirmation with service_id
        """
        payload: Dict[str, Any] = {
            "name": name,
            "description": description,
            "url": url,
            "category": category,
            "price_usd": price_usd,
        }
        if tags:
            payload["tags"] = tags
        if wallet_address:
            payload["wallet_address"] = wallet_address

        resp = self._session.post(
            f"{self.base_url}/register", json=payload, timeout=self.timeout
        )
        if resp.status_code in (200, 201):
            return resp.json()
        raise DiscoveryAPIError(
            f"Registration failed: {resp.status_code} {resp.text[:200]}"
        )

    def well_known(self) -> Dict[str, Any]:
        """
        Fetch the /.well-known/x402-discovery index. Free, machine-readable.
        """
        resp = self._session.get(
            f"{self.base_url}/.well-known/x402-discovery", timeout=self.timeout
        )
        if resp.status_code == 200:
            return resp.json()
        raise DiscoveryAPIError(
            f"Well-known request failed: {resp.status_code}"
        )


# Module-level convenience functions using a shared default client
_default_client = X402DiscoveryClient()


def discover(
    capability: Optional[str] = None,
    max_price: float = 0.50,
    query: Optional[str] = None,
    min_quality: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Discover x402 services by filtering the free /catalog locally.

    Args:
        capability: Filter by capability_tag or category
        max_price: Maximum price per call in USD (default 0.50)
        query: Free-text search against name and description
        min_quality: Minimum health_status tier (gold|silver|bronze|unverified)

    Returns:
        Matching services sorted by quality tier then price
    """
    return _default_client.discover(
        capability=capability, max_price=max_price, query=query, min_quality=min_quality
    )


def browse() -> List[Dict[str, Any]]:
    """Return all services from the free /catalog endpoint."""
    return _default_client.browse()


def health_check(service_id: str) -> Dict[str, Any]:
    """Live health check for a registered service. Free."""
    return _default_client.health_check(service_id)


def discover_and_execute(
    capability: Optional[str] = None,
    max_price: float = 0.50,
    query: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Discover the best matching service and return it ready for execution."""
    return _default_client.discover_and_execute(
        capability=capability, max_price=max_price, query=query
    )
