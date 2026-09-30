"""Unit formatting shared by every sport."""

from __future__ import annotations


def format_time(total_seconds: float) -> str:
    """Format time as H:MM:SS or MM:SS string."""
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
