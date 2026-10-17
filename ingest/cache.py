"""On-disk JSON caching utility for external API queries with SHA-256 key hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CACHE_ROOT: Path = Path("data/cache")


class DiskCache:
    """Manages file-based disk caching for network API requests.

    Each namespace (e.g. 'geocode', 'osrm', 'overpass', 'elevation') has its
    own subdirectory. Cache keys are hashed using SHA-256 to ensure filesystem safety.

    Complexity:
        Read/Write: O(1) file system lookup + O(payload size) serialization.
    """

    def __init__(self, namespace: str, cache_dir: Path | None = None) -> None:
        self.namespace = namespace
        self.dir = (cache_dir or CACHE_ROOT) / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def _hash_key(self, key: str) -> str:
        """Compute SHA-256 hex digest of cache key."""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Any | None:
        """Retrieve cached JSON payload if present, else None."""
        file_path = self.dir / f"{self._hash_key(key)}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def set(self, key: str, value: Any) -> None:
        """Store JSON-serializable payload on disk."""
        file_path = self.dir / f"{self._hash_key(key)}.json"
        temp_path = self.dir / f"{self._hash_key(key)}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)
        temp_path.replace(file_path)
