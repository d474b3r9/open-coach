"""Anti-regression test for hand-edited VDOT/pace tables in plan markdown.

Plan markdowns may include human-readable tables that map VDOT values to
predicted race times and paces. Hand-edited tables tend to drift from the
Daniels-Gilbert truth values — a single hardcoded row that disagrees with
`vdot.py` by a few seconds per km can propagate through multiple retargets
before anyone catches it.

The test runs against committed fixtures in `tests/data/` (hermetic —
identical on CI and locally, never dependent on the developer's gitignored
`plans/` directory). The fixture values were generated from `vdot.py`, so a
failure means either the fixture was hand-edited incorrectly or `vdot.py`
output drifted.

This test parses any markdown table whose header contains "VDOT" + at least
one of (5K, 10K, Half, Semi, Marathon — English or French headers), extracts
each non-header row, and compares every race-time and pace cell against `predict_time` from vdot.py.

Tolerance:
- Race time: ±10 s (covers rounding and the small Daniels chart-vs-formula
  variation Daniels himself acknowledges in Running Formula 4e)
- Pace per km: ±3 s/km

A failing test points to a markdown row that must be reauthored from the
formula, not a bug in vdot.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from open_coach.vdot import predict_time

FIXTURES_DIR = Path(__file__).resolve().parent / "data"

# Column header → (kind, distance_m or None for pace columns, optional distance for paces)
# 'time' columns hold m:ss or h:mm:ss race totals; 'pace' columns hold m:ss /km.
_DISTANCE_M = {
    "5k": 5000.0,
    "10k": 10000.0,
    "semi": 21097.5,
    "half": 21097.5,
    "half marathon": 21097.5,
    "marathon": 42195.0,
}

_TIME_TOLERANCE_S = 10.0
_PACE_TOLERANCE_S = 3.0


def _strip_markdown(cell: str) -> str:
    """Drop bold/emoji decoration so the numeric core is testable."""
    cell = cell.strip()
    cell = re.sub(r"\*\*([^*]+)\*\*", r"\1", cell)
    cell = cell.replace("🎯", "").strip()
    return cell


def _parse_time(cell: str) -> float | None:
    """Parse m:ss or h:mm:ss into seconds. Returns None if no time found."""
    cell = _strip_markdown(cell)
    # accept embedded annotations like "42:16" inside "1:33:37"
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", cell)
    if not m:
        return None
    a, b, c = m.groups()
    if c is None:
        # m:ss
        return int(a) * 60 + int(b)
    return int(a) * 3600 + int(b) * 60 + int(c)


def _parse_pace(cell: str) -> float | None:
    """Parse pace strings like '4:13/km' or '4:13' into sec/km."""
    cell = _strip_markdown(cell)
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", cell)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _parse_vdot(cell: str) -> float | None:
    """Extract leading VDOT number from cells like '49 (target)', '**48.7 (current)**'."""
    cell = _strip_markdown(cell)
    m = re.match(r"\s*(\d+(?:\.\d+)?)", cell)
    if not m:
        return None
    return float(m.group(1))


def _classify_column(header: str) -> tuple[str, float] | None:
    """Map a column header to either ('time', distance_m), ('pace', distance_m), or None."""
    h = _strip_markdown(header).lower().strip()
    # Pace columns mention 'pace', 'allure' (French) or '/km'
    is_pace = "allure" in h or "/km" in h or h.startswith("pace")
    for keyword, dist in _DISTANCE_M.items():
        if keyword in h:
            return ("pace" if is_pace else "time", dist)
    return None


def _find_vdot_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return (header_cells, list_of_data_rows) for every markdown table whose
    header row contains 'VDOT' plus at least one race-distance keyword."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and "VDOT" in line:
            # candidate header
            header = [c.strip() for c in line.strip("|").split("|")]
            # next line must be the separator
            if i + 1 < len(lines) and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[i + 1]):
                rows: list[list[str]] = []
                j = i + 2
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    row = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                    if len(row) == len(header):
                        rows.append(row)
                    j += 1
                # only keep if at least one column maps to a distance
                if any(_classify_column(h) for h in header):
                    tables.append((header, rows))
                i = j
                continue
        i += 1
    return tables


def _expected(kind: str, vdot: float, distance_m: float) -> float:
    """Compute the expected time (s) or pace (s/km) at this VDOT and distance."""
    t = predict_time(vdot, distance_m)
    if kind == "time":
        return t
    return t / (distance_m / 1000.0)


def _format_check_failures(plan_path: Path) -> list[str]:
    text = plan_path.read_text(encoding="utf-8")
    errors: list[str] = []
    for header, rows in _find_vdot_tables(text):
        # Map column index → (kind, distance)
        col_meta: dict[int, tuple[str, float]] = {}
        vdot_idx: int | None = None
        for idx, h in enumerate(header):
            if "VDOT" in h.upper():
                vdot_idx = idx
                continue
            cls = _classify_column(h)
            if cls is not None:
                col_meta[idx] = cls
        if vdot_idx is None or not col_meta:
            continue

        for row in rows:
            vdot = _parse_vdot(row[vdot_idx])
            if vdot is None:
                continue
            for idx, (kind, dist) in col_meta.items():
                cell = row[idx]
                if kind == "time":
                    got = _parse_time(cell)
                    tol = _TIME_TOLERANCE_S
                else:
                    got = _parse_pace(cell)
                    tol = _PACE_TOLERANCE_S
                if got is None:
                    continue
                want = _expected(kind, vdot, dist)
                if abs(got - want) > tol:
                    errors.append(
                        f"{plan_path.name}: VDOT {vdot} | col={header[idx]!r} "
                        f"({kind} {int(dist)}m) | got={cell!r} ({got:.1f}s) "
                        f"vs vdot.py={want:.1f}s | diff={got - want:+.1f}s "
                        f"(tol ±{tol:.0f})"
                    )
    return errors


def test_fixtures_present() -> None:
    """The hermetic fixture set must never silently shrink to zero files."""
    assert sorted(FIXTURES_DIR.glob("*.md")), f"No markdown fixtures found in {FIXTURES_DIR}"


@pytest.mark.parametrize(
    "plan_path",
    sorted(FIXTURES_DIR.glob("*.md")),
    ids=lambda p: p.name,
)
def test_vdot_table_matches_daniels(plan_path: Path) -> None:
    """Every VDOT row in every fixture markdown must match `vdot.py` predictions."""
    errors = _format_check_failures(plan_path)
    assert not errors, "VDOT table drift:\n  " + "\n  ".join(errors)


def test_checker_detects_drift(tmp_path: Path) -> None:
    """The table checker must flag a row that disagrees with `vdot.py`."""
    bad = tmp_path / "bad_table.md"
    bad.write_text(
        "| VDOT | 10K | Allure 10K |\n"  # French pace header must be recognised too
        "|------|------|------------|\n"
        "| 50 | 45:00 | 4:30/km |\n",  # truth is 41:19 / 4:07 per km
        encoding="utf-8",
    )
    errors = _format_check_failures(bad)
    assert len(errors) == 2, f"Expected 2 drift errors (time + pace), got: {errors}"
    assert all("VDOT 50" in e for e in errors)


def test_checker_ignores_tables_within_tolerance(tmp_path: Path) -> None:
    """Rows within tolerance (±10 s time, ±3 s/km pace) must not be flagged."""
    ok = tmp_path / "ok_table.md"
    ok.write_text(
        "| VDOT | 10K | Pace 10K |\n"
        "|------|------|------------|\n"
        "| 50 | 41:15 | 4:09/km |\n",  # truth 41:19 / 4:07 — inside tolerance
        encoding="utf-8",
    )
    assert _format_check_failures(ok) == []
