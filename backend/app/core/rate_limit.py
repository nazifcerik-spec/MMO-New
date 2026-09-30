"""Redis fixed-window rate limiter. Fails open (logged) if Redis is unavailable: rate limiting is a
defence-in-depth layer, never the only guard for correctness."""

import logging
import time

from app.core.errors import RateLimitedError
from app.db.redis import get_redis

log = logging.getLogger("app.ratelimit")


def parse_rule(rule: str) -> tuple[int, int]:
    count, seconds = rule.split("/")
    return int(count), int(seconds)


async def hit(bucket: str, rule: str) -> int:
    """Increment bucket; raise RateLimitedError when over the limit. Returns current count."""
    limit, window = parse_rule(rule)
    window_id = int(time.time() // window)
    key = f"rl:{bucket}:{window_id}"
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window + 1)
        count, _ = await pipe.execute()
    except Exception:
        log.warning("rate_limit_unavailable", extra={"bucket": bucket})
        return 0
    if int(count) > limit:
        retry_after = window - int(time.time()) % window
        raise RateLimitedError("Too many requests", details={"retry_after_seconds": retry_after})
    return int(count)


async def reset(bucket: str, rule: str) -> None:
    _, window = parse_rule(rule)
    try:
        await get_redis().delete(f"rl:{bucket}:{int(time.time() // window)}")
    except Exception:
        log.warning("rate_limit_unavailable", extra={"bucket": bucket})
