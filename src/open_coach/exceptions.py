"""Custom exceptions for Open Coach (vendor-specific ones live with their provider)."""

from __future__ import annotations


class CoachError(Exception):
    """Base exception for Open Coach."""


class WatchError(CoachError):
    """Base exception for watch-platform integrations."""


class WatchAuthError(WatchError):
    """A watch platform cannot authenticate (missing or rejected credentials)."""


class StravaError(CoachError):
    """Base exception for Strava integration."""
