"""Ecosystem scraper for x402 Service Discovery API.

Scans multiple sources for x402-enabled services and returns normalized entries
ready to be upserted into the registry:
  - https://x402.org/ecosystem   (official ecosystem page)
  - awesome-x402 README on GitHub (community curated list)

New entries are given:
  status = "discovered"
  source = "ecosystem_scan"
  facilitator_compatible = True (assumed — will be verified on next health check)
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
# Helpers
# ---------------------------------------------------------------------------

AWESOME_X402_README_URL = (
    "https://raw.githubusercontent.com/xpaysh/awesome-x402/main/README.md"
)
X402_ORG_ECOSYSTEM_URL = "https://x402.org/ecosystem"

# Timeouts
HTTP_TIMEOUT = 15.0
PROBE_TIMEOUT = 8.0


def _make_id(url: str) -> str:
    """Stable, short deterministic ID from URL."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _hostname_name(url: str) -> str:
    """Turn https://api.example.com/v1 -> 'Example'."""
    try:
        host = urlparse(url).hostname or url
        parts = host.split(".")
        # Remove common prefixes/suffixes
        filtered = [p for p in parts if p not in ("api", "www", "app", "com", "io", "net", "org", "xyz")]
        if filtered:
            return filtered[0].replace("-", " ").title()
        return parts[0].title()
    except Exception:
        return url[:30]


def _canonical_entry(url: str, name: str = "", description: str = "", category: str = "utility", tags: list[str] | None = None) -> dict[str, Any]:
    """Build a canonical registry entry from minimal info."""
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
        "asset_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
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
    }


async def _probe_url_returns_402(client: httpx.AsyncClient, url: str) -> bool:
    """Return True if URL returns HTTP 402 (x402 gateway active)."""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=PROBE_TIMEOUT)
        return resp.status_code == 402
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Source 1: awesome-x402 README (markdown link extraction)
# ---------------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_MD_HEADING_RE = re.compile(r"^#{1,4}\s+(.+)", re.MULTILINE)


def _parse_awesome_x402(md: str) -> list[dict[str, Any]]:
    """Extract service entries from awesome-x402 README markdown."""
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    # Track current section heading for category inference
    current_section = "utility"
    lines = md.split("\n")

    for line in lines:
        heading_match = _MD_HEADING_RE.match(line)
        if heading_match:
            heading_text = heading_match.group(1).lower()
            if any(w in heading_text for w in ["data", "analytics", "intelligence", "oracle"]):
                current_section = "data"
            elif any(w in heading_text for w in ["compute", "ai", "ml", "inference", "model"]):
                current_section = "compute"
            elif any(w in heading_text for w in ["agent", "automation", "workflow"]):
                current_section = "agent"
            elif any(w in heading_text for w in ["payment", "finance", "defi"]):
                current_section = "utility"
            else:
                current_section = "utility"

        for match in _MD_LINK_RE.finditer(line):
            name, url = match.group(1), match.group(2)
            # Skip non-service links (GitHub repos, docs, etc.)
            if any(skip in url for skip in [
                "github.com", "docs.", "discord.", "twitter.", "t.co",
                "medium.", "blog.", "npmjs.", "pypi.", "reddit.", "youtube.",
            ]):
                continue
            # Skip anchor links and mailto
            if url.startswith("#") or url.startswith("mailto:"):
                continue
            # Clean up URL — take base path without query
            clean_url = url.split("?")[0].rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            results.append(_canonical_entry(
                url=clean_url,
                name=name,
                description=f"x402 service listed on awesome-x402: {name}",
                category=current_section,
                tags=["x402", "awesome-x402", current_section],
            ))

    log.info("awesome-x402 README: found %d candidate URLs", len(results))
    return results


