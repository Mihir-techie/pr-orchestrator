import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import httpx

from app.config import Settings
from app.services.cost_router import ModelTier
from app.services.llm import (
    PermanentLLMError,
    _cost,
    _get_chat_model,
    invoke_agent,
)


class ProviderFailure(Exception):
    def __init__(self, status_code: int, message: str | None = None) -> None:
        super().__init__(message or f"provider returned HTTP {status_code}")
        self.status_code = status_code


class FailingModel:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def ainvoke(self, _: list[object]) -> object:
        raise self.error


class SuccessfulModel:
    async def ainvoke(self, _: list[object]) -> object:
        return SimpleNamespace(
            content="review output",
            usage_metadata={"input_tokens": 5, "output_tokens": 3},
        )


class LoopBoundModel:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def ainvoke(self, messages: list[object]) -> object:
        if self.loop is not asyncio.get_running_loop():
            raise RuntimeError("Event loop is closed")
        return await SuccessfulModel().ainvoke(messages)


class LLMTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            _env_file=None,
            redis_url="redis://localhost:6379/0",
            groq_api_key="groq-test-key",
            google_api_key="google-test-key",
            groq_model="openai/gpt-oss-20b",
            groq_flagship_model="openai/gpt-oss-120b",
            gemini_flash_model="gemini-flash-test",
            gemini_pro_model="gemini-pro-test",
        )

    def test_groq_tier_uses_configured_model(self) -> None:
        http_client = MagicMock()
        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch("app.services.llm.ChatGroq") as chat_groq,
        ):
            _get_chat_model("groq", http_client)

        chat_groq.assert_called_once_with(
            model="openai/gpt-oss-20b",
            api_key="groq-test-key",
            temperature=0,
            max_retries=0,
            http_async_client=http_client,
        )

    def test_default_groq_model_is_current_replacement(self) -> None:
        settings = Settings(
            _env_file=None,
            redis_url="redis://localhost:6379/0",
        )

        self.assertEqual(settings.groq_model, "openai/gpt-oss-20b")
        self.assertEqual(settings.groq_flagship_model, "openai/gpt-oss-120b")

    def test_flash_and_flagship_tiers_use_configured_groq_models(self) -> None:
        http_client = MagicMock()
        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch("app.services.llm.ChatGroq") as chat_groq,
        ):
            _get_chat_model("gemini_flash", http_client)
            _get_chat_model("gemini_pro", http_client)

        self.assertEqual(
            [call.kwargs["model"] for call in chat_groq.call_args_list],
            ["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
        )
        self.assertTrue(
            all(call.kwargs["max_retries"] == 0 for call in chat_groq.call_args_list)
        )

    def test_all_routing_tiers_require_groq_key(self) -> None:
        settings = Settings(
            _env_file=None,
            redis_url="redis://localhost:6379/0",
        )
        with (
            patch("app.services.llm.get_settings", return_value=settings),
            patch("app.services.llm.ChatGroq") as chat_groq,
        ):
            with self.assertRaisesRegex(PermanentLLMError, "GROQ_API_KEY"):
                _get_chat_model("gemini_flash", MagicMock())

        chat_groq.assert_not_called()

    def test_cost_uses_correct_input_and_output_rates_per_tier(self) -> None:
        settings = self.settings.model_copy(
            update={
                "groq_input_cost_per_million": 1,
                "groq_output_cost_per_million": 2,
                "gemini_flash_input_cost_per_million": 3,
                "gemini_flash_output_cost_per_million": 4,
                "gemini_pro_input_cost_per_million": 5,
                "gemini_pro_output_cost_per_million": 6,
            }
        )

        self.assertEqual(_cost(settings, "groq", 1_000_000, 1_000_000), 3)
        self.assertEqual(_cost(settings, "gemini_flash", 1_000_000, 1_000_000), 7)
        self.assertEqual(_cost(settings, "gemini_pro", 1_000_000, 1_000_000), 11)

    def test_permanent_provider_error_is_not_retryable(self) -> None:
        settings = self.settings
        with (
            patch("app.services.llm.get_settings", return_value=settings),
            patch(
                "app.services.llm._get_chat_model",
                return_value=FailingModel(ProviderFailure(400)),
            ),
        ):
            with self.assertRaises(PermanentLLMError):
                asyncio.run(invoke_agent("groq", "system", "user"))

    def test_transient_provider_error_remains_retryable(self) -> None:
        failure = ProviderFailure(503)
        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch(
                "app.services.llm._get_chat_model",
                return_value=FailingModel(failure),
            ),
        ):
            with self.assertRaises(ProviderFailure) as raised:
                asyncio.run(invoke_agent("groq", "system", "user"))

        self.assertIs(raised.exception, failure)

    def test_async_http_client_is_closed_after_invocation(self) -> None:
        real_async_client = httpx.AsyncClient
        clients: list[httpx.AsyncClient] = []

        def create_client(**kwargs: object) -> httpx.AsyncClient:
            client = real_async_client(**kwargs)
            clients.append(client)
            return client

        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch(
                "app.services.llm.httpx.AsyncClient",
                side_effect=create_client,
            ),
            patch(
                "app.services.llm._get_chat_model",
                return_value=SuccessfulModel(),
            ),
        ):
            asyncio.run(invoke_agent("groq", "system", "user"))

        self.assertEqual(len(clients), 1)
        self.assertTrue(clients[0].is_closed)

    def test_rate_limit_without_daily_quota_message_remains_retryable(self) -> None:
        failure = ProviderFailure(429)
        with patch("app.services.llm.get_settings", return_value=self.settings):
            with self.assertRaises(ProviderFailure) as raised:
                asyncio.run(
                    self._invoke_with_model_failure(
                        "groq", failure
                    )
                )

        self.assertIs(raised.exception, failure)

    def test_daily_quota_exhaustion_is_not_retryable(self) -> None:
        failure = ProviderFailure(429, "Daily quota exceeded; check billing.")
        with patch("app.services.llm.get_settings", return_value=self.settings):
            with self.assertRaises(PermanentLLMError):
                asyncio.run(self._invoke_with_model_failure("gemini_pro", failure))

    async def _invoke_with_model_failure(
        self, tier: ModelTier, failure: Exception
    ) -> object:
        with patch(
            "app.services.llm._get_chat_model",
            return_value=FailingModel(failure),
        ):
            return await invoke_agent(tier, "system", "user")

    def test_successful_invoke_reports_actual_model_and_usage(self) -> None:
        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch(
                "app.services.llm._get_chat_model",
                return_value=SuccessfulModel(),
            ),
        ):
            text, metrics = asyncio.run(invoke_agent("groq", "system", "user"))

        self.assertEqual(text, "review output")
        self.assertEqual(metrics["model_name"], "openai/gpt-oss-20b")
        self.assertEqual(metrics["input_tokens"], 5)
        self.assertEqual(metrics["output_tokens"], 3)

    def test_groq_model_is_created_for_each_invocation(self) -> None:
        async def invoke_twice() -> None:
            await invoke_agent("gemini_pro", "system", "first")
            await invoke_agent("gemini_pro", "system", "second")

        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch(
                "app.services.llm.ChatGroq",
                side_effect=lambda **_: SuccessfulModel(),
            ) as chat_groq,
        ):
            asyncio.run(invoke_twice())

        self.assertEqual(chat_groq.call_count, 2)

    def test_celery_excludes_permanent_llm_errors_from_retries(self) -> None:
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
            from app.workers.celery_worker import process_pull_request

        self.assertIn(PermanentLLMError, process_pull_request.dont_autoretry_for)

    def test_celery_drains_tasks_spawned_during_cancellation(self) -> None:
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
            from app.workers.celery_worker import _run_with_fresh_loop

        cleaned_up: list[bool] = []

        async def nested_task() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                cleaned_up.append(True)

        async def background_task() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                asyncio.create_task(nested_task())
                await asyncio.sleep(0)

        async def finish_task() -> str:
            asyncio.create_task(background_task())
            return "done"

        self.assertEqual(_run_with_fresh_loop(finish_task()), "done")
        self.assertEqual(cleaned_up, [True])

    def test_celery_uses_fresh_loop_and_model_between_tasks(self) -> None:
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
            from app.workers.celery_worker import _run_with_fresh_loop

        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch(
                "app.services.llm.ChatGroq",
                side_effect=lambda **_: LoopBoundModel(asyncio.get_running_loop()),
            ),
        ):
            async def invoke_fresh_model() -> object:
                self.assertIs(asyncio.get_event_loop(), asyncio.get_running_loop())
                async with httpx.AsyncClient() as client:
                    return await _get_chat_model("gemini_pro", client).ainvoke([])

            first_result = _run_with_fresh_loop(invoke_fresh_model())
            second_result = _run_with_fresh_loop(invoke_fresh_model())

        self.assertEqual(first_result.content, "review output")
        self.assertEqual(second_result.content, "review output")

    def test_celery_retry_gets_fresh_loop_bound_model_after_failure(self) -> None:
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
            from app.workers.celery_worker import _run_with_fresh_loop

        with (
            patch("app.services.llm.get_settings", return_value=self.settings),
            patch(
                "app.services.llm.ChatGroq",
                side_effect=lambda **_: LoopBoundModel(asyncio.get_running_loop()),
            ),
        ):
            async def fail_task() -> None:
                async with httpx.AsyncClient() as client:
                    _get_chat_model("gemini_pro", client)
                raise RuntimeError("temporary provider failure")

            with self.assertRaisesRegex(RuntimeError, "temporary provider failure"):
                _run_with_fresh_loop(fail_task())

            async def invoke_after_retry() -> object:
                self.assertIs(asyncio.get_event_loop(), asyncio.get_running_loop())
                async with httpx.AsyncClient() as client:
                    return await _get_chat_model("gemini_pro", client).ainvoke([])

            result = _run_with_fresh_loop(invoke_after_retry())

        self.assertEqual(result.content, "review output")


if __name__ == "__main__":
    unittest.main()
