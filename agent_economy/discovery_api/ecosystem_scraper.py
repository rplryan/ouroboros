"""Ecosystem scraper for x402 Service Discovery API.

Scans x402.org/ecosystem and the awesome-x402 README for new services
every 6 hours and upserts them into the registry.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

ECOSYSTEM_URL = "https://x402.org/ecosystem"
AWESOME_X402_URL = "https://raw.githubusercontent.com/xpaysh/awesome-x402/main/README.md"

# URLs/domains to skip (internal links, social, docs, etc.)
_SKIP_DOMAINS = [
    "x402.org", "github.com", "twitter.com", "x.com",
    "discord", "t.me", "docs.", "blog.", "medium.com",
    "coinbase.com", "base.org", "shields.io", "badgen.net",
    "npmjs.com", "pypi.org",
]


def _make_id(url: str, name: str) -> str:
    """Generate a stable 12-char ID from URL + name."""
    raw = f"{url}:{name}".lower()
    return hashlib.md5(raw.encode()).hexdigest()[:12]


async def _probe_url(client: httpx.AsyncClient, url: str) -> dict:
    """Probe URL and return status/latency info."""
    try:
        start = asyncio.get_event_loop().time()
        resp = await client.get(url, timeout=8.0, follow_redirects=True)
        latency_ms = int((asyncio.get_event_loop().time() - start) * 1000)
        if resp.status_code == 402:
            return {"status": "active", "latency_ms": latency_ms, "uptime_pct": 99.0}
        elif resp.status_code in (200, 201):
            return {"status": "discovered", "latency_ms": latency_ms, "uptime_pct": 95.0}
        else:
            return {"status": "discovered", "latency_ms": latency_ms, "uptime_pct": 80.0}
    except httpx.TimeoutException:
        return {"status": "discovered", "latency_ms": 9999, "uptime_pct": 50.0}
    except Exception:
        return {"status": "discovered", "latency_ms": 9999, "uptime_pct": 0.0}


def _make_entry(name: str, url: str, description: str, category: str, probe: dict) -> dict:
    """Build a normalized service entry compatible with the registry schema."""
    now = datetime.now(timezone.utc).isoformat()
    entry_id = _make_id(url, name)
    return {
        "id": entry_id,
        "name": name,
        "description": description or f"x402-enabled service: {name}",
        "url": url,
        "category": category,
        "price_usd": 0.001,
        "network": "eip155:8453",
        "asset_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "tags": ["x402", "ecosystem", "discovered"],
        "registered_at": now,
        "query_count": 0,
        "uptime_pct": probe.get("uptime_pct", 50.0),
        "avg_latency_ms": probe.get("latency_ms", 9999),
        "last_health_check": now,
        "status": probe.get("status", "discovered"),
        "facilitator_compatible": True,
        "recommended_facilitator": "https://facilitator.payai.network",
        "facilitator_count": 0,
        "capability_tags": ["x402"],
        "source": "ecosystem_scan",
        "service_id": entry_id,
        "input_format": "HTTP",
        "output_format": "JSON",
        "pricing_model": "per-call",
        "agent_callable": True,
        "auth_required": False,
    }


def _infer_category(name: str, desc: str) -> str:
    """Infer service category from name/description keywords."""
    low = (name + " " + desc).lower()
    if any(w in low for w in ["data", "price", "token", "analytics", "score", "intelligence", "blockchain", "dex"]):
        return "data"
    if any(w in low for w in ["compute", "llm", "model", "ai", "ml", "gpu", "inference", "generation"]):
        return "compute"
    if any(w in low for w in ["agent", "bot", "autonomous", "workflow", "task"]):
        return "agent"
    return "utility"


async def scrape_x402_ecosystem() -> list[dict]:
    """Scrape x402.org/ecosystem for service listings."""
    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(ECOSYSTEM_URL)
            if resp.status_code != 200:
                log.warning("x402.org/ecosystem returned %d", resp.status_code)
                return []
            html = resp.text

            # Extract all external links from the page
            url_pattern = re.compile(
                r'href=["\']?(https?://[^"\'>\s]+)["\']?[^>]*>([^<]{3,80})<',
                re.IGNORECASE,
            )
            seen_urls: set[str] = set()
            candidates: list[tuple[str, str]] = []

            for m in url_pattern.finditer(html):
                href, name = m.group(1).strip(), m.group(2).strip()
                if any(skip in href for skip in _SKIP_DOMAINS):
                    continue
                if href in seen_urls or not name or len(name) < 3:
                    continue
                seen_urls.add(href)
                candidates.append((name, href))

            log.info("x402.org/ecosystem: found %d candidate URLs", len(candidates))

            for name, url in candidates[:50]:  # cap to avoid rate limiting
                probe = await _probe_url(client, url)
                results.append(_make_entry(
                    name=name,
                    url=url,
                    description="Discovered via x402.org ecosystem page.",
                    category=_infer_category(name, ""),
                    probe=probe,
                ))
                await asyncio.sleep(0.3)

    except Exception as exc:
        log.warning("x402.org ecosystem scrape failed: %s", exc)

    log.info("x402.org ecosystem scraper: %d entries found", len(results))
    return results


async def scrape_awesome_x402() -> list[dict]:
    """Scrape the awesome-x402 README for service links."""
    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(AWESOME_X402_URL)
            if resp.status_code != 200:
                log.warning("awesome-x402 README returned %d", resp.status_code)
                return []
            md = resp.text

            # Parse Markdown links: [Name](URL)
            link_pattern = re.compile(r'\[([^\]]{3,80})\]\((https?://[^\)]+)\)')
            seen_urls: set[str] = set()
            candidates: list[tuple[str, str, str]] = []

            for line in md.split("\n"):
                for m in link_pattern.finditer(line):
                    name, url = m.group(1).strip(), m.group(2).strip()
                    if url in seen_urls:
                        continue
                    if any(skip in url for skip in _SKIP_DOMAINS):
                        continue
                    seen_urls.add(url)
                    # Try to grab inline description (text after "—" or "-")
                    desc_m = re.search(r'\)\s*[—–-]\s*(.+)', line)
                    desc = desc_m.group(1).strip() if desc_m else ""
                    candidates.append((name, url, desc))

            log.info("awesome-x402: found %d candidate URLs", len(candidates))

            for name, url, desc in candidates[:50]:
                probe = await _probe_url(client, url)
                results.append(_make_entry(
                    name=name,
                    url=url,
                    description=desc or "Discovered via awesome-x402 curated list.",
                    category=_infer_category(name, desc),
                    probe=probe,
                ))
                await asyncio.sleep(0.3)

    except Exception as exc:
        log.warning("awesome-x402 scrape failed: %s", exc)

    log.info("awesome-x402 scraper: %d entries found", len(results))
    return results


async def run_ecosystem_scan(existing_urls: set[str]) -> list[dict]:
    """Run all ecosystem scrapers; return only NEW services not already in the registry.

    Args:
        existing_urls: Set of URLs already registered (used to deduplicate).

    Returns:
        List of new service entries ready to append to the registry.
    """
    ecosystem_entries, awesome_entries = await asyncio.gather(
        scrape_x402_ecosystem(),
        scrape_awesome_x402(),
        return_exceptions=True,
    )

    if isinstance(ecosystem_entries, Exception):
        log.warning("Ecosystem scraper error: %s", ecosystem_entries)
        ecosystem_entries = []
    if isinstance(awesome_entries, Exception):
        log.warning("Awesome-x402 scraper error: %s", awesome_entries)
        awesome_entries = []

    all_new: list[dict] = []
    seen_in_run: set[str] = set()

    for entry in list(ecosystem_entries) + list(awesome_entries):  # type: ignore[operator]
        url = entry.get("url", "")
        if url and url not in existing_urls and url not in seen_in_run:
            all_new.append(entry)
            seen_in_run.add(url)

    log.info(
        "Ecosystem scan complete: %d new services (ecosystem=%d, awesome=%d)",
        len(all_new),
        len(ecosystem_entries),  # type: ignore[arg-type]
        len(awesome_entries),    # type: ignore[arg-type]
    )
    return all_new
