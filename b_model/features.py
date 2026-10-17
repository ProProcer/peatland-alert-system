"""
Feature extraction, flattening, and preprocessing for Role B (ML Lead).
Strictly adheres to Contract 3.1 (/data/processed/features.json).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from b_model.config import (
    DEFAULT_FEATURES_PATH,
    DEFAULT_HISTORY_PATH,
    FEATURE_COLUMNS,
    FEATURE_GROUPS,
    SCHEMA_VERSION,
    setup_logger,
)

logger = setup_logger("b_model.features")


def flatten_feature_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flattens a single nested JSON record adhering to Contract 3.1 into a flat dictionary.
    Excludes non-numeric list attributes like 'polygon_ids'.
    Converts nulls to np.nan.

    Args:
        record: Dictionary conforming to Contract 3.1

    Returns:
        Flat dictionary with cell metadata and feature columns
    """
    flat: Dict[str, Any] = {
        "schema_version": record.get("schema_version", SCHEMA_VERSION),
        "cell_id": str(record["cell_id"]),
        "ts": str(record["ts"]),
        "lat": float(record["lat"]) if record.get("lat") is not None else np.nan,
        "lon": float(record["lon"]) if record.get("lon") is not None else np.nan,
    }

    # Extract all nested sub-objects: peat, weather, derived, fire
    for group in ["peat", "weather", "derived", "fire"]:
        group_data = record.get(group) or {}
        for key, val in group_data.items():
            if key == "polygon_ids":
                # polygon_ids is a metadata list, not a numerical ML feature
                continue
            flat[key] = np.nan if val is None else val

    return flat


def flatten_features_json(
    json_path: Path = DEFAULT_FEATURES_PATH,
    latest_only: bool = True
) -> pd.DataFrame:
    """
    Reads nested Contract 3.1 JSON and returns a validated DataFrame with exact FEATURE_COLUMNS order.
    Deduplicates multi-hour inputs by keeping only the latest timestamp per cell_id when latest_only=True.

    Args:
        json_path: Path to features.json
        latest_only: If True, keeps only the latest hourly record per cell_id

    Returns:
        pd.DataFrame containing metadata + all FEATURE_COLUMNS in exact canonical order
    """
    if not json_path.exists() or json_path.stat().st_size == 0:
        logger.warning("Features file %s missing or empty; generating mock features.", json_path)
        generate_mock_data_if_missing(features_path=json_path)

    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    if isinstance(raw_data, dict):
        raw_list = [raw_data]
    elif isinstance(raw_data, list):
        raw_list = raw_data
    else:
        raise ValueError(f"Unexpected JSON root type in {json_path}: {type(raw_data)}")

    flattened = [flatten_feature_record(rec) for rec in raw_list]
    df = pd.DataFrame(flattened)

    if df.empty:
        return df

    # Deduplicate multi-hour inputs: keep latest timestamp per cell_id
    if latest_only and "cell_id" in df.columns and "ts" in df.columns:
        df = df.sort_values("ts").groupby("cell_id", as_index=False).last()

    # Ensure all canonical feature columns exist in exact order
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Order columns: metadata first, then exact FEATURE_COLUMNS order
    metadata_cols = [c for c in ["schema_version", "cell_id", "ts", "lat", "lon"] if c in df.columns]
    ordered_cols = metadata_cols + [c for c in FEATURE_COLUMNS if c not in metadata_cols]
    df = df[ordered_cols]

    logger.info("Loaded %d unique cell feature rows from %s", len(df), json_path)
    return df


def load_live_features(
    json_path: Path = DEFAULT_FEATURES_PATH,
    latest_only: bool = True
) -> pd.DataFrame:
    """Convenience alias for flatten_features_json."""
    return flatten_features_json(json_path, latest_only=latest_only)


