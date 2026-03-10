"""Post to X (Twitter) via Tweepy OAuth 1.0a."""
import tweepy
from .config import (
    X_CONSUMER_KEY, X_CONSUMER_SECRET,
    X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET,
    X_ENABLED,
)


def _get_client() -> tweepy.Client:
    if not X_ENABLED:
        raise RuntimeError("X credentials not configured")
    return tweepy.Client(
        consumer_key=X_CONSUMER_KEY,
        consumer_secret=X_CONSUMER_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
    )


def post_tweet(text: str) -> dict:
    """Post a tweet. Returns {success, post_id, error}."""
    if not X_ENABLED:
        return {"success": False, "post_id": None, "error": "X not configured"}
    if len(text) > 280:
        return {"success": False, "post_id": None, "error": f"Tweet too long: {len(text)} chars"}
    try:
        client = _get_client()
        response = client.create_tweet(text=text)
        post_id = str(response.data["id"])
        return {"success": True, "post_id": post_id, "error": None}
    except tweepy.TweepyException as e:
        return {"success": False, "post_id": None, "error": str(e)}
    except Exception as e:
        return {"success": False, "post_id": None, "error": f"Unexpected: {e}"}


def reply_to_tweet(text: str, reply_to_id: str) -> dict:
    """Reply to an existing tweet."""
    if not X_ENABLED:
        return {"success": False, "post_id": None, "error": "X not configured"}
    try:
        client = _get_client()
        response = client.create_tweet(text=text, in_reply_to_tweet_id=reply_to_id)
        post_id = str(response.data["id"])
        return {"success": True, "post_id": post_id, "error": None}
    except tweepy.TweepyException as e:
        return {"success": False, "post_id": None, "error": str(e)}
    except Exception as e:
        return {"success": False, "post_id": None, "error": f"Unexpected: {e}"}
