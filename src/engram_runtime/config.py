from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    """Local runtime configuration loaded without exposing secret values."""

    model_config = SettingsConfigDict(
        env_prefix="ENGRAM_",
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://engram:engram@localhost:5439/engram"
    provider: str = "ollama"
    model: str = "olmo-3:7b-instruct"
    ollama_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text:v1.5"
    workspace_slug: str = "local"
    output_inline_bytes: int = Field(default=900, ge=200, le=8_000)
    action_limit: int = Field(default=8, ge=1, le=40)
    duration_limit_seconds: int = Field(default=180, ge=10, le=3_600)


@lru_cache
def get_settings() -> RuntimeSettings:
    return RuntimeSettings()
