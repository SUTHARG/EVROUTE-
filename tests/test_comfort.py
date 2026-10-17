"""Unit tests for comfort model and premature-stop penalty."""

from core.comfort import compute_dwell_discomfort


def test_dwell_window_penalty_piecewise_linear():
    """Verify dwell window penalty is 0 in [20, 40] min and grows linearly outside it."""
    amenity_score = 1.0  # Perfect amenities to isolate window penalty
    fixed_penalty = 5.0

    # 1. Inside sweet spot (e.g. 25 min, 30 min, 35 min) -> penalty is only fixed overhead
    d_25 = compute_dwell_discomfort(25.0, amenity_score, is_real_charge=True, arrival_soc=0.20)
    d_30 = compute_dwell_discomfort(30.0, amenity_score, is_real_charge=True, arrival_soc=0.20)
    assert d_25 == fixed_penalty
    assert d_30 == fixed_penalty

    # 2. Too short (<20 min) -> window penalty 1.0 * (20 - t)
    d_10 = compute_dwell_discomfort(10.0, amenity_score, is_real_charge=True, arrival_soc=0.20)
    expected_10 = fixed_penalty + 1.0 * (20.0 - 10.0)
    assert d_10 == expected_10

    # 3. Too long (>40 min) -> window penalty 1.5 * (t - 40)
    d_50 = compute_dwell_discomfort(50.0, amenity_score, is_real_charge=True, arrival_soc=0.20)
    expected_50 = fixed_penalty + 1.5 * (50.0 - 40.0)
    assert d_50 == expected_50


def test_soft_premature_stop_penalty_only_on_real_charge():
    """Verify premature stop penalty applies only when charging, not on pass-through."""
    gamma = 80.0
    stop_threshold = 0.70

    # Case A: Real charge with arrival SoC 0.85 (>0.70)
    d_charge = compute_dwell_discomfort(
        dwell_min=25.0,
        amenity_score=0.50,
        is_real_charge=True,
        arrival_soc=0.85,
        stop_threshold_soc=stop_threshold,
        gamma=gamma,
    )
    premature_component = gamma * (0.85 - stop_threshold)
    expected_exact_sum = 25.0 * (1.0 - 0.50) + 0.0 + 5.0 + premature_component
    assert d_charge == expected_exact_sum
    assert d_charge == 29.5

    # Case B: Pass-through (is_real_charge=False) -> penalty must be strictly 0.0
    d_pass = compute_dwell_discomfort(
        dwell_min=0.0,
        amenity_score=0.50,
        is_real_charge=False,
        arrival_soc=0.85,
        stop_threshold_soc=stop_threshold,
        gamma=gamma,
    )
    assert d_pass == 0.0
