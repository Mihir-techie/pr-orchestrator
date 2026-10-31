import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.dashboard import router as dashboard_router
from app.api.webhooks import router as webhook_router
from app.config import get_settings
from app.middleware.ip_rate_limiter import IPRateLimitMiddleware
from app.services.redis_client import get_redis

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_redis().aclose()


app = FastAPI(
    title="PR Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(IPRateLimitMiddleware)
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    await get_redis().ping()
    return {"status": "ok"}
