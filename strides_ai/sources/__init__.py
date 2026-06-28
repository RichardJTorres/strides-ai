"""Data source registry.

Each DataSource encapsulates one external data provider (Strava, HEVY).
Register new sources via register_source(); core logic never needs to change.
"""

from .base import DataSource
from .hevy import HevySource
from .strava import StravaSource

# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, DataSource] = {}


def register_source(source: DataSource) -> DataSource:
    """Register a source by its source_name. Returns the source for chaining."""
    _REGISTRY[source.source_name] = source
    return source


def get_source(name: str) -> DataSource:
    """Look up a registered source by name. Raises ValueError for unknown names."""
    source = _REGISTRY.get(name)
    if source is None:
        raise ValueError(f"No registered data source for '{name}'")
    return source


# ── Default sources ───────────────────────────────────────────────────────────
# Named singletons are preserved so existing routers can still do:
#   from ...sources import strava_source

strava_source: StravaSource = register_source(StravaSource())
hevy_source: HevySource = register_source(HevySource())


# ── Resolution helper ─────────────────────────────────────────────────────────


def get_source_for_activity(activity) -> DataSource:
    """Return the DataSource that owns *activity*.

    Reads activity.source set by migration 007 and all new inserts.
    Falls back to 'strava' for any legacy row where source is None.
    """
    name = getattr(activity, "source", None) or "strava"
    return get_source(name)
