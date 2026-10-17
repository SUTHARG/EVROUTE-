"""Comfort model, piecewise-linear dwell window penalty, and soft premature-stop penalty."""

from __future__ import annotations


def compute_dwell_discomfort(
    dwell_min: float,
    amenity_score: float,
    is_real_charge: bool = True,
    arrival_soc: float = 0.0,
    stop_threshold_soc: float = 0.35,
    gamma: float = 80.0,
    fixed_stop_penalty_min: float = 5.0,
    window_under_slope: float = 1.0,
    window_over_slope: float = 1.5,
) -> float:
    """Compute total discomfort penalty in equivalent minutes for a charging stop.

    Components:
    1. Base dwell discomfort: dwell_min * (1.0 - amenity_score)
    2. Piecewise-linear dwell window penalty:
       - 0.0 if dwell_min in [20, 40] minutes (ideal rest duration)
       - window_under_slope * (20 - dwell_min) if dwell_min < 20 (too rushed)
       - window_over_slope * (dwell_min - 40) if dwell_min > 40 (excessively boring)
    3. Fixed stop penalty: fixed_stop_penalty_min (overhead of highway exit, parking, plug-in)
    4. Soft premature-stop penalty:
       - APPLIES ONLY ON REAL CHARGING TRANSITIONS (is_real_charge=True).
       - Zero on zero-cost pass-through transitions.
       - gamma * max(0.0, arrival_soc - stop_threshold_soc) in discomfort-minutes.

    Complexity:
        Time: O(1)
        Space: O(1)

    Args:
        dwell_min: Time spent at station in minutes.
        amenity_score: Normalized station comfort score in [0.0, 1.0].
        is_real_charge: True if vehicle recharged, False if passing through without charging.
        arrival_soc: Battery SoC fraction upon arrival in [0, 1].
        stop_threshold_soc: Preferred maximum arrival SoC to trigger a charging stop.
        gamma: Discomfort penalty factor per unit SoC above stop_threshold_soc (default ~80).
        fixed_stop_penalty_min: Fixed overhead penalty per stop in minutes.
        window_under_slope: Penalty slope for dwell < 20 min.
        window_over_slope: Penalty slope for dwell > 40 min.

    Returns:
        Total discomfort in equivalent minutes.
    """
    if not is_real_charge or dwell_min <= 0.0:
        return 0.0

    # 1. Base amenity-scaled dwell discomfort
    base_discomfort = dwell_min * max(0.0, 1.0 - amenity_score)

    # 2. Piecewise-linear dwell window penalty
    if dwell_min < 20.0:
        window_penalty = window_under_slope * (20.0 - dwell_min)
    elif dwell_min > 40.0:
        window_penalty = window_over_slope * (dwell_min - 40.0)
    else:
        window_penalty = 0.0

    # 3. Soft premature stop penalty (only on real charging stops)
    if arrival_soc > stop_threshold_soc:
        premature_penalty = gamma * (arrival_soc - stop_threshold_soc)
    else:
        premature_penalty = 0.0

    return base_discomfort + window_penalty + fixed_stop_penalty_min + premature_penalty
