"""Tests for training zone calculations."""

from datetime import date

import pytest

from open_coach.models import ActivitySummary
from open_coach.zones import (
    estimate_max_hr,
    estimate_resting_hr,
    hr_zones_karvonen,
    merge_zones,
    pace_zones_from_vdot,
)


class TestPaceZonesFromVdot:
    def test_returns_all_zones(self):
        zones = pace_zones_from_vdot(50)
        assert zones.easy.pace is not None
        assert zones.marathon.pace is not None
        assert zones.threshold.pace is not None
        assert zones.interval.pace is not None
        assert zones.repetition.pace is not None

    def test_easy_slower_than_threshold(self):
        zones = pace_zones_from_vdot(50)
        assert zones.easy.pace is not None
        assert zones.threshold.pace is not None
        assert zones.easy.pace.max_pace_sec_per_km > zones.threshold.pace.max_pace_sec_per_km

    def test_no_hr_in_pace_zones(self):
        zones = pace_zones_from_vdot(50)
        assert zones.easy.hr is None


class TestHrZonesKarvonen:
    def test_basic_zones(self):
        zones = hr_zones_karvonen(resting_hr=50, max_hr=190)
        assert zones.easy.hr is not None
        assert zones.repetition.hr is not None

    def test_easy_zone_range(self):
        zones = hr_zones_karvonen(resting_hr=50, max_hr=190)
        assert zones.easy.hr is not None
        # HRR = 140, easy = 50 + 140*0.59 to 50 + 140*0.74 = 133-154
        assert zones.easy.hr.min_bpm == pytest.approx(133, abs=1)
        assert zones.easy.hr.max_bpm == pytest.approx(154, abs=1)

    def test_zones_increase_progressively(self):
        zones = hr_zones_karvonen(resting_hr=50, max_hr=190)
        assert zones.easy.hr is not None
        assert zones.threshold.hr is not None
        assert zones.interval.hr is not None
        assert zones.repetition.hr is not None
        assert zones.easy.hr.min_bpm < zones.threshold.hr.min_bpm
        assert zones.threshold.hr.min_bpm < zones.interval.hr.min_bpm
        assert zones.interval.hr.min_bpm < zones.repetition.hr.min_bpm

    def test_no_pace_in_hr_zones(self):
        zones = hr_zones_karvonen(resting_hr=50, max_hr=190)
        assert zones.easy.pace is None

    def test_invalid_resting_gte_max(self):
        with pytest.raises(ValueError, match="must be less than max HR"):
            hr_zones_karvonen(resting_hr=190, max_hr=190)


class TestMergeZones:
    def test_merge_combines_pace_and_hr(self):
        pace_zones = pace_zones_from_vdot(50)
        hr_zones = hr_zones_karvonen(resting_hr=50, max_hr=190)
        merged = merge_zones(pace_zones, hr_zones)

        assert merged.easy.pace is not None
        assert merged.easy.hr is not None
        assert merged.threshold.pace is not None
        assert merged.threshold.hr is not None


def _make_activity(
    avg_hr: int | None = 140,
    max_hr: int | None = 170,
    duration_s: float = 3600,
    avg_pace: float = 330,
    idx: int = 0,
) -> ActivitySummary:
    return ActivitySummary(
        activity_id=1000 + idx,
        date=date(2026, 3, 1),
        distance_m=duration_s / avg_pace * 1000 if avg_pace else 10000,
        duration_s=duration_s,
        avg_hr=avg_hr,
        max_hr=max_hr,
        sport="running",
    )


class TestEstimateRestingHr:
    def test_enough_data(self):
        activities = [_make_activity(avg_hr=130 + i, avg_pace=340, idx=i) for i in range(5)]
        result = estimate_resting_hr(activities)
        assert result is not None
        assert 40 <= result <= 100

    def test_not_enough_data(self):
        activities = [_make_activity(avg_hr=140, idx=0)]
        assert estimate_resting_hr(activities) is None

    def test_filters_short_runs(self):
        activities = [_make_activity(avg_hr=130 + i, duration_s=600, idx=i) for i in range(5)]
        assert estimate_resting_hr(activities) is None

    def test_filters_fast_runs(self):
        activities = [_make_activity(avg_hr=160 + i, avg_pace=240, idx=i) for i in range(5)]
        assert estimate_resting_hr(activities) is None


class TestEstimateMaxHr:
    def test_enough_data(self):
        activities = [_make_activity(max_hr=175 + i, idx=i) for i in range(10)]
        result = estimate_max_hr(activities)
        assert result is not None
        assert result >= 180

    def test_not_enough_data(self):
        activities = [_make_activity(max_hr=185, idx=0)]
        assert estimate_max_hr(activities) is None

    def test_filters_low_values(self):
        activities = [_make_activity(max_hr=50 + i, idx=i) for i in range(5)]
        assert estimate_max_hr(activities) is None

    def test_uses_percentile_95(self):
        """Should ignore outlier spike at the very top."""
        # 95 normal readings + 5 sensor glitches → p95 should be in normal range
        activities = [_make_activity(max_hr=180, idx=i) for i in range(95)]
        activities += [_make_activity(max_hr=250, idx=95 + i) for i in range(5)]
        result = estimate_max_hr(activities)
        assert result is not None
        assert result <= 200  # should not pick the 250 outlier
