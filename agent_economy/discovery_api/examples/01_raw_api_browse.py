#!/usr/bin/env python3
"""
Demonstrates: browsing the free x402 service catalog without any payment.
Source: https://x402-discovery-api.onrender.com

The /.well-known/x402-discovery endpoint and /catalog are free and ungated.
Use these to enumerate all registered x402 services.
"""
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

# Option 1: Free catalog endpoint
catalog = requests.get(f"{DISCOVERY_URL}/catalog").json()
print(f"Total services: {len(catalog['services'])}")
for svc in catalog["services"]:
    print(f"  - {svc['name']} [{svc.get('category', '?')}] ${svc.get('price_per_call', '?')}/call")

print()

# Option 2: Well-known URL (standard pattern for protocol compliance)
well_known = requests.get(f"{DISCOVERY_URL}/.well-known/x402-discovery").json()
print(f"Well-known index: {well_known.get('total_services')} services")
print(f"Schema version: {well_known.get('schema_version')}")
print(f"Index URL: {well_known.get('index_url')}")
