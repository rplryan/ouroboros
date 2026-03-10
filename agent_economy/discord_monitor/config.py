"""Discord monitor configuration."""
import os

# Discord bot token (from Discord Developer Portal)
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

# Telegram alerting
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_OWNER_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))

# Optional: your own Discord server webhook (to forward alerts there too)
DISCORD_ALERT_WEBHOOK = os.environ.get("DISCORD_ALERT_WEBHOOK", "")

# Keywords to monitor (case-insensitive)
MONITOR_KEYWORDS = [
    "x402",
    "x-402",
    "micropayment",
    "agent payment",
    "http 402",
    "402 payment",
    "facilitator",
    "scoutgate",
    "x402scout",
    "payment required",
    "agentkit payment",
    "stablecoin api",
    "coinbase x402",
]

# Server/channel filter — monitor ALL channels in these servers
# Set to empty list to monitor ALL servers the bot is in
MONITOR_SERVER_NAMES = [
    "Base",
    "CDP",
    "Coinbase Developer Platform",
    "x402",
]

# Minimum message length to forward (avoid single-word noise)
MIN_MESSAGE_LENGTH = 20

# Cooldown per (server, channel, author) in seconds — avoid flooding same conversation
ALERT_COOLDOWN_SECONDS = 300  # 5 minutes
