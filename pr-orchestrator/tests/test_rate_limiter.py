import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.rate_limiter import acquire_tokens


class TokenBucketTests(unittest.TestCase):
    def test_waits_asynchronously_until_tokens_are_available(self) -> None:
        redis = SimpleNamespace(
            eval=AsyncMock(side_effect=[[0, 250], [1, 0]])
        )
        sleep = AsyncMock()

        async def run() -> None:
            with (
                patch("app.services.rate_limiter.get_redis", return_value=redis),
                patch("app.services.rate_limiter.asyncio.sleep", sleep),
            ):
                await acquire_tokens("groq", 25, 30_000)

        asyncio.run(run())

        self.assertEqual(redis.eval.await_count, 2)
        sleep.assert_awaited_once_with(0.25)
        self.assertEqual(redis.eval.await_args_list[0].args[2:], (
            "rate-limit:llm:groq",
            30_000,
            25,
            60_000,
        ))

    def test_rejects_prompts_larger_than_the_budget(self) -> None:
        async def run() -> None:
            await acquire_tokens("groq", 101, 100)

        with self.assertRaisesRegex(ValueError, "exceed"):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
