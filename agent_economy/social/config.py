"""Social media configuration — credentials loaded from environment variables."""
import os

# X (Twitter) — OAuth 1.0a
X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_SECRET = os.environ.get("X_CONSUMER_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

# Discord webhooks — loaded from env
DISCORD_WEBHOOK_CDP = os.environ.get("DISCORD_WEBHOOK_CDP", "")
DISCORD_WEBHOOK_BASE = os.environ.get("DISCORD_WEBHOOK_BASE", "")

# Platform feature flags
X_ENABLED = bool(X_CONSUMER_KEY and X_ACCESS_TOKEN)
DISCORD_ENABLED = bool(DISCORD_WEBHOOK_CDP or DISCORD_WEBHOOK_BASE)

# State file path (persistent, on Drive)
STATE_FILE = os.environ.get("SOCIAL_STATE_FILE", "/root/Ouroboros/data/memory/social_state.json")

# Rate limits (conservative, well below X's 1500/month free tier)
X_MAX_POSTS_PER_DAY = 3
X_MAX_POSTS_PER_WEEK = 15
DISCORD_MAX_POSTS_PER_DAY = 2

# Content pillars (from strategy doc)
PILLARS = [
    "build_in_public",      # Revenue & metrics transparency
    "ecosystem_intel",      # Maps, gaps, data
    "tutorials",            # How to build with Scout
    "agent_economy_vision", # Big-picture narrative
    "hot_takes",            # Contrarian/competitive intel
]
