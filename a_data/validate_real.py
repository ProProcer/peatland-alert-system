"""Audit the real sample against source events and frozen interfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

from a_data.assemble import haversine_km
from a_data.common import FEATURES, GROUPS, ROOT, sha256, utc_now, write_json
from a_data.water import WaterIndex
from contracts.validate import validate_file


def validate(output_dir: Path, bundle_name: str = "sample", weather_path: Path | None = None) -> dict:
    checks = []

    def require(condition, name):
        if not condition:
            raise ValueError(f"Real-data audit failed: {name}")
        checks.append(name)

    bundle = output_dir / bundle_name
    validate_file("features", bundle / "features.json")
    validate_file("cells", bundle / "cells.geojson")
    validate_file("cells", output_dir / "cells.geojson")
    checks.append("Real feature JSON and both cell maps satisfy schema 1.0")
    history = pd.read_parquet(bundle / "history.parquet")
    snapshot = pd.read_parquet(bundle / "features.parquet")
    config = json.loads((ROOT / "a_data/processing_config.json").read_text())
    require(not history.duplicated(["cell_id", "ts"]).any(), "Unique historical cell/hour keys")
    require(history["ts"].str.endswith("Z").all(), "UTC Z timestamps")
    require(not history[GROUPS["weather"]].isna().all(axis=1).any(), "No all-null hourly weather rows")
    values = history[FEATURES].to_numpy(dtype=float, na_value=np.nan)
    require(not np.isinf(values).any() and not (values == -999).any(), "No infinite or sentinel measurements")
    require(not history[FEATURES].isna().all().any(), "Every canonical feature has observed sample values")
    for cell_id, cell_history in history.groupby("cell_id"):
        timestamps = pd.to_datetime(cell_history["ts"], utc=True)
        require((timestamps.diff().dropna() == pd.Timedelta(hours=1)).all(), f"Contiguous hourly history: {cell_id}")
    targets = [f"target_{h}h" for h in config["horizons_h"]]
    require(history[targets].stack().isin([0, 1]).all(), "Observed target values are binary")
    complete = history.dropna(subset=targets)
    require(((complete["target_24h"] <= complete["target_48h"]) & (complete["target_48h"] <= complete["target_72h"])).all(), "Future targets are monotonic across horizons")
    detection_frame = pd.read_parquet(output_dir / "firms_normalized.parquet")
    detection_frame = detection_frame[detection_frame["alert_eligible"]].copy()
    detection_frame["at"] = pd.to_datetime(detection_frame["ts"], utc=True)
    coverage_end = pd.Timestamp(config["firms_export_coverage"]["end_exclusive"])
    coverage_start = pd.Timestamp(config["firms_export_coverage"]["start"])
    label_cases = 0
    for horizon in config["horizons_h"]:
        column = f"target_{horizon}h"
        valid_future = pd.to_datetime(history["ts"], utc=True) + pd.Timedelta(hours=horizon) < coverage_end
        require(history.loc[~valid_future, column].isna().all(), f"Incomplete {horizon}h tail labels remain null")
        for label in (0, 1):
            examples = history[history[column] == label].iloc[::max(1, int((history[column] == label).sum()) // 15)].head(15)
            for row in examples.to_dict("records"):
                timestamp = pd.Timestamp(row["ts"])
                events = detection_frame[detection_frame["in_scope"] & detection_frame["cell_id"].eq(row["cell_id"])]
                expected = int(((events["at"] > timestamp) & (events["at"] <= timestamp + pd.Timedelta(hours=horizon))).any())
                require(int(row[column]) == expected, f"Raw-event label {column}: {row['cell_id']} {row['ts']}")
                label_cases += 1
    weather = pd.read_parquet(weather_path or output_dir / "weather_sample.parquet")
    weather["at"] = pd.to_datetime(weather["ts"], utc=True)
    feature_cases = 0
    for row in history.iloc[::max(1, len(history) // 25)].to_dict("records"):
        timestamp = pd.Timestamp(row["ts"])
        raw_weather = weather[weather["cell_id"].eq(row["cell_id"])]
        for window, column in ((24, "rain_24h_mm"), (168, "rain_7d_mm"), (720, "rain_30d_mm")):
            observed = raw_weather[(raw_weather["at"] > timestamp - pd.Timedelta(hours=window)) & (raw_weather["at"] <= timestamp)]["precip_mm"]
            expected = observed.sum() if len(observed) == window and observed.notna().all() else np.nan
            require((pd.isna(expected) and pd.isna(row[column])) or np.isclose(expected, row[column]), f"Trailing rainfall {column}: {row['cell_id']} {row['ts']}")
        expected_gap = row["soil_temp_18_c"] - row["temp_c"]
        require(np.isclose(row["soil_air_temp_gap_c"], expected_gap, equal_nan=True), f"Agreed soil/air gap: {row['cell_id']} {row['ts']}")
        if pd.notna(row["hotspots_in_cell_24h"]):
            events = detection_frame[detection_frame["in_scope"] & detection_frame["cell_id"].eq(row["cell_id"])]
            expected = ((events["at"] > timestamp - pd.Timedelta(hours=24)) & (events["at"] <= timestamp)).sum()
            require(int(row["hotspots_in_cell_24h"]) == expected, f"Trailing raw-event count: {row['cell_id']} {row['ts']}")
        if pd.notna(row["nearest_hotspot_km"]):
            events = detection_frame[(detection_frame["at"] > timestamp - pd.Timedelta(days=7)) & (detection_frame["at"] <= timestamp)]
            expected = haversine_km(row["lat"], row["lon"], events["latitude"].to_numpy(), events["longitude"].to_numpy()).min()
            require(np.isclose(row["nearest_hotspot_km"], expected), f"Nearest seven-day raw event: {row['cell_id']} {row['ts']}")
        feature_cases += 1
    require(coverage_start == pd.Timestamp(config["start_date"], tz="UTC"), "Explicit declared export coverage start")
    manifest = json.loads((output_dir / "source_manifest.json").read_text(encoding="utf-8"))
    require(all(sha256(ROOT / item["path"]) == item["sha256"] for item in manifest["sources"]), "All six original raw sources retain their recorded hashes")
    from b_model.features import flatten_features_json
    loaded = flatten_features_json(bundle / "features.json", history_path=bundle / "history.parquet")
    require(len(loaded) == len(snapshot), "Role B loader accepts real JSON against real Parquet dtypes")
    water_path = output_dir / "water_sources.geojson"
    examples = []
    if water_path.exists():
        catalogue = json.loads(water_path.read_text(encoding="utf-8"))
        require(all(f["properties"]["is_mock"] is False for f in catalogue["features"]), "Water candidates are explicitly real OSM features")
        require(len({f["properties"]["source_id"] for f in catalogue["features"]}) == len(catalogue["features"]), "Water OSM IDs are unique")
        require(all(shape(f["geometry"]).is_valid for f in catalogue["features"]), "Extracted water geometries are valid")
        index = WaterIndex(water_path)
        schema = json.loads((ROOT / "contracts/dispatch.schema.json").read_text(encoding="utf-8"))["items"]["properties"]["water_source"]
        for row in snapshot.head(5).to_dict("records"):
            for suffix, offset in (("center", 0), ("shifted", .02)):
                lat, lon = row["lat"] + offset, row["lon"] + offset
                lookup = index.nearest(lat, lon)
                jsonschema.Draft202012Validator(schema).validate(lookup["water_source"])
                examples.append({"case_id": f"{row['cell_id']}_{suffix}", "is_mock": False,
                                 "cell_id": row["cell_id"], "ts": row["ts"], "target": {"lat": lat, "lon": lon}, **lookup})
        write_json(bundle / "water_lookup_examples.json", {"is_mock": False,
                   "distance_method": "Straight-line distance in local LAEA projection to mapped line, point, or polygon shoreline; not road routing or verified access.",
                   "examples": examples})
        checks.append("Real center and shifted-target lookups use the frozen dispatch water_source shape")
    report = {"generated_at": utc_now(), "status": "passed", "checks_passed": len(checks),
              "label_cases_checked_against_raw_events": label_cases, "feature_hours_checked_against_sources": feature_cases,
              "checks": checks, "water_lookup_examples": len(examples),
              "limitation": "Source correctness audits do not evaluate model performance. Full-region weather is still a separate staged download."}
    write_json(bundle / "validation_report.json", report)
    print(json.dumps({k: report[k] for k in ("status", "checks_passed", "label_cases_checked_against_raw_events", "feature_hours_checked_against_sources", "water_lookup_examples")}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    parser.add_argument("--bundle-name", default="sample")
    parser.add_argument("--weather", type=Path)
    args = parser.parse_args()
    validate(args.output_dir, args.bundle_name, args.weather)


if __name__ == "__main__":
    main()
