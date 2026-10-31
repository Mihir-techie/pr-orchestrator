import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.middleware.ip_rate_limiter import IPRateLimitMiddleware


class IPRateLimitMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.add_middleware(IPRateLimitMiddleware)

        @app.get("/api/v1/test")
        async def api_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/health")
        async def health_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        self.client = TestClient(app)

    def test_returns_429_and_retry_after_when_ip_is_limited(self) -> None:
        redis = type("RedisMock", (), {"eval": AsyncMock(return_value=[0, 1_500])})()
        with patch("app.middleware.ip_rate_limiter.get_redis", return_value=redis):
            response = self.client.get("/api/v1/test")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "2")
        self.assertIn("Too many requests", response.json()["detail"])

    def test_non_api_path_is_not_rate_limited(self) -> None:
        redis = type("RedisMock", (), {"eval": AsyncMock()})()
        with patch("app.middleware.ip_rate_limiter.get_redis", return_value=redis):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        redis.eval.assert_not_awaited()

    def test_redis_failure_returns_service_unavailable(self) -> None:
        redis = type(
            "RedisMock",
            (),
            {"eval": AsyncMock(side_effect=RedisError("connection failed"))},
        )()
        with patch("app.middleware.ip_rate_limiter.get_redis", return_value=redis):
            response = self.client.get("/api/v1/test")

        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
