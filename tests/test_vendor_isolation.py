"""Vendor knowledge stays inside its provider modules.

Garmin code lives in ``providers/garmin*.py``. Anywhere else, the word
"garmin" may only appear on the few lines listed below (provider registry,
legacy names kept for compatibility, a Garmin-only purge caveat). A new
mention in generic code fails this test: route it through the provider or,
if it is genuinely needed, add it here with the reason.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "open_coach"

VENDOR_FILES = re.compile(r"^providers/garmin[a-z_]*\.py$")

# (relative path, substring of the allowed line) — why it is allowed
ALLOWED_LINES = {
    ("providers/__init__.py", '_PROVIDER_MODULES = {"garmin": "open_coach.providers.garmin"}'),
    ("providers/__init__.py", 'DEFAULT_WATCH = "garmin"'),
    ("providers/__init__.py", "``garmin``, the only provider implemented so far"),
    ("providers/__init__.py", "(lower-cased, default ``garmin``)"),
    # legacy names of the garmin_coach → open_coach rename
    ("paths.py", "garmin"),
    ("storage.py", "First run after the garmin_coach → open_coach rename."),
    ("models.py", 'profile.json files written before the watch-provider layer say "garmin_pr"'),
    ("models.py", 'return "platform_pr" if value == "garmin_pr" else value'),
    ("models.py", 'provider: str = "garmin"  # WatchProvider.name; older registries'),
    # purge_watch_workouts documents a Garmin-only limitation (ATP plans)
    ("tools/workout.py", "on Garmin, ATP plan workouts (Garmin Coach auto-plans"),
    ("tools/workout.py", "(Garmin returns 400). To remove them, stop the active plan in"),
    ("tools/workout.py", "Garmin Connect web (Plus → Coaching → end plan)."),
}


def _generic_lines_mentioning_garmin() -> list[str]:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if VENDOR_FILES.match(rel):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "garmin" not in line.lower():
                continue
            if any(rel == f and sub.lower() in line.lower() for f, sub in ALLOWED_LINES):
                continue
            offenders.append(f"{rel}:{n}: {line.strip()}")
    return offenders


def test_no_garmin_in_generic_code() -> None:
    assert _generic_lines_mentioning_garmin() == []


def test_garminconnect_is_imported_by_garmin_modules_only() -> None:
    importers = sorted(
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if re.search(r"^\s*(from|import) garminconnect", path.read_text(encoding="utf-8"), re.M)
    )
    assert importers
    assert all(VENDOR_FILES.match(rel) for rel in importers), importers


def test_allowlist_has_no_stale_entries() -> None:
    # Every allowed line must still exist, so the list cannot silently rot.
    for rel, sub in ALLOWED_LINES:
        text = (SRC / rel).read_text(encoding="utf-8")
        assert sub in text, (rel, sub)


# Vendor payloads use camelCase keys (workoutId, summaryDTO, averageHR…); the
# neutral models use snake_case. Reading a camelCase key outside providers/
# means a tool is parsing a vendor payload itself.
_CAMEL_KEY_READ = re.compile(r"""(\.get\(|\[)["'][a-z]+[A-Z][A-Za-z]*["']""")


def test_no_vendor_payload_parsing_outside_providers() -> None:
    offenders = [
        f"{path.relative_to(SRC).as_posix()}:{n}: {line.strip()}"
        for path in sorted(SRC.rglob("*.py"))
        if not path.relative_to(SRC).as_posix().startswith("providers/")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _CAMEL_KEY_READ.search(line)
    ]
    assert offenders == []
