"""Physics-based EV energy consumption and battery simulation module for Route.ev.

Implements aerodynamic drag, rolling resistance with calibration against rated
consumption, gravitational potential energy with asymmetric regenerative braking,
prefix-checked battery feasibility, and 100% SoC clamping.
"""

from __future__ import annotations

from core.models import Car, RoadEdge

# Physical constants
GRAVITY_M_S2: float = 9.80665
AIR_DENSITY_KG_M3: float = 1.225
JOULES_PER_KWH: float = 3_600_000.0
REFERENCE_SPEED_KMH: float = 70.0


def calibrate_crr(
    car: Car,
    v_ref_kmh: float = REFERENCE_SPEED_KMH,
    rho_air: float = AIR_DENSITY_KG_M3,
) -> float:
    """Calibrate rolling resistance coefficient (Crr) from rated consumption.

    Calibrates Crr so that at reference speed on a level road (delta_h = 0),
    the total electrical energy consumed matches car.consumption_kwh_per_km.
    Crr also absorbs ambient chassis friction and baseline auxiliary loads.

    Complexity:
        Time: O(1)
        Space: O(1)

    Args:
        car: Vehicle profile with mass, Cd, frontal area, efficiency, and rated consumption.
        v_ref_kmh: Reference vehicle speed in km/h (default 70 km/h).
        rho_air: Ambient air density in kg/m^3 (default 1.225 kg/m^3).

    Returns:
        Calibrated dimensionless rolling resistance coefficient (Crr >= 0.005).
    """
    v_ref = v_ref_kmh / 3.6  # convert to m/s
    # Total electrical work demanded per meter (Joules/m)
    w_elec_per_m = (car.consumption_kwh_per_km * JOULES_PER_KWH) / 1000.0

    # Subtract baseline auxiliary load if any
    if car.auxiliary_power_kw > 0.0 and v_ref > 0.0:
        w_aux_per_m = (car.auxiliary_power_kw * 1000.0) / v_ref
        w_traction_elec_per_m = max(0.0, w_elec_per_m - w_aux_per_m)
    else:
        w_traction_elec_per_m = w_elec_per_m

    # Mechanical work demanded at wheels per meter
    w_mech_per_m = w_traction_elec_per_m * car.drivetrain_efficiency

    # Aerodynamic drag force at v_ref (Newtons)
    f_aero = 0.5 * rho_air * car.drag_coefficient * car.frontal_area_m2 * (v_ref**2)

    # Residual mechanical force supplied by rolling resistance
    f_roll = w_mech_per_m - f_aero

    # Normal force = m * g
    f_normal = car.mass_kg * GRAVITY_M_S2

    crr = f_roll / f_normal
    # Enforce realistic lower bound for automotive radial tires
    return max(0.005, crr)


def edge_energy_kwh(
    car: Car,
    length_m: float,
    time_s: float,
    elevation_gain_m: float,
    crr: float | None = None,
    rho_air: float = AIR_DENSITY_KG_M3,
) -> float:
    """Compute electrical energy consumed across a single directed road edge.

    Energy accounts for rolling resistance, aerodynamic drag at edge speed,
    gravitational work (m * g * delta_h), and asymmetric regenerative braking.
    Downhill edges with net negative work yield negative kWh (battery recharge).

    Complexity:
        Time: O(1)
        Space: O(1)

    Args:
        car: Vehicle profile.
        length_m: Edge distance in meters.
        time_s: Edge traversal duration in seconds.
        elevation_gain_m: Altitude change h(v) - h(u) in meters.
        crr: Pre-calibrated Crr, or None to calibrate automatically.
        rho_air: Ambient air density.

    Returns:
        Energy in kWh. Positive indicates battery discharge, negative indicates
        regenerative recharge.
    """
    if length_m <= 0.0:
        return 0.0

    if crr is None:
        crr = calibrate_crr(car, rho_air=rho_air)

    # Average speed along edge (clamped to realistic minimum to avoid divide-by-zero)
    v = max(0.5, length_m / max(0.1, time_s))

    # Forces (Newtons)
    f_roll = crr * car.mass_kg * GRAVITY_M_S2
    f_aero = 0.5 * rho_air * car.drag_coefficient * car.frontal_area_m2 * (v**2)

    # Flat road mechanical work (Joules)
    w_flat_mech = (f_roll + f_aero) * length_m

    # Potential energy change (Joules): m * g * delta_h
    delta_e_pot = car.mass_kg * GRAVITY_M_S2 * elevation_gain_m

    # Net mechanical work demanded at wheels
    delta_w_mech = w_flat_mech + delta_e_pot

    # Traction vs Regenerative conversion
    if delta_w_mech >= 0.0:
        # Propulsion: motor efficiency loss increases electrical demand
        e_traction_kwh = delta_w_mech / (car.drivetrain_efficiency * JOULES_PER_KWH)
    else:
        # Regeneration: recovery limited by regen_efficiency < 1.0 (negative kWh)
        e_traction_kwh = (delta_w_mech * car.regen_efficiency) / JOULES_PER_KWH

    # Add auxiliary power consumption over time_s
    e_aux_kwh = (car.auxiliary_power_kw * time_s) / 3600.0

    return e_traction_kwh + e_aux_kwh


