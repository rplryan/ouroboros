#!/usr/bin/env python3
"""
Demonstrates: discovering multiple services for the same capability and
comparing them by price and quality to select the best-value endpoint.

Pattern overview
----------------
1. Fetch the full catalog from /catalog (free, no payment required).
2. Filter services by the target capability tag.
3. Score each service using a simple value metric:
       quality_score / price_per_call
   where quality_score maps gold=4, silver=3, bronze=2, unverified=1.
4. Display ranked results and identify the "best value" pick.

Use this before building an agent that calls a specific capability — run
the comparison once to understand the market, then hardcode the winner
into your agent config (or re-run comparison at startup to stay current).

Source: https://x402-discovery-api.onrender.com
"""

import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

QUALITY_SCORE = {"gold": 4, "silver": 3, "bronze": 2, "unverified": 1}
QUALITY_ORDER = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}


def get_catalog() -> list[dict]:
    """Fetch all services from the free catalog endpoint."""
    resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
    resp.raise_for_status()
    return resp.json().get("services", [])


def filter_by_capability(services: list[dict], capability: str) -> list[dict]:
    """Filter to services that match the given capability tag."""
    return [
        s for s in services
        if capability in s.get("capability_tags", [])
        or s.get("category") == capability
    ]


def value_score(service: dict) -> float:
    """Compute quality/price ratio. Higher is better.

    A gold-tier service at $0.10/call scores 4/0.10 = 40.
    A bronze-tier service at $0.01/call scores 2/0.01 = 200.
    The bronze service wins on value even though gold is higher quality.
    """
    price = service.get("price_per_call", service.get("price_usd", 0))
    quality = QUALITY_SCORE.get(service.get("quality_tier", "unverified"), 1)
    if price <= 0:
        return 0.0
    return quality / price


def compare_services(capability: str, max_price: float | None = None) -> list[dict]:
    """Return services for a capability, ranked by value score (desc)."""
    all_services = get_catalog()
    candidates = filter_by_capability(all_services, capability)

    if max_price is not None:
        candidates = [
            s for s in candidates
            if s.get("price_per_call", s.get("price_usd", 999)) <= max_price
        ]

    return sorted(candidates, key=value_score, reverse=True)


def print_comparison(capability: str, max_price: float | None = None) -> None:
    """Print a formatted comparison table for a capability."""
    print(f"\nCapability: {capability}", end="")
    if max_price:
        print(f"  (max ${max_price}/call)", end="")
    print()
    print("-" * 70)

    services = compare_services(capability, max_price=max_price)

    if not services:
        print("  No services found.")
        return

    # Header
    print(f"  {'Rank':<5} {'Name':<28} {'Price':>8} {'Quality':<12} {'Value':>8}  {'Uptime':>7}")
    print(f"  {'----':<5} {'----':<28} {'-----':>8} {'-------':<12} {'-----':>8}  {'------':>7}")

    for i, svc in enumerate(services, 1):
        name = (svc.get("name") or "")[:27]
        price = svc.get("price_per_call", svc.get("price_usd"))
        price_str = f"${price:.4f}" if price is not None else "  ?"
        quality = svc.get("quality_tier", "unverified")
        score = value_score(svc)
        uptime = svc.get("uptime_pct") or svc.get("uptime_7d")
        uptime_str = f"{uptime:.1f}%" if uptime is not None else "    ?"

        marker = " <-- best value" if i == 1 else ""
        print(f"  {i:<5} {name:<28} {price_str:>8} {quality:<12} {score:>8.1f}  {uptime_str:>7}{marker}")

    best = services[0]
    print()
    print(f"  Best value: {best.get('name')}")
    print(f"    Endpoint: {best.get('endpoint_url') or best.get('url')}")
    print(f"    Price:    ${best.get('price_per_call', best.get('price_usd', '?'))}/call")
    print(f"    Quality:  {best.get('quality_tier', 'unverified')}")
    if best.get("llm_usage_prompt"):
        print(f"    Prompt:   {best['llm_usage_prompt'][:100]}...")


def best_value(capability: str, max_price: float | None = None) -> dict | None:
    """Return the single best-value service for a capability, or None."""
    ranked = compare_services(capability, max_price=max_price)
    return ranked[0] if ranked else None


# ---------------------------------------------------------------------------
# Main — run comparison across common capabilities
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("x402 Service Price Comparison — Example 12")
    print("=" * 70)
    print(f"Source: {DISCOVERY_URL}/catalog")

    # Fetch catalog once, display summary
    all_services = get_catalog()
    print(f"\nTotal services indexed: {len(all_services)}")

    # Count by capability
    cap_counts: dict[str, int] = {}
    for svc in all_services:
        for tag in svc.get("capability_tags", [svc.get("category", "other")]):
            cap_counts[tag] = cap_counts.get(tag, 0) + 1

    if cap_counts:
        print("\nServices by capability:")
        for cap, count in sorted(cap_counts.items(), key=lambda x: -x[1]):
            print(f"  {cap:<20} {count} service{'s' if count != 1 else ''}")

    # Run comparisons for key capabilities
    CAPABILITIES_TO_COMPARE = ["research", "data", "compute", "enrichment"]

    for cap in CAPABILITIES_TO_COMPARE:
        print_comparison(cap)

    # Show the overall best-value pick for research under $0.25
    print("\n" + "=" * 70)
    winner = best_value("research", max_price=0.25)
    if winner:
        print(f"\nRecommended research endpoint (under $0.25/call):")
        print(f"  {winner.get('name')}")
        print(f"  {winner.get('endpoint_url') or winner.get('url')}")
        print(f"  ${winner.get('price_per_call', winner.get('price_usd', '?'))}/call  "
              f"— {winner.get('quality_tier', 'unverified')} tier")
    else:
        print("\nNo research services currently available under $0.25/call.")
        print(f"Browse the full catalog: {DISCOVERY_URL}/catalog")
