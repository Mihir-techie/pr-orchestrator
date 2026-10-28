import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dashboard import router as dashboard_router
from app.api.dashboard import ManualReviewRequest
from app.services.telemetry_store import (
    get_metrics,
    get_recent_reviews,
    record_completed_review,
)

REPORT = """## Automated PR review

### Routing and telemetry
- Model route: `groq`
- Model(s): openai/gpt-oss-20b
- Tokens: 125
- Estimated LLM cost: $0.000123
- Estimated savings vs. Gemini Pro: $0.004321
- Review workflow latency: 2.50s
"""


class TelemetryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "telemetry.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_empty_store_returns_zero_metrics_and_no_reviews(self) -> None:
        self.assertEqual(
            get_metrics(db_path=self.db_path),
            {
                "total_reviews": 0,
                "average_latency_seconds": 0,
                "total_tokens": 0,
                "total_savings_usd": 0,
            },
        )
        self.assertEqual(get_recent_reviews(db_path=self.db_path), [])

    def test_records_report_telemetry_and_aggregates_metrics(self) -> None:
        record_completed_review(
            "example/first", 12, REPORT, db_path=self.db_path
        )
        second_report = REPORT.replace("`groq`", "`gemini_pro`").replace(
            "Tokens: 125", "Tokens: 375"
        ).replace("latency: 2.50s", "latency: 5.50s")
        record_completed_review(
            "example/second", 34, second_report, db_path=self.db_path
        )

        self.assertEqual(
            get_metrics(db_path=self.db_path),
            {
                "total_reviews": 2,
                "average_latency_seconds": 4.0,
                "total_tokens": 500,
                "total_savings_usd": 0.008642,
            },
        )
        recent = get_recent_reviews(limit=1, db_path=self.db_path)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["repository"], "example/second")
        self.assertEqual(recent[0]["model_tier"], "gemini_pro")
        self.assertEqual(recent[0]["estimated_cost_usd"], 0.000123)
        self.assertEqual(recent[0]["total_tokens"], 375)
        self.assertEqual(recent[0]["status"], "Completed")
        self.assertTrue(recent[0]["created_at"].endswith("+00:00"))

    def test_incomplete_report_is_not_saved(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing telemetry field"):
            record_completed_review(
                "example/repo",
                7,
                "Review report without telemetry",
                db_path=self.db_path,
            )

        self.assertEqual(get_metrics(db_path=self.db_path)["total_reviews"], 0)

    def test_dashboard_endpoints_return_empty_and_recorded_data(self) -> None:
        app = FastAPI()
        app.include_router(dashboard_router, prefix="/api/v1")
        client = TestClient(app)

        with patch.dict(os.environ, {"TELEMETRY_DB_PATH": str(self.db_path)}):
            empty_metrics = client.get("/api/v1/metrics")
            empty_reviews = client.get("/api/v1/reviews")
            record_completed_review(
                "example/repo", 7, REPORT, db_path=self.db_path
            )
            metrics_response = client.get("/api/v1/metrics")
            reviews_response = client.get("/api/v1/reviews")

        self.assertEqual(empty_metrics.status_code, 200)
        self.assertEqual(empty_metrics.json()["total_reviews"], 0)
        self.assertEqual(empty_reviews.json(), [])
        self.assertEqual(metrics_response.status_code, 200)
        self.assertEqual(metrics_response.json()["total_tokens"], 125)
        self.assertEqual(reviews_response.status_code, 200)
        self.assertEqual(reviews_response.json()[0]["repository"], "example/repo")


class ManualReviewEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(dashboard_router, prefix="/api/v1")
        self.client = TestClient(app)

    def test_repository_field_accepts_owner_repo_and_github_urls(self) -> None:
        self.assertEqual(
            ManualReviewRequest(
                repository="owner/repository.git", pull_number=7
            ).repository,
            "owner/repository",
        )
        self.assertEqual(
            ManualReviewRequest(
                repository="https://github.com/owner/repository/pull/7",
                pull_number=7,
            ).repository,
            "owner/repository",
        )

    def test_repository_field_rejects_non_github_urls(self) -> None:
        with self.assertRaises(ValueError):
            ManualReviewRequest(
                repository="https://example.com/owner/repository",
                pull_number=7,
            )

    def test_manual_request_fetches_metadata_and_queues_existing_task(self) -> None:
        from app.api import dashboard

        github = MagicMock()
        github.get_pull_request_metadata = AsyncMock(
            return_value={
                "base": {"ref": "main"},
                "user": {"login": "author"},
                "head": {"sha": "head-sha"},
            }
        )
        github.close = AsyncMock()

        with (
            patch("app.api.dashboard.GitHubClient", return_value=github),
            patch.object(dashboard, "_enqueue_review", return_value="task-123") as enqueue,
        ):
            response = self.client.post(
                "/api/v1/reviews",
                json={
                    "repository": "https://github.com/example/repo",
                    "pull_number": 12,
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(),
            {
                "status": "queued",
                "task_id": "task-123",
                "repository": "example/repo",
                "pull_number": 12,
            },
        )
        github.get_pull_request_metadata.assert_awaited_once_with("example/repo", 12)
        github.close.assert_awaited_once()
        enqueue.assert_called_once_with(
            {
                "action": "manual",
                "repository": {"full_name": "example/repo"},
                "pull_request": {
                    "number": 12,
                    "base": {"ref": "main"},
                    "user": {"login": "author"},
                    "head": {"sha": "head-sha"},
                },
            }
        )


class ReviewCommentPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_telemetry_is_saved_only_after_comment_is_accepted(self) -> None:
        from app.services.github_client import GitHubClient

        client = object.__new__(GitHubClient)
        client.client = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        client.client.post = AsyncMock(return_value=response)

        with patch(
            "app.services.github_client.record_completed_review"
        ) as record:
            await client.post_pr_comment("example/repo", 7, REPORT)

        record.assert_called_once_with("example/repo", 7, REPORT)

    async def test_failed_comment_is_not_recorded(self) -> None:
        from app.services.github_client import GitHubClient

        client = object.__new__(GitHubClient)
        client.client = MagicMock()
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError("GitHub rejected comment")
        client.client.post = AsyncMock(return_value=response)

        with patch(
            "app.services.github_client.record_completed_review"
        ) as record:
            with self.assertRaisesRegex(RuntimeError, "GitHub rejected comment"):
                await client.post_pr_comment("example/repo", 7, REPORT)

        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
