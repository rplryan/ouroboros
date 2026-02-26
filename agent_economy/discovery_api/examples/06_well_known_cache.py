#!/usr/bin/env python3
"""
Demonstrates: caching the /.well-known/x402-discovery index locally.

The well-known endpoint is free, ungated, and returns the full index.
Cache it to avoid repeated network calls in high-frequency agent loops.

Source: https://x402-discovery-api.onrender.com
"""
import json
import time
import requests
from pathlib import Path

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"
CACHE_FILE = Path("/tmp/x402-discovery-cache.json")
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_x402_index(force_refresh: bool = False) -> dict:
    """Get the x402 service index, from cache if fresh enough."""
    if not force_refresh and CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            print(f"Using cached index (age: {age:.0f}s)")
            return json.loads(CACHE_FILE.read_text())

    print("Fetching fresh index from /.well-known/x402-discovery...")
    resp = requests.get(f"{DISCOVERY_URL}/.well-known/x402-discovery", timeout=15)
    resp.raise_for_status()
    data = resp.json()

    CACHE_FILE.write_text(json.dumps(data, indent=2))
    print(f"Cached {data.get('total_services', '?')} services to {CACHE_FILE}")
    return data


def find_service(capability: str, max_price: float = 1.0, index: dict = None) -> list:
    """Search the cached index without a network call."""
    if index is None:
        index = get_x402_index()

    services = index.get("services", [])
    results = [
        s for s in services
        if (not capability or capability in s.get("capability_tags", []) or s.get("category") == capability)
        and s.get("price_per_call", 999) <= max_price
    ]
    return sorted(
        results,
        key=lambda s: {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}.get(s.get("quality_tier", "unverified"), 3)
    )


# Demo
index = get_x402_index()
print(f"\nIndex contains {len(index.get('services', []))} services")
print(f"Schema version: {index.get('schema_version')}")
print()

# Search from cache — zero extra network calls
for cap in ["research", "data", "compute"]:
    found = find_service(cap, max_price=0.20, index=index)
    print(f"{cap}: {len(found)} services under $0.20/call")
