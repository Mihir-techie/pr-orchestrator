from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq

from app.config import Settings, get_settings
from app.services.cost_router import ModelTier, estimate_tokens


class PermanentLLMError(RuntimeError):
    """An LLM provider rejected a request that retries cannot fix."""


def _get_chat_model(
    tier: ModelTier,
    http_async_client: httpx.AsyncClient,
) -> Runnable[Any, Any]:
    settings = get_settings()
    api_key = settings.groq_api_key.get_secret_value()
    if not api_key:
        raise PermanentLLMError("GROQ_API_KEY is required for model routing")
    if tier in {"groq", "gemini_flash"}:
        model = settings.groq_model
    elif tier == "gemini_pro":
        model = settings.groq_flagship_model
    else:
        raise PermanentLLMError(f"Unsupported model tier: {tier}")
    return ChatGroq(
        model=model,
        api_key=api_key,
        temperature=0,
        max_retries=0,
        http_async_client=http_async_client,
    )


def _cost(settings: Settings, tier: ModelTier, input_tokens: int, output_tokens: int) -> float:
    if tier == "groq":
        input_rate = settings.groq_input_cost_per_million
        output_rate = settings.groq_output_cost_per_million
    elif tier == "gemini_flash":
        input_rate = settings.gemini_flash_input_cost_per_million
        output_rate = settings.gemini_flash_output_cost_per_million
    elif tier == "gemini_pro":
        input_rate = settings.gemini_pro_input_cost_per_million
        output_rate = settings.gemini_pro_output_cost_per_million
    else:
        raise ValueError(f"Unsupported model tier: {tier}")
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def _is_permanent_provider_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    message = str(error).lower()
    exhausted_daily_quota = (
        "quota" in message
        and any(
            marker in message
            for marker in ("exceed", "exhaust", "per day", "daily", "billing")
        )
    )
    if status_code == 429 and exhausted_daily_quota:
        return True
    return (
        isinstance(status_code, int)
        and 400 <= status_code < 500
        and status_code not in {408, 409, 425, 429}
    )


async def invoke_agent(
    tier: ModelTier,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, dict[str, int | float | str]]:
    settings = get_settings()
    try:
        http_async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        )
        try:
            response = await _get_chat_model(tier, http_async_client).ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        finally:
            await http_async_client.aclose()
    except Exception as error:
        if _is_permanent_provider_error(error):
            raise PermanentLLMError(
                f"LLM provider rejected the request with HTTP "
                f"{error.status_code}; verify model configuration and API access."
            ) from error
        raise

    content = response.content
    if not isinstance(content, str):
        text = "\n".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    else:
        text = content
    usage = response.usage_metadata or {}
    input_tokens = int(usage.get("input_tokens", estimate_tokens(system_prompt + user_prompt)))
    output_tokens = int(usage.get("output_tokens", estimate_tokens(text)))
    actual_cost = _cost(settings, tier, input_tokens, output_tokens)
    baseline_cost = _cost(settings, "gemini_pro", input_tokens, output_tokens)
    if tier in {"groq", "gemini_flash"}:
        model_name = settings.groq_model
    elif tier == "gemini_pro":
        model_name = settings.groq_flagship_model
    else:
        raise ValueError(f"Unsupported model tier: {tier}")
    return text, {
        "model_tier": tier,
        "model_name": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": actual_cost,
        "estimated_savings_usd": max(0.0, baseline_cost - actual_cost),
    }
