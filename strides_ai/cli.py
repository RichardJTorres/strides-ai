"""Entry point: auth → sync → chat."""

import os
import sys

from dotenv import load_dotenv

from .auth import get_access_token
from .db import init_db
from .sync import sync_activities
from .coach import chat


def main() -> None:
    load_dotenv()

    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    missing = [
        name
        for name, val in [
            ("STRAVA_CLIENT_ID", client_id),
            ("STRAVA_CLIENT_SECRET", client_secret),
            ("ANTHROPIC_API_KEY", anthropic_key),
        ]
        if not val
    ]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    # 1. Ensure DB schema exists
    init_db()

    # 2. Authenticate with Strava (no-op if token is valid)
    print("Authenticating with Strava…")
    access_token = get_access_token(client_id, client_secret)

    # 3. Incremental sync on every startup
    print("Syncing activities…")
    new_count = sync_activities(access_token)
    if new_count:
        print(f"  {new_count} new run(s) synced.")
    else:
        print("  Already up to date.")

    # 4. Launch chat
    chat(anthropic_key)


if __name__ == "__main__":
    main()
