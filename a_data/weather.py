"""Fetch consistent ICON weather with persistent caches and conservative API budgets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from a_data.common import ROOT, WEATHER_MAP, utc_now, write_json, write_parquet

HISTORICAL_API = "https://historical-forecast-api.open-meteo.com/v1/forecast"
LIVE_API = "https://api.open-meteo.com/v1/forecast"


class WeatherBudgetExceeded(RuntimeError):
    pass


class WeatherClient:
    def __init__(self, cache_dir: Path, daily_budget: float = 8000):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = cache_dir / "usage_ledger.json"
        self.daily_budget = daily_budget
        self.session = requests.Session()

    def _charge(self, cost: float) -> None:
        ledger = json.loads(self.ledger_path.read_text()) if self.ledger_path.exists() else {"requests": []}
        now = pd.Timestamp.now(tz="UTC")
        entries = [(pd.Timestamp(entry["at"]), entry["weighted_calls"]) for entry in ledger["requests"]]
        daily = sum(value for stamp, value in entries if stamp.date() == now.date())
        hourly = sum(value for stamp, value in entries if stamp > now - pd.Timedelta(hours=1))
        minute = sum(value for stamp, value in entries if stamp > now - pd.Timedelta(minutes=1))
        if daily + cost > self.daily_budget or hourly + cost > 4500:
            raise WeatherBudgetExceeded(f"Resume later: estimated calls today={daily:.1f}, last hour={hourly:.1f}, last minute={minute:.1f}; next={cost:.1f}")
        if cost > 500:
            raise WeatherBudgetExceeded("Request exceeds the conservative per-minute budget; use shorter date batches")
        if minute + cost > 500:
            active = sorted((stamp, value) for stamp, value in entries if stamp > now - pd.Timedelta(minutes=1))
            delay = min(30, max(1, math.ceil((active[0][0] + pd.Timedelta(seconds=61) - now).total_seconds())))
            print(f"Weather: throttling for {delay}s to respect the minute quota", flush=True)
            time.sleep(delay)
            return self._charge(cost)
        ledger["requests"].append({"at": utc_now(), "weighted_calls": cost})
        ledger["note"] = "Conservative local estimates, including retries. Other clients may also consume the shared quota."
        write_json(self.ledger_path, ledger)

    def fetch(self, cell: dict, start: str, end: str, live: bool = False, cache_only: bool = False) -> dict:
        params = {"latitude": float(cell["lat"]), "longitude": float(cell["lon"]),
                  "hourly": ",".join(WEATHER_MAP), "timezone": "GMT", "models": "icon_global",
                  "temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm",
                  "start_date": start, "end_date": end}
        endpoint = LIVE_API if live else HISTORICAL_API
        signature = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True)
        key = hashlib.sha256(signature.encode()).hexdigest()[:20]
        path = self.cache_dir / f"{cell['cell_id']}_{start}_{end}_{key}.json"
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached["request"] != {"endpoint": endpoint, "params": params}:
                raise ValueError("Weather cache metadata differs from requested location/time/model")
            return cached
        if cache_only:
            raise FileNotFoundError(f"Weather response not cached: {path.name}")
        days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
        cost = max(1, len(WEATHER_MAP) / 10) * max(1, days / 14)
        for attempt in range(4):
            self._charge(cost)
            try:
                response = self.session.get(endpoint, params=params, timeout=(15, 90))
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 429:
                raise WeatherBudgetExceeded("Open-Meteo returned 429; cached work is retained. Resume after the provider's quota resets.")
            if response.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise ValueError(f"Open-Meteo error: {payload.get('reason')}")
            if payload.get("utc_offset_seconds") != 0:
                raise ValueError("Open-Meteo did not return UTC")
            if not set(WEATHER_MAP).issubset(payload.get("hourly", {})):
                raise ValueError("Open-Meteo omitted a contracted variable; no soil-depth substitutions are allowed")
            cached = {"retrieved_at": utc_now(), "cell_id": cell["cell_id"],
                      "request": {"endpoint": endpoint, "params": params}, "response": payload}
            write_json(path, cached)
            return cached
        raise RuntimeError("Weather request did not complete")


def parse_response(cached: dict, cell: dict) -> tuple[pd.DataFrame, dict]:
    payload = cached["response"]
    frame = pd.DataFrame(payload["hourly"]).rename(columns={"time": "ts", **WEATHER_MAP})
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True, errors="raise")
    if frame["ts"].duplicated().any() or not frame["ts"].is_monotonic_increasing:
        raise ValueError("Duplicate or unordered weather timestamps")
    expected_units = {"temperature_2m": "°C", "precipitation": "mm", "wind_speed_10m": "km/h",
                      "wind_direction_10m": "°", "vapour_pressure_deficit": "kPa",
                      "soil_temperature_0cm": "°C", "soil_temperature_18cm": "°C",
                      "evapotranspiration": "mm", "et0_fao_evapotranspiration": "mm"}
    expected_units.update({name: "m³/m³" for name in WEATHER_MAP if name.startswith("soil_moisture")})
    for source, canonical in WEATHER_MAP.items():
        if payload.get("hourly_units", {}).get(source) != expected_units[source]:
            raise ValueError(f"Unexpected unit for {source}: {payload.get('hourly_units', {}).get(source)}")
        frame[canonical] = pd.to_numeric(frame[canonical], errors="raise").astype("float64")
        values = frame[canonical].dropna()
        if np.isinf(values).any() or (values == -999).any():
            raise ValueError(f"Invalid values in {canonical}")
        if canonical.startswith("sm_") and not values.between(0, 1).all():
            raise ValueError(f"Out-of-range soil moisture in {canonical}")
        if canonical in {"precip_mm", "wind_kmh", "vpd_kpa", "et_mm", "et0_mm"} and (values < 0).any():
            raise ValueError(f"Negative values in {canonical}")
        if canonical == "wind_dir_deg" and not values.between(0, 360).all():
            raise ValueError("Wind direction outside 0..360 degrees")
    frame["cell_id"], frame["lat"], frame["lon"] = cell["cell_id"], float(cell["lat"]), float(cell["lon"])
    frame["weather_grid_lat"], frame["weather_grid_lon"] = payload["latitude"], payload["longitude"]
    report = {"cell_id": cell["cell_id"], "rows": len(frame), "first_hour": frame["ts"].min().isoformat(),
              "last_hour": frame["ts"].max().isoformat(),
              "missing_values": {k: int(frame[k].isna().sum()) for k in WEATHER_MAP.values()},
              "constant_columns": [k for k in WEATHER_MAP.values() if frame[k].nunique() <= 1],
              "all_null_weather_hours": int(frame[list(WEATHER_MAP.values())].isna().all(axis=1).sum()),
              "hourly_gap_count": int((frame["ts"].diff().dropna() != pd.Timedelta(hours=1)).sum()),
              "weather_grid_lat": payload["latitude"], "weather_grid_lon": payload["longitude"]}
    return frame, report


def download_weather(output_dir: Path, start: str, end: str, sample: bool, budget: float, cache_only: bool = False) -> dict:
    cells = pd.read_parquet(output_dir / "cells.parquet")
    if sample:
        cells = cells.groupby("province", sort=True).nth(0).reset_index(drop=True)
    client = WeatherClient(output_dir / "cache/weather", budget)
    reports = []
    warmup = (pd.Timestamp(start) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    # Do not request a whole current/future day from the historical archive.
    today = pd.Timestamp.now(tz="UTC").normalize()
    config = json.loads((ROOT / "a_data/processing_config.json").read_text(encoding="utf-8"))
    history_end = min(pd.Timestamp(end, tz="UTC"), today - pd.Timedelta(days=1),
                      pd.Timestamp(config["weather_historical_end_date"], tz="UTC")).strftime("%Y-%m-%d")
    status, error = "complete", None
    name = "weather_sample" if sample else "weather_history"
    target = output_dir / f"{name}.parquet"
    temporary = target.with_suffix(".parquet.tmp")
    writer = None
    try:
        for cell in cells.to_dict("records"):
            try:
                cached = client.fetch(cell, warmup, history_end, cache_only=cache_only)
                frame, report = parse_response(cached, cell)
            except (WeatherBudgetExceeded, requests.RequestException, FileNotFoundError) as exc:
                status, error = "incomplete_resumable", str(exc)
                break
            reports.append(report)
            frame["ts"] = frame["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            write_parquet(frame, output_dir / "cache/normalized_weather" / f"{cell['cell_id']}.parquet")
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temporary, table.schema, compression="zstd")
            writer.write_table(table)
            write_json(output_dir / f"{name}_progress.json", {"updated_at": utc_now(), "status": "running",
                       "completed_cells": len(reports), "requested_cells": len(cells), "last_cell_id": cell["cell_id"]})
            print(f"Weather: {cell['cell_id']} {len(frame):,} hours; {len(reports)}/{len(cells)} cells", flush=True)
    finally:
        if writer is not None:
            writer.close()
    if reports:
        temporary.replace(target)
    report = {"generated_at": utc_now(), "is_mock": False, "status": status, "error": error,
              "requested_start_date": start, "requested_end_date": end, "weather_start_with_warmup": warmup,
              "historical_end_date": history_end, "model": "icon_global", "requested_cells": len(cells),
              "completed_cells": len(reports), "cells": reports,
              "provenance": "Open-Meteo Historical Forecast / DWD ICON, modeled hourly data; CC BY 4.0",
              "source_url": "https://open-meteo.com/en/docs/historical-forecast-api"}
    write_json(output_dir / f"{name}_report.json", report)
    write_json(output_dir / f"{name}_progress.json", {"updated_at": utc_now(), "status": status,
               "completed_cells": len(reports), "requested_cells": len(cells), "error": error})
    print(json.dumps({k: report[k] for k in ("status", "completed_cells", "requested_cells", "error")}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    parser.add_argument("--start-date", default="2024-12-02")
    parser.add_argument("--end-date", default="2026-10-17")
    parser.add_argument("--sample", action="store_true", help="One real qualifying cell per province")
    parser.add_argument("--daily-budget", type=float, default=8000)
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    report = download_weather(args.output_dir, args.start_date, args.end_date, args.sample, args.daily_budget, args.cache_only)
    if report["status"] != "complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
