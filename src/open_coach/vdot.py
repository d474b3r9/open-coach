"""Daniels-Gilbert VDOT calculation engine.

Implements the VO2/VDOT equations from Jack Daniels' Running Formula.
All calculations are pure math — no external API dependencies.

References:
- Daniels, J. & Gilbert, J. (1979). Oxygen Power.
- Daniels, J. (2014). Daniels' Running Formula, 3rd edition.
- https://vdoto2.com/Calculator
"""

from __future__ import annotations

import math

# Canonical race distances in meters (labels vary per surface; values do not).
HALF_MARATHON_M = 21097.5
MARATHON_M = 42195.0


def vo2_from_velocity(v_m_per_min: float) -> float:
    """Calculate oxygen cost (VO2) from running velocity.

    Args:
        v_m_per_min: Running velocity in meters per minute.

    Returns:
        VO2 in ml/kg/min.
    """
    return -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min**2


def vo2max_fraction(t_min: float) -> float:
    """Calculate the fraction of VO2max sustainable for a given duration.

    Args:
        t_min: Duration of effort in minutes.

    Returns:
        Fraction of VO2max (0.0 to 1.0+).
    """
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def calculate_vdot(distance_m: float, time_s: float) -> float:
    """Calculate VDOT from a race or time trial result.

    Args:
        distance_m: Race distance in meters.
        time_s: Finish time in seconds.

    Returns:
        VDOT value.

    Raises:
        ValueError: If distance or time is non-positive.
    """
    if distance_m <= 0 or time_s <= 0:
        raise ValueError("Distance and time must be positive.")

    t_min = time_s / 60.0
    v_m_per_min = distance_m / t_min

    vo2 = vo2_from_velocity(v_m_per_min)
    fraction = vo2max_fraction(t_min)

    return vo2 / fraction


def predict_time(vdot: float, distance_m: float) -> float:
    """Predict race time from VDOT and distance using bisection method.

    Args:
        vdot: The athlete's VDOT value.
        distance_m: Target race distance in meters.

    Returns:
        Predicted time in seconds.

    Raises:
        ValueError: If VDOT or distance is non-positive, or if solver fails.
    """
    if vdot <= 0 or distance_m <= 0:
        raise ValueError("VDOT and distance must be positive.")

    # Bisection: find t such that calculate_vdot(distance_m, t) == vdot
    # Search between 1 minute and 24 hours
    t_low = 60.0
    t_high = 86400.0

    # VDOT decreases as time increases (slower = lower VDOT for same distance)
    # So we look for the time where calculated VDOT matches target
    for _ in range(200):  # max iterations
        t_mid = (t_low + t_high) / 2.0
        computed_vdot = calculate_vdot(distance_m, t_mid)

        if abs(computed_vdot - vdot) < 0.001:
            return t_mid

        if computed_vdot > vdot:
            # Running too fast (time too short), increase time
            t_low = t_mid
        else:
            # Running too slow (time too long), decrease time
            t_high = t_mid

    raise ValueError(f"Bisection did not converge for VDOT={vdot}, distance={distance_m}m")


# ── Training paces from VDOT ──

# Daniels training intensity percentages of VDOT
# These define the pace zones as fractions of vVO2max
_ZONE_FRACTIONS = {
    "easy": (0.59, 0.74),
    "marathon": (0.75, 0.84),
    "threshold": (0.83, 0.88),
    "interval": (0.95, 1.00),
    "repetition": (1.00, 1.10),
}


def _velocity_from_vo2(vo2: float) -> float:
    """Inverse of vo2_from_velocity: find velocity for a given VO2.

    Uses quadratic formula on: VO2 = -4.60 + 0.182258*v + 0.000104*v²
    """
    a = 0.000104
    b = 0.182258
    c = -4.60 - vo2
    discriminant = b**2 - 4 * a * c
    if discriminant < 0:
        raise ValueError(f"No valid velocity for VO2={vo2}")
    return (-b + math.sqrt(discriminant)) / (2 * a)


def training_paces(vdot: float) -> dict[str, tuple[float, float]]:
    """Calculate Daniels training paces from VDOT.

    Args:
        vdot: The athlete's VDOT value.

    Returns:
        Dict mapping zone name to (min_pace_sec_per_km, max_pace_sec_per_km).
        min_pace is the faster pace (lower number), max_pace is the slower pace.
    """
    paces: dict[str, tuple[float, float]] = {}

    for zone_name, (low_frac, high_frac) in _ZONE_FRACTIONS.items():
        # VO2 at each intensity boundary
        vo2_low = vdot * low_frac  # lower intensity = slower
        vo2_high = vdot * high_frac  # higher intensity = faster

        # Velocity in m/min
        v_slow = _velocity_from_vo2(vo2_low)
        v_fast = _velocity_from_vo2(vo2_high)

        # Convert to sec/km (1000m / (v m/min) * 60 s/min)
        pace_slow = 1000.0 / v_slow * 60.0  # slower pace = higher number
        pace_fast = 1000.0 / v_fast * 60.0  # faster pace = lower number

        # min_pace = faster (lower), max_pace = slower (higher)
        paces[zone_name] = (pace_fast, pace_slow)

    return paces


def format_pace(seconds_per_km: float) -> str:
    """Format pace as an "M:SS" string (no unit suffix)."""
    minutes = int(seconds_per_km // 60)
    secs = int(seconds_per_km % 60)
    return f"{minutes}:{secs:02d}"


def format_time(total_seconds: float) -> str:
    """Format time as H:MM:SS or MM:SS string."""
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
