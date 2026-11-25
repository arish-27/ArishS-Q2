import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple
import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logger import logger


class RateLimiter:
    """
    Distributed rate limiter backed by Redis (primary), with transparent in-memory
    fallback if Redis is unavailable (e.g. standalone unit tests outside Docker).
    Always exposes which backend is active ('redis' or 'memory').
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[aioredis.Redis] = None
        self._memory_windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._memory_lock = asyncio.Lock()
        self.active_backend: str = "uninitialized"

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
        try:
            await self._redis.ping()
            self.active_backend = "redis"
            return self._redis
        except Exception as exc:
            if self.active_backend != "memory":
                logger.warning(f"Redis unreachable ({exc}); using in-memory rate limiter fallback.")
            self.active_backend = "memory"
            return None

    async def get_backend_status(self) -> str:
        """Probes Redis and returns active rate-limiter backend ('redis' or 'memory')."""
        await self._get_redis()
        return self.active_backend

    async def check_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int, str]:
        """
        Increments rate limit bucket and returns (allowed, remaining, active_backend).
        """
        client = await self._get_redis()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.incr(key)
                pipe.ttl(key)
                count, ttl = await pipe.execute()
                if count == 1 or ttl == -1:
                    await client.expire(key, window_seconds)
                allowed = count <= max_requests
                remaining = max(0, max_requests - count)
                return allowed, remaining, "redis"
            except Exception as exc:
                logger.warning(f"Redis rate limit command failed ({exc}); falling back to memory.")
                self.active_backend = "memory"

        # In-memory sliding window fallback
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._memory_lock:
            q = self._memory_windows[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= max_requests:
                return False, 0, "memory"
            q.append(now)
            return True, max(0, max_requests - len(q)), "memory"

    async def check_ws_connection(self, user_id: str, client_ip: str) -> Tuple[bool, int, str]:
        """Checks both per-user and per-IP WebSocket connection rate limits."""
        window = settings.WS_RATE_LIMIT_WINDOW_SECONDS
        limit = settings.WS_RATE_LIMIT_CONNECTIONS

        user_ok, user_rem, backend = await self.check_limit(
            f"ratelimit:ws:user:{user_id}", limit, window
        )
        if not user_ok:
            return False, 0, backend

        ip_ok, ip_rem, backend = await self.check_limit(
            f"ratelimit:ws:ip:{client_ip or 'unknown'}", limit, window
        )
        return ip_ok, min(user_rem, ip_rem), backend

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


rate_limiter = RateLimiter()
