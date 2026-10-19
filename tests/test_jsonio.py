"""Coach JSON files are UTF-8 with LF on every platform; legacy cp1252 files still load."""

from __future__ import annotations

from pathlib import Path

from open_coach.jsonio import read_json_text, write_json_text
from open_coach.models import TrainingConstraints
from open_coach.storage import CoachStorage


def test_write_is_utf8_with_lf(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    write_json_text(path, '{"notes": "côtes — pas"}\r\n')
    raw = path.read_bytes()
    assert b"\r" not in raw
    assert "côtes — pas".encode() in raw


def test_read_tolerates_bom_and_crlf(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_bytes(b"\xef\xbb\xbf" + "côtes\r\nok".encode())
    assert read_json_text(path) == "côtes\nok"


def test_legacy_cp1252_file_from_an_old_windows_install_still_loads(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    storage.ensure_dirs()
    path = tmp_path / "constraints.json"
    legacy = TrainingConstraints(notes="Tendons — côtes").model_dump_json(indent=2)
    path.write_bytes(legacy.replace("\n", "\r\n").encode("cp1252"))
    loaded = storage.load_constraints()
    assert loaded is not None
    assert loaded.notes == "Tendons — côtes"
    storage.save_constraints(loaded)  # rewritten as UTF-8
    path.read_bytes().decode("utf-8")
