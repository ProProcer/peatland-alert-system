"""Assemble real canonical hourly features and raw-event future labels."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point
from shapely.ops import transform

from a_data.common import FEATURES, GROUPS, ROOT, utc_now, write_json, write_parquet
from a_data.geography import TO_AREA, load_boundary

HOUR_NS = 3_600_000_000_000


def haversine_km(lat, lon, latitudes, longitudes):
    lat1, lat2 = np.radians(lat), np.radians(latitudes)
    dlat, dlon = lat2 - lat1, np.radians(longitudes - lon)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arctan2(np.sqrt(np.clip(a, 0, 1)), np.sqrt(np.clip(1 - a, 0, 1)))


def days_since_rain(precip: pd.Series) -> pd.Series:
    """UTC dates: use only the current day's observed prefix and completed past days."""
    last_wet, day, total, missing = None, None, 0.0, False
    values = []
    for timestamp, rain in precip.items():
        current = timestamp.normalize()
        if current != day:
            # Unknown rain on a completed day prevents an exact older dry-spell count.
            if missing and total < 1:
                last_wet = None
            day, total, missing = current, 0.0, False
        if pd.isna(rain):
            missing = True
        else:
            total += float(rain)
        if total >= 1:
            last_wet = current
            values.append(0)
        elif missing or last_wet is None:
            values.append(pd.NA)
        else:
            values.append((current - last_wet).days)
    return pd.Series(values, index=precip.index, dtype="Int64")


def window_counts(events: np.ndarray, hours: np.ndarray, lookback_h: int) -> np.ndarray:
    return np.searchsorted(events, hours, side="right") - np.searchsorted(events, hours - lookback_h * HOUR_NS, side="right")


def rolling_nearest(events: np.ndarray, distances: np.ndarray, hours: np.ndarray) -> np.ndarray:
    candidates, cursor, result = deque(), 0, np.full(len(hours), np.nan)
    for row, timestamp in enumerate(hours):
        while cursor < len(events) and events[cursor] <= timestamp:
            while candidates and distances[candidates[-1]] >= distances[cursor]:
                candidates.pop()
            candidates.append(cursor)
            cursor += 1
        while candidates and events[candidates[0]] <= timestamp - 168 * HOUR_NS:
            candidates.popleft()
        if candidates:
            result[row] = distances[candidates[0]]
    return result


