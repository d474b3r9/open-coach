"""Sport registry: the one place that knows which sport plugins exist."""

from __future__ import annotations

from typing import get_args

from open_coach.sports.base import Sport, SportKey
from open_coach.sports.running import RunningSport

_SPORTS: dict[str, Sport] = {"running": RunningSport()}

SUPPORTED_SPORTS: tuple[str, ...] = get_args(SportKey)


def get_sport(key: str) -> Sport:
    """Return the plugin for *key*; ValueError for an unknown sport."""
    try:
        return _SPORTS[key]
    except KeyError:
        raise ValueError(
            f"Unknown sport {key!r}. Supported: {', '.join(SUPPORTED_SPORTS)}"
        ) from None
