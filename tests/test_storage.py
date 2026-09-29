"""Tests for CoachStorage persistence layer."""

import json
from datetime import date, timedelta

import pytest

from open_coach.models import (
    ActivitySummary,
    AthleteProfile,
    GoalsConfig,
    TrainingConstraints,
    TrainingGoal,
    TrainingPlan,
    WorkoutFeedback,
)


class TestEnsureDirs:
    def test_creates_directories(self, storage):
        assert storage.base_dir.exists()
        assert (storage.base_dir / "feedback").exists()
        assert (storage.base_dir / "plans" / "archive").exists()
        assert (storage.base_dir / "activity_cache").exists()


class TestProfile:
    def test_load_nonexistent(self, storage):
        assert storage.load_profile() is None

    def test_save_and_load(self, storage):
        profile = AthleteProfile(vdot=50.0, max_hr=190, resting_hr=50)
        storage.save_profile(profile)

        loaded = storage.load_profile()
        assert loaded is not None
        assert loaded.vdot == 50.0
        assert loaded.max_hr == 190
        assert loaded.updated_at is not None


class TestGoals:
    def test_load_nonexistent(self, storage):
        assert storage.load_goals() is None

    def test_save_and_load(self, storage):
        goals = GoalsConfig(
            goals=[TrainingGoal(race_name="Semi Paris", distance_m=21097.5, priority="A")]
        )
        storage.save_goals(goals)

        loaded = storage.load_goals()
        assert loaded is not None
        assert len(loaded.goals) == 1
        assert loaded.goals[0].race_name == "Semi Paris"


class TestConstraints:
    def test_save_and_load(self, storage):
        constraints = TrainingConstraints(
            available_days=["monday", "wednesday", "friday", "sunday"],
            max_sessions_per_week=4,
        )
        storage.save_constraints(constraints)

        loaded = storage.load_constraints()
        assert loaded is not None
        assert loaded.max_sessions_per_week == 4
        assert "friday" in loaded.available_days


class TestFeedback:
    def test_load_empty(self, storage):
        log = storage.load_feedback()
        assert len(log.entries) == 0

    def test_append_and_load(self, storage):
        entry = WorkoutFeedback(
            date=date(2026, 4, 1),
            workout_type="tempo",
            perceived_effort="hard",
            feeling="tired",
        )
        storage.append_feedback(entry)
        storage.append_feedback(entry)

        log = storage.load_feedback()
        assert len(log.entries) == 2


class TestPlans:
    def _make_plan(self, name="Test Plan"):
        return TrainingPlan(
            name=name,
            goal=TrainingGoal(distance_m=21097.5),
            start_date=date(2026, 3, 1),
            end_date=date(2026, 5, 31),
        )

    def test_load_no_active(self, storage):
        assert storage.load_active_plan() is None

    def test_save_and_load_active(self, storage):
        plan = self._make_plan()
        storage.save_plan(plan)

        loaded = storage.load_active_plan()
        assert loaded is not None
        assert loaded.name == "Test Plan"

    def test_archive_plan(self, storage):
        plan = self._make_plan("10K Fall 2025")
        plan.status = "completed"
        storage.save_plan(plan)
        storage.archive_plan(plan)

        assert storage.load_active_plan() is None
        assert "10k-fall-2025" in storage.list_archived_plans()

        archived = storage.load_archived_plan("10k-fall-2025")
        assert archived is not None
        assert archived.name == "10K Fall 2025"

    def test_save_same_name_updates_without_archiving(self, storage):
        storage.save_plan(self._make_plan("Same Plan"))
        archived_name = storage.save_plan(self._make_plan("Same Plan"))
        assert archived_name is None
        assert storage.list_archived_plans() == []

    def test_save_different_name_auto_archives_previous(self, storage):
        # end_date 2026-05-31 is in the past → archived as completed
        storage.save_plan(self._make_plan("Old Plan"))
        archived_name = storage.save_plan(self._make_plan("New Plan"))
        assert archived_name == "Old Plan"
        assert storage.load_active_plan().name == "New Plan"
        archived = storage.load_archived_plan("old-plan")
        assert archived is not None
        assert archived.status == "completed"

    def test_save_different_name_future_race_archived_as_abandoned(self, storage):
        future = self._make_plan("Old Future Plan")
        future.end_date = date.today() + timedelta(weeks=8)
        storage.save_plan(future)
        storage.save_plan(self._make_plan("New Plan"))
        archived = storage.load_archived_plan("old-future-plan")
        assert archived is not None
        assert archived.status == "abandoned"

    def test_rename_active_plan(self, storage):
        storage.save_plan(self._make_plan("Ugly Name (from curated markdown)"))
        old, new = storage.rename_active_plan("Clean Name")
        assert old == "Ugly Name (from curated markdown)"
        assert new == "Clean Name"
        assert storage.load_active_plan().name == "Clean Name"

    def test_rename_without_active_raises(self, storage):
        with pytest.raises(ValueError, match="No active plan to rename"):
            storage.rename_active_plan("Whatever")

    def test_auto_archive_expired_past_grace(self, storage):
        plan = self._make_plan("Expired Plan")  # end 2026-05-31, long past
        storage.save_plan(plan)
        archived = storage.auto_archive_expired(grace_days=3)
        assert archived is not None
        assert archived.status == "completed"
        assert storage.load_active_plan() is None
        assert "expired-plan" in storage.list_archived_plans()

    def test_auto_archive_expired_within_grace_keeps_active(self, storage):
        plan = self._make_plan("Just Finished")
        plan.end_date = date.today() - timedelta(days=2)
        storage.save_plan(plan)
        assert storage.auto_archive_expired(grace_days=3) is None
        assert storage.load_active_plan() is not None

    def test_auto_archive_no_active_plan(self, storage):
        assert storage.auto_archive_expired() is None


class TestActivityCache:
    def test_load_empty(self, storage):
        assert storage.load_activity_cache() == []

    def test_save_and_load(self, storage):
        activities = [
            ActivitySummary(
                activity_id=123,
                date=date(2026, 3, 15),
                distance_m=10000,
                duration_s=3000,
            )
        ]
        storage.save_activity_cache(activities)

        loaded = storage.load_activity_cache()
        assert len(loaded) == 1
        assert loaded[0].activity_id == 123

    def test_save_writes_versioned_envelope(self, storage):
        storage.save_activity_cache(
            [
                ActivitySummary(
                    activity_id=1, date=date(2026, 3, 15), distance_m=5000, duration_s=1500
                )
            ]
        )
        raw = json.loads((storage.base_dir / "activity_cache" / "summary.json").read_text())
        assert raw["schema_version"] == 1
        assert len(raw["activities"]) == 1

    def test_load_accepts_legacy_bare_list(self, storage):
        legacy = [
            {
                "activity_id": 7,
                "date": "2026-03-15",
                "distance_m": 10000,
                "duration_s": 3000,
            }
        ]
        path = storage.base_dir / "activity_cache" / "summary.json"
        path.write_text(json.dumps(legacy))
        loaded = storage.load_activity_cache()
        assert len(loaded) == 1
        assert loaded[0].activity_id == 7
