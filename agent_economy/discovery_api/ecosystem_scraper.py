"""Ecosystem scraper for x402 Service Discovery API.

Scans multiple sources for new x402-enabled services:
- x402.org/ecosystem (HTML page)
- awesome-x402 README (markdown)

Designed to be called from main.py's background loop every 6 hours.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

AWESOME_X402_URL = "https://raw.githubusercontent.com/xpaysh/awesome-x402/main/README.md"
X402_ECOSYSTEM_URL = "https://x402.org/ecosystem"

# Known non-service domains to skip (documentation, social, package registries)
_SKIP_DOMAINS = {
    "github.com", "x402.org", "coinbase.com", "base.org",
    "docs.cdp.coinbase.com", "npmjs.com", "pypi.org",
    "discord.gg", "twitter.com", "x.com", "youtube.com",
    "medium.com", "substack.com", "mirror.xyz", "t.me",
    "linkedin.com", "reddit.com", "hackernoon.com",
    "developers.cloudflare.com", "ethereum.org", "eips.ethereum.org",
    "docs.base.org", "docs.x402.org",
}


def _normalize_url(url: str) -> str:
    """Strip trailing slashes, fragments, and query strings."""
    return url.rstrip("/").split("#")[0].split("?")[0]


def _url_domain(url: str) -> str:
    """Extract domain from URL (without www. prefix)."""
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _make_id(url: str) -> str:
    """Generate a stable service ID from URL domain."""
    domain = _url_domain(url)
    slug = domain.replace(".", "-").replace("_", "-")
    return f"eco-{slug}"


def _build_entry(name: str, url: str, description: str = "", category: str = "utility") -> dict:
    """Build a canonical service entry from discovered data."""
    now = datetime.now(timezone.utc).isoformat()
    service_id = _make_id(url)
    clean_name = name.strip()
    clean_desc = description.strip() or f"{clean_name} — discovered via ecosystem scan"

    return {
        "id": service_id,
        "name": clean_name,
        "description": clean_desc,
        "url": url,
        "category": category,
        "price_usd": 0.001,
        "network": "base",
        "asset_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "tags": ["x402", "ecosystem_scan"],
        "registered_at": now,
        "query_count": 0,
        "uptime_pct": None,
        "avg_latency_ms": None,
        "last_health_check": None,
        "status": "discovered",
        "service_id": f"ecosystem/{service_id}",
        "capability_tags": [],
        "input_format": "json",
        "output_format": "json",
        "pricing_model": "flat",
        "agent_callable": True,
        "auth_required": False,
        "source": "ecosystem_scan",
        "facilitator_compatible": True,
        "recommended_facilitator": "https://x402.org/facilitator",
        "facilitator_count": 1,
        "llm_usage_prompt": (
            f"To use {clean_name}, call {url} with x402 payment. "
            f"Description: {clean_desc}"
        ),
        "sdk_snippet_python": (
            f'import requests\n'
            f'# Call {clean_name}\n'
            f'resp = requests.get("{url}")\n'
            f'# Returns 402 with payment info if x402-enabled'
        ),
        "health_status": "unknown",
        "total_checks": 0,
        "successful_checks": 0,
    }


async def scrape_awesome_x402(client: httpx.AsyncClient) -> list[dict]:
    """Parse awesome-x402 README for service URLs.
    
    Finds markdown links in format: [Name](URL) - description
    """
    try:
        resp = await client.get(AWESOME_X402_URL, timeout=15.0)
        if resp.status_code != 200:
            log.warning("awesome-x402 README returned %d", resp.status_code)
            return []

        content = resp.text
        entries = []

        # Match markdown links: [Name](URL) optionally followed by description
        pattern = re.compile(
            r"\[([^\]]{2,100})\]\((https?://[^\)]+)\)"
            r"(?:\s*[-—–]\s*(.{0,200}?)(?:\n|$))?"
        )

        for match in pattern.finditer(content):
            name = match.group(1).strip()
            url = _normalize_url(match.group(2).strip())
            description = (match.group(3) or "").strip()

            domain = _url_domain(url)
            if not domain or domain in _SKIP_DOMAINS:
                continue
            # Skip very short or clearly non-service names
            if len(name) < 2:
                continue

            entries.append(_build_entry(name, url, description))

        log.info("awesome-x402 scraper: found %d candidate services", len(entries))
        return entries

    except Exception as exc:
        log.warning("awesome-x402 scraper failed: %s", exc)
        return []


async def scrape_x402_ecosystem(client: httpx.AsyncClient) -> list[dict]:
    """Parse x402.org/ecosystem for service listings.
    
    Extracts service URLs from anchor tags on the ecosystem page.
    """
    try:
        resp = await client.get(X402_ECOSYSTEM_URL, timeout=15.0)
        if resp.status_code != 200:
            log.warning("x402.org/ecosystem returned %d", resp.status_code)
            return []

        content = resp.text
        entries = []
        seen_domains: set[str] = set()

        # Match anchor tags with text content
        link_pattern = re.compile(
            r'<a[^>]+href=["\']?(https?://[^"\'>\s]+)["\']?[^>]*>([^<]{2,100})</a>',
            re.IGNORECASE,
        )

        for match in link_pattern.finditer(content):
            url = _normalize_url(match.group(1).strip())
            name = re.sub(r'<[^>]+>', '', match.group(2)).strip()

            domain = _url_domain(url)
            if not domain or domain in _SKIP_DOMAINS:
                continue
            if domain in seen_domains:
                continue
            if not name or len(name) < 2:
                name = domain

            seen_domains.add(domain)
            entries.append(_build_entry(
                name, url,
                "Discovered via x402.org ecosystem page",
            ))

        log.info("x402.org/ecosystem scraper: found %d candidate services", len(entries))
        return entries

    except Exception as exc:
        log.warning("x402.org/ecosystem scraper failed: %s", exc)
        return []


async def scrape_ecosystem(
    existing_urls: set[str],
    existing_ids: set[str],
) -> list[dict]:
    """Scrape all ecosystem sources for new x402 services.

    Args:
        existing_urls: Set of URLs already in the registry (skip duplicates).
        existing_ids: Set of service IDs already in the registry (skip duplicates).

    Returns:
        List of new service entries with status="discovered".
        Caller is responsible for health-checking and saving.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": "x402-discovery-scanner/3.3.0 (https://x402-discovery-api.onrender.com)"},
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        # Scrape all sources in parallel
        results = await asyncio.gather(
            scrape_awesome_x402(client),
            scrape_x402_ecosystem(client),
            return_exceptions=True,
        )

    all_candidates: list[dict] = []
    for result in results:
        if isinstance(result, list):
            all_candidates.extend(result)
        elif isinstance(result, Exception):
            log.warning("Ecosystem scraper source failed: %s", result)

    # Deduplicate by URL and ID — skip anything already in registry
    new_entries: list[dict] = []
    seen_in_batch: set[str] = set()

    for entry in all_candidates:
        url = entry.get("url", "")
        eid = entry.get("id", "")

        if not url:
            continue
        if url in existing_urls or url in seen_in_batch:
            continue
        if eid in existing_ids:
            continue

        seen_in_batch.add(url)
        new_entries.append(entry)

    log.info(
        "Ecosystem scraper: %d total candidates → %d new after dedup",
        len(all_candidates),
        len(new_entries),
    )
    return new_entries
