"""Sport registry: the one place that knows which sport plugins exist."""

from __future__ import annotations

from open_coach.sports.base import OTHER_SPORT, Sport
from open_coach.sports.running import RunningSport

_SPORTS: dict[str, Sport] = {"running": RunningSport()}


def supported_sports() -> tuple[str, ...]:
    """Keys of the registered sports, in registration order."""
    return tuple(_SPORTS)


def is_registered(key: str) -> bool:
    return key in _SPORTS


def get_sport(key: str) -> Sport:
    """Return the plugin for *key*; ValueError for an unknown sport."""
    try:
        return _SPORTS[key]
    except KeyError:
        raise ValueError(
            f"Unknown sport {key!r}. Supported: {', '.join(supported_sports())}"
        ) from None


def register_sport(sport: Sport) -> None:
    """Register a sport plugin (``sport.key`` must be new and not ``other``)."""
    if sport.key == OTHER_SPORT or sport.key in _SPORTS:
        raise ValueError(f"Sport key {sport.key!r} is reserved or already registered")
    _SPORTS[sport.key] = sport


def unregister_sport(key: str) -> None:
    """Remove a sport plugin (tests only: the built-in sports stay registered)."""
    _SPORTS.pop(key, None)
