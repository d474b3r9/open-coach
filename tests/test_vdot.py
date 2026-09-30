"""Tests for the VDOT calculation engine.

Reference values verified against vdoto2.com and Daniels-Gilbert equations.
"""

import pytest

from open_coach.sports.running.vdot import (
    calculate_vdot,
    format_pace,
    format_time,
    predict_time,
    training_paces,
    vo2_from_velocity,
    vo2max_fraction,
)

VDOT_TOLERANCE = 0.3


class TestVo2FromVelocity:
    def test_zero_velocity(self):
        assert vo2_from_velocity(0) == pytest.approx(-4.60, abs=0.01)

    def test_typical_easy_pace(self):
        # ~200 m/min ≈ 5:00/km
        vo2 = vo2_from_velocity(200)
        assert vo2 > 0
        assert vo2 < 60

    def test_fast_pace(self):
        # ~300 m/min ≈ 3:20/km
        vo2 = vo2_from_velocity(300)
        assert vo2 > vo2_from_velocity(200)


class TestVo2maxFraction:
    def test_short_effort(self):
        # Very short effort → close to max fraction (~1.0+)
        frac = vo2max_fraction(3)
        assert frac > 1.0

    def test_marathon_effort(self):
        # ~180 min → fraction should be around 0.8
        frac = vo2max_fraction(180)
        assert 0.75 < frac < 0.85

    def test_decreases_with_time(self):
        assert vo2max_fraction(10) > vo2max_fraction(60)
        assert vo2max_fraction(60) > vo2max_fraction(180)


class TestCalculateVdot:
    """Reference values verified against vdoto2.com."""

    def test_5k_20min(self):
        vdot = calculate_vdot(5000, 20 * 60)
        assert vdot == pytest.approx(49.8, abs=VDOT_TOLERANCE)

    def test_5k_25min(self):
        vdot = calculate_vdot(5000, 25 * 60)
        assert vdot == pytest.approx(38.3, abs=VDOT_TOLERANCE)

    def test_10k_40min(self):
        vdot = calculate_vdot(10000, 40 * 60)
        assert vdot == pytest.approx(51.9, abs=VDOT_TOLERANCE)

    def test_half_marathon_90min(self):
        vdot = calculate_vdot(21097.5, 90 * 60)
        assert vdot == pytest.approx(51.0, abs=VDOT_TOLERANCE)

    def test_marathon_3h(self):
        vdot = calculate_vdot(42195, 3 * 3600)
        assert vdot == pytest.approx(53.5, abs=VDOT_TOLERANCE)

    def test_invalid_distance(self):
        with pytest.raises(ValueError, match="Distance and time must be positive"):
            calculate_vdot(0, 1200)

    def test_invalid_time(self):
        with pytest.raises(ValueError, match="Distance and time must be positive"):
            calculate_vdot(5000, 0)

    def test_negative_values(self):
        with pytest.raises(ValueError, match="Distance and time must be positive"):
            calculate_vdot(-5000, 1200)


class TestPredictTime:
    def test_roundtrip_5k(self):
        """calculate_vdot → predict_time should round-trip within 1 second."""
        original_time = 20 * 60  # 20:00
        vdot = calculate_vdot(5000, original_time)
        predicted = predict_time(vdot, 5000)
        assert predicted == pytest.approx(original_time, abs=1.0)

    def test_roundtrip_10k(self):
        original_time = 40 * 60
        vdot = calculate_vdot(10000, original_time)
        predicted = predict_time(vdot, 10000)
        assert predicted == pytest.approx(original_time, abs=1.0)

    def test_roundtrip_marathon(self):
        original_time = 3 * 3600
        vdot = calculate_vdot(42195, original_time)
        predicted = predict_time(vdot, 42195)
        assert predicted == pytest.approx(original_time, abs=1.0)

    def test_roundtrip_half_marathon(self):
        original_time = 90 * 60
        vdot = calculate_vdot(21097.5, original_time)
        predicted = predict_time(vdot, 21097.5)
        assert predicted == pytest.approx(original_time, abs=1.0)

    def test_faster_vdot_gives_faster_time(self):
        time_50 = predict_time(50, 5000)
        time_60 = predict_time(60, 5000)
        assert time_60 < time_50

    def test_longer_distance_gives_longer_time(self):
        time_5k = predict_time(50, 5000)
        time_10k = predict_time(50, 10000)
        assert time_10k > time_5k

    def test_invalid_vdot(self):
        with pytest.raises(ValueError, match="VDOT and distance must be positive"):
            predict_time(0, 5000)

    def test_invalid_distance(self):
        with pytest.raises(ValueError, match="VDOT and distance must be positive"):
            predict_time(50, 0)


class TestTrainingPaces:
    def test_returns_all_zones(self):
        paces = training_paces(50)
        assert set(paces.keys()) == {"easy", "marathon", "threshold", "interval", "repetition"}

    def test_paces_are_ordered(self):
        """For each zone, min_pace (fast) < max_pace (slow)."""
        paces = training_paces(50)
        for zone_name, (min_pace, max_pace) in paces.items():
            assert min_pace < max_pace, f"{zone_name}: min_pace should be faster (lower)"

    def test_zones_get_progressively_faster(self):
        """Easy is slowest, repetition is fastest."""
        paces = training_paces(50)
        # Compare midpoints of each zone
        midpoints = {name: (p[0] + p[1]) / 2 for name, p in paces.items()}
        assert midpoints["easy"] > midpoints["marathon"]
        assert midpoints["marathon"] > midpoints["threshold"]
        assert midpoints["threshold"] > midpoints["interval"]
        assert midpoints["interval"] > midpoints["repetition"]

    def test_higher_vdot_gives_faster_paces(self):
        paces_40 = training_paces(40)
        paces_60 = training_paces(60)
        for zone in paces_40:
            assert paces_60[zone][0] < paces_40[zone][0], f"VDOT 60 should be faster in {zone}"

    def test_easy_pace_reasonable(self):
        """VDOT 50 easy pace should be roughly 5:00-6:30/km."""
        paces = training_paces(50)
        min_pace, max_pace = paces["easy"]
        assert 270 < min_pace < 360  # ~4:30-6:00
        assert 300 < max_pace < 420  # ~5:00-7:00

    def test_interval_pace_reasonable(self):
        """VDOT 50 interval pace should be roughly 3:40-4:10/km."""
        paces = training_paces(50)
        min_pace, max_pace = paces["interval"]
        assert 200 < min_pace < 270
        assert 220 < max_pace < 300


class TestFormatPace:
    def test_4min_per_km(self):
        assert format_pace(240) == "4:00"

    def test_5_30_per_km(self):
        assert format_pace(330) == "5:30"

    def test_6_05_per_km(self):
        assert format_pace(365) == "6:05"


class TestFormatTime:
    def test_under_hour(self):
        assert format_time(1200) == "20:00"

    def test_over_hour(self):
        assert format_time(3723) == "1:02:03"

    def test_marathon_time(self):
        assert format_time(10800) == "3:00:00"
