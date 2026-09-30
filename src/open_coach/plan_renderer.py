"""Render a TrainingPlan to a human-readable markdown file.

Pure rendering — no I/O for the formatting itself. The `write_plan_markdown`
helper handles the file write and resolves the destination directory.

Default destination: `<repo-root>/plans/` (the repo's gitignored plans folder).
Override via env var `OPEN_COACH_PLANS_MD_DIR`.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from open_coach.i18n import DEFAULT_LANGUAGE, day_abbreviation, label, t
from open_coach.models import Language, PlannedWorkout, TrainingPlan, TrainingWeek
from open_coach.paths import env
from open_coach.sports.base import SportKey, Volume
from open_coach.sports.registry import get_sport
from open_coach.units import format_time

logger = logging.getLogger(__name__)

# Repo root = three levels up from this file (src/open_coach/plan_renderer.py)
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MD_DIR = _REPO_ROOT / "plans"


def _slugify(name: str) -> str:
    """Lowercase ASCII slug for filenames; accented letters keep their base letter."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = ascii_name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "plan"


def volume_headline(sport: SportKey, vol: Volume) -> float:
    """The sport's headline volume number: km, or hours for duration-based sports."""
    if get_sport(sport).volume_metric == "distance":
        return vol.distance_m / 1000
    return vol.duration_s / 3600


def _fmt_headline(sport: SportKey, value: float) -> str:
    if get_sport(sport).volume_metric == "distance":
        return f"{value:.0f} km"
    hours, minutes = divmod(round(value * 60), 60)
    return f"{hours}h{minutes:02d}"


def format_volume(volumes: dict[SportKey, Volume], default: SportKey) -> str:
    """One week's volume, e.g. ``42 km``; one part per sport for a multi-sport week."""
    items = volumes or {default: Volume()}
    parts = [_fmt_headline(s, volume_headline(s, v)) for s, v in items.items()]
    if len(parts) > 1:
        parts = [f"{p} {s}" for p, s in zip(parts, items, strict=True)]
    return " + ".join(parts)


def count_phases(plan: TrainingPlan) -> dict[str, int]:
    """Count weeks per phase (week.notes carries the phase name, default 'base')."""
    counts: dict[str, int] = {}
    for week in plan.weeks:
        t = week.notes or "base"
        counts[t] = counts.get(t, 0) + 1
    return counts


def _fmt_workout_row(w: PlannedWorkout, sport: SportKey, lang: Language) -> str:
    day = day_abbreviation(w.date.weekday(), lang)
    dist = f"{w.target_distance_m / 1000:.1f} km" if w.target_distance_m else "-"
    target = get_sport(sport).format_intensity(w.target_intensity) if w.target_intensity else "-"
    status = "✓" if w.completed else ("✗" if w.skipped_reason else " ")
    wtype = label("workout_type", w.workout_type, lang)
    desc = (w.description or wtype).replace("|", "\\|")
    return f"| {status} | {day} {w.date} | **{wtype}** | {dist} | {target} | {desc} |"


def _fmt_week_section(plan: TrainingPlan, week: TrainingWeek, lang: Language) -> str:
    phase = label("phase", week.notes or "base", lang).upper()
    header = t(
        "md.week_header",
        lang,
        n=week.week_number,
        phase=phase,
        start=week.start_date,
        vol=format_volume(week.planned_volume, plan.goal.sport),
    )
    if week.completion_rate > 0:
        header += t(
            "md.week_done",
            lang,
            vol=format_volume(week.actual_volume, plan.goal.sport),
            rate=week.completion_rate * 100,
        )
    rows = "\n".join(_fmt_workout_row(w, plan.sport_of(w), lang) for w in week.workouts)
    table = t("md.table_header", lang) + rows
    return f"{header}\n\n{table}\n"


