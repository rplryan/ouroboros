# x402Scout Social Media Manager

Automated social media management for the x402Scout ecosystem. Posts to X (Twitter) and Discord on a schedule, with a 30-day content library aligned to the `scout_social_strategy.docx` playbook.

## Architecture

```
agent_economy/social/
├── __init__.py           # Package root
├── config.py             # Credentials from env vars
├── content_library.py    # 30+ pre-written posts (5 pillars)
├── state.py              # Persistent queue + history (Drive JSON)
├── scheduler.py          # Queue builder, due-post runner
├── x_poster.py           # Tweepy OAuth 1.0a → X API v2
├── discord_poster.py     # Webhook → Discord channels
└── README.md             # This file
```

### Content Pillars

| ID | Pillar | Cadence | Description |
|----|--------|---------|-------------|
| `bip` | Build in Public | 3×/week | Metrics, milestones, ScoutGate updates |
| `edu` | Education | 2×/week | How x402 works, tutorials |
| `social_proof` | Social Proof | 1×/week | Catalog growth, ecosystem signals |
| `engagement` | Engagement | 2×/week | Questions, polls, community threads |
| `product` | Product Update | 1×/week | New features, ScoutGate, RouteNet |

## Setup

### 1. Add Colab Secrets

Add these secrets in your Colab notebook (key icon in sidebar):

| Secret | Where to get it |
|--------|----------------|
| `X_CONSUMER_KEY` | developer.twitter.com → App → Keys & Tokens |
| `X_CONSUMER_SECRET` | developer.twitter.com → App → Keys & Tokens |
| `X_ACCESS_TOKEN` | developer.twitter.com → App → Keys & Tokens |
| `X_ACCESS_TOKEN_SECRET` | developer.twitter.com → App → Keys & Tokens |
| `DISCORD_WEBHOOK_CDP` | CDP Discord → Channel Settings → Integrations → Webhooks |
| `DISCORD_WEBHOOK_BASE` | Base Discord → Channel Settings → Integrations → Webhooks |
| `DISCORD_WEBHOOK_X402` | x402 Discord → Channel Settings → Integrations → Webhooks |

### 2. X API App Setup

- App needs **Read and Write** permissions
- Generate OAuth 1.0a tokens after enabling write access
- Free tier: 1,500 posts/month (sufficient for 2 posts/day)

### 3. Discord Webhooks

For each Discord server you want to post to:
1. Go to the channel → Edit Channel → Integrations → Webhooks → New Webhook
2. Copy the webhook URL
3. Add to Colab secrets

## Usage via Telegram

Once running, control via Telegram:

```
/social status                     — Queue size, next scheduled post, stats
/social queue_week                 — Queue 7 days of posts (auto-selected)
/social post_now [content_id]      — Post immediately (or next queued)
/social run_due                    — Execute all posts due right now
/social add_post [content] [x|discord|both] — Add custom one-off post
/social list_library               — List all content library posts
```

## Autonomous Operation

The social manager runs automatically via background consciousness:
- Checks for due posts every 2 hours
- Auto-queues the next week's posts when queue runs low
- Posts without manual intervention

## Content Library

30+ pre-written posts covering all 5 pillars. Posts are selected in a
round-robin fashion across pillars to maintain variety. Each post is
marked with platform preference (x, discord, or both).

To add posts, edit `content_library.py` — follow the existing format.

## State Persistence

State (queue + history) is stored at:
- Runtime: `/data/social_state.json` (Render disk)
- Fallback: `data/social_state.json` (Drive root)

History is retained for 90 days for analytics.
