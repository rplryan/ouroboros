#!/usr/bin/env python3
"""
Demonstrates: polling health endpoints and alerting on degraded services.

Use this pattern to monitor x402 services your agent depends on.
Alerts when uptime drops below threshold or latency spikes.

Source: https://x402-discovery-api.onrender.com
"""
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"
UPTIME_THRESHOLD = 90.0
LATENCY_THRESHOLD_MS = 2000


def check_service(service_id: str) -> dict:
    """Check health of a specific service by ID."""
    try:
        resp = requests.get(f"{DISCOVERY_URL}/health/{service_id}", timeout=10)
        if resp.status_code == 404:
            return {"service_id": service_id, "status": "not_found"}
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"service_id": service_id, "status": "error", "error": str(e)}


def check_all() -> tuple[list[dict], list[str]]:
    """Check all indexed services. Returns (results, alerts)."""
    catalog = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15).json()
    services = catalog.get("services", [])

    results, alerts = [], []

    for svc in services:
        # The health endpoint uses integer IDs in the current implementation
        svc_id = svc.get("id") or svc.get("service_id", "unknown")
        health = check_service(svc_id)
        results.append(health)

        status = health.get("status", "unknown")
        uptime = health.get("uptime_pct")
        latency = health.get("latency_ms")
        name = svc.get("name", svc_id)

        if status == "down":
            alerts.append(f"DOWN: {name} ({svc_id})")
        elif status == "degraded":
            alerts.append(f"DEGRADED: {name} ({svc_id})")
        elif uptime is not None and uptime < UPTIME_THRESHOLD:
            alerts.append(f"LOW UPTIME: {name} {uptime:.1f}% (threshold: {UPTIME_THRESHOLD}%)")
        elif latency is not None and latency > LATENCY_THRESHOLD_MS:
            alerts.append(f"HIGH LATENCY: {name} {latency}ms (threshold: {LATENCY_THRESHOLD_MS}ms)")

    return results, alerts


# Run check
print("x402 Service Health Monitor")
print("=" * 50)

results, alerts = check_all()

up = sum(1 for r in results if r.get("status") == "up")
down = sum(1 for r in results if r.get("status") == "down")
degraded = sum(1 for r in results if r.get("status") == "degraded")
other = len(results) - up - down - degraded

print(f"Services checked: {len(results)}")
print(f"  up:       {up}")
print(f"  degraded: {degraded}")
print(f"  down:     {down}")
print(f"  other:    {other}")
print()

if alerts:
    print(f"Alerts ({len(alerts)}):")
    for a in alerts:
        print(f"  {a}")
else:
    print("No alerts — all services nominal.")
