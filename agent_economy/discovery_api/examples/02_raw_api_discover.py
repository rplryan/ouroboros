#!/usr/bin/env python3
"""
Demonstrates: querying the paid /discover endpoint and handling the x402 response.
Source: https://x402-discovery-api.onrender.com

The /discover endpoint returns HTTP 402 with payment instructions.
This example shows exactly what the 402 response contains so you can
build x402-capable clients.
"""
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

# Query the discovery endpoint
resp = requests.get(
    f"{DISCOVERY_URL}/discover",
    params={"q": "research", "max_price": "0.10"},
)

if resp.status_code == 402:
    # This is expected — the discovery service charges $0.005/query via x402
    payment_info = resp.json()
    print("HTTP 402 — Payment Required")
    print(f"  x402Version: {payment_info.get('x402Version')}")

    accepts = payment_info.get("accepts", [{}])[0]
    print(f"  payTo:  {accepts.get('payTo')}")
    print(f"  amount: {accepts.get('maxAmountRequired')} USDC micro-units (= ${int(accepts.get('maxAmountRequired', 0)) / 1_000_000:.4f})")
    print(f"  network: {accepts.get('network')}")
    print(f"  scheme: {accepts.get('scheme')}")
    print()
    print("To pay: send a valid x402 payment header with USDC on Base,")
    print("then retry the request. See https://x402.org for the payment spec.")

elif resp.status_code == 200:
    results = resp.json()
    print(f"Results: {len(results.get('results', []))} services found")
    for svc in results["results"][:3]:
        print(f"  - {svc['name']}: ${svc.get('price_per_call')}/call")
