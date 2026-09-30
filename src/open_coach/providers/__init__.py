"""Watch providers: the platforms the coach reads activities from and pushes workouts to.

Each provider lives in its own module and exposes two module-level names:

- ``connect() -> WatchProvider | None`` — authenticate, or return None (offline);
- ``NOT_CONNECTED`` — the message tools return when ``connect()`` gave None.

``create_provider`` picks the module from ``OPEN_COACH_WATCH`` (default
``garmin``, the only provider implemented so far). This module knows the
provider names only, never a vendor SDK.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType

from open_coach.paths import env
from open_coach.providers.base import (
    Activity,
    ActivityDetail,
    DailyHeartRate,
    RecoverySignals,
    WatchProvider,
    WatchWorkout,
)

logger = logging.getLogger(__name__)

# watch name → module implementing it
_PROVIDER_MODULES = {"garmin": "open_coach.providers.garmin"}
SUPPORTED_WATCHES = tuple(_PROVIDER_MODULES)
DEFAULT_WATCH = "garmin"

__all__ = [
    "DEFAULT_WATCH",
    "SUPPORTED_WATCHES",
    "Activity",
    "ActivityDetail",
    "DailyHeartRate",
    "RecoverySignals",
    "WatchProvider",
    "WatchWorkout",
    "configured_watch",
    "create_provider",
    "not_connected_message",
]


def configured_watch() -> str:
    """Watch name selected by the environment (lower-cased, default ``garmin``)."""
    return (env("WATCH") or "").strip().lower() or DEFAULT_WATCH


def _module(watch: str) -> ModuleType | None:
    path = _PROVIDER_MODULES.get(watch)
    return importlib.import_module(path) if path else None


def create_provider() -> WatchProvider | None:
    """Connect to the configured watch platform; None when offline or misconfigured."""
    watch = configured_watch()
    module = _module(watch)
    if module is None:
        logger.warning(
            "Watch %r is not supported (choose from %s) — running offline.",
            watch,
            ", ".join(SUPPORTED_WATCHES),
        )
        return None
    provider: WatchProvider | None = module.connect()
    return provider


def not_connected_message() -> str:
    """What tools answer when no provider is connected, for the configured watch."""
    watch = configured_watch()
    module = _module(watch)
    if module is None:
        return f"Watch {watch!r} is not supported. Supported: {', '.join(SUPPORTED_WATCHES)}."
    message: str = module.NOT_CONNECTED
    return message
