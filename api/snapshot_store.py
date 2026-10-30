"""Snapshot persistence and in-memory lookup for the HTTP API layer."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

from core.models import CorridorSnapshot

SNAPSHOTS_DIR = Path("data/snapshots")
SNAPSHOT_CACHE: dict[str, CorridorSnapshot] = {}


def load_all_snapshots() -> dict[str, CorridorSnapshot]:
    """Load persisted corridor snapshots into the shared API cache."""
    if not SNAPSHOTS_DIR.exists():
        return SNAPSHOT_CACHE

    for file_path in SNAPSHOTS_DIR.glob("*.json"):
        try:
            with file_path.open("r", encoding="utf-8") as snapshot_file:
                snapshot = CorridorSnapshot(**json.load(snapshot_file))
            # Historical snapshots stored edge energy using the default Nexon EV.
            snapshot.metadata.setdefault("energy_vehicle_id", "tata_nexon_ev_lr")
            # Disk snapshots are saved artifacts rather than live session builds.
            snapshot.metadata["is_live_build"] = False
            SNAPSHOT_CACHE[snapshot.id] = snapshot
            SNAPSHOT_CACHE[file_path.stem] = snapshot
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            print(f"[!] Warning: failed to load snapshot {file_path}: {exc}")

    return SNAPSHOT_CACHE


def get_snapshot(snapshot_id: str) -> CorridorSnapshot:
    """Return a snapshot by ID or filename stem, reloading the cache if needed."""
    if snapshot_id not in SNAPSHOT_CACHE:
        load_all_snapshots()

    if snapshot_id not in SNAPSHOT_CACHE:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot '{snapshot_id}' not found. Available: {list(SNAPSHOT_CACHE)}",
        )
    return SNAPSHOT_CACHE[snapshot_id]
