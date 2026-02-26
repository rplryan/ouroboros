#!/usr/bin/env python3
"""
Demonstrates: what the MCP server tools do under the hood.

The MCP server (agent_economy/discovery_api/mcp/server.py) exposes
x402 discovery to Claude Desktop, Cursor, and Windsurf.

This script reproduces each MCP tool's behavior directly
so you can understand the API calls without running MCP.

Source: https://x402-discovery-api.onrender.com
"""
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

print("MCP Tool Walkthrough — direct API equivalents")
print("=" * 55)
print()

# ------------------------------------------------------------------
# Tool 1: x402_discover
# ------------------------------------------------------------------
print("── x402_discover(capability='research', max_price_usd=0.20) ──")
catalog = requests.get(f"{DISCOVERY_URL}/catalog").json()
services = catalog.get("services", [])

research = [
    s for s in services
    if ("research" in s.get("capability_tags", []) or s.get("category") == "research")
    and s.get("price_per_call", 99) <= 0.20
]
order = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}
research.sort(key=lambda s: order.get(s.get("quality_tier", "unverified"), 3))

if research:
    for i, s in enumerate(research[:3], 1):
        print(f"  {i}. {s.get('name')} [{s.get('quality_tier','?')}] ${s.get('price_per_call','?')}/call")
else:
    print("  (no research services matching criteria)")
print()

# ------------------------------------------------------------------
# Tool 2: x402_browse
# ------------------------------------------------------------------
print("── x402_browse() — all services by category ──")
by_cat: dict[str, list] = {}
for s in services:
    cat = s.get("category") or (s.get("capability_tags") or ["other"])[0]
    by_cat.setdefault(cat, []).append(s)

for cat, svcs in sorted(by_cat.items()):
    print(f"  {cat}: {len(svcs)} services")
print()

# ------------------------------------------------------------------
# Tool 3: x402_health
# ------------------------------------------------------------------
print("── x402_health('1') — health check for service ID 1 ──")
try:
    h = requests.get(f"{DISCOVERY_URL}/health/1", timeout=10).json()
    print(f"  Status: {h.get('status', 'unknown')}")
    print(f"  Latency: {h.get('latency_ms', '?')}ms")
    print(f"  Uptime: {h.get('uptime_pct', '?')}%")
except Exception as e:
    print(f"  (health endpoint: {DISCOVERY_URL}/health/{{id}})")
print()

# ------------------------------------------------------------------
# Tool 4: x402_register
# ------------------------------------------------------------------
print("── x402_register — how to add your service ──")
print(f"  POST {DISCOVERY_URL}/register")
print("  Body: {name, url, description, price_usd, category}")
print()
print("MCP config (claude_desktop_config.json):")
print("""  {
    "mcpServers": {
      "x402-discovery": {
        "command": "python",
        "args": ["/path/to/agent_economy/discovery_api/mcp/server.py"]
      }
    }
  }""")
