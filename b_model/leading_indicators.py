"""Causal, Role B internal predictors; shared feature JSON stays schema 1.0."""

import numpy as np
import pandas as pd

from b_model.config import FEATURE_COLUMNS

ENGINEERED_FEATURES = ["cumulative_dry_days", "soil_moisture_momentum"]
ENSEMBLE_FEATURES = [*FEATURE_COLUMNS, *ENGINEERED_FEATURES]
PIPELINE_VERSION = "leading_indicators_v1"
SOURCE_COLUMNS = ["cell_id", "ts", "precip_mm", "sm_27_81"]


def add_leading_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Use only measurements at or before each row, separately for each cell.

    Dry days count consecutive *complete UTC days* with total rain <1 mm.
    A day completes at 23:00; intraday rows use the previous completed day.
    Missing hours make a day unknown and break the observed streak. Streaks
    start at the beginning of available history, so are lower bounds there.
    Momentum is current deep moisture minus the preceding 72 hourly values'
    mean, excluding the current hour. A missing hour/value makes it unknown.
    """
    result = frame.copy()
    result["_indicator_time"] = pd.to_datetime(result["ts"], utc=True, errors="raise")
    if result["_indicator_time"].isna().any():
        raise ValueError("Indicator timestamps must not be missing")
    if result.duplicated(["cell_id", "_indicator_time"]).any():
        raise ValueError("Duplicate cell/hour in indicator history")
    if not result["_indicator_time"].eq(result["_indicator_time"].dt.floor("h")).all():
        raise ValueError("Leading indicators require hourly timestamps")
    result[ENGINEERED_FEATURES] = np.nan
    for _, group in result.groupby("cell_id", sort=False):
        group = group.sort_values("_indicator_time")
        times = pd.DatetimeIndex(group["_indicator_time"])
        hourly = group.set_index("_indicator_time")[["precip_mm", "sm_27_81"]].astype(float)
        if np.isinf(hourly.to_numpy()).any() or (hourly.to_numpy() == -999).any():
            raise ValueError("Indicator measurements must be finite or null, not sentinels")
        hourly = hourly.reindex(pd.date_range(times.min(), times.max(), freq="h"))
        soil = hourly["sm_27_81"]
        momentum = soil - soil.shift(1).rolling(72, min_periods=72).mean()
        rain = hourly["precip_mm"].resample("D").sum(min_count=24)
        streak = []
        count = 0
        for value in rain:
            if pd.isna(value):
                streak.append(np.nan)
                count = 0
            else:
                count = count + 1 if value < 1.0 else 0
                streak.append(float(count))
        daily = pd.Series(streak, index=rain.index)
        complete_day = times.floor("D") - pd.to_timedelta((times.hour != 23).astype(int), unit="D")
        result.loc[group.index, "cumulative_dry_days"] = daily.reindex(complete_day).to_numpy()
        result.loc[group.index, "soil_moisture_momentum"] = momentum.reindex(times).to_numpy()
    return result.drop(columns="_indicator_time")


def add_snapshot_indicators(snapshots: pd.DataFrame, history_path) -> pd.DataFrame:
    """Use predictor-only history strictly before each snapshot, never targets."""
    if history_path is None:
        raise ValueError("Leading-indicator artifacts require paths.history for rolling context")
    history = pd.read_parquet(history_path, columns=SOURCE_COLUMNS)
    history["ts"] = pd.to_datetime(history["ts"], utc=True, errors="raise")
    current = snapshots[SOURCE_COLUMNS].copy()
    current["ts"] = pd.to_datetime(current["ts"], utc=True, errors="raise")
    cutoffs = current.set_index("cell_id")["ts"]
    history = history[history["ts"] < history["cell_id"].map(cutoffs)]
    if history.duplicated(["cell_id", "ts"]).any():
        raise ValueError("Duplicate cell/hour in inference history")
    combined = pd.concat([history, current], ignore_index=True)
    engineered = add_leading_indicators(combined).iloc[-len(current):]
    output = snapshots.copy()
    output[ENGINEERED_FEATURES] = engineered[ENGINEERED_FEATURES].to_numpy()
    return output


def cold_start_sample_weights(frame: pd.DataFrame, labels, multiplier=5.0):
    """Train-only inverse frequency; unknown hotspot history is not 'quiet'."""
    labels = np.asarray(labels)
    if not np.isin(labels, [0, 1]).all() or len(labels) != len(frame):
        raise ValueError("Sample weights need aligned binary targets")
    positive = labels == 1
    n_positive = int(positive.sum())
    n_negative = int((~positive).sum())
    if not n_positive or not n_negative:
        raise ValueError("Sample weights require both target classes")
    base = n_negative / n_positive
    weights = np.where(positive, base, 1.0)
    quiet_positive = positive & frame["hotspots_in_cell_24h"].eq(0).fillna(False).to_numpy(dtype=bool)
    weights[quiet_positive] *= multiplier
    return weights, {"base_positive_weight": base, "cold_start_multiplier": multiplier,
                     "cold_start_positive_rows": int(quiet_positive.sum()),
                     "positive_rows": n_positive, "negative_rows": n_negative}
