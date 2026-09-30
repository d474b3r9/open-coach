"""Running session strings (EN/FR), registered into ``open_coach.i18n`` on load."""

from __future__ import annotations

from open_coach.i18n import register
from open_coach.models import Language

STRINGS: dict[str, dict[Language, str]] = {
    "wo.long_run": {
        "en": "Long run {km:.0f}km @ easy pace ({pace})",
        "fr": "Sortie longue {km:.0f}km @ allure facile ({pace})",
    },
    "wo.easy": {"en": "Easy run {km:.0f}km @ {pace}", "fr": "Sortie facile {km:.0f}km @ {pace}"},
    "wo.recovery": {
        "en": "Recovery jog {km:.0f}km very easy",
        "fr": "Footing récup {km:.0f}km très facile",
    },
    # Session strings must stay parsable by plan_to_dsl (sync_upcoming_workouts
    # pushes them): tempo uses the "incl."/"dont" embedded-block form, intervals
    # an NxD set with an "r"/"rec" recovery.
    "wo.tempo": {
        "en": (
            "Tempo {total:.1f}km incl. {km:.1f}km @ threshold ({pace}), 2km warmup, 1.5km cooldown"
        ),
        "fr": (
            "Tempo {total:.1f}km dont {km:.1f}km @ seuil ({pace}),"
            " échauffement 2km, retour au calme 1.5km"
        ),
    },
    "wo.intervals": {
        "en": "Intervals: 2km warmup + {reps}x1km @ {pace} rec 400m jog + 1.5km cooldown",
        "fr": (
            "Fractionné : échauffement 2km + {reps}x1km @ {pace} r 400m trot"
            " + retour au calme 1.5km"
        ),
    },
    "wo.fallback": {"en": "Run {km:.0f}km", "fr": "Sortie {km:.0f}km"},
    "wo.race": {
        "en": "Race: {race} {km:.1f}km @ {pace}",
        "fr": "Course : {race} {km:.1f}km @ {pace}",
    },
}

LABELS: dict[str, dict[str, str]] = {
    "workout_type": {
        "easy": "footing",
        "long_run": "sortie longue",
        "recovery": "récup",
        "tempo": "tempo",
        "interval": "fractionné",
        "intervals": "fractionné",
        "fartlek": "fartlek",
        "race": "course",
    },
}

register(STRINGS, LABELS)
