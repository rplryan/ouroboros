"""x402scan.com scraper for x402 Service Discovery API.

Fetches listings from x402scan.com and normalizes them to our canonical schema.
Called by the background scraper task in main.py every 6 hours.
"""
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

X402SCAN_API = "https://x402scan.com/api"
X402SCAN_WEB = "https://x402scan.com"


async def _try_api(client: httpx.AsyncClient) -> list[dict]:
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
    endpoints = []
    try:
        resp = await client.get(f"{X402SCAN_WEB}/servers", timeout=20)
        if resp.status_code != 200:
            resp = await client.get(X402SCAN_WEB, timeout=20)
        if resp.status_code != 200:
            return []
        url_pattern = re.compile(r"https?://[^\s\"'<>]{10,}")
        # Simple regex approach since bs4 may not be available
        for match in url_pattern.finditer(resp.text):
            url = match.group(0)
            if "x402scan" not in url and any(kw in url for kw in ["/api", "/v1", "/discover", "/query"]):
                endpoints.append({"url": url.split("?")[0], "name": ""})
    except Exception:
        pass
    return endpoints


def _categorize(name: str, description: str) -> str:
    text = (name + " " + description).lower()
    if any(w in text for w in ["research", "search", "web", "query", "rag"]):
        return "research"
    if any(w in text for w in ["data", "feed", "price", "crypto", "stock", "weather"]):
        return "data"
    if any(w in text for w in ["compute", "gpu", "inference", "llm", "model"]):
        return "compute"
    if any(w in text for w in ["route", "proxy", "gateway", "forward"]):
        return "routing"
    return "other"


def _normalize_entry(raw: dict) -> dict:
    url = raw.get("url") or raw.get("endpoint") or raw.get("endpoint_url") or ""
    name = raw.get("name") or raw.get("title") or raw.get("service_name") or ""
    description = raw.get("description") or raw.get("desc") or ""
    price = raw.get("price_per_call") or raw.get("price") or raw.get("amount") or 0.005
    if not url:
        return {}
    capability = _categorize(name, description)
    h = hashlib.md5(url.encode()).hexdigest()[:12]
    if isinstance(price, str):
        nums = re.findall(r"[\d.]+", price)
        price = float(nums[0]) if nums else 0.005
    return {
        "service_id": h,
        "id": h,
        "name": name or url,
        "description": description or f"x402-payable endpoint at {url}",
        "url": url,
        "price_usd": float(price),
        "pricing_model": "flat",
        "capability_tags": [capability],
        "category": capability,
        "agent_callable": True,
        "auth_required": False,
        "input_format": "json",
        "output_format": "json",
        "source": "x402scan",
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }


async def scrape_x402scan() -> list[dict]:
    results = []
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(headers={"User-Agent": "x402-discovery-scraper/1.0"}) as client:
        api_results = await _try_api(client)
        if api_results:
            for raw in api_results:
                entry = _normalize_entry(raw)
                if entry and entry.get("url") not in seen_urls:
                    results.append(entry)
                    seen_urls.add(entry["url"])
        web_results = await _parse_web_listings(client)
        for raw in web_results:
            entry = _normalize_entry(raw)
            if entry and entry.get("url") not in seen_urls:
                results.append(entry)
                seen_urls.add(entry["url"])
    return results
