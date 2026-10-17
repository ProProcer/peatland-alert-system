"""Export exact-value CSV history and reproduce frozen regional LR training.

Export on a machine that can read the original Parquet. Train on LinuxONE with
the resulting CSV and manifest. Existing Role A/B files remain read-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import struct
import time

ROOT = Path(__file__).resolve().parents[1]


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def value_sha(frame) -> str:
    """Hash column order, dtypes, missing masks and endian-independent values."""
    import numpy as np
    import pandas as pd

    digest = hashlib.sha256()
    digest.update(struct.pack("<Q", len(frame)))
    for name in frame:
        series = frame[name]
        descriptor = json.dumps([name, str(series.dtype)], ensure_ascii=True)
        digest.update(descriptor.encode() + b"\n")
        mask = series.isna().to_numpy(dtype=bool)
        digest.update(mask.astype("u1").tobytes())
        if pd.api.types.is_integer_dtype(series.dtype):
            digest.update(np.asarray(series.fillna(0), dtype="<i8").tobytes())
        elif pd.api.types.is_float_dtype(series.dtype):
            digest.update(np.asarray(series.fillna(0), dtype="<f8").tobytes())
        elif series.dtype == object:
            for item, missing in zip(series, mask):
                if not missing and (not isinstance(item, str) or not item):
                    raise ValueError("Portable text columns require nonempty strings")
                encoded = b"" if missing else item.encode("utf-8")
                digest.update(struct.pack("<Q", len(encoded)))
                digest.update(encoded)
        else:
            raise ValueError(f"Unsupported portable dtype: {name}: {series.dtype}")
    return digest.hexdigest()


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")


def read_portable(directory: Path):
    import pandas as pd

    manifest = json.loads((directory / "history-manifest.json").read_text())
    source = directory / "history.csv.gz"
    if file_sha(source) != manifest["csv_gzip_sha256"]:
        raise ValueError("CSV file fingerprint mismatch")
    frame = pd.read_csv(source, dtype=manifest["dtypes"], float_precision="round_trip",
                        keep_default_na=False, na_values=[""])
    if list(frame) != manifest["columns"] or len(frame) != manifest["rows"]:
        raise ValueError("Portable history shape differs from original")
    if value_sha(frame) != manifest["values_sha256"]:
        raise ValueError("Decoded values/dtypes/nulls differ from the original Parquet")
    return frame, manifest


def new_directory(path: Path) -> None:
    path = path.resolve()
    if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / "data/demo"):
        raise ValueError("Use a temporary path, data/demo, or /workspace/outputs")
    path.mkdir(parents=True, exist_ok=False)


def export(output: Path) -> None:
    import pandas as pd

    handoff = json.loads((ROOT / "b_model/CURRENT_HANDOFF.json").read_text())
    source = ROOT / handoff["history"]
    original_sha = file_sha(source)
    if original_sha != handoff["source_fingerprints"]["history.parquet"]:
        raise ValueError("Original Parquet differs from the frozen handoff")
    frame = pd.read_parquet(source)
    new_directory(output)
    csv = output / "history.csv.gz"
    frame.to_csv(csv, index=False, float_format="%.17g",
                 compression={"method": "gzip", "mtime": 0})
    manifest = {
        "source_parquet": handoff["history"], "source_parquet_sha256": original_sha,
        "rows": len(frame), "columns": list(frame),
        "dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
        "csv_gzip_sha256": file_sha(csv), "values_sha256": value_sha(frame),
        "meaning": "Exact-value transport copy; no feature, label or split changes.",
    }
    write_json(output / "history-manifest.json", manifest)
    restored, _ = read_portable(output)
    pd.testing.assert_frame_equal(frame, restored, check_exact=True)
    if file_sha(source) != original_sha:
        raise ValueError("Original history changed during export")
    print(f"Verified exact CSV round trip: {len(frame)} rows, {len(frame.columns)} columns", flush=True)
    print(f"Transfer folder: {output.resolve()}", flush=True)


def train(bundle: Path, output: Path) -> None:
    started = time.perf_counter()
    import resource
    import numpy as np
    import pandas as pd
    from omegaconf import OmegaConf
    from b_model.config import FEATURE_COLUMNS, HORIZONS
    from b_model.experiment import (calibrate, export_bundle, fit_model,
        partition_summary, prepare, probability_metrics, split_window)
    from b_model.train import compute_directional_feature_signs
    from b_model.predict import run_predictions
    from b_model.quality import assess_saved_metrics
    from contracts.validate import validate_file

    handoff = json.loads((ROOT / "b_model/CURRENT_HANDOFF.json").read_text())
    frame, source = read_portable(bundle)
    if source["source_parquet_sha256"] != handoff["source_fingerprints"]["history.parquet"]:
        raise ValueError("Portable history does not belong to the current handoff")
    if file_sha(ROOT / handoff["history"]) != source["source_parquet_sha256"]:
        raise ValueError("Local original Parquet fingerprint differs from handoff")
    plan = OmegaConf.to_container(OmegaConf.load(ROOT / "b_model/conf/backtest_regional.yaml"), resolve=True)
    window = plan["windows"][-1]
    if window["name"] != "final_2026" or plan["embargo_hours"] < 72:
        raise ValueError("Expected frozen final regional window and 72-hour gaps")
    train_end, cs, ce, vs, ve = [pd.Timestamp(window[key]) for key in
        ["train_end", "calibration_start", "calibration_end", "validation_start", "validation_end"]]
    gap = pd.Timedelta(hours=plan["embargo_hours"])
    if not train_end <= cs < ce <= vs < ve or cs - train_end < gap or vs - ce < gap:
        raise ValueError("Invalid frozen chronological partitions")
    labels = [f"target_{h}h" for h in HORIZONS]
    required = {"cell_id", "ts", *FEATURE_COLUMNS, *labels}
    if not required.issubset(frame) or frame.duplicated(["cell_id", "ts"]).any():
        raise ValueError("Missing training columns or duplicate cell/hour records")
    if not frame.ts.map(lambda value: isinstance(value, str) and value.endswith("Z")).all():
        raise ValueError("History timestamps must be UTC with Z")
    values = frame[FEATURE_COLUMNS].to_numpy(dtype=float, na_value=np.nan)
    if np.isinf(values).any() or (values == -999).any():
        raise ValueError("Invalid numeric predictor values")
    del values
    if not frame[labels].stack().isin([0, 1]).all():
        raise ValueError("Labels must be 0/1 or missing")
    frame["_time"] = pd.to_datetime(frame.ts, utc=True, errors="raise")
    complete = frame.dropna(subset=labels).sort_values(["ts", "cell_id"]).reset_index(drop=True)
    excluded = len(frame) - len(complete)
    del frame
    selected = json.loads((ROOT / "b_model/experiment_results/20261017_regional_40/selection.json").read_text())
    if selected["frozen_before"] != "final_2026":
        raise ValueError("Expected pre-final frozen backend selection")
    if any(selected["selected"][str(h)]["spec"]["backend"] != "logistic_regression" for h in HORIZONS):
        raise ValueError("This runner reproduces the selected logistic models only")
    parts = split_window(complete, window)
    new_directory(output)
    models = output / "models"
    models.mkdir()
    OmegaConf.save(OmegaConf.create(plan), output / "original-protocol.yaml")
    write_json(output / "source-manifest.json", source)
    write_json(output / "partitions.json", partition_summary(parts))
    imputer, scaler, arrays = prepare(parts)
    del complete
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_version = "v1-linuxone-reproduction-" + run_id
    metadata = {
        "run_id_utc": run_id, "architecture": platform.machine(),
        "scope": "Frozen regional LR models and dryness baselines; final historical window only",
        "source_parquet_sha256": source["source_parquet_sha256"],
        "values_sha256": source["values_sha256"], "portable_value_check": "passed",
        "rows_with_incomplete_labels_excluded": excluded,
        "libraries": {name: version(name) for name in ["numpy", "pandas", "scipy", "scikit-learn", "joblib"]},
        "evaluation_note": "Retrospective reproduction, not a new independent test or automatic promotion.",
    }
    metrics = {"schema_version": "1.0", "model_version": model_version, "horizons": {}}
    manifest = {"schema_version": "1.0", "models": {}}
    for h in HORIZONS:
        begin = time.perf_counter()
        ys = {key: part[f"target_{h}h"].to_numpy(dtype=int) for key, part in parts.items()}
        spec = {"backend": "logistic_regression", "c": plan["logistic_c"][str(h)]}
        base = fit_model(spec, plan["seed"], arrays["primary"]["train"], ys["train"])
        fitted = calibrate(base, arrays["primary"]["calibration"], ys["calibration"], h, "sigmoid")
        scores = fitted.predict_proba(arrays["primary"]["validation"])[:, 1]
        actual = probability_metrics(ys["validation"], scores)
        baseline = fit_model({"backend": "dryness_baseline", "c": 1.0}, plan["seed"],
                             arrays["baseline"]["train"], ys["train"])
        baseline = calibrate(baseline, arrays["baseline"]["calibration"], ys["calibration"], h, "sigmoid")
        baseline_metrics = probability_metrics(ys["validation"], baseline.predict_proba(arrays["baseline"]["validation"])[:, 1])
        signs = compute_directional_feature_signs(arrays["primary"]["train"], ys["train"], FEATURE_COLUMNS)
        export_bundle(models, h, spec, "sigmoid", base, fitted, imputer, scaler,
                      arrays["primary"]["calibration"], ys["calibration"],
                      {"seed": plan["seed"], "model_version": model_version,
                       "feature_signs": signs.tolist(), "training_data": metadata})
        manifest["models"][str(h)] = {"filename": f"model_{h}h.joblib", "format": "joblib",
            "model_version": model_version, "feature_order": FEATURE_COLUMNS, "positive_class": 1}
        cutoff = actual["thresholds"]["0.50"]
        metrics["horizons"][str(h)] = {"model_backend": "logistic_regression",
            "pr_auc": actual["pr_auc"], "baseline_pr_auc": baseline_metrics["pr_auc"],
            "precision": cutoff["precision"], "recall": cutoff["recall"],
            "classification_threshold": 0.5, "metrics": actual, "baseline_metrics": baseline_metrics,
            "fit_calibrate_evaluate_export_seconds": time.perf_counter() - begin}
        write_json(output / "metrics.json", metrics)
        print(f"{h}h trained: AP={actual['pr_auc']:.6f}, baseline AP={baseline_metrics['pr_auc']:.6f}", flush=True)
    write_json(models / "artifact_manifest.json", manifest)
    write_json(output / "quality_gate.json", assess_saved_metrics(metrics))
    risk = output / "risk.json"
    run_predictions(features_path=ROOT / handoff["features"], model_dir=models,
                    output_path=risk, history_path=None)
    predictions = validate_file("risk", risk)
    metadata.update({"completed_forecast_models": 3, "completed_baseline_fits": 3,
        "prediction_count": len(predictions), "cell_count": len({r["cell_id"] for r in predictions}),
        "schema_validation": "passed", "wall_seconds_including_data_loading": time.perf_counter() - started,
        "peak_process_memory_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "artifacts_sha256": {p.name: file_sha(p) for p in models.glob("*.joblib")}})
    write_json(output / "training-report.json", metadata)
    print(json.dumps(metadata, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("--output", type=Path, required=True)
    trainer = commands.add_parser("train")
    trainer.add_argument("--bundle", type=Path, required=True)
    trainer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        export(args.output)
    else:
        train(args.bundle, args.output)


if __name__ == "__main__":
    main()