async def _fetch_awesome_x402(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch and parse awesome-x402 README."""
    try:
        resp = await client.get(AWESOME_X402_README_URL, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return _parse_awesome_x402(resp.text)
    except Exception as exc:
        log.warning("Failed to fetch awesome-x402 README: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source 2: x402.org/ecosystem (HTML parsing)
# ---------------------------------------------------------------------------

def _parse_x402_org_ecosystem(html: str) -> list[dict[str, Any]]:
    """Parse x402.org/ecosystem page for service cards.

    The page renders service cards with links. We extract all https:// links
    that look like API endpoints (not GitHub, docs, etc.).
    """
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
        soup = BeautifulSoup(html, "html.parser")

        # Find service cards — look for anchor tags with service URLs
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href.startswith("http"):
                continue
            # Skip non-service links
            if any(skip in href for skip in [
                "github.com", "docs.", "discord.", "twitter.", "t.co",
                "medium.", "blog.", "npmjs.", "pypi.", "reddit.",
                "x402.org", "coinbase.com/developer", "base.org",
            ]):
                continue

            clean_url = href.split("?")[0].rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            # Try to get a name from the surrounding context
            name = a_tag.get_text(strip=True) or _hostname_name(clean_url)
            # Look for a description in parent/sibling text
            parent = a_tag.parent
            desc = ""
            if parent:
                desc = parent.get_text(separator=" ", strip=True)[:200]

            # Infer category from text
            cat = "utility"
            combined = (name + " " + desc).lower()
            if any(w in combined for w in ["data", "analytics", "price", "intelligence", "oracle", "nansen", "zapper"]):
                cat = "data"
            elif any(w in combined for w in ["compute", "ai", "model", "inference", "llm"]):
                cat = "compute"
            elif any(w in combined for w in ["agent", "workflow", "automation"]):
                cat = "agent"

            results.append(_canonical_entry(
                url=clean_url,
                name=name,
                description=desc or f"x402 service from x402.org ecosystem: {name}",
                category=cat,
                tags=["x402", "x402.org", cat],
            ))

        log.info("x402.org/ecosystem: found %d candidate URLs", len(results))

    except ImportError:
        log.warning("BeautifulSoup not available — falling back to regex parsing for x402.org")
        # Fallback: regex extract all https:// links
        url_re = re.compile(r'href=["\']?(https?://[^\s"\'<>]+)["\']?')
        for match in url_re.finditer(html):
            url = match.group(1).split("?")[0].rstrip("/")
            if any(skip in url for skip in ["github.com", "docs.", "x402.org", "coinbase.com", "base.org"]):
                continue
            if url not in seen_urls:
                seen_urls.add(url)
                results.append(_canonical_entry(url=url, tags=["x402", "x402.org"]))

    return results


async def _fetch_x402_org_ecosystem(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch and parse x402.org/ecosystem page."""
    try:
        resp = await client.get(X402_ORG_ECOSYSTEM_URL, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return _parse_x402_org_ecosystem(resp.text)
    except Exception as exc:
        log.warning("Failed to fetch x402.org/ecosystem: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_ecosystem_scan(existing_urls: set[str]) -> list[dict[str, Any]]:
    """Scan all ecosystem sources and return new services not in existing_urls.

    Probes each candidate URL for a 402 response before adding.
    Returns only services that pass the probe OR where probe is inconclusive
    (some services require specific headers/paths to trigger 402).
    """
    log.info("Starting ecosystem scan (existing: %d services)", len(existing_urls))

    async with httpx.AsyncClient(
        headers={"User-Agent": "x402-discovery-bot/3.3.0 (+https://x402-discovery-api.onrender.com)"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        # Fetch from all sources concurrently
        awesome_entries, x402_org_entries = await asyncio.gather(
            _fetch_awesome_x402(client),
            _fetch_x402_org_ecosystem(client),
        )

    # Merge, deduplicate
    all_candidates: dict[str, dict[str, Any]] = {}
    for entry in awesome_entries + x402_org_entries:
        url = entry["url"]
        if url not in existing_urls and url not in all_candidates:
            all_candidates[url] = entry

    if not all_candidates:
        log.info("Ecosystem scan: no new candidates found")
        return []

    log.info("Ecosystem scan: %d new candidates to probe", len(all_candidates))

    # Probe all candidates concurrently (with semaphore to limit connections)
    sem = asyncio.Semaphore(10)
    results: list[dict[str, Any]] = []

    async def probe_and_add(entry: dict[str, Any]) -> None:
        async with sem:
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as probe_client:
                got_402 = await _probe_url_returns_402(probe_client, entry["url"])
                if got_402:
                    entry["status"] = "discovered"
                    results.append(entry)
                    log.debug("Probe 402 confirmed: %s", entry["url"])
                else:
                    # Include anyway with status "unverified" — health checker will validate
                    entry["status"] = "unverified"
                    results.append(entry)
                    log.debug("Probe: no 402 from %s (added as unverified)", entry["url"])

    await asyncio.gather(*[probe_and_add(e) for e in all_candidates.values()])

    confirmed = [e for e in results if e["status"] == "discovered"]
    unverified = [e for e in results if e["status"] == "unverified"]
    log.info(
        "Ecosystem scan complete: %d confirmed (402), %d unverified, %d total new",
        len(confirmed), len(unverified), len(results),
    )

    return results
