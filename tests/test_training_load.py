"""Tests for training load calculations (TSS, CTL, ATL, TSB)."""

from datetime import date, timedelta

import pytest

from open_coach.training_load import calculate_load_series, calculate_tss


class TestCalculateTss:
    def test_threshold_run_1h(self):
        """1 hour at threshold HR should give ~100 TSS."""
        tss = calculate_tss(3600, avg_hr=170, threshold_hr=170)
        assert tss == pytest.approx(100, abs=1)

    def test_easy_run_1h(self):
        """1 hour at 75% of threshold HR should give less than 100 TSS."""
        tss = calculate_tss(3600, avg_hr=128, threshold_hr=170)
        assert tss < 100
        assert tss > 0

    def test_hard_run_1h(self):
        """1 hour above threshold should give more than 100 TSS."""
        tss = calculate_tss(3600, avg_hr=180, threshold_hr=170)
        assert tss > 100

    def test_longer_duration_more_tss(self):
        tss_30min = calculate_tss(1800, avg_hr=150, threshold_hr=170)
        tss_60min = calculate_tss(3600, avg_hr=150, threshold_hr=170)
        assert tss_60min > tss_30min

    def test_higher_hr_more_tss(self):
        tss_easy = calculate_tss(3600, avg_hr=130, threshold_hr=170)
        tss_hard = calculate_tss(3600, avg_hr=165, threshold_hr=170)
        assert tss_hard > tss_easy

    def test_invalid_inputs(self):
        with pytest.raises(ValueError, match="All inputs must be positive"):
            calculate_tss(0, 150, 170)
        with pytest.raises(ValueError, match="All inputs must be positive"):
            calculate_tss(3600, 0, 170)
        with pytest.raises(ValueError, match="All inputs must be positive"):
            calculate_tss(3600, 150, 0)


class TestCalculateLoadSeries:
    def test_empty_input(self):
        assert calculate_load_series([]) == []

    def test_single_day(self):
        result = calculate_load_series([(date(2026, 1, 1), 50.0)])
        assert len(result) == 1
        assert result[0].tss == 50.0
        assert result[0].ctl > 0
        assert result[0].atl > 0

    def test_ctl_converges_to_daily_tss(self):
        """After many days of consistent TSS, CTL should approach that value."""
        start = date(2026, 1, 1)
        daily = [(start + timedelta(days=i), 50.0) for i in range(120)]
        result = calculate_load_series(daily)

        # After 120 days of 50 TSS/day, CTL should be close to 50
        # EWMA starting from 0 takes ~3x window to converge, so allow wider tolerance
        final = result[-1]
        assert final.ctl == pytest.approx(50.0, abs=3.0)

    def test_atl_converges_faster_than_ctl(self):
        """ATL (7-day) should converge faster than CTL (42-day)."""
        start = date(2026, 1, 1)
        daily = [(start + timedelta(days=i), 80.0) for i in range(14)]
        result = calculate_load_series(daily)

        final = result[-1]
        assert final.atl > final.ctl  # ATL reacts faster to load

    def test_tsb_negative_after_hard_block(self):
        """TSB should be negative during a heavy training block."""
        start = date(2026, 1, 1)
        daily = [(start + timedelta(days=i), 100.0) for i in range(7)]
        result = calculate_load_series(daily)

        final = result[-1]
        assert final.tsb < 0  # fatigue > fitness during buildup

    def test_tsb_positive_after_rest(self):
        """TSB should become positive after rest following hard training."""
        start = date(2026, 1, 1)
        # 21 days hard, then 10 days rest
        daily = [(start + timedelta(days=i), 80.0) for i in range(21)]
        daily += [(start + timedelta(days=21 + i), 0.0) for i in range(10)]
        result = calculate_load_series(daily)

        final = result[-1]
        assert final.tsb > 0  # freshness after taper

    def test_fills_missing_days(self):
        """Days without TSS entries should be filled with 0."""
        daily = [
            (date(2026, 1, 1), 50.0),
            (date(2026, 1, 5), 60.0),
        ]
        result = calculate_load_series(daily)
        assert len(result) == 5  # Jan 1-5 inclusive

    def test_date_order(self):
        start = date(2026, 1, 1)
        daily = [(start + timedelta(days=i), 50.0) for i in range(7)]
        result = calculate_load_series(daily)

        dates = [r.date for r in result]
        assert dates == sorted(dates)


def test_load_series_extends_to_end_date_with_rest_days() -> None:
    from datetime import date as _date

    from open_coach.training_load import calculate_load_series

    series = calculate_load_series([(_date(2026, 9, 1), 100.0)], end_date=_date(2026, 9, 11))
    assert series[-1].date == _date(2026, 9, 11)
    assert len(series) == 11
    assert series[-1].tss == 0.0
    assert series[-1].atl < series[0].atl  # fatigue decays over rest days
    # end_date before the last activity never truncates the series
    assert calculate_load_series([(_date(2026, 9, 5), 50.0)], end_date=_date(2026, 9, 1))[
        -1
    ].date == _date(2026, 9, 5)


def test_daily_tss_from_runs_skips_runs_without_hr() -> None:
    from datetime import date as _date

    from open_coach.training_load import daily_tss_from_runs

    daily = daily_tss_from_runs(
        [
            ("2026-09-01 08:00:00", 3600.0, 150.0),
            ("2026-09-01 18:00:00", 1800.0, 150.0),
            ("2026-09-02 08:00:00", 3600.0, None),
            ("bad-date", 3600.0, 150.0),
            ("2026-09-03 08:00:00", 0.0, 150.0),
        ],
        threshold_hr=170,
    )
    assert list(daily) == [_date(2026, 9, 1)]
    assert daily[_date(2026, 9, 1)] > 0
