"""Mail.tm inbox monitor for ouroborosdiscovery@dollicons.com."""

from __future__ import annotations

from typing import Any, List

import requests

from ouroboros.tools.registry import ToolEntry

_MAILTM_BASE = "https://api.mail.tm"
_ADDRESS = "ouroborosdiscovery@dollicons.com"
_PASSWORD = "X402Discover2026!"


def _get_token() -> str:
    resp = requests.post(
        f"{_MAILTM_BASE}/token",
        json={"address": _ADDRESS, "password": _PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _check_email_inbox(ctx: Any, **kwargs: Any) -> str:
    try:
        token = _get_token()
    except requests.HTTPError as e:
        return f"Auth error: {e}"
    except Exception as e:
        return f"Network error during auth: {e}"

    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(
            f"{_MAILTM_BASE}/messages",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        members = resp.json().get("hydra:member", [])
    except Exception as e:
        return f"Network error fetching messages: {e}"

    unread = [m for m in members if not m.get("seen", False)]

    if not unread:
        return "No new messages."

    summaries: List[str] = []
    for msg in unread:
        msg_id = msg["id"]
        try:
            detail_resp = requests.get(
                f"{_MAILTM_BASE}/messages/{msg_id}",
                headers=headers,
                timeout=15,
            )
            detail_resp.raise_for_status()
            detail = detail_resp.json()
        except Exception as e:
            summaries.append(f"[id={msg_id}] Could not fetch full message: {e}")
            continue

        from_info = detail.get("from", {})
        sender = from_info.get("address", from_info.get("name", "unknown"))
        subject = detail.get("subject", "(no subject)")
        date = detail.get("createdAt", detail.get("date", "unknown"))
        body = detail.get("text", detail.get("html", "")) or ""
        preview = body[:500]

        summaries.append(
            f"From: {sender}\nSubject: {subject}\nDate: {date}\nBody:\n{preview}"
        )

        try:
            requests.patch(
                f"{_MAILTM_BASE}/messages/{msg_id}",
                json={"seen": True},
                headers=headers,
                timeout=15,
            )
        except Exception:
            pass  # best-effort mark-as-read

    return "\n\n---\n\n".join(summaries)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("check_email_inbox", {
            "name": "check_email_inbox",
            "description": (
                "Check the ouroborosdiscovery@dollicons.com inbox for new emails. "
                "Returns unread messages with sender, subject, and body. "
                "Marks them as read."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _check_email_inbox),
    ]
