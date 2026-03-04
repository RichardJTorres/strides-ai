"""Entry point: auth → sync → chat."""

import os
import sys

from dotenv import load_dotenv

from .auth import get_access_token
from .db import init_db, get_all_activities, get_recent_messages
from .sync import sync_activities
from .coach import chat, build_initial_history, RECALL_MESSAGES


def _build_backend(initial_history: list[dict]):
    provider = os.environ.get("PROVIDER", "claude").lower()

    if provider == "ollama":
        from .backends.ollama import OllamaBackend, DEFAULT_HOST
        model = os.environ.get("OLLAMA_MODEL")
        if not model:
            print("OLLAMA_MODEL must be set when using PROVIDER=ollama")
            sys.exit(1)
        host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        return OllamaBackend(model, initial_history, host)

    # Default: Claude
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY must be set when using PROVIDER=claude (the default)")
        sys.exit(1)
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    from .backends.claude import ClaudeBackend
    return ClaudeBackend(api_key, initial_history, model)


def main() -> None:
    load_dotenv()

    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET.")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    # 1. DB schema
    init_db()

    # 2. Strava auth
    print("Authenticating with Strava…")
    access_token = get_access_token(client_id, client_secret)

    # 3. Incremental sync
    print("Syncing activities…")
    new_count = sync_activities(access_token)
    if new_count:
        print(f"  {new_count} new run(s) synced.")
    else:
        print("  Already up to date.")

    # 4. Build initial history (shared across backends)
    activities = get_all_activities()
    prior_messages = get_recent_messages(RECALL_MESSAGES)
    initial_history = build_initial_history(activities, prior_messages)

    # 5. Select backend
    backend = _build_backend(initial_history)

    # 6. Chat
    chat(backend)


if __name__ == "__main__":
    main()
