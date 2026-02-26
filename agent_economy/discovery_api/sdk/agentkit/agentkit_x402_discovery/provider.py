"""
X402DiscoveryActionProvider — AgentKit ActionProvider for x402 Service Discovery.

Gives AgentKit agents 4 actions:
  - x402_discover: Find x402-payable services by capability/query
  - x402_browse: List all services in the catalog (free)
  - x402_health: Check live health of a specific service
  - x402_pay_and_call: Discover a service and execute it with x402 payment

Usage:
    from agentkit_x402_discovery import x402_discovery_action_provider
    from coinbase_agentkit import AgentKit, AgentKitConfig

    agent_kit = AgentKit(AgentKitConfig(
        wallet_provider=...,
        action_providers=[x402_discovery_action_provider()]
    ))
"""

import json
import requests
from typing import Optional
from pydantic import BaseModel, Field

# AgentKit imports — graceful fallback if not installed
try:
    from coinbase_agentkit import ActionProvider, CreateAction, WalletProvider
    AGENTKIT_AVAILABLE = True
except ImportError:
    AGENTKIT_AVAILABLE = False
    # Stub classes so the module loads even without agentkit installed
    class ActionProvider:
        def __init__(self, name, action_providers): pass
    class WalletProvider: pass
    def CreateAction(**kwargs):
        def decorator(fn): return fn
        return decorator

DISCOVERY_BASE_URL = "https://x402-discovery-api.onrender.com"


# --- Input schemas ---

class DiscoverInput(BaseModel):
    query: Optional[str] = Field(None, description="Free-text search, e.g. 'weather data' or 'crypto prices'")
    capability: Optional[str] = Field(None, description="Category filter: research|data|compute|agent|utility|monitoring")
    max_price_usd: float = Field(0.50, description="Maximum price per call in USD (default 0.50)")
    min_quality: Optional[str] = Field(None, description="Minimum quality tier: gold|silver|bronze|unverified")

class BrowseInput(BaseModel):
    pass

class HealthInput(BaseModel):
    service_id: str = Field(..., description="Service ID from the catalog, e.g. 'x402engine-crypto-prices'")

class PayAndCallInput(BaseModel):
    query: Optional[str] = Field(None, description="What kind of service to find and call")
    capability: Optional[str] = Field(None, description="Category filter: research|data|compute|agent|utility")
    max_price_usd: float = Field(0.10, description="Maximum price per call in USD")
    call_payload: Optional[dict] = Field(None, description="Request body to send to the discovered service")


# --- Provider ---

