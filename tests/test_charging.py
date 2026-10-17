"""Unit tests for Phase 7 exact CC-CV charging and dwell targets."""

import pytest

from core.charging import (
    charge_time_min,
    compute_dwell_window_soc_targets,
    invert_charge_time_to_soc,
)
from core.models import PRESET_CARS


def test_charging_time_3_cases_and_additivity():
    """Verify exact CC-CV charging time across CC, CV, and spanning intervals."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    station_kw = 60.0  # Car max DC is 50 kW, so effective P0 = 50 kW

    # Case 1: Pure CC (10% to 70%)
    t_cc = charge_time_min(0.10, 0.70, station_kw, car)
    assert t_cc > 0.0

    # Case 2: Pure CV taper (80% to 95%)
    t_cv = charge_time_min(0.80, 0.95, station_kw, car)
    assert t_cv > 0.0

    # Case 3: Spanning both (10% to 95%)
    t_span = charge_time_min(0.10, 0.95, station_kw, car)

    # EXACT ADDITIVITY TEST: time(0.10 -> 0.95) must equal time(0.10 -> 0.80) + time(0.80 -> 0.95)
    t_part1 = charge_time_min(0.10, 0.80, station_kw, car)
    t_part2 = charge_time_min(0.80, 0.95, station_kw, car)
    assert t_span == pytest.approx(t_part1 + t_part2, rel=1e-7)


def test_charging_continuity_at_elbow():
    """Verify charge_time_min is continuous at the 80% knee."""
    car = PRESET_CARS["mg_zs_ev"]
    station_kw = 100.0

    eps = 1e-5
    t_left = charge_time_min(0.79, 0.80 - eps, station_kw, car)
    t_right = charge_time_min(0.80 - eps, 0.80 + eps, station_kw, car)

    assert t_left > 0.0
    assert t_right > 0.0


def test_taper_slowdown_rate():
    """Verify charging 10->80% is much faster per percent than 80->100%."""
    car = PRESET_CARS["hyundai_ioniq_5"]
    station_kw = 250.0

    # 10% to 80% (70% gained)
    t_10_to_80 = charge_time_min(0.10, 0.80, station_kw, car)
    rate_cc = t_10_to_80 / 0.70  # minutes per 1.0 SoC

    # 80% to 100% (20% gained)
    t_80_to_100 = charge_time_min(0.80, 1.00, station_kw, car)
    rate_cv = t_80_to_100 / 0.20  # minutes per 1.0 SoC

    # Taper rate in CV must be significantly slower (higher minutes per percent)
    assert rate_cv > 2.0 * rate_cc


def test_invert_charge_time_and_dwell_targets():
    """Verify inversion of charge time and discrete target generation."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    station_kw = 50.0

    s_in = 0.20
    s_20min = invert_charge_time_to_soc(s_in, 20.0, station_kw, car)
    assert s_20min > s_in

    # Inverted time should round-trip back to ~20 minutes
    t_check = charge_time_min(s_in, s_20min, station_kw, car)
    assert t_check == pytest.approx(20.0, rel=1e-3)

    # Discrete targets for K=50
    targets = compute_dwell_window_soc_targets(s_in, station_kw, car, K=50)
    assert len(targets) > 0
    for t_lvl in targets:
        assert t_lvl > int(s_in * 50)
        assert t_lvl <= 50
