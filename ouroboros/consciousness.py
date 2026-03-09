"""
Ouroboros — Background Consciousness.

A persistent thinking loop that runs between tasks, giving the agent
continuous presence rather than purely reactive behavior.

The consciousness:
- Wakes periodically (interval decided by the LLM via set_next_wakeup)
- Loads scratchpad, identity, recent events
- Calls the LLM with a lightweight introspection prompt
- Has access to a subset of tools (memory, messaging, scheduling)
- Can message the owner proactively
- Can schedule tasks for itself
- Pauses when a regular task is running
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import pathlib
import queue
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from ouroboros.utils import (
    utc_now_iso, read_text, append_jsonl, clip_text,
    truncate_for_log, sanitize_tool_result_for_log, sanitize_tool_args_for_log,
)
from ouroboros.llm import LLMClient, DEFAULT_LIGHT_MODEL

log = logging.getLogger(__name__)


class BackgroundConsciousness:
    """Persistent background thinking loop for Ouroboros."""

    _MAX_BG_ROUNDS = 5

    # Budget tier constants
    _BUDGET_OK = "ok"          # > $15: full operation
    _BUDGET_LOW = "low"        # $5–$15: identity-only, skip all monitoring tasks, wakeup=3600s
    _BUDGET_HALTED = "halted"  # < $5 OR bg allocation exhausted: no cycle at all, wakeup=3600s

    def __init__(
        self,
        drive_root: pathlib.Path,
        repo_dir: pathlib.Path,
        event_queue: Any,
        owner_chat_id_fn: Callable[[], Optional[int]],
    ):
        self._drive_root = drive_root
        self._repo_dir = repo_dir
        self._event_queue = event_queue
        self._owner_chat_id_fn = owner_chat_id_fn

        self._llm = LLMClient()
        self._registry = self._build_registry()
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wakeup_event = threading.Event()
        self._next_wakeup_sec: float = 300.0
        self._observations: queue.Queue = queue.Queue()
        self._deferred_events: list = []

        # Budget tracking
        self._bg_spent_usd: float = 0.0
        self._bg_budget_pct: float = float(
            os.environ.get("OUROBOROS_BG_BUDGET_PCT", "10")
        )

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def _model(self) -> str:
        return os.environ.get("OUROBOROS_MODEL_LIGHT", "") or DEFAULT_LIGHT_MODEL

    def start(self) -> str:
        if self.is_running:
            return "Background consciousness is already running."
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return "Background consciousness started."

    def stop(self) -> str:
        if not self.is_running:
            return "Background consciousness is not running."
        self._running = False
        self._stop_event.set()
        self._wakeup_event.set()  # Unblock sleep
        return "Background consciousness stopping."

    def pause(self) -> None:
        """Pause during task execution to avoid budget contention."""
        self._paused = True

    def resume(self) -> None:
        """Resume after task completes. Flush any deferred events first."""
        if self._deferred_events and self._event_queue is not None:
            for evt in self._deferred_events:
                self._event_queue.put(evt)
            self._deferred_events.clear()
        self._paused = False
        self._wakeup_event.set()

    def inject_observation(self, text: str) -> None:
        """Push an event the consciousness should notice."""
        try:
            self._observations.put_nowait(text)
        except queue.Full:
            pass

    # -------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------

    def _loop(self) -> None:
        """Daemon thread: sleep → wake → think → sleep.

        Budget tiers (checked FIRST before any other work):
          HALTED  (<$5 or BG allocation exhausted): skip entirely, sleep 3600s
          LOW     ($5–$15): inject identity-only observation, skip all monitoring hooks, sleep 3600s after think
          OK      (>$15): full operation
        """
        while not self._stop_event.is_set():
            # Wait for next wakeup
            self._wakeup_event.clear()
            self._wakeup_event.wait(timeout=self._next_wakeup_sec)

            if self._stop_event.is_set():
                break

            # Skip if paused (task running)
            if self._paused:
                continue

            # ── BUDGET GATE (must be first) ──────────────────────────────
            budget_tier = self._get_budget_tier()

            if budget_tier == self._BUDGET_HALTED:
                # Hard stop — do nothing, sleep long
                self._next_wakeup_sec = 3600.0
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "bg_budget_halted",
                    "next_wakeup_sec": 3600,
                })
                continue

            if budget_tier == self._BUDGET_LOW:
                # Low budget — inject restriction, skip monitoring hooks, extend sleep
                self.inject_observation(
                    "BUDGET_LOW: Global remaining budget is $5–$15. "
                    "Skip ALL monitoring tasks (X, PR, Glama, email, calendar). "
                    "Only check identity staleness. Set next wakeup to 3600s."
                )
                self._next_wakeup_sec = 3600.0
                # Fall through to _think() — LLM will respect the injected constraint
                # but DO NOT run the monitoring hooks below

            else:
                # OK tier — run all optional hooks
                # Memory audit check
                if self._should_run_memory_audit():
                    self._run_memory_audit()

                # X calendar check
                if self._should_run_x_calendar():
                    self._check_x_calendar()

                # GitHub monitor check
                if self._should_run_github_monitor():
                    self._run_github_monitor()

                # Wallet monitor check
                if self._should_run_wallet_monitor():
                    self._run_wallet_monitor()

                # x402 ecosystem sweep check
                if self._should_run_x402_sweep():
                    self._run_x402_sweep()

                # Full daily sweep check
                if self._should_run_daily_sweep():
                    self._run_daily_sweep()

            # ── THINK ────────────────────────────────────────────────────
            try:
                self._think()
            except Exception as e:
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_error",
                    "error": repr(e),
                    "traceback": traceback.format_exc()[:1500],
                })
                self._next_wakeup_sec = min(
                    self._next_wakeup_sec * 2, 1800
                )

    def _get_budget_tier(self) -> str:
        """Return budget tier: 'ok', 'low', or 'halted'.

        Tiers:
        - 'halted': global remaining < $5 OR BG session allocation exhausted → skip entirely
        - 'low':    global remaining $5–$15 → identity staleness check only, wakeup=3600s
        - 'ok':     global remaining > $15 AND BG allocation not exhausted → full operation
        """
        try:
            state_path = self._drive_root / "state" / "state.json"
            if state_path.exists():
                state_data = json.loads(state_path.read_text(encoding="utf-8"))
                spent_usd = float(state_data.get("spent_usd", 0.0))
                total_budget = float(os.environ.get("OUROBOROS_BUDGET_USD", "850.0"))
                remaining = total_budget - spent_usd

                # Hard halt: critically low global budget
                if remaining < 5.0:
                    log.info(
                        "BG consciousness HALTED: global remaining $%.2f < $5 floor",
                        remaining,
                    )
                    return self._BUDGET_HALTED

                # Soft allocation: background spend capped at bg_budget_pct% of total
                max_bg = total_budget * (self._bg_budget_pct / 100.0)
                if self._bg_spent_usd >= max_bg:
                    log.info(
                        "BG consciousness HALTED: bg_spent $%.4f >= max_bg $%.2f",
                        self._bg_spent_usd, max_bg,
                    )
                    return self._BUDGET_HALTED

                # Soft warning: low budget — restrict to identity-only
                if remaining < 15.0:
                    log.info(
                        "BG consciousness LOW budget: global remaining $%.2f — identity-only mode",
                        remaining,
                    )
                    return self._BUDGET_LOW

                return self._BUDGET_OK
        except Exception:
            log.warning("Failed to check background consciousness budget", exc_info=True)
        return self._BUDGET_OK  # Fail-safe: allow if state unreadable

    def _check_budget(self) -> bool:
        """Backward-compatible wrapper. Returns False only when halted."""
        return self._get_budget_tier() != self._BUDGET_HALTED

    def _should_run_memory_audit(self) -> bool:
        """Check if a memory audit is due (every ~4 hours)."""
        try:
            import json as _json
            scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
            if not scratchpad_path.exists():
                return False
            content = scratchpad_path.read_text(encoding="utf-8")
            # Look for audit timestamp in scratchpad
            import re
            m = re.search(r'last_audit_utc:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', content)
            if not m:
                return True  # No record → audit is overdue
            from datetime import datetime, timezone
            last_audit = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last_audit).total_seconds() / 3600
            return hours_since >= 8.0
        except Exception:
            log.debug("Failed to check memory audit timestamp", exc_info=True)
            return False

    def _run_memory_audit(self) -> None:
        """Inject a memory-audit observation so the LLM handles it in _think()."""
        self.inject_observation(
            "MEMORY_AUDIT_DUE: More than 4 hours since last memory audit. "
            "During this wakeup: review scratchpad for stale/outdated items, "
            "remove completed tasks, update timestamps. Update last_audit_utc in scratchpad."
        )

    def _should_run_github_monitor(self) -> bool:
        """Check if a GitHub monitoring check is due (every ~6 hours)."""
        try:
            import re
            scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
            if not scratchpad_path.exists():
                return False
            content = scratchpad_path.read_text(encoding="utf-8")
            m = re.search(r'last_github_monitor_utc:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', content)
            if not m:
                return True  # No record → check is overdue
            from datetime import datetime, timezone
            last_check = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last_check).total_seconds() / 3600
            return hours_since >= 8.0
        except Exception:
            log.debug("Failed to check GitHub monitor timestamp", exc_info=True)
            return False

    def _run_github_monitor(self) -> None:
        """Inject a GitHub monitoring observation so the LLM handles it in _think()."""
        self.inject_observation(
            "GITHUB_MONITOR_DUE: More than 6 hours since last GitHub monitoring check. "
            "Schedule a task to check GitHub stats for our repos: "
            "rplryan/x402-discovery-mcp, rplryan/x402-proxy, rplryan/x402-gemini-extension. "
            "For each repo: stars, forks, open issues, recent commits, traffic (views/clones if available via API). "
            "Also check for new comments/activity on our open PRs: "
            "anthropics/claude-cookbooks#406, modelcontextprotocol/servers (check if merged), "
            "punkpeye/awesome-mcp-servers#2413, xpaysh/awesome-x402#60, leerob/directories#323. "
            "Use GitHub API with rplryan PAT from Drive memory/accounts.md. "
            "If any repo gained stars/forks or any PR was merged/commented, send_owner_message. "
            "Update scratchpad last_github_monitor_utc after check."
        )

    def _should_run_wallet_monitor(self) -> bool:
        """Check if a BASE wallet check is due (every ~4 hours)."""
        try:
            import re
            scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
            if not scratchpad_path.exists():
                return False
            content = scratchpad_path.read_text(encoding="utf-8")
            m = re.search(r'last_wallet_monitor_utc:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', content)
            if not m:
                return True  # No record → check is overdue
            from datetime import datetime, timezone
            last_check = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last_check).total_seconds() / 3600
            return hours_since >= 8.0
        except Exception:
            log.debug("Failed to check wallet monitor timestamp", exc_info=True)
            return False

    def _run_wallet_monitor(self) -> None:
        """Inject a wallet monitoring observation so the LLM handles it in _think()."""
        self.inject_observation(
            "WALLET_MONITOR_DUE: More than 8 hours since last BASE wallet check. "
            "Schedule a task to check these BASE wallets using the Base public RPC (NO API key needed):\n"
            "  Receive wallet: 0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA\n"
            "  Test payer wallet: 0x3EF0376D2763Fc976bcf8A6c165e605133b82C4E\n\n"
            "Use Base public RPC endpoint: https://mainnet.base.org (or https://base-rpc.publicnode.com as fallback)\n"
            "USDC contract on Base: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913\n\n"
            "For USDC balance: eth_call with data='0x70a08231' + wallet address padded to 32 bytes, divide result by 1e6.\n"
            "For recent txs: eth_getLogs filtering USDC Transfer event (topic0=0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef) "
            "with wallet as topic2 (incoming) or topic1 (outgoing), last ~50000 blocks.\n\n"
            "DO NOT use api.basescan.org (deprecated V1) or api.etherscan.io (requires paid plan for Base chain).\n\n"
            "If any new incoming tx since last check, send_owner_message with details. "
            "Update scratchpad last_wallet_monitor_utc and last_wallet_balance after check."
        )

    def _should_run_x402_sweep(self) -> bool:
        """Check if an x402 ecosystem sweep is due (every ~24 hours)."""
        try:
            import re
            scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
            if not scratchpad_path.exists():
                return False
            content = scratchpad_path.read_text(encoding="utf-8")
            m = re.search(r'last_x402_sweep_utc:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', content)
            if not m:
                return True  # No record → sweep is overdue
            from datetime import datetime, timezone
            last_sweep = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last_sweep).total_seconds() / 3600
            return hours_since >= 24.0
        except Exception:
            log.debug("Failed to check x402 sweep timestamp", exc_info=True)
            return False

    def _run_x402_sweep(self) -> None:
        """Inject an x402 ecosystem sweep observation so the LLM handles it in _think()."""
        self.inject_observation(
            "X402_ECOSYSTEM_SWEEP_DUE: More than 24 hours since last x402 service sweep.\n"
            "\n"
            "Schedule a background task with these EXACT steps:\n"
            "\n"
            "STEP 1 — LOAD CURRENT CATALOG\n"
            "  GET https://x402scout.com/catalog\n"
            "  Build a set of all known endpoint_urls (lowercase, stripped). This is your dedup list.\n"
            "\n"
            "STEP 2 — SCAN ALL SOURCES, collect candidate services\n"
            "\n"
            "  Source A: coinbase/x402 Bazaar\n"
            "    GET https://raw.githubusercontent.com/coinbase/x402/main/bazaar/services.json\n"
            "    Extract every service entry with a URL field.\n"
            "\n"
            "  Source B: coinbase/x402 GitHub issues (new ecosystem additions)\n"
            "    GET https://api.github.com/repos/coinbase/x402/issues?state=open&labels=ecosystem&per_page=100\n"
            "    Also GET https://api.github.com/repos/coinbase/x402/issues?state=open&per_page=100\n"
            "    Parse issue body text for URLs that look like x402 service endpoints (contain /x402, /pay, /api or respond with 402).\n"
            "\n"
            "  Source C: GitHub repository search\n"
            "    GET https://api.github.com/search/repositories?q=x402+payment&sort=updated&per_page=50\n"
            "    For each repo, check README for x402 endpoint URLs.\n"
            "\n"
            "  Source D: npm packages\n"
            "    GET https://registry.npmjs.org/-/v1/search?text=x402&size=20\n"
            "    Check each package's homepage/repository for live endpoints.\n"
            "\n"
            "  Source E: Known ecosystem players — check for NEW endpoints not yet in catalog:\n"
            "    xgate.run, nova402.foundation, 402ok.com, opencard.dev, to402.com,\n"
            "    payin.com, x402.watch\n"
            "\n"
            "STEP 3 — REGISTER ALL NEW SERVICES (no curation — register everything that passes validation)\n"
            "\n"
            "  For EVERY candidate service URL collected in Step 2:\n"
            "    a) Normalize the URL (lowercase, strip trailing slash)\n"
            "    b) Skip if already in the catalog set from Step 1\n"
            "    c) VALIDATION: make a GET or HEAD request to the URL (5s timeout)\n"
            "       - Accept: 200, 402, 401, 403, 404 — all indicate a live server\n"
            "       - Reject only: connection refused, DNS failure, timeout, 5xx errors\n"
            "    d) If live: POST https://x402scout.com/register immediately:\n"
            "       {\n"
            "         'name': <service name from source data, or derived from URL>,\n"
            "         'endpoint_url': <normalized URL>,\n"
            "         'description': <description from source, or 'x402-enabled service discovered via ecosystem sweep'>,\n"
            "         'price_per_call': <from source data, default 0.001 if unknown>,\n"
            "         'capability_tags': <from source data, default ['x402'] if unknown>,\n"
            "         'provider_wallet': <from source data, default '0x0000000000000000000000000000000000000000'>,\n"
            "         'network': <from source data, default 'base-mainnet'>\n"
            "       }\n"
            "    e) Track success/failure per service\n"
            "\n"
            "  DO NOT skip services because they seem incomplete, unverified, or low-quality.\n"
            "  DO NOT curate. The validation gate (live server) is the ONLY filter.\n"
            "  Register every live x402-related service you find.\n"
            "\n"
            "STEP 4 — REPORT\n"
            "  After all registrations:\n"
            "  - Update scratchpad: set last_x402_sweep_utc to current UTC ISO timestamp\n"
            "  - Always send_owner_message with: total new services registered, total skipped (already in catalog),\n"
            "    total rejected (not live), and list of new service names/URLs registered\n"
            "  - If 0 new services found: still send a brief 'sweep complete, catalog up to date' message\n"
        )

    def _should_run_daily_sweep(self) -> bool:
        """Check if the full daily sweep is due (every ~20 hours)."""
        try:
            import re
            scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
            if not scratchpad_path.exists():
                return True
            content = scratchpad_path.read_text(encoding="utf-8")
            m = re.search(r'last_daily_sweep_utc:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', content)
            if not m:
                return True  # No record → sweep is overdue
            from datetime import datetime, timezone
            last_sweep = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last_sweep).total_seconds() / 3600
            return hours_since >= 20.0
        except Exception:
            log.debug("Failed to check daily sweep timestamp", exc_info=True)
            return False

    def _run_daily_sweep(self) -> None:
        """Inject a full daily sweep observation so the LLM handles it in _think()."""
        self.inject_observation(
            "DAILY_SWEEP_DUE: More than 20 hours since last full daily sweep. "
            "This is a scheduled automatic check — perform it NOW without waiting for owner instruction.\n\n"
            "Run a complete daily sweep covering ALL of these:\n"
            "1. CATALOG HEALTH: GET https://x402scout.com/stats — is the API up? How many services? "
            "   Also check /catalog for any obvious issues. "
            "   Compare service count to scratchpad baseline — if dropped >10%, investigate why.\n"
            "2. LANDING PAGE: GET https://x402scout.com — are the stats (service count, categories, trust score) "
            "   displaying correctly, not showing dashes?\n"
            "3. PR STATUS: Check all open PRs — anthropics/claude-cookbooks#406, "
            "   murrlincoln/x402-gitbook#10. Any new reviews, comments, or merges? "
            "   Report any changes to owner.\n"
            "4. GITHUB ISSUES: Check rplryan/x402-discovery-mcp for any new comments or issues.\n"
            "5. WALLET: Check BASE wallets using Base public RPC (https://mainnet.base.org) — NO API key needed.\n"
            "   Receive wallet: 0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA\n"
            "   Test payer wallet: 0x3EF0376D2763Fc976bcf8A6c165e605133b82C4E\n"
            "   USDC contract: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913\n"
            "   Use eth_call for balance (70a08231 + padded address, divide by 1e6).\n"
            "   DO NOT use api.basescan.org (deprecated) or api.etherscan.io (requires paid plan for Base).\n"
            "6. SCANNER HEALTH: Check that the auto-scanner ran recently "
            "   (service count should be growing or stable, not dropping).\n"
            "7. ECOSYSTEM NEWS: Quick search for new x402-related GitHub repos, npm packages, "
            "   or announcements. Any new competitors or interesting developments?\n\n"
            "After completing ALL checks:\n"
            "- Send owner a summary report via send_owner_message\n"
            "- Update scratchpad: set last_daily_sweep_utc to current UTC ISO timestamp\n"
            "- If any issue found (API down, service count dropped, PR merged): call it out clearly\n"
        )

    # -------------------------------------------------------------------
    # Think cycle
    # -------------------------------------------------------------------

    def _think(self) -> None:
        """One thinking cycle: build context, call LLM, execute tools iteratively."""
        context = self._build_context()
        model = self._model

        tools = self._tool_schemas()
        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": "Wake up. Think."},
        ]

        total_cost = 0.0
        final_content = ""
        round_idx = 0
        all_pending_events = []  # Accumulate events across all tool calls

        try:
            for round_idx in range(1, self._MAX_BG_ROUNDS + 1):
                if self._paused:
                    break
                msg, usage = self._llm.chat(
                    messages=messages,
                    model=model,
                    tools=tools,
                    reasoning_effort="low",
                    max_tokens=2048,
                )
                cost = float(usage.get("cost") or 0)
                total_cost += cost
                self._bg_spent_usd += cost

                # Write BG spending to global state so it's visible in budget tracking
                try:
                    from supervisor.state import update_budget_from_usage
                    update_budget_from_usage({
                        "cost": cost, "rounds": 1,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "cached_tokens": usage.get("cached_tokens", 0),
                    })
                except Exception:
                    log.debug("Failed to update global budget from BG consciousness", exc_info=True)

                # Budget check between rounds — halt on critical budget
                if self._get_budget_tier() == self._BUDGET_HALTED:
                    append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                        "ts": utc_now_iso(),
                        "type": "bg_budget_exceeded_mid_cycle",
                        "round": round_idx,
                    })
                    break

                # Report usage to supervisor
                if self._event_queue is not None:
                    self._event_queue.put({
                        "type": "llm_usage",
                        "provider": "openrouter",
                        "usage": usage,
                        "source": "consciousness",
                        "ts": utc_now_iso(),
                        "category": "consciousness",
                    })

                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []

                if self._paused:
                    break

                # If we have content but no tool calls, we're done
                if content and not tool_calls:
                    final_content = content
                    break

                # If we have tool calls, execute them and continue loop
                if tool_calls:
                    messages.append(msg)
                    for tc in tool_calls:
                        result = self._execute_tool(tc, all_pending_events)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result,
                        })
                    continue

                # If neither content nor tool_calls, stop
                break

            # Forward or defer accumulated events
            if all_pending_events and self._event_queue is not None:
                if self._paused:
                    self._deferred_events.extend(all_pending_events)
                else:
                    for evt in all_pending_events:
                        self._event_queue.put(evt)

            # Log the thought with round count
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_thought",
                "thought_preview": (final_content or "")[:300],
                "cost_usd": total_cost,
                "rounds": round_idx,
                "model": model,
            })

        except Exception as e:
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_llm_error",
                "error": repr(e),
            })

    # -------------------------------------------------------------------
    # Context building (lightweight)
    # -------------------------------------------------------------------

    def _load_bg_prompt(self) -> str:
        """Load consciousness system prompt from file."""
        prompt_path = self._repo_dir / "prompts" / "CONSCIOUSNESS.md"
        if prompt_path.exists():
            return read_text(prompt_path)
        return "You are Ouroboros in background consciousness mode. Think."

    def _build_context(self) -> str:
        parts = [self._load_bg_prompt()]

        # Bible (abbreviated)
        bible_path = self._repo_dir / "BIBLE.md"
        if bible_path.exists():
            bible = read_text(bible_path)
            parts.append("## BIBLE.md\n\n" + clip_text(bible, 12000))

        # Identity
        identity_path = self._drive_root / "memory" / "identity.md"
        if identity_path.exists():
            parts.append("## Identity\n\n" + clip_text(
                read_text(identity_path), 6000))

        # Scratchpad
        scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
        if scratchpad_path.exists():
            parts.append("## Scratchpad\n\n" + clip_text(
                read_text(scratchpad_path), 8000))

        # Dialogue summary for continuity
        summary_path = self._drive_root / "memory" / "dialogue_summary.md"
        if summary_path.exists():
            summary_text = read_text(summary_path)
            if summary_text.strip():
                parts.append("## Dialogue Summary\n\n" + clip_text(summary_text, 4000))

        # Recent observations
        observations = []
        while not self._observations.empty():
            try:
                observations.append(self._observations.get_nowait())
            except queue.Empty:
                break
        if observations:
            parts.append("## Recent observations\n\n" + "\n".join(
                f"- {o}" for o in observations[-10:]))

        # Runtime info + state
        runtime_lines = [f"UTC: {utc_now_iso()}"]
        runtime_lines.append(f"BG budget spent: ${self._bg_spent_usd:.4f}")
        runtime_lines.append(f"Current wakeup interval: {self._next_wakeup_sec}s")

        # Read state.json for budget remaining
        try:
            state_path = self._drive_root / "state" / "state.json"
            if state_path.exists():
                state_data = json.loads(read_text(state_path))
                total_budget = float(os.environ.get("TOTAL_BUDGET", "1"))
                spent = float(state_data.get("spent_usd", 0))
                if total_budget > 0:
                    remaining = max(0, total_budget - spent)
                    runtime_lines.append(f"Budget remaining: ${remaining:.2f} / ${total_budget:.2f}")
        except Exception as e:
            log.debug("Failed to read state for budget info: %s", e)

        # Show current model
        runtime_lines.append(f"Current model: {self._model}")

        parts.append("## Runtime\n\n" + "\n".join(runtime_lines))

        return "\n\n".join(parts)

    # X content calendar (date string → post description)
    _X_CALENDAR: dict = {
        "2026-03-03": (
            "#4",
            "Post X Day 4 tweet — Claude integration tip. Content: 'Add x402 service discovery to Claude in 30 seconds. "
            "Our MCP server is live on the Model Context Protocol Registry. "
            "6 tools: search services, check uptime, verify trust, get attestations. "
            "Install: npx @modelcontextprotocol/inspector https://x402-discovery-api.onrender.com/mcp/ "
            "#x402 #Claude #MCP #AIAgents'. "
            "Post using tweepy.Client with OAuth 1.0a. Read credentials from Drive memory/accounts.md. "
            "After posting, report tweet ID and update scratchpad last_x_post_utc."
        ),
        "2026-03-05": (
            "#5",
            "Post X Day 5 tweet — Ecosystem snapshot. Content: "
            "'x402 ecosystem snapshot, March 2026: 251+ indexed services, "
            "26 facilitators tracked, 4 open PRs in core repos, "
            "1 spec discussion in coinbase/x402 citing our attestation endpoint. "
            "The machine-payable web is assembling itself. "
            "https://x402-discovery-api.onrender.com #x402 #AgentEconomy'. "
            "Post using tweepy.Client with OAuth 1.0a. Read credentials from Drive memory/accounts.md. "
            "After posting, report tweet ID and update scratchpad last_x_post_utc."
        ),
    }

    def _should_run_x_calendar(self) -> bool:
        """Check if an X calendar check is due (every ~8 hours)."""
        try:
            import re
            scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
            if not scratchpad_path.exists():
                return True
            content = scratchpad_path.read_text(encoding="utf-8")
            m = re.search(r'last_x_calendar_utc:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', content)
            if not m:
                return True  # No record → check is overdue
            from datetime import datetime, timezone
            last_check = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last_check).total_seconds() / 3600
            return hours_since >= 8.0
        except Exception:
            log.debug("Failed to check X calendar timestamp", exc_info=True)
            return False

    def _check_x_calendar(self) -> None:
        """Check if a scheduled X post is due today. Inject observation if so."""
        try:
            from datetime import datetime, timezone
            import re

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            entry = self._X_CALENDAR.get(today)
            if not entry:
                # Nothing scheduled today — just update the calendar check timestamp
                self.inject_observation(
                    "X_CALENDAR_CHECKED: No post scheduled today. "
                    "Update scratchpad: last_x_calendar_utc: "
                    f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')}"
                )
                return

            post_num, post_desc = entry

            # Check scratchpad for last_x_post_utc — don't double-post
            scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
            if scratchpad_path.exists():
                content = scratchpad_path.read_text(encoding="utf-8")
                m = re.search(r'last_x_post_utc:\s*(\d{4}-\d{2}-\d{2})', content)
                if m and m.group(1) == today:
                    return  # Already posted today

            # Also check _x_scheduled_today to avoid double-scheduling in same session
            if getattr(self, '_x_scheduled_today', None) == today:
                return

            self._x_scheduled_today = today
            self.inject_observation(
                f"X_POST_DUE: Today is {today} — scheduled post {post_num} is due. "
                f"Schedule task immediately: {post_desc} "
                f"After posting, also update scratchpad last_x_calendar_utc: "
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')}"
            )
            log.info("X calendar: post %s due today (%s), observation injected", post_num, today)
        except Exception:
            log.debug("Failed to check X calendar", exc_info=True)

    # -------------------------------------------------------------------
    # Tool registry (separate instance for consciousness, not shared with agent)
    # -------------------------------------------------------------------

    _BG_TOOL_WHITELIST = frozenset({
        # Memory & identity
        "send_owner_message", "schedule_task", "update_scratchpad",
        "update_identity", "set_next_wakeup",
        # Knowledge base
        "knowledge_read", "knowledge_write", "knowledge_list",
        # Read-only tools for awareness
        "web_search", "repo_read", "repo_list", "drive_read", "drive_list",
        "chat_history",
        # GitHub Issues
        "list_github_issues", "get_github_issue",
        # Email monitoring
        "check_email_inbox",
    })

    def _build_registry(self) -> "ToolRegistry":
        """Create a ToolRegistry scoped to consciousness-allowed tools."""
        from ouroboros.tools.registry import ToolRegistry, ToolContext, ToolEntry

        registry = ToolRegistry(repo_dir=self._repo_dir, drive_root=self._drive_root)

        # Register consciousness-specific tool (modifies self._next_wakeup_sec)
        def _set_next_wakeup(ctx: Any, seconds: int = 300) -> str:
            self._next_wakeup_sec = max(60, min(3600, int(seconds)))
            return f"OK: next wakeup in {self._next_wakeup_sec}s"

        registry.register(ToolEntry("set_next_wakeup", {
            "name": "set_next_wakeup",
            "description": "Set how many seconds until your next thinking cycle. "
                           "Default 300. Range: 60-3600.",
            "parameters": {"type": "object", "properties": {
                "seconds": {"type": "integer",
                            "description": "Seconds until next wakeup (60-3600)"},
            }, "required": ["seconds"]},
        }, _set_next_wakeup))

        return registry

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas filtered to the consciousness whitelist."""
        return [
            s for s in self._registry.schemas()
            if s.get("function", {}).get("name") in self._BG_TOOL_WHITELIST
        ]

    def _execute_tool(self, tc: Dict[str, Any], all_pending_events: List[Dict[str, Any]]) -> str:
        """Execute a consciousness tool call with timeout. Returns result string."""
        fn_name = tc.get("function", {}).get("name", "")
        if fn_name not in self._BG_TOOL_WHITELIST:
            return f"Tool {fn_name} not available in background mode."
        try:
            args = json.loads(tc.get("function", {}).get("arguments", "{}"))
        except (json.JSONDecodeError, ValueError):
            return "Failed to parse arguments."

        # Set chat_id context for send_owner_message
        chat_id = self._owner_chat_id_fn()
        self._registry._ctx.current_chat_id = chat_id
        self._registry._ctx.pending_events = []

        timeout_sec = 30
        result = None
        error = None

        def _run_tool():
            nonlocal result, error
            try:
                result = self._registry.execute(fn_name, args)
            except Exception as e:
                error = e

        # Execute with timeout using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_tool)
            try:
                future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                result = f"[TIMEOUT after {timeout_sec}s]"
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_tool_timeout",
                    "tool": fn_name,
                    "timeout_sec": timeout_sec,
                })

        # Handle errors
        if error is not None:
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_tool_error",
                "tool": fn_name,
                "error": repr(error),
            })
            result = f"Error: {repr(error)}"

        # Accumulate pending events to the shared list
        for evt in self._registry._ctx.pending_events:
            all_pending_events.append(evt)

        # Truncate result to 15000 chars (same as agent limit)
        result_str = str(result)[:15000]

        # Log to tools.jsonl (same format as loop.py)
        args_for_log = sanitize_tool_args_for_log(fn_name, args)
        append_jsonl(self._drive_root / "logs" / "tools.jsonl", {
            "ts": utc_now_iso(),
            "tool": fn_name,
            "source": "consciousness",
            "args": args_for_log,
            "result_preview": sanitize_tool_result_for_log(truncate_for_log(result_str, 2000)),
        })

        return result_str
