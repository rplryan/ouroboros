#!/usr/bin/env python3
"""
Demonstrates: registering your own x402-payable endpoint with the discovery layer.

Once registered, your service is:
  - Health-checked every 5 minutes
  - Discoverable by all agents querying the index
  - Listed in /.well-known/x402-discovery
  - Assigned a quality tier (bronze → silver → gold) as data accumulates

Registration is free. No API key required.

Source: https://x402-discovery-api.onrender.com
"""
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

# Fill in your service details
MY_SERVICE = {
    "name": "My Research API",
    "url": "https://your-service.example.com/research",
    "description": "Answers research queries about any topic, returns structured summaries.",
    "price_usd": 0.05,
    "category": "research",
}

print("x402 Service Registration")
print("=" * 50)
print(f"Registering: {MY_SERVICE['name']}")
print(f"URL:         {MY_SERVICE['url']}")
print(f"Price:       ${MY_SERVICE['price_usd']}/call")
print()

resp = requests.post(f"{DISCOVERY_URL}/register", json=MY_SERVICE, timeout=15)

if resp.status_code == 200:
    data = resp.json()
    print(f"Registered! Service ID: {data.get('service_id', 'assigned')}")
    print(f"  Catalog: {DISCOVERY_URL}/catalog")
    print(f"  Health:  {DISCOVERY_URL}/health/{data.get('id', '...')}")
    print()
    print("Your service will be health-checked within 5 minutes.")
    print("Quality tier: unverified -> bronze -> silver -> gold (auto-upgraded).")
else:
    print(f"Registration failed (HTTP {resp.status_code}):")
    print(resp.text)

print()
print("Via curl:")
print(f"""curl -X POST {DISCOVERY_URL}/register \\
  -H "Content-Type: application/json" \\
  -d '{{"name": "My API", "url": "https://example.com/api", \\
       "description": "Does X, returns Y.", "price_usd": 0.01, "category": "data"}}'""")
