"""Role A's frozen field names and atomic artifact helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WEATHER_MAP = dict(zip(
    ("temperature_2m", "precipitation", "wind_speed_10m", "wind_direction_10m",
     "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm", "soil_moisture_3_to_9cm",
     "soil_moisture_9_to_27cm", "soil_moisture_27_to_81cm", "vapour_pressure_deficit",
     "soil_temperature_0cm", "soil_temperature_18cm", "evapotranspiration", "et0_fao_evapotranspiration"),
    ("temp_c", "precip_mm", "wind_kmh", "wind_dir_deg", "sm_0_1", "sm_1_3",
     "sm_3_9", "sm_9_27", "sm_27_81", "vpd_kpa", "soil_temp_0_c", "soil_temp_18_c", "et_mm", "et0_mm"),
))
GROUPS = {
    "peat": ["peat_fraction", "peat_area_km2"],
    "weather": list(WEATHER_MAP.values()),
    "derived": ["rain_24h_mm", "rain_7d_mm", "rain_30d_mm", "days_since_rain",
                "sm_27_81_delta_7d", "vpd_mean_24h", "soil_air_temp_gap_c"],
    "fire": ["hotspots_in_cell_24h", "hotspots_10km_7d", "frp_sum_10km_7d", "nearest_hotspot_km"],
}
FEATURES = [column for columns in GROUPS.values() for column in columns]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                   indent=None if compact else 2,
                                   separators=(",", ":") if compact else None) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_parquet(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)
