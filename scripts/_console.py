"""Shared console helpers for the standalone scripts (stdlib only).

Windows shells default to cp1252; non-ASCII output would crash print().
Import from sibling scripts (they run with scripts/ on sys.path):

    from _console import ensure_utf8_stdout, utf8_print
"""

from __future__ import annotations

import contextlib
import io
import sys


def utf8_print(*args: object) -> None:
    """Print, degrading to ASCII on Windows cp1252 consoles."""
    text = " ".join(str(a) for a in args)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode())


def ensure_utf8_stdout() -> None:
    """Reconfigure stdout to UTF-8 when the console encoding allows it."""
    if (
        isinstance(sys.stdout, io.TextIOWrapper)
        and sys.stdout.encoding
        and sys.stdout.encoding.lower() != "utf-8"
    ):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
