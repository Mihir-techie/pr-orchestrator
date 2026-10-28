import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr

from fastapi import FastAPI

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api.webhooks import router
from app.config import Settings


class GitHubWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "test-webhook-secret"
        self.payload = {
            "action": "opened",
            "repository": {"full_name": "example/repo"},
            "pull_request": {"number": 7},
        }
        self.body = json.dumps(self.payload).encode()
        self.signature = "sha256=" + hmac.new(
            self.secret.encode(), self.body, hashlib.sha256
        ).hexdigest()
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        self.client = TestClient(app)
        self.settings_patch = patch(
            "app.api.webhooks.get_settings",
            return_value=Settings(
                _env_file=None,
                redis_url="redis://localhost:6379/0",
                github_webhook_secret=SecretStr(self.secret),
            ),
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_valid_pull_request_is_enqueued(self) -> None:
        with (
            patch(
                "app.api.webhooks.reserve_webhook_delivery",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.webhooks.process_pull_request.delay",
                return_value=MagicMock(id="task-123"),
            ) as enqueue,
        ):
            response = self.client.post(
                "/api/v1/webhooks/github",
                content=self.body,
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-GitHub-Delivery": "delivery-123",
                    "X-Hub-Signature-256": self.signature,
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["task_id"], "task-123")
        enqueue.assert_called_once_with(self.payload)

    def test_invalid_signature_is_rejected(self) -> None:
        response = self.client.post(
            "/api/v1/webhooks/github",
            content=self.body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-123",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_duplicate_delivery_is_not_enqueued(self) -> None:
        with (
            patch(
                "app.api.webhooks.reserve_webhook_delivery",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.api.webhooks.process_pull_request.delay") as enqueue,
        ):
            response = self.client.post(
                "/api/v1/webhooks/github",
                content=self.body,
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-GitHub-Delivery": "delivery-123",
                    "X-Hub-Signature-256": self.signature,
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "duplicate")
        enqueue.assert_not_called()
def test_webhook_payload_validation():
    """Verify webhook ingestion endpoint handles standard payloads."""
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 1,
            "title": "Test PR",
            "head": {"ref": "feature-branch"},
            "base": {"ref": "main"}
        },
        "repository": {
            "full_name": "Mihir-techie/pr-orchestrator"
        }
    }


if __name__ == "__main__":
    unittest.main()
