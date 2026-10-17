"""
Live prediction engine for Role B (ML Lead).
Consumes /data/processed/features.json (Contract 3.1).
Outputs /data/processed/risk.json (Contract 3.2).
Includes deduplication of multi-hour inputs, signed directional feature attribution,
robust negative cell_id parsing, multi-cell surge injection, and separate demo-feature output.
Hardware compatibility and latency require verification on the deployment target.
"""

import argparse
import tempfile
import pickle
import copy
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
    DEFAULT_HISTORY_PATH,
    DEFAULT_MODEL_DIR,
    DEFAULT_RISK_PATH,
    FEATURE_COLUMNS,
    HORIZONS,
    SCHEMA_VERSION,
    get_risk_level,
    setup_logger,
)
from b_model.features import flatten_features_json, _unique_keys, _invalid_constant, validate_feature_record

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
    """Rank exact signed weight * standardized feature values by absolute magnitude.

    These are directional heuristic contributions, not SHAP or calibrated log odds.
    No signs, magnitudes or extra factors are fabricated for any risk category.
    """
    values = np.asarray(X_scaled, dtype=float)
    weights = np.asarray(signed_feature_weights, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(feature_names) or weights.shape != (len(feature_names),):
        raise ValueError("Attribution feature/weight dimensions do not match")
    if not np.isfinite(values).all() or not np.isfinite(weights).all():
        raise ValueError("Attribution inputs must be finite")
    if type(top_k) is not int or not 1 <= top_k <= len(feature_names):
        raise ValueError("Invalid top_k")
    with np.errstate(over="raise", invalid="raise"):
        contributions = values * weights
    indices = np.argsort(-np.abs(contributions), axis=1, kind="stable")[:, :top_k]
    return [[{"feature": feature_names[index], "contribution": float(row[index])}
             for index in order] for row, order in zip(contributions, indices)]


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
            raise ValueError(f"Unknown surge cell: {cell_id}")
        s_idx = match_indices

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


def build_demo_features(input_features_path: Path, target_cells: List[str]):
    """Build a separate demo feed using the same transformation as inference."""
    data = json.loads(input_features_path.read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
    original = flatten_features_json(input_features_path, latest_only=False)
    transformed = apply_surge_scenario(original, ",".join(target_cells))
    rows = {(row["cell_id"], row["ts"]): row for row in transformed.to_dict("records")}
    result = copy.deepcopy(data)
    from b_model.config import FEATURE_GROUPS
    for index, record in enumerate(result):
        if record["cell_id"] in target_cells:
            row = rows[(record["cell_id"], record["ts"])]
            for group, columns in FEATURE_GROUPS.items():
                for column in columns:
                    value = row[column]
                    record[group][column] = None if pd.isna(value) else value
        validate_feature_record(record, index)
    return result


def atomic_write_json(payload, output_path: Path, deadline=None):
    """Serialize beside the destination; failures preserve the previous complete file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent,
                                         prefix=".risk-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, allow_nan=False)
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError("Inference exceeded the configured latency budget")
        temporary.replace(output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_artifact_manifest(model_dir: Path):
    """Validate an explicit PIC 2 handoff before loading any executable artifacts.

    Joblib and pickle files must originate from the trusted training pipeline.
    The manifest constrains file locations and metadata, not pickle execution.
    """
    model_dir = Path(model_dir).resolve()
    manifest_path = model_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Invalid artifact manifest schema_version")
    entries = manifest.get("models")
    if not isinstance(entries, dict) or set(entries) != {str(h) for h in HORIZONS}:
        raise ValueError("Manifest requires exactly 24, 48 and 72 hour entries")
    validated = {}
    for horizon in HORIZONS:
        entry = entries[str(horizon)]
        if not isinstance(entry, dict) or not {"filename", "format", "model_version", "feature_order"} <= entry.keys():
            raise ValueError(f"Incomplete manifest for horizon {horizon}")
        filename = entry["filename"]
        if not isinstance(filename, str) or not filename:
            raise ValueError("Artifact filename must be nonempty")
        path = (model_dir / filename).resolve()
        if not path.is_relative_to(model_dir) or path == manifest_path:
            raise ValueError("Artifact path must remain inside the model directory")
        if entry["format"] not in ("joblib", "pickle"):
            raise ValueError("Artifact format must be joblib or pickle")
        if not isinstance(entry["model_version"], str) or not entry["model_version"]:
            raise ValueError("Artifact model_version must be nonempty")
        order = entry["feature_order"]
        if not isinstance(order, list) or any(not isinstance(c, str) for c in order) or len(order) != len(FEATURE_COLUMNS) or set(order) != set(FEATURE_COLUMNS):
            raise ValueError("Manifest feature_order must contain each canonical predictor exactly once")
        if type(entry.get("positive_class", 1)) is not int or entry.get("positive_class", 1) != 1:
            raise ValueError("The hotspot target positive_class must be 1")
        if not path.is_file():
            raise FileNotFoundError(path)
        validated[horizon] = (entry, path)
    return validated


def validate_output_paths(inputs, outputs, model_dir):
    """Every public inference entry point shares collision and artifact protection."""
    sources = {Path(p).resolve() for p in inputs if p is not None}
    destinations = [Path(p).resolve() for p in outputs if p is not None]
    if len(destinations) != len(set(destinations)):
        raise ValueError("Output paths must be distinct")
    for destination in destinations:
        if destination in sources or any(destination.exists() and source.exists() and destination.samefile(source) for source in sources):
            raise ValueError("Output must not overwrite inputs")
        if destination.is_relative_to(Path(model_dir).resolve()):
            raise ValueError("Output must not overwrite model artifacts")


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
    history_path: Optional[Path] = DEFAULT_HISTORY_PATH,
    hotspot_imputation: str = "artifact_median",
    max_seconds: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Executes live inference on features.json and writes contract-validated risk.json.
    Deduplicates multi-hour inputs: guarantees exactly 1 prediction per (cell_id, horizon_h).
    Optionally publishes a separate demo feed; source features are never mutated.
    Checks the latency budget before publishing; target hardware must be benchmarked.
    """
    start_time = time.perf_counter()
    features_path, model_dir, output_path = map(Path, (features_path, model_dir, output_path))
    if not 0 < max_seconds <= 60:
        raise ValueError("max_seconds must be in (0, 60]")
    if output_path.name != "risk.json":
        raise ValueError("Inference output filename must be risk.json")
    if write_surged_features and surge_output_features is None:
        raise ValueError("Demo persistence requires a separate demo_features_out path")
    if surge_output_features is not None and not surge_cell:
        raise ValueError("demo_features_out requires a surge_cell")
    validate_output_paths([features_path, history_path], [output_path, surge_output_features], model_dir)
    manifest = load_artifact_manifest(model_dir)
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

    if hotspot_imputation not in ("artifact_median", "zero"):
        raise ValueError("Unsupported hotspot imputation")
    X_raw = df[FEATURE_COLUMNS].astype("float64").copy()
    if hotspot_imputation == "zero":
        counts = ["hotspots_in_cell_24h", "hotspots_10km_7d"]
        X_raw[counts] = X_raw[counts].fillna(0.0)
    results: List[Dict[str, Any]] = []

    # 2. Iterate through each horizon (24, 48, 72)
    for horizon in HORIZONS:
        entry, model_file = manifest[horizon]
        order = entry["feature_order"]
        X_ordered = X_raw.loc[:, order]
        if X_ordered.columns.tolist() != order:
            raise ValueError("DataFrame does not match manifest feature_order")
        if entry["format"] == "joblib":
            artifact = joblib.load(model_file)
        else:
            with model_file.open("rb") as handle:
                artifact = pickle.load(handle)
        if not isinstance(artifact, dict):
            raise ValueError("Artifact must be a preprocessing/model bundle")
        if artifact.get("feature_columns") != order:
            raise ValueError("Artifact feature order differs from manifest")
        if artifact.get("horizon_h") != horizon or artifact.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Artifact horizon/schema mismatch")
        if artifact.get("model_version") != entry["model_version"]:
            raise ValueError("Artifact model_version differs from manifest")
        imputer = artifact["imputer"]
        if getattr(imputer, "strategy", None) != "median":
            raise ValueError("Expected fitted median imputer")
        scaler = artifact["scaler"]
        primary_model = artifact.get("primary_model", artifact.get("model"))
        signed_weights = artifact.get("signed_feature_weights", artifact.get("feature_weights"))

        # Reuse fitted preprocessing; attribution uses the exact standardized values.
        X_imp = imputer.transform(X_ordered)
        if X_imp.shape != X_raw.shape or not np.isfinite(X_imp).all() or (X_imp == -999).any():
            raise ValueError("Imputer must produce 27 finite predictor columns")
        X_scaled = scaler.transform(X_imp)

        # Use the calibrated model probability without rounding or clipping.
        classes = np.asarray(primary_model.classes_)
        positive = np.flatnonzero(classes == entry.get("positive_class", 1))
        if classes.shape != (2,) or len(positive) != 1 or set(classes.tolist()) != {0, 1}:
            raise ValueError("Model must expose binary classes 0 and 1")
        raw_probs = primary_model.predict_proba(X_imp)[:, int(positive[0])]
        if raw_probs.shape != (len(df),) or not np.isfinite(raw_probs).all() or ((raw_probs < 0) | (raw_probs > 1)).any():
            raise ValueError("Model produced invalid probabilities")
        probs = raw_probs

        # Signed local attributions for top_factors
        top_factors_all = compute_local_attributions(
            model=primary_model,
            X_imp=X_imp,
            X_scaled=X_scaled,
            signed_feature_weights=signed_weights,
            feature_names=order,
            risk_scores=probs,
            top_k=3,
        )

        for idx, row in df.iterrows():
            score = float(probs[idx])
            results.append({
                "schema_version": SCHEMA_VERSION,
                "cell_id": str(row["cell_id"]),
                "ts": str(row["ts"]),
                "horizon_h": int(horizon),
                "risk_score": score,
                "risk_level": get_risk_level(score),
                "top_factors": top_factors_all[idx],
                "model_version": entry["model_version"],
            })

    # 3. Validate against Contract 3.2
    validate_risk_contract(results)

    # Build/validate the demo payload before publishing any outputs. Inputs stay read-only.
    demo_payload = build_demo_features(features_path, target_cells) if surge_output_features is not None else None
    deadline = start_time + max_seconds
    if demo_payload is not None:
        atomic_write_json(demo_payload, Path(surge_output_features), deadline)
    atomic_write_json(results, output_path, deadline)

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
        default=None,
        help="Path to live features.json",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Directory containing trained model joblib artifacts",
    )
    parser.add_argument(
        "--output",
        "--output-path",
        dest="output_path",
        type=Path,
        default=None,
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
        help="Write a separate demo feature feed (requires --surge-output-features)",
    )
    parser.add_argument(
        "--surge-output-features",
        type=Path,
        default=None,
        help="Separate path to write demo features; must not equal an input or risk.json",
    )

    parser.add_argument("--history", type=Path, default=None)
    normalized_args = normalize_cli_args(args_list)
    args = parser.parse_args(normalized_args)

    try:
        if args.write_surged_features and args.surge_output_features is None:
            raise ValueError("--write-surged-features requires --surge-output-features")
        from b_model.config import load_inference_config
        from omegaconf import OmegaConf
        paths = {key: str(value) for key, value in {
            "features": args.features_path, "model_dir": args.model_dir,
            "history": args.history, "output": args.output_path,
            "demo_features_out": args.surge_output_features,
        }.items() if value is not None}
        overrides = {"paths": paths}
        if args.surge_cell is not None:
            overrides["surge_cell"] = args.surge_cell
        run_configured(OmegaConf.merge(load_inference_config(), overrides))
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
    results = run_predictions(features_path=source, model_dir=resolve(config.paths.model_dir),
                              output_path=output, history_path=history,
                              surge_cell=config.surge_cell,
                              surge_output_features=resolve(config.paths.demo_features_out) if config.paths.demo_features_out else None,
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
                    "--model-dir", "--history", "--surge-cell", "--write-surged-features", "--surge-output-features")
    if any(arg.split("=")[0] in legacy_flags for arg in sys.argv[1:]):
        main()
    else:
        hydra_main()
