"""Application-wide configuration and constants."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM providers
    provider: str = "claude"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    gemini_model: str = ""
    openai_model: str = ""
    ollama_model: str = ""
    ollama_host: str = "http://localhost:11434"

    # How hard the model thinks on chat turns: off | low | medium | high. Each provider maps it to
    # the setting its model takes (backends/model_profile.py). Thinking counts against the
    # per-round output cap. CLAUDE_THINKING_EFFORT is the older name for the same setting.
    thinking_effort: Literal["off", "low", "medium", "high"] = Field(
        "medium", validation_alias=AliasChoices("thinking_effort", "claude_thinking_effort")
    )

    # JSON overrides keyed by default, provider, or provider/model label. They may raise or lower
    # the limits derived from the model (budget.Limits); a value past what the model supports is
    # clamped with a warning. The older key names (output_tokens, rounds, ...) still work.
    chat_limits: dict[str, dict[str, int | float]] = {}

    @field_validator("chat_limits")
    @classmethod
    def _chat_limits_are_valid(cls, value):
        from .budget import normalize_limits

        for layer in value.values():
            normalize_limits(layer)  # raises on an unknown key or a bad value
        return value

    # Strava
    strava_client_id: str = ""
    strava_client_secret: str = ""

    # HEVY
    hevy_api_key: str = ""

    # Server
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ── Application constants ──────────────────────────────────────────────────────

VALID_MODES: frozenset[str] = frozenset({"running", "cycling", "hybrid", "lifting"})
VALID_PROVIDERS: frozenset[str] = frozenset({"claude", "gemini", "ollama", "openai"})

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("STRIDES_DATA_DIR", Path.home() / ".strides_ai")).expanduser()
UPLOADS_DIR = DATA_DIR / "uploads"
SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB
