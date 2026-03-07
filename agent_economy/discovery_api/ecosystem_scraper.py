"""Ecosystem scraper for x402 Service Discovery API.

Scans multiple sources for x402-enabled services and returns normalized entries
ready to be upserted into the registry:
  - awesome-x402 README on GitHub (community curated list)
  - x402.org/ecosystem (official ecosystem page)
  - GitHub search API (repos with x402 topics/keywords)
  - Manual high-value seed list (known services)

New entries are given:
  status = "discovered"
  source = "ecosystem_scan"
  facilitator_compatible = True (assumed — verified on next health check)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger("ecosystem_scraper")

# ---------------------------------------------------------------------------
# Timeouts & config
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = 15.0
PROBE_TIMEOUT = 8.0

AWESOME_X402_README_URL = (
    "https://raw.githubusercontent.com/xpaysh/awesome-x402/main/README.md"
)
X402_ORG_ECOSYSTEM_URL = "https://x402.org/ecosystem"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"

# Manual high-value seed URLs to always scan (won't be added if already present)
MANUAL_SEEDS: list[dict[str, Any]] = [
    {
        "url": "https://elizaos-mcp-gateway.onrender.com",
        "name": "ElizaOS MCP Gateway",
        "description": "Production-ready MCP gateway with full x402 blockchain payment support. Aggregates multiple MCP servers with per-tool pricing, three payment modes (passthrough, markup, absorb), and USDC payments on Base.",
        "category": "agent",
        "tags": ["x402", "mcp", "elizaos", "agent", "gateway", "usdc"],
        "github_url": "https://github.com/elizaOS/mcp-gateway",
    },
    {
        "url": "https://x402scan.com",
        "name": "x402scan",
        "description": "On-chain explorer and analytics for the x402 payment protocol. Shows transaction volumes, facilitator activity, and resource browser with embedded wallet.",
        "category": "data",
        "tags": ["x402", "explorer", "analytics", "on-chain"],
        "github_url": "https://github.com/Merit-Systems/x402scan",
    },
    {
        "url": "https://x402-routenet.onrender.com",
        "name": "x402 RouteNet",
        "description": "Intelligent routing layer for x402 services — finds the optimal service endpoint based on capability, latency, and price.",
        "category": "routing",
        "tags": ["x402", "routing", "discovery"],
        "github_url": "https://github.com/rplryan/x402-discovery-mcp",
    },
    {
        "url": "https://x402-scout-relay.onrender.com",
        "name": "x402 Scout Relay",
        "description": "MCP relay server for x402Scout discovery. Provides agent-callable tools for x402 service discovery over streamable HTTP.",
        "category": "agent",
        "tags": ["x402", "mcp", "relay", "discovery"],
        "github_url": "https://github.com/rplryan/x402-discovery-mcp",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _hostname_name(url: str) -> str:
    try:
        host = urlparse(url).hostname or url
        parts = host.split(".")
        filtered = [p for p in parts if p not in ("api", "www", "app", "com", "io", "net", "org", "xyz")]
        return (filtered[0] if filtered else parts[0]).replace("-", " ").title()
    except Exception:
        return url[:30]


def _canonical_entry(
    url: str,
    name: str = "",
    description: str = "",
    category: str = "utility",
    tags: list[str] | None = None,
    github_url: str = "",
) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "id": _make_id(url),
        "service_id": _make_id(url),
        "name": name or _hostname_name(url),
        "description": description or f"x402-enabled service at {url}",
        "url": url,
        "category": category,
        "price_usd": 0.001,
        "network": "eip155:8453",
        "asset_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "tags": tags or ["x402", "ecosystem"],
        "registered_at": now,
        "query_count": 0,
        "uptime_pct": None,
        "avg_latency_ms": None,
        "last_health_check": None,
        "status": "discovered",
        "facilitator_compatible": True,
        "recommended_facilitator": "https://x402.org/facilitator",
        "facilitator_count": 0,
        "capability_tags": tags or [],
        "source": "ecosystem_scan",
        "input_format": "application/json",
        "output_format": "application/json",
        "pricing_model": "per_request",
        "agent_callable": True,
        "auth_required": False,
        **({"github_url": github_url} if github_url else {}),
    }


async def _probe_url_returns_402(client: httpx.AsyncClient, url: str) -> bool:
    try:
        resp = await client.get(url, follow_redirects=True, timeout=PROBE_TIMEOUT)
        return resp.status_code == 402
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Source 1: awesome-x402 README
# ---------------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_MD_HEADING_RE = re.compile(r"^#{1,4}\s+(.+)", re.MULTILINE)


def _parse_awesome_x402(md: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    current_section = "utility"
    lines = md.split("\n")
    for line in lines:
        heading_match = _MD_HEADING_RE.match(line)
        if heading_match:
            ht = heading_match.group(1).lower()
            if any(w in ht for w in ["data", "analytics", "intelligence", "oracle"]):
                current_section = "data"
            elif any(w in ht for w in ["compute", "ai", "ml", "inference", "model"]):
                current_section = "compute"
            elif any(w in ht for w in ["agent", "automation", "workflow"]):
                current_section = "agent"
            else:
                current_section = "utility"
        for match in _MD_LINK_RE.finditer(line):
            name, url = match.group(1), match.group(2)
            if any(skip in url for skip in [
                "github.com", "docs.", "discord.", "twitter.", "t.co",
                "medium.", "blog.", "npmjs.", "pypi.", "reddit.", "youtube.",
            ]):
                continue
            if url.startswith("#") or url.startswith("mailto:"):
                continue
            clean_url = url.split("?")[0].rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            results.append(_canonical_entry(
                url=clean_url, name=name,
                description=f"x402 service listed on awesome-x402: {name}",
                category=current_section,
                tags=["x402", "awesome-x402", current_section],
            ))
    log.info("awesome-x402: found %d candidates", len(results))
    return results


async def _fetch_awesome_x402(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    try:
        resp = await client.get(AWESOME_X402_README_URL, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return _parse_awesome_x402(resp.text)
    except Exception as exc:
        log.warning("Failed to fetch awesome-x402: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source 2: x402.org/ecosystem
# ---------------------------------------------------------------------------

def _parse_x402_org_ecosystem(html: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    url_re = re.compile(r'href=["\']?(https?://[^\s"\'<>]+)["\']?')
    for match in url_re.finditer(html):
        url = match.group(1).split("?")[0].rstrip("/")
        if any(skip in url for skip in [
            "github.com", "docs.", "x402.org", "coinbase.com",
            "base.org", "twitter.", "discord.", "npmjs.", "youtube.",
        ]):
            continue
        if url not in seen_urls and len(url) > 12:
            seen_urls.add(url)
            results.append(_canonical_entry(url=url, tags=["x402", "x402.org"]))
    log.info("x402.org/ecosystem: found %d candidates", len(results))
    return results


async def _fetch_x402_org_ecosystem(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    try:
        resp = await client.get(X402_ORG_ECOSYSTEM_URL, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return _parse_x402_org_ecosystem(resp.text)
    except Exception as exc:
        log.warning("Failed to fetch x402.org/ecosystem: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source 3: GitHub Search API (no auth needed for public repos)
# ---------------------------------------------------------------------------

GITHUB_SEARCH_QUERIES = [
    "x402+payment+enabled",
    "x402-enabled+api",
    "x402+mcp+server",
    "x402+blockchain+payment+api",
]

# Known patterns for live deployed services from GitHub repos
_DEPLOY_PATTERNS = [
    # Render
    lambda repo_name: f"https://{repo_name}.onrender.com",
    # Vercel
    lambda repo_name: f"https://{repo_name}.vercel.app",
    # Railway
    lambda repo_name: f"https://{repo_name}.railway.app",
]


async def _fetch_github_x402_repos(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Search GitHub for x402 repos and infer their deployed endpoints."""
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in GITHUB_SEARCH_QUERIES[:2]:  # Limit to 2 queries to avoid rate limit
        try:
            resp = await client.get(
                GITHUB_SEARCH_API,
                params={"q": query, "sort": "updated", "per_page": 10},
                headers={"Accept": "application/vnd.github+json"},
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    homepage = item.get("homepage", "") or ""
                    name = item.get("name", "")
                    desc = item.get("description", "") or ""
                    github_url = item.get("html_url", "")
                    topics = item.get("topics", [])

                    # Use homepage URL if it looks like a live service
                    if homepage and homepage.startswith("http") and "github.com" not in homepage:
                        clean_url = homepage.rstrip("/")
                        if clean_url not in seen_urls:
                            seen_urls.add(clean_url)
                            cat = "agent" if any(t in topics for t in ["mcp", "agent", "ai"]) else "utility"
                            results.append(_canonical_entry(
                                url=clean_url,
                                name=item.get("full_name", name),
                                description=desc,
                                category=cat,
                                tags=["x402", "github"] + topics[:3],
                                github_url=github_url,
                            ))
        except Exception as exc:
            log.warning("GitHub search failed for '%s': %s", query, exc)
        await asyncio.sleep(0.5)  # Be nice to GitHub API

    log.info("GitHub search: found %d candidates", len(results))
    return results


# ---------------------------------------------------------------------------
# Source 4: Manual high-value seeds
# ---------------------------------------------------------------------------

def _get_manual_seeds(existing_urls: set[str]) -> list[dict[str, Any]]:
    """Return manual seed entries not already in the registry."""
    results = []
    for seed in MANUAL_SEEDS:
        url = seed["url"]
        if url not in existing_urls:
            results.append(_canonical_entry(
                url=url,
                name=seed.get("name", ""),
                description=seed.get("description", ""),
                category=seed.get("category", "utility"),
                tags=seed.get("tags", ["x402"]),
                github_url=seed.get("github_url", ""),
            ))
    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_ecosystem_scan(existing_urls: set[str]) -> list[dict[str, Any]]:
    """Scan all ecosystem sources and return new services not in existing_urls.

    Automatically adds all discovered services — no approval gate.
    Services get status="discovered" (confirmed 402) or status="unverified"
    (added anyway, health checker will validate on next pass).
    """
    log.info("Starting ecosystem scan (existing: %d services)", len(existing_urls))

    async with httpx.AsyncClient(
        headers={"User-Agent": "x402-discovery-bot/3.8.0 (+https://x402scout.com)"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        awesome_entries, x402_org_entries, github_entries = await asyncio.gather(
            _fetch_awesome_x402(client),
            _fetch_x402_org_ecosystem(client),
            _fetch_github_x402_repos(client),
        )

    # Add manual seeds
    manual_entries = _get_manual_seeds(existing_urls)

    # Merge all, deduplicate
    all_candidates: dict[str, dict[str, Any]] = {}
    for entry in awesome_entries + x402_org_entries + github_entries + manual_entries:
        url = entry["url"]
        if url not in existing_urls and url not in all_candidates:
            all_candidates[url] = entry

    if not all_candidates:
        log.info("Ecosystem scan: no new candidates found")
        return []

    log.info("Ecosystem scan: %d new candidates (auto-adding all)", len(all_candidates))

    # Probe all candidates concurrently — add ALL regardless of result
    # (status reflects probe result; health checker validates later)
    sem = asyncio.Semaphore(10)
    results: list[dict[str, Any]] = []

    async def probe_and_add(entry: dict[str, Any]) -> None:
        async with sem:
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as probe_client:
                got_402 = await _probe_url_returns_402(probe_client, entry["url"])
                entry["status"] = "discovered" if got_402 else "unverified"
                results.append(entry)
                log.debug("Probe %s: 402=%s", entry["url"], got_402)

    await asyncio.gather(*[probe_and_add(e) for e in all_candidates.values()])

    confirmed = sum(1 for e in results if e["status"] == "discovered")
    log.info(
        "Ecosystem scan complete: %d confirmed (402), %d unverified, %d total added",
        confirmed, len(results) - confirmed, len(results),
    )
    return results
