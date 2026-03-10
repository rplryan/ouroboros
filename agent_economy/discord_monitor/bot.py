"""Discord keyword monitor selfbot for x402Scout.

Runs as the x402scout USER account (not a bot application) using discord.py-self.
The account must already be a member of the servers you want to monitor.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import aiohttp
import discord  # from discord.py-self package

from .config import (
    DISCORD_USER_TOKEN,
    DISCORD_WEBHOOK_BASE_ALERTS,
    DISCORD_WEBHOOK_CDP_ALERTS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    MONITOR_KEYWORDS,
    MONITOR_SERVER_NAMES,
    MIN_MESSAGE_LENGTH,
    ALERT_COOLDOWN_SECONDS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("discord_monitor")

# Cooldown tracker: key = f"{guild_id}:{channel_id}:{author_id}" -> last alert timestamp
_cooldowns: dict[str, float] = {}


def _matches_keywords(content: str) -> list[str]:
    """Return list of matched keywords (empty if none)."""
    lower = content.lower()
    return [kw for kw in MONITOR_KEYWORDS if kw.lower() in lower]


def _should_monitor_server(guild_name: str) -> bool:
    """Check if this server should be monitored."""
    if not MONITOR_SERVER_NAMES:
        return True  # Monitor all servers
    lower = guild_name.lower()
    return any(name.lower() in lower for name in MONITOR_SERVER_NAMES)


def _get_webhook_for_server(guild_name: str) -> str:
    """Return the appropriate webhook URL based on server name, or empty string."""
    lower = guild_name.lower()
    if "base" in lower and DISCORD_WEBHOOK_BASE_ALERTS:
        return DISCORD_WEBHOOK_BASE_ALERTS
    if "cdp" in lower and DISCORD_WEBHOOK_CDP_ALERTS:
        return DISCORD_WEBHOOK_CDP_ALERTS
    if "coinbase developer platform" in lower and DISCORD_WEBHOOK_CDP_ALERTS:
        return DISCORD_WEBHOOK_CDP_ALERTS
    return ""


def _check_cooldown(guild_id: int, channel_id: int, author_id: int) -> bool:
    """Return True if we should send alert (not in cooldown)."""
    key = f"{guild_id}:{channel_id}:{author_id}"
    last = _cooldowns.get(key, 0)
    if time.time() - last >= ALERT_COOLDOWN_SECONDS:
        _cooldowns[key] = time.time()
        return True
    return False


async def send_telegram_alert(session: aiohttp.ClientSession, text: str) -> bool:
    """Send a message to Telegram via bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return True
            body = await resp.text()
            log.error(f"Telegram API error {resp.status}: {body[:200]}")
            return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


async def send_webhook_alert(session: aiohttp.ClientSession, webhook_url: str, text: str) -> bool:
    """Forward alert to a Discord webhook in our own server."""
    if not webhook_url:
        return False
    try:
        async with session.post(
            webhook_url,
            json={"content": text, "username": "x402 Monitor"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        log.error(f"Discord webhook send failed: {e}")
        return False


class MonitorClient(discord.Client):
    """Selfbot client — connects as a Discord user account."""

    def __init__(self):
        # User accounts don't need special intents for message content
        super().__init__()
        self._session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        self._session = aiohttp.ClientSession()
        log.info("aiohttp session created")

    async def close(self):
        if self._session:
            await self._session.close()
        await super().close()

    async def on_ready(self):
        guilds = [g.name for g in self.guilds]
        log.info(f"Selfbot ready. Logged in as {self.user}. Guilds: {guilds}")
        monitored = [g for g in guilds if _should_monitor_server(g)]
        log.info(f"Monitoring {len(monitored)} servers: {monitored}")
        if self._session:
            await send_telegram_alert(
                self._session,
                f"👁 <b>x402 Discord Monitor online</b>\n"
                f"Watching: {', '.join(monitored) if monitored else 'all servers'}\n"
                f"Keywords: {len(MONITOR_KEYWORDS)} patterns",
            )

    async def on_message(self, message: discord.Message):
        # Only monitor guild messages; skip our own messages
        if not message.guild or message.author.id == self.user.id:
            return

        # Server filter
        if not _should_monitor_server(message.guild.name):
            return

        # Length filter
        if len(message.content) < MIN_MESSAGE_LENGTH:
            return

        # Keyword check
        matched = _matches_keywords(message.content)
        if not matched:
            return

        # Cooldown check
        if not _check_cooldown(message.guild.id, message.channel.id, message.author.id):
            log.debug(f"Cooldown active for {message.author} in {message.guild.name}#{message.channel.name}")
            return

        # Build alert
        server_name = message.guild.name
        channel_name = getattr(message.channel, "name", "unknown")
        author = str(message.author)
        content_preview = message.content[:500]
        jump_url = message.jump_url
        keywords_str = ", ".join(matched[:3])
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

        log.info(f"MATCH [{ts}] {server_name}#{channel_name} @{author} | keywords: {keywords_str}")

        tg_text = (
            f"🔍 <b>x402 mention</b> in <b>{server_name}</b> #{channel_name}\n"
            f"🏷️ Keywords: <code>{keywords_str}</code>\n\n"
            f"👤 <b>{author}</b>:\n"
            f"<i>{content_preview}</i>\n\n"
            f"🔗 <a href='{jump_url}'>Jump to message</a>"
        )

        dc_text = (
            f"**🔍 x402 mention in {server_name} #{channel_name}**\n"
            f"Keywords: `{keywords_str}`\n"
            f"> {content_preview}\n"
            f"— {author} | [Jump]({jump_url})"
        )

        webhook_url = _get_webhook_for_server(server_name)

        assert self._session is not None
        tasks = [send_telegram_alert(self._session, tg_text)]
        if webhook_url:
            tasks.append(send_webhook_alert(self._session, webhook_url, dc_text))
        await asyncio.gather(*tasks)

    async def on_error(self, event, *args, **kwargs):
        log.exception(f"Error in event {event}")


def run():
    if not DISCORD_USER_TOKEN:
        raise RuntimeError("DISCORD_USER_TOKEN not set — cannot start selfbot")
    client = MonitorClient()
    # bot=False tells discord.py-self this is a user token, not a bot token
    client.run(DISCORD_USER_TOKEN, bot=False, log_handler=None)


if __name__ == "__main__":
    run()
