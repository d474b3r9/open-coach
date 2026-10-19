"""Cross-platform text I/O for the coach's JSON files.

``Path.read_text()`` / ``write_text()`` use the locale encoding: cp1252 on a
Windows console, UTF-8 on Linux and macOS. A file written on one and read on
the other is then corrupt or unreadable as soon as it holds an accent or a
dash. Every coach file is therefore written as UTF-8 with ``\\n`` line endings,
and read leniently (BOM tolerated, legacy cp1252 files still load).
"""

from __future__ import annotations

from pathlib import Path


def read_json_text(path: Path) -> str:
    """File text as ``str`` with ``\\n`` newlines: UTF-8 first, legacy cp1252 as fallback."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n")


def write_json_text(path: Path, text: str) -> None:
    """Write *text* as UTF-8 with ``\\n`` line endings (never the platform default)."""
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
