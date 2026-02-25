"""
x402discovery — Python client for the x402 Service Discovery API.

The discovery API is itself x402-gated: discovery queries cost $0.001 USDC.
Browse (catalog listing) and health checks are free.

Usage:
    from x402discovery import discover, browse, health_check

    # Free: browse all services
    services = browse(category="research")

    # Paid: ranked discovery ($0.001 USDC per call)
    # Requires x402 payment header (handled by facilitator or manual payment)
    results = discover("real-time crypto prices", max_price=0.01)

    # Free: live health check
    status = health_check("x402engine-crypto-prices")
"""

import requests
from typing import Optional, List, Dict, Any

from .exceptions import PaymentRequired, ServiceNotFound, DiscoveryAPIError

DEFAULT_BASE_URL = "https://x402-discovery-api.onrender.com"


class X402DiscoveryClient:
    """Client for the x402 Service Discovery API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 30,
        x402_payment_header: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.x402_payment_header = x402_payment_header
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "x402discovery/0.1.0 python-requests",
                "Accept": "application/json",
            }
        )
        if x402_payment_header:
            self._session.headers.update({"X-PAYMENT": x402_payment_header})

    def browse(
        self,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List registered services. Free — no payment required.

        Args:
            category: Filter by category (research|data|compute|agent|utility)
            limit: Max results to return (default 50)

        Returns:
            List of service dicts with quality signals
        """
        params: Dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category

        resp = self._session.get(
            f"{self.base_url}/catalog", params=params, timeout=self.timeout
        )

        if resp.status_code == 200:
            data = resp.json()
            services = (
                data
                if isinstance(data, list)
                else data.get("services", data.get("endpoints", []))
            )
            return services

        raise DiscoveryAPIError(
            f"Catalog request failed: {resp.status_code} {resp.text[:200]}"
        )

    def discover(
        self,
        query: str,
        category: Optional[str] = None,
        max_price: Optional[float] = None,
        min_quality: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search for x402 services by capability. Requires x402 payment ($0.001 USDC).

        If no payment header is configured, raises PaymentRequired with payment details.

        Args:
            query: Natural language search (e.g. "real-time crypto prices")
            category: Filter by capability category
            max_price: Maximum price per call in USD
            min_quality: Minimum quality tier (unverified|bronze|silver|gold)
            limit: Max results

        Returns:
            List of service dicts, quality-ranked by uptime and latency

        Raises:
            PaymentRequired: If no payment header configured
            ServiceNotFound: If no services match
        """
        params: Dict[str, Any] = {"q": query, "limit": limit}
        if category:
            params["category"] = category
        if max_price is not None:
            params["max_price"] = max_price
        if min_quality:
            params["min_quality"] = min_quality

        resp = self._session.get(
            f"{self.base_url}/discover", params=params, timeout=self.timeout
        )

        if resp.status_code == 402:
            try:
                payment_info = resp.json()
            except Exception:
                payment_info = {"raw": resp.text}
            raise PaymentRequired(payment_info)

        if resp.status_code == 200:
            data = resp.json()
            results = (
                data
                if isinstance(data, list)
                else data.get("results", data.get("services", []))
            )
            if not results:
                raise ServiceNotFound(f"No services found for query: {query!r}")
            return results

        raise DiscoveryAPIError(
            f"Discovery request failed: {resp.status_code} {resp.text[:200]}"
        )

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
        Implements RFC 5785 well-known URL for x402 service discovery.
        """
        resp = self._session.get(
            f"{self.base_url}/.well-known/x402-discovery", timeout=self.timeout
        )
        if resp.status_code == 200:
            return resp.json()
        raise DiscoveryAPIError(
            f"Well-known request failed: {resp.status_code}"
        )


# Module-level convenience functions using a default client
_default_client = X402DiscoveryClient()


def discover(
    query: str,
    category: Optional[str] = None,
    max_price: Optional[float] = None,
    limit: int = 10,
    payment_header: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Module-level convenience: discover x402 services."""
    client = (
        X402DiscoveryClient(x402_payment_header=payment_header)
        if payment_header
        else _default_client
    )
    return client.discover(query, category=category, max_price=max_price, limit=limit)


def browse(
    category: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """Module-level convenience: browse the free catalog."""
    return _default_client.browse(category=category, limit=limit)


def health_check(service_id: str) -> Dict[str, Any]:
    """Module-level convenience: check service health."""
    return _default_client.health_check(service_id)