def compute_dryness_index(df: pd.DataFrame) -> pd.Series:
    """
    Computes a rule-based peat dryness index scaled to [0.0, 1.0].
    Combines:
    1. Prolonged absence of rain (days_since_rain)
    2. Deep peat layer moisture depletion (sm_27_81)
    3. Atmospheric evaporative demand (vpd_mean_24h or vpd_kpa)

    Args:
        df: DataFrame containing at least days_since_rain, sm_27_81, and vpd_mean_24h

    Returns:
        pd.Series of dryness index in [0.0, 1.0]
    """
    # Rainless duration: saturated at 30 days
    days_rain = df.get("days_since_rain", pd.Series(0, index=df.index))
    days_dry = days_rain.fillna(0).clip(lower=0, upper=30) / 30.0

    # Deep soil moisture depletion: peat critical threshold typically < 0.25 m3/m3
    sm_deep = df.get("sm_27_81", pd.Series(0.35, index=df.index))
    deep_dryness = (1.0 - (sm_deep.fillna(0.30) / 0.50)).clip(lower=0.0, upper=1.0)

    # Atmospheric thirst: Vapor Pressure Deficit (VPD)
    vpd = df.get("vpd_mean_24h")
    if vpd is None or vpd.isna().all():
        vpd = df.get("vpd_kpa", pd.Series(1.5, index=df.index))
    vpd_norm = (vpd.fillna(1.5) / 3.5).clip(lower=0.0, upper=1.0)

    # Weighted blend: high weight on deep moisture and days without rain
    dryness = 0.40 * days_dry + 0.40 * deep_dryness + 0.20 * vpd_norm
    return dryness.clip(lower=0.0, upper=1.0)


