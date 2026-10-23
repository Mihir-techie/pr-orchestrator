from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import Settings, get_settings
from app.services.cost_router import ModelTier, estimate_tokens


@lru_cache
def _get_chat_model(tier: ModelTier) -> Runnable[Any, Any]:
    settings = get_settings()
    if tier == "groq":
        if not settings.groq_api_key.get_secret_value():
            raise RuntimeError("GROQ_API_KEY is required for lightweight-model routing")
        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key.get_secret_value(),
            temperature=0,
        )
    if not settings.google_api_key.get_secret_value():
        raise RuntimeError("GOOGLE_API_KEY is required for Gemini routing")
    model = settings.gemini_pro_model if tier == "gemini_pro" else settings.gemini_flash_model
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.google_api_key.get_secret_value(),
        temperature=0,
    )


def _cost(settings: Settings, tier: ModelTier, input_tokens: int, output_tokens: int) -> float:
    if tier == "groq":
        input_rate = settings.groq_input_cost_per_million
        output_rate = settings.groq_output_cost_per_million
    elif tier == "gemini_flash":
        input_rate = settings.gemini_flash_input_cost_per_million
        output_rate = settings.gemini_flash_output_cost_per_million
    else:
        input_rate = settings.gemini_pro_input_cost_per_million
        output_rate = settings.gemini_pro_output_cost_per_million
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


async def invoke_agent(
    tier: ModelTier,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, dict[str, int | float | str]]:
    settings = get_settings()
    response = await _get_chat_model(tier).ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
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
    return text, {
        "model_tier": tier,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": actual_cost,
        "estimated_savings_usd": max(0.0, baseline_cost - actual_cost),
    }
