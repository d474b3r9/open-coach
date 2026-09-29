"""Unit tests for `scripts/setup_local.py` template selection (`--lang`)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_setup_module() -> ModuleType:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("setup_local", SCRIPTS_DIR / "setup_local.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup_local = _load_setup_module()


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_templates_exist_for_every_language(lang: str) -> None:
    for src, _dst in setup_local.build_mappings(lang):
        assert src.exists(), src


def test_default_language_is_english() -> None:
    names = [src.name for src, _dst in setup_local.build_mappings()]
    assert "athlete-profile.template.md" in names
    assert "training-journal.template.md" in names


def test_french_templates_selected_with_lang_fr() -> None:
    names = [src.name for src, _dst in setup_local.build_mappings("fr")]
    assert "athlete-profile.fr.template.md" in names
    assert "training-journal.fr.template.md" in names


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_destination_names_do_not_depend_on_language(lang: str) -> None:
    mappings = setup_local.build_mappings(lang)
    dests = {dst.relative_to(REPO_ROOT).as_posix() for _src, dst in mappings}
    assert dests == {
        ".claude/local/hooks.config.json",
        "plans/athlete-profile.md",
        "plans/training-journal.md",
    }


def test_unknown_language_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        setup_local.build_mappings("de")
