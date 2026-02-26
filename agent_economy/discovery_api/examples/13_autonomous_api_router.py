#!/usr/bin/env python3
"""
Demonstrates: the "runtime routing" pattern for autonomous agents.

Instead of hardcoding API endpoints at development time, AgentRouter always
queries the discovery layer at runtime to find the current best endpoint for
a given capability.

Why this matters
----------------
Hardcoding service URLs creates brittleness:
  - Services go down; the agent breaks.
  - Better services appear; the agent never uses them.
  - Prices change; the agent doesn't adapt.

Runtime routing solves all three. The agent declares what it needs
(capability + price ceiling), not which specific URL to call. The discovery
layer handles routing. This creates a direct dependency on the discovery
layer — which is the point.

Usage:

    router = AgentRouter(max_price=0.10, min_quality="bronze")

    # These resolve to different endpoints depending on what's live right now
    result = router.call("research", {"query": "latest AI safety research"})
    result = router.call("data", {"symbol": "ETH"})
    result = router.call("enrichment", {"url": "https://example.com"})

Source: https://x402-discovery-api.onrender.com
"""

import time
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

QUALITY_ORDER = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}


class AgentRouter:
    """Routes capability requests to the best available x402 endpoint.

    The router discovers endpoints at call time (with optional in-process
    caching) so it always reflects the current state of the index.

    Args:
        max_price:    Maximum price per call in USD. Default: 0.50.
        min_quality:  Minimum quality tier. One of: unverified, bronze,
                      silver, gold. Default: "unverified" (any).
        cache_ttl:    Seconds to cache the catalog locally. Set to 0 to
                      always fetch fresh. Default: 300 (5 minutes).
        discovery_url: Override the discovery API base URL.
        report_outcomes: If True, send call outcomes back to the discovery
                         layer to improve quality scores. Default: True.

    Example:
        router = AgentRouter(max_price=0.10, min_quality="bronze")
        result = router.call("research", {"query": "EU AI Act status"})
        print(result["data"])   # service response
        print(result["service_name"])  # which service was used
    """

    def __init__(
        self,
        max_price: float = 0.50,
        min_quality: str = "unverified",
        cache_ttl: int = 300,
        discovery_url: str = DISCOVERY_URL,
        report_outcomes: bool = True,
    ):
        self.max_price = max_price
        self.min_quality = min_quality
        self.cache_ttl = cache_ttl
        self.discovery_url = discovery_url
        self.report_outcomes = report_outcomes

        # Internal catalog cache
        self._catalog: list[dict] = []
        self._catalog_fetched_at: float = 0.0

        # Per-capability endpoint history (last used)
        self._last_used: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(
        self,
        capability: str,
        input_data: dict,
        *,
        timeout: int = 30,
        fallback_count: int = 3,
    ) -> dict:
        """Discover the best endpoint for capability and call it.

        Args:
            capability:     The service capability needed (e.g. "research",
                            "data", "compute", "enrichment").
            input_data:     Request payload to send to the service.
            timeout:        Request timeout in seconds.
            fallback_count: How many services to try before giving up.

        Returns:
            A dict with keys:
                - success (bool)
                - service_name (str)
                - service_id (str)
                - endpoint_url (str)
                - price_per_call (float)
                - quality_tier (str)
                - data (any): service response on success, None on failure
                - payment_required (dict | None): x402 payment info if unpaid
                - latency_ms (int)
                - error (str | None)

        Raises:
            RouterError: if all candidate services fail or none are found.
        """
        candidates = self._get_candidates(capability)

        if not candidates:
            raise RouterError(
                f"No services found for capability='{capability}' "
                f"max_price={self.max_price} min_quality={self.min_quality}"
            )

        print(f"[Router] capability={capability} → {len(candidates)} candidate(s)")

        last_error = None
        for service in candidates[:fallback_count]:
            result = self._try_call(service, input_data, timeout=timeout)
            if result["success"] or result.get("payment_required"):
                # Record which service was used for this capability
                self._last_used[capability] = service.get("service_id", "")
                return result
            last_error = result.get("error")

        raise RouterError(
            f"All {min(len(candidates), fallback_count)} services failed for "
            f"capability='{capability}'. Last error: {last_error}"
        )

    def discover(self, capability: str) -> list[dict]:
        """Return ranked candidate services for a capability without calling them."""
        return self._get_candidates(capability)

    def refresh(self) -> int:
        """Force-refresh the catalog cache. Returns number of services loaded."""
        self._catalog = self._fetch_catalog()
        self._catalog_fetched_at = time.time()
        return len(self._catalog)

    def status(self) -> dict:
        """Return router status: cache age, catalog size, last-used services."""
        age = time.time() - self._catalog_fetched_at
        return {
            "catalog_size": len(self._catalog),
            "cache_age_seconds": int(age),
            "cache_fresh": age < self.cache_ttl,
            "last_used": dict(self._last_used),
            "config": {
                "max_price": self.max_price,
                "min_quality": self.min_quality,
                "cache_ttl": self.cache_ttl,
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_candidates(self, capability: str) -> list[dict]:
        """Return quality-ranked, price-filtered candidates for a capability."""
        catalog = self._get_catalog()

        QUALITY_MIN_SCORE = {
            "unverified": 0, "bronze": 1, "silver": 2, "gold": 3
        }
        min_score = QUALITY_MIN_SCORE.get(self.min_quality, 0)

        candidates = []
        for svc in catalog:
            tags = svc.get("capability_tags", [svc.get("category", "")])
            if capability not in tags:
                continue
            price = svc.get("price_per_call", svc.get("price_usd", 999))
            if price > self.max_price:
                continue
            tier = svc.get("quality_tier", "unverified")
            if QUALITY_MIN_SCORE.get(tier, 0) < min_score:
                continue
            candidates.append(svc)

        candidates.sort(key=lambda s: QUALITY_ORDER.get(s.get("quality_tier", "unverified"), 3))
        return candidates

    def _get_catalog(self) -> list[dict]:
        """Return the catalog, using cache if fresh."""
        age = time.time() - self._catalog_fetched_at
        if self._catalog and age < self.cache_ttl:
            return self._catalog
        self._catalog = self._fetch_catalog()
        self._catalog_fetched_at = time.time()
        return self._catalog

    def _fetch_catalog(self) -> list[dict]:
        """Fetch the current catalog from the discovery API."""
        resp = requests.get(f"{self.discovery_url}/catalog", timeout=15)
        resp.raise_for_status()
        services = resp.json().get("services", [])
        print(f"[Router] Refreshed catalog: {len(services)} services")
        return services

    def _try_call(self, service: dict, input_data: dict, *, timeout: int) -> dict:
        """Attempt to call a single service. Returns result dict."""
        endpoint = service.get("endpoint_url") or service.get("url", "")
        service_id = service.get("service_id", service.get("id", "unknown"))
        name = service.get("name", service_id)
        price = service.get("price_per_call", service.get("price_usd", "?"))
        quality = service.get("quality_tier", "unverified")

        print(f"[Router]   Trying: {name} (${price}/call, {quality})")

        start = time.time()
        try:
            resp = requests.post(
                endpoint,
                json=input_data,
                headers={"Content-Type": "application/json",
                         "User-Agent": "x402-agent-router/1.0"},
                timeout=timeout,
            )
            latency_ms = int((time.time() - start) * 1000)

            base = {
                "service_name": name,
                "service_id": service_id,
                "endpoint_url": endpoint,
                "price_per_call": price,
                "quality_tier": quality,
                "latency_ms": latency_ms,
            }

            if resp.status_code == 402:
                payment_info = resp.json()
                if self.report_outcomes:
                    self._report(service_id, "success", latency_ms)  # 402 = alive
                return {**base, "success": False, "data": None,
                        "payment_required": payment_info, "error": None}

            if resp.status_code < 400:
                data = (resp.json()
                        if "json" in resp.headers.get("content-type", "")
                        else resp.text)
                if self.report_outcomes:
                    self._report(service_id, "success", latency_ms)
                return {**base, "success": True, "data": data,
                        "payment_required": None, "error": None}

            # 4xx / 5xx
            if self.report_outcomes:
                self._report(service_id, "fail", latency_ms)
            return {**base, "success": False, "data": None,
                    "payment_required": None,
                    "error": f"HTTP {resp.status_code}"}

        except requests.Timeout:
            latency_ms = int((time.time() - start) * 1000)
            if self.report_outcomes:
                self._report(service_id, "timeout", latency_ms)
            return {"success": False, "data": None, "payment_required": None,
                    "service_name": name, "service_id": service_id,
                    "endpoint_url": endpoint, "price_per_call": price,
                    "quality_tier": quality, "latency_ms": latency_ms,
                    "error": "timeout"}

        except requests.RequestException as e:
            latency_ms = int((time.time() - start) * 1000)
            if self.report_outcomes:
                self._report(service_id, "fail", latency_ms)
            return {"success": False, "data": None, "payment_required": None,
                    "service_name": name, "service_id": service_id,
                    "endpoint_url": endpoint, "price_per_call": price,
                    "quality_tier": quality, "latency_ms": latency_ms,
                    "error": str(e)}

    def _report(self, service_id: str, result: str, latency_ms: int) -> None:
        """Send outcome report to discovery layer (best-effort, silent)."""
        try:
            requests.post(
                f"{self.discovery_url}/report",
                json={"service_id": service_id, "called": True,
                      "result": result, "latency_ms": latency_ms},
                timeout=5,
            )
        except Exception:
            pass


class RouterError(Exception):
    """Raised when AgentRouter cannot fulfill a capability request."""


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("x402 Autonomous API Router — Example 13")
    print("=" * 50)
    print()

    # Instantiate a router: max $0.25/call, bronze or better
    router = AgentRouter(max_price=0.25, min_quality="bronze", cache_ttl=60)

    # Show current catalog status
    count = router.refresh()
    print(f"Catalog loaded: {count} services")
    print()

    # Show what's available for each capability
    for cap in ["research", "data", "compute", "enrichment"]:
        candidates = router.discover(cap)
        if candidates:
            best = candidates[0]
            print(f"{cap}: {len(candidates)} service(s) — "
                  f"best: {best.get('name')} "
                  f"(${best.get('price_per_call', best.get('price_usd', '?'))}/call, "
                  f"{best.get('quality_tier', 'unverified')})")
        else:
            print(f"{cap}: no services available within constraints")

    print()

    # Attempt a real call (will get 402 without funded wallet — expected)
    print("Attempting router.call('research', {'query': 'x402 protocol overview'})...")
    print()
    try:
        result = router.call("research", {"query": "x402 protocol overview"})
        if result.get("payment_required"):
            accepts = result["payment_required"].get("accepts", [{}])[0]
            print(f"Service found: {result['service_name']}")
            print(f"  Endpoint:  {result['endpoint_url']}")
            print(f"  Payment:   {accepts.get('amount', '?')} USDC units")
            print(f"  Pay to:    {accepts.get('payTo', '?')}")
            print()
            print("To execute: fund a Base wallet with USDC and add an")
            print("X-PAYMENT header with a signed payment token.")
        elif result.get("success"):
            print(f"Success from {result['service_name']}:")
            print(result["data"])
    except RouterError as e:
        print(f"Router: {e}")
        print()
        print("No services currently registered — try registering one:")
        print(f"  python3 examples/10_register_service.py")

    print()
    print("Router status:")
    status = router.status()
    for k, v in status.items():
        print(f"  {k}: {v}")
