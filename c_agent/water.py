"""Nearest water-source lookup against Role A's catalogue (schema 1.0 four-field output)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from contracts.validate import ROOT

# Mean Earth radius from a_data/WATER_HANDOFF.md
EARTH_RADIUS_KM = 6371.0088
DEFAULT_WATER_CATALOGUE = ROOT / "a_data" / "mock_water_sources.json"


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
    """Prefer CLI path, then data-dir export, then Role A's mock catalogue."""
    candidates = []
    if explicit is not None:
        candidates.append(explicit)
    if data_dir is not None:
        candidates.append(data_dir / "water_sources.json")
    candidates.append(DEFAULT_WATER_CATALOGUE)
    for path in candidates:
        if path.exists():
            return path
    return None


def nearest_water_source(
    target: dict[str, float],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return contract water_source {lat, lon, distance_km, kind} or null.

    Distance is computed before rounding; output distance is rounded to 3 decimals
    per Role A's WATER_HANDOFF.md.
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
    if best is None:
        return None
    return {
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
        "distance_km": round(best_distance, 3),
        "kind": str(best["kind"]),
    }
