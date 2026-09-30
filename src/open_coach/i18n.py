"""Athlete-facing strings for the text the coach generates itself.

Pure lookup, no I/O. Covers only text produced by code (plan markdown copies,
generated session descriptions, plan names). The conversation language is the
LLM's job and never goes through this module.

Keep both languages in the same entry so a missing translation is visible in
review. An unknown language or missing key falls back to English. Sport
plugins add their own session strings through ``register`` (running:
``sports/running/i18n.py``).
"""

from __future__ import annotations

from open_coach.models import Language

DEFAULT_LANGUAGE: Language = "en"

DAY_ABBREVIATIONS: dict[Language, list[str]] = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "fr": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"],
}

STRINGS: dict[str, dict[Language, str]] = {
    # ── plan markdown (plan_renderer) ──
    "md.banner": {
        "en": (
            "> Auto-generated plan — local copy of `~/.open-coach/plans/active.json`. "
            "Regenerated on every `generate_training_plan` or `update_workout_completion` call."
        ),
        "fr": (
            "> Plan généré automatiquement — copie locale de `~/.open-coach/plans/active.json`. "
            "Régénéré à chaque appel à `generate_training_plan` ou `update_workout_completion`."
        ),
    },
    "md.target_race": {"en": "## Target race", "fr": "## Course cible"},
    "md.default_race": {"en": "Race", "fr": "Course"},
    "md.race_line": {
        "en": "- **{race}** — {km:.1f} km — priority {priority}",
        "fr": "- **{race}** — {km:.1f} km — priorité {priority}",
    },
    "md.date_line": {"en": "- Date: **{date}**{target}", "fr": "- Date : **{date}**{target}"},
    "md.target_time": {"en": " — target {time}", "fr": " — cible {time}"},
    "md.overview": {"en": "## Overview", "fr": "## Vue d'ensemble"},
    "md.period": {"en": "- Period: **{start} → {end}**", "fr": "- Période : **{start} → {end}**"},
    "md.weeks_total": {
        "en": "- {weeks} weeks, {vol} total",
        "fr": "- {weeks} semaines, {vol} cumulés",
    },
    "md.volume": {
        "en": "- Volume: start **{start}/wk**, peak **{peak}/wk**",
        "fr": "- Volume : début **{start}/sem**, pic **{peak}/sem**",
    },
    "md.phases": {"en": "- Phases: {phases}", "fr": "- Phases : {phases}"},
    "md.status": {"en": "- Status: `{status}`", "fr": "- Statut : `{status}`"},
    "md.outcome_notes": {"en": "## Outcome notes", "fr": "## Notes d'issue"},
    "md.detailed_plan": {"en": "## Detailed plan\n", "fr": "## Plan détaillé\n"},
    "md.updated_at": {"en": "*Last updated: {ts}*", "fr": "*Dernière mise à jour : {ts}*"},
    "md.created_at": {"en": "*Created: {ts}*", "fr": "*Créé le : {ts}*"},
    "md.week_header": {
        "en": "### Wk {n} — {phase} ({start}) — {vol} planned",
        "fr": "### Sem {n} — {phase} ({start}) — {vol} prévus",
    },
    "md.week_done": {
        "en": "  — *done: {vol}, rate {rate:.0f}%*",
        "fr": "  — *réalisé : {vol}, taux {rate:.0f}%*",
    },
    "md.table_header": {
        "en": (
            "| ✓ | Day | Type | Distance | Target | Details |\n"
            "|---|-----|------|----------|--------|---------|\n"
        ),
        "fr": (
            "| ✓ | Jour | Type | Distance | Cible | Détail |\n"
            "|---|------|------|----------|-------|--------|\n"
        ),
    },
    # ── generated plans (sport plan builders; sessions come from each sport) ──
    "plan.name": {"en": "{race} Plan — {weeks} weeks", "fr": "Plan {race} — {weeks} semaines"},
}


# Display labels for internal enum values (workout types, week phases, plan
# status). Only French differs: English output shows the raw keys, as before.
# Unknown keys (e.g. a custom phase name in week.notes) are shown unchanged.
LABELS: dict[str, dict[str, str]] = {
    "workout_type": {
        "rest": "repos",
        "strength": "renfo",
        "kine-renfo": "renfo",
        "kiné-renfo": "renfo",
        "cross_training": "sport croisé",
    },
    "phase": {
        "base": "base",
        "build": "développement",
        "peak": "pic",
        "taper": "affûtage",
        "recovery": "récupération",
    },
    "status": {
        "active": "actif",
        "completed": "terminé",
        "abandoned": "abandonné",
    },
}


def register(strings: dict[str, dict[Language, str]], labels: dict[str, dict[str, str]]) -> None:
    """Add a sport plugin's strings and labels (called once when the plugin loads)."""
    for key in strings:
        if key in STRINGS:
            raise ValueError(f"i18n key {key!r} is already registered")
    STRINGS.update(strings)
    for kind, entries in labels.items():
        LABELS.setdefault(kind, {}).update(entries)


def label(kind: str, key: str, lang: Language = DEFAULT_LANGUAGE) -> str:
    """Display label for an internal value (``label("phase", "taper", "fr")`` → ``affûtage``)."""
    if lang != "fr":
        return key
    return LABELS[kind].get(key.lower(), key)


def t(key: str, lang: Language = DEFAULT_LANGUAGE, **kwargs: object) -> str:
    """Translated string for *key* in *lang*, formatted with *kwargs*.

    Falls back to English when *lang* has no entry for *key*. An unknown key
    raises ``KeyError`` — that is a programming error, not a data issue.
    """
    entry = STRINGS[key]
    template = entry.get(lang) or entry[DEFAULT_LANGUAGE]
    return template.format(**kwargs) if kwargs else template


def day_abbreviation(weekday: int, lang: Language = DEFAULT_LANGUAGE) -> str:
    """Short day name for ``date.weekday()`` (0 = Monday)."""
    return DAY_ABBREVIATIONS.get(lang, DAY_ABBREVIATIONS[DEFAULT_LANGUAGE])[weekday]
