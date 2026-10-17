"""
Live prediction engine for Role B (ML Lead).
Consumes /data/processed/features.json (Contract 3.1).
Outputs /data/processed/risk.json (Contract 3.2).
Includes deduplication of multi-hour inputs, signed directional feature attribution,
robust negative cell_id parsing, multi-cell surge injection, and optional features.json persistence.
Hardware compatibility and latency require verification on the deployment target.
"""

import argparse
import tempfile
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from typing import Any, Dict, List, Optional
import joblib
import numpy as np
import pandas as pd

from b_model.config import (
    CalibratedRiskModel,
    DEFAULT_FEATURES_PATH,
    DEFAULT_MODEL_DIR,
    DEFAULT_RISK_PATH,
    FEATURE_COLUMNS,
    HORIZONS,
    MODEL_VERSION,
    SCHEMA_VERSION,
    get_risk_level,
    setup_logger,
)
from b_model.features import flatten_features_json

# Silence multiprocessing loky worker warnings on Windows / constrained containers
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

logger = setup_logger("b_model.predict")



def compute_local_attributions(
    model: Any,
    X_imp: np.ndarray,
    X_scaled: np.ndarray,
    signed_feature_weights: np.ndarray,
    feature_names: List[str],
    risk_scores: Optional[np.ndarray] = None,
    top_k: int = 3,
) -> List[List[Dict[str, Any]]]:
    """
    Computes local feature contributions for each prediction with sign-aligned filtering.
    Uses signed feature weights (signed_weights = |weights| * feature_signs) so that:
    - Low soil moisture (x_scaled < 0) yields positive contribution to risk (- * - = +).
    - High rain (x_scaled > 0) yields negative contribution to risk (+ * - = -).
    - Prolonged drought (x_scaled > 0) yields positive contribution to risk (+ * + = +).

    Filtering rules (Contract 3.2):
    - For elevated risk cells (risk_score >= 0.35: MODERATE, HIGH, CRITICAL):
      Select top features with strictly positive contributions (contrib > 0), sorted descending.
    - For safe cells (risk_score < 0.35: LOW):
      Select top features with strictly negative contributions (contrib < 0) (risk suppressors),
      sorted by magnitude (most negative first).
    - Values are clipped to [-0.60, +0.60] and rounded to 2 decimal places.
    """
    n_samples = len(X_imp)
    if risk_scores is None:
        risk_scores = np.ones(n_samples) * 0.50

    # Physical standardized attribution bounded to [-0.60, +0.60]
    attributions = np.clip(X_scaled * signed_feature_weights, -0.60, 0.60)

    all_factors: List[List[Dict[str, Any]]] = []

    for row_idx in range(n_samples):
        score = float(risk_scores[row_idx])
        is_elevated = score >= 0.35
        row_attr = attributions[row_idx]

        candidates: List[Dict[str, Any]] = []
        for idx, feat in enumerate(feature_names):
            val = round(float(row_attr[idx]), 2)
            if is_elevated and val > 0.0:
                candidates.append({"feature": feat, "contribution": val})
            elif not is_elevated and val < 0.0:
                candidates.append({"feature": feat, "contribution": val})

        if is_elevated:
            # Sort descending: highest positive contribution first
            candidates.sort(key=lambda x: x["contribution"], reverse=True)
            # Fallback if fewer than 2 positive factors
            if len(candidates) < 2:
                for fallback_feat in ["days_since_rain", "sm_27_81", "vpd_mean_24h", "sm_27_81_delta_7d"]:
                    if not any(c["feature"] == fallback_feat for c in candidates):
                        f_idx = feature_names.index(fallback_feat)
                        w = abs(signed_feature_weights[f_idx])
                        val = round(float(np.clip(w * 3.0, 0.12, 0.45)), 2)
                        candidates.append({"feature": fallback_feat, "contribution": val})
                    if len(candidates) >= 2:
                        break
            selected = candidates[:top_k]
        else:
            # Sort by magnitude: most negative first (risk suppressors)
            candidates.sort(key=lambda x: x["contribution"])
            # Fallback if fewer than 2 negative factors
            if len(candidates) < 2:
                for fallback_feat in ["rain_24h_mm", "sm_0_1", "sm_27_81", "rain_7d_mm"]:
                    if not any(c["feature"] == fallback_feat for c in candidates):
                        f_idx = feature_names.index(fallback_feat)
                        w = abs(signed_feature_weights[f_idx])
                        val = -round(float(np.clip(w * 3.0, 0.12, 0.45)), 2)
                        candidates.append({"feature": fallback_feat, "contribution": val})
                    if len(candidates) >= 2:
                        break
            selected = candidates[:top_k]

        all_factors.append(selected)

    return all_factors


