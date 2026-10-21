"""Amenity discovery module around EV charging stations using Overpass API with local caching."""

from __future__ import annotations

from typing import Any

import requests

from core.models import Station
from ingest.cache import DiskCache

OVERPASS_API_URL: str = "https://overpass-api.de/api/interpreter"


def compute_amenity_score(amenities: dict[str, int]) -> float:
    """Compute aggregate comfort score in [0.0, 1.0] from amenity counts.

    Weights:
        - Food/Restaurant presence: 0.35
        - Toilets / Restroom: 0.30
        - Cafe / Coffee: 0.20
        - Convenience / Fuel shop: 0.15

    Complexity: O(1).
    """
    has_restaurant = 1.0 if (amenities.get("restaurant", 0) > 0 or amenities.get("fast_food", 0) > 0) else 0.0
    has_toilets = 1.0 if amenities.get("toilets", 0) > 0 else 0.0
    has_cafe = 1.0 if amenities.get("cafe", 0) > 0 else 0.0
    has_fuel = 1.0 if amenities.get("fuel", 0) > 0 else 0.0

    score = (
        0.35 * has_restaurant
        + 0.30 * has_toilets
        + 0.20 * has_cafe
        + 0.15 * has_fuel
    )
    # Minor boost for multiple options (clamped at 1.0)
    total_count = sum(amenities.values())
    if total_count >= 3:
        score = min(1.0, score + 0.05)

    return round(score, 3)


_overpass_amenity_failures: int = 0
_overpass_amenity_cooldown_until: float = 0.0


def populate_station_amenities(
    station: Station,
    radius_m: int = 250,
    allow_network: bool = True,
    cache: DiskCache | None = None,
) -> Station:
    """Fetch POIs within radius around a station and update amenities and amenity_score.

    Args:
        station: Target Station instance.
        radius_m: Search buffer radius in meters (default 250m).
        allow_network: Whether to query Overpass if cache misses.
        cache: Optional DiskCache instance.

    Returns:
        Updated Station instance.
    """
    global _overpass_amenity_failures, _overpass_amenity_cooldown_until
    disk_cache = cache or DiskCache("amenities")
    if station.amenity_known and station.amenities:
        station.amenity_score = compute_amenity_score(station.amenities)
        return station

    cache_key = f"{round(station.lat, 4)}_{round(station.lon, 4)}_{radius_m}"
    cached: dict[str, Any] | None = disk_cache.get(cache_key)
    if cached is not None:
        station.amenities = cached.get("amenities", {})
        station.amenity_score = compute_amenity_score(station.amenities)
        return station

    import time
    if not allow_network or time.time() < _overpass_amenity_cooldown_until:
        station.amenities = station.amenities or {}
        station.amenity_score = compute_amenity_score(station.amenities)
        return station

    query = f"""
    [out:json][timeout:5];
    (
      node["amenity"~"cafe|restaurant|fast_food|toilets|fuel"](around:{radius_m},{station.lat},{station.lon});
    );
    out tags;
    """

    amenity_counts: dict[str, int] = {}
    try:
        resp = requests.post(OVERPASS_API_URL, data={"data": query}, timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            for elem in data.get("elements", []):
                amenity_type = elem.get("tags", {}).get("amenity")
                if amenity_type:
                    amenity_counts[amenity_type] = amenity_counts.get(amenity_type, 0) + 1
            _overpass_amenity_failures = 0
        else:
            _overpass_amenity_failures += 1
            if _overpass_amenity_failures >= 2:
                _overpass_amenity_cooldown_until = time.time() + 60.0
    except (requests.RequestException, ValueError, KeyError):
        _overpass_amenity_failures += 1
        if _overpass_amenity_failures >= 2:
            _overpass_amenity_cooldown_until = time.time() + 60.0
        amenity_counts = {}

    disk_cache.set(cache_key, {"amenities": amenity_counts})
    station.amenities = amenity_counts
    station.amenity_score = compute_amenity_score(amenity_counts)
    return station

