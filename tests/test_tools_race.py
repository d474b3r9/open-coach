"""Tests for the race prediction / pacing / readiness MCP tools (tools/race.py)."""

from __future__ import annotations

from open_coach.models import AthleteProfile, GoalsConfig
from open_coach.tools.race import (
    get_pacing_strategy,
    get_race_predictions,
    get_race_readiness,
)
from tests.conftest import MockStorage, make_goal, make_plan, make_profile, mock_ctx


class TestGetRacePredictions:
    async def test_no_profile_returns_error(self):
        result = await get_race_predictions(ctx=mock_ctx(storage=MockStorage()))
        assert "error" in result

    async def test_profile_without_vdot_returns_error(self):
        storage = MockStorage(profile=AthleteProfile())
        result = await get_race_predictions(ctx=mock_ctx(storage=storage))
        assert "error" in result

    async def test_happy_path_with_goal(self):
        storage = MockStorage(
            profile=make_profile(vdot=48.0),
            goals=GoalsConfig(goals=[make_goal(race_name="Autumn 10K")]),
        )
        result = await get_race_predictions(ctx=mock_ctx(storage=storage))

        assert result["vdot"] == 48.0
        assert result["goal"] == "Autumn 10K"
        assert result["fitness_context"]["ctl"] == 45.0
        assert result["fitness_context"]["tsb"] == "+5"
        labels = [p["distance"] for p in result["predictions"]]
        assert "5K" in labels
        assert "Marathon" in labels
        for p in result["predictions"]:
            assert p["pace"].endswith("/km")

    async def test_works_without_goals(self):
        storage = MockStorage(profile=make_profile(vdot=48.0, tsb=None))
        result = await get_race_predictions(ctx=mock_ctx(storage=storage))
        assert result["goal"] is None
        assert result["fitness_context"]["tsb"] == "unknown"


class TestGetPacingStrategy:
    async def test_no_profile_returns_error(self):
        result = await get_pacing_strategy(ctx=mock_ctx(storage=MockStorage()))
        assert "error" in result

    async def test_no_goal_returns_error(self):
        storage = MockStorage(profile=make_profile(vdot=48.0))
        result = await get_pacing_strategy(ctx=mock_ctx(storage=storage))
        assert "error" in result

    async def test_happy_path_uses_target_time(self):
        goal = make_goal(race_name="Autumn 10K", target_time_s=2400.0)
        storage = MockStorage(profile=make_profile(vdot=48.0), goals=GoalsConfig(goals=[goal]))
        result = await get_pacing_strategy(ctx=mock_ctx(storage=storage))

        assert result["race"] == "Autumn 10K"
        assert result["target_time"] == "40:00"
        assert len(result["splits"]) > 0
        assert result["key_guidance"]

    async def test_predicts_time_when_no_target(self):
        storage = MockStorage(
            profile=make_profile(vdot=48.0),
            goals=GoalsConfig(goals=[make_goal(race_name="Autumn 10K")]),
        )
        result = await get_pacing_strategy(ctx=mock_ctx(storage=storage))
        assert result["target_time"]  # predicted from VDOT
        assert result["strategy"]


class TestGetRaceReadiness:
    async def test_no_profile_returns_error(self):
        result = await get_race_readiness(ctx=mock_ctx(storage=MockStorage()))
        assert "error" in result

    async def test_no_goal_returns_error(self):
        storage = MockStorage(profile=make_profile(vdot=48.0))
        result = await get_race_readiness(ctx=mock_ctx(storage=storage))
        assert "error" in result

    async def test_happy_path(self):
        storage = MockStorage(
            profile=make_profile(vdot=48.0),
            goals=GoalsConfig(goals=[make_goal(race_name="Autumn 10K")]),
            plan=make_plan(),
        )
        result = await get_race_readiness(ctx=mock_ctx(storage=storage))

        assert 0.0 <= result["overall_score"] <= 1.0
        assert result["overall_status"] in ("ready", "caution", "not_ready")
        assert result["components"]
        for c in result["components"]:
            assert c["status"] in ("ready", "caution", "not_ready")
        assert isinstance(result["recommendations"], list)