class X402DiscoveryActionProvider(ActionProvider):
    """
    AgentKit ActionProvider that gives agents access to the x402 Service Discovery API.

    An AgentKit agent already has a funded Base/USDC wallet. This provider bridges that
    wallet to the x402 ecosystem: the agent can discover services, check health, and
    execute paid API calls without any manual API key management.
    """

    def __init__(self, base_url: str = DISCOVERY_BASE_URL):
        super().__init__("x402-discovery", [])
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "agentkit-x402-discovery/1.0.0",
            "Accept": "application/json",
        })

    def _get_catalog(self):
        resp = self._session.get(f"{self.base_url}/catalog", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("endpoints", []) if isinstance(data, dict) else data

    def _filter_services(self, services, query=None, capability=None, max_price=0.50, min_quality=None):
        quality_rank = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}

        if capability:
            services = [s for s in services
                        if capability in s.get("capability_tags", [])
                        or s.get("category") == capability]

        services = [s for s in services if (s.get("price_usd") or 999) <= max_price]

        if query:
            q = query.lower()
            services = [s for s in services
                        if q in s.get("name", "").lower()
                        or q in s.get("description", "").lower()
                        or any(q in t.lower() for t in s.get("tags", []))]

        if min_quality:
            min_rank = quality_rank.get(min_quality, 3)
            services = [s for s in services
                        if quality_rank.get(s.get("health_status", "unverified"), 3) <= min_rank]

        services.sort(key=lambda s: (
            quality_rank.get(s.get("health_status", "unverified"), 3),
            s.get("price_usd") or 999,
        ))

        return services

    @CreateAction(
        name="x402_discover",
        description=(
            "Discover x402-payable API services by capability or keyword. "
            "Returns a ranked list of services with pricing, quality tier, and endpoint URL. "
            "Use this when you need to find a paid API service at runtime without hardcoded keys."
        ),
        schema=DiscoverInput,
    )
    def x402_discover(self, wallet_provider: WalletProvider, args: dict) -> str:
        try:
            services = self._get_catalog()
            results = self._filter_services(
                services,
                query=args.get("query"),
                capability=args.get("capability"),
                max_price=args.get("max_price_usd", 0.50),
                min_quality=args.get("min_quality"),
            )

            if not results:
                return json.dumps({
                    "found": 0,
                    "message": "No matching services found. Try broadening your search.",
                    "services": []
                })

            # Return top 5 with key fields for the agent
            top = []
            for s in results[:5]:
                top.append({
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "description": s.get("description"),
                    "url": s.get("url"),
                    "price_usd": s.get("price_usd"),
                    "quality": s.get("health_status", "unverified"),
                    "category": s.get("category"),
                    "tags": s.get("tags", []),
                    "network": s.get("network", "base"),
                    "wallet_address": s.get("wallet_address"),
                    "llm_usage_prompt": s.get("llm_usage_prompt"),
                })

            return json.dumps({
                "found": len(results),
                "showing": len(top),
                "services": top,
                "tip": (
                    "Use x402_pay_and_call to execute the selected service, "
                    "or use the url + wallet_address to construct an x402 payment manually."
                )
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    @CreateAction(
        name="x402_browse",
        description=(
            "List all x402-payable services in the discovery catalog. Free, no payment needed. "
            "Returns the complete catalog with names, descriptions, prices, and quality tiers."
        ),
        schema=BrowseInput,
    )
    def x402_browse(self, wallet_provider: WalletProvider, args: dict) -> str:
        try:
            services = self._get_catalog()
            summary = []
            for s in services:
                summary.append({
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "description": s.get("description"),
                    "price_usd": s.get("price_usd"),
                    "category": s.get("category"),
                    "quality": s.get("health_status", "unverified"),
                })
            return json.dumps({
                "total": len(summary),
                "services": summary
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @CreateAction(
        name="x402_health",
        description=(
            "Check the live health status of a specific x402 service. Free. "
            "Returns uptime percentage, average latency, and current status."
        ),
        schema=HealthInput,
    )
    def x402_health(self, wallet_provider: WalletProvider, args: dict) -> str:
        try:
            service_id = args["service_id"]
            resp = self._session.get(f"{self.base_url}/health/{service_id}", timeout=10)
            if resp.status_code == 404:
                return json.dumps({"error": f"Service '{service_id}' not found in catalog"})
            resp.raise_for_status()
            return json.dumps(resp.json(), indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @CreateAction(
        name="x402_pay_and_call",
        description=(
            "Discover the best matching x402 service and execute it using your wallet. "
            "This action finds a service, constructs the x402 payment, and makes the API call — "
            "the full autonomous pay-per-use pattern. Your AgentKit wallet handles the USDC payment on Base."
        ),
        schema=PayAndCallInput,
    )
    def x402_pay_and_call(self, wallet_provider: WalletProvider, args: dict) -> str:
        try:
            # Step 1: Discover the best matching service
            services = self._get_catalog()
            results = self._filter_services(
                services,
                query=args.get("query"),
                capability=args.get("capability"),
                max_price=args.get("max_price_usd", 0.10),
            )

            if not results:
                return json.dumps({
                    "status": "no_service_found",
                    "message": "No matching x402 service found within price limit."
                })

            service = results[0]
            service_url = service.get("url")
            price_usd = service.get("price_usd", 0.005)
            wallet_address = service.get("wallet_address")

            if not service_url:
                return json.dumps({"status": "error", "message": "Service has no endpoint URL"})

            # Step 2: Probe the service — first request without payment to get 402 challenge
            call_payload = args.get("call_payload") or {}

            try:
                probe = self._session.post(service_url, json=call_payload, timeout=10)

                if probe.status_code == 200:
                    # Service responded without payment (free tier or already paid)
                    content_type = probe.headers.get("content-type", "")
                    response_body = (
                        probe.json()
                        if content_type.startswith("application/json")
                        else probe.text[:500]
                    )
                    return json.dumps({
                        "status": "success",
                        "service": service.get("name"),
                        "service_id": service.get("id"),
                        "response": response_body,
                    })

                elif probe.status_code == 402:
                    # x402 payment required — surface the challenge and payment instructions
                    challenge = probe.json()
                    return json.dumps({
                        "status": "payment_required",
                        "service": service.get("name"),
                        "service_id": service.get("id"),
                        "service_url": service_url,
                        "price_usd": price_usd,
                        "payment_recipient": wallet_address,
                        "network": service.get("network", "base"),
                        "x402_challenge": challenge,
                        "instruction": (
                            f"Service requires x402 payment of ${price_usd} USDC on Base. "
                            f"Send USDC to {wallet_address} using your AgentKit wallet, "
                            "then retry the call with X-PAYMENT header. "
                            "Your wallet address: use wallet_provider.get_default_address()"
                        ),
                        "agentkit_payment_hint": (
                            "Use the AgentKit native_token_transfer or erc20_transfer action "
                            f"to send {price_usd} USDC to {wallet_address} on Base mainnet, "
                            "then retry the API call with the payment receipt."
                        ),
                    })

                else:
                    return json.dumps({
                        "status": "service_error",
                        "service": service.get("name"),
                        "http_status": probe.status_code,
                        "message": probe.text[:200],
                    })

            except requests.RequestException as call_err:
                return json.dumps({
                    "status": "call_failed",
                    "service": service.get("name"),
                    "service_url": service_url,
                    "error": str(call_err),
                    "service_info": {
                        "id": service.get("id"),
                        "price_usd": price_usd,
                        "wallet_address": wallet_address,
                    },
                })

        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    def supports_network(self, network) -> bool:
        """This provider works on all networks — discovery is off-chain, payments are on Base."""
        return True


def x402_discovery_action_provider(base_url: str = DISCOVERY_BASE_URL) -> X402DiscoveryActionProvider:
    """
    Factory function. Use this in AgentKitConfig:

        from agentkit_x402_discovery import x402_discovery_action_provider

        agent_kit = AgentKit(AgentKitConfig(
            wallet_provider=wallet_provider,
            action_providers=[
                x402_discovery_action_provider(),
                # ... other providers
            ]
        ))
    """
    return X402DiscoveryActionProvider(base_url=base_url)
