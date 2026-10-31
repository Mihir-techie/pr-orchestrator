from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_DIFF_CHARS = 10_000


class Settings(BaseSettings):
    redis_url: SecretStr
    github_token: SecretStr = SecretStr("")
    github_webhook_secret: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    google_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-20b"
    groq_flagship_model: str = "openai/gpt-oss-120b"
    gemini_flash_model: str = "gemini-1.5-flash"
    gemini_pro_model: str = "gemini-3.8-flash"
    max_diff_chars: int = Field(default=MAX_DIFF_CHARS, gt=0, le=MAX_DIFF_CHARS)
    llm_tokens_per_minute: int = Field(default=30_000, gt=0)
    ip_rate_limit_requests: int = Field(default=10, gt=0)
    ip_rate_limit_window_seconds: int = Field(default=60, gt=0)
    log_level: str = "INFO"
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2022-11-28"
    groq_input_cost_per_million: float = Field(default=0.05, ge=0)
    groq_output_cost_per_million: float = Field(default=0.08, ge=0)
    gemini_flash_input_cost_per_million: float = Field(default=0.15, ge=0)
    gemini_flash_output_cost_per_million: float = Field(default=0.60, ge=0)
    gemini_pro_input_cost_per_million: float = Field(default=1.25, ge=0)
    gemini_pro_output_cost_per_million: float = Field(default=5.00, ge=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must be a non-empty redis:// or rediss:// URL")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
