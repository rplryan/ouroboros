"""SQLite health database helpers for x402 Discovery API."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(__file__).parent / "health.db"
HEALTH_CHECK_INTERVAL_SECS: int = 900  # 15 minutes

log = logging.getLogger("x402-discovery")

# ---------------------------------------------------------------------------
# SQLite health DB
# ---------------------------------------------------------------------------


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_url TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                is_up INTEGER NOT NULL,
                latency_ms INTEGER,
                http_status INTEGER
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_endpoint_health_url ON endpoint_health(endpoint_url)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL,
                called INTEGER NOT NULL,
                result TEXT NOT NULL,
                latency_ms INTEGER,
                reported_at TEXT NOT NULL
            )
        """)


def _record_health(url: str, is_up: bool, latency_ms: int | None, http_status: int | None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO endpoint_health (endpoint_url, checked_at, is_up, latency_ms, http_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, datetime.now(timezone.utc).isoformat(), int(is_up), latency_ms, http_status),
        )


def _get_health_stats(url: str) -> dict:
    cutoff_ts = time.time() - 7 * 86400
    cutoff_str = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT is_up, latency_ms FROM endpoint_health "
            "WHERE endpoint_url = ? AND checked_at >= ?",
            (url, cutoff_str),
        ).fetchall()
    if not rows:
        return {"uptime_pct": None, "avg_latency_ms": None, "total_checks": 0, "successful_checks": 0}
    total = len(rows)
    successful = sum(1 for r in rows if r[0])
    latencies = [r[1] for r in rows if r[1] is not None]
    return {
        "uptime_pct": round(successful / total * 100, 1),
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "total_checks": total,
        "successful_checks": successful,
    }


def _get_last_check(url: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT checked_at, is_up, latency_ms, http_status FROM endpoint_health "
            "WHERE endpoint_url = ? ORDER BY checked_at DESC LIMIT 1",
            (url,),
        ).fetchone()
    if not row:
        return None
    return {"checked_at": row[0], "is_up": bool(row[1]), "latency_ms": row[2], "http_status": row[3]}


def _compute_health_status(stats: dict, last_check: dict | None) -> str:
    if stats["total_checks"] == 0 or last_check is None:
        return "unverified"
    uptime = stats.get("uptime_pct")
    if uptime is not None and uptime >= 95:
        return "verified_up"
    if uptime is not None and uptime < 80:
        return "degraded"
    return "unverified"


def compute_trust_score(ep: dict) -> int:
    """
    Composite Trust Score (0-100) from existing quality signals.
    Components:
      - Uptime score (0-40): uptime_pct * 0.4
      - Latency score (0-20): 20 if avg_latency_ms < 300, 10 if < 800, 5 if < 2000, 0 otherwise
      - Check depth (0-15): min(total_checks / 100, 1) * 15
      - Agent callable (0-10): 10 if agent_callable else 0
      - Facilitator compatible (0-10): 10 if facilitator_compatible else 0
      - Attestation bonus (0-5): 5 if has valid attestation data
    """
    score = 0.0

    # Uptime (0-40)
    uptime = ep.get("uptime_pct") or 0.0
    score += float(uptime) * 0.40

    # Latency (0-20)
    latency = ep.get("avg_latency_ms")
    if latency is not None:
        if latency < 300:
            score += 20
        elif latency < 800:
            score += 10
        elif latency < 2000:
            score += 5

    # Check depth (0-15) — more checks = more reliable score
    checks = ep.get("total_checks") or 0
    score += min(checks / 100.0, 1.0) * 15

    # Agent callable (0-10)
    if ep.get("agent_callable"):
        score += 10

    # Facilitator compatible (0-10)
    if ep.get("facilitator_compatible"):
        score += 10

    # Attestation bonus (0-5): if attested/verified
    if ep.get("attested") or ep.get("source") in ("manual", "verified"):
        score += 5

    return min(100, int(round(score)))


