"""Elevation sampling via OpenTopoData with caching, noise smoothing, and ascent reporting."""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

from ingest.cache import DiskCache

OPENTOPODATA_URL: str = "https://api.opentopodata.org/v1/srtm30m"
MAX_BATCH_SIZE: int = 100
RATE_LIMIT_DELAY_S: float = 1.0

_last_elevation_request_time: float = 0.0


def smooth_elevation_profile(
    elevations: list[float],
    window_size: int = 3,
) -> tuple[list[float], float, float]:
    """Apply centered moving average smoothing to eliminate radar sensor noise.

    Computes and reports total cumulative vertical ascent before and after smoothing.

    Complexity:
        Time: O(N * window_size)
        Space: O(N)

    Args:
        elevations: Raw list of sampled altitude measurements in meters.
        window_size: Odd integer window length for moving average (default 3).

    Returns:
        Tuple of (smoothed_elevations, total_ascent_before_m, total_ascent_after_m).
    """
    if not elevations:
        return [], 0.0, 0.0

    n = len(elevations)
    # Compute raw ascent before smoothing
    ascent_before = sum(max(0.0, elevations[i + 1] - elevations[i]) for i in range(n - 1))

    if n <= window_size:
        return list(elevations), ascent_before, ascent_before

    half_w = window_size // 2
    smoothed: list[float] = []

    for i in range(n):
        start_idx = max(0, i - half_w)
        end_idx = min(n, i + half_w + 1)
        sub_window = elevations[start_idx:end_idx]
        avg_h = sum(sub_window) / len(sub_window)
        smoothed.append(round(avg_h, 2))

    # Compute smoothed ascent
    ascent_after = sum(max(0.0, smoothed[i + 1] - smoothed[i]) for i in range(n - 1))

    return smoothed, round(ascent_before, 2), round(ascent_after, 2)


def sample_elevations(
    coords: list[tuple[float, float]],  # [(lat, lon), ...]
    allow_network: bool = True,
    cache: DiskCache | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[float]:
    """Sample elevations for a sequence of (lat, lon) coordinates via batched queries.

    Checks disk cache for previously sampled coordinates.

    Complexity:
        O(N) with caching, O(N / batch_size) HTTP queries.

    Args:
        coords: Sequence of (lat, lon) coordinates.
        allow_network: Whether to query OpenTopoData if cache misses.
        cache: Optional DiskCache instance.

    Returns:
        List of elevation altitudes in meters corresponding to each input coordinate.
    """
    global _last_elevation_request_time
    if not coords:
        return []

    disk_cache = cache or DiskCache("elevation")
    results: list[float] = [0.0] * len(coords)
    missing_indices: list[int] = []

    # 1. Check cached individual coordinates (rounded to 4 decimal places ~11m)
    for idx, (lat, lon) in enumerate(coords):
        key = f"{lat:.4f},{lon:.4f}"
        cached_val: Any = disk_cache.get(key)
        if cached_val is not None and isinstance(cached_val, (int, float)):
            results[idx] = float(cached_val)
        else:
            missing_indices.append(idx)

    if not missing_indices or not allow_network:
        return results

    # 2. Batch query missing coordinates in chunks of MAX_BATCH_SIZE
    chunks = range(0, len(missing_indices), MAX_BATCH_SIZE)
    total_chunks = len(chunks)
    for chunk_number, chunk_start in enumerate(chunks, start=1):
        chunk_indices = missing_indices[chunk_start : chunk_start + MAX_BATCH_SIZE]
        locations_str = "|".join(
            f"{coords[i][0]:.5f},{coords[i][1]:.5f}" for i in chunk_indices
        )

        elapsed = time.time() - _last_elevation_request_time
        if elapsed < RATE_LIMIT_DELAY_S:
            time.sleep(RATE_LIMIT_DELAY_S - elapsed)

        try:
            resp = requests.get(
                OPENTOPODATA_URL,
                params={"locations": locations_str},
                headers={"User-Agent": "RouteEV-TripPlanner/1.0"},
                timeout=15,
            )
            _last_elevation_request_time = time.time()
            if resp.status_code == 200:
                data = resp.json()
                for i_pos, item in enumerate(data.get("results", [])):
                    elev = item.get("elevation") or 0.0
                    real_idx = chunk_indices[i_pos]
                    results[real_idx] = float(elev)
                    coord_key = f"{coords[real_idx][0]:.4f},{coords[real_idx][1]:.4f}"
                    disk_cache.set(coord_key, float(elev))
        except (requests.RequestException, ValueError, KeyError):
            # On network failure or malformed payload, retain default heights
            continue
        finally:
            if progress_callback:
                progress_callback(chunk_number, total_chunks)

    return results