def build_cell(cell: dict, weather: pd.DataFrame, detections: pd.DataFrame, config: dict, region_metric) -> tuple[pd.DataFrame, dict]:
    frame = weather.set_index("ts").sort_index()
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq="h", tz="UTC"))
    for hours, column in ((24, "rain_24h_mm"), (168, "rain_7d_mm"), (720, "rain_30d_mm")):
        frame[column] = frame["precip_mm"].rolling(hours, min_periods=hours).sum()
    frame["vpd_mean_24h"] = frame["vpd_kpa"].rolling(24, min_periods=24).mean()
    frame["sm_27_81_delta_7d"] = frame["sm_27_81"] - frame["sm_27_81"].shift(168)
    frame["soil_air_temp_gap_c"] = frame["soil_temp_18_c"] - frame["temp_c"]
    frame["days_since_rain"] = days_since_rain(frame["precip_mm"])
    hours = frame.index.asi8
    event_times = detections["time_ns"].to_numpy()
    in_cell = detections["cell_id"].eq(cell["cell_id"]).to_numpy() & detections["in_scope"].to_numpy()
    cell_times = event_times[in_cell]
    distances = haversine_km(cell["lat"], cell["lon"], detections["latitude"].to_numpy(), detections["longitude"].to_numpy())
    nearby = distances <= 10
    nearby_times = event_times[nearby]
    coverage = config["firms_export_coverage"]
    coverage_start, coverage_end = pd.Timestamp(coverage["start"]).value, pd.Timestamp(coverage["end_exclusive"]).value
    coverage_confirmed = coverage["status"] in {
        "human_declared_complete_local_J1V_J2V_exports",
        "live_nrt_api_request_succeeded",
    }
    valid_24 = (hours - 24 * HOUR_NS >= coverage_start) & (hours < coverage_end) & coverage_confirmed
    valid_7d = (hours - 168 * HOUR_NS >= coverage_start) & (hours < coverage_end) & coverage_confirmed
    frame["hotspots_in_cell_24h"] = pd.array(np.where(valid_24, window_counts(cell_times, hours, 24), np.nan), dtype="Int64")
    # Coverage outside the regional boundary was not declared. A full 10 km disk
    # must lie inside that boundary before publishing a complete nearby count.
    metric_target = transform(TO_AREA, Point(cell["lon"], cell["lat"]))
    distance_to_boundary_km = metric_target.distance(region_metric.boundary) / 1000 if region_metric.covers(metric_target) else 0
    complete_nearby_scope = distance_to_boundary_km >= 10.05  # small projection margin
    valid_nearby = valid_7d & complete_nearby_scope
    frame["hotspots_10km_7d"] = pd.array(np.where(valid_nearby, window_counts(nearby_times, hours, 168), np.nan), dtype="Int64")
    frp = detections.loc[nearby, "frp"].to_numpy(dtype=float)
    invalid_frp = ~np.isfinite(frp) | (frp < 0)
    right = np.searchsorted(nearby_times, hours, side="right")
    left = np.searchsorted(nearby_times, hours - 168 * HOUR_NS, side="right")
    sums = np.r_[0.0, np.cumsum(np.where(invalid_frp, 0, frp))]
    invalid_counts = np.r_[0, np.cumsum(invalid_frp)]
    frame["frp_sum_10km_7d"] = np.where(valid_nearby & ((invalid_counts[right] - invalid_counts[left]) == 0),
                                          np.maximum(0, sums[right] - sums[left]), np.nan)
    nearest = rolling_nearest(event_times, distances, hours)
    # A missing observation beyond the boundary cannot change a closer in-region result.
    frame["nearest_hotspot_km"] = np.where(valid_7d & (nearest < distance_to_boundary_km / 1.01), nearest, np.nan)
    for horizon in config["horizons_h"]:
        count = np.searchsorted(cell_times, hours + horizon * HOUR_NS, side="right") - np.searchsorted(cell_times, hours, side="right")
        complete = (hours >= coverage_start) & (hours + horizon * HOUR_NS < coverage_end) & coverage_confirmed
        frame[f"target_{horizon}h"] = pd.array(np.where(complete, (count > 0).astype(int), np.nan), dtype="Int8")
    frame["schema_version"], frame["cell_id"] = "1.0", cell["cell_id"]
    for column in ("lat", "lon", "peat_fraction", "peat_area_km2"):
        frame[column] = float(cell[column])
    start, end = pd.Timestamp(config["start_date"], tz="UTC"), pd.Timestamp(config["end_date"], tz="UTC") + pd.Timedelta(days=1)
    frame = frame[(frame.index >= start) & (frame.index < end)].copy()
    frame["ts"] = frame.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    columns = ["schema_version", "cell_id", "ts", "lat", "lon", *FEATURES, *[f"target_{h}h" for h in config["horizons_h"]]]
    return frame[columns].reset_index(drop=True), {"cell_id": cell["cell_id"],
            "complete_10km_geographic_coverage": complete_nearby_scope,
            "distance_to_declared_coverage_boundary_km": distance_to_boundary_km}


def as_json_record(row: dict, polygon_ids: list) -> dict:
    result = {key: row[key] for key in ("schema_version", "cell_id", "ts", "lat", "lon")}
    integers = {"days_since_rain", "hotspots_in_cell_24h", "hotspots_10km_7d"}
    for group, columns in GROUPS.items():
        result[group] = {column: None if pd.isna(row[column]) else int(row[column]) if column in integers else float(row[column]) for column in columns}
    result["peat"]["polygon_ids"] = list(polygon_ids)
    return result


