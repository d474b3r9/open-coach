"""Where the coach keeps its data, and how it reads its environment variables.

The project was renamed from ``garmin_coach`` to ``open_coach``. Two
compatibility shims keep existing installs working:

- ``migrate_legacy_data_dir`` moves ``~/.garmin-coach/`` to ``~/.open-coach/``
  the first time the new directory is needed (never when both exist).
- ``env`` reads ``OPEN_COACH_<NAME>`` and falls back to the legacy
  ``GARMIN_COACH_<NAME>``, logging a one-time hint to rename it.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".open-coach"
LEGACY_DATA_DIR = Path.home() / ".garmin-coach"

ENV_PREFIX = "OPEN_COACH_"
LEGACY_ENV_PREFIX = "GARMIN_COACH_"

_warned: set[str] = set()


def migrate_legacy_data_dir(new: Path | None = None, legacy: Path | None = None) -> bool:
    """Move the legacy data directory to its new name if only the legacy one exists.

    Returns True when a move happened. Never merges or overwrites: if both
    directories exist, the new one wins and the legacy one is left untouched.
    Defaults are read at call time (tests redirect them).
    """
    new = new or DATA_DIR
    legacy = legacy or LEGACY_DATA_DIR
    if new.exists() or not legacy.is_dir():
        return False
    shutil.move(str(legacy), str(new))
    logger.info("Moved coach data %s → %s", legacy, new)
    return True


def env(name: str, default: str | None = None) -> str | None:
    """``OPEN_COACH_<name>``, else the legacy ``GARMIN_COACH_<name>``, else *default*."""
    value = os.environ.get(ENV_PREFIX + name)
    if value:
        return value
    legacy = os.environ.get(LEGACY_ENV_PREFIX + name)
    if legacy:
        if name not in _warned:
            _warned.add(name)
            logger.warning(
                "%s%s is deprecated, rename it to %s%s", LEGACY_ENV_PREFIX, name, ENV_PREFIX, name
            )
        return legacy
    return default


def env_credential(name: str) -> str:
    """Return the value of env var ``name``, or ``""`` when unset or unexpanded.

    MCP hosts interpolate ``${VAR}`` placeholders from ``.mcp.json``; when the
    variable is not defined on the machine, some hosts pass the literal
    placeholder through. Treating such a value as a real credential would fire
    a vendor login with garbage on every start, and some platforms lock
    accounts for 48h+ on repeated login failures. Anything that still looks like a
    placeholder is therefore reported as unset.
    """
    value = os.environ.get(name, "").strip()
    if value.startswith("${") or value.startswith("<"):
        return ""
    return value
