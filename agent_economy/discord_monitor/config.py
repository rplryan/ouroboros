"""Discord monitor configuration."""
import os

# Discord user account token (NOT a bot token — selfbot)
DISCORD_USER_TOKEN = os.environ.get("DISCORD_USER_TOKEN", "")

# Telegram alerting
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_OWNER_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))

# Optional: webhooks in YOUR OWN Discord server to mirror alerts
DISCORD_WEBHOOK_BASE_ALERTS = os.environ.get("DISCORD_WEBHOOK_BASE_ALERTS", "")
DISCORD_WEBHOOK_CDP_ALERTS = os.environ.get("DISCORD_WEBHOOK_CDP_ALERTS", "")

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
# Set to empty list to monitor ALL servers the account is in
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
