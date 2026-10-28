import asyncio
import time
from collections.abc import Coroutine
from typing import Any, TypeVar

from celery import Celery
from celery.utils.log import get_task_logger

from app.config import get_settings
from app.services.cost_router import analyze_diff, select_model_tier
from app.services.github_client import GitHubClient
from app.services.llm import PermanentLLMError
from app.agents.graph import review_graph

Result = TypeVar("Result")

settings = get_settings()
logger = get_task_logger(__name__)
celery_app = Celery(
    "pr_orchestrator",
    broker=settings.redis_url.get_secret_value(),
    backend=settings.redis_url.get_secret_value(),
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=86_400,
    task_track_started=True,
)


def _render_report(state: dict[str, Any]) -> str:
    metrics = state.get("telemetry", [])
    total_cost = sum(float(item.get("estimated_cost_usd", 0)) for item in metrics)
    total_savings = sum(float(item.get("estimated_savings_usd", 0)) for item in metrics)
    total_tokens = sum(
        int(item.get("input_tokens", 0)) + int(item.get("output_tokens", 0))
        for item in metrics
    )
    report = (
        "## Automated PR review\n\n"
        "### Code review\n"
        f"{state.get('code_review', 'No code review result.')}\n\n"
        "### Security review\n"
        f"{state.get('security_review', 'No security review result.')}\n\n"
        "### Routing and telemetry\n"
        f"- Model route: `{state.get('model_tier', 'unknown')}`\n"
        f"- Model(s): {', '.join(sorted({str(item['model_name']) for item in metrics if item.get('model_name')})) or 'unknown'}\n"
        f"- Tokens: {total_tokens}\n"
        f"- Estimated LLM cost: ${total_cost:.6f}\n"
        f"- Estimated savings vs. Gemini Pro: ${total_savings:.6f}\n"
        f"- Review workflow latency: {state.get('latency_seconds', 0):.2f}s\n"
    )
    if state.get("diff_truncated"):
        report += "- Note: the diff was truncated before review; inspect the complete changes manually.\n"
    reviewers = state.get("reviewer_candidates", [])
    if reviewers:
        report += f"- Suggested reviewers: {', '.join('@' + name for name in reviewers)}\n"
    return report


def _drain_pending_tasks(loop: asyncio.AbstractEventLoop) -> None:
    for _ in range(3):
        pending_tasks = asyncio.all_tasks(loop)
        if not pending_tasks:
            return
        for task in pending_tasks:
            task.cancel()
        loop.run_until_complete(
            asyncio.gather(*pending_tasks, return_exceptions=True)
        )

    pending_names = ", ".join(task.get_name() for task in asyncio.all_tasks(loop))
    if pending_names:
        logger.error("Async tasks remained during event-loop shutdown: %s", pending_names)


def _run_with_fresh_loop(
    coroutine: Coroutine[Any, Any, Result],
) -> Result:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)
    finally:
        try:
            _drain_pending_tasks(loop)
            loop.run_until_complete(loop.shutdown_asyncgens())
            _drain_pending_tasks(loop)
            loop.run_until_complete(loop.shutdown_default_executor())
            _drain_pending_tasks(loop)
        finally:
            asyncio.set_event_loop(None)
            loop.close()


async def _process_pull_request(payload: dict[str, Any]) -> dict[str, Any]:
    started_at = time.perf_counter()
    pull = payload["pull_request"]
    repository = payload["repository"]["full_name"]
    number = int(pull["number"])
    base_ref = pull["base"]["ref"]
    github = GitHubClient()
    try:
        diff = await github.get_pull_diff(repository, number)
        analysis = analyze_diff(diff, settings)
        tier = select_model_tier(analysis)
        initial_state = {
            "repository": repository,
            "pull_number": number,
            "pull_author": pull.get("user", {}).get("login", ""),
            "base_ref": base_ref,
            "head_sha": pull.get("head", {}).get("sha", ""),
            "diff": diff,
            "pruned_diff": analysis.pruned_diff,
            "changed_files": list(analysis.changed_files),
            "changed_lines": analysis.changed_lines,
            "complexity_score": analysis.complexity_score,
            "sensitive": analysis.sensitive,
            "diff_truncated": analysis.truncated,
            "model_tier": tier,
            "telemetry": [],
        }
        result = await review_graph.ainvoke(initial_state)
        result["latency_seconds"] = time.perf_counter() - started_at
        await github.request_reviewers(
            repository, number, result.get("reviewer_candidates", [])
        )
        await github.post_pr_comment(repository, number, _render_report(result))
        logger.info(
            "Completed review for %s#%s route=%s models=%s changed_files=%s tokens=%s cost_usd=%.6f savings_usd=%.6f latency_seconds=%.2f",
            repository,
            number,
            tier,
            sorted({str(item["model_name"]) for item in result.get("telemetry", []) if item.get("model_name")}),
            len(analysis.changed_files),
            sum(
                int(item.get("input_tokens", 0)) + int(item.get("output_tokens", 0))
                for item in result.get("telemetry", [])
            ),
            sum(float(item.get("estimated_cost_usd", 0)) for item in result.get("telemetry", [])),
            sum(float(item.get("estimated_savings_usd", 0)) for item in result.get("telemetry", [])),
            result["latency_seconds"],
        )
        return {
            "repository": repository,
            "pull_number": number,
            "model_tier": tier,
            "reviewers": result.get("reviewer_candidates", []),
            "truncated": analysis.truncated,
            "latency_seconds": result["latency_seconds"],
        }
    finally:
        await github.close()


@celery_app.task(
    bind=True,
    name="app.workers.celery_worker.process_pull_request",
    autoretry_for=(Exception,),
    dont_autoretry_for=(PermanentLLMError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def process_pull_request(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
    logger.info(
        "Processing pull request task_id=%s repository=%s",
        self.request.id,
        payload.get("repository", {}).get("full_name", "unknown"),
    )
    return _run_with_fresh_loop(_process_pull_request(payload))
