"""Shared dependencies: backend lifecycle and provider utilities."""

from fastapi import FastAPI, HTTPException, Request

from .. import db
from ..backends.claude import ClaudeBackend
from ..backends.gemini import GeminiBackend
from ..backends.ollama import OllamaBackend
from ..backends.openai import OpenAIBackend
from ..coach import build_initial_history, RECALL_MESSAGES
from ..config import get_settings


def get_provider_models(provider_id: str) -> list[dict]:
    """Return available models for a provider."""
    settings = get_settings()
    if provider_id == "claude":
        return ClaudeBackend.fetch_models(settings.anthropic_api_key)
    if provider_id == "gemini":
        return GeminiBackend.fetch_models(settings.gemini_api_key)
    if provider_id == "openai":
        return OpenAIBackend.fetch_models(settings.openai_api_key)
    if provider_id == "ollama":
        return OllamaBackend.fetch_models(settings.ollama_host)
    return []


def _stored_model(provider_id: str, default: str = "") -> str:
    """Return the model stored in DB for this provider, falling back to env then default."""
    env_default = getattr(get_settings(), f"{provider_id}_model", "") or default
    return db.get_setting(f"{provider_id}_model") or env_default


def provider_statuses() -> list[dict]:
    """Return the list of providers with their configuration and active status."""
    settings = get_settings()
    current = db.get_setting("provider", settings.provider) or "claude"

    ollama_models = get_provider_models("ollama")
    ollama_configured = len(ollama_models) > 0
    ollama_default = ollama_models[0]["id"] if ollama_models else ""

    gemini_models = get_provider_models("gemini")
    gemini_default = gemini_models[0]["id"] if gemini_models else ""

    openai_models = get_provider_models("openai")
    openai_default = openai_models[0]["id"] if openai_models else ""

    return [
        {
            "id": "claude",
            "label": "Claude",
            "selected_model": _stored_model("claude"),
            "configured": bool(settings.anthropic_api_key),
            "active": current == "claude",
            "config_hint": (
                "Set ANTHROPIC_API_KEY in .env" if not settings.anthropic_api_key else None
            ),
        },
        {
            "id": "gemini",
            "label": "Gemini",
            "selected_model": _stored_model("gemini", gemini_default),
            "configured": bool(settings.gemini_api_key),
            "active": current == "gemini",
            "config_hint": ("Set GEMINI_API_KEY in .env" if not settings.gemini_api_key else None),
        },
        {
            "id": "openai",
            "label": "ChatGPT",
            "selected_model": _stored_model("openai", openai_default),
            "configured": bool(settings.openai_api_key),
            "active": current == "openai",
            "config_hint": ("Set OPENAI_API_KEY in .env" if not settings.openai_api_key else None),
        },
        {
            "id": "ollama",
            "label": "Ollama",
            "selected_model": _stored_model("ollama", ollama_default),
            "configured": ollama_configured,
            "active": current == "ollama",
            "config_hint": (
                "Start Ollama and pull at least one model" if not ollama_configured else None
            ),
        },
    ]


def init_backend(app: FastAPI, mode: str | None = None, provider: str | None = None) -> None:
    """Called at server startup (and on mode/profile/provider changes) to build the LLM backend."""
    if mode is not None:
        app.state.mode = mode
    if provider is not None:
        app.state.provider = provider
    current_mode = getattr(app.state, "mode", "running")
    settings = get_settings()
    current_provider = (getattr(app.state, "provider", None) or settings.provider).lower()

    activities = db.get_activities_for_mode(current_mode)
    prior_messages = db.get_recent_messages(RECALL_MESSAGES, mode=current_mode)
    profile_fields = db.get_profile_fields(current_mode) or {}
    weight_unit = profile_fields.get("weight_unit", "kg")
    initial_history = build_initial_history(
        activities, prior_messages, mode=current_mode, weight_unit=weight_unit
    )

    if current_provider == "ollama":
        available = get_provider_models("ollama")
        auto_default = available[0]["id"] if available else ""
        model = _stored_model("ollama", auto_default)
        app.state.backend = OllamaBackend(model, initial_history, settings.ollama_host)
    elif current_provider == "gemini":
        available = get_provider_models("gemini")
        auto_default = available[0]["id"] if available else ""
        model = _stored_model("gemini", auto_default)
        app.state.backend = GeminiBackend(settings.gemini_api_key, initial_history, model)
    elif current_provider == "openai":
        available = get_provider_models("openai")
        auto_default = available[0]["id"] if available else "gpt-4o"
        model = _stored_model("openai", auto_default)
        app.state.backend = OpenAIBackend(settings.openai_api_key, initial_history, model)
    else:
        model = _stored_model("claude")
        app.state.backend = ClaudeBackend(settings.anthropic_api_key, initial_history, model)


def get_backend(request: Request):
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="Backend not initialised")
    return backend
