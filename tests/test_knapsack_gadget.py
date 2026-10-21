"""Verification of the 0/1 Knapsack reduction gadget against the multi-route oracle.

Decoupled Gadget Properties:
1. Usable battery capacity E_usable = 12.0 kWh, reserve = 0.25 (3.0 kWh).
2. Leg energy consumption = 9.0 kWh (including inbound/outbound spurs).
3. Max departure energy = reserve + leg energy = 3.0 + 9.0 = 12.0 kWh = E_usable.
   Hence, minimum feasible charge == maximum charge == 100% SoC (12.0 kWh).
4. No excess energy can be carried over between stages (zero inter-stage coupling).
5. Charger powers recomputed with CC-CV taper closed form:
   K_taper = 60 * 12 * (0.55 + ln(10)/4.50) ~= 764.4136 kW*min.
   P(A_i) = K_taper / 20.0 kW -> t_charge = 20.0 min.
   P(B_i) = K_taper / (20.0 + v_i) kW -> t_charge = 20.0 + v_i min.
"""

from __future__ import annotations

import itertools
import math
import random

import pytest

from core.charging import charge_time_min
from core.comfort import compute_dwell_discomfort
from core.energy import simulate_path_soc
from core.models import Car, CorridorSnapshot, RoadEdge, RoadNode, Station, Trip
from core.oracle import solve_multi_route_oracle
from core.road_graph import RoadGraph

E_USABLE = 12.0
RESERVE_SOC = 0.25
RESERVE_KWH = RESERVE_SOC * E_USABLE  # 3.0 kWh
LEG_KWH = 9.0  # Consumed between successive stations
CC_TERM = 0.80 - RESERVE_SOC  # 0.55
CV_TERM = math.log(1.0 / 0.1) / 4.50  # ln(10) / 4.5
K_TAPER = 60.0 * E_USABLE * (CC_TERM + CV_TERM)  # ~764.4136 kW*min
T0 = 20.0  # Base charge time (min)
D0 = 5.0  # Base dwell discomfort
LEG_DRIVE_MIN = 50.0  # Highway leg driving time


