"""Current-form tools use today's training load, not the bootstrap snapshot.

The profile stores CTL/ATL/TSB computed at the last bootstrap. Everything
that judges *current* form recomputes them from the watch history as of
today (rest days included), and says where the numbers come from.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from open_coach.models import (
    AthleteProfile,
    GoalsConfig,
    SportProfile,
    TrainingGoal,
    TrainingPattern,
)
from open_coach.sports.base import FitnessMarker
from open_coach.sports.running import pace
from open_coach.tools._common import load_profile_live
from open_coach.tools.memory import get_coaching_context
from open_coach.tools.race import get_race_predictions
from tests.conftest import StubGarmin, mock_ctx

STALE = AthleteProfile(
    ctl=39.4,
    atl=43.1,
    tsb=-3.7,
    onboarding_complete=True,
    sports={
        "running": SportProfile(
            fitness=FitnessMarker(metric="vdot", value=48.7),
            training_pattern=TrainingPattern(
                weekly_distance_m=34_000.0,
                weekly_frequency=4.0,
                long_session_avg_distance_m=18_000.0,
                easy_intensity=pace(329.0),
                computed_at=datetime(2026, 5, 18, 13, 0),
            ),
        )
    },
)


def _runs_until(days_ago: int) -> list[dict]:
    """A hard 3-week block ending *days_ago* days ago."""
    return [
        {
            "startTimeLocal": f"{date.today() - timedelta(days=d)} 08:00:00",
            "averageHR": 165,
            "duration": 4800.0,
        }
        for d in range(days_ago, days_ago + 21)
    ]


async def test_context_training_load_is_live_and_profile_has_no_stale_load(storage) -> None:
    storage.save_profile(STALE)
    ctx = mock_ctx(storage=storage, garmin=StubGarmin(get_activities_by_date=_runs_until(8)))
    data = json.loads(await get_coaching_context(ctx))

    load = data["training_load"]
    assert load["source"] == "watch"
    assert load["as_of"] == date.today().isoformat()
    assert load["tsb"] != STALE.tsb
    assert load["tsb"] > 0  # eight rest days after the block: fresh again
    assert not {"ctl", "atl", "tsb"} & set(data["profile"])


async def test_context_falls_back_to_a_labelled_snapshot(storage) -> None:
    storage.save_profile(STALE)
    data = json.loads(await get_coaching_context(mock_ctx(storage=storage, garmin=None)))
    load = data["training_load"]
    assert load["source"] == "profile_snapshot"
    assert load["as_of"] == "2026-05-18"
    assert load["tsb"] == STALE.tsb
    assert "Stale" in load["note"]


async def test_live_profile_is_a_copy(storage) -> None:
    storage.save_profile(STALE)
    ctx = mock_ctx(storage=storage, garmin=StubGarmin(get_activities_by_date=_runs_until(0)))
    live = await load_profile_live(ctx)
    assert live is not None
    assert live.tsb != STALE.tsb
    assert storage.load_profile().tsb == STALE.tsb  # stored profile untouched


async def test_race_predictions_use_todays_form(storage) -> None:
    storage.save_profile(STALE)
    storage.save_goals(
        GoalsConfig(
            goals=[
                TrainingGoal(
                    sport="running",
                    race_name="Test",
                    distance_m=10000,
                    race_date=date.today() + timedelta(weeks=8),
                )
            ]
        )
    )
    ctx = mock_ctx(storage=storage, garmin=StubGarmin(get_activities_by_date=_runs_until(8)))
    result = await get_race_predictions(ctx=ctx)
    assert result["fitness_context"]["tsb"] != f"{STALE.tsb:+.0f}"
