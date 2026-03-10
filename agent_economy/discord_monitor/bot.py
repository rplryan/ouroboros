"""Discord keyword monitor bot for x402Scout."""
import asyncio
import logging
import time
from datetime import datetime, timezone

import aiohttp
import discord

from .config import (
    DISCORD_BOT_TOKEN,
    DISCORD_ALERT_WEBHOOK,
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
            else:
                body = await resp.text()
                log.error(f"Telegram API error {resp.status}: {body[:200]}")
                return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


async def send_discord_alert(session: aiohttp.ClientSession, text: str) -> bool:
    """Send to our own Discord alert webhook (optional)."""
    if not DISCORD_ALERT_WEBHOOK:
        return False
    try:
        async with session.post(
            DISCORD_ALERT_WEBHOOK,
            json={"content": text, "username": "x402 Monitor"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        log.error(f"Discord webhook send failed: {e}")
        return False


class MonitorBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
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
        log.info(f"Bot ready. Logged in as {self.user}. Guilds: {guilds}")
        monitored = [g for g in guilds if _should_monitor_server(g)]
        log.info(f"Monitoring {len(monitored)} servers: {monitored}")
        # Send startup notification to Telegram
        if self._session:
            await send_telegram_alert(
                self._session,
                f"🤖 <b>x402 Discord Monitor online</b>\n"
                f"Watching: {', '.join(monitored) if monitored else 'all servers'}\n"
                f"Keywords: {len(MONITOR_KEYWORDS)} patterns",
            )

    async def on_message(self, message: discord.Message):
        # Ignore DMs and messages from bots (including self)
        if not message.guild or message.author.bot:
            return

        # Health check command
        if message.content.strip() == "!ping":
            await message.channel.send("pong — x402 monitor active ✓")
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

        # Telegram alert
        tg_text = (
            f"🔍 <b>x402 mention</b> in <b>{server_name}</b> #{channel_name}\n"
            f"🏷️ Keywords: <code>{keywords_str}</code>\n\n"
            f"👤 <b>{author}</b>:\n"
            f"<i>{content_preview}</i>\n\n"
            f"🔗 <a href='{jump_url}'>Jump to message</a>"
        )

        # Discord webhook alert
        dc_text = (
            f"**🔍 x402 mention in {server_name} #{channel_name}**\n"
            f"Keywords: `{keywords_str}`\n"
            f"> {content_preview}\n"
            f"— {author} | [Jump]({jump_url})"
        )

        assert self._session is not None
        await asyncio.gather(
            send_telegram_alert(self._session, tg_text),
            send_discord_alert(self._session, dc_text),
        )

    async def on_error(self, event, *args, **kwargs):
        log.exception(f"Error in event {event}")


def run():
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN not set — cannot start bot")
    bot = MonitorBot()
    bot.run(DISCORD_BOT_TOKEN, log_handler=None)  # We handle logging ourselves


if __name__ == "__main__":
    run()