def build_knapsack_gadget_corridor(
    weights: list[int],
    values: list[int],
) -> tuple[CorridorSnapshot, Car, Trip]:
    """Construct a physical EV road corridor reflecting a 0/1 Knapsack instance."""
    n = len(weights)
    assert len(values) == n

    car = Car(
        id="knapsack_gadget_car",
        name="Gadget EV",
        battery_kwh=E_USABLE,
        usable_fraction=1.0,
        max_dc_kw=350.0,
        consumption_kwh_per_km=0.15,
        mass_kg=1500.0,
    )

    nodes: dict[int, RoadNode] = {}
    edges: list[RoadEdge] = []
    stations: dict[str, Station] = {}

    origin_id = 0
    nodes[origin_id] = RoadNode(id=origin_id, lat=18.0, lon=73.0, elevation_m=50.0)

    prev_node = origin_id
    for i in range(1, n + 1):
        w_i = weights[i - 1]
        v_i = values[i - 1]

        u_i = 100 * i + 1  # Split node before station pair
        a_i = 100 * i + 10  # Branch A charger node
        b_i = 100 * i + 20  # Branch B charger node
        v_node = 100 * i + 30  # Merge node after station pair

        nodes[u_i] = RoadNode(id=u_i, lat=18.0 + 0.1 * i, lon=73.0 + 0.1 * i, elevation_m=50.0)
        nodes[a_i] = RoadNode(id=a_i, lat=18.0 + 0.1 * i + 0.01, lon=73.0 + 0.1 * i, elevation_m=50.0)
        nodes[b_i] = RoadNode(id=b_i, lat=18.0 + 0.1 * i - 0.01, lon=73.0 + 0.1 * i, elevation_m=50.0)
        nodes[v_node] = RoadNode(id=v_node, lat=18.0 + 0.1 * i + 0.02, lon=73.0 + 0.1 * i, elevation_m=50.0)

        # Highway edge from prev_node to u_i:
        # First leg: 8.8 kWh (plus 0.2 spur = 9.0 kWh)
        # Subsequent legs: 8.6 kWh (plus 0.2 spur_out + 0.2 spur_in = 9.0 kWh)
        hwy_kwh = 8.8 if i == 1 else 8.6
        hwy_time = 48.5 if i == 1 else 47.0
        edges.append(
            RoadEdge(
                u=prev_node,
                v=u_i,
                length_m=58000.0,
                time_s=hwy_time * 60.0,
                energy_kwh=hwy_kwh,
            )
        )

        # Inbound spurs into chargers (0.2 kWh, 1.5 min)
        edges.append(
            RoadEdge(u=u_i, v=a_i, length_m=1000.0, time_s=1.5 * 60.0, energy_kwh=0.2)
        )
        edges.append(
            RoadEdge(u=u_i, v=b_i, length_m=1000.0, time_s=1.5 * 60.0, energy_kwh=0.2)
        )

        # Outbound spurs from chargers into merge node (0.2 kWh, 1.5 min)
        edges.append(
            RoadEdge(u=a_i, v=v_node, length_m=1000.0, time_s=1.5 * 60.0, energy_kwh=0.2)
        )
        edges.append(
            RoadEdge(u=b_i, v=v_node, length_m=1000.0, time_s=1.5 * 60.0, energy_kwh=0.2)
        )

        # Station A_i: Tuned DC, lower amenity (takes item i)
        # Long-dwell regime (> 40 min): T_A = 50 + w_i + 2 * v_i
        t_a = 50.0 + w_i + 2.0 * v_i
        t_b = t_a + v_i
        a_b = 1.0
        a_a = 1.0 - (w_i + 1.5 * v_i) / t_a

        p_a = K_TAPER / t_a
        p_b = K_TAPER / t_b

        st_a_id = f"st_A_{i}"
        stations[st_a_id] = Station(
            id=st_a_id,
            name=f"Stage {i} Branch A (Take item {i})",
            lat=nodes[a_i].lat,
            lon=nodes[a_i].lon,
            road_node_id=a_i,
            max_kw=p_a,
            connector_types=["CCS2"],
            amenity_score=a_a,
            reliability=1.0,
            is_reliability_simulated=True,
            source="synthetic",
        )

        st_b_id = f"st_B_{i}"
        stations[st_b_id] = Station(
            id=st_b_id,
            name=f"Stage {i} Branch B (Leave item {i})",
            lat=nodes[b_i].lat,
            lon=nodes[b_i].lon,
            road_node_id=b_i,
            max_kw=p_b,
            connector_types=["CCS2"],
            amenity_score=a_b,
            reliability=1.0,
            is_reliability_simulated=True,
            source="synthetic",
        )

        prev_node = v_node

    # Final milestone to destination (8.8 kWh, 48.5 min; plus 0.2 outbound spur = 9.0 kWh)
    dest_id = 9999
    nodes[dest_id] = RoadNode(id=dest_id, lat=18.0 + 0.1 * (n + 1), lon=73.0 + 0.1 * (n + 1), elevation_m=50.0)
    edges.append(
        RoadEdge(
            u=prev_node,
            v=dest_id,
            length_m=58000.0,
            time_s=48.5 * 60.0,
            energy_kwh=8.8,
        )
    )

    snapshot = CorridorSnapshot(
        id=f"knapsack_gadget_n_{n}",
        source_name="Gadget Origin",
        destination_name="Gadget Destination",
        created_at="2026-10-18T10:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=list(stations.values()),
        source_node_id=origin_id,
        destination_node_id=dest_id,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        source_id="source",
        destination_id="dest",
        start_soc=1.0,  # Depart fully charged (12.0 kWh)
        reserve_soc=RESERVE_SOC,  # Strict 0.25 reserve
        stop_threshold_soc=0.35,  # Arrival at 0.25 incurs zero premature stop penalty
        comfort_weight_lambda=1.0,
        K=12,
    )

    return snapshot, car, trip


