"""Entry point: auth → sync → chat."""

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv

from .auth import get_access_token
from .db import init_db, get_all_activities, get_recent_messages
from .sync import sync_activities
from .coach import chat, build_initial_history, RECALL_MESSAGES
from .profile import PROFILE_PATH, ensure_profile_file, load_profile


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


def _open_editor(path) -> None:
    """Open a file in $EDITOR, falling back to common editors."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        for fallback in ("nano", "vim", "vi", "notepad.exe"):
            if subprocess.run(["which", fallback], capture_output=True).returncode == 0:
                editor = fallback
                break
    if editor:
        subprocess.run([editor, str(path)])
    else:
        print(f"Could not find an editor. Open this file manually:\n  {path}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="strides-ai")
    parser.add_argument(
        "--setup-profile",
        action="store_true",
        help="Open your athlete profile file for editing, then exit.",
    )
    args = parser.parse_args()

    # DB schema (needed even for --setup-profile so the dir exists)
    init_db()

    # ── Profile handling ──────────────────────────────────────────────────────
    newly_created = ensure_profile_file()

    if args.setup_profile or newly_created:
        if newly_created:
            print(f"\nWelcome! A profile template has been created at:\n  {PROFILE_PATH}")
            print("Fill it in so your coach knows about you.\n")
        else:
            print(f"\nOpening your athlete profile:\n  {PROFILE_PATH}\n")
        _open_editor(PROFILE_PATH)
        if args.setup_profile:
            print("Profile saved. Run strides-ai to start coaching.")
            return
        # After a first-run edit, continue into the app

    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET.")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    # Strava auth
    print("Authenticating with Strava…")
    access_token = get_access_token(client_id, client_secret)

    # Incremental sync
    print("Syncing activities…")
    new_count = sync_activities(access_token)
    if new_count:
        print(f"  {new_count} new run(s) synced.")
    else:
        print("  Already up to date.")

    # Build initial history
    activities = get_all_activities()
    prior_messages = get_recent_messages(RECALL_MESSAGES)
    initial_history = build_initial_history(activities, prior_messages)

    # Select backend
    backend = _build_backend(initial_history)

    # Load profile
    profile = load_profile()

    # Chat
    chat(backend, profile)


if __name__ == "__main__":
    main()
