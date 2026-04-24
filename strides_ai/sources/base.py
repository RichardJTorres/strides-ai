"""DataSource protocol and shared exception types."""

from typing import Protocol, runtime_checkable


class ConfigurationError(Exception):
    """Source credentials or required configuration are missing."""


class AuthError(Exception):
    """Could not authenticate with the external service."""


class NoDataError(Exception):
    """No data is available for the requested activity."""


@runtime_checkable
class DataSource(Protocol):
    """Contract that every data-source implementation must satisfy."""

    def build_deep_dive_content(self, activity, backend) -> tuple[str, str]:
        """Return ``(system_prompt, user_content)`` for a deep-dive LLM call.

        Raises:
            ConfigurationError: credentials / config missing
            AuthError: could not authenticate with the external service
            NoDataError: no stream/exercise data available for this activity
            RateLimitError (analysis.RateLimitError): external API rate limit hit
        """
        ...

    def sync(self, full: bool = False) -> int:
        """Pull new activities from this source into the local DB.

        Returns the count of newly stored items.

        Raises:
            ConfigurationError: credentials / config missing
        """
        ...
