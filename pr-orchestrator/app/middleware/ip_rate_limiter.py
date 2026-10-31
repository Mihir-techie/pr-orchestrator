import hashlib
import logging
import math
import uuid

from fastapi import Request
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

_SLIDING_WINDOW_SCRIPT = """
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
local window = tonumber(ARGV[1])
local request_limit = tonumber(ARGV[2])
local cutoff = now - window

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
local count = redis.call('ZCARD', KEYS[1])
if count >= request_limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after = math.max(1, tonumber(oldest[2]) + window - now)
    return {0, retry_after}
end

redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0}
"""


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        hashed_ip = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
        settings = get_settings()
        window_milliseconds = settings.ip_rate_limit_window_seconds * 1000
        try:
            allowed, retry_milliseconds = await get_redis().eval(
                _SLIDING_WINDOW_SCRIPT,
                1,
                f"rate-limit:ip:{hashed_ip}",
                window_milliseconds,
                settings.ip_rate_limit_requests,
                uuid.uuid4().hex,
            )
        except RedisError:
            logger.exception("Unable to check IP request rate limit")
            return JSONResponse(
                status_code=503,
                content={"detail": "Request rate limiting is temporarily unavailable"},
            )

        if not allowed:
            retry_after = max(1, math.ceil(int(retry_milliseconds) / 1000))
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests; try again later"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
