"""Exact piecewise CC-CV EV charging model with analytical logarithmic integration.

Implements exact closed-form integration for battery charging times without
numerical step approximation, handling all three regimes:
1. Pure Constant Current (CC, SoC <= 80%)
2. Pure Constant Voltage (CV, SoC >= 80% with linear power taper down to 10%)
3. Spanning both regimes (split at exactly 80%)
"""

from __future__ import annotations

import math

from core.models import Car

ELBOW_SOC: float = 0.80


def charge_time_min(
    s_in: float,
    s_out: float,
    station_max_kw: float,
    car: Car,
) -> float:
    """Compute exact duration in minutes required to charge battery from s_in to s_out.

    The charging curve is defined piecewise:
    - For s in [0.0, 0.80] (Constant Current):
        P(s) = P0 = min(station_max_kw, car.max_dc_kw)
        dt = (E_usable * ds) / P0
    - For s in [0.80, 1.00] (Constant Voltage taper down to 0.10 * P0):
        P(s) = P0 * (1 - (0.90 / 0.20) * (s - 0.80)) = P0 * (4.60 - 4.50 * s)
        dt = (E_usable * ds) / (P0 * (4.60 - 4.50 * s))
        Exact closed-form integral:
        dt = (E_usable / (4.50 * P0)) * ln((4.60 - 4.50 * s_a) / (4.60 - 4.50 * s_b))

    Complexity:
        Time: O(1)
        Space: O(1)

    Args:
        s_in: Initial arrival SoC fraction in [0, 1].
        s_out: Target departure SoC fraction in [0, 1].
        station_max_kw: Peak charger output power in kW.
        car: Vehicle profile defining usable_battery_kwh and max_dc_kw.

    Returns:
        Exact charging time in minutes. Returns 0.0 if s_out <= s_in.
    """
    if s_out <= s_in:
        return 0.0

    s_a = max(0.0, min(1.0, s_in))
    s_b = max(0.0, min(1.0, s_out))

    e_usable = car.usable_battery_kwh
    p0 = min(station_max_kw, car.max_dc_kw)
    if p0 <= 0.0:
        return float("inf")

    # Case 1: Pure Constant Current (s_b <= 0.80)
    if s_b <= ELBOW_SOC:
        hours = (e_usable * (s_b - s_a)) / p0
        return hours * 60.0

    # Case 2: Pure Constant Voltage taper (s_a >= 0.80)
    if s_a >= ELBOW_SOC:
        term_a = 4.60 - 4.50 * s_a
        term_b = max(0.05, 4.60 - 4.50 * s_b)
        hours = (e_usable / (4.50 * p0)) * math.log(term_a / term_b)
        return hours * 60.0

    # Case 3: Spanning both CC and CV regimes (s_a < 0.80 < s_b)
    # Split exactly at 0.80
    hours_cc = (e_usable * (ELBOW_SOC - s_a)) / p0
    term_elbow = 4.60 - 4.50 * ELBOW_SOC  # = 1.00
    term_b = max(0.05, 4.60 - 4.50 * s_b)
    hours_cv = (e_usable / (4.50 * p0)) * math.log(term_elbow / term_b)
    return (hours_cc + hours_cv) * 60.0


def invert_charge_time_to_soc(
    s_in: float,
    target_dwell_min: float,
    station_max_kw: float,
    car: Car,
) -> float:
    """Compute departure SoC achieved after exactly target_dwell_min minutes of charging.

    Analytical inversion of the piecewise CC-CV charging time integral.

    Complexity:
        Time: O(1)
        Space: O(1)

    Args:
        s_in: Starting SoC fraction in [0, 1].
        target_dwell_min: Available charging duration in minutes.
        station_max_kw: Peak charger output power in kW.
        car: Vehicle profile.

    Returns:
        Resulting SoC fraction clamped to [s_in, 1.0].
    """
    if target_dwell_min <= 0.0:
        return s_in

    e_usable = car.usable_battery_kwh
    p0 = min(station_max_kw, car.max_dc_kw)
    target_hours = target_dwell_min / 60.0

    # Time needed to reach 0.80 from s_in
    if s_in < ELBOW_SOC:
        hours_to_elbow = (e_usable * (ELBOW_SOC - s_in)) / p0
        if target_hours <= hours_to_elbow:
            # Reached within CC region
            return min(ELBOW_SOC, s_in + (target_hours * p0) / e_usable)
        # Consumes hours_to_elbow in CC, remainder in CV
        remain_hours = target_hours - hours_to_elbow
        s_curr = ELBOW_SOC
    else:
        remain_hours = target_hours
        s_curr = s_in

    # Invert CV logarithmic integral:
    # remain_hours = (e_usable / (4.50 * p0)) * ln(term_curr / term_out)
    # => term_out = term_curr * exp(- (4.50 * p0 * remain_hours) / e_usable)
    term_curr = 4.60 - 4.50 * s_curr
    exponent = -(4.50 * p0 * remain_hours) / e_usable
    term_out = term_curr * math.exp(exponent)
    # term_out = 4.60 - 4.50 * s_out => s_out = (4.60 - term_out) / 4.50
    s_out = (4.60 - term_out) / 4.50
    return min(1.0, max(s_in, s_out))


def compute_dwell_window_soc_targets(
    s_in: float,
    station_max_kw: float,
    car: Car,
    K: int = 100,
) -> list[int]:
    """Compute floor and ceil discrete levels for 20-min and 40-min dwell sweet spot.

    Complexity: O(1).

    Returns:
        List of integer departure levels in {0, ..., K}.
    """
    targets: set[int] = set()

    for dwell_m in (20.0, 40.0):
        soc_val = invert_charge_time_to_soc(s_in, dwell_m, station_max_kw, car)
        lvl_floor = math.floor(soc_val * K)
        lvl_ceil = math.ceil(soc_val * K)
        in_lvl = math.floor(s_in * K)

        if lvl_floor > in_lvl:
            targets.add(min(K, lvl_floor))
        if lvl_ceil > in_lvl:
            targets.add(min(K, lvl_ceil))

    return sorted(targets)
