"""Persistent state for social media scheduler."""
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _default_state() -> dict:
    return {
        "posts": [],           # List of posted items: {id, platform, content, posted_at, post_id, pillar}
        "queue": [],           # Scheduled posts: {id, platform, content, scheduled_for, pillar, status}
        "stats": {
            "total_x_posts": 0,
            "total_discord_posts": 0,
            "x_posts_this_week": 0,
            "x_posts_today": 0,
            "discord_posts_today": 0,
            "last_x_post_at": None,
            "last_discord_post_at": None,
        },
        "last_updated": None,
    }


class SocialState:
    def __init__(self, state_file: str):
        self.path = Path(state_file)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return _default_state()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(self._data, indent=2))

    def record_post(self, platform: str, content: str, post_id: str | None, pillar: str):
        entry = {
            "id": str(uuid.uuid4())[:8],
            "platform": platform,
            "content": content[:100] + "..." if len(content) > 100 else content,
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "post_id": post_id,
            "pillar": pillar,
        }
        self._data["posts"].append(entry)
        # Keep only last 500
        self._data["posts"] = self._data["posts"][-500:]
        # Update stats
        stats = self._data["stats"]
        if platform == "x":
            stats["total_x_posts"] += 1
            stats["last_x_post_at"] = entry["posted_at"]
            self._recalc_x_counts()
        elif platform in ("discord_cdp", "discord_base"):
            stats["total_discord_posts"] += 1
            stats["last_discord_post_at"] = entry["posted_at"]
            self._recalc_discord_counts()
        self.save()

    def _recalc_x_counts(self):
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=now.weekday())
        x_posts = [p for p in self._data["posts"] if p["platform"] == "x"]
        self._data["stats"]["x_posts_today"] = sum(
            1 for p in x_posts
            if datetime.fromisoformat(p["posted_at"]) >= today_start
        )
        self._data["stats"]["x_posts_this_week"] = sum(
            1 for p in x_posts
            if datetime.fromisoformat(p["posted_at"]) >= week_start
        )

    def _recalc_discord_counts(self):
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        discord_posts = [p for p in self._data["posts"] if p["platform"].startswith("discord")]
        self._data["stats"]["discord_posts_today"] = sum(
            1 for p in discord_posts
            if datetime.fromisoformat(p["posted_at"]) >= today_start
        )

    def add_to_queue(self, platform: str, content: str, scheduled_for: str, pillar: str) -> str:
        item_id = str(uuid.uuid4())[:8]
        self._data["queue"].append({
            "id": item_id,
            "platform": platform,
            "content": content,
            "scheduled_for": scheduled_for,
            "pillar": pillar,
            "status": "pending",
        })
        self.save()
        return item_id

    def get_due_posts(self) -> list:
        """Return posts scheduled for now or past."""
        now = datetime.now(timezone.utc).isoformat()
        return [
            item for item in self._data["queue"]
            if item["status"] == "pending" and item["scheduled_for"] <= now
        ]

    def mark_queue_item(self, item_id: str, status: str):
        for item in self._data["queue"]:
            if item["id"] == item_id:
                item["status"] = status
                break
        self.save()

    def get_stats(self) -> dict:
        self._recalc_x_counts()
        self._recalc_discord_counts()
        return self._data["stats"]

    def get_recent_posts(self, n: int = 20) -> list:
        return self._data["posts"][-n:]

    def get_queue(self) -> list:
        return [q for q in self._data["queue"] if q["status"] == "pending"]
