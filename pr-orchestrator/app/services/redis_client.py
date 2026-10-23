from functools import lru_cache
import json
from typing import Any

from redis.asyncio import Redis

from app.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(
        get_settings().redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )


async def cache_get(key: str) -> Any | None:
    value = await get_redis().get(key)
    return json.loads(value) if value is not None else None


async def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    await get_redis().set(key, json.dumps(value), ex=ttl_seconds)


async def reserve_webhook_delivery(delivery_id: str, ttl_seconds: int = 86_400) -> bool:
    return bool(
        await get_redis().set(
            f"github:webhook:{delivery_id}",
            "1",
            nx=True,
            ex=ttl_seconds,
        )
    )


async def release_webhook_delivery(delivery_id: str) -> None:
    await get_redis().delete(f"github:webhook:{delivery_id}")
