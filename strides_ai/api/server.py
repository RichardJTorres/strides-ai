"""Entry point for the web server: strides-ai-web."""

import sys
from pathlib import Path

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

    # One-time migration: import profile.md as running-mode profile if not yet in DB
    profile_md = Path.home() / ".strides_ai" / "profile.md"
    if profile_md.exists() and db.get_profile_fields("running") is None:
        from ..profile import parse_legacy_profile, get_default_fields

        try:
            legacy = parse_legacy_profile(profile_md.read_text())
            fields = get_default_fields("running")
            for k in (
                "personal",
                "running_background",
                "personal_bests",
                "goals",
                "injuries_and_health",
                "gear",
                "other_notes",
            ):
                if legacy.get(k):
                    fields[k] = legacy[k]
            db.save_profile_fields("running", fields)
        except Exception:
            pass  # best-effort; no crash on parse failure

    from .app import app  # lifespan handles backend initialisation at startup

    import uvicorn

    port = settings.port
    print(f"Starting Strides AI web server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
