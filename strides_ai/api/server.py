"""Entry point for the web server: strides-ai-web."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    # Validate required env vars
    provider = os.environ.get("PROVIDER", "claude").lower()
    if provider == "ollama":
        if not os.environ.get("OLLAMA_MODEL"):
            print("OLLAMA_MODEL must be set when using PROVIDER=ollama")
            sys.exit(1)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY must be set when using PROVIDER=claude (the default)")
            sys.exit(1)

    strava_ok = os.environ.get("STRAVA_CLIENT_ID") and os.environ.get("STRAVA_CLIENT_SECRET")
    if not strava_ok:
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
            for k in ("personal", "running_background", "personal_bests",
                      "goals", "injuries_and_health", "gear", "other_notes"):
                if legacy.get(k):
                    fields[k] = legacy[k]
            db.save_profile_fields("running", fields)
        except Exception:
            pass  # best-effort; no crash on parse failure

    from .app import app  # lifespan handles backend initialisation at startup

    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting Strides AI web server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
