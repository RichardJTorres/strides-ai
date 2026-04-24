"""Strava data source — cardio activities (runs, rides, etc.)."""

from ..analysis import (
    DEEP_DIVE_SYSTEM_PROMPT,
    DEEP_DIVE_SYSTEM_PROMPT_LOCAL,
    RateLimitError,
    build_precomputed_brief,
    condense_streams_for_deep_dive,
    fetch_activity_streams,
)
from ..auth import get_access_token
from ..config import get_settings
from ..sync import sync_activities
from .base import AuthError, ConfigurationError, NoDataError


class StravaSource:
    """DataSource implementation backed by Strava."""

    def build_deep_dive_content(self, activity, backend) -> tuple[str, str]:
        settings = get_settings()
        if not settings.strava_client_id or not settings.strava_client_secret:
            raise ConfigurationError("Strava credentials not configured")

        try:
            access_token = get_access_token(
                settings.strava_client_id, settings.strava_client_secret
            )
        except Exception as exc:
            raise AuthError(f"Could not get Strava token: {exc}") from exc

        try:
            streams = fetch_activity_streams(activity.id, access_token)
        except RateLimitError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch stream data from Strava: {exc}") from exc

        if not streams:
            raise NoDataError(
                "No stream data available for this activity (manual entry or GPS disabled)"
            )

        activity_dict = activity.model_dump()
        if backend.prefers_precomputed_brief:
            system_prompt = DEEP_DIVE_SYSTEM_PROMPT_LOCAL
            user_content = build_precomputed_brief(streams, activity_dict)
        else:
            system_prompt = DEEP_DIVE_SYSTEM_PROMPT
            user_content = condense_streams_for_deep_dive(streams, activity_dict)

        return system_prompt, user_content

    def sync(self, full: bool = False) -> int:
        settings = get_settings()
        if not settings.strava_client_id or not settings.strava_client_secret:
            raise ConfigurationError("Strava credentials not configured")

        access_token = get_access_token(settings.strava_client_id, settings.strava_client_secret)
        return sync_activities(access_token, full=full)
