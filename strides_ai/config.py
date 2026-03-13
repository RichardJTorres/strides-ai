"""Application-wide configuration and constants."""

from functools import lru_cache
from pathlib import Path

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

    # Strava
    strava_client_id: str = ""
    strava_client_secret: str = ""

    # Server
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ── Application constants ──────────────────────────────────────────────────────

VALID_MODES: frozenset[str] = frozenset({"running", "cycling", "hybrid"})
VALID_PROVIDERS: frozenset[str] = frozenset({"claude", "gemini", "ollama", "openai"})

UPLOADS_DIR = Path.home() / ".strides_ai" / "uploads"
SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB
