"""Compatibility shims for the garmin_coach → open_coach rename."""

from __future__ import annotations

import logging

from open_coach import paths


def test_migration_moves_the_legacy_dir(tmp_path) -> None:
    legacy, new = tmp_path / ".garmin-coach", tmp_path / ".open-coach"
    (legacy / "plans").mkdir(parents=True)
    (legacy / "profile.json").write_text("{}")
    assert paths.migrate_legacy_data_dir(new, legacy) is True
    assert (new / "profile.json").read_text() == "{}"
    assert (new / "plans").is_dir()
    assert not legacy.exists()


def test_migration_never_overwrites_an_existing_new_dir(tmp_path) -> None:
    legacy, new = tmp_path / ".garmin-coach", tmp_path / ".open-coach"
    legacy.mkdir()
    (legacy / "profile.json").write_text("old")
    new.mkdir()
    assert paths.migrate_legacy_data_dir(new, legacy) is False
    assert (legacy / "profile.json").read_text() == "old"


def test_migration_noop_without_legacy_dir(tmp_path) -> None:
    assert paths.migrate_legacy_data_dir(tmp_path / "new", tmp_path / "missing") is False
    assert not (tmp_path / "new").exists()


def test_default_storage_migrates_on_first_use(monkeypatch, tmp_path) -> None:
    import open_coach.storage as storage_mod

    legacy, new = tmp_path / ".garmin-coach", tmp_path / ".open-coach"
    legacy.mkdir()
    (legacy / "goals.json").write_text("{}")
    monkeypatch.setattr(paths, "DATA_DIR", new)
    monkeypatch.setattr(paths, "LEGACY_DATA_DIR", legacy)
    monkeypatch.setattr(storage_mod, "DEFAULT_COACH_DIR", new)
    s = storage_mod.CoachStorage()
    assert s.base_dir == new
    assert (new / "goals.json").exists()


def test_env_prefers_new_name(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_COACH_WATCH", "garmin")
    monkeypatch.setenv("GARMIN_COACH_WATCH", "coros")
    assert paths.env("WATCH") == "garmin"


def test_env_falls_back_to_legacy_name_with_a_hint(monkeypatch, caplog) -> None:
    monkeypatch.delenv("OPEN_COACH_PLANS_MD_DIR", raising=False)
    monkeypatch.setenv("GARMIN_COACH_PLANS_MD_DIR", "/tmp/x")
    paths._warned.discard("PLANS_MD_DIR")
    with caplog.at_level(logging.WARNING):
        assert paths.env("PLANS_MD_DIR") == "/tmp/x"
    assert "rename it to OPEN_COACH_PLANS_MD_DIR" in caplog.text


def test_env_default(monkeypatch) -> None:
    monkeypatch.delenv("OPEN_COACH_NOPE", raising=False)
    monkeypatch.delenv("GARMIN_COACH_NOPE", raising=False)
    assert paths.env("NOPE", "d") == "d"
