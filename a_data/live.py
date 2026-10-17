"""Refresh current Role A features for the frozen 40-cell Kalimantan bundle."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

import numpy as np
import pandas as pd
import requests
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from a_data.assemble import as_json_record, build_cell
from a_data.common import ROOT, WEATHER_MAP, utc_now, write_json, write_parquet
from a_data.geography import AREA_CRS, TO_AREA, load_boundary
from a_data.weather import LIVE_API, parse_response
from contracts.validate import validate_file

FIRMS_AREA_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
FIRMS_DAY_RANGE = 5
FIRMS_LOOKBACK_DAYS = 10
WEATHER_TEMPLATE_PATH = ROOT / "data/raw/open-meteo_api.md"
WEATHER_PAST_DAYS = 30
WEATHER_FORECAST_DAYS = 3
TO_WGS84 = Transformer.from_crs(AREA_CRS, "EPSG:4326", always_xy=True).transform


def _firms_key() -> str:
    value = os.environ.get("FIRMS_MAP_KEY")
    if value:
        return value.strip()
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, separator, raw = line.partition("=")
            if separator and name.strip() == "FIRMS_MAP_KEY":
                value = raw.strip().strip("\"'")
                if value:
                    return value
    raise RuntimeError("FIRMS_MAP_KEY is missing; set it in the environment or the ignored repository .env file.")


def _safe_error(error: Exception, key: str) -> str:
    return str(error).replace(key, "[redacted]")


def _weather_template() -> tuple[str, dict[str, str]]:
    text = WEATHER_TEMPLATE_PATH.read_text(encoding="utf-8")
    match = re.search(r'Weather Forecast API\s*=\s*"\s*(https?://[^"\s]+)\s*"', text)
    if not match:
        raise ValueError(f"Could not find the Weather Forecast API URL in {WEATHER_TEMPLATE_PATH}")
    template = match.group(1)
    parts = urlsplit(template)
    endpoint = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if endpoint != LIVE_API:
        raise ValueError("The markdown weather URL must use the Open-Meteo Forecast API endpoint")
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    required = {"latitude", "longitude", "hourly", "timezone", "past_days", "forecast_days"}
    if not required.issubset(params):
        raise ValueError("The markdown weather URL is missing required location, variable, or time-range parameters")
    if params["timezone"] != "GMT" or int(params["past_days"]) != WEATHER_PAST_DAYS or int(params["forecast_days"]) != WEATHER_FORECAST_DAYS:
        raise ValueError("The markdown weather URL's time settings must be GMT, past_days=30, forecast_days=3")
    if not set(WEATHER_MAP).issubset(params["hourly"].split(",")):
        raise ValueError("The markdown weather URL does not request all canonical schema 1.0 weather variables")
    return endpoint, params


def _weather_request(session: requests.Session, cell: dict, cache_dir: Path) -> tuple[pd.DataFrame, dict]:
    endpoint, template_params = _weather_template()
    params = {**template_params, "latitude": float(cell["lat"]), "longitude": float(cell["lon"])}
    response = None
    for attempt in range(3):
        try:
            response = session.get(endpoint, params=params, timeout=(15, 90))
            if response.status_code == 429:
                raise RuntimeError("Open-Meteo returned 429; pause and retry after the provider quota resets")
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            if exc.response is not None and exc.response.status_code < 500:
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    payload = response.json()
    if payload.get("error"):
        raise ValueError(f"Open-Meteo error: {payload.get('reason', 'unspecified')}")
    if payload.get("utc_offset_seconds") != 0:
        raise ValueError("Open-Meteo did not return UTC")
    if not set(WEATHER_MAP).issubset(payload.get("hourly", {})):
        raise ValueError("Open-Meteo omitted one or more required schema 1.0 weather variables")
    cached = {"retrieved_at": utc_now(), "cell_id": cell["cell_id"],
              "request": {"endpoint": LIVE_API, "params": params}, "response": payload}
    write_json(cache_dir / f"{cell['cell_id']}.json", cached, compact=True)
    frame, report = parse_response(cached, cell)
    if frame["ts"].duplicated().any() or frame[list(WEATHER_MAP.values())].isna().all(axis=1).any():
        raise ValueError(f"Weather response for {cell['cell_id']} has duplicate hours or all-null weather")
    return frame, report


def _query_dates(today: pd.Timestamp) -> list[str]:
    # The FIRMS area service accepts at most five dates per request. Two
    # adjacent, non-overlapping windows provide the seven-day fire features.
    oldest = today - pd.Timedelta(days=FIRMS_LOOKBACK_DAYS - 1)
    newer = today - pd.Timedelta(days=FIRMS_DAY_RANGE - 1)
    return [oldest.strftime("%Y-%m-%d"), newer.strftime("%Y-%m-%d")]


def _fetch_firms(session: requests.Session, key: str, region, cache_dir: Path,
                 today: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    buffered_region = transform(TO_AREA, region).buffer(10_050)
    buffered_wgs84 = transform(TO_WGS84, buffered_region)
    west, south, east, north = buffered_wgs84.bounds
    area = ",".join(f"{value:.5f}" for value in (west, south, east, north))
    requested_dates = _query_dates(today)
    frames, report = [], []
    for source in FIRMS_SOURCES:
        for query_start in requested_dates:
            # API keys are part of this provider's path format; never emit the
            # request URL or unredacted exception text to logs or manifests.
            url = (f"{FIRMS_AREA_API}/{quote(key, safe='')}/{source}/{area}/"
                   f"{FIRMS_DAY_RANGE}/{query_start}")
            try:
                response = session.get(url, timeout=(15, 90))
            except requests.RequestException as exc:
                raise RuntimeError(f"FIRMS request failed: {_safe_error(exc, key)}") from None
            if response.status_code >= 400:
                raise RuntimeError(f"FIRMS API returned HTTP {response.status_code} for {source} starting {query_start}")
            raw_path = cache_dir / f"{source}_{query_start}_{FIRMS_DAY_RANGE}d.csv"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = raw_path.with_suffix(raw_path.suffix + ".tmp")
            temporary.write_text(response.text, encoding="utf-8")
            temporary.replace(raw_path)
            try:
                frame = pd.read_csv(io.StringIO(response.text))
            except Exception as exc:
                raise ValueError(f"Could not parse FIRMS response for {source} starting {query_start}") from exc
            required = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "frp"}
            if not required.issubset(frame.columns):
                raise ValueError(f"FIRMS response for {source} is missing required columns")
            frames.append(frame)
            report.append({"product": source, "start_date": query_start,
                           "end_date_exclusive": (pd.Timestamp(query_start) + pd.Timedelta(days=FIRMS_DAY_RANGE)).strftime("%Y-%m-%d"),
                           "response_rows": int(len(frame)), "cache_file": raw_path.name})
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if raw.empty:
        empty = pd.DataFrame({"ts": pd.Series(dtype="datetime64[ns, UTC]"), "time_ns": pd.Series(dtype="int64"),
                              "latitude": pd.Series(dtype="float64"), "longitude": pd.Series(dtype="float64"),
                              "frp": pd.Series(dtype="float64"), "cell_id": pd.Series(dtype="object"),
                              "in_scope": pd.Series(dtype="bool"), "alert_eligible": pd.Series(dtype="bool")})
        return empty, {
            "queries": report, "response_rows": 0, "retained_in_buffer": 0, "retained_alert_eligible": 0,
            "bbox_west_south_east_north": [west, south, east, north]}
    raw["latitude"] = pd.to_numeric(raw["latitude"], errors="coerce")
    raw["longitude"] = pd.to_numeric(raw["longitude"], errors="coerce")
    raw["frp"] = pd.to_numeric(raw["frp"], errors="coerce")
    raw["confidence"] = raw["confidence"].astype(str).str.strip().str.lower()
    acq_time = raw["acq_time"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    raw["ts"] = pd.to_datetime(raw["acq_date"].astype(str) + " " + acq_time,
                               format="%Y-%m-%d %H%M", utc=True, errors="coerce")
    raw = raw.dropna(subset=["latitude", "longitude", "ts"])
    window_start = pd.Timestamp(requested_dates[0], tz="UTC")
    window_end = today + pd.Timedelta(days=1)
    raw = raw[(raw["ts"] >= window_start) & (raw["ts"] < window_end)]
    raw = raw[(raw["latitude"].between(-90, 90)) & (raw["longitude"].between(-180, 180))]
    inside = np.asarray(shapely.contains_xy(buffered_region, raw["longitude"].to_numpy(), raw["latitude"].to_numpy()))
    raw = raw.loc[inside].copy()
    raw["in_scope"] = np.asarray(shapely.contains_xy(region, raw["longitude"].to_numpy(), raw["latitude"].to_numpy()))
    raw["alert_eligible"] = raw["confidence"].isin(["n", "h"])
    raw["cell_id"] = [f"{np.floor(lat * 10) / 10 + 0.05:.2f}_{np.floor(lon * 10) / 10 + 0.05:.2f}"
                      for lat, lon in zip(raw["latitude"], raw["longitude"])]
    raw["time_ns"] = raw["ts"].astype("int64")
    raw = raw.drop_duplicates(subset=["ts", "latitude", "longitude", "satellite", "confidence", "frp"])
    raw = raw.sort_values("time_ns").reset_index(drop=True)
    return raw, {"queries": report, "response_rows": int(sum(item["response_rows"] for item in report)),
                 "retained_in_buffer": int(len(raw)), "retained_alert_eligible": int(raw["alert_eligible"].sum()),
                 "bbox_west_south_east_north": [west, south, east, north]}


def _cells_from_geojson(path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells = []
    for feature in payload["features"]:
        props = feature["properties"]
        cells.append({key: props[key] for key in ("cell_id", "lat", "lon", "peat_fraction", "peat_area_km2", "polygon_ids")})
    if len(cells) != 40 or len({cell["cell_id"] for cell in cells}) != 40:
        raise ValueError("Live refresh requires the frozen, unique 40-cell regional bundle")
    return cells, payload


def refresh_live(source_dir: Path, output_dir: Path) -> dict:
    """Fetch current weather and NRT detections, then atomically publish A's feed."""
    source_dir, output_dir = source_dir.resolve(), output_dir.resolve()
    if source_dir == output_dir or source_dir in output_dir.parents or output_dir in source_dir.parents:
        raise ValueError("Live output must be a separate directory from the frozen source bundle")
    for name in ("features.json", "history.parquet", "cells.geojson", "selection.json"):
        if not (source_dir / name).is_file():
            raise FileNotFoundError(source_dir / name)
    key = _firms_key()
    cells, cells_payload = _cells_from_geojson(source_dir / "cells.geojson")
    selection = json.loads((source_dir / "selection.json").read_text(encoding="utf-8"))
    if set(selection.get("cell_ids", [])) != {cell["cell_id"] for cell in cells}:
        raise ValueError("Frozen selection metadata does not match its cell geometry")
    validate_file("features", source_dir / "features.json")
    source_features = json.loads((source_dir / "features.json").read_text(encoding="utf-8"))
    if {row["cell_id"] for row in source_features} != {cell["cell_id"] for cell in cells}:
        raise ValueError("Frozen features and geometry refer to different cells")
    history_path = source_dir / "history.parquet"
    history = pd.read_parquet(history_path)
    if history["cell_id"].nunique() != 40 or history.duplicated(["cell_id", "ts"]).any():
        raise ValueError("Historical context does not match the frozen 40-cell bundle")
    per_cell_end = history.groupby("cell_id")["ts"].max()
    if per_cell_end.nunique() != 1:
        raise ValueError("Historical context has different final timestamps across cells")
    history_end = pd.Timestamp(per_cell_end.iloc[0])
    retrieved = pd.Timestamp.now(tz="UTC").floor("s")
    today = retrieved.normalize()
    weather_cache = output_dir / "cache/raw_weather"
    firms_cache = output_dir / "cache/raw_firms"
    weather_cache.mkdir(parents=True, exist_ok=True)
    firms_cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    weather_frames, weather_reports = [], []
    for index, cell in enumerate(cells, start=1):
        frame, report = _weather_request(session, cell, weather_cache)
        weather_frames.append(frame)
        weather_reports.append(report)
        print(f"Live weather: {cell['cell_id']} ({index}/{len(cells)})", flush=True)
    latest_by_cell = {frame["cell_id"].iloc[0]: frame.loc[frame["ts"] <= retrieved.floor("h"), "ts"].max()
                      for frame in weather_frames}
    if any(pd.isna(value) for value in latest_by_cell.values()):
        raise ValueError("At least one cell has no current or past hourly weather")
    snapshot = min(latest_by_cell.values())
    if snapshot <= history_end:
        raise ValueError(f"Live weather is not newer than the training history (latest {snapshot.isoformat()})")
    if (snapshot - history_end) > pd.Timedelta(hours=24):
        raise ValueError("Live weather is more than 24 hours beyond saved history; refusing a discontinuous B context")
    detections, firms_report = _fetch_firms(session, key, load_boundary(source_dir.parent / "cache")[0], firms_cache, today)
    detections = detections[detections["alert_eligible"] & (detections["ts"] <= snapshot)].copy()
    detections["time_ns"] = detections["ts"].astype("int64")
    detections = detections.sort_values("time_ns").reset_index(drop=True)
    weather = pd.concat(weather_frames, ignore_index=True)
    weather["ts"] = pd.to_datetime(weather["ts"], utc=True)
    # Keep enough warmup for the 30-day rain field, then build the live rows
    # with the same feature code and declared formulas as the historical set.
    start = snapshot - pd.Timedelta(days=WEATHER_PAST_DAYS)
    config = json.loads((ROOT / "a_data/processing_config.json").read_text(encoding="utf-8"))
    config["start_date"] = start.strftime("%Y-%m-%d")
    config["end_date"] = snapshot.strftime("%Y-%m-%d")
    config["firms_export_coverage"] = {
        "start": (today - pd.Timedelta(days=FIRMS_LOOKBACK_DAYS - 1)).strftime("%Y-%m-%dT00:00:00Z"),
        "end_exclusive": (today + pd.Timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
        "status": "live_nrt_api_request_succeeded",
    }
    region, _, _ = load_boundary(source_dir.parent / "cache")
    region_metric = transform(TO_AREA, region)
    alert_detections = detections[detections["alert_eligible"]].copy()
    frames = []
    for cell in cells:
        cell_weather = weather[weather["cell_id"].eq(cell["cell_id"])].copy()
        built, _ = build_cell(cell, cell_weather, alert_detections, config, region_metric)
        built_ts = pd.to_datetime(built["ts"], utc=True)
        new_rows = built[(built_ts > history_end) & (built_ts <= snapshot)].copy()
        if new_rows.empty or new_rows["ts"].iloc[-1] != snapshot.strftime("%Y-%m-%dT%H:%M:%SZ"):
            raise ValueError(f"Feature rows for {cell['cell_id']} do not reach the common live snapshot")
        cell_history_end = pd.to_datetime(history.loc[history["cell_id"].eq(cell["cell_id"]), "ts"], utc=True).max()
        new_times = pd.to_datetime(new_rows["ts"], utc=True)
        expected = pd.date_range(cell_history_end + pd.Timedelta(hours=1), snapshot, freq="h", tz="UTC")
        if not new_times.reset_index(drop=True).equals(pd.Series(expected, name=new_times.name)):
            raise ValueError(f"Live rows for {cell['cell_id']} do not form a contiguous hourly extension")
        for target in ("target_24h", "target_48h", "target_72h"):
            new_rows[target] = pd.NA
        frames.append(new_rows)
    live_rows = pd.concat(frames, ignore_index=True)
    combined_history = pd.concat([history, live_rows], ignore_index=True)
    if combined_history.duplicated(["cell_id", "ts"]).any():
        raise ValueError("Appending live weather created duplicate cell/hour rows")
    combined_history = combined_history.sort_values(["cell_id", "ts"]).reset_index(drop=True)
    features = live_rows[live_rows["ts"] == snapshot.strftime("%Y-%m-%dT%H:%M:%SZ")].copy()
    if len(features) != 40 or features["cell_id"].nunique() != 40:
        raise ValueError("The live snapshot must contain exactly one row for each of the 40 cells")
    if features[list(WEATHER_MAP.values())].isna().all(axis=1).any():
        raise ValueError("A live snapshot cell has all-null weather")
    features = features.drop(columns=["target_24h", "target_48h", "target_72h"])
    polygon_lookup = {cell["cell_id"]: cell["polygon_ids"] for cell in cells}
    records = [as_json_record(row, polygon_lookup[row["cell_id"]]) for row in features.to_dict("records")]
    # Validate the complete new feature feed before touching published files.
    staging = output_dir / ".staging"
    write_json(staging / "features.json", records)
    validate_file("features", staging / "features.json")
    validate_file("cells", source_dir / "cells.geojson")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_parquet(combined_history, staging / "history.parquet")
    write_parquet(features, staging / "features.parquet")
    staged_cells = staging / "cells.geojson"
    staged_cells.write_text(json.dumps(cells_payload, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    manifest = {
        "generated_at": utc_now(), "is_mock": False, "mode": "live", "schema_version": "1.0",
        "scope": "Frozen 40 peat-centered cells across Indonesian Kalimantan; eight per province",
        "cell_count": 40, "snapshot": snapshot.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "history_start": str(history["ts"].min()), "history_end_before_refresh": history_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "history_rows_before": int(len(history)), "history_rows_after": int(len(combined_history)),
        "appended_live_rows": int(len(live_rows)), "new_targets": "null; live FIRMS observations are not training labels",
        "weather": {"provider": "Open-Meteo Forecast API",
                    "model": _weather_template()[1].get("models", "best_match (provider default)"),
                    "requests": len(weather_reports),
                    "past_days": WEATHER_PAST_DAYS, "forecast_days_requested": WEATHER_FORECAST_DAYS,
                    "cells": weather_reports, "source_url": LIVE_API,
                    "note": ("Modeled weather; only hourly values at or before retrieval time are published."
                             if _weather_template()[1].get("models") == "icon_global" else
                             "Modeled weather; only hourly values at or before retrieval time are published. The request model differs from historical icon_global weather.")},
        "firms": {"provider": "NASA FIRMS Area API", "products": list(FIRMS_SOURCES),
                  "lookback_date_days": FIRMS_LOOKBACK_DAYS, "day_range_per_request": FIRMS_DAY_RANGE,
                  **firms_report,
                  "note": "NRT query success is provisional feed coverage; recent overpass/processing delays can leave the latest hours incomplete.",
                  "source_url": "https://firms.modaps.eosdis.nasa.gov/api/area/"},
        "limitations": ["NRT detections can be revised or delayed and do not establish complete ground-truth coverage.",
                        "The frozen model scope samples 40 cells, not every Kalimantan peat cell.",
                        "This command only ingests Role A feeds; Role B inference and Role C policy remain separate steps."],
    }
    write_json(staging / "live_manifest.json", manifest)
    # Publish each validated artifact with atomic replacement. No historical
    # replay bundle is modified; consumers point to this separate directory.
    for name in ("features.json", "features.parquet", "history.parquet", "cells.geojson", "live_manifest.json"):
        target = output_dir / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes((staging / name).read_bytes())
        temporary.replace(target)
    print(f"A: live snapshot {manifest['snapshot']} for 40 cells written to {output_dir}", flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/demo/role_a_real/regional_40")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real/live")
    args = parser.parse_args()
    try:
        refresh_live(args.source_dir, args.output_dir)
    except requests.RequestException as exc:
        key = os.environ.get("FIRMS_MAP_KEY", "")
        message = _safe_error(exc, key) if key else str(exc)
        raise SystemExit(f"Live refresh failed; no feature bundle was published: {message}") from None


if __name__ == "__main__":
    main()
