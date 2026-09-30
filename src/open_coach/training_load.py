"""Training load calculations: TSS, CTL, ATL, TSB.

Implements the Performance Management Chart (PMC) model:
- TSS (Training Stress Score) via heart rate (hrTSS)
- CTL (Chronic Training Load / Fitness) — 42-day EWMA
- ATL (Acute Training Load / Fatigue) — 7-day EWMA
- TSB (Training Stress Balance / Form) = CTL - ATL
"""

from __future__ import annotations

from datetime import date, timedelta

from open_coach.models import TrainingLoadPoint


def calculate_tss(duration_s: float, avg_hr: float, threshold_hr: float) -> float:
    """Calculate heart-rate based Training Stress Score (hrTSS).

    Formula: TSS = (duration_s * avg_hr * IF) / (threshold_hr * 3600) * 100
    where IF (Intensity Factor) = avg_hr / threshold_hr

    Args:
        duration_s: Workout duration in seconds.
        avg_hr: Average heart rate during workout.
        threshold_hr: Lactate threshold heart rate.

    Returns:
        hrTSS value. A 1-hour threshold workout ≈ 100 TSS.

    Raises:
        ValueError: If any input is non-positive.
    """
    if duration_s <= 0 or avg_hr <= 0 or threshold_hr <= 0:
        raise ValueError("All inputs must be positive.")

    intensity_factor = avg_hr / threshold_hr
    return (duration_s * avg_hr * intensity_factor) / (threshold_hr * 3600) * 100


def calculate_load_series(
    daily_tss: list[tuple[date, float]],
    ctl_days: int = 42,
    atl_days: int = 7,
    end_date: date | None = None,
) -> list[TrainingLoadPoint]:
    """Calculate CTL/ATL/TSB time series from daily TSS values.

    Uses exponentially weighted moving averages (EWMA):
    - CTL_today = CTL_yesterday + (TSS_today - CTL_yesterday) / ctl_days
    - ATL_today = ATL_yesterday + (TSS_today - ATL_yesterday) / atl_days
    - TSB = CTL - ATL

    Args:
        daily_tss: List of (date, tss) tuples, sorted by date ascending.
        ctl_days: EWMA window for chronic load (default 42 days).
        atl_days: EWMA window for acute load (default 7 days).
        end_date: Extend the series to this day with zero-TSS rest days
            (default: the last activity date). Pass the day you assess, or the
            fatigue of the last session is reported as if it were today.

    Returns:
        List of TrainingLoadPoint, one per day from first date to end date.
    """
    if not daily_tss:
        return []

    # Build a dict for quick TSS lookup
    tss_by_date = dict(daily_tss)

    # Fill in all dates from first to last
    start_date = min(d for d, _ in daily_tss)
    last_activity = max(d for d, _ in daily_tss)
    end_date = max(end_date, last_activity) if end_date is not None else last_activity

    # PMC cold-start bias: seeding CTL/ATL at 0 understates fitness/fatigue for
    # roughly the first CTL window (~42 days) of the series.
    ctl = 0.0
    atl = 0.0
    results: list[TrainingLoadPoint] = []

    current = start_date
    while current <= end_date:
        tss = tss_by_date.get(current, 0.0)

        ctl = ctl + (tss - ctl) / ctl_days
        atl = atl + (tss - atl) / atl_days
        tsb = ctl - atl

        results.append(
            TrainingLoadPoint(
                date=current,
                tss=tss,
                ctl=round(ctl, 2),
                atl=round(atl, 2),
                tsb=round(tsb, 2),
            )
        )
        current += timedelta(days=1)

    return results


def interpret_tsb(tsb: float) -> str:
    """One-line coaching interpretation of a TSB (form) value.

    Canonical prose scale for tool responses. Component scorers in
    race_predictor/recovery_monitor use their own numeric scales on purpose
    (readiness and recovery weigh TSB differently) — do not merge them here.
    """
    if tsb > 15:
        return "Very fresh — risk of detraining"
    if tsb > 5:
        return "Fresh — good for racing or hard session"
    if tsb > -10:
        return "Neutral — normal training"
    if tsb > -25:
        return "Tired — building fitness"
    return "Very fatigued — consider recovery"


def daily_tss_from_activities(
    activities: list[tuple[str, float, float | None]], threshold_hr: float
) -> dict[date, float]:
    """Sum hrTSS per day from ``(start_time_local, duration_s, avg_hr)`` tuples.

    Activities without heart rate, without duration or with an unparsable date are
    skipped (hrTSS needs HR).
    """
    daily: dict[date, float] = {}
    for start_time_local, duration_s, avg_hr in activities:
        if not avg_hr or duration_s <= 0:
            continue
        try:
            day = date.fromisoformat(start_time_local[:10])
        except ValueError:
            continue
        daily[day] = daily.get(day, 0.0) + calculate_tss(duration_s, avg_hr, threshold_hr)
    return daily
