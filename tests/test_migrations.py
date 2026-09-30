"""Schema migrations: v1 (running-only) files load as v2 (sport plugins)."""

from __future__ import annotations

import json
from pathlib import Path

from open_coach.migrations import migrate
from open_coach.sports.running import pace_of, vdot_of
from open_coach.storage import CoachStorage

V1_PROFILE = {
    "schema_version": 1,
    "vdot": 48.7,
    "vdot_source": "10K 42:10 on 2026-04-12",
    "max_hr": 190,
    "personal_records": [
        {
            "distance_label": "10K",
            "distance_m": 10000,
            "time_s": 2530,
            "pace_sec_per_km": 253,
            "activity_id": 7,
            "date": "2026-04-12",
            "source": "garmin_pr",
        }
    ],
    "training_pattern": {
        "weekly_volume_km": 33.9,
        "weekly_frequency": 4.0,
        "long_run_avg_km": 18.1,
        "easy_pace_avg_sec_per_km": 329,
        "computed_at": "2026-05-18T13:25:46",
    },
    "ctl": 40.0,
    "onboarding_complete": True,
}

V1_GOAL = {"race_name": "Test 10K", "distance_m": 10000, "race_date": "2026-11-01"}

V1_PLAN = {
    "schema_version": 1,
    "name": "Test plan",
    "goal": V1_GOAL,
    "start_date": "2026-10-05",
    "end_date": "2026-11-01",
    "weeks": [
        {
            "week_number": 1,
            "start_date": "2026-10-05",
            "planned_volume_km": 30.5,
            "actual_volume_km": 12.3,
            "completion_rate": 0.5,
            "workouts": [
                {
                    "date": "2026-10-06",
                    "workout_type": "easy",
                    "description": "Easy 8 km",
                    "target_distance_km": 8.0,
                    "target_duration_min": 44,
                    "target_pace_sec_per_km": 330,
                    "completed": True,
                    "actual_distance_km": 8.2,
                    "actual_pace_sec_per_km": 325,
                },
                {"date": "2026-10-07", "workout_type": "rest", "description": "Rest"},
            ],
            "extra_activities": [{"date": "2026-10-08", "distance_km": 4.1, "name": "Trail"}],
        }
    ],
}

V1_FEEDBACK = {
    "schema_version": 1,
    "period": "2026-Q4",
    "entries": [
        {
            "date": "2026-10-06",
            "planned_distance_km": 8.0,
            "actual_distance_km": 8.2,
            "planned_pace_sec_per_km": 330,
            "actual_pace_sec_per_km": 325,
        }
    ],
}


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_profile_moves_running_data_under_its_sport(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    _write(tmp_path / "profile.json", V1_PROFILE)

    profile = storage.load_profile()

    assert profile is not None
    assert profile.schema_version == 2
    assert vdot_of(profile) == 48.7
    running = profile.sport_profile("running")
    assert running.fitness is not None
    assert running.fitness.source == "10K 42:10 on 2026-04-12"
    [pr] = running.personal_records
    assert pr.time_s == 2530
    assert pr.source == "platform_pr"
    assert running.training_pattern is not None
    assert running.training_pattern.weekly_distance_m == 33900
    assert running.training_pattern.long_session_avg_distance_m == 18100
    assert pace_of(running.training_pattern.easy_intensity) == 329
    assert profile.max_hr == 190
    assert profile.ctl == 40.0


def test_plan_converts_units_and_volumes(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    _write(tmp_path / "plans" / "active.json", V1_PLAN)

    plan = storage.load_active_plan()

    assert plan is not None
    assert plan.goal.sport == "running"
    week = plan.weeks[0]
    assert week.planned_volume["running"].distance_m == 30500
    assert week.actual_volume["running"].distance_m == 12300
    easy, rest = week.workouts
    assert easy.target_distance_m == 8000
    assert easy.target_duration_s == 44 * 60
    assert pace_of(easy.target_intensity) == 330
    assert easy.actual_distance_m == 8200
    assert pace_of(easy.actual_intensity) == 325
    assert plan.sport_of(easy) == "running"
    assert rest.target_intensity is None
    assert rest.target_distance_m is None
    [extra] = week.extra_activities
    assert extra.sport == "running"
    assert extra.distance_m == 4100


def test_feedback_and_goals_are_migrated(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    _write(tmp_path / "goals.json", {"schema_version": 1, "goals": [V1_GOAL]})
    _write(tmp_path / "feedback" / "2026-Q4.json", V1_FEEDBACK)

    goals = storage.load_goals()
    [entry] = storage.load_feedback("2026-Q4").entries

    assert goals is not None
    assert goals.goals[0].sport == "running"
    assert entry.sport == "running"
    assert entry.workout_type == "easy"  # the v1 default
    assert entry.planned_distance_m == 8000
    assert entry.actual_distance_m == 8200
    assert pace_of(entry.planned_intensity) == 330
    assert pace_of(entry.actual_intensity) == 325


def test_legacy_bare_list_activity_cache(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    _write(
        tmp_path / "activity_cache" / "summary.json",
        [
            {
                "activity_id": 1,
                "date": "2026-10-01",
                "distance_m": 10000,
                "duration_s": 3000,
                "avg_pace_sec_per_km": 300,
                "activity_type": "running",
            }
        ],
    )

    [activity] = storage.load_activity_cache()

    assert activity.sport == "running"
    assert activity.distance_m == 10000


def test_migrated_file_is_rewritten_and_backed_up_once(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    path = tmp_path / "profile.json"
    _write(path, V1_PROFILE)
    original = path.read_text()

    storage.load_profile()
    backup = tmp_path / "profile.json.v1.bak"
    assert backup.read_text() == original
    assert json.loads(path.read_text())["schema_version"] == 2

    # Second load: already current, nothing rewritten, backup untouched.
    rewritten = path.read_text()
    storage.load_profile()
    assert path.read_text() == rewritten
    assert backup.read_text() == original


def test_archived_plan_backups_are_not_listed_as_plans(tmp_path: Path) -> None:
    storage = CoachStorage(base_dir=tmp_path)
    _write(tmp_path / "plans" / "archive" / "old.json", V1_PLAN)

    assert storage.load_archived_plan("old") is not None
    assert storage.list_archived_plans() == ["old"]


def test_current_data_is_left_alone() -> None:
    data = {"schema_version": 2, "goals": []}
    assert migrate("goals", data) == (data, None)


def test_missing_schema_version_is_treated_as_v1() -> None:
    data, from_version = migrate("goals", {"goals": [dict(V1_GOAL)]})
    assert from_version == 1
    assert data["schema_version"] == 2
    assert data["goals"][0]["sport"] == "running"