def render_plan_to_markdown(plan: TrainingPlan, lang: Language = DEFAULT_LANGUAGE) -> str:
    """Render a TrainingPlan to a complete markdown document in *lang*."""
    g = plan.goal
    race_d = g.race_date.isoformat() if g.race_date else "?"
    target_t = (
        t("md.target_time", lang, time=format_time(g.target_time_s)) if g.target_time_s else ""
    )

    sports = list(dict.fromkeys(s for w in plan.weeks for s in w.planned_volume)) or [g.sport]
    per_sport = {
        s: [volume_headline(s, w.planned_volume.get(s, Volume())) for w in plan.weeks]
        for s in sports
    }

    def _join(pick: Callable[[list[float]], float]) -> str:
        parts = [(s, _fmt_headline(s, pick(v) if v else 0)) for s, v in per_sport.items()]
        return " + ".join(f"{txt} {s}" if len(parts) > 1 else txt for s, txt in parts)

    phases_str = ", ".join(
        f"{n}× {label('phase', ph, lang)}"  # noqa: RUF001
        for ph, n in count_phases(plan).items()
    )

    parts = [
        f"# {plan.name}",
        "",
        t("md.banner", lang),
        "",
        t("md.target_race", lang),
        "",
        t(
            "md.race_line",
            lang,
            race=g.race_name or t("md.default_race", lang),
            km=g.distance_m / 1000,
            priority=g.priority,
        ),
        t("md.date_line", lang, date=race_d, target=target_t),
        "",
        t("md.overview", lang),
        "",
        t("md.period", lang, start=plan.start_date, end=plan.end_date),
        t("md.weeks_total", lang, weeks=len(plan.weeks), vol=_join(sum)),
        t("md.volume", lang, start=_join(lambda v: v[0]), peak=_join(max)),
        t("md.phases", lang, phases=phases_str),
        t("md.status", lang, status=label("status", plan.status, lang)),
        "",
    ]

    if plan.outcome_notes:
        parts += [t("md.outcome_notes", lang), "", plan.outcome_notes, ""]

    parts.append(t("md.detailed_plan", lang))
    parts.extend(_fmt_week_section(plan, w, lang) for w in plan.weeks)

    parts.append("---")
    if plan.updated_at:
        parts.append(t("md.updated_at", lang, ts=plan.updated_at.isoformat(timespec="seconds")))
    elif plan.created_at:
        parts.append(t("md.created_at", lang, ts=plan.created_at.isoformat(timespec="seconds")))

    return "\n".join(parts) + "\n"


def _resolve_md_dir() -> Path:
    """Resolve the markdown destination directory.

    Priority: env var OPEN_COACH_PLANS_MD_DIR, then DEFAULT_MD_DIR (repo's plans/).
    """
    override = env("PLANS_MD_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_MD_DIR


def write_plan_markdown(
    plan: TrainingPlan, dest_dir: Path | None = None, lang: Language = DEFAULT_LANGUAGE
) -> Path:
    """Render the plan in *lang* and write it to <dest_dir>/<slug>.md.

    Returns the path to the written file. Creates the directory if missing.
    """
    out_dir = dest_dir or _resolve_md_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    race_d = plan.goal.race_date.isoformat() if plan.goal.race_date else "no-date"
    fname = f"{_slugify(plan.name)}-{race_d}.md"
    out_path = out_dir / fname
    out_path.write_text(render_plan_to_markdown(plan, lang), encoding="utf-8")
    logger.info("Wrote plan markdown to %s", out_path)
    return out_path


def plan_markdown_path(plan: TrainingPlan, dest_dir: Path | None = None) -> Path:
    """Deterministic markdown path for a plan (same naming as write_plan_markdown)."""
    out_dir = dest_dir or _resolve_md_dir()
    race_d = plan.goal.race_date.isoformat() if plan.goal.race_date else "no-date"
    return out_dir / f"{_slugify(plan.name)}-{race_d}.md"


def delete_plan_markdown(plan: TrainingPlan, dest_dir: Path | None = None) -> bool:
    """Delete the auto-generated markdown copy of a plan, if present.

    Used on rename (stale slug) and archive (JSON archive is the source of
    truth). Returns True if a file was removed.
    """
    path = plan_markdown_path(plan, dest_dir)
    if path.exists():
        path.unlink()
        logger.info("Deleted stale plan markdown %s", path)
        return True
    return False