def solve_knapsack_brute_force(
    weights: list[int],
    values: list[int],
    lambda_val: float,
) -> tuple[float, list[tuple[float, float, list[int]]]]:
    """Exhaustively solve the scalarized Knapsack objective across all 2^n subsets.

    Returns the minimum cost J and all optimal (time, discomfort, subset) solutions.
    """
    n = len(weights)
    t_drive_total = (n + 1) * LEG_DRIVE_MIN
    base_t_charge = sum(50.0 + w + 2.0 * v for w, v in zip(weights, values))
    base_discomfort = sum(1.5 * (50.0 + w + 3.0 * v) - 55.0 for w, v in zip(weights, values))

    best_j = float("inf")
    solutions: list[tuple[float, float, list[int]]] = []

    for subset_tuple in itertools.product([0, 1], repeat=n):
        subset = list(subset_tuple)  # 1 for A (take), 0 for B (leave)
        w_sum = sum(w for take, w in zip(subset, weights) if take == 1)
        v_unselected = sum(v for take, v in zip(subset, values) if take == 0)

        t_total = t_drive_total + base_t_charge + v_unselected
        d_total = base_discomfort + w_sum
        cost_j = t_total + lambda_val * d_total

        if cost_j < best_j - 1e-6:
            best_j = cost_j
            solutions = [(t_total, d_total, subset)]
        elif abs(cost_j - best_j) <= 1e-6:
            solutions.append((t_total, d_total, subset))

    return best_j, solutions


def test_gadget_energy_decoupling_and_taper():
    """Verify that gadget physical charging taper and energy balance match theory."""
    weights = [250, 400]
    values = [120, 350]
    snapshot, car, _trip = build_knapsack_gadget_corridor(weights, values)

    st_map = {st.id: st for st in snapshot.stations}
    for i in range(1, len(weights) + 1):
        st_a = st_map[f"st_A_{i}"]
        st_b = st_map[f"st_B_{i}"]

        # Recharging from reserve (0.25) to 1.00:
        t_a = charge_time_min(RESERVE_SOC, 1.0, st_a.max_kw, car)
        t_b = charge_time_min(RESERVE_SOC, 1.0, st_b.max_kw, car)

        expected_ta = 50.0 + weights[i - 1] + 2.0 * values[i - 1]
        expected_tb = expected_ta + values[i - 1]

        assert abs(t_a - expected_ta) < 1e-3, f"Branch A charge time {t_a} != {expected_ta}"
        assert abs(t_b - expected_tb) < 1e-3, f"Branch B charge time {t_b} != {expected_tb}"
        assert abs((t_b - t_a) - values[i - 1]) < 1e-3

        d_a = compute_dwell_discomfort(t_a, st_a.amenity_score, True, RESERVE_SOC, 0.35)
        d_b = compute_dwell_discomfort(t_b, st_b.amenity_score, True, RESERVE_SOC, 0.35)
        assert abs((d_a - d_b) - weights[i - 1]) < 1e-3


@pytest.mark.parametrize("seed", [42, 101, 777, 999])
def test_knapsack_gadget_matches_oracle(seed: int):
    """Test on random Knapsack instances with weights/values up to ~1000 against brute-force and oracle."""
    rng = random.Random(seed)
    n = 3
    # Arbitrary integer weights and values up to ~1000
    weights = [rng.randint(20, 1000) for _ in range(n)]
    values = [rng.randint(20, 1000) for _ in range(n)]

    snapshot, car, trip = build_knapsack_gadget_corridor(weights, values)

    # Test across multiple lambda values (weights of comfort vs time)
    for lambda_val in [0.23, 0.50, 1.00, 2.15]:
        best_j, opt_solutions = solve_knapsack_brute_force(weights, values, lambda_val)

        oracle_res = solve_multi_route_oracle(snapshot, car, trip, lambda_val=lambda_val)
        assert oracle_res["feasible"] is True, "Oracle failed to find a feasible EV plan"

        oracle_j = oracle_res["cost_J"]
        oracle_t = oracle_res["total_time_min"]
        oracle_d = oracle_res["total_discomfort_min"]

        # 1. Optimal objective cost must match exactly within numerical tolerance
        assert abs(oracle_j - best_j) < 0.1, (
            f"Cost mismatch at lambda={lambda_val}: Oracle J={oracle_j:.3f} vs Knapsack J={best_j:.3f}"
        )

        # 2. Time and discomfort must match one of the global optima of the Knapsack instance
        matched_opt = any(
            abs(oracle_t - t_opt) < 0.1 and abs(oracle_d - d_opt) < 0.1
            for t_opt, d_opt, _ in opt_solutions
        )
        assert matched_opt, (
            f"Oracle (T={oracle_t:.2f}, D={oracle_d:.2f}) did not match any Knapsack optimum: {opt_solutions}"
        )


