import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import get_settings
from app.services.redis_client import release_webhook_delivery, reserve_webhook_delivery
from app.workers.celery_worker import process_pull_request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    secret = settings.github_webhook_secret.get_secret_value()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub webhook verification is not configured",
        )
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    if not x_github_delivery:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing delivery ID")
    if x_github_event != "pull_request":
        return {"status": "ignored"}
    try:
        payload: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    action = payload.get("action")
    if action not in {"opened", "synchronize"}:
        return {"status": "ignored"}
    repository = payload.get("repository")
    pull_request = payload.get("pull_request")
    if (
        not isinstance(repository, dict)
        or not isinstance(repository.get("full_name"), str)
        or "/" not in repository["full_name"]
        or not isinstance(pull_request, dict)
        or not isinstance(pull_request.get("number"), int)
        or isinstance(pull_request.get("number"), bool)
        or pull_request["number"] < 1
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pull request payload")

    try:
        reserved = await reserve_webhook_delivery(x_github_delivery)
    except Exception as exc:
        logger.exception("Unable to reserve GitHub webhook delivery")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook deduplication is unavailable",
        ) from exc
    if not reserved:
        return {"status": "duplicate"}

    try:
        task = await asyncio.to_thread(process_pull_request.delay, payload)
    except Exception as exc:
        logger.exception("Unable to enqueue GitHub pull request webhook")
        try:
            await release_webhook_delivery(x_github_delivery)
        except Exception:
            logger.exception("Unable to release failed GitHub webhook delivery reservation")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to enqueue webhook for processing",
        ) from exc
    return {"status": "queued", "task_id": task.id}
