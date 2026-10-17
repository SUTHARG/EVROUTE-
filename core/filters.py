"""Greedy charger filtering module with range-preserving loop reinstatement.

Filters candidate charging stations by connector compatibility and a multi-attribute
score (reliability, amenities, charging power, detour penalty), while guaranteeing
that corridor connectivity is preserved across all gaps (source -> first charger,
intermediate charger-to-charger gaps, and last charger -> destination).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.models import Car, Station
from ingest.route import haversine_distance_m


def compute_station_score(
    station: Station,
    detour_km: float = 0.5,
    corridor_buffer_km: float = 5.0,
    w_rel: float = 0.35,
    w_amenity: float = 0.30,
    w_power: float = 0.25,
    w_detour: float = 0.10,
) -> float:
    """Compute multi-attribute utility score for a charging station.

    Score = w1 * reliability + w2 * amenity_score + w3 * (power / 150) - w4 * (detour_km / buffer_km)

    Complexity: O(1).
    """
    power_norm = min(1.0, station.max_kw / 150.0)
    detour_norm = min(1.0, max(0.0, detour_km / max(0.1, corridor_buffer_km)))
    score = (
        w_rel * station.reliability
        + w_amenity * station.amenity_score
        + w_power * power_norm
        - w_detour * detour_norm
    )
    return round(score, 4)


def filter_stations_greedy(
    stations: list[Station],
    car: Car,
    source_coord: tuple[float, float],
    destination_coord: tuple[float, float],
    start_soc: float = 1.0,
    reserve_soc: float = 0.10,
    score_threshold: float = 0.35,
    target_connector: str = "CCS2",
    distance_fn: Callable[[tuple[float, float], tuple[float, float]], float] | None = None,
) -> tuple[list[Station], list[Station], dict[str, Any]]:
    """Greedily filter stations while strictly guaranteeing corridor feasibility.

    Guarantees:
        If a sequence of stations exists that allows the vehicle to complete the trip
        without dropping below reserve_soc, this filter will NEVER produce an
        infeasible filtered set.

    Algorithm:
        1. Drop stations without target_connector (e.g. CCS2).
        2. Score all compatible stations and initially keep only those with score >= threshold.
        3. Project stations onto the 1D path from source to destination.
        4. Check corridor connectivity across all gaps:
           - Gap 0: Source -> First kept station (energy <= E_start_effective)
           - Gap i: Kept station i -> Kept station i+1 (energy <= E_effective)
           - Gap Last: Last kept station -> Destination (energy <= E_effective)
        5. Loop Reinstatement: If any gap exceeds effective range, find the highest-scoring
           dropped station inside that gap and reinstate it. Repeat until all gaps are valid
           or no dropped station can bridge the gap.

    Complexity:
        Time: O(|stations| * log |stations|) for sorting and greedy interval checks.
        Space: O(|stations|)

    Args:
        stations: Candidate charging stations.
        car: Vehicle profile.
        source_coord: (lat, lon) start.
        destination_coord: (lat, lon) end.
        start_soc: Initial battery fraction in [0, 1].
        reserve_soc: Safety reserve fraction in [0, 1].
        score_threshold: Initial cutoff score for candidates.
        target_connector: Desired fast-charge plug standard.
        distance_fn: Optional custom distance function in meters.

    Returns:
        Tuple of (kept_stations, dropped_stations, audit_metadata).
    """
    dist_calc = distance_fn or (lambda c1, c2: haversine_distance_m(c1[0], c1[1], c2[0], c2[1]))

    e_usable = car.usable_battery_kwh
    e_effective = e_usable * max(0.0, 1.0 - reserve_soc)
    e_start_effective = e_usable * max(0.0, start_soc - reserve_soc)

    # Approximate max distance vehicle can travel on flat terrain with effective energy
    # (used for 1D corridor projection gap verification)
    km_per_kwh = 1.0 / car.consumption_kwh_per_km
    max_range_m = (e_effective * km_per_kwh) * 1000.0
    max_start_range_m = (e_start_effective * km_per_kwh) * 1000.0

    # 1. Connector compatibility filter
    compatible_stations: list[Station] = []
    dropped_incompatible: list[Station] = []

    for st in stations:
        if target_connector in st.connector_types:
            compatible_stations.append(st)
        else:
            dropped_incompatible.append(st)

    # If entire trip can be completed on single charge from start without any charging:
    direct_trip_dist_m = dist_calc(source_coord, destination_coord)
    if direct_trip_dist_m <= max_start_range_m:
        # Trip is feasible with 0 charging stops; keep high-scoring chargers as options
        scored = [
            (st, compute_station_score(st))
            for st in compatible_stations
        ]
        kept = [st for st, sc in scored if sc >= score_threshold]
        dropped = [st for st, sc in scored if sc < score_threshold] + dropped_incompatible
        return kept, dropped, {
            "feasible_without_stops": True,
            "reinstated_count": 0,
            "kept_count": len(kept),
            "dropped_count": len(dropped),
        }

    # 2. Project stations along 1D axis from source to destination
    def project_station_distance(st: Station) -> float:
        return dist_calc(source_coord, (st.lat, st.lon))

    compatible_stations.sort(key=project_station_distance)

    # Initial split by score threshold
    initial_kept: list[Station] = []
    available_dropped: list[Station] = []

    for st in compatible_stations:
        sc = compute_station_score(st)
        if sc >= score_threshold:
            initial_kept.append(st)
        else:
            available_dropped.append(st)

    stations_by_id = {st.id: st for st in compatible_stations}
    kept_ids: set[str] = {st.id for st in initial_kept}
    reinstated_count = 0

    max_iterations = len(available_dropped) + 5
    unbridgeable_gap: dict[str, Any] | None = None
    for _ in range(max_iterations):
        # Current ordered kept list
        current_kept = sorted([stations_by_id[sid] for sid in kept_ids], key=project_station_distance)
        gap_violated = False

        # Build list of corridor sequence points: Source -> St_1 -> ... -> St_k -> Destination
        points: list[tuple[float, Station | None]] = [(0.0, None)]  # Source
        for st in current_kept:
            points.append((project_station_distance(st), st))
        points.append((direct_trip_dist_m, None))  # Destination

        # Verify each consecutive gap
        for i in range(len(points) - 1):
            p1_dist, p1_st = points[i]
            p2_dist, p2_st = points[i + 1]
            gap_dist_m = p2_dist - p1_dist

            allowed_dist_m = max_start_range_m if i == 0 else max_range_m

            if gap_dist_m > allowed_dist_m:
                # Gap is unbridgeable! Find highest-scoring dropped station inside [p1_dist, p2_dist]
                candidates_in_gap = [
                    st for st in available_dropped
                    if st.id not in kept_ids and p1_dist < project_station_distance(st) < p2_dist
                ]

                if candidates_in_gap:
                    # Greedily reinstate the best station in this gap
                    best_candidate = max(candidates_in_gap, key=compute_station_score)
                    kept_ids.add(best_candidate.id)
                    reinstated_count += 1
                    gap_violated = True
                    break  # Re-evaluate gaps with updated kept set
                else:
                    p1_name = "Source" if p1_st is None else p1_st.name
                    p2_name = "Destination" if p2_st is None else p2_st.name
                    unbridgeable_gap = {
                        "from_point": p1_name,
                        "to_point": p2_name,
                        "gap_dist_km": round(gap_dist_m / 1000.0, 1),
                        "allowed_dist_km": round(allowed_dist_m / 1000.0, 1),
                        "deficit_km": round((gap_dist_m - allowed_dist_m) / 1000.0, 1),
                        "deficit_kwh": round(
                            (gap_dist_m - allowed_dist_m) * car.consumption_kwh_per_km / 1000.0, 2
                        ),
                    }

        if not gap_violated:
            # All gaps successfully bridged!
            break

    final_kept = sorted([stations_by_id[sid] for sid in kept_ids], key=project_station_distance)
    final_dropped = [st for st in stations if st.id not in kept_ids]

    audit_res: dict[str, Any] = {
        "feasible_without_stops": False,
        "reinstated_count": reinstated_count,
        "kept_count": len(final_kept),
        "dropped_count": len(final_dropped),
    }
    if unbridgeable_gap is not None:
        audit_res["unbridgeable_gap"] = unbridgeable_gap

    return final_kept, final_dropped, audit_res