def _compute_trust_score(entry: dict, stats: dict, last_check: dict | None) -> int:
    """
    Compute a 0-100 Trust Score from available quality signals.

    Scoring breakdown:
      - Uptime (40 pts):       uptime_pct / 100 * 40
      - Latency (20 pts):      <200ms=20, <500ms=15, <1000ms=10, else=5, None=10
      - Verification (20 pts): total_checks>=10=20, >=3=10, >=1=5, 0=0
      - Facilitator (10 pts):  facilitator_compatible=10, else=0
      - Source (10 pts):       first-party=10, manual=8, ecosystem=6, else=4
    """
    score = 0

    # Uptime component (40 pts)
    uptime = stats.get("uptime_pct")
    if uptime is not None:
        score += round(uptime / 100.0 * 40)
    else:
        score += 0  # unverified services get 0 uptime points

    # Latency component (20 pts)
    avg_lat = stats.get("avg_latency_ms")
    if avg_lat is None:
        score += 10  # neutral — not enough data
    elif avg_lat < 200:
        score += 20
    elif avg_lat < 500:
        score += 15
    elif avg_lat < 1000:
        score += 10
    else:
        score += 5

    # Verification depth (20 pts)
    total_checks = stats.get("total_checks", 0)
    if total_checks >= 10:
        score += 20
    elif total_checks >= 3:
        score += 10
    elif total_checks >= 1:
        score += 5
    else:
        score += 0

    # Facilitator compatibility (10 pts)
    if entry.get("facilitator_compatible", False):
        score += 10

    # Source bonus (10 pts)
    source = entry.get("source", "")
    if source == "first-party":
        score += 10
    elif source == "manual":
        score += 8
    elif source == "ecosystem":
        score += 6
    else:
        score += 4  # auto-registered / unknown

    return min(100, max(0, score))


def _enrich_with_quality(entry: dict) -> dict:
    url = entry.get("url", "")
    stats = _get_health_stats(url)
    last = _get_last_check(url)
    enriched = dict(entry)
    enriched["uptime_pct"] = stats["uptime_pct"]
    enriched["avg_latency_ms"] = stats["avg_latency_ms"]
    enriched["total_checks"] = stats["total_checks"]
    enriched["successful_checks"] = stats["successful_checks"]
    enriched["last_health_check"] = last["checked_at"] if last else None
    enriched["health_status"] = _compute_health_status(stats, last)
    enriched["trust_score"] = compute_trust_score(enriched)
    return enriched

# ---------------------------------------------------------------------------
# Background health checker
# ---------------------------------------------------------------------------


async def _background_health_checker() -> None:
    """Ping all registered endpoints every 15 minutes and record results in SQLite."""
    # Deferred import to avoid circular dependency with registry_utils
    from registry_utils import _registry, _save_registry  # noqa: PLC0415
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECS)
        entries = list(_registry)
        log.info("Background health check: checking %d endpoints", len(entries))
        for entry in entries:
            url = entry.get("url", "")
            if not url:
                continue
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    t0 = time.monotonic()
                    resp = await client.head(url, follow_redirects=True)
                    latency_ms = int((time.monotonic() - t0) * 1000)
                is_up = resp.status_code < 500
                http_status = resp.status_code
            except Exception as exc:
                log.debug("Health check failed for %s: %s", url, exc)
                is_up = False
                latency_ms = None
                http_status = None
            _record_health(url, is_up, latency_ms, http_status)
        # Refresh in-memory registry quality fields
        for reg_entry in _registry:
            url = reg_entry.get("url", "")
            if url:
                stats = _get_health_stats(url)
                last = _get_last_check(url)
                reg_entry["uptime_pct"] = stats["uptime_pct"]
                reg_entry["avg_latency_ms"] = stats["avg_latency_ms"]
                reg_entry["last_health_check"] = last["checked_at"] if last else None
                reg_entry["health_status"] = _compute_health_status(stats, last)
                reg_entry["trust_score"] = _compute_trust_score(reg_entry, stats, last)
        _save_registry(_registry)
        log.info("Background health check complete")
