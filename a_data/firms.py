"""Normalize local J1/J2 detections for Kalimantan and retain lookback context."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.ops import transform

from a_data.common import ROOT, utc_now, write_json, write_parquet
from a_data.geography import AREA_CRS, TO_AREA, load_boundary


def normalize(raw_dir: Path, output_dir: Path, start: str, end: str) -> dict:
    region, _, _ = load_boundary(output_dir / "cache")
    to_wgs = Transformer.from_crs(AREA_CRS, "EPSG:4326", always_xy=True).transform
    buffer_region = transform(to_wgs, transform(TO_AREA, region).buffer(10000))
    shapely.prepare(region)
    shapely.prepare(buffer_region)
    west, south, east, north = buffer_region.bounds
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    context_start = start_ts - pd.Timedelta(days=30)
    frames, source_counts = [], []
    for path in sorted(raw_dir.glob("DL_FIRE_*/*.csv")):
        counts = {"source_file": path.relative_to(ROOT).as_posix(), "rows_read": 0,
                  "invalid_datetime_or_coordinates": 0, "retained_with_context_and_buffer": 0}
        for chunk in pd.read_csv(path, dtype=str, chunksize=200000):
            counts["rows_read"] += len(chunk)
            lat = pd.to_numeric(chunk["latitude"], errors="coerce")
            lon = pd.to_numeric(chunk["longitude"], errors="coerce")
            times = chunk["acq_time"].str.strip().str.zfill(4)
            timestamps = pd.to_datetime(chunk["acq_date"] + " " + times,
                                        format="%Y-%m-%d %H%M", errors="coerce", utc=True)
            valid = lat.between(-90, 90) & lon.between(-180, 180) & timestamps.notna()
            counts["invalid_datetime_or_coordinates"] += int((~valid).sum())
            selected = valid & lat.between(south, north) & lon.between(west, east)
            selected &= (timestamps >= context_start) & (timestamps < end_ts)
            chunk = chunk.loc[selected].copy()
            if chunk.empty:
                continue
            chunk["latitude"], chunk["longitude"] = lat.loc[selected], lon.loc[selected]
            chunk["ts"] = timestamps.loc[selected]
            inside_buffer = shapely.intersects_xy(buffer_region, chunk["longitude"].to_numpy(), chunk["latitude"].to_numpy())
            chunk = chunk.loc[inside_buffer].copy()
            if chunk.empty:
                continue
            chunk["in_scope"] = shapely.intersects_xy(region, chunk["longitude"].to_numpy(), chunk["latitude"].to_numpy())
            chunk["in_requested_window"] = chunk["ts"] >= start_ts
            chunk["confidence"] = chunk["confidence"].str.lower().str.strip()
            chunk["alert_eligible"] = chunk["confidence"].isin(["n", "h"])
            chunk["source_file"] = path.relative_to(ROOT).as_posix()
            chunk["acq_time"] = times.loc[chunk.index]
            for column in ("frp", "brightness", "bright_ti4", "bright_t31", "bright_ti5", "scan", "track"):
                if column in chunk:
                    chunk[column] = pd.to_numeric(chunk[column], errors="coerce")
            iy = np.floor(chunk["latitude"].to_numpy() * 10).astype(int)
            ix = np.floor(chunk["longitude"].to_numpy() * 10).astype(int)
            chunk["cell_id"] = [f"{(y + .5) / 10:.2f}_{(x + .5) / 10:.2f}" for y, x in zip(iy, ix)]
            counts["retained_with_context_and_buffer"] += len(chunk)
            frames.append(chunk)
        source_counts.append(counts)
        print(f"FIRMS: {path.name}: {counts['retained_with_context_and_buffer']:,} retained", flush=True)
    if not frames:
        raise ValueError("No FIRMS observations retained for requested scope and dates")
    data = pd.concat(frames, ignore_index=True)
    before = len(data)
    subset = [c for c in data.columns if c not in {"source_file", "type"}]
    data = data.drop_duplicates(subset=subset).sort_values(["ts", "satellite", "latitude", "longitude"]).reset_index(drop=True)
    data["ts"] = data["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    requested = data[data["in_scope"] & data["in_requested_window"]]
    eligible = requested[requested["alert_eligible"]]
    daily = requested.groupby(requested["ts"].str[:10]).size()
    report = {"generated_at": utc_now(), "is_mock": False, "scope": "All Indonesian Kalimantan",
              "requested_start": start_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "requested_end_exclusive": end_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "context_start": context_start.strftime("%Y-%m-%dT%H:%M:%SZ"), "spatial_buffer_km": 10,
              "sources": source_counts, "retained_rows_with_context_and_buffer": len(data),
              "exact_duplicate_rows_removed": before - len(data), "requested_region_rows": len(requested),
              "nominal_high_requested_region_rows": len(eligible),
              "confidence_counts": {str(k): int(v) for k, v in requested["confidence"].value_counts().items()},
              "satellite_counts": {str(k): int(v) for k, v in requested["satellite"].value_counts().items()},
              "first_detection": requested["ts"].min(), "last_detection": requested["ts"].max(),
              "detections_by_day": {str(k): int(v) for k, v in daily.items()},
              "source_coverage_status": "unconfirmed; detection timestamps are not an availability manifest",
              "cell_edge_rule": "Half-open degree intervals [west,east) and [south,north), using floor(coord * 10).",
              "label_policy": "Future-window coverage must be established before absence becomes target=0."}
    write_parquet(data, output_dir / "firms_normalized.parquet")
    write_json(output_dir / "firms_report.json", report)
    print(json.dumps({k: report[k] for k in ("retained_rows_with_context_and_buffer", "requested_region_rows", "nominal_high_requested_region_rows", "first_detection", "last_detection")}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    parser.add_argument("--start-date", default="2024-12-02")
    parser.add_argument("--end-date", default="2026-10-17")
    args = parser.parse_args()
    normalize(args.raw_dir, args.output_dir, args.start_date, args.end_date)


if __name__ == "__main__":
    main()
