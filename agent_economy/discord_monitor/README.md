# x402 Discord Monitor (Selfbot)

Monitors Base and CDP Discord servers for x402-related discussions and forwards alerts to Telegram instantly.

This is a **selfbot** — it runs as your Discord user account (`x402scout`), not a bot application. Because it connects as a real user, it can read messages in any server that account is already a member of — no need to get bot approval from server admins.

## What it does

- Connects to Discord as the `x402scout` user account
- Watches **all channels** in Base Discord, CDP Discord, and any other servers the account is in
- Monitors for 13 x402 keywords: `x402`, `micropayment`, `facilitator`, `scoutgate`, etc.
- Forwards matches to **Telegram** in real-time (< 3 seconds)
- Optionally mirrors alerts to webhooks in your own Discord server (#base-alerts, #cdp-alerts)
- 5-minute cooldown per user/channel to prevent alert flood

## Why this matters

When someone asks "how do I discover x402 services?" in Base Discord, you see it in Telegram within seconds — and can jump in with a relevant answer. This is the difference between responding in minutes vs. days.

## Setup

### Step 1 — Get your Discord user token

You need the account token for the `x402scout` Discord account.

**From browser DevTools:**
1. Open Discord in your browser (discord.com/app) — **log in as x402scout**
2. Open DevTools → Network tab
3. Refresh the page and look for any request to `discord.com/api/`
4. In the request headers, find `Authorization:` — the value is your user token
5. It starts with something like `MTM...` (not `Bot ...`)

**Important:** Keep this token secret — it grants full access to the account.

### Step 2 — Create alert webhooks in your own Discord server (optional)

If you want alerts mirrored to a Discord server you control:

1. In your Discord server, create two channels: `#base-alerts` and `#cdp-alerts`
2. For each channel: **Edit Channel → Integrations → Webhooks → New Webhook → Copy URL**
3. Set `DISCORD_WEBHOOK_BASE_ALERTS` and `DISCORD_WEBHOOK_CDP_ALERTS` to those URLs

This step is optional — Telegram alerts work without it.

### Step 3 — Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_USER_TOKEN` | ✅ | User account token for x402scout (NOT a bot token) |
| `TELEGRAM_BOT_TOKEN` | ✅ | Ouroboros Telegram bot token |
| `TELEGRAM_OWNER_ID` | ✅ | Your Telegram user ID (numeric) |
| `DISCORD_WEBHOOK_BASE_ALERTS` | Optional | Webhook URL for #base-alerts in your own server |
| `DISCORD_WEBHOOK_CDP_ALERTS` | Optional | Webhook URL for #cdp-alerts in your own server |

The Telegram vars are already set from the main Ouroboros config.

### Step 4 — Deploy on Render

Add as a new **Worker** service (Starter plan):

| Setting | Value |
|---------|-------|
| **Repository** | `rplryan/ouroboros` |
| **Branch** | `ouroboros` |
| **Build Command** | `pip install -r agent_economy/discord_monitor/requirements.txt` |
| **Start Command** | `python discord_monitor_main.py` |
| **Instance Type** | Starter |

Add the env vars above in the Render dashboard. No port needed — this is a background worker.

## Keywords monitored

```
x402, x-402, micropayment, agent payment, http 402, 402 payment,
facilitator, scoutgate, x402scout, payment required,
agentkit payment, stablecoin api, coinbase x402
```

## Alert format (Telegram)

```
👁 x402 mention in Base #build-in-public
🏷️ Keywords: x402, micropayment

👤 someuser:
"Has anyone tried using x402 for micropayments with AgentKit? Looking for a service discovery layer..."

🔗 Jump to message
```

## Testing locally

```bash
export DISCORD_USER_TOKEN=your_user_token
export TELEGRAM_BOT_TOKEN=your_tg_token
export TELEGRAM_OWNER_ID=your_numeric_id

cd /root/Ouroboros
python discord_monitor_main.py
```

Once running, send a message containing "x402" in any server the x402scout account is in. You'll get a Telegram alert within 2-3 seconds.

## Note on selfbots

Running a selfbot technically violates Discord's Terms of Service. This monitor is read-only and passive — it never sends messages, reacts, or interacts on behalf of the account. The account is used solely as a listening post for your own keyword alerting. Use at your own discretion.