def generate_mock_data_if_missing(
    history_path: Path = DEFAULT_HISTORY_PATH,
    features_path: Path = DEFAULT_FEATURES_PATH,
    num_cells: int = 9,
    days_history: int = 30,
    force: bool = False,
) -> None:
    """
    Generates mock training history (history.parquet) and live features (features.json)
    strictly conforming to Contracts 3.1 if files are missing or if force=True.
    Incorporates realistic peat fire physical dynamics with zero current-hour target leakage.
    Ensures 30-day (720-hour) history with distinct weather regimes and a clean validation drying precursor.
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)
    features_path.parent.mkdir(parents=True, exist_ok=True)

    cell_coords = [
        (-2.35, 114.05), (-2.35, 114.15), (-2.35, 114.25),
        (-2.45, 114.05), (-2.45, 114.15), (-2.45, 114.25),
        (-2.55, 114.05), (-2.55, 114.15), (-2.55, 114.25),
    ][:num_cells]

    # 1. Generate live features.json
    if force or not features_path.exists() or features_path.stat().st_size == 0:
        logger.info("Generating realistic mock features for Contract 3.1 -> %s", features_path)
        features_list = []
        base_ts = "2026-10-17T09:00:00Z"

        for idx, (lat, lon) in enumerate(cell_coords):
            cell_id = f"{lat:.2f}_{lon:.2f}"
            # Distribution of conditions across demo cells:
            # cell 0: extreme dry spell (CRITICAL risk)
            # cell 1: elevated drought (HIGH risk)
            # cell 2-3: moderate dry conditions (MODERATE risk)
            # cell 4-8: normal / wet baseline (LOW risk)
            if idx == 0:
                is_crit, is_high, is_mod = True, False, False
            elif idx == 1:
                is_crit, is_high, is_mod = False, True, False
            elif idx in (2, 3):
                is_crit, is_high, is_mod = False, False, True
            else:
                is_crit, is_high, is_mod = False, False, False

            days_rain = 22 if is_crit else (14 if is_high else (6 if is_mod else 0))
            sm_deep = 0.14 if is_crit else (0.20 if is_high else (0.28 if is_mod else 0.44))
            sm_surf = 0.10 if is_crit else (0.15 if is_high else (0.24 if is_mod else 0.40))
            vpd_val = 3.6 if is_crit else (2.6 if is_high else (1.6 if is_mod else 0.7))
            temp_val = 36.0 if is_crit else (33.5 if is_high else (31.0 if is_mod else 26.5))
            hotspots = 2 if is_crit else (1 if is_high else 0)
            dist_km = 2.5 if is_crit else (7.0 if is_high else (18.0 if is_mod else 45.0))
            precip = 0.0 if (is_crit or is_high or is_mod) else 8.5
            rain_24 = 0.0 if (is_crit or is_high or is_mod) else 16.0

            record = {
                "schema_version": SCHEMA_VERSION,
                "cell_id": cell_id,
                "ts": base_ts,
                "lat": lat,
                "lon": lon,
                "peat": {
                    "peat_fraction": round(0.55 + 0.05 * (idx % 5), 2),
                    "peat_area_km2": round(6.5 + 0.3 * (idx % 5), 1),
                    "polygon_ids": [f"{{DF27C432-B0{idx:02d}-4A61-A123-8899AABBCCDD}}"],
                },
                "weather": {
                    "temp_c": temp_val,
                    "precip_mm": precip,
                    "wind_kmh": round(12.0 + idx * 0.5, 1),
                    "wind_dir_deg": 120 + idx * 10,
                    "sm_0_1": sm_surf,
                    "sm_1_3": round(sm_surf + 0.01, 2),
                    "sm_3_9": round(sm_surf + 0.02, 2),
                    "sm_9_27": round(sm_deep - 0.02, 2),
                    "sm_27_81": sm_deep,
                    "vpd_kpa": vpd_val,
                    "soil_temp_0_c": round(temp_val + 2.5, 1),
                    "soil_temp_18_c": round(temp_val - 1.0, 1),
                    "et_mm": 0.4 if (is_crit or is_high) else 0.2,
                    "et0_mm": 0.5 if (is_crit or is_high) else 0.3,
                },
                "derived": {
                    "rain_24h_mm": rain_24,
                    "rain_7d_mm": 0.0 if (is_crit or is_high) else (6.0 if is_mod else 48.0),
                    "rain_30d_mm": 12.0 if (is_crit or is_high) else (45.0 if is_mod else 145.0),
                    "days_since_rain": days_rain,
                    "sm_27_81_delta_7d": -0.06 if is_crit else (-0.03 if is_high else 0.02),
                    "vpd_mean_24h": vpd_val,
                    "soil_air_temp_gap_c": round(-1.5 + (idx * 0.2), 1),
                },
                "fire": {
                    "hotspots_in_cell_24h": hotspots,
                    "hotspots_10km_7d": hotspots * 2,
                    "frp_sum_10km_7d": round(hotspots * 18.5, 1),
                    "nearest_hotspot_km": dist_km,
                },
            }
            features_list.append(record)

        with open(features_path, "w", encoding="utf-8") as f:
            json.dump(features_list, f, indent=2)
        logger.info("Wrote %d mock features to %s", len(features_list), features_path)

    # 2. Generate history.parquet (30 days = 720 hours)
    if force or not history_path.exists() or history_path.stat().st_size == 0:
        logger.info("Generating realistic 30-day mock history table -> %s", history_path)
        timestamps = pd.date_range("2025-08-01 00:00:00", periods=days_history * 24, freq="1h", tz="UTC")
        rows = []
        rng = np.random.RandomState(42)

        for c_idx, (lat, lon) in enumerate(cell_coords):
            cell_id = f"{lat:.2f}_{lon:.2f}"
            peat_frac = round(0.55 + 0.05 * (c_idx % 5), 2)
            peat_area = round(6.5 + 0.3 * (c_idx % 5), 1)

            for t_idx, ts in enumerate(timestamps):
                # Regimes across 720 hours:
                # 0-140h: Regime 1 (Train): drying, fire at 130-142 for c_idx % 2 == 0, wet recovery 142-220h
                # 220-450h: Regime 2 (Train+Calib): drying, fire at 420-432 for c_idx % 3 != 1, recovery 432-540h
                # 540-720h: Regime 3 (Validation):
                #   540-570h (30h): wet baseline
                #   570-675h (105h): clean gradual multi-day drying precursor
                #   675-692h (17h): brief fire emergence in validation for selected cells
                #   692-720h (28h): rain recovery
                if t_idx < 140:
                    dry_prog = max(0.0, (t_idx - 40) / 90.0)
                    fire_active = (130 <= t_idx <= 142) and (c_idx % 2 == 0)
                elif t_idx < 220:
                    dry_prog = 0.0
                    fire_active = False
                elif t_idx < 440:
                    dry_prog = max(0.0, (t_idx - 320) / 100.0)
                    fire_active = (420 <= t_idx <= 432) and (c_idx in (1, 3, 4, 5, 7))
                elif t_idx < 570:
                    dry_prog = 0.0
                    fire_active = False
                elif t_idx < 675:
                    # Validation clean gradual multi-day drying precursor (105 hours)
                    dry_prog = max(0.0, (t_idx - 570) / 105.0)
                    fire_active = False
                elif t_idx < 692:
                    # Hotspot emergence at end of validation dry spell
                    dry_prog = 1.0
                    fire_active = (c_idx in (0, 1, 2, 4, 6))
                else:
                    dry_prog = 0.0
                    fire_active = False

                cell_dry = float(np.clip(dry_prog + (c_idx % 3 - 1) * 0.04, 0.0, 1.0))
                days_rain = int(cell_dry * 24)
                precip = 0.0 if cell_dry > 0.05 else float(rng.exponential(2.0))
                rain_24 = 0.0 if cell_dry > 0.05 else float(rng.uniform(10.0, 30.0))
                rain_7d = max(0.0, (1.0 - cell_dry) * 60.0)
                rain_30d = max(10.0, (1.0 - cell_dry) * 140.0 + 20.0)

                sm_deep = float(np.clip(0.44 - cell_dry * 0.30 + rng.normal(0, 0.01), 0.12, 0.52))
                sm_surf = float(np.clip(sm_deep - 0.05 + precip * 0.03, 0.08, 0.48))
                vpd = float(np.clip(0.8 + cell_dry * 2.8 + rng.normal(0, 0.04), 0.5, 4.0))
                temp = float(np.clip(26.0 + cell_dry * 9.5 + rng.normal(0, 0.3), 24.0, 39.0))
                soil_temp = float(temp + 2.5 + cell_dry * 2.5)
                sm_delta = float(np.clip(0.02 - cell_dry * 0.10, -0.09, 0.04))

                has_hotspot = 1 if fire_active else 0
                hotspots_10k = has_hotspot * 2 if has_hotspot else (1 if cell_dry > 0.85 else 0)
                frp_sum = float(hotspots_10k * 22.0)
                dist_km = float(2.0 if has_hotspot else (8.0 if hotspots_10k else 45.0))

                row = {
                    "cell_id": cell_id,
                    "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "lat": lat,
                    "lon": lon,
                    "peat_fraction": peat_frac,
                    "peat_area_km2": peat_area,
                    "temp_c": temp,
                    "precip_mm": precip,
                    "wind_kmh": float(10.0 + cell_dry * 5.0 + rng.uniform(0, 3)),
                    "wind_dir_deg": float(rng.uniform(110.0, 170.0)),
                    "sm_0_1": sm_surf,
                    "sm_1_3": float(np.clip(sm_surf + 0.01, 0.08, 0.5)),
                    "sm_3_9": float(np.clip(sm_surf + 0.02, 0.08, 0.5)),
                    "sm_9_27": float(np.clip(sm_deep - 0.02, 0.08, 0.5)),
                    "sm_27_81": sm_deep,
                    "vpd_kpa": vpd,
                    "soil_temp_0_c": soil_temp,
                    "soil_temp_18_c": float(temp - 1.0),
                    "et_mm": float(0.2 + cell_dry * 0.3),
                    "et0_mm": float(0.3 + cell_dry * 0.3),
                    "rain_24h_mm": rain_24,
                    "rain_7d_mm": rain_7d,
                    "rain_30d_mm": rain_30d,
                    "days_since_rain": days_rain,
                    "sm_27_81_delta_7d": sm_delta,
                    "vpd_mean_24h": vpd,
                    "soil_air_temp_gap_c": float(-1.2 + rng.normal(0, 0.2)),
                    "hotspots_in_cell_24h": has_hotspot,
                    "hotspots_10km_7d": hotspots_10k,
                    "frp_sum_10km_7d": frp_sum,
                    "nearest_hotspot_km": dist_km,
                }
                rows.append(row)

        df_hist = pd.DataFrame(rows)
        df_hist = df_hist.sort_values(["cell_id", "ts"]).reset_index(drop=True)

        # Forward-looking target labeling with .shift(-1) to eliminate current-hour target leakage
        for h, target_col in [(24, "target_24h"), (48, "target_48h"), (72, "target_72h")]:
            indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=h)
            df_hist[target_col] = (
                df_hist.groupby("cell_id")["hotspots_in_cell_24h"]
                .transform(lambda s: (s.shift(-1).fillna(0).rolling(indexer, min_periods=1).max() > 0).astype(int))
            )

        df_hist.to_parquet(history_path, index=False)
        logger.info("Saved %d historical rows with non-leaking targets to %s", len(df_hist), history_path)


if __name__ == "__main__":
    generate_mock_data_if_missing(force=True)
    features_df = flatten_features_json()
    print(f"Loaded features shape: {features_df.shape}")
    print(f"Columns: {features_df.columns.tolist()}")