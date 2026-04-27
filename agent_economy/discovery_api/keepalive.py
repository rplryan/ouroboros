"""Keepalive script for x402-discovery-api cron job."""
import requests
import sys

try:
    r = requests.get(
        "https://x402-discovery-api.onrender.com/",
        timeout=90,
        allow_redirects=True,
    )
    print(f"keepalive: {r.status_code}")
except Exception as e:
    # Log warning but exit 0 — cold starts are expected
    print(f"keepalive warning: {e}", file=sys.stderr)
