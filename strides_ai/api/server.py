"""Entry point for the web server: strides-ai-web."""

import sys

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    from ..config import get_settings

    settings = get_settings()

    # Validate required env vars
    provider = settings.provider.lower()
    if provider == "ollama":
        pass  # Ollama is auto-detected at runtime; no env var required
    elif provider == "gemini":
        if not settings.gemini_api_key:
            print("GEMINI_API_KEY must be set when using PROVIDER=gemini")
            sys.exit(1)
    else:
        if not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY must be set when using PROVIDER=claude (the default)")
            sys.exit(1)

    if not settings.strava_client_id or not settings.strava_client_secret:
        print("Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET.")
        sys.exit(1)

    from .. import db

    db.init_db()

    from .app import app  # lifespan handles backend initialisation at startup

    import uvicorn

    port = settings.port
    print(f"Starting Strides AI web server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
