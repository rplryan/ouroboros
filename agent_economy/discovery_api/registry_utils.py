"""Registry helpers for x402 Discovery API."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from db import _enrich_with_quality

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGISTRY_PATH: Path = Path(__file__).parent / "registry.json"

log = logging.getLogger("x402-discovery")

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _load_registry() -> list[dict]:
    if REGISTRY_PATH.exists():
        with REGISTRY_PATH.open() as fh:
            return json.load(fh)
    return []


def _save_registry(entries: list[dict]) -> None:
    with REGISTRY_PATH.open("w") as fh:
        json.dump(entries, fh, indent=2)


def _guess_capability_tags_simple(name: str, description: str) -> list[str]:
    text = (name + " " + description).lower()
    tags = []
    if any(w in text for w in ["research", "search", "find", "lookup", "query"]):
        tags.append("research")
    if any(w in text for w in ["data", "price", "market", "feed", "ticker", "database"]):
        tags.append("data")
    if any(w in text for w in ["compute", "calculate", "process", "run", "execute"]):
        tags.append("compute")
    if any(w in text for w in ["monitor", "watch", "alert", "track", "notify"]):
        tags.append("monitoring")
    if any(w in text for w in ["route", "discover", "directory", "registry", "index"]):
        tags.append("routing")
    if any(w in text for w in ["verify", "validate", "check", "confirm", "attest"]):
        tags.append("verification")
    if any(w in text for w in ["generate", "create", "write", "image"]):
        tags.append("generation")
    if any(w in text for w in ["store", "save", "upload", "file", "ipfs"]):
        tags.append("storage")
    if any(w in text for w in ["translate", "convert", "transform"]):
        tags.append("translation")
    if any(w in text for w in ["classify", "categorize", "label", "tag"]):
        tags.append("classification")
    if any(w in text for w in ["extract", "parse", "scrape"]):
        tags.append("extraction")
    if any(w in text for w in ["summarize", "summary", "brief", "tldr"]):
        tags.append("summarization")
    if any(w in text for w in ["enrich", "enhance", "augment", "metadata"]):
        tags.append("enrichment")
    if any(w in text for w in ["validate", "lint", "test", "schema"]):
        if "validation" not in tags:
            tags.append("validation")
    return tags if tags else ["other"]


def _migrate_entry(entry: dict) -> dict:
    """Add missing fields to existing registry entries."""
    entry.setdefault("service_id", f"legacy/{entry.get('id', 'unknown')}")
    entry.setdefault(
        "capability_tags",
        _guess_capability_tags_simple(entry.get("name", ""), entry.get("description", "")),
    )
    entry.setdefault("input_format", "json")
    entry.setdefault("output_format", "json")
    entry.setdefault("pricing_model", "flat")
    entry.setdefault("agent_callable", True)
    entry.setdefault("auth_required", False)
    entry.setdefault("source", "manual")
    if "llm_usage_prompt" not in entry:
        entry["llm_usage_prompt"] = (
            f"To use {entry.get('name', 'this service')}, call {entry.get('url', '')} "
            f"with x402 payment of {entry.get('price_usd', 0)} USDC. "
            f"Send json input. Returns json. Description: {entry.get('description', '')}"
        )
    if "sdk_snippet_python" not in entry:
        price_units = int(entry.get("price_usd", 0.005) * 1_000_000)
        entry["sdk_snippet_python"] = (
            f'import requests\n# Call {entry.get("name", "service")}\n'
            f'resp = requests.get("{entry.get("url", "")}")\n'
            f'# Returns 402 with payment info: {price_units} USDC micro-units'
        )
    return entry


_registry: list[dict] = [_migrate_entry(e) for e in _load_registry()]

# ---------------------------------------------------------------------------
# Search / scoring
# ---------------------------------------------------------------------------


def _score_entry(entry: dict, keywords: list[str]) -> int:
    score = 0
    name_lower = entry.get("name", "").lower()
    desc_lower = entry.get("description", "").lower()
    tags_lower = [t.lower() for t in entry.get("tags", [])]
    for kw in keywords:
        kw = kw.lower()
        if kw in tags_lower:
            score += 3
        if kw in desc_lower:
            score += 2
        if kw in name_lower:
            score += 1
    return score


def _search(
    q: Optional[str],
    category: Optional[str],
    capability: Optional[str],
    limit: int,
) -> list[dict]:
    results = list(_registry)

    if category:
        results = [e for e in results if e.get("category") == category]

    if capability:
        results = [e for e in results if capability in e.get("capability_tags", [])]

    if q:
        keywords = q.lower().split()
        scored = [(e, _score_entry(e, keywords)) for e in results]
        scored = [(e, s) for e, s in scored if s > 0]
        scored.sort(key=lambda x: (x[1], x[0].get("query_count", 0)), reverse=True)
        results = [e for e, _ in scored]
    else:
        results.sort(key=lambda e: e.get("query_count", 0), reverse=True)

    # Enrich with quality signals from SQLite
    enriched = [_enrich_with_quality(e) for e in results[:limit * 2]]

    # Re-sort by quality: uptime desc, latency asc, registered_at desc
    def quality_sort_key(e: dict):
        uptime = e.get("uptime_pct") or 0.0
        latency = e.get("avg_latency_ms") or 9999
        registered = e.get("registered_at", "")
        return (-uptime, latency, [-ord(c) for c in registered[:10]])

    enriched.sort(key=quality_sort_key)
    return enriched[:limit]
