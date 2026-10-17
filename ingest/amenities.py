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
    disk_cache = cache or DiskCache("amenities")
    cache_key = f"{station.id}_{radius_m}m"

    cached: dict[str, Any] | None = disk_cache.get(cache_key)
    if cached is not None:
        station.amenities = cached.get("amenities", {})
        station.amenity_score = compute_amenity_score(station.amenities)
        return station

    if not allow_network:
        # Default empty amenities if offline and not cached
        station.amenities = station.amenities or {}
        station.amenity_score = compute_amenity_score(station.amenities)
        return station

    query = f"""
    [out:json][timeout:15];
    (
      node["amenity"~"cafe|restaurant|fast_food|toilets|fuel"](around:{radius_m},{station.lat},{station.lon});
    );
    out tags;
    """

    amenity_counts: dict[str, int] = {}
    try:
        resp = requests.post(OVERPASS_API_URL, data={"data": query}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for elem in data.get("elements", []):
                amenity_type = elem.get("tags", {}).get("amenity")
                if amenity_type:
                    amenity_counts[amenity_type] = amenity_counts.get(amenity_type, 0) + 1
    except (requests.RequestException, ValueError, KeyError):
        amenity_counts = {}

    disk_cache.set(cache_key, {"amenities": amenity_counts})
    station.amenities = amenity_counts
    station.amenity_score = compute_amenity_score(amenity_counts)
    return station
