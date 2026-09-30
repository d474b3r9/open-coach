"""Tests for onboarding: PR detection, VDOT computation, pattern analysis."""

from datetime import date, timedelta

from open_coach.models import ActivitySummary
from open_coach.onboarding import (
    analyze_training_patterns,
    build_profile_from_activities,
    compute_training_load,
    compute_vdot_from_prs,
    detect_personal_records,
)
from open_coach.sports.running import vdot_of


def _activity(
    distance_m: float,
    duration_s: float,
    days_ago: int = 0,
    avg_hr: int | None = 150,
    idx: int = 0,
) -> ActivitySummary:
    return ActivitySummary(
        activity_id=1000 + idx,
        sport="running",
        date=date.today() - timedelta(days=days_ago),
        distance_m=distance_m,
        duration_s=duration_s,
        avg_hr=avg_hr,
        max_hr=(avg_hr + 20) if avg_hr else None,
    )


class TestDetectPersonalRecords:
    def test_detects_5k(self):
        activities = [_activity(5020, 1200, days_ago=10, idx=0)]  # ~5K in 20:00
        prs = detect_personal_records(activities)
        assert len(prs) == 1
        assert prs[0].distance_label == "5K"

    def test_detects_multiple_distances(self):
        activities = [
            _activity(5050, 1200, days_ago=10, idx=0),  # 5K
            _activity(10100, 2400, days_ago=20, idx=1),  # 10K
        ]
        prs = detect_personal_records(activities)
        labels = {pr.distance_label for pr in prs}
        assert "5K" in labels
        assert "10K" in labels

    def test_picks_fastest(self):
        activities = [
            _activity(5050, 1200, days_ago=10, idx=0),  # 20:00
            _activity(5020, 1500, days_ago=20, idx=1),  # 25:00
        ]
        prs = detect_personal_records(activities)
        pr_5k = next(pr for pr in prs if pr.distance_label == "5K")
        assert pr_5k.time_s == 1200

    def test_ignores_out_of_tolerance(self):
        activities = [_activity(6000, 1800, idx=0)]  # too far from 5K or 10K
        prs = detect_personal_records(activities)
        assert len(prs) == 0

    def test_no_activities(self):
        assert detect_personal_records([]) == []


class TestComputeVdotFromPrs:
    def test_prefers_shorter_distance(self):
        from open_coach.models import PersonalRecord

        prs = [
            PersonalRecord(
                distance_label="5K",
                distance_m=5000,
                time_s=1200,
                activity_id=1,
                date=date.today(),
            ),
            PersonalRecord(
                distance_label="10K",
                distance_m=10000,
                time_s=2400,
                activity_id=2,
                date=date.today(),
            ),
        ]
        vdot, source = compute_vdot_from_prs(prs)
        assert vdot is not None
        assert source is not None
        assert "5K" in source

    def test_no_prs(self):
        vdot, source = compute_vdot_from_prs([])
        assert vdot is None
        assert source is None


class TestAnalyzeTrainingPatterns:
    def test_enough_data(self):
        activities = [_activity(10000, 3600, days_ago=i * 2, avg_hr=145, idx=i) for i in range(30)]
        pattern = analyze_training_patterns(activities, window_days=90)
        assert pattern is not None
        assert pattern.weekly_distance_m > 0
        assert pattern.weekly_frequency > 0

    def test_not_enough_data(self):
        activities = [_activity(10000, 3600, idx=0)]
        assert analyze_training_patterns(activities) is None


class TestComputeTrainingLoad:
    def test_with_hr_data(self):
        activities = [_activity(10000, 3600, days_ago=i, avg_hr=150, idx=i) for i in range(30)]
        ctl, atl, tsb = compute_training_load(activities)
        assert ctl is not None
        assert atl is not None
        assert tsb is not None

    def test_no_hr_data(self):
        activities = [_activity(10000, 3600, avg_hr=None, idx=0)]
        ctl, _atl, _tsb = compute_training_load(activities)
        assert ctl is None


class TestBuildProfileFromActivities:
    def test_full_profile(self):
        activities = [
            _activity(5050, 1200, days_ago=10, avg_hr=165, idx=0),  # 5K PR
            *[_activity(8000, 3000, days_ago=i * 2, avg_hr=145, idx=i + 1) for i in range(30)],
        ]
        profile = build_profile_from_activities(activities)
        assert profile.onboarding_complete is True
        assert vdot_of(profile) is not None
        assert len(profile.sport_profile("running").personal_records) > 0

    def test_empty_activities(self):
        profile = build_profile_from_activities([])
        assert profile.onboarding_complete is True
        assert vdot_of(profile) is None
        assert len(profile.sport_profile("running").personal_records) == 0
