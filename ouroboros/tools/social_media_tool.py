"""
Social media management tool for Ouroboros.

Allows posting to X and Discord from Telegram commands.
Usage examples from Telegram:
  /social status
  /social post x
  /social post discord_cdp  
  /social dry-run x
  /social queue-week
  /social run-due
"""
import json
import sys
import os

# Ensure agent_economy is importable
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _get_scheduler():
    from agent_economy.social import scheduler
    return scheduler


def social_status() -> str:
    """Get social media posting status and queue."""
    sched = _get_scheduler()
    status = sched.get_status()
    stats = status["stats"]
    
    lines = [
        "📊 **Social Media Status**",
        "",
        f"**Credentials:**",
        f"  X (Twitter): {'✅ enabled' if status['x_enabled'] else '❌ not configured'}",
        f"  Discord: {'✅ enabled' if status['discord_enabled'] else '❌ not configured'}",
        "",
        f"**Activity:**",
        f"  X posts today: {stats['x_posts_today']} / 3",
        f"  X posts this week: {stats['x_posts_this_week']} / 15",
        f"  Discord posts today: {stats['discord_posts_today']} / 2",
        f"  Total posts: {stats.get('total_x_posts', 0) + stats.get('total_discord_posts', 0)}",
        "",
        f"**Queue:** {status['queue_pending']} pending",
        f"**Content library:** {status['content_library_size']} posts",
    ]
    
    if status["recent_posts"]:
        lines.append("")
        lines.append("**Recent posts:**")
        for p in status["recent_posts"][-3:]:
            ts = p.get("posted_at", "")[:16]
            platform = p.get("platform", "?")
            pillar = p.get("pillar", "?")
            lines.append(f"  [{platform}] {ts} ({pillar})")
    
    return "\n".join(lines)


def social_post(platform: str, dry_run: bool = False) -> str:
    """Post next content to a platform. Returns result summary."""
    sched = _get_scheduler()
    result = sched.post_now(platform, dry_run=dry_run)
    
    if dry_run:
        if result.get("success"):
            content = result.get("content", "")
            char_count = result.get("char_count", len(content))
            content_id = result.get("id", "?")
            pillar = result.get("pillar", "?")
            return (
                f"🔍 **Dry run — would post to {platform}:**\n"
                f"Content ID: `{content_id}` ({pillar})\n"
                f"Chars: {char_count}\n\n"
                f"```\n{content[:500]}\n```"
            )
        else:
            return f"❌ Dry run failed: {result.get('error', 'unknown error')}"
    
    if result.get("success"):
        post_id = result.get("post_id", "")
        content_id = result.get("content_id", "?")
        pillar = result.get("pillar", "?")
        post_id_str = f"\nPost ID: `{post_id}`" if post_id else ""
        return f"✅ **Posted to {platform}!**{post_id_str}\nContent: `{content_id}` ({pillar})"
    else:
        return f"❌ Post failed: {result.get('error', 'unknown error')}"


def social_queue_week() -> str:
    """Queue a week of posts across all platforms."""
    sched = _get_scheduler()
    queued = sched.queue_week_of_posts()
    
    if not queued:
        return "⚠️ No posts queued (all content may already be scheduled or limits reached)"
    
    lines = [f"📅 **Queued {len(queued)} posts for next 7 days:**"]
    for q in queued:
        platform = q["platform"]
        scheduled_for = q["scheduled_for"]
        content_id = q["content_id"]
        pillar = q["pillar"]
        lines.append(f"  `[{platform}]` {scheduled_for} — `{content_id}` ({pillar})")
    
    return "\n".join(lines)


def social_run_due() -> str:
    """Run all due queue items."""
    sched = _get_scheduler()
    results = sched.run_due_posts()
    
    if not results:
        return "📭 No posts due right now."
    
    posted = [r for r in results if r.get("status") == "posted"]
    failed = [r for r in results if r.get("status") == "failed"]
    skipped = [r for r in results if r.get("status", "").startswith("skipped")]
    
    lines = [f"**Processed {len(results)} due posts:**"]
    lines.append(f"  ✅ Posted: {len(posted)}")
    lines.append(f"  ❌ Failed: {len(failed)}")
    lines.append(f"  ⏭️ Skipped: {len(skipped)}")
    
    for r in failed:
        lines.append(f"\n  Error [{r['platform']}]: {r.get('error', 'unknown')}")
    
    return "\n".join(lines)


def get_tools() -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": "social_media",
                "description": (
                    "Manage x402Scout social media posting. "
                    "Post to X (Twitter) or Discord (CDP/Base channels), "
                    "check status, queue a week of posts, or run due posts. "
                    "Credentials must be set as env vars: X_CONSUMER_KEY, X_CONSUMER_SECRET, "
                    "X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, DISCORD_WEBHOOK_CDP, DISCORD_WEBHOOK_BASE."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["status", "post", "dry_run", "queue_week", "run_due"],
                            "description": (
                                "status: show stats and queue. "
                                "post: post next content to platform. "
                                "dry_run: show what would be posted without posting. "
                                "queue_week: queue a week of posts. "
                                "run_due: execute all scheduled posts that are due now."
                            ),
                        },
                        "platform": {
                            "type": "string",
                            "enum": ["x", "discord_cdp", "discord_base"],
                            "description": "Required for 'post' and 'dry_run' actions.",
                        },
                    },
                    "required": ["action"],
                },
            },
        }
    ]


def social_media(action: str, platform: str = None) -> str:
    """Main entry point for social media tool."""
    if action == "status":
        return social_status()
    elif action == "post":
        if not platform:
            return "❌ 'post' action requires a platform (x, discord_cdp, discord_base)"
        return social_post(platform, dry_run=False)
    elif action == "dry_run":
        if not platform:
            return "❌ 'dry_run' action requires a platform"
        return social_post(platform, dry_run=True)
    elif action == "queue_week":
        return social_queue_week()
    elif action == "run_due":
        return social_run_due()
    else:
        return f"❌ Unknown action: {action}"