def simulate_path_soc(
    car: Car,
    edges: list[RoadEdge],
    departure_soc: float,
    reserve_soc: float = 0.10,
) -> float | None:
    """Simulate battery SoC along a sequence of road edges with 100% clamping.

    Enforces that battery SoC never drops below reserve_soc at any intermediate
    prefix, and clamps regenerative charging so battery never exceeds 100%
    of usable capacity.

    Complexity:
        Time: O(|edges|)
        Space: O(1)

    Args:
        car: Vehicle profile.
        edges: Ordered sequence of physical road edges traversed.
        departure_soc: Initial SoC as fraction of usable capacity in [0, 1].
        reserve_soc: Minimum allowable safety reserve SoC in [0, 1].

    Returns:
        Arrival SoC in [reserve_soc, 1.0] upon reaching the final node,
        or None if battery drops below reserve_soc at any point.
    """
    e_usable = car.usable_battery_kwh
    e_reserve = reserve_soc * e_usable
    e_curr = departure_soc * e_usable

    if e_curr < e_reserve:
        return None

    for edge in edges:
        e_curr -= edge.energy_kwh

        # Infeasible: battery dropped below safety reserve buffer
        if e_curr < e_reserve:
            return None

        # Clamping: battery cannot charge beyond 100% of usable capacity
        e_curr = min(e_curr, e_usable)

    return e_curr / e_usable


def build_arrival_soc_table(
    car: Car,
    edges: list[RoadEdge],
    K: int = 100,
    reserve_soc: float = 0.10,
) -> list[float | None]:
    """Pre-tabulate arrival SoC for all discrete departure levels 0..K.

    For each departure level s in {0, ..., K}, simulates traversal across the
    underlying edge sequence with intermediate clamping and reserve checking.

    Complexity:
        Time: O(K * |edges|)
        Space: O(K)

    Args:
        car: Vehicle profile.
        edges: Ordered sequence of physical road edges.
        K: Discretization resolution (e.g. 100).
        reserve_soc: Minimum allowable safety reserve fraction.

    Returns:
        List of length K + 1 where index s gives arrival SoC for departure SoC s / K,
        or None if infeasible.
    """
    table: list[float | None] = [None] * (K + 1)
    for s_idx in range(K + 1):
        dep_soc = s_idx / K
        if dep_soc < reserve_soc:
            table[s_idx] = None
        else:
            table[s_idx] = simulate_path_soc(car, edges, dep_soc, reserve_soc)
    return table


def compute_path_energy_summary(
    edges: list[RoadEdge],
) -> tuple[float, float, float]:
    """Compute aggregate time, net energy, and peak prefix energy need.

    Complexity:
        Time: O(|edges|)
        Space: O(1)

    Args:
        edges: Ordered sequence of road edges.

    Returns:
        Tuple of (total_time_s, net_energy_kwh, peak_need_kwh).
        peak_need_kwh is the maximum cumulative energy deficit encountered at
        any intermediate prefix along the sequence.
    """
    total_time_s = 0.0
    cumulative_energy = 0.0
    peak_need_kwh = 0.0

    for edge in edges:
        total_time_s += edge.time_s
        cumulative_energy += edge.energy_kwh
        peak_need_kwh = max(peak_need_kwh, cumulative_energy)

    return total_time_s, cumulative_energy, peak_need_kwh
