"""
Social media scheduler for x402Scout.

Run modes:
  python -m agent_economy.social.scheduler --post-now x
  python -m agent_economy.social.scheduler --post-now discord_cdp
  python -m agent_economy.social.scheduler --run-due
  python -m agent_economy.social.scheduler --queue-week
  python -m agent_economy.social.scheduler --status
  python -m agent_economy.social.scheduler --dry-run --post-now x
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta

from .config import (
    X_ENABLED, DISCORD_ENABLED,
    X_MAX_POSTS_PER_DAY, X_MAX_POSTS_PER_WEEK, DISCORD_MAX_POSTS_PER_DAY,
    STATE_FILE,
)
from .state import SocialState
from .x_poster import post_tweet
from .discord_poster import post_discord
from .content_library import CONTENT_LIBRARY


def _pick_next_post(state: SocialState, platform: str) -> dict | None:
    """Pick highest-priority unposted content for platform."""
    recent = state.get_recent_posts(500)
    posted_ids = {p.get("content_id") for p in recent}

    available = [
        item for item in CONTENT_LIBRARY
        if item["platform"] in (platform, "all")
        and item["id"] not in posted_ids
    ]
    if not available:
        # All content cycled — restart from highest priority
        available = [item for item in CONTENT_LIBRARY if item["platform"] in (platform, "all")]

    if not available:
        return None
    return sorted(available, key=lambda x: x["priority"])[0]


def _can_post_x(state: SocialState) -> tuple[bool, str]:
    stats = state.get_stats()
    if stats["x_posts_today"] >= X_MAX_POSTS_PER_DAY:
        return False, f"Daily X limit reached ({X_MAX_POSTS_PER_DAY}/day)"
    if stats["x_posts_this_week"] >= X_MAX_POSTS_PER_WEEK:
        return False, f"Weekly X limit reached ({X_MAX_POSTS_PER_WEEK}/week)"
    return True, "ok"


def _can_post_discord(state: SocialState) -> tuple[bool, str]:
    stats = state.get_stats()
    if stats["discord_posts_today"] >= DISCORD_MAX_POSTS_PER_DAY:
        return False, f"Daily Discord limit reached ({DISCORD_MAX_POSTS_PER_DAY}/day)"
    return True, "ok"


def post_now(platform: str, dry_run: bool = False) -> dict:
    """Post next scheduled content to platform immediately."""
    state = SocialState(STATE_FILE)

    if platform == "x":
        if not X_ENABLED and not dry_run:
            return {"success": False, "error": "X not configured (set X_CONSUMER_KEY etc.)"}
        can, reason = _can_post_x(state)
        if not can:
            return {"success": False, "error": reason}
        item = _pick_next_post(state, "x")
        if not item:
            return {"success": False, "error": "No content available for X"}

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "content": item["content"],
                "id": item["id"],
                "pillar": item["pillar"],
                "char_count": len(item["content"]),
            }

        result = post_tweet(item["content"])
        if result["success"]:
            state.record_post("x", item["content"], result["post_id"], item["pillar"])
            state._data["posts"][-1]["content_id"] = item["id"]
            state.save()
        return {**result, "content_id": item["id"], "pillar": item["pillar"]}

    elif platform.startswith("discord"):
        if not DISCORD_ENABLED and not dry_run:
            return {"success": False, "error": "Discord webhooks not configured"}
        can, reason = _can_post_discord(state)
        if not can:
            return {"success": False, "error": reason}
        item = _pick_next_post(state, platform)
        if not item:
            return {"success": False, "error": f"No content available for {platform}"}

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "content": item["content"],
                "id": item["id"],
                "pillar": item["pillar"],
            }

        result = post_discord(platform, item["content"])
        if result["success"]:
            state.record_post(platform, item["content"], result["post_id"], item["pillar"])
            state._data["posts"][-1]["content_id"] = item["id"]
            state.save()
        return {**result, "content_id": item["id"], "pillar": item["pillar"]}

    else:
        return {"success": False, "error": f"Unknown platform: {platform}"}


def run_due_posts() -> list:
    """Process all queue items that are due."""
    state = SocialState(STATE_FILE)
    due = state.get_due_posts()
    results = []

    for item in due:
        platform = item["platform"]
        content = item["content"]
        result: dict = {"item_id": item["id"], "platform": platform}

        if platform == "x":
            if not X_ENABLED:
                state.mark_queue_item(item["id"], "skipped_no_creds")
                result["status"] = "skipped_no_creds"
            else:
                can, reason = _can_post_x(state)
                if not can:
                    result["status"] = "skipped_rate_limit"
                    result["reason"] = reason
                else:
                    r = post_tweet(content)
                    if r["success"]:
                        state.record_post("x", content, r["post_id"], item["pillar"])
                        state.mark_queue_item(item["id"], "posted")
                        result["status"] = "posted"
                    else:
                        state.mark_queue_item(item["id"], f"failed:{r['error'][:50]}")
                        result["status"] = "failed"
                        result["error"] = r["error"]

        elif platform.startswith("discord"):
            can, reason = _can_post_discord(state)
            if not can:
                result["status"] = "skipped_rate_limit"
                result["reason"] = reason
            else:
                r = post_discord(platform, content)
                if r["success"]:
                    state.record_post(platform, content, None, item["pillar"])
                    state.mark_queue_item(item["id"], "posted")
                    result["status"] = "posted"
                else:
                    state.mark_queue_item(item["id"], f"failed:{r['error'][:50]}")
                    result["status"] = "failed"
                    result["error"] = r["error"]
        else:
            result["status"] = "unknown_platform"

        results.append(result)

    return results


def queue_week_of_posts() -> list:
    """Queue a full week of posts across platforms."""
    state = SocialState(STATE_FILE)
    now = datetime.now(timezone.utc)

    # Schedule: Mon/Wed/Fri → X at 14:00 UTC; Tue/Thu → Discord at 16:00 UTC
    schedule = []
    for day_offset in range(1, 8):
        post_time = now + timedelta(days=day_offset)
        weekday = post_time.weekday()  # 0=Mon, 6=Sun

        if weekday in (0, 2, 4):  # Mon, Wed, Fri
            schedule.append({
                "platform": "x",
                "scheduled_for": post_time.replace(hour=14, minute=0, second=0, microsecond=0).isoformat(),
            })
        elif weekday in (1, 3):  # Tue, Thu
            schedule.append({
                "platform": "discord_cdp",
                "scheduled_for": post_time.replace(hour=16, minute=0, second=0, microsecond=0).isoformat(),
            })

    queued = []
    for slot in schedule:
        item = _pick_next_post(state, slot["platform"])
        if item:
            item_id = state.add_to_queue(
                platform=slot["platform"],
                content=item["content"],
                scheduled_for=slot["scheduled_for"],
                pillar=item["pillar"],
            )
            queued.append({
                "id": item_id,
                "platform": slot["platform"],
                "scheduled_for": slot["scheduled_for"][:16],
                "content_id": item["id"],
                "pillar": item["pillar"],
            })

    return queued


def get_status() -> dict:
    state = SocialState(STATE_FILE)
    return {
        "stats": state.get_stats(),
        "queue_pending": len(state.get_queue()),
        "recent_posts": state.get_recent_posts(5),
        "x_enabled": X_ENABLED,
        "discord_enabled": DISCORD_ENABLED,
        "content_library_size": len(CONTENT_LIBRARY),
    }


def main():
    parser = argparse.ArgumentParser(description="x402Scout Social Media Scheduler")
    parser.add_argument(
        "--post-now",
        metavar="PLATFORM",
        help="Post next content to platform: x | discord_cdp | discord_base",
    )
    parser.add_argument("--run-due", action="store_true", help="Run all due queue items")
    parser.add_argument("--queue-week", action="store_true", help="Queue a week of posts")
    parser.add_argument("--status", action="store_true", help="Show current state and stats")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be posted without posting")

    args = parser.parse_args()

    if args.post_now:
        result = post_now(args.post_now, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))

    elif args.run_due:
        results = run_due_posts()
        if results:
            print(json.dumps(results, indent=2))
        else:
            print("No posts due.")

    elif args.queue_week:
        queued = queue_week_of_posts()
        print(f"Queued {len(queued)} posts for next 7 days:")
        for q in queued:
            print(f"  [{q['platform']:12}] {q['scheduled_for']} — {q['content_id']} ({q['pillar']})")

    elif args.status:
        status = get_status()
        print(json.dumps(status, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
