"""Race prediction, pacing strategy, and readiness assessment.

Pure computation — no I/O.  All watch data access happens in tools/race.py.

Provides:
- predict_race_times: VDOT-based predictions with TSB confidence intervals
- build_pacing_strategy: split-by-split pacing plans per distance
- assess_race_readiness: multi-component readiness scoring
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from open_coach.models import (
    AthleteProfile,
    PacingSplit,
    PacingStrategy,
    RacePrediction,
    RaceReadiness,
    ReadinessComponent,
    TrainingGoal,
    TrainingPlan,
)
from open_coach.sports.running import RUNNING, vdot_of
from open_coach.vdot import HALF_MARATHON_M, MARATHON_M, predict_time

# ── Standard race distances ──

STANDARD_DISTANCES: dict[str, float] = {
    "5K": 5000.0,
    "10K": 10000.0,
    "Half Marathon": HALF_MARATHON_M,
    "Marathon": MARATHON_M,
}


# ── Race predictions ──


def _confidence_band(tsb: float | None) -> tuple[float, float]:
    """Return (low_pct, high_pct) confidence multipliers based on TSB.

    low_pct  = fraction below predicted time (optimistic, faster)
    high_pct = fraction above predicted time (conservative, slower)
    """
    if tsb is None:
        return (0.04, 0.04)
    if tsb > 10:
        return (0.015, 0.015)
    if tsb >= 0:
        return (0.025, 0.025)
    if tsb >= -10:
        return (0.01, 0.04)
    return (0.01, 0.06)


def _endurance_penalty(ctl: float | None, distance_m: float) -> float:
    """Multiplier (>= 1.0) on predicted time: low chronic load penalizes long races.

    VDOT alone overestimates half/marathon performance when the aerobic base
    is thin. CTL ~50 is treated as an adequate base; the shortfall below that
    slows the prediction, twice as fast for the marathon, capped at +6%.
    """
    if ctl is None or distance_m < HALF_MARATHON_M:
        return 1.0
    shortfall = max(0.0, 50.0 - ctl)
    scale = 0.002 if distance_m >= 40_000 else 0.001  # marathon-and-up, with margin
    return min(1.06, 1.0 + shortfall * scale)


def predict_race_times(
    vdot: float,
    ctl: float | None = None,
    tsb: float | None = None,
    target_distance_m: float | None = None,
) -> list[RacePrediction]:
    """Predict race times for standard distances with confidence intervals.

    Args:
        vdot: Athlete's VDOT value.
        ctl: Chronic Training Load — low CTL slows half/marathon predictions.
        tsb: Training Stress Balance — drives confidence width.
        target_distance_m: Optional custom distance to include.

    Returns:
        List of RacePrediction for each distance.
    """
    distances = dict(STANDARD_DISTANCES)
    # Add custom distance if not already standard
    if target_distance_m is not None and not any(
        abs(target_distance_m - d) < 100 for d in distances.values()
    ):
        if target_distance_m < 5000:
            label = f"{target_distance_m / 1000:.1f}K"
        else:
            label = f"{target_distance_m / 1000:.0f}K"
        distances[label] = target_distance_m

    low_pct, high_pct = _confidence_band(tsb)

    predictions = []
    for label, dist_m in distances.items():
        predicted_s = predict_time(vdot, dist_m) * _endurance_penalty(ctl, dist_m)
        pace = predicted_s / (dist_m / 1000.0)
        predictions.append(
            RacePrediction(
                distance_label=label,
                distance_m=dist_m,
                predicted_time_s=predicted_s,
                confidence_low_s=predicted_s * (1 - low_pct),
                confidence_high_s=predicted_s * (1 + high_pct),
                predicted_pace_sec_per_km=pace,
            )
        )

    return predictions


# ── Pacing strategies ──

_STRATEGY_BY_DISTANCE: list[tuple[float, str]] = [
    (5000, "even_effort"),
    (10000, "slight_negative"),
    (HALF_MARATHON_M, "negative_split"),
    (MARATHON_M, "conservative_start"),
]


def _auto_strategy(distance_m: float) -> str:
    """Pick the best default strategy based on race distance."""
    for threshold, strategy in _STRATEGY_BY_DISTANCE:
        if distance_m <= threshold:
            return strategy
    return "conservative_start"


def _distance_label(distance_m: float) -> str:
    """Human-readable label for a distance."""
    for label, d in STANDARD_DISTANCES.items():
        if abs(distance_m - d) < 100:
            return label
    return f"{distance_m / 1000:.1f}K"


def _splits_from_configs(
    target_time_s: float,
    distance_m: float,
    configs: list[tuple[float, str, float, str]],
) -> list[PacingSplit]:
    """Build splits from (km, label, pace_adjustment, note) configs.

    The raw adjustments are re-centered so their km-weighted sum is zero,
    guaranteeing the cumulative time lands exactly on the target time.
    """
    total_km = distance_m / 1000.0
    avg_pace = target_time_s / total_km
    drift = sum(km * adj for km, _, adj, _ in configs) / total_km
    splits = []
    cumulative = 0.0
    for km, label, adj, note in configs:
        pace = avg_pace + adj - drift
        cumulative += km * pace
        splits.append(
            PacingSplit(
                split_km=km,
                split_label=label,
                target_pace_sec_per_km=round(pace, 1),
                cumulative_time_s=round(cumulative, 1),
                effort_note=note,
            )
        )
    return splits


def _build_5k(target_time_s: float, distance_m: float) -> list[PacingSplit]:
    """Per-km splits for a 5K (even effort with controlled start/finish kick)."""
    configs: list[tuple[float, str, float, str]] = [
        (1, "km 1", +4, "Controlled start — resist the adrenaline surge"),
        (1, "km 2", 0, "Settle into target rhythm"),
        (1, "km 3", 0, "Hold steady — halfway done"),
        (1, "km 4", 0, "Stay relaxed, maintain form"),
        (distance_m / 1000 - 4, "km 5", -3, "Push to the line — empty the tank"),
    ]
    return _splits_from_configs(target_time_s, distance_m, configs)


def _build_10k(target_time_s: float, distance_m: float) -> list[PacingSplit]:
    """Per-km splits for a 10K (slight negative)."""
    configs: list[tuple[float, str, float, str]] = [
        (1, "km 1", +3, "Ease in — don't chase the pack"),
        (1, "km 2", +3, "Find your rhythm, stay patient"),
        (1, "km 3", 0, "Lock into target pace"),
        (1, "km 4", 0, "Smooth and steady"),
        (1, "km 5", 0, "Halfway — you're on track"),
        (1, "km 6", 0, "Hold form, stay relaxed"),
        (1, "km 7", 0, "Last 3K — time to work"),
        (1, "km 8", -2, "Start building — slight push"),
        (1, "km 9", -3, "Commit to the effort"),
        (distance_m / 1000 - 9, "km 10", -4, "All out to the finish"),
    ]
    return _splits_from_configs(target_time_s, distance_m, configs)


def _build_half(target_time_s: float, distance_m: float) -> list[PacingSplit]:
    """5K-block splits for a half marathon (negative split)."""
    configs: list[tuple[float, str, float, str]] = [
        (5.0, "0-5K", +5, "Conservative — bank nothing, stay easy"),
        (5.0, "5-10K", 0, "Settle into target pace"),
        (5.0, "10-15K", 0, "Rhythm cruise — halfway there"),
        (5.0, "15-20K", -3, "Time to push — run the second half with your heart"),
        (distance_m / 1000 - 20, "20K-finish", -5, "Leave everything on the course"),
    ]
    return _splits_from_configs(target_time_s, distance_m, configs)


def _build_marathon(target_time_s: float, distance_m: float) -> list[PacingSplit]:
    """5K-block splits for a marathon (conservative start)."""
    configs: list[tuple[float, str, float, str]] = [
        (5.0, "0-5K", +9, "Banking time is a myth — stay patient"),
        (5.0, "5-10K", 0, "Find your groove, eat/drink early"),
        (5.0, "10-15K", 0, "Smooth rhythm — enjoy the crowd"),
        (5.0, "15-20K", 0, "Halfway — stay on plan, fueling on schedule"),
        (5.0, "20-25K", 0, "Keep form, stay present"),
        (5.0, "25-30K", 0, "This is where it starts — stay strong mentally"),
        (5.0, "30-35K", 0, "The real marathon begins here — hold pace"),
        (5.0, "35-40K", -3, "If legs respond, push gently; if not, hold on"),
        (distance_m / 1000 - 40, "40K-finish", -5, "Everything you've got — the finish is yours"),
    ]
    return _splits_from_configs(target_time_s, distance_m, configs)


def _build_even_splits(target_time_s: float, distance_m: float) -> list[PacingSplit]:
    """Fallback: per-km even splits for any distance."""
    total_km = distance_m / 1000.0
    full_kms = int(total_km)
    remainder = total_km - full_kms
    avg_pace = target_time_s / total_km

    splits = []
    cumulative = 0.0
    for i in range(full_kms):
        cumulative += avg_pace
        splits.append(
            PacingSplit(
                split_km=1.0,
                split_label=f"km {i + 1}",
                target_pace_sec_per_km=round(avg_pace, 1),
                cumulative_time_s=round(cumulative, 1),
                effort_note="Even effort" if i < full_kms - 1 else "Push to finish",
            )
        )
    if remainder > 0.01:
        cumulative += remainder * avg_pace
        splits.append(
            PacingSplit(
                split_km=round(remainder, 3),
                split_label=f"final {remainder * 1000:.0f}m",
                target_pace_sec_per_km=round(avg_pace, 1),
                cumulative_time_s=round(cumulative, 1),
                effort_note="Finish strong",
            )
        )
    return splits


_GUIDANCE = {
    "5K": [
        "Warm up 10-15 min with strides before the start.",
        "Don't chase others in km 1 — most runners go out too fast.",
        "Focus on cadence and breathing through km 2-4.",
        "Last 200m: arms drive the legs — sprint if you can.",
    ],
    "10K": [
        "Warm up 10 min with 3-4 strides.",
        "First 2K are an investment — patience pays at 8K.",
        "Take water at 5K if warm, but don't stop for it.",
        "Km 8-10: relax your shoulders, shorten your stride slightly to push.",
    ],
    "Half Marathon": [
        "Run the first half with your head, the second half with your heart.",
        "Take a gel at 30 min and again at 60 min.",
        "Don't chase a time split at 10K — trust the process.",
        "Km 18-21: focus on one km at a time, not the distance left.",
        "Practice this pacing strategy in a long run before race day.",
    ],
    "Marathon": [
        "Banking time early in a marathon never works — trust the data.",
        "Fuel every 30-40 min from the start (don't wait until you're hungry).",
        "Walk aid stations if needed in the first half — the seconds don't matter.",
        "30-35K is the real start of the marathon. Everything before is a warmup.",
        "If you hit the wall at 35K, slow down 10-15 sec/km — don't stop.",
    ],
}

_DEFAULT_GUIDANCE = [
    "Warm up 10-15 min before the start.",
    "Start conservatively and build into the race.",
    "Stay hydrated and fuel appropriately for the distance.",
]


def build_pacing_strategy(
    distance_m: float,
    target_time_s: float,
    strategy: str = "auto",
) -> PacingStrategy:
    """Build a split-by-split pacing strategy for a race.

    Args:
        distance_m: Race distance in meters.
        target_time_s: Target finish time in seconds.
        strategy: "auto" (recommended), "even_effort", "slight_negative",
                  "negative_split", "conservative_start", or "even_split".

    Returns:
        PacingStrategy with splits and coaching guidance.
    """
    if strategy == "auto":
        strategy = _auto_strategy(distance_m)

    label = _distance_label(distance_m)

    # Build splits based on strategy + distance
    if strategy == "even_effort" and abs(distance_m - 5000) < 500:
        splits = _build_5k(target_time_s, distance_m)
    elif strategy == "slight_negative" and abs(distance_m - 10000) < 500:
        splits = _build_10k(target_time_s, distance_m)
    elif strategy == "negative_split" and abs(distance_m - HALF_MARATHON_M) < 500:
        splits = _build_half(target_time_s, distance_m)
    elif strategy == "conservative_start" and abs(distance_m - MARATHON_M) < 500:
        splits = _build_marathon(target_time_s, distance_m)
    else:
        splits = _build_even_splits(target_time_s, distance_m)

    guidance = _GUIDANCE.get(label, _DEFAULT_GUIDANCE)

    return PacingStrategy(
        distance_label=label,
        distance_m=distance_m,
        strategy_name=strategy,
        target_time_s=target_time_s,
        splits=splits,
        key_guidance=guidance,
    )


# ── Race readiness assessment ──

# CTL thresholds per distance: (ready, caution)
_CTL_THRESHOLDS: list[tuple[float, int, int]] = [
    (5000, 30, 20),
    (10000, 35, 25),
    (HALF_MARATHON_M, 45, 35),
    (MARATHON_M, 55, 45),
]

# Long run thresholds per distance: (ready_km, caution_km)
_LONG_RUN_THRESHOLDS: list[tuple[float, float, float]] = [
    (HALF_MARATHON_M, 16.0, 12.0),
    (MARATHON_M, 30.0, 25.0),
]


def _ctl_thresholds(distance_m: float) -> tuple[int, int]:
    """Return (ready, caution) CTL thresholds for a distance."""
    for d, ready, caution in _CTL_THRESHOLDS:
        if distance_m <= d:
            return ready, caution
    return 55, 45


def _score_vdot(profile: AthleteProfile, goal: TrainingGoal) -> ReadinessComponent:
    """Score VDOT fitness vs target time."""
    vdot = vdot_of(profile)
    if vdot is None:
        return ReadinessComponent(
            name="VDOT Fitness",
            score=0.3,
            status="not_ready",
            detail="No VDOT data — run onboarding or enter a race result.",
        )

    if goal.target_time_s is None:
        return ReadinessComponent(
            name="VDOT Fitness",
            score=0.8,
            status="ready",
            detail=f"VDOT {vdot:.1f} — no target time set to compare against.",
        )

    predicted_s = predict_time(vdot, goal.distance_m)
    gap_pct = (predicted_s - goal.target_time_s) / goal.target_time_s

    if gap_pct <= 0:
        return ReadinessComponent(
            name="VDOT Fitness",
            score=1.0,
            status="ready",
            detail=(
                f"VDOT predicts {predicted_s:.0f}s"
                f" — faster than your {goal.target_time_s:.0f}s target."
            ),
        )
    if gap_pct <= 0.03:
        return ReadinessComponent(
            name="VDOT Fitness",
            score=0.7,
            status="caution",
            detail=(
                f"VDOT predicts {predicted_s:.0f}s — close to target but will require a good day."
            ),
        )
    if gap_pct <= 0.06:
        return ReadinessComponent(
            name="VDOT Fitness",
            score=0.4,
            status="not_ready",
            detail=f"VDOT predicts {predicted_s:.0f}s — target is ambitious, consider adjusting.",
        )
    return ReadinessComponent(
        name="VDOT Fitness",
        score=0.2,
        status="not_ready",
        detail=f"VDOT predicts {predicted_s:.0f}s — target unlikely at current fitness.",
    )


def _score_ctl(profile: AthleteProfile, goal: TrainingGoal) -> ReadinessComponent:
    """Score CTL fitness level for the target distance."""
    if profile.ctl is None:
        return ReadinessComponent(
            name="CTL Fitness",
            score=0.3,
            status="not_ready",
            detail="No training load data available.",
        )

    ready, caution = _ctl_thresholds(goal.distance_m)

    if profile.ctl >= ready:
        return ReadinessComponent(
            name="CTL Fitness",
            score=1.0,
            status="ready",
            detail=f"CTL {profile.ctl:.0f} — solid training base for this distance.",
        )
    if profile.ctl >= caution:
        return ReadinessComponent(
            name="CTL Fitness",
            score=0.6,
            status="caution",
            detail=f"CTL {profile.ctl:.0f} — adequate but could be higher for this distance.",
        )
    return ReadinessComponent(
        name="CTL Fitness",
        score=0.3,
        status="not_ready",
        detail=f"CTL {profile.ctl:.0f} — training volume is low for this distance.",
    )


def _score_tsb(profile: AthleteProfile) -> ReadinessComponent:
    """Score TSB form (freshness)."""
    if profile.tsb is None:
        return ReadinessComponent(
            name="TSB Form",
            score=0.5,
            status="caution",
            detail="No TSB data — cannot assess freshness.",
        )

    tsb = profile.tsb
    if 5 <= tsb <= 20:
        return ReadinessComponent(
            name="TSB Form",
            score=1.0,
            status="ready",
            detail=f"TSB {tsb:+.0f} — tapered and fresh, ideal for racing.",
        )
    if 0 <= tsb < 5:
        return ReadinessComponent(
            name="TSB Form",
            score=0.7,
            status="caution",
            detail=f"TSB {tsb:+.0f} — reasonably fresh.",
        )
    if 20 < tsb <= 30:
        return ReadinessComponent(
            name="TSB Form",
            score=0.6,
            status="caution",
            detail=f"TSB {tsb:+.0f} — very rested, may have lost some sharpness.",
        )
    if -5 <= tsb < 0:
        return ReadinessComponent(
            name="TSB Form",
            score=0.5,
            status="caution",
            detail=f"TSB {tsb:+.0f} — slightly fatigued.",
        )
    if tsb > 30:
        return ReadinessComponent(
            name="TSB Form",
            score=0.4,
            status="caution",
            detail=f"TSB {tsb:+.0f} — long rest period, fitness may have declined.",
        )
    # tsb < -5
    return ReadinessComponent(
        name="TSB Form",
        score=0.3,
        status="not_ready",
        detail=f"TSB {tsb:+.0f} — carrying significant fatigue, consider more rest.",
    )


def _score_completion(plan: TrainingPlan | None, today: date) -> ReadinessComponent:
    """Score training plan completion rate."""
    if plan is None:
        return ReadinessComponent(
            name="Training Completion",
            score=0.5,
            status="caution",
            detail="No structured plan to evaluate.",
        )

    total = 0
    completed = 0
    for week in plan.weeks:
        if week.start_date > today:
            break
        for w in week.workouts:
            if w.date <= today:
                total += 1
                if w.completed:
                    completed += 1

    if total == 0:
        return ReadinessComponent(
            name="Training Completion",
            score=0.5,
            status="caution",
            detail="Plan just started — no data yet.",
        )

    rate = completed / total
    status: Literal["ready", "caution", "not_ready"]
    if rate >= 0.85:
        score, status = 1.0, "ready"
        detail = f"{rate:.0%} completion — consistent training."
    elif rate >= 0.70:
        score, status = 0.7, "caution"
        detail = f"{rate:.0%} completion — some missed sessions."
    elif rate >= 0.50:
        score, status = 0.4, "not_ready"
        detail = f"{rate:.0%} completion — significant gaps in training."
    else:
        score, status = 0.2, "not_ready"
        detail = f"{rate:.0%} completion — majority of training missed."

    return ReadinessComponent(name="Training Completion", score=score, status=status, detail=detail)


def _score_long_run(profile: AthleteProfile, goal: TrainingGoal) -> ReadinessComponent:
    """Score long run readiness for the target distance."""
    # For short distances, long runs are less critical
    if goal.distance_m <= 10500:
        return ReadinessComponent(
            name="Long Run Readiness",
            score=0.9,
            status="ready",
            detail="Short distance — long run preparation is not a limiting factor.",
        )

    pattern = profile.sport_profile(RUNNING).training_pattern
    if pattern is None:
        return ReadinessComponent(
            name="Long Run Readiness",
            score=0.5,
            status="caution",
            detail="No training pattern data to assess long run readiness.",
        )

    avg_km = pattern.long_session_avg_distance_m / 1000

    for d, ready_km, caution_km in _LONG_RUN_THRESHOLDS:
        if goal.distance_m <= d + 500:
            if avg_km >= ready_km:
                return ReadinessComponent(
                    name="Long Run Readiness",
                    score=1.0,
                    status="ready",
                    detail=f"Long run average {avg_km:.0f} km — well prepared.",
                )
            if avg_km >= caution_km:
                return ReadinessComponent(
                    name="Long Run Readiness",
                    score=0.6,
                    status="caution",
                    detail=f"Long run average {avg_km:.0f} km — slightly below ideal.",
                )
            return ReadinessComponent(
                name="Long Run Readiness",
                score=0.3,
                status="not_ready",
                detail=f"Long run average {avg_km:.0f} km — insufficient for this distance.",
            )

    # Fallback for ultra distances
    return ReadinessComponent(
        name="Long Run Readiness",
        score=0.5,
        status="caution",
        detail=f"Long run average {avg_km:.0f} km — verify preparation for this distance.",
    )


_WEIGHTS = {
    "VDOT Fitness": 0.30,
    "CTL Fitness": 0.25,
    "TSB Form": 0.20,
    "Training Completion": 0.15,
    "Long Run Readiness": 0.10,
}


def _generate_recommendations(components: list[ReadinessComponent]) -> list[str]:
    """Generate actionable recommendations from weak components."""
    recs = []
    for c in components:
        if c.score >= 0.7:
            continue
        if c.name == "VDOT Fitness":
            recs.append(
                "Your VDOT suggests the target may be ambitious. Consider a more"
                " conservative goal or race a shorter distance to build confidence."
            )
        elif c.name == "CTL Fitness":
            recs.append(
                "Training volume is below ideal."
                " Focus on consistent easy runs to build your aerobic base."
            )
        elif c.name == "TSB Form":
            if c.score <= 0.3:
                recs.append(
                    "You're carrying fatigue."
                    " Prioritize rest and easy running in the days before the race."
                )
            else:
                recs.append(
                    "Your freshness could be better."
                    " Ensure you taper properly in the final 7-10 days."
                )
        elif c.name == "Training Completion":
            recs.append(
                "Training consistency has been low. Focus on completing the"
                " remaining planned sessions without adding intensity."
            )
        elif c.name == "Long Run Readiness":
            recs.append(
                "Your longest runs may be insufficient. Try to complete at least"
                " one more long run at near-race distance if time allows."
            )
    return recs


def assess_race_readiness(
    profile: AthleteProfile,
    goal: TrainingGoal,
    plan: TrainingPlan | None = None,
    today: date | None = None,
) -> RaceReadiness:
    """Assess overall race readiness from multiple components.

    Args:
        profile: Athlete profile with VDOT, CTL/ATL/TSB, training pattern.
        goal: Target race goal.
        plan: Active training plan (optional).
        today: Current date (defaults to date.today()).

    Returns:
        RaceReadiness with overall score, component breakdown, and recommendations.
    """
    if today is None:
        today = date.today()

    components = [
        _score_vdot(profile, goal),
        _score_ctl(profile, goal),
        _score_tsb(profile),
        _score_completion(plan, today),
        _score_long_run(profile, goal),
    ]

    overall = sum(c.score * _WEIGHTS[c.name] for c in components)

    status: Literal["ready", "caution", "not_ready"]
    if overall >= 0.75:
        status = "ready"
    elif overall >= 0.50:
        status = "caution"
    else:
        status = "not_ready"

    # Build summary from strongest and weakest components
    weakest = min(components, key=lambda c: c.score)
    if status == "ready":
        summary = f"You're in good shape for your {_distance_label(goal.distance_m)}."
        if weakest.score < 0.7:
            summary += f" Watch out: {weakest.detail.lower()}"
    elif status == "caution":
        summary = (
            f"You can race your {_distance_label(goal.distance_m)},"
            f" but there are areas to address. {weakest.detail}"
        )
    else:
        summary = (
            f"Your preparation for the {_distance_label(goal.distance_m)} has gaps."
            f" {weakest.detail}"
        )

    recommendations = _generate_recommendations(components)

    days_to_race = (goal.race_date - today).days if goal.race_date else None

    return RaceReadiness(
        overall_score=round(overall, 3),
        overall_status=status,
        summary=summary,
        components=components,
        recommendations=recommendations,
        days_to_race=days_to_race,
    )
