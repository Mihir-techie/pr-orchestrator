import asyncio

from app.services.redis_client import get_redis

_WINDOW_MILLISECONDS = 60_000
_TOKEN_BUCKET_SCRIPT = """
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
local capacity = tonumber(ARGV[1])
local requested = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local tokens = tonumber(values[1])
local updated_at = tonumber(values[2])

if not tokens or not updated_at then
    tokens = capacity
else
    local elapsed = math.max(0, now - updated_at)
    tokens = math.min(capacity, tokens + elapsed * capacity / window)
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
    redis.call('PEXPIRE', KEYS[1], window * 2)
    return {1, 0}
end

local wait_milliseconds = math.ceil((requested - tokens) * window / capacity)
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('PEXPIRE', KEYS[1], window * 2)
return {0, wait_milliseconds}
"""


async def acquire_tokens(
    provider: str,
    requested_tokens: int,
    tokens_per_minute: int,
) -> None:
    if requested_tokens < 1:
        raise ValueError("requested_tokens must be positive")
    if tokens_per_minute < 1:
        raise ValueError("tokens_per_minute must be positive")
    if requested_tokens > tokens_per_minute:
        raise ValueError(
            "Estimated prompt tokens exceed the configured per-minute token budget"
        )

    key = f"rate-limit:llm:{provider}"
    while True:
        allowed, wait_milliseconds = await get_redis().eval(
            _TOKEN_BUCKET_SCRIPT,
            1,
            key,
            tokens_per_minute,
            requested_tokens,
            _WINDOW_MILLISECONDS,
        )
        if allowed:
            return
        await asyncio.sleep(max(int(wait_milliseconds) / 1000, 0.001))
