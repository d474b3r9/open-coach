"""Recovery monitoring and adaptive training recommendations.

Pure computation — no I/O.  All watch data access happens in tools/recovery.py.

Provides:
- assess_recovery: multi-signal recovery scoring (HRV, sleep, TSB, stress, subjective)
- recommend_adaptation: concrete workout adjustment based on recovery status
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from open_coach.models import (
    AdaptiveRecommendation,
    AthleteProfile,
    PlannedWorkout,
    RecoveryAssessment,
    RecoverySignal,
    WorkoutFeedback,
)
from open_coach.sports.base import SportKey
from open_coach.sports.registry import get_sport

# ── Signal weights ──

_RECOVERY_WEIGHTS = {
    "HRV": 0.30,
    "Sleep": 0.25,
    "TSB": 0.20,
    "Subjective": 0.15,
    "Stress": 0.10,
}

# ── Signal scoring functions ──


def _score_hrv(
    hrv_last_night: float | None,
    hrv_weekly_avg: float | None,
) -> RecoverySignal:
    """Score HRV relative to weekly baseline."""
    if hrv_last_night is None or hrv_weekly_avg is None or hrv_weekly_avg <= 0:
        return RecoverySignal(
            name="HRV",
            score=0.5,
            status="yellow",
            value="HRV data unavailable",
            available=False,
            detail="No HRV data — cannot assess autonomic recovery.",
        )

    ratio = hrv_last_night / hrv_weekly_avg

    if ratio >= 0.95:
        return RecoverySignal(
            name="HRV",
            score=1.0,
            status="green",
            value=f"HRV {hrv_last_night:.0f}ms (baseline {hrv_weekly_avg:.0f}ms)",
            detail="HRV at or above baseline — good autonomic recovery.",
        )
    if ratio >= 0.85:
        return RecoverySignal(
            name="HRV",
            score=0.6,
            status="yellow",
            value=f"HRV {hrv_last_night:.0f}ms (baseline {hrv_weekly_avg:.0f}ms)",
            detail="HRV slightly below baseline — recovery is incomplete.",
        )
    return RecoverySignal(
        name="HRV",
        score=0.3,
        status="red",
        value=f"HRV {hrv_last_night:.0f}ms (baseline {hrv_weekly_avg:.0f}ms)",
        detail="HRV significantly below baseline — body is still recovering.",
    )


def _score_sleep(
    sleep_score: float | None,
    sleep_duration_s: float | None,
) -> RecoverySignal:
    """Score sleep quality and duration."""
    if sleep_score is None and sleep_duration_s is None:
        return RecoverySignal(
            name="Sleep",
            score=0.5,
            status="yellow",
            value="Sleep data unavailable",
            available=False,
            detail="No sleep data — cannot assess sleep quality.",
        )

    duration_h = sleep_duration_s / 3600.0 if sleep_duration_s else None
    score_val = sleep_score if sleep_score is not None else 70  # neutral default

    # Short sleep overrides good score
    if duration_h is not None and duration_h < 6.0:
        dur_str = f"{duration_h:.1f}h"
        score_str = f", score {score_val:.0f}/100" if sleep_score is not None else ""
        return RecoverySignal(
            name="Sleep",
            score=0.3,
            status="red",
            value=f"Sleep {dur_str}{score_str}",
            detail=f"Very short sleep ({dur_str}) — recovery severely impacted.",
        )

    # Build value string
    parts = []
    if sleep_score is not None:
        parts.append(f"score {score_val:.0f}/100")
    if duration_h is not None:
        parts.append(f"{duration_h:.1f}h")
    value_str = f"Sleep {', '.join(parts)}"

    if score_val >= 80 and (duration_h is None or duration_h >= 7.0):
        return RecoverySignal(
            name="Sleep",
            score=1.0,
            status="green",
            value=value_str,
            detail="Good sleep quality and duration.",
        )
    if score_val < 60:
        return RecoverySignal(
            name="Sleep",
            score=0.3,
            status="red",
            value=value_str,
            detail="Poor sleep quality — recovery is compromised.",
        )
    # score 60-80 or duration 6-7h
    return RecoverySignal(
        name="Sleep",
        score=0.6,
        status="yellow",
        value=value_str,
        detail="Moderate sleep — could be better for optimal recovery.",
    )


def _score_tsb(tsb: float | None) -> RecoverySignal:
    """Score Training Stress Balance (form)."""
    if tsb is None:
        return RecoverySignal(
            name="TSB",
            score=0.5,
            status="yellow",
            value="TSB unavailable",
            available=False,
            detail="No training load data — cannot assess form.",
        )

    if tsb >= 0:
        # Scale 0.7 to 1.0 for TSB 0 to +20, cap at 1.0
        score = min(1.0, 0.7 + (tsb / 20.0) * 0.3)
        return RecoverySignal(
            name="TSB",
            score=round(score, 2),
            status="green",
            value=f"TSB {tsb:+.0f}",
            detail="Positive form — training stress is absorbed.",
        )
    if tsb >= -5:
        return RecoverySignal(
            name="TSB",
            score=0.6,
            status="yellow",
            value=f"TSB {tsb:+.0f}",
            detail="Slightly negative form — manageable fatigue.",
        )
    if tsb >= -10:
        return RecoverySignal(
            name="TSB",
            score=0.4,
            status="yellow",
            value=f"TSB {tsb:+.0f}",
            detail="Moderate fatigue accumulated — be cautious with intensity.",
        )
    return RecoverySignal(
        name="TSB",
        score=0.25,
        status="red",
        value=f"TSB {tsb:+.0f}",
        detail="Significant fatigue — body needs recovery time.",
    )


def _score_stress(avg_stress: float | None) -> RecoverySignal:
    """Score the watch stress level (0-100, lower is better)."""
    if avg_stress is None:
        return RecoverySignal(
            name="Stress",
            score=0.5,
            status="yellow",
            value="Stress data unavailable",
            available=False,
            detail="No stress data available.",
        )

    if avg_stress <= 25:
        return RecoverySignal(
            name="Stress",
            score=1.0,
            status="green",
            value=f"Stress {avg_stress:.0f}/100",
            detail="Low stress level — favorable for training.",
        )
    if avg_stress <= 50:
        return RecoverySignal(
            name="Stress",
            score=0.6,
            status="yellow",
            value=f"Stress {avg_stress:.0f}/100",
            detail="Moderate stress — monitor how you feel during the session.",
        )
    return RecoverySignal(
        name="Stress",
        score=0.3,
        status="red",
        value=f"Stress {avg_stress:.0f}/100",
        detail="High stress — non-training stress is taxing your recovery.",
    )


# Feeling and effort mappings for subjective scoring
_FEELING_SCORES = {
    "great": 1.0,
    "good": 0.8,
    "okay": 0.6,
    "tired": 0.3,
    "terrible": 0.1,
}

_EFFORT_SCORES = {
    "too_easy": 0.9,
    "easy": 0.8,
    "moderate": 0.6,
    "hard": 0.4,
    "too_hard": 0.2,
}


def _score_subjective(recent_feedback: list[WorkoutFeedback] | None) -> RecoverySignal:
    """Score subjective feeling from recent workout feedback."""
    if not recent_feedback:
        return RecoverySignal(
            name="Subjective",
            score=0.5,
            status="yellow",
            value="No recent feedback",
            available=False,
            detail="No recent workout feedback — consider logging how you feel.",
        )

    # Use last 3 entries max
    entries = recent_feedback[-3:]
    feeling_scores = []
    effort_scores = []

    for fb in entries:
        if fb.feeling and fb.feeling in _FEELING_SCORES:
            feeling_scores.append(_FEELING_SCORES[fb.feeling])
        if fb.perceived_effort and fb.perceived_effort in _EFFORT_SCORES:
            effort_scores.append(_EFFORT_SCORES[fb.perceived_effort])

    if not feeling_scores and not effort_scores:
        return RecoverySignal(
            name="Subjective",
            score=0.5,
            status="yellow",
            value="No subjective data in recent feedback",
            available=False,
            detail="Recent feedback entries lack feeling/effort ratings.",
        )

    # Weight: feeling 60%, effort 40%
    avg_feeling = sum(feeling_scores) / len(feeling_scores) if feeling_scores else 0.5
    avg_effort = sum(effort_scores) / len(effort_scores) if effort_scores else 0.5
    score = avg_feeling * 0.6 + avg_effort * 0.4

    # Determine status
    status: Literal["green", "yellow", "red"]
    if score >= 0.7:
        status = "green"
    elif score >= 0.4:
        status = "yellow"
    else:
        status = "red"

    # Latest feeling for display
    latest = entries[-1]
    feeling_str = latest.feeling or "unknown"

    return RecoverySignal(
        name="Subjective",
        score=round(score, 2),
        status=status,
        value=f"Recent feeling: {feeling_str}",
        detail=f"Based on last {len(entries)} session(s) — avg subjective score {score:.0%}.",
    )


# ── Composite recovery assessment ──


def _generate_recovery_recommendations(signals: list[RecoverySignal]) -> list[str]:
    """Generate actionable recommendations from weak signals."""
    recs = []
    for s in signals:
        if s.score >= 0.7 or not s.available:
            continue
        if s.name == "HRV":
            recs.append(
                "HRV is suppressed. Prioritize sleep tonight, avoid alcohol and screens before bed."
            )
        elif s.name == "Sleep":
            recs.append(
                "Sleep quality or duration was poor. Aim for 8 hours tonight "
                "and consider shifting tomorrow's session later in the day."
            )
        elif s.name == "TSB":
            recs.append(
                "Training fatigue is accumulated. An easy or rest day "
                "will help your body absorb recent training."
            )
        elif s.name == "Stress":
            recs.append(
                "Non-training stress is elevated. Consider a shorter, "
                "easier session or active recovery (walk, yoga)."
            )
        elif s.name == "Subjective":
            recs.append(
                "You've reported feeling tired in recent sessions. "
                "Listen to your body — back off if needed."
            )
    return recs


def assess_recovery(
    hrv_last_night: float | None = None,
    hrv_weekly_avg: float | None = None,
    sleep_score: float | None = None,
    sleep_duration_s: float | None = None,
    tsb: float | None = None,
    avg_stress: float | None = None,
    recent_feedback: list[WorkoutFeedback] | None = None,
    today: date | None = None,
) -> RecoveryAssessment:
    """Assess overall recovery from multiple signals.

    Args:
        hrv_last_night: Last night's HRV in ms.
        hrv_weekly_avg: 7-day HRV average in ms (baseline).
        sleep_score: Watch sleep score (0-100).
        sleep_duration_s: Sleep duration in seconds.
        tsb: Training Stress Balance.
        avg_stress: Watch average stress level (0-100).
        recent_feedback: Last few workout feedback entries.
        today: Current date (defaults to date.today()).

    Returns:
        RecoveryAssessment with overall score, signal breakdown, and recommendations.
    """
    if today is None:
        today = date.today()

    signals = [
        _score_hrv(hrv_last_night, hrv_weekly_avg),
        _score_sleep(sleep_score, sleep_duration_s),
        _score_tsb(tsb),
        _score_subjective(recent_feedback),
        _score_stress(avg_stress),
    ]

    overall = sum(s.score * _RECOVERY_WEIGHTS[s.name] for s in signals) * 100

    status: Literal["green", "yellow", "red"]
    if overall >= 70:
        status = "green"
    elif overall >= 40:
        status = "yellow"
    else:
        status = "red"

    # Summary based on status; only signals backed by data can be "the concern".
    measured = [s for s in signals if s.available]
    weak = [s for s in measured if s.score < 0.7]
    missing = [s.name for s in signals if not s.available]
    if not measured:
        summary = (
            "Not enough data to assess recovery (no HRV, sleep, stress, load or"
            " feedback). Go by feel and log how the session went."
        )
    elif not weak and missing:
        # Missing signals pull the overall score to neutral; what is measured is fine.
        summary = (
            f"Measured signals look good ({', '.join(s.name for s in measured)});"
            f" no data for {', '.join(missing)}. Go by feel for the rest."
        )
    elif status == "green":
        summary = "Well recovered. Proceed with planned training."
    elif status == "yellow":
        weakest = min(weak or measured, key=lambda s: s.score)
        summary = (
            f"Partially recovered — {weakest.name.lower()} is the main concern."
            " Consider reducing intensity."
        )
    else:
        weakest = min(weak or measured, key=lambda s: s.score)
        summary = (
            f"Recovery is poor — {weakest.name.lower()} signals caution."
            " Prioritize rest over training."
        )

    recommendations = _generate_recovery_recommendations(signals)

    return RecoveryAssessment(
        date=today,
        overall_score=round(overall, 1),
        status=status,
        signals=signals,
        summary=summary,
        recommendations=recommendations,
    )


# ── Adaptive recommendations ──


def recommend_adaptation(
    recovery: RecoveryAssessment,
    planned_workout: PlannedWorkout | None = None,
    profile: AthleteProfile | None = None,
    sport: SportKey | None = None,
) -> AdaptiveRecommendation:
    """Recommend a concrete workout adjustment based on recovery status.

    Args:
        recovery: Current recovery assessment.
        planned_workout: Today's planned workout from the active plan.
        profile: Athlete profile (for the sport's intensity suggestions).
        sport: Sport of the planned workout (its own ``sport`` when None); the
            sport plugin adapts the session (``Sport.adapt_workout``).

    Returns:
        AdaptiveRecommendation with action and concrete details.
    """
    if planned_workout is None:
        if recovery.status == "red":
            return AdaptiveRecommendation(
                action="rest_day",
                reasoning="No workout planned and recovery is poor. Take a full rest day.",
            )
        return AdaptiveRecommendation(
            action="proceed",
            reasoning="No workout planned today.",
        )

    sport = sport or planned_workout.sport
    if sport is None:
        raise ValueError("recommend_adaptation: the planned workout's sport is unknown")
    return get_sport(sport).adapt_workout(recovery, planned_workout, profile)