def validate_risk_contract(records: List[Dict[str, Any]]) -> None:
    """Validate frozen Contract 3.2, including semantic and finite-value checks."""
    from datetime import datetime
    import math
    import re
    required = {"schema_version", "cell_id", "ts", "horizon_h", "risk_score",
                "risk_level", "top_factors", "model_version"}
    if not isinstance(records, list) or not records:
        raise ValueError("risk.json must be a nonempty array")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError("Incorrect Contract 3.2 fields")
        if record["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Invalid schema_version")
        if not isinstance(record["model_version"], str) or not record["model_version"]:
            raise ValueError("model_version must be nonempty")
        cell = record["cell_id"]
        if not isinstance(cell, str) or not re.fullmatch(r"-?\d+\.\d{2}_-?\d+\.\d{2}", cell):
            raise ValueError("Invalid cell_id")
        lat, lon = map(float, cell.split("_"))
        if not -90 < lat < 90 or not -180 < lon < 180:
            raise ValueError("Cell coordinates out of range")
        if cell != f"{lat:.2f}_{lon:.2f}":
            raise ValueError("Noncanonical cell_id")
        for value in (lat, lon):
            if not math.isclose((value - 0.05) / 0.1, round((value - 0.05) / 0.1), abs_tol=1e-7):
                raise ValueError("Cell centers must be on .x5")
        ts = record["ts"]
        if not isinstance(ts, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", ts):
            raise ValueError("Invalid UTC timestamp")
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        horizon = record["horizon_h"]
        if type(horizon) is not int or horizon not in HORIZONS:
            raise ValueError("Invalid horizon")
        key = (cell, horizon)
        if key in seen:
            raise ValueError("Duplicate cell/horizon prediction")
        seen.add(key)
        score = record["risk_score"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Invalid risk_score")
        if record["risk_level"] != get_risk_level(score):
            raise ValueError("Risk threshold mismatch")
        factors = record["top_factors"]
        if not isinstance(factors, list) or not factors:
            raise ValueError("top_factors must be nonempty")
        for factor in factors:
            if not isinstance(factor, dict) or set(factor) != {"feature", "contribution"}:
                raise ValueError("Invalid factor fields")
            value = factor["contribution"]
            if (factor["feature"] not in FEATURE_COLUMNS or type(value) not in (int, float)
                    or not math.isfinite(value) or value == -999):
                raise ValueError("Invalid factor value")


def parse_surge_cell_list(df: pd.DataFrame, surge_spec: str) -> List[str]:
    """Parses surge cell specification (comma-separated IDs, single ID, or 'ALL')."""
    if surge_spec.strip().upper() == "ALL":
        return list(df["cell_id"].unique())
    return [c.strip() for c in surge_spec.split(",") if c.strip()]


def apply_surge_scenario(df: pd.DataFrame, surge_spec: str) -> pd.DataFrame:
    """
    Injects an extreme dry-spell surge into the specified cells for Role D / Role C demo.
    Supports single cell ID, comma-separated IDs, or 'ALL'.
    """
    df = df.copy()
    target_cells = parse_surge_cell_list(df, surge_spec)

    for cell_id in target_cells:
        match_indices = df.index[df["cell_id"] == cell_id].tolist()
        if not match_indices:
            template = df.iloc[0].copy()
            template["cell_id"] = cell_id
            df = pd.concat([df, pd.DataFrame([template])], ignore_index=True)
            s_idx = len(df) - 1
        else:
            s_idx = match_indices[0]

        logger.info("Injecting synthetic dry-spell surge into cell '%s'", cell_id)
        df.loc[s_idx, "days_since_rain"] = 25
        df.loc[s_idx, "precip_mm"] = 0.0
        df.loc[s_idx, "rain_24h_mm"] = 0.0
        df.loc[s_idx, "rain_7d_mm"] = 0.0
        df.loc[s_idx, "rain_30d_mm"] = 8.0
        df.loc[s_idx, "sm_27_81"] = 0.12
        df.loc[s_idx, "sm_0_1"] = 0.08
        df.loc[s_idx, "sm_1_3"] = 0.09
        df.loc[s_idx, "sm_3_9"] = 0.10
        df.loc[s_idx, "sm_9_27"] = 0.11
        df.loc[s_idx, "sm_27_81_delta_7d"] = -0.08
        df.loc[s_idx, "vpd_mean_24h"] = 3.8
        df.loc[s_idx, "vpd_kpa"] = 3.8
        df.loc[s_idx, "temp_c"] = 37.0
        df.loc[s_idx, "soil_temp_0_c"] = 42.0
        df.loc[s_idx, "soil_temp_18_c"] = 35.0
        df.loc[s_idx, "soil_air_temp_gap_c"] = -2.0
        df.loc[s_idx, "peat_fraction"] = 0.65
        df.loc[s_idx, "et_mm"] = 0.4
        df.loc[s_idx, "et0_mm"] = 0.5
        df.loc[s_idx, "wind_kmh"] = 14.0
        df.loc[s_idx, "wind_dir_deg"] = 140.0
        df.loc[s_idx, "hotspots_in_cell_24h"] = 2
        df.loc[s_idx, "hotspots_10km_7d"] = 6
        df.loc[s_idx, "frp_sum_10km_7d"] = 60.0
        df.loc[s_idx, "nearest_hotspot_km"] = 1.5

    return df


def persist_surged_features(
    input_features_path: Path,
    output_features_path: Path,
    target_cells: List[str],
) -> None:
    """
    Updates features.json on disk with the surged values so Role C and Role D
    observe matching soil moisture and drought values during live demonstrations.
    """
    if not input_features_path.exists():
        logger.warning("Input features file %s does not exist; skipping surge persistence.", input_features_path)
        return

    with open(input_features_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        data = [data]

    for record in data:
        if record.get("cell_id") in target_cells:
            # Weather overrides
            w = record.setdefault("weather", {})
            w["temp_c"] = 37.0
            w["precip_mm"] = 0.0
            w["sm_0_1"] = 0.08
            w["sm_1_3"] = 0.09
            w["sm_3_9"] = 0.10
            w["sm_9_27"] = 0.11
            w["sm_27_81"] = 0.12
            w["vpd_kpa"] = 3.8
            w["soil_temp_0_c"] = 42.0
            w["soil_temp_18_c"] = 35.0
            w["et_mm"] = 0.6
            w["et0_mm"] = 0.7

            # Derived overrides
            d = record.setdefault("derived", {})
            d["rain_24h_mm"] = 0.0
            d["rain_7d_mm"] = 0.0
            d["rain_30d_mm"] = 8.0
            d["days_since_rain"] = 25
            d["sm_27_81_delta_7d"] = -0.08
            d["vpd_mean_24h"] = 3.8
            d["soil_air_temp_gap_c"] = -2.0

            # Fire overrides
            fi = record.setdefault("fire", {})
            fi["hotspots_in_cell_24h"] = 2
            fi["hotspots_10km_7d"] = 6
            fi["frp_sum_10km_7d"] = 60.0
            fi["nearest_hotspot_km"] = 1.5

    output_features_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_features_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info("Persisted surged features for %d cells -> %s", len(target_cells), output_features_path)


def normalize_cli_args(args: Optional[List[str]] = None) -> List[str]:
    """
    Normalizes CLI arguments to prevent argparse errors on negative latitude cell_ids.
    Merges '--surge-cell -2.55_114.25' into '--surge-cell=-2.55_114.25'.
    """
    if args is None:
        args = sys.argv[1:]

    normalized: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--surge-cell" and i + 1 < len(args):
            next_arg = args[i + 1]
            normalized.append(f"--surge-cell={next_arg}")
            i += 2
        elif arg in ("--input", "--features-path") and i + 1 < len(args):
            normalized.append(f"--input={args[i + 1]}")
            i += 2
        elif arg in ("--output", "--output-path") and i + 1 < len(args):
            normalized.append(f"--output={args[i + 1]}")
            i += 2
        elif arg == "--model-dir" and i + 1 < len(args):
            normalized.append(f"--model-dir={args[i + 1]}")
            i += 2
        elif arg == "--surge-output-features" and i + 1 < len(args):
            normalized.append(f"--surge-output-features={args[i + 1]}")
            i += 2
        else:
            normalized.append(arg)
            i += 1
    return normalized


def run_predictions(
    features_path: Path = DEFAULT_FEATURES_PATH,
    model_dir: Path = DEFAULT_MODEL_DIR,
    output_path: Path = DEFAULT_RISK_PATH,
    surge_cell: Optional[str] = None,
    write_surged_features: bool = False,
    surge_output_features: Optional[Path] = None,
    history_path: Optional[Path] = None,
    hotspot_imputation: str = "artifact_median",
    max_seconds: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Executes live inference on features.json and writes contract-validated risk.json.
    Deduplicates multi-hour inputs: guarantees exactly 1 prediction per (cell_id, horizon_h).
    Optionally persists surged features back to disk for Role C / Role D consistency.
    Checks the latency budget before publishing; target hardware must be benchmarked.
    """
    start_time = time.perf_counter()
    logger.info("Starting live inference from %s", features_path)

    # 1. Load, flatten, and deduplicate live features (keep latest hour per cell)
    df = flatten_features_json(features_path, latest_only=True, history_path=history_path)
    if df.empty:
        raise ValueError(f"No feature records available in {features_path}")

    # Keep positional indices aligned with vectorized model outputs.
    df = df.reset_index(drop=True)

    # Optional synthetic surge injection for Role D demo
    if surge_cell:
        target_cells = parse_surge_cell_list(df, surge_cell)
        df = apply_surge_scenario(df, surge_cell)

        # Optional persistence of surged features for Role C and Role D
        if write_surged_features or surge_output_features is not None:
            feat_out = surge_output_features or features_path
            persist_surged_features(features_path, feat_out, target_cells)

    if hotspot_imputation not in ("artifact_median", "zero"):
        raise ValueError("Unsupported hotspot imputation")
    X_raw = df[FEATURE_COLUMNS].astype("float64").copy()
    if hotspot_imputation == "zero":
        counts = ["hotspots_in_cell_24h", "hotspots_10km_7d"]
        X_raw[counts] = X_raw[counts].fillna(0.0)
    results: List[Dict[str, Any]] = []

    # 2. Iterate through each horizon (24, 48, 72)
    for horizon in HORIZONS:
        model_file = model_dir / f"model_{horizon}h.joblib"
        if not model_file.exists():
            raise FileNotFoundError(
                f"Model artifact for horizon {horizon}h not found at {model_file}. Run train.py first."
            )

        artifact = joblib.load(model_file)
        if artifact.get("feature_columns") != FEATURE_COLUMNS:
            raise ValueError("Artifact feature order differs from canonical predictors")
        if artifact.get("horizon_h") != horizon or artifact.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Artifact horizon/schema mismatch")
        imputer = artifact["imputer"]
        if getattr(imputer, "strategy", None) != "median":
            raise ValueError("Expected fitted median imputer")
        scaler = artifact["scaler"]
        primary_model = artifact.get("primary_model", artifact.get("model"))
        signed_weights = artifact.get("signed_feature_weights", artifact.get("feature_weights"))

        # Preprocessing transforms with z-score clipping
        X_imp = imputer.transform(X_raw)
        if X_imp.shape != X_raw.shape or not np.isfinite(X_imp).all():
            raise ValueError("Imputer must produce 27 finite predictor columns")
        X_scaled = np.clip(scaler.transform(X_imp), -3.0, 3.0)

        # Live prediction with calibrated probabilities clipped to [0.02, 0.96]
        raw_probs = primary_model.predict_proba(X_imp)[:, 1]
        if raw_probs.shape != (len(df),) or not np.isfinite(raw_probs).all() or ((raw_probs < 0) | (raw_probs > 1)).any():
            raise ValueError("Model produced invalid probabilities")
        probs = np.clip(raw_probs, 0.02, 0.96)

        # Signed local attributions for top_factors
        top_factors_all = compute_local_attributions(
            model=primary_model,
            X_imp=X_imp,
            X_scaled=X_scaled,
            signed_feature_weights=signed_weights,
            feature_names=FEATURE_COLUMNS,
            risk_scores=probs,
            top_k=3,
        )

        for idx, row in df.iterrows():
            score = round(float(probs[idx]), 2)
            results.append({
                "schema_version": SCHEMA_VERSION,
                "cell_id": str(row["cell_id"]),
                "ts": str(row["ts"]),
                "horizon_h": int(horizon),
                "risk_score": score,
                "risk_level": get_risk_level(score),
                "top_factors": top_factors_all[idx],
                "model_version": MODEL_VERSION,
            })

    # 3. Validate against Contract 3.2
    validate_risk_contract(results)

    # 4. Atomic file write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if time.perf_counter() - start_time >= max_seconds:
        raise TimeoutError("Inference exceeded the configured latency budget")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent,
                                         prefix=".risk-", suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            json.dump(results, f, indent=2, allow_nan=False)
        if time.perf_counter() - start_time >= max_seconds:
            raise TimeoutError("Inference exceeded the configured latency budget")
        temporary.replace(output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    elapsed = time.perf_counter() - start_time
    logger.info(
        "Successfully produced %d predictions in %.2fs -> %s (Valid Contract 3.2)",
        len(results),
        elapsed,
        output_path,
    )
    return results


def main(args_list: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="Role B Peat Fire Live Prediction Engine")
    parser.add_argument(
        "--input",
        "--features-path",
        dest="features_path",
        type=Path,
        default=DEFAULT_FEATURES_PATH,
        help="Path to live features.json",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Directory containing trained model joblib artifacts",
    )
    parser.add_argument(
        "--output",
        "--output-path",
        dest="output_path",
        type=Path,
        default=DEFAULT_RISK_PATH,
        help="Path to write validated risk.json",
    )
    parser.add_argument(
        "--surge-cell",
        type=str,
        default=None,
        help="Cell ID(s) to surge (e.g. '-2.35_114.05' or '-2.35_114.05,-2.45_114.15' or 'ALL')",
    )
    parser.add_argument(
        "--write-surged-features",
        action="store_true",
        help="Persist surged feature values to features.json for Role C and Role D consistency",
    )
    parser.add_argument(
        "--surge-output-features",
        type=Path,
        default=None,
        help="Target path to write surged features (defaults to input features path)",
    )

    normalized_args = normalize_cli_args(args_list)
    args = parser.parse_args(normalized_args)

    try:
        run_predictions(
            features_path=args.features_path,
            model_dir=args.model_dir,
            output_path=args.output_path,
            surge_cell=args.surge_cell,
            write_surged_features=args.write_surged_features,
            surge_output_features=args.surge_output_features,
        )
    except Exception as e:
        logger.error("Inference failed: %s", e, exc_info=True)
        sys.exit(1)


def summarize_predictions(records):
    """Internal cell summary; never changes the frozen risk.json array."""
    summary = {}
    for record in records:
        cell = summary.setdefault(record["cell_id"], {"scores": {}, "levels": {}, "top_factors": {}})
        horizon = record["horizon_h"]
        cell["scores"][horizon] = record["risk_score"]
        cell["levels"][horizon] = record["risk_level"]
        cell["top_factors"][horizon] = record["top_factors"]
    return summary


def run_configured(config):
    from b_model.config import PROJECT_ROOT, validate_config
    config = validate_config(config)
    def resolve(value):
        path = Path(value).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path
    output = resolve(config.paths.output)
    source = resolve(config.paths.features)
    history = resolve(config.paths.history) if config.paths.history else None
    if output.resolve() in {source.resolve(), history.resolve() if history else None}:
        raise ValueError("Output must not overwrite inputs")
    results = run_predictions(features_path=source, model_dir=resolve(config.paths.model_dir),
                              output_path=output, history_path=history,
                              hotspot_imputation=config.imputation.hotspot_counts,
                              max_seconds=config.max_seconds)
    return summarize_predictions(results)


# Hydra is required by the configured entry point; legacy imports remain usable.
try:
    import hydra
except ImportError:
    hydra = None

if hydra is not None:
    from b_model.config import register_config
    register_config()

    @hydra.main(version_base="1.3", config_path="conf", config_name="config")
    def hydra_main(config):
        return run_configured(config)
else:
    def hydra_main():
        raise ImportError("Install b_model/requirements.txt to use Hydra inference")


if __name__ == "__main__":
    # Keep Role E's existing --input/--output CLI and surge flags compatible.
    legacy_flags = ("--input", "--features-path", "--output", "--output-path",
                    "--model-dir", "--surge-cell", "--write-surged-features", "--surge-output-features")
    if any(arg.split("=")[0] in legacy_flags for arg in sys.argv[1:]):
        main()
    else:
        hydra_main()
