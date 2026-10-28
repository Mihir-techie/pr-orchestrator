import asyncio
import logging
import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.services.github_client import GitHubClient
from app.services.telemetry_store import (
    Metrics,
    ReviewRecord,
    get_metrics,
    get_recent_reviews,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37})$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class ManualReviewRequest(BaseModel):
    repository: str
    pull_number: int = Field(gt=0)

    @field_validator("repository")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        candidate = value.strip()
        if candidate.startswith(("https://", "http://")):
            parsed = urlsplit(candidate)
            if parsed.scheme != "https" or parsed.hostname != "github.com":
                raise ValueError("Repository links must use https://github.com")
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[2] == "pull" and parts[3].isdigit():
                parts = parts[:2]
            elif len(parts) != 2:
                raise ValueError("Enter a GitHub repository URL or owner/repository")
        else:
            parts = candidate.split("/")
            if len(parts) != 2:
                raise ValueError("Enter a GitHub repository URL or owner/repository")

        owner, repository = parts
        if repository.endswith(".git"):
            repository = repository[:-4]
        if not _OWNER_PATTERN.fullmatch(owner) or not _REPOSITORY_PATTERN.fullmatch(
            repository
        ):
            raise ValueError("Enter a valid GitHub owner/repository")
        return f"{owner}/{repository}"


def _enqueue_review(payload: dict[str, object]) -> str:
    from app.workers.celery_worker import process_pull_request

    return process_pull_request.delay(payload).id


@router.get("/metrics", response_model=Metrics)
def read_metrics() -> Metrics:
    try:
        return get_metrics()
    except Exception as exc:
        logger.exception("Unable to read review telemetry metrics")
        raise HTTPException(
            status_code=503, detail="Review telemetry is temporarily unavailable"
        ) from exc


@router.get("/reviews", response_model=list[ReviewRecord])
def read_reviews(
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ReviewRecord]:
    try:
        return get_recent_reviews(limit=limit)
    except Exception as exc:
        logger.exception("Unable to read recent review telemetry")
        raise HTTPException(
            status_code=503, detail="Review history is temporarily unavailable"
        ) from exc


@router.post("/reviews", status_code=202)
async def start_review(request: ManualReviewRequest) -> dict[str, object]:
    try:
        github = GitHubClient()
    except RuntimeError as exc:
        logger.exception("Unable to initialize GitHub client for manual review")
        raise HTTPException(
            status_code=503, detail="GitHub access is not configured"
        ) from exc

    try:
        metadata = await github.get_pull_request_metadata(
            request.repository, request.pull_number
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="Pull request was not found or is not accessible to the configured GitHub token",
            ) from exc
        logger.exception(
            "GitHub rejected manual review lookup for %s#%s",
            request.repository,
            request.pull_number,
        )
        raise HTTPException(
            status_code=502, detail="Unable to load pull request from GitHub"
        ) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.exception(
            "Unable to load manual review metadata for %s#%s",
            request.repository,
            request.pull_number,
        )
        raise HTTPException(
            status_code=503, detail="Unable to connect to GitHub for this review"
        ) from exc
    finally:
        await github.close()

    payload: dict[str, object] = {
        "action": "manual",
        "repository": {"full_name": request.repository},
        "pull_request": {
            "number": request.pull_number,
            "base": metadata["base"],
            "user": metadata.get("user") or {},
            "head": metadata.get("head") or {},
        },
    }
    try:
        task_id = await asyncio.to_thread(_enqueue_review, payload)
    except Exception as exc:
        logger.exception(
            "Unable to enqueue manual review for %s#%s",
            request.repository,
            request.pull_number,
        )
        raise HTTPException(
            status_code=503, detail="Unable to enqueue pull request review"
        ) from exc
    return {
        "status": "queued",
        "task_id": task_id,
        "repository": request.repository,
        "pull_number": request.pull_number,
    }
