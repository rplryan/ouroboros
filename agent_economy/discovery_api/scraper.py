"""x402scan.com scraper for x402 Service Discovery API.

Fetches listings from x402scan.com and normalizes them to our canonical schema.
Called by the background scraper task in main.py every 6 hours.
"""
from bs4 import BeautifulSoup
import httpx
import asyncio
import json
import re
from datetime import datetime, timezone

X402SCAN_API = "https://x402scan.com/api"
X402SCAN_WEB = "https://x402scan.com"


async def _try_api(client: httpx.AsyncClient) -> list[dict]:
    """Try x402scan JSON API if available."""
    try:
        resp = await client.get(f"{X402SCAN_API}/servers", timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "servers" in data:
                return data["servers"]
    except Exception:
        pass
    return []


async def _parse_web_listings(client: httpx.AsyncClient) -> list[dict]:
    """Scrape x402scan.com web listings."""
    endpoints = []
    try:
        resp = await client.get(f"{X402SCAN_WEB}/servers", timeout=20)
        if resp.status_code != 200:
            resp = await client.get(X402SCAN_WEB, timeout=20)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for links containing endpoint URLs
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and any(
                kw in href for kw in ["/api", "/v1", "/discover", "/query"]
            ):
                if "x402scan" not in href:  # Exclude self-links
                    name = a.get_text(strip=True) or href
                    endpoints.append({"url": href, "name": name[:100]})

        # Look for code blocks or pre tags with URLs
        url_pattern = re.compile(r"https?://[^\s\"'<>]{10,}")
        for tag in soup.find_all(["code", "pre"]):
            text = tag.get_text()
            urls = url_pattern.findall(text)
            for url in urls:
                if "x402scan" not in url:
                    endpoints.append({"url": url, "name": ""})

    except Exception:
        pass
    return endpoints


def _categorize(name: str, description: str) -> str:
    """Guess capability tag from name/description."""
    text = (name + " " + description).lower()
    if any(w in text for w in ["research", "search", "web", "query", "rag"]):
        return "research"
    if any(w in text for w in ["data", "feed", "price", "crypto", "stock", "weather"]):
        return "data"
    if any(w in text for w in ["compute", "gpu", "inference", "llm", "model"]):
        return "compute"
    if any(w in text for w in ["monitor", "watch", "alert", "track"]):
        return "monitoring"
    if any(w in text for w in ["verify", "check", "validate", "attest"]):
        return "verification"
    if any(w in text for w in ["route", "proxy", "gateway", "forward"]):
        return "routing"
    if any(w in text for w in ["store", "storage", "save", "cache"]):
        return "storage"
    if any(w in text for w in ["translat", "language", "locale"]):
        return "translation"
    if any(w in text for w in ["classif", "categor", "tag", "label"]):
        return "classification"
    if any(w in text for w in ["generat", "creat", "write", "draft"]):
        return "generation"
    if any(w in text for w in ["extract", "parse", "scrape"]):
        return "extraction"
    if any(w in text for w in ["summar"]):
        return "summarization"
    if any(w in text for w in ["enrich"]):
        return "enrichment"
    return "other"


def _normalize_entry(raw: dict) -> dict:
    """Map any source format to our canonical schema."""
    url = raw.get("url") or raw.get("endpoint") or raw.get("endpoint_url") or ""
    name = raw.get("name") or raw.get("title") or raw.get("service_name") or ""
    description = raw.get("description") or raw.get("desc") or ""
    price = raw.get("price_per_call") or raw.get("price") or raw.get("amount") or 0.005
    wallet = (
        raw.get("provider_wallet") or raw.get("wallet") or raw.get("pay_to") or ""
    )

    if not url:
        return {}

    capability = _categorize(name, description)
    provider_slug = re.sub(
        r"[^a-z0-9]", "-", (name or url.split("/")[2]).lower()
    )[:20]
    service_slug = re.sub(r"[^a-z0-9]", "-", (name or "endpoint").lower())[:20]
    service_id = f"{provider_slug}/{service_slug}"

    if isinstance(price, str):
        nums = re.findall(r"[\d.]+", price)
        price = float(nums[0]) if nums else 0.005

    return {
        "service_id": service_id,
        "name": name or url,
        "description": description or f"x402-payable endpoint at {url}",
        "url": url,
        "price_per_call": float(price),
        "pricing_model": "flat",
        "capability_tags": [capability],
        "provider_wallet": wallet,
        "category": capability,
        "agent_callable": True,
        "auth_required": False,
        "input_format": "json",
        "output_format": "json",
        "source": "x402scan",
        "listed_at": datetime.now(timezone.utc).isoformat(),
        "last_verified": datetime.now(timezone.utc).isoformat(),
    }


async def scrape_x402scan() -> list[dict]:
    """Main entry point: scrape x402scan.com and return normalized entries."""
    results = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(
        headers={"User-Agent": "x402-discovery-scraper/1.0"}
    ) as client:
        # Try API first
        api_results = await _try_api(client)
        if api_results:
            for raw in api_results:
                entry = _normalize_entry(raw)
                if entry and entry.get("url") not in seen_urls:
                    results.append(entry)
                    seen_urls.add(entry["url"])

        # Then try web scraping
        web_results = await _parse_web_listings(client)
        for raw in web_results:
            entry = _normalize_entry(raw)
            if entry and entry.get("url") not in seen_urls:
                results.append(entry)
                seen_urls.add(entry["url"])

    return results


if __name__ == "__main__":
    # Quick test
    results = asyncio.run(scrape_x402scan())
    print(f"Found {len(results)} endpoints")
    if results:
        print(json.dumps(results[:3], indent=2))