def test_knapsack_gadget_exhaustive_bijection():
    """Verify that every 2^n Knapsack subset maps 1-to-1 to an EV route with identical T and D."""
    weights = [350, 120, 680]
    values = [420, 210, 150]
    n = len(weights)

    snapshot, car, _trip = build_knapsack_gadget_corridor(weights, values)

    road_graph = RoadGraph.from_snapshot(snapshot)
    edge_map = {(e.u, e.v): e for e in road_graph.get_edges()}
    st_map = {st.id: st for st in snapshot.stations}

    t_drive_total = (n + 1) * LEG_DRIVE_MIN
    base_t_charge = sum(50.0 + w + 2.0 * v for w, v in zip(weights, values))
    base_discomfort = sum(1.5 * (50.0 + w + 3.0 * v) - 55.0 for w, v in zip(weights, values))

    for subset_tuple in itertools.product([0, 1], repeat=n):
        subset = list(subset_tuple)  # 1 for A (take), 0 for B (leave)
        w_sum = sum(w for take, w in zip(subset, weights) if take == 1)
        v_unselected = sum(v for take, v in zip(subset, values) if take == 0)

        expected_time = t_drive_total + base_t_charge + v_unselected
        expected_discomfort = base_discomfort + w_sum

        # Construct the physical path for this subset
        path_nodes = [0]
        chosen_stations = []
        for i in range(1, n + 1):
            take = subset[i - 1]
            u_i = 100 * i + 1
            st_node = 100 * i + 10 if take == 1 else 100 * i + 20
            v_i = 100 * i + 30
            st_id = f"st_A_{i}" if take == 1 else f"st_B_{i}"
            path_nodes.extend([u_i, st_node, v_i])
            chosen_stations.append(st_map[st_id])
        path_nodes.append(9999)

        # Simulate physics along this path
        curr_soc = 1.0
        total_chg_time = 0.0
        total_dwell_discomfort = 0.0
        prev_n = path_nodes[0]

        for i, st in enumerate(chosen_stations):
            # Edges from prev_n to st.road_node_id
            idx_start = path_nodes.index(prev_n)
            idx_st = path_nodes.index(st.road_node_id)
            seg_edges = [edge_map[(path_nodes[k], path_nodes[k + 1])] for k in range(idx_start, idx_st)]

            arr_soc = simulate_path_soc(car, seg_edges, curr_soc, RESERVE_SOC)
            assert arr_soc is not None, f"Battery depleted before station {st.id}"
            assert abs(arr_soc - RESERVE_SOC) < 1e-4, f"Arrival SoC {arr_soc} != {RESERVE_SOC}"

            # Charge back to 100%
            chg_t = charge_time_min(arr_soc, 1.0, st.max_kw, car)
            d_dwell = compute_dwell_discomfort(
                dwell_min=chg_t,
                amenity_score=st.amenity_score,
                is_real_charge=True,
                arrival_soc=arr_soc,
                stop_threshold_soc=0.35,
            )

            total_chg_time += chg_t
            total_dwell_discomfort += d_dwell
            curr_soc = 1.0
            prev_n = st.road_node_id

        # Final leg to destination
        idx_last = path_nodes.index(prev_n)
        final_seg = [edge_map[(path_nodes[k], path_nodes[k + 1])] for k in range(idx_last, len(path_nodes) - 1)]
        dest_soc = simulate_path_soc(car, final_seg, curr_soc, RESERVE_SOC)
        assert dest_soc is not None, "Battery depleted before destination"
        assert abs(dest_soc - RESERVE_SOC) < 1e-4, f"Destination arrival SoC {dest_soc} != {RESERVE_SOC}"

        sim_total_time = t_drive_total + total_chg_time
        sim_total_discomfort = total_dwell_discomfort

        assert abs(sim_total_time - expected_time) < 0.05, (
            f"Subset {subset}: time {sim_total_time} != expected {expected_time}"
        )
        assert abs(sim_total_discomfort - expected_discomfort) < 0.05, (
            f"Subset {subset}: discomfort {sim_total_discomfort} != expected {expected_discomfort}"
        )
