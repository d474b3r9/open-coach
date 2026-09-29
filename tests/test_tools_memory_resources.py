"""Tests for the MCP resources in tools/memory.py (coach:// reads)."""

from __future__ import annotations

import json
from datetime import date

from open_coach.tools.memory import get_active_plan, get_archived_plan, get_coaching_context
from tests.conftest import MockStorage, make_plan, mock_ctx

# ── coach://context ───────────────────────────────────────────────────────────


class TestGetCoachingContext:
    async def test_contains_today(self):
        ctx = mock_ctx(MockStorage())
        data = json.loads(await get_coaching_context(ctx))
        assert "today" in data
        assert data["today"] == date.today().isoformat()

    async def test_today_is_valid_iso_date(self):
        ctx = mock_ctx(MockStorage())
        data = json.loads(await get_coaching_context(ctx))
        parsed = date.fromisoformat(data["today"])  # raises if invalid
        assert parsed == date.today()

    async def test_contains_day_of_week(self):
        ctx = mock_ctx(MockStorage())
        data = json.loads(await get_coaching_context(ctx))
        assert "day_of_week" in data
        assert data["day_of_week"] == date.today().strftime("%A")

    async def test_no_plan(self):
        ctx = mock_ctx(MockStorage(plan=None))
        data = json.loads(await get_coaching_context(ctx))
        assert data["active_plan"]["status"] == "no_active_plan"

    async def test_plan_includes_current_week(self):
        plan = make_plan(start_offset_days=-14, duration_weeks=8)  # started 2 weeks ago
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(await get_coaching_context(ctx))
        ap = data["active_plan"]
        assert ap["current_week"] == 3  # week 1, 2 elapsed → now in week 3

    async def test_plan_days_remaining(self):
        plan = make_plan(start_offset_days=0, duration_weeks=8)
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(await get_coaching_context(ctx))
        expected = (plan.end_date - date.today()).days
        assert data["active_plan"]["days_remaining"] == expected

    async def test_plan_days_remaining_never_negative(self):
        # Plan ended 3 days ago
        plan = make_plan(start_offset_days=-70, duration_weeks=8)
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(await get_coaching_context(ctx))
        assert data["active_plan"]["days_remaining"] == 0


# ── coach://plan/active ───────────────────────────────────────────────────────


class TestGetActivePlan:
    def test_no_plan_includes_today(self):
        ctx = mock_ctx(MockStorage(plan=None))
        data = json.loads(get_active_plan(ctx))
        assert data["status"] == "no_active_plan"
        assert data["today"] == date.today().isoformat()

    def test_plan_includes_today(self):
        plan = make_plan()
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(get_active_plan(ctx))
        assert data["today"] == date.today().isoformat()

    def test_plan_includes_day_of_week(self):
        plan = make_plan()
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(get_active_plan(ctx))
        assert data["day_of_week"] == date.today().strftime("%A")

    def test_plan_current_week_clipped_to_1(self):
        # Plan starts in the future → current_week = 1
        plan = make_plan(start_offset_days=7, duration_weeks=8)
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(get_active_plan(ctx))
        assert data["current_week"] == 1

    def test_plan_current_week_clipped_to_max(self):
        # Plan ended → current_week = len(weeks)
        plan = make_plan(start_offset_days=-100, duration_weeks=8)
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(get_active_plan(ctx))
        assert data["current_week"] == 8

    def test_plan_preserves_original_fields(self):
        plan = make_plan(name="Marathon Berlin")
        ctx = mock_ctx(MockStorage(plan=plan))
        data = json.loads(get_active_plan(ctx))
        assert data["name"] == "Marathon Berlin"
        assert "weeks" in data


# ── coach://plans/archive/{name} ──────────────────────────────────────────────


class TestGetArchivedPlan:
    def test_archived_plan_round_trips(self, storage):
        plan = make_plan(name="Old Cycle")
        plan.status = "completed"
        storage.archive_plan(plan)

        data = json.loads(get_archived_plan("old-cycle", mock_ctx(storage)))
        assert data["name"] == "Old Cycle"
        assert data["status"] == "completed"
        assert len(data["weeks"]) == 8

    def test_unknown_name_returns_error_and_available(self, storage):
        plan = make_plan(name="Old Cycle")
        storage.archive_plan(plan)

        data = json.loads(get_archived_plan("nope", mock_ctx(storage)))
        assert data["error"] == "No archived plan 'nope'"
        assert data["available"] == ["old-cycle"]
