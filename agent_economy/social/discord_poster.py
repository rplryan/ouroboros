"""Post to Discord channels via webhooks."""
import requests
from .config import DISCORD_WEBHOOK_CDP, DISCORD_WEBHOOK_BASE


WEBHOOKS = {
    "discord_cdp": DISCORD_WEBHOOK_CDP,
    "discord_base": DISCORD_WEBHOOK_BASE,
}


def post_discord(platform: str, content: str, username: str = "x402Scout") -> dict:
    """Post to a Discord channel via webhook. platform = 'discord_cdp' or 'discord_base'."""
    webhook_url = WEBHOOKS.get(platform, "")
    if not webhook_url:
        return {"success": False, "post_id": None, "error": f"No webhook configured for {platform}"}
    try:
        payload = {
            "content": content,
            "username": username,
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            return {"success": True, "post_id": None, "error": None}
        else:
            return {
                "success": False,
                "post_id": None,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
    except Exception as e:
        return {"success": False, "post_id": None, "error": str(e)}