def assemble(output_dir: Path, weather_path: Path, config_path: Path, bundle_name: str = "sample") -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config["soil_air_temp_gap_formula"] != "soil_temp_18_c - temp_c" or config["nearest_hotspot_lookback_h"] != 168:
        raise ValueError("This implementation requires the agreed definitions; discuss any change before use")
    cells = pd.read_parquet(output_dir / "cells.parquet")
    weather = pd.read_parquet(weather_path)
    weather["ts"] = pd.to_datetime(weather["ts"], utc=True)
    detections = pd.read_parquet(output_dir / "firms_normalized.parquet")
    detections = detections[detections["alert_eligible"]].copy()
    detections["time_ns"] = pd.to_datetime(detections["ts"], utc=True).astype("int64")
    detections = detections.sort_values("time_ns").reset_index(drop=True)
    region, _, _ = load_boundary(output_dir / "cache")
    region_metric = transform(TO_AREA, region)
    shapely.prepare(region_metric)
    frames, spatial_reports = [], []
    for cell_id, cell_weather in weather.groupby("cell_id", sort=True):
        cell = cells[cells["cell_id"] == cell_id].iloc[0].to_dict()
        frame, spatial = build_cell(cell, cell_weather, detections, config, region_metric)
        frames.append(frame)
        spatial_reports.append(spatial)
        print(f"Features: {cell_id}: {len(frame):,} hourly rows", flush=True)
    if not frames:
        raise ValueError("No weather-backed cells to assemble")
    history = pd.concat(frames, ignore_index=True)
    if history.duplicated(["cell_id", "ts"]).any():
        raise ValueError("Duplicate historical cell/hour")
    for column in FEATURES:
        if column not in {"days_since_rain", "hotspots_in_cell_24h", "hotspots_10km_7d"}:
            history[column] = history[column].astype("float64")
    snapshot = history[history["ts"] == config["replay_snapshot"]].copy()
    snapshot = snapshot[~snapshot[GROUPS["weather"]].isna().all(axis=1)]
    if len(snapshot) != history["cell_id"].nunique():
        raise ValueError("Configured snapshot does not have usable weather for every selected cell")
    bundle = output_dir / bundle_name
    if not bundle.resolve().is_relative_to(output_dir.resolve()):
        raise ValueError("Bundle directory must stay within the output workspace")
    snapshot_features = snapshot.drop(columns=[f"target_{h}h" for h in config["horizons_h"]])
    write_parquet(history, bundle / "history.parquet")
    write_parquet(snapshot_features, bundle / "features.parquet")
    polygon_lookup = dict(zip(cells["cell_id"], cells["polygon_ids"]))
    records = [as_json_record(row, polygon_lookup[row["cell_id"]]) for row in snapshot_features.to_dict("records")]
    write_json(bundle / "features.json", records)
    geometry = json.loads((output_dir / "cells.geojson").read_text(encoding="utf-8"))
    ids = set(snapshot["cell_id"])
    geometry["features"] = [feature for feature in geometry["features"] if feature["properties"]["cell_id"] in ids]
    write_json(bundle / "cells.geojson", geometry)
    targets = [f"target_{h}h" for h in config["horizons_h"]]
    report = {"generated_at": utc_now(), "is_mock": False, "mode": "historical_replay",
              "snapshot": config["replay_snapshot"], "history_rows": len(history), "cells": len(ids),
              "first_hour": history["ts"].min(), "last_hour": history["ts"].max(),
              "missing_values": {column: int(history[column].isna().sum()) for column in FEATURES + targets},
              "entirely_missing_features": [column for column in FEATURES if history[column].isna().all()],
              "rows_with_all_targets": int(history[targets].notna().all(axis=1).sum()),
              "target_counts": {column: {str(k): int(v) for k, v in history[column].value_counts(dropna=False).items()} for column in targets},
              "spatial_coverage": spatial_reports, "definitions": config,
              "notes": ["Coverage is human-declared export completeness; satellite observation availability is not independently verified.",
                        "10km features stay null where the required disk crosses the declared regional boundary.",
                        "Nearest distance stays null when an unobserved source outside the declared region could be nearer.",
                        "Incomplete future windows remain null. No model has been trained or evaluated by Role A."]}
    write_json(bundle / "quality_report.json", report)
    print(json.dumps({k: report[k] for k in ("history_rows", "cells", "rows_with_all_targets", "entirely_missing_features")}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    parser.add_argument("--weather", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "a_data/processing_config.json")
    parser.add_argument("--bundle-name", default="sample")
    args = parser.parse_args()
    assemble(args.output_dir, args.weather or args.output_dir / "weather_sample.parquet", args.config, args.bundle_name)


if __name__ == "__main__":
    main()
