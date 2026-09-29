"""Tests for i18n.py — athlete-facing string table."""

from __future__ import annotations

import string

import pytest

from open_coach.i18n import DAY_ABBREVIATIONS, STRINGS, day_abbreviation, label, t


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


@pytest.mark.parametrize("key", sorted(STRINGS))
def test_every_key_has_both_languages_with_same_placeholders(key: str) -> None:
    entry = STRINGS[key]
    assert set(entry) == {"en", "fr"}
    assert _fields(entry["en"]) == _fields(entry["fr"])


def test_t_formats_and_selects_language() -> None:
    assert t("plan.name", "en", race="10K", weeks=12) == "10K Plan — 12 weeks"
    assert t("plan.name", "fr", race="10K", weeks=12) == "Plan 10K — 12 semaines"


def test_t_falls_back_to_english_for_unknown_language() -> None:
    assert t("md.overview", "de") == "## Overview"  # type: ignore[arg-type]


def test_t_unknown_key_raises() -> None:
    with pytest.raises(KeyError):
        t("does.not.exist")


def test_day_abbreviation() -> None:
    assert day_abbreviation(0) == "Mon"
    assert day_abbreviation(6, "fr") == "Dim"
    assert all(len(days) == 7 for days in DAY_ABBREVIATIONS.values())


def test_labels_translate_known_values_in_french_only() -> None:
    assert label("workout_type", "long_run", "fr") == "sortie longue"
    assert label("workout_type", "kiné-renfo", "fr") == "renfo"
    assert label("phase", "TAPER", "fr") == "affûtage"
    assert label("status", "abandoned", "fr") == "abandonné"
    assert label("phase", "taper", "en") == "taper"
    # custom phase names written by the coach are kept as-is
    assert label("phase", "Décharge en intensité", "fr") == "Décharge en intensité"
