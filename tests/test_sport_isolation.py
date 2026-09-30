"""The core stays sport-agnostic: running code lives in sports/running/ only.

Pure text scans over src/open_coach (same approach as test_vendor_isolation):
- the running plugin is imported by the registry only (plus a short,
  justified allowlist);
- no public name defined by the running plugin is used in the core;
- the persisted models carry no running-specific field (pace, VDOT, km).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from open_coach import models
from open_coach.sports.base import Sport

SRC = Path(__file__).resolve().parents[1] / "src" / "open_coach"
RUNNING_DIR = SRC / "sports" / "running"

# (file, symbol) pairs the core may use, each with its reason.
ALLOWED: set[tuple[str, str]] = {
    # The registry is where plugins are wired in.
    ("sports/registry.py", "RunningSport"),
    # Resting HR is estimated from easy runs (pace > 5:00/km) until each sport
    # can flag its own easy sessions.
    ("zones.py", "RUNNING"),
    ("zones.py", "avg_pace_sec_per_km"),
    # Garmin personal-record typeIds are running distances.
    ("providers/garmin.py", "HALF_MARATHON_M"),
    ("providers/garmin.py", "MARATHON_M"),
}

_IMPORT_RE = re.compile(r"^\s*from open_coach\.sports\.running(?:\.\w+)? import (.+)$", re.M)


def _core_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if RUNNING_DIR not in p.parents]


def _running_public_names() -> set[str]:
    names: set[str] = set()
    for path in RUNNING_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.ClassDef) and not node.name.startswith("_"):
                names.add(node.name)
            elif isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and not t.id.startswith("_"):
                        names.add(t.id)
    # Generic names a sport module may also define (the Sport protocol members,
    # i18n tables): not running vocabulary.
    protocol = {n for n in dir(Sport) if not n.startswith("_")} | set(Sport.__annotations__)
    return names - protocol - {"STRINGS", "LABELS", "logger"}


def _imported_running_symbols(path: Path) -> set[str]:
    symbols: set[str] = set()
    for match in _IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
        chunk = match.group(1).strip("() ")
        symbols |= {s.strip() for s in chunk.split(",") if s.strip()}
    # Multi-line imports: read the parenthesised block.
    text = path.read_text(encoding="utf-8")
    for block in re.finditer(
        r"from open_coach\.sports\.running(?:\.\w+)? import \(([^)]*)\)", text
    ):
        symbols |= {s.strip() for s in block.group(1).replace("\n", ",").split(",") if s.strip()}
    return symbols


def test_running_plugin_is_imported_by_the_registry_only() -> None:
    offenders = []
    for path in _core_files():
        rel = path.relative_to(SRC).as_posix()
        for symbol in _imported_running_symbols(path):
            if (rel, symbol) not in ALLOWED:
                offenders.append(f"{rel}: {symbol}")
    assert offenders == [], "core imports the running plugin:\n" + "\n".join(sorted(offenders))


def test_core_uses_no_running_name() -> None:
    running_names = _running_public_names()
    offenders = []
    for path in _core_files():
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for name in sorted(used & running_names):
            if (rel, name) not in ALLOWED:
                offenders.append(f"{rel}: {name}")
    assert offenders == [], "core uses running names:\n" + "\n".join(offenders)


def test_allowlist_has_no_stale_entries() -> None:
    for rel, symbol in ALLOWED:
        assert symbol in (SRC / rel).read_text(encoding="utf-8"), (rel, symbol)


_RUNNING_FIELD_RE = re.compile(r"pace|vdot|_km\b|_km_|long_run")


def test_persisted_models_have_no_running_fields() -> None:
    offenders = []
    for name in dir(models):
        model = getattr(models, name)
        fields = getattr(model, "model_fields", None)
        if not isinstance(fields, dict) or getattr(model, "__module__", "") != models.__name__:
            continue
        offenders += [f"{name}.{f}" for f in fields if _RUNNING_FIELD_RE.search(f)]
    assert offenders == []
