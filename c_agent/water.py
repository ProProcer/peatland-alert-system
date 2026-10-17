"""Nearest water-source lookup against Role A's catalogue (schema 1.0 four-field output).

Supports two modes:
1. GeoJSON with Role A's WaterIndex (spatial index, metric projection, line/polygon shorelines)
2. Simple JSON array with Haversine distance (fallback for mocks and catalogues without geometry)
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from contracts.validate import ROOT

# Mean Earth radius from a_data/WATER_HANDOFF.md
EARTH_RADIUS_KM = 6371.0088
DEFAULT_WATER_CATALOGUE = ROOT / "a_data" / "mock_water_sources.json"
# A source farther than this from the target is not useful to a field team: report null.
DEFAULT_MAX_WATER_KM = 15.0

# Try to import Role A's WaterIndex; if dependencies are missing, fall back to simple mode
_WATER_INDEX_AVAILABLE = False
try:
    from a_data.water import WaterIndex
    _WATER_INDEX_AVAILABLE = True
except ImportError:
    # Role A's dependencies (osmium, shapely, pyproj) may not be installed in C's environment
    WaterIndex = None  # type: ignore[assignment]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def load_water_catalogue(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"water catalogue must be a JSON array: {path}")
    return payload


def resolve_water_catalogue_path(explicit: Path | None, data_dir: Path | None = None) -> Path | None:
    """Prefer explicit path, dataset catalogue, then its shared real-source catalogue.

    Checks for both GeoJSON (water_sources.geojson) and JSON array (water_sources.json).
    """
    if explicit is not None:
        if not explicit.is_file():
            raise ValueError(f"Water catalogue not found: {explicit}")
        return explicit
    candidates = []
    if data_dir is not None:
        candidates.extend([data_dir / 'water_sources.geojson', data_dir / 'water_sources.json'])
        if data_dir.parent.name == 'role_a_real':
            candidates.append(data_dir.parent / 'water_sources.geojson')
    # Synthetic water sources must be requested explicitly, never inferred for real data.
    return next((path for path in candidates if path.is_file()), None)


def is_geojson_catalogue(path: Path) -> bool:
    """Detect if the catalogue is a GeoJSON FeatureCollection (WaterIndex) vs simple JSON array."""
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(payload, dict) and payload.get("type") == "FeatureCollection"
    except (json.JSONDecodeError, IOError):
        return False


def nearest_water_source_simple(
    target: dict[str, float],
    candidates: list[dict[str, Any]],
    max_km: float | None = None,
) -> dict[str, Any] | None:
    """Return contract water_source {lat, lon, distance_km, kind} or null using Haversine.

    Used when WaterIndex is unavailable (mock catalogues, missing dependencies).
    Distance is computed before rounding; output distance is rounded to 3 decimals
    per Role A's WATER_HANDOFF.md. If ``max_km`` is set and the nearest source is
    farther than that, return ``None`` (never attach a distant source).
    """
    if not candidates:
        return None
    best: dict[str, Any] | None = None
    best_distance = math.inf
    for source in candidates:
        distance = haversine_km(target["lat"], target["lon"], float(source["lat"]), float(source["lon"]))
        if distance < best_distance:
            best_distance = distance
            best = source
    if best is None or (max_km is not None and best_distance > max_km):
        return None
    return {
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
        "distance_km": round(best_distance, 3),
        "kind": str(best["kind"]),
    }


def nearest_water_source_from_index(
    target: dict[str, float],
    geojson_path: Path,
    max_km: float | None = None,
) -> dict[str, Any] | None:
    """Return contract water_source using Role A's WaterIndex (spatial index, metric projection).

    Requires Role A's dependencies (osmium, shapely, pyproj). Falls back to None if unavailable.
    """
    if not _WATER_INDEX_AVAILABLE or WaterIndex is None:
        raise ValueError('Spatial water lookup requires osmium, shapely and pyproj. Start the server with .venv/Scripts/python.exe.')
    path = geojson_path.resolve()
    stat = path.stat()
    try:
        index = _cached_water_index(str(path), stat.st_mtime_ns, stat.st_size)
        return index.nearest(target['lat'], target['lon'], max_distance_km=max_km).get('water_source')
    except Exception as exc:
        raise ValueError(f'Could not read or query spatial water catalogue: {path.name}') from exc


@lru_cache(maxsize=2)
def _cached_water_index(path, modified_ns, size):
    """Build the large spatial index once per catalogue revision."""
    return WaterIndex(Path(path))


def nearest_water_source(
    target: dict[str, float],
    candidates_or_path: list[dict[str, Any]] | Path,
    max_km: float | None = None,
) -> dict[str, Any] | None:
    """Return contract water_source {lat, lon, distance_km, kind} or null.

    Auto-detects input type:
    - If Path: tries WaterIndex for GeoJSON, else loads as JSON array
    - If list: uses simple Haversine distance
    """
    if isinstance(candidates_or_path, Path):
        if candidates_or_path.suffix.lower() == '.geojson' or is_geojson_catalogue(candidates_or_path):
            return nearest_water_source_from_index(target, candidates_or_path, max_km)
        # Not a GeoJSON, load as simple JSON array
        candidates = load_water_catalogue(candidates_or_path)
        return nearest_water_source_simple(target, candidates, max_km)
    else:
        # Assume it's a list of candidates
        return nearest_water_source_simple(target, candidates_or_path, max_km)
