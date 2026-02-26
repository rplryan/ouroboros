#!/usr/bin/env python3
"""
Demonstrates: POST /report — feeding quality signals back to the discovery layer.

Every time your agent calls a discovered service, report the outcome.
This improves quality rankings for all agents without central coordination.
The more agents report, the better the index becomes.

Source: https://x402-discovery-api.onrender.com
"""
import time
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"


def call_and_report(service_id: str, endpoint_url: str) -> dict:
    """Call a service (simulated), measure latency, and report to discovery layer."""
    start = time.time()
    outcome = "success"
    latency_ms = 0

    try:
        resp = requests.get(endpoint_url, timeout=15)
        latency_ms = int((time.time() - start) * 1000)
        # 402 is correct behavior for x402 endpoints — counts as "up"
        if resp.status_code in (200, 402):
            outcome = "success"
        else:
            outcome = "fail"
    except requests.Timeout:
        outcome = "timeout"
        latency_ms = 15_000
    except requests.RequestException:
        outcome = "fail"

    # Report back — best-effort, non-blocking
    try:
        report_resp = requests.post(
            f"{DISCOVERY_URL}/report",
            json={"service_id": service_id, "called": True, "result": outcome, "latency_ms": latency_ms},
            timeout=5,
        )
        print(f"Reported {outcome} for {service_id} (HTTP {report_resp.status_code})")
    except Exception as e:
        print(f"Report failed (non-critical): {e}")

    return {"outcome": outcome, "latency_ms": latency_ms}


# Demo: check catalog, pick first service, call and report
print("x402 Feedback Loop Demo")
print("=" * 50)

catalog = requests.get(f"{DISCOVERY_URL}/catalog").json()
services = catalog.get("services", [])

if services:
    target = services[0]
    sid = target.get("service_id", "unknown")
    url = target.get("endpoint_url") or target.get("url", "")
    print(f"Testing: {target.get('name')} ({sid})")
    result = call_and_report(sid, url)
    print(f"Result: {result}")
else:
    # No services yet — send a synthetic report to show the API
    print("No services in catalog. Sending synthetic report:")
    resp = requests.post(
        f"{DISCOVERY_URL}/report",
        json={"service_id": "demo/test", "called": True, "result": "success", "latency_ms": 200},
    )
    print(f"HTTP {resp.status_code}: {resp.json()}")

print()
print("Add this pattern to every discover_and_execute() call in your agent.")
print("Your reports make the index more accurate for everyone.")
