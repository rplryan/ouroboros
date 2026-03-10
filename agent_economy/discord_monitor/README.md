# x402 Discord Monitor

Monitors Base and CDP Discord servers for x402-related discussions and forwards alerts to Telegram instantly.

## What it does

- Joins Discord servers (Base, CDP, x402 communities)
- Watches **all channels** for 13 x402 keywords: `x402`, `micropayment`, `facilitator`, `scoutgate`, etc.
- Forwards matches to **Telegram** in real-time (< 3 seconds)
- Optional: forwards to your own Discord webhook too
- 5-minute cooldown per user/channel to prevent alert flood
- `!ping` health check command in any monitored channel

## Why this matters

When someone asks "how do I discover x402 services?" in Base Discord, you see it in Telegram within seconds — and can jump in with a relevant answer. This is the difference between responding in minutes vs. days.

## Setup

### Step 1 — Create the Discord bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → name it **"x402Scout Monitor"**
3. Go to **Bot** tab → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable:
   - ✅ **Message Content Intent** ← required to read message text
5. Copy the **Bot Token** → this is your `DISCORD_BOT_TOKEN`
6. Note your **Application ID** (Client ID) from the General Information tab

### Step 2 — Invite the bot to servers

Use this URL (replace `YOUR_CLIENT_ID`):
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=68608&scope=bot
```

**Permissions requested (68608):**
- Read Messages / View Channels
- Read Message History  
- Send Messages (for `!ping` health check)

**You can only invite bots to servers where you have "Manage Server" permission.**

For Base and CDP Discord — you need to request bot access:
- **Base Discord:** Create a support ticket in `#builder-support` or post in `#build-in-public` explaining you want to run a keyword monitor for the x402Scout project
- **CDP Discord:** Use their developer support channel or submit via their ecosystem form

In the meantime: create your own test server, invite the bot, and verify it's working before requesting access to Base/CDP.

### Step 3 — Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | ✅ | Bot token from Discord Developer Portal |
| `TELEGRAM_BOT_TOKEN` | ✅ | Ouroboros Telegram bot token |
| `TELEGRAM_OWNER_ID` | ✅ | Your Telegram user ID (numeric) |
| `DISCORD_ALERT_WEBHOOK` | Optional | Your own Discord channel webhook for mirrored alerts |

Add to `/root/Ouroboros/.env`:
```
DISCORD_BOT_TOKEN=your_token_here
```

The Telegram vars are already set from the main Ouroboros config.

### Step 4 — Deploy on Render

Add as a new **Background Worker** service:

| Setting | Value |
|---------|-------|
| **Repository** | `rplryan/ouroboros` |
| **Branch** | `ouroboros` |
| **Build Command** | `pip install -r agent_economy/discord_monitor/requirements.txt` |
| **Start Command** | `python discord_monitor_main.py` |
| **Instance Type** | Free (background workers are fine on free tier) |

Add the env vars above in the Render dashboard.

No port needed — this is a background worker, not a web service.

## Keywords monitored

```
x402, x-402, micropayment, agent payment, http 402, 402 payment,
facilitator, scoutgate, x402scout, payment required,
agentkit payment, stablecoin api, coinbase x402
```

## Alert format (Telegram)

```
🔍 x402 mention in Base #build-in-public
🏷️ Keywords: x402, micropayment

👤 someuser#1234:
"Has anyone tried using x402 for micropayments with AgentKit? Looking for a service discovery layer..."

🔗 Jump to message
```

## Testing locally

```bash
export DISCORD_BOT_TOKEN=your_token
export TELEGRAM_BOT_TOKEN=your_tg_token
export TELEGRAM_OWNER_ID=your_numeric_id

cd /root/Ouroboros
python discord_monitor_main.py
```

Once running, send a message containing "x402" in any server the bot has joined. You'll get a Telegram alert within 2-3 seconds.
