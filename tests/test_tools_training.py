"""Tests for the VDOT / zones / training-load MCP tools (tools/training.py)."""

from __future__ import annotations

from datetime import date, timedelta

from open_coach.models import AthleteProfile
from open_coach.tools.training import (
    calculate_fitness_from_race,
    get_training_load,
    get_training_zones,
)
from tests.conftest import MockStorage, StubGarmin, mock_ctx, running_profile


class TestCalculateFitnessFromRace:
    async def test_10k_result(self):
        result = await calculate_fitness_from_race(10000, 2400)  # 40:00 10K
        assert 50 < result["vdot"] < 56
        assert set(result["race_predictions"]) == {"5K", "10K", "Half", "Marathon"}
        assert set(result["training_paces"]) >= {"easy", "threshold", "interval"}

    async def test_paces_are_formatted_ranges(self):
        result = await calculate_fitness_from_race(5000, 1500)
        for value in result["training_paces"].values():
            assert value.endswith("/km")
            assert " - " in value


class TestGetTrainingZones:
    async def test_with_explicit_vdot(self):
        result = await get_training_zones(fitness=50.0, ctx=mock_ctx(storage=MockStorage()))
        assert result["vdot"] == 50.0
        assert set(result["zones"]) == {"easy", "marathon", "threshold", "interval", "repetition"}
        assert result["zones"]["easy"]["pace"] is not None

    async def test_with_race_result(self):
        result = await get_training_zones(
            race_distance_m=10000, race_time_s=2400, ctx=mock_ctx(storage=MockStorage())
        )
        assert result["vdot"] > 0

    async def test_falls_back_to_profile(self):
        storage = MockStorage(profile=running_profile(vdot=47.5))
        result = await get_training_zones(ctx=mock_ctx(storage=storage))
        assert result["vdot"] == 47.5

    async def test_no_vdot_anywhere_returns_error(self):
        result = await get_training_zones(ctx=mock_ctx(storage=MockStorage()))
        assert "error" in result

    async def test_hr_zones_merged_from_profile(self):
        storage = MockStorage(profile=running_profile(vdot=50.0, resting_hr=50, max_hr=190))
        result = await get_training_zones(ctx=mock_ctx(storage=storage))
        # Karvonen: 50 + 140 * (0.59, 0.74) → 133-154 bpm
        assert result["zones"]["easy"]["hr"] == "133-154 bpm"
        assert all(z["hr"] is not None for z in result["zones"].values())
        assert result["hr_source"] == {"resting_hr": 50, "max_hr": 190, "method": "karvonen"}
        assert "hint" not in result

    async def test_no_hr_data_gives_pace_only_with_hint(self):
        storage = MockStorage(profile=running_profile(vdot=50.0))
        result = await get_training_zones(ctx=mock_ctx(storage=storage))
        assert all(z["hr"] is None for z in result["zones"].values())
        assert all(z["pace"] is not None for z in result["zones"].values())
        assert "HR zones unavailable" in result["hint"]

    async def test_inverted_hr_degrades_to_pace_only(self):
        storage = MockStorage(profile=running_profile(vdot=50.0, resting_hr=190, max_hr=150))
        result = await get_training_zones(ctx=mock_ctx(storage=storage))
        assert all(z["hr"] is None for z in result["zones"].values())
        assert "hint" in result

    async def test_explicit_vdot_still_merges_profile_hr(self):
        storage = MockStorage(profile=AthleteProfile(resting_hr=50, max_hr=190))
        result = await get_training_zones(fitness=55.0, ctx=mock_ctx(storage=storage))
        assert result["vdot"] == 55.0
        assert result["zones"]["easy"]["hr"] is not None


class TestGetTrainingLoad:
    @staticmethod
    def _activity(days_ago: int, avg_hr=150, duration=3000.0) -> dict:
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        return {
            "startTimeLocal": f"{d} 08:00:00",
            "averageHR": avg_hr,
            "duration": duration,
        }

    async def test_no_garmin_returns_error(self):
        result = await get_training_load(ctx=mock_ctx(garmin=None))
        assert "error" in result

    async def test_no_hr_data_returns_error(self):
        garmin = StubGarmin(get_activities_by_date=[self._activity(3, avg_hr=None)])
        ctx = mock_ctx(storage=MockStorage(), garmin=garmin)
        result = await get_training_load(ctx=ctx)
        assert "error" in result

    async def test_rest_days_since_last_run_count(self):
        # Regression: the load was read on the last activity date, so 8 days of
        # rest after a hard block still showed the block's fatigue as today's.
        block = [self._activity(d, avg_hr=165, duration=4800.0) for d in range(8, 30)]
        garmin = StubGarmin(get_activities_by_date=block)
        ctx = mock_ctx(storage=MockStorage(), garmin=garmin)
        today = await get_training_load(days=60, ctx=ctx)
        assert today["as_of"] == date.today().isoformat()

        # Same block, but ending today: fatigue at its peak.
        fresh = [self._activity(d - 8, avg_hr=165, duration=4800.0) for d in range(8, 30)]
        ctx = mock_ctx(storage=MockStorage(), garmin=StubGarmin(get_activities_by_date=fresh))
        peak = await get_training_load(days=60, ctx=ctx)
        assert today["atl_fatigue"] < peak["atl_fatigue"] * 0.5
        assert today["tsb_form"] > peak["tsb_form"]

    async def test_happy_path(self):
        activities = [self._activity(d) for d in (2, 4, 7, 10, 14)]
        garmin = StubGarmin(get_activities_by_date=activities)
        profile = AthleteProfile(threshold_hr=172)
        ctx = mock_ctx(storage=MockStorage(profile=profile), garmin=garmin)
        result = await get_training_load(days=30, ctx=ctx)

        assert result["ctl_fitness"] > 0
        assert result["atl_fatigue"] > 0
        assert isinstance(result["tsb_form"], float)
        assert result["interpretation"]
        assert result["threshold_hr_used"] == 172
        assert result["activities_count"] == 5

    async def test_default_threshold_without_profile(self):
        garmin = StubGarmin(get_activities_by_date=[self._activity(2)])
        ctx = mock_ctx(storage=MockStorage(), garmin=garmin)
        result = await get_training_load(ctx=ctx)
        assert result["threshold_hr_used"] == 170

    async def test_bad_date_entries_skipped(self):
        activities = [self._activity(2), {"startTimeLocal": "", "averageHR": 150, "duration": 100}]
        garmin = StubGarmin(get_activities_by_date=activities)
        ctx = mock_ctx(storage=MockStorage(), garmin=garmin)
        result = await get_training_load(ctx=ctx)
        assert result["activities_count"] == 2  # counted raw, but load still computed
        assert result["ctl_fitness"] > 0
